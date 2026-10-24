"""The show's own chat posts (quiz/chatpost.py): tips and !friends replies through
liveChatMessages.insert, a hard daily budget, back-off, and our own messages never read back
as plays.

HTTP is faked with the documented shapes (read 2026-10-24):
  liveBroadcasts.list -> {"kind": "youtube#liveBroadcastListResponse", "items": [liveBroadcast]},
    snippet.liveChatId and snippet.channelId as in developers.google.com/youtube/v3/live/docs/liveBroadcasts
  liveChatMessages.insert: POST liveChat/messages?part=snippet with snippet.liveChatId, snippet.type
    textMessageEvent and snippet.textMessageDetails.messageText; returns a liveChatMessage resource;
    errors forbidden, liveChatDisabled, liveChatEnded (403), messageTextInvalid (400),
    liveChatNotFound (404), rateLimitExceeded
    (developers.google.com/youtube/v3/live/docs/liveChatMessages/insert)
  error bodies: the Google JSON error format the existing ytapi fakes use.
"""

import json
import queue
import threading
import time
from urllib.parse import urlparse

import pytest

import quiz.chat as chat_mod
from quiz import chatpost, ytapi
from quiz.chat import ChatManager
from quiz.chatpost import ChatPoster, FriendsReplies, TipTicker
from tests.test_ytapi import _Clock, _Resp, _error

CHANNEL = "UCnv51D67E_oLPfHmQU_6prw"
CHAT_ID = "KicKGFVDbnY1MUQ2N0VfvExQbVF1N"


class FakeLiveChatAPI:
    """liveBroadcasts.list by id and liveChatMessages.insert, as documented."""

    def __init__(self):
        self.calls = []
        self.errors = []          # (status, reason) answered to the next inserts, in order
        self.hang = 0.0
        self.chat_ids = {"vid-1": CHAT_ID, "vid-2": CHAT_ID + "2"}

    def inserts(self):
        return [c for c in self.calls if c[1] == "liveChat/messages"]

    def lists(self):
        return [c for c in self.calls if c[1] == "liveBroadcasts"]

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        if self.hang:
            time.sleep(self.hang)
        path = urlparse(url).path.replace("/youtube/v3/", "")
        self.calls.append((method, path, dict(params or {}), json))
        if method == "GET" and path == "liveBroadcasts":
            vid = params["id"]
            items = [{"kind": "youtube#liveBroadcast", "id": vid, "snippet": {
                "publishedAt": "2026-10-24T18:00:00Z", "channelId": CHANNEL, "title": "The Lifelong Quiz",
                "liveChatId": self.chat_ids[vid]}}] if vid in self.chat_ids else []
            return _Resp(200, {"kind": "youtube#liveBroadcastListResponse", "items": items})
        if method == "POST" and path == "liveChat/messages":
            if self.errors:
                status, reason = self.errors.pop(0)
                return _error(status, reason)
            sn = json["snippet"]
            return _Resp(200, {"kind": "youtube#liveChatMessage", "id": f"m{len(self.calls)}", "snippet": {
                "type": "textMessageEvent", "liveChatId": sn["liveChatId"], "authorChannelId": CHANNEL,
                "publishedAt": "2026-10-24T18:01:00Z", "hasDisplayContent": True,
                "displayMessage": sn["textMessageDetails"]["messageText"],
                "textMessageDetails": {"messageText": sn["textMessageDetails"]["messageText"]}}})
        return _error(400, "unknownRoute")


@pytest.fixture
def poster(tmp_path):
    (tmp_path / "client.json").write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "cs"}}))
    clock = _Clock()
    (tmp_path / "token.json").write_text(json.dumps(
        {"access_token": "at-0", "refresh_token": "refresh-secret", "expiry": clock.t + 1e9}))
    fake, logs, channels = FakeLiveChatAPI(), [], []
    api = ytapi.YouTubeAPI("key", client_file=tmp_path / "client.json", token_file=tmp_path / "token.json",
                           http=fake, clock=clock, log=logs.append)
    p = ChatPoster(api, clock=clock, log=logs.append, on_channel=channels.append)
    return p, fake, logs, clock, channels


# ---- posting -------------------------------------------------------------------------------
def test_a_post_goes_to_the_broadcasts_live_chat_as_documented(poster):
    p, fake, logs, clock, channels = poster
    assert not p.ready and p.send("hello", "tip") is False and fake.calls == []   # no video yet: no calls
    assert p.post("hello") is False and p.pending == 0                           # nothing even queued
    p.set_video("vid-1")
    assert p.send("hello", "tip") and p.send("again", "reply")
    assert len(fake.lists()) == 1                                     # the chat id is resolved once
    method, path, params, body = fake.inserts()[0]
    assert (method, params) == ("POST", {"part": "snippet"})
    assert body == {"snippet": {"liveChatId": CHAT_ID, "type": "textMessageEvent",
                                "textMessageDetails": {"messageText": "hello"}}}
    assert channels == [CHANNEL]                                      # the chat reader learns who we are
    assert p.used == chatpost.LIST_COST + 2 * chatpost.INSERT_COST
    p.set_video("vid-2")                                              # a new broadcast: a new chat
    p.send("third", "tip")
    assert fake.inserts()[-1][3]["snippet"]["liveChatId"] == CHAT_ID + "2" and len(fake.lists()) == 2


def test_long_texts_are_cut_to_200_characters(poster):
    p, fake, *_ = poster
    p.set_video("vid-1")
    p.send("x" * 500, "reply")
    assert len(fake.inserts()[0][3]["snippet"]["textMessageDetails"]["messageText"]) == chatpost.MAX_LEN == 200


def test_the_daily_budget_is_hard_keeps_room_for_replies_and_resets_at_pacific_midnight(poster):
    p, fake, logs, clock, _ = poster
    clock.t = 1_792_800_000.0          # 2026-10-24 00:00 UTC = 17:00 PDT on the 23rd
    p.set_video("vid-1")
    tips = next(n for n in range(1000) if not p.send("tip", "tip"))        # bounded: a broken budget fails, not hangs
    assert p.used <= chatpost.POST_BUDGET - chatpost.REPLY_RESERVE
    replies = next(n for n in range(1000) if not p.send("reply", "reply"))
    sent = tips + replies
    assert p.used <= chatpost.POST_BUDGET <= chatpost.DAILY_QUOTA - 5_000
    assert sent == (chatpost.POST_BUDGET - chatpost.LIST_COST) // chatpost.INSERT_COST
    calls = len(fake.calls)
    assert p.send("over", "reply") is False and len(fake.calls) == calls   # over budget: dropped, no call
    clock.t += 7 * 3600 + 1            # 07:00 UTC = 00:00 PDT: YouTube's quota day starts again
    assert p.send("new day", "reply")


def test_quota_exceeded_stops_posting_until_youtubes_next_day(poster):
    p, fake, logs, clock, _ = poster
    clock.t = 1_792_800_000.0          # 17:00 PDT
    p.set_video("vid-1")
    fake.errors = [(403, "quotaExceeded")]
    assert p.send("a", "tip") is False
    calls = len(fake.calls)
    clock.t += 3 * 3600                # the API's own pause is over, but the day is not
    assert p.send("b", "reply") is False and len(fake.calls) == calls and not p.ready
    clock.t += 5 * 3600 + 1            # past midnight PT
    assert p.send("c", "reply")


@pytest.mark.parametrize("reason,status,retry", [
    ("rateLimitExceeded", 403, ChatPoster.RATE_PAUSE),
    ("forbidden", 403, ChatPoster.FORBIDDEN_PAUSE),
    ("liveChatDisabled", 403, ChatPoster.CHAT_RETRY),
    ("liveChatNotFound", 404, ChatPoster.CHAT_RETRY),
])
def test_errors_back_off_before_the_next_call(poster, reason, status, retry):
    p, fake, logs, clock, _ = poster
    p.set_video("vid-1")
    fake.errors = [(status, reason)]
    assert p.send("a", "tip") is False
    calls = len(fake.calls)
    clock.t += retry - 1
    assert p.send("b", "tip") is False and len(fake.calls) == calls
    clock.t += 2
    assert p.send("c", "tip")
    assert any(reason in line for line in logs)


def test_rate_limits_back_off_longer_each_time(poster):
    p, fake, logs, clock, _ = poster
    p.set_video("vid-1")
    fake.errors = [(403, "rateLimitExceeded")] * 2
    p.send("a", "tip")
    clock.t += ChatPoster.RATE_PAUSE + 1
    p.send("b", "tip")
    clock.t += ChatPoster.RATE_PAUSE + 1
    calls = len(fake.calls)
    assert p.send("c", "tip") is False and len(fake.calls) == calls      # the second pause is twice as long


def test_an_ended_chat_is_not_posted_to_again_until_the_video_changes(poster):
    p, fake, logs, clock, _ = poster
    p.set_video("vid-1")
    fake.errors = [(403, "liveChatEnded")]
    assert p.send("a", "tip") is False
    clock.t += 86_400 * 2
    calls = len(fake.calls)
    assert p.send("b", "tip") is False and len(fake.calls) == calls
    p.set_video("vid-2")
    assert p.send("c", "tip")


def test_a_bad_text_is_dropped_without_a_pause(poster):
    p, fake, *_ = poster
    p.set_video("vid-1")
    fake.errors = [(400, "messageTextInvalid")]
    assert p.send("a", "reply") is False
    assert p.send("b", "reply")


def test_the_thread_never_blocks_the_caller_and_never_dies(poster):
    p, fake, logs, clock, _ = poster
    p.set_video("vid-1")
    fake.hang = 0.5                    # YouTube is slow
    p.start()
    try:
        t0 = time.perf_counter()
        for i in range(20):            # far more than the queue holds: extra ones are dropped
            p.post(f"m{i}", "reply")
        assert time.perf_counter() - t0 < 0.05
        assert 0 < p.pending <= ChatPoster.QUEUE_MAX + 1               # one in flight, the queue full
        fake.hang = 0.0
        deadline = time.monotonic() + 10
        while p.pending and time.monotonic() < deadline:
            time.sleep(0.02)
        fake.request = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("network down"))
        assert p.post("boom", "reply")
        while p.pending and time.monotonic() < deadline:
            time.sleep(0.02)
        assert p._thread.is_alive() and not p.ready                    # alive, and pausing after the error
    finally:
        p.stop()
    assert any("network down" in line for line in logs)


def test_no_token_means_no_poster_and_todays_behaviour(tmp_path, monkeypatch):
    import quiz.controller as controller
    monkeypatch.setattr(controller, "STREAM_ENABLED", True)
    monkeypatch.setattr(controller, "YOUTUBE_STREAM_KEY", "key")
    monkeypatch.setenv("QUIZ_YT_TOKEN", str(tmp_path / "youtube_token.json"))
    g = controller.MainGameController.__new__(controller.MainGameController)
    g.youtube = g._make_youtube(offline=False)
    assert g.youtube is None and g._make_poster() is None
    g.poster = None
    g._chat_out()                       # the loop step does nothing


def test_no_secrets_in_logs(poster):
    p, fake, logs, clock, _ = poster
    p.set_video("vid-1")
    fake.errors = [(403, "forbidden")]
    p.send("a", "tip")
    assert not any("refresh-secret" in line or "at-0" in line for line in logs)


# ---- !friends replies ----------------------------------------------------------------------
def test_friends_replies_are_batched_with_a_per_user_cooldown():
    r = FriendsReplies()
    lines = {"ann": "@ann friends all-time: bo 10 pts #4", "bo": "@bo friends all-time: ann 9 pts #5",
             "cy": "@cy no friends yet: type !friend @name"}
    assert r.ask("ann", now=0.0) and r.ask("bo", now=1.0)
    assert r.ask("ann", now=2.0) is False                        # already waiting
    assert r.take(now=5.0, line_for=lines.get) == ""             # not before the batch window
    text = r.take(now=r.BATCH, line_for=lines.get)
    assert text == lines["ann"] + " | " + lines["bo"]            # one combined message
    assert r.take(now=r.BATCH + 1, line_for=lines.get) == ""     # nothing new, and one per window
    assert r.ask("ann", now=r.BATCH + 2) is False                # per-user cooldown
    assert r.ask("ann", now=r.COOLDOWN + 1)


def test_a_batch_that_does_not_fit_in_200_characters_carries_over():
    r = FriendsReplies()
    lines = {f"u{i}": f"@u{i} friends all-time: " + "x" * 70 for i in range(4)}
    for u in lines:
        r.ask(u, now=0.0)
    first = r.take(now=r.BATCH, line_for=lines.get)
    assert len(first) <= 200 and first.count("@u") == 2
    second = r.take(now=2 * r.BATCH, line_for=lines.get)
    assert second.count("@u") == 2 and "@u2" in second


def test_the_waiting_list_is_capped():
    r = FriendsReplies()
    assert sum(r.ask(f"u{i}", now=0.0) for i in range(50)) == r.PENDING_MAX


# ---- tips ----------------------------------------------------------------------------------
def test_tips_rotate_every_interval_and_cover_the_social_commands():
    t = TipTicker(minutes=9, start=0)
    assert t.take(now=0.0) == ""                                  # never right at the start (restarts)
    assert t.take(now=9 * 60 - 1) == ""
    got = [t.take(now=9 * 60 * k) for k in range(1, len(chatpost.TIPS) + 1)]
    assert got == chatpost.TIPS
    text = " ".join(chatpost.TIPS)
    for cmd in ("!friend @", "!friends", "!duel @", "!accept", "!crew", "!team", "!half", "!double", "!rank", "!card"):
        assert cmd in text
    assert all(len(tip) <= 200 for tip in chatpost.TIPS)
    assert TipTicker(minutes=0).take(now=1e9) == ""                # QUIZ_CHAT_TIPS_MINUTES=0: off


def test_the_controller_posts_tips_and_replies_only_while_live(poster, monkeypatch):
    import quiz.controller as controller
    p, fake, logs, clock, _ = poster
    posted = []
    p.post = lambda text, kind="tip": posted.append((kind, text)) or True

    class _B:
        is_active = False

    class _Logic:
        def friends_line(self, u):
            return f"@{u} friends all-time: x 1 pts #1"
    g = controller.MainGameController.__new__(controller.MainGameController)
    g.poster, g.broadcaster, g.logic = p, _B(), _Logic()
    g.replies, g.tips = FriendsReplies(), TipTicker(minutes=9, start=0)
    g.replies.ask("ann", now=time.time() - 60)
    g.tips._next = 0.0
    g._chat_out()
    assert posted == []                                           # not streaming
    _B.is_active = True
    g._chat_out()
    assert posted == []                                           # streaming, but no broadcast yet
    p.set_video("vid-1")
    g._chat_out()
    assert ("reply", "@ann friends all-time: x 1 pts #1") in posted and posted[-1][0] == "tip"


# ---- our own messages ----------------------------------------------------------------------
def test_our_own_posts_coming_back_through_the_reader_are_ignored(monkeypatch):
    # authorExternalChannelId: present on every text message of a public live chat
    # (measured 2026-10-24, get_live_chat of a public stream; pytchat 0.5.5 reads the same key)
    from tests.test_ytchat import RECORDED
    from quiz.ytchat import parse_chat
    recorded = json.loads(json.dumps(RECORDED))
    items = [a["addChatItemAction"]["item"]["liveChatTextMessageRenderer"]
             for a in recorded["continuationContents"]["liveChatContinuation"]["actions"] if "addChatItemAction" in a]
    items[0]["authorExternalChannelId"] = CHANNEL                    # "@LifelongQuiz" posting as the channel
    items[1]["authorExternalChannelId"] = "UCviewer1xxxxxxxxxxxxxxx"
    items[2]["authorExternalChannelId"] = "UCviewer1xxxxxxxxxxxxxxx"
    messages, _, _ = parse_chat(recorded)
    assert [m[4] for m in messages] == [CHANNEL, "UCviewer1xxxxxxxxxxxxxxx", "UCviewer1xxxxxxxxxxxxxxx"]

    class FakeChat:
        def __init__(self, url, session=None):
            self.video_id, self.alive, self.done = "vid-1", True, False

        def open(self):
            return True

        def poll(self):
            if self.done:
                return [], 0.01
            self.done = True
            return [(a, t, s, c) for _, a, t, s, c in messages], 0.01
    monkeypatch.setattr(chat_mod, "LiveChat", FakeChat)
    q = queue.Queue()
    cm = ChatManager(["https://www.youtube.com/watch?v=vid-1"], q)
    cm.ignore_channel(CHANNEL)
    cm.start()
    got = []
    deadline = time.monotonic() + 3
    while len(got) < 2 and time.monotonic() < deadline:
        try:
            got.append(q.get(timeout=0.05))
        except queue.Empty:
            pass
    cm.stop()
    assert [m.username for m in got] == ["Viewer_1", "Viewer_1"]   # not LifelongQuiz
    assert q.empty()
