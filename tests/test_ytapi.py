"""YouTube broadcasts through the Data API: find our stream, reuse or create and bind a broadcast,
keep it live, end it on shutdown. HTTP is faked with the response shapes of the API reference
(developers.google.com/youtube/data/live/reference/rest/v3, read 2026-10-24)."""

import json
import os
import queue
import threading
import time
from urllib.parse import urlparse

import pytest

import quiz.chat as chat_mod
import quiz.controller as controller
from quiz import ytapi
from quiz.chat import ChatManager

KEY = "abcd-efgh-ijkl-mnop-qrst"
INGEST = "rtmp://a.rtmp.youtube.com/live2"
SECRETS = (KEY, INGEST, "refresh-secret", "at-")


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _error(status, reason, message="error"):
    return _Resp(status, {"error": {"code": status, "message": message,
                                    "errors": [{"reason": reason, "domain": "youtube.liveBroadcast"}]}})


class FakeYouTube:
    """Just enough of the API to replay its documented behaviour."""

    ACTIVE = ("live", "liveStarting", "testing", "testStarting")
    UPCOMING = ("created", "ready")

    def __init__(self):
        self.streams = [
            {"id": "S-other", "snippet": {"title": "Old key"}, "cdn": {"ingestionInfo": {
                "streamName": "zzzz-zzzz", "ingestionAddress": INGEST}}, "status": {
                "streamStatus": "inactive", "healthStatus": {"status": "noData"}}},
            {"id": "S-ours", "snippet": {"title": "Default stream key"}, "cdn": {"ingestionInfo": {
                "streamName": KEY, "ingestionAddress": INGEST}}, "status": {
                "streamStatus": "active", "healthStatus": {"status": "good"}}},
        ]
        self.broadcasts = {}
        self.calls = []
        self.auto_start = True        # enableAutoStart: live as soon as it is bound to an active stream
        self.refresh = "ok"           # or "invalid_grant"
        self.quota_left = 10_000
        self.hang = 0.0
        self.device_answers = []
        self._n = 0

    def add(self, bid, state, stream="S-ours"):
        self.broadcasts[bid] = {"id": bid, "snippet": {"title": "t"}, "status": {
            "lifeCycleStatus": state, "privacyStatus": "public"}, "contentDetails": {"boundStreamId": stream}}

    def posts(self, path):
        return [c for c in self.calls if c[0] in ("POST", "PUT") and c[1] == path]

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        if self.hang:
            time.sleep(self.hang)
        u = urlparse(url)
        params = params or {}
        if url == ytapi.DEVICE_CODE_URL:   # shapes from the limited-input-device guide
            self.calls.append((method, "device", data))
            return _Resp(200, {"device_code": "dev-code", "user_code": "GQVQ-JKEC",
                               "verification_url": "https://www.google.com/device",
                               "expires_in": 1800, "interval": 5})
        if url == ytapi.TOKEN_URL and data.get("grant_type", "").endswith("device_code"):
            self.calls.append((method, "device-token", data))
            if self.device_answers:
                return _Resp(428 if self.device_answers[0] == "authorization_pending" else 403,
                             {"error": self.device_answers.pop(0), "error_description": "wait"})
            return _Resp(200, {"access_token": "at-dev", "expires_in": 3599, "refresh_token": "refresh-secret",
                               "scope": ytapi.SCOPE, "token_type": "Bearer"})
        if url == ytapi.TOKEN_URL:
            self.calls.append((method, "token", data))
            if self.refresh == "invalid_grant":
                return _Resp(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            self._n += 1
            return _Resp(200, {"access_token": f"at-{self._n}", "expires_in": 3599,
                               "scope": ytapi.SCOPE, "token_type": "Bearer"})
        path = u.path.replace("/youtube/v3/", "")
        self.calls.append((method, path, dict(params), json, (headers or {}).get("Authorization")))
        if self.quota_left <= 0:
            return _error(403, "quotaExceeded", "The request cannot be completed because you have exceeded your quota.")
        self.quota_left -= 1
        if method == "GET" and path == "liveStreams":
            items = self.streams if params.get("mine") else [s for s in self.streams if s["id"] == params.get("id")]
            return _Resp(200, {"kind": "youtube#liveStreamListResponse", "items": items})
        if method == "GET" and path == "liveBroadcasts":
            if "id" in params:
                items = [b for b in self.broadcasts.values() if b["id"] == params["id"]]
            else:
                want = self.ACTIVE if params["broadcastStatus"] == "active" else self.UPCOMING
                items = [b for b in self.broadcasts.values() if b["status"]["lifeCycleStatus"] in want]
            return _Resp(200, {"kind": "youtube#liveBroadcastListResponse", "items": items})
        if method == "POST" and path == "liveBroadcasts":
            bid = f"B-new{len(self.broadcasts) + 1}"
            self.broadcasts[bid] = {**json, "id": bid}
            self.broadcasts[bid]["status"] = {**json["status"], "lifeCycleStatus": "created"}
            self.broadcasts[bid]["contentDetails"] = dict(json["contentDetails"])
            return _Resp(200, self.broadcasts[bid])
        if method == "POST" and path == "liveBroadcasts/bind":
            b = self.broadcasts[params["id"]]
            b["contentDetails"]["boundStreamId"] = params["streamId"]
            stream = next(s for s in self.streams if s["id"] == params["streamId"])
            live = self.auto_start and stream["status"]["streamStatus"] == "active"
            b["status"]["lifeCycleStatus"] = "live" if live else "ready"
            return _Resp(200, b)
        if method == "POST" and path == "liveBroadcasts/transition":
            b = self.broadcasts.get(params["id"])
            if b is None:
                return _error(404, "liveBroadcastNotFound")
            target = params["broadcastStatus"]
            if b["status"]["lifeCycleStatus"] == target:
                return _error(403, "redundantTransition")
            if target == "live" and b["status"]["lifeCycleStatus"] in ("created", "ready"):
                return _error(403, "invalidTransition")   # the quiz channel, 2026-10-24: testing first
            if target == "live":
                stream = next(s for s in self.streams if s["id"] == b["contentDetails"]["boundStreamId"])
                if stream["status"]["streamStatus"] != "active":
                    return _error(403, "errorStreamInactive")
            b["status"]["lifeCycleStatus"] = target
            return _Resp(200, b)
        if method == "PUT" and path == "videos":
            return _Resp(200, json)
        if method == "GET" and path == "channels":
            return _Resp(200, {"items": [{"id": "UC-quiz", "snippet": {"title": "The Lifelong Quiz"}}]})
        return _error(400, "unknownRoute")


@pytest.fixture(autouse=True)
def _keep_pygame(monkeypatch):
    monkeypatch.setattr(controller.pygame, "quit", lambda: None)   # other tests still need pygame


class _Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def yt(tmp_path):
    (tmp_path / "client.json").write_text(json.dumps(
        {"installed": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "csecret"}}))
    clock = _Clock()
    (tmp_path / "token.json").write_text(json.dumps(
        {"access_token": "at-0", "refresh_token": "refresh-secret", "expiry": clock.t + 3000}))
    fake, logs = FakeYouTube(), []
    api = ytapi.YouTubeAPI(KEY, client_file=tmp_path / "client.json", token_file=tmp_path / "token.json",
                           http=fake, clock=clock, log=logs.append)
    return api, fake, logs, clock


def _no_secrets(*texts):
    for text in texts:
        for s in SECRETS:
            assert s not in text, f"a secret leaked: {text!r}"


# ---- the stream ----------------------------------------------------------------------------
def test_our_stream_is_found_by_its_key_and_the_key_is_never_logged(yt, capsys):
    api, fake, logs, _ = yt
    bid = api.ensure_broadcast(wait_live=0)
    assert fake.broadcasts[bid]["contentDetails"]["boundStreamId"] == "S-ours"   # not the other stream
    ytapi._status(api)
    api.end_broadcast(bid)
    out = capsys.readouterr()
    _no_secrets(out.out, out.err, *logs)
    assert "S-ours" in out.out and "<- QUIZ_STREAM_KEY" in out.out


def test_a_single_stream_is_used_even_if_the_key_differs_but_two_strangers_are_not(yt):
    api, fake, logs, _ = yt
    fake.streams = fake.streams[:1]
    assert api.find_stream()["id"] == "S-other"
    fake.streams = [fake.streams[0], {**fake.streams[0], "id": "S-third"}]
    with pytest.raises(ytapi.YouTubeError) as e:
        api.find_stream()
    _no_secrets(str(e.value))


# ---- reuse, start, create ------------------------------------------------------------------
def test_an_active_broadcast_on_our_stream_is_reused_without_writes(yt):
    api, fake, logs, _ = yt
    fake.add("B-live", "live")
    assert api.ensure_broadcast() == "B-live"
    assert [c for c in fake.calls if c[0] != "GET"] == []      # no insert, bind or transition (50 units each)


def test_an_upcoming_broadcast_on_our_stream_is_started_not_duplicated(yt):
    api, fake, logs, _ = yt
    fake.add("B-other-stream", "ready", stream="S-other")
    fake.add("B-ready", "ready")
    assert api.ensure_broadcast(wait_live=0) == "B-ready"
    assert fake.broadcasts["B-ready"]["status"]["lifeCycleStatus"] == "live"
    assert fake.posts("liveBroadcasts") == []
    assert [p[2]["broadcastStatus"] for p in fake.posts("liveBroadcasts/transition")] == ["testing", "live"]


def test_no_manual_go_live_while_no_video_arrives_and_at_most_one_per_5_min(yt):
    api, fake, logs, clock = yt
    fake.add("B-ready", "ready")
    fake.streams[1]["status"]["streamStatus"] = "inactive"
    api.ensure_broadcast(wait_live=0)
    assert fake.posts("liveBroadcasts/transition") == []        # it would fail with errorStreamInactive
    fake.streams[1]["status"]["streamStatus"] = "active"
    fake.broadcasts["B-ready"]["status"]["lifeCycleStatus"] = "testing"   # transition accepted, not live yet
    api.ensure_broadcast(wait_live=0)
    fake.broadcasts["B-ready"]["status"]["lifeCycleStatus"] = "testing"
    clock.t += 60
    api.ensure_broadcast(wait_live=0)
    assert len(fake.posts("liveBroadcasts/transition")) == 1
    clock.t += api.TRANSITION_EVERY
    api.ensure_broadcast(wait_live=0)
    assert len(fake.posts("liveBroadcasts/transition")) == 2


def test_without_a_broadcast_one_is_created_bound_and_categorised(yt, monkeypatch):
    api, fake, logs, clock = yt
    fake.add("B-other-stream", "ready", stream="S-other")
    bid = api.ensure_broadcast(wait_live=0)
    (_, _, params, body, _), = fake.posts("liveBroadcasts")
    assert params["part"] == "snippet,status,contentDetails"
    assert body["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert body["contentDetails"] == {"enableAutoStart": True, "enableAutoStop": False,
                                      "latencyPreference": "ultraLow", "enableDvr": False,
                                      "monitorStream": {"enableMonitorStream": True, "broadcastStreamDelayMs": 0}}
    assert body["snippet"]["title"] == ytapi.DEFAULT_TITLE
    assert not set("<>") & set(body["snippet"]["description"])   # YouTube answers 400 invalidDescription
    assert body["snippet"]["scheduledStartTime"] > ytapi._iso(clock.t)   # must be in the future
    (_, _, bind, _, _), = fake.posts("liveBroadcasts/bind")
    assert (bind["id"], bind["streamId"]) == (bid, "S-ours")
    (_, _, _, video, _), = fake.posts("videos")
    assert video["id"] == bid and video["snippet"]["categoryId"] == "24"
    assert f"YouTube: created broadcast {bid} (public)" in logs
    assert fake.broadcasts[bid]["status"]["lifeCycleStatus"] == "live"


# ---- tokens --------------------------------------------------------------------------------
def test_browser_flow_takes_only_its_own_redirect_and_saves_the_token(tmp_path):
    """The brand-account path: Google redirects to our loopback port; a stray request with the wrong
    state is ignored, the right one is exchanged with PKCE and saved privately."""
    import urllib.parse
    import urllib.request
    (tmp_path / "client.json").write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "cs"}}))
    posted = []

    class Http:
        def request(self, method, url, data=None, **kw):
            posted.append((url, data))
            return _Resp(200, {"access_token": "at-web", "refresh_token": "rt-web", "expires_in": 3600})

    api = ytapi.YouTubeAPI("", client_file=tmp_path / "client.json", token_file=tmp_path / "token.json", http=Http())

    def browser(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect, state = q["redirect_uri"][0], q["state"][0]
        assert "select_account" in q["prompt"][0] and q["code_challenge_method"] == ["S256"]

        def hit():
            urllib.request.urlopen(f"{redirect}/?state=forged&code=evil", timeout=5).read()
            urllib.request.urlopen(f"{redirect}/?state={state}&code=good", timeout=5).read()
        threading.Thread(target=hit, daemon=True).start()

    api.browser_auth(open_url=browser, timeout=20)
    url, data = posted[-1]
    assert url == ytapi.TOKEN_URL and data["code"] == "good" and data["code_verifier"]
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "rt-web"


def test_device_flow_shows_the_code_waits_for_approval_and_saves_the_token(yt):
    api, fake, logs, clock = yt
    api.token_file.unlink()
    fake.device_answers = ["authorization_pending", "slow_down", "authorization_pending"]
    shown, slept = [], []

    def sleep(s):
        slept.append(s)
        clock.t += s
    api.device_auth(show=shown.append, sleep=sleep)
    assert "https://www.google.com/device" in shown[0] and "GQVQ-JKEC" in shown[0]
    assert fake.calls[0][2]["scope"] == "https://www.googleapis.com/auth/youtube"
    assert slept == [5, 5, 10, 10]                               # slow_down adds 5 s to the interval
    saved = json.loads(api.token_file.read_text())
    assert saved["refresh_token"] == "refresh-secret" and saved["access_token"] == "at-dev"
    fake.device_answers = ["access_denied"]
    with pytest.raises(ytapi.YouTubeError):
        api.device_auth(show=shown.append, sleep=sleep)


def test_an_expired_access_token_is_refreshed_and_saved_privately(yt):
    api, fake, logs, clock = yt
    clock.t += 3600                                              # the saved access token expired
    api.broadcast_state("x")
    assert fake.calls[0][1] == "token" and fake.calls[0][2]["grant_type"] == "refresh_token"
    assert fake.calls[1][4] == "Bearer at-1"
    saved = json.loads(api.token_file.read_text())
    assert saved["access_token"] == "at-1" and saved["refresh_token"] == "refresh-secret"
    assert saved["expiry"] > clock.t
    if os.name == "posix":
        assert os.stat(api.token_file).st_mode & 0o077 == 0
    api.broadcast_state("x")
    assert len([c for c in fake.calls if c[1] == "token"]) == 1   # still fresh: no second refresh


def test_invalid_grant_is_reported_once_with_the_fix(yt):
    api, fake, logs, clock = yt
    clock.t += 3600
    fake.refresh = "invalid_grant"
    with pytest.raises(ytapi.AuthExpired):
        api.broadcast_state("x")
    keeper = ytapi.BroadcastKeeper(api, is_streaming=lambda: True, on_video=lambda v: None, log=logs.append)
    assert keeper.check() == keeper.AUTH_RETRY
    assert keeper.check() == keeper.AUTH_RETRY
    assert logs.count("YouTube authorisation expired: run quizctl youtube-auth") == 1


def test_quota_exceeded_pauses_all_calls(yt):
    api, fake, logs, clock = yt
    fake.quota_left = 0
    keeper = ytapi.BroadcastKeeper(api, is_streaming=lambda: True, on_video=lambda v: None, log=logs.append)
    assert keeper.check() == api.QUOTA_PAUSE
    sent = len(fake.calls)
    with pytest.raises(ytapi.QuotaExceeded):
        api.broadcast_state("x")
    assert len(fake.calls) == sent                               # no request while paused
    clock.t += api.QUOTA_PAUSE + 1
    fake.quota_left = 100
    assert api.broadcast_state("x") is None


# ---- the watchdog --------------------------------------------------------------------------
def test_the_watchdog_replaces_an_ended_broadcast_and_repins_chat(yt):
    api, fake, logs, _ = yt
    pinned = []
    keeper = ytapi.BroadcastKeeper(api, is_streaming=lambda: True, on_video=pinned.append, log=logs.append)
    keeper.check()
    first = keeper.video_id
    assert pinned == [first]
    writes = len([c for c in fake.calls if c[0] != "GET"])
    keeper.check()                                               # still live: one cheap list, nothing else
    assert len([c for c in fake.calls if c[0] != "GET"]) == writes and pinned == [first]
    fake.broadcasts[first]["status"]["lifeCycleStatus"] = "complete"   # YouTube ended it under us
    keeper.check()
    assert keeper.video_id != first and pinned == [first, keeper.video_id]
    assert fake.broadcasts[keeper.video_id]["status"]["lifeCycleStatus"] == "live"


def test_the_watchdog_calls_nothing_while_we_do_not_stream(yt):
    api, fake, logs, _ = yt
    keeper = ytapi.BroadcastKeeper(api, is_streaming=lambda: False, on_video=lambda v: None, log=logs.append)
    keeper.check()
    assert fake.calls == []


# ---- shutdown ------------------------------------------------------------------------------
class _Stub:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _shutdown_game(keeper):
    g = controller.MainGameController.__new__(controller.MainGameController)
    g._shutdown_done = False
    g.sounds = g.broadcaster = g.chat = g.db = _Stub()
    g.youtube = keeper
    return g


def test_shutdown_ends_the_broadcast(yt):
    api, fake, logs, _ = yt
    keeper = ytapi.BroadcastKeeper(api, is_streaming=lambda: True, on_video=lambda v: None, log=logs.append)
    keeper.check()
    _shutdown_game(keeper).shutdown()
    assert fake.broadcasts[keeper.video_id]["status"]["lifeCycleStatus"] == "complete"
    assert f"YouTube: ended broadcast {keeper.video_id}" in logs


def test_shutdown_never_waits_long_for_youtube(yt, monkeypatch):
    api, fake, logs, _ = yt
    keeper = ytapi.BroadcastKeeper(api, is_streaming=lambda: True, on_video=lambda v: None, log=logs.append)
    keeper.check()
    fake.hang = 3.0                                              # YouTube does not answer
    monkeypatch.setattr(controller, "END_BROADCAST_SECONDS", 0.3)
    t0 = time.monotonic()
    _shutdown_game(keeper).shutdown()
    assert time.monotonic() - t0 < 1.0


# ---- unconfigured: today's behaviour -------------------------------------------------------
def test_without_a_token_file_the_api_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "STREAM_ENABLED", True)
    monkeypatch.setattr(controller, "YOUTUBE_STREAM_KEY", KEY)
    monkeypatch.setenv("QUIZ_YT_TOKEN", str(tmp_path / "youtube_token.json"))
    g = controller.MainGameController.__new__(controller.MainGameController)
    assert g._make_youtube(offline=False) is None
    _shutdown_game(None).shutdown()                               # and shutdown is as before
    (tmp_path / "youtube_token.json").write_text("{}")
    assert isinstance(g._make_youtube(offline=False), ytapi.BroadcastKeeper)
    assert g._make_youtube(offline=True) is None


# ---- chat follows the broadcast ------------------------------------------------------------
def test_pinning_moves_chat_to_the_new_video(monkeypatch):
    opened = []

    class FakeChat:
        def __init__(self, url, session=None):
            self.url, self.video_id, self.alive = url, url[-5:], True

        def open(self):
            opened.append(self.url)
            return True

        def poll(self):
            return [], 0.01

    monkeypatch.setattr(chat_mod, "LiveChat", FakeChat)
    cm = ChatManager(["https://www.youtube.com/channel/UC/live"], queue.Queue())
    cm.start()
    deadline = time.monotonic() + 3
    while not opened and time.monotonic() < deadline:
        time.sleep(0.01)
    cm.pin(["https://www.youtube.com/watch?v=B-new"])
    while len(opened) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    cm.stop()
    cm._thread.join(2)
    assert opened[:2] == ["https://www.youtube.com/channel/UC/live", "https://www.youtube.com/watch?v=B-new"]
    assert threading.active_count() >= 1 and not cm._thread.is_alive()
