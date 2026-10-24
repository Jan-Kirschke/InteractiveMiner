"""
The Lifelong Quiz - the show's own messages in the YouTube live chat.

The show posts as the channel through the YouTube Data API (liveChatMessages.insert): a rotating
tip about the social commands every few minutes, and batched answers to !friends. Chat is still
READ by quiz/ytchat.py; ChatManager.ignore_channel drops our posts when they come back.

Quota (read 2026-10-24):
  liveChatMessages.insert: 20 units
      developers.google.com/youtube/v3/live/docs/liveChatMessages/insert ("quota cost of 20 units")
      and the quota calculator developers.google.com/youtube/v3/determine_quota_cost
  liveBroadcasts.list: 1 unit (determine_quota_cost); snippet.liveChatId and snippet.channelId
      from developers.google.com/youtube/v3/live/docs/liveBroadcasts
  10,000 units per day for the project, reset at midnight Pacific Time (determine_quota_cost)
So POST_BUDGET = 4,000 units = about 200 posts a day, which leaves 6,000 for the broadcast keeper.
The 200-character message limit is YouTube chat's own; the API reference does not state it, and an
over-long text would come back as 400 messageTextInvalid, so texts are cut to MAX_LEN first.
"""

from __future__ import annotations

import datetime as _dt
import queue
import random
import threading
import time

from quiz.config import DOUBLE_AFTER, DOUBLE_STAKE, HALF_STREAK
from quiz.ytapi import AuthExpired, QuotaExceeded, YouTubeError

INSERT_COST = 20
LIST_COST = 1
DAILY_QUOTA = 10_000
POST_BUDGET = 4_000       # units per Pacific day for chat posts
REPLY_RESERVE = 1_000     # tips stop with this much left, so !friends replies keep 50 posts
MAX_LEN = 200

# One tip every QUIZ_CHAT_TIPS_MINUTES while live, in this order (English: the show is English)
TIPS = [
    "Play with a friend: type !friend @name. When they type !friend @you back, you are friends. "
    "Then !friends shows your friends' points and places right here in chat.",
    "Challenge someone: type !duel @name. When they type !accept, you go head to head in the next "
    "match and the most points wins.",
    "Team up: !crew name joins a crew (or founds it). Your crew's best 3 players count in every match. "
    "!crew leave to leave.",
    "Gold or Teal? Type !team to see which side your name plays for in team matches.",
    f"50:50 joker: on a {HALF_STREAK}-answer streak, type !half 1 3 to answer with two options for half "
    "the points. Once per match.",
    f"Feeling sure? After {DOUBLE_AFTER} answers in a match, type !double while a question runs: x2 if "
    f"right, up to {DOUBLE_STAKE} match points lost if wrong.",
    "Type !rank for your weekly place, points and level, or !card to put your player card on screen.",
    "!friends answers here in chat with how your friends are doing. Add one with !friend @name, "
    "remove one with !unfriend @name.",
]


# ---- YouTube's quota day: midnight Pacific Time ----------------------------------------------
def _pacific_offset(t: float) -> int:
    """UTC offset of US Pacific time in hours: -7 from the second Sunday of March 10:00 UTC
    (2:00 PST) to the first Sunday of November 09:00 UTC (2:00 PDT), else -8."""
    utc = _dt.datetime.fromtimestamp(t, _dt.timezone.utc)

    def sunday(month: int, n: int) -> _dt.datetime:
        first = _dt.datetime(utc.year, month, 1, tzinfo=_dt.timezone.utc)
        return first + _dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))
    start = sunday(3, 2) + _dt.timedelta(hours=10)
    end = sunday(11, 1) + _dt.timedelta(hours=9)
    return -7 if start <= utc < end else -8


def pacific_day(t: float) -> str:
    return (_dt.datetime.fromtimestamp(t, _dt.timezone.utc)
            + _dt.timedelta(hours=_pacific_offset(t))).strftime("%Y-%m-%d")


def next_pacific_midnight(t: float) -> float:
    off = _pacific_offset(t)
    local = _dt.datetime.fromtimestamp(t, _dt.timezone.utc) + _dt.timedelta(hours=off)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) + _dt.timedelta(days=1)
    return (midnight - _dt.timedelta(hours=off)).timestamp()


class ChatPoster:
    """Posts to the current broadcast's live chat on its own thread. post() never blocks and
    never raises; when anything goes wrong the message is dropped and posting pauses."""

    QUEUE_MAX = 4
    RATE_PAUSE, RATE_PAUSE_MAX = 60.0, 900.0   # rateLimitExceeded: 1 min, doubling up to 15 min
    FORBIDDEN_PAUSE = 3600.0                   # forbidden: the channel may not post here
    CHAT_RETRY = 600.0                         # no chat id / chat disabled or not found: look again later
    AUTH_PAUSE = 600.0                         # invalid_grant: the keeper tells the operator
    ERROR_PAUSE = 60.0                         # network trouble, 5xx

    def __init__(self, api, budget: int = POST_BUDGET, reserve: int = REPLY_RESERVE,
                 clock=time.time, log=print, on_channel=None):
        self.api, self.budget, self.reserve = api, budget, reserve
        self._clock, self._log, self._on_channel = clock, log, on_channel or (lambda cid: None)
        self._q: queue.Queue = queue.Queue(self.QUEUE_MAX)
        self._lock = threading.Lock()
        self._video = ""            # the broadcast being shown (set from the keeper's thread)
        self._ended = ""            # a video whose chat ended: never posted to again
        self._chat_id = ""
        self.channel_id = ""
        self._day = ""
        self.used = 0               # units spent today (Pacific day), every attempt counted
        self.sent = 0
        self._pause_until = 0.0
        self._rate_pause = self.RATE_PAUSE
        self._said: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- called from other threads ------------------------------------------------------------
    def set_video(self, video_id: str):
        with self._lock:
            if video_id != self._video:
                self._video, self._chat_id = video_id, ""

    @property
    def ready(self) -> bool:
        """A live broadcast is known and posting is not paused (a cheap check for the game loop)."""
        return bool(self._video) and self._video != self._ended and self._clock() >= self._pause_until

    @property
    def pending(self) -> int:
        return self._q.unfinished_tasks

    def post(self, text: str, kind: str = "tip") -> bool:
        """Queue a message ("tip" or "reply"); False if dropped (no broadcast, or the queue is full)."""
        if not self.ready:
            return False
        try:
            self._q.put_nowait((text, kind))
            return True
        except queue.Full:
            return False

    def start(self):
        self._thread = threading.Thread(target=self._run, name="chat-poster", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                text, kind = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.send(text, kind)
            except Exception as e:   # never let the thread die
                self._log(f"YouTube chat: {e}")
            finally:
                self._q.task_done()

    # ---- the post itself (the poster's thread; tests call it directly) -------------------------
    def _once(self, key: str, line: str):
        if key not in self._said:
            self._said.add(key)
            self._log(line)

    def _pause(self, seconds: float):
        self._pause_until = max(self._pause_until, self._clock() + seconds)

    def send(self, text: str, kind: str = "tip") -> bool:
        now = self._clock()
        day = pacific_day(now)
        if day != self._day:
            self._day, self.used, self._said = day, 0, set()
        with self._lock:
            video, chat_id = self._video, self._chat_id
        if not video or video == self._ended or now < self._pause_until:
            return False
        limit = self.budget - (self.reserve if kind == "tip" else 0)
        if self.used + INSERT_COST + (0 if chat_id else LIST_COST) > limit:
            self._once(f"budget-{kind}", f"YouTube chat: today's {kind} budget is used up "
                                         f"({self.used} of {self.budget} units), not posting until midnight PT")
            return False
        try:
            if not chat_id:
                chat_id = self._resolve(video)
                if not chat_id:
                    return False
            self.used += INSERT_COST
            self.api.call("POST", "liveChat/messages", {"part": "snippet"}, {"snippet": {
                "liveChatId": chat_id, "type": "textMessageEvent",
                "textMessageDetails": {"messageText": text[:MAX_LEN]}}})
        except QuotaExceeded:
            self._pause_until = next_pacific_midnight(now)
            self._log("YouTube chat: API quota used up, no chat posts until midnight PT")
            return False
        except AuthExpired:
            self._pause(self.AUTH_PAUSE)
            return False
        except YouTubeError as e:
            self._failed(e, video)
            return False
        except Exception as e:      # network trouble
            self._pause(self.ERROR_PAUSE)
            self._log(f"YouTube chat: post failed ({e})")
            return False
        self.sent += 1
        self._rate_pause = self.RATE_PAUSE
        return True

    def _resolve(self, video: str) -> str:
        """The broadcast's liveChatId (1 unit); also tells the chat reader our channel id."""
        self.used += LIST_COST
        items = self.api.call("GET", "liveBroadcasts", {"part": "snippet", "id": video}).get("items", [])
        snippet = items[0].get("snippet", {}) if items else {}
        chat_id, channel = snippet.get("liveChatId", ""), snippet.get("channelId", "")
        if channel and channel != self.channel_id:
            self.channel_id = channel
            self._on_channel(channel)
        if not chat_id:
            self._pause(self.CHAT_RETRY)
            self._log(f"YouTube chat: broadcast {video} has no live chat (yet)")
            return ""
        with self._lock:
            if self._video == video:
                self._chat_id = chat_id
        return chat_id

    def _failed(self, e: YouTubeError, video: str):
        reason = e.reason
        if reason in ("rateLimitExceeded", "userRequestsExceedRateLimit"):
            self._pause(self._rate_pause)
            self._log(f"YouTube chat: {reason}, pausing posts for {int(self._rate_pause)} s")
            self._rate_pause = min(self._rate_pause * 2, self.RATE_PAUSE_MAX)
        elif reason == "liveChatEnded":
            self._ended = video
            self._log(f"YouTube chat: {reason}, no more posts to broadcast {video}")
        elif reason in ("liveChatDisabled", "liveChatNotFound"):
            with self._lock:
                self._chat_id = ""
            self._pause(self.CHAT_RETRY)
            self._log(f"YouTube chat: {reason}, trying again in {int(self.CHAT_RETRY // 60)} min")
        elif reason in ("forbidden", "insufficientPermissions"):
            self._pause(self.FORBIDDEN_PAUSE)
            self._log(f"YouTube chat: {reason} ({e}), pausing posts for an hour")
        elif reason == "messageTextInvalid":
            self._log(f"YouTube chat: a message was rejected ({e})")
        else:
            self._pause(self.ERROR_PAUSE)
            self._log(f"YouTube chat: post failed ({e})")


class FriendsReplies:
    """!friends requests, on the game thread: one combined chat message per BATCH seconds at most,
    one request per player per COOLDOWN, at most PENDING_MAX waiting."""

    BATCH = 25.0
    COOLDOWN = 120.0
    PENDING_MAX = 10

    def __init__(self):
        self._pending: list[str] = []
        self._asked: dict[str, float] = {}
        self._due = 0.0

    def ask(self, username: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if (username in self._pending or len(self._pending) >= self.PENDING_MAX
                or now - self._asked.get(username, -1e12) < self.COOLDOWN):
            return False
        if not self._pending:
            self._due = max(self._due, now + self.BATCH)
        self._pending.append(username)
        self._asked[username] = now
        if len(self._asked) > 1000:   # forget cooldowns long over
            self._asked = {u: t for u, t in self._asked.items() if now - t < self.COOLDOWN}
        return True

    def take(self, now: float, line_for) -> str:
        """The next combined message once one is due, else "". Lines that do not fit wait for the next."""
        if not self._pending or now < self._due:
            return ""
        parts, rest = [], []
        for user in self._pending:
            line = line_for(user)[:MAX_LEN]
            if len(" | ".join(parts + [line])) <= MAX_LEN and not rest:
                parts.append(line)
            else:
                rest.append(user)
        self._pending = rest
        self._due = now + self.BATCH
        return " | ".join(parts)


class TipTicker:
    """The next tip every `minutes` (0 = off). The first one comes one interval after the first
    call, so a restart never posts at once; a random starting tip keeps restarts from repeating."""

    def __init__(self, minutes: float, tips: list[str] = TIPS, start: int | None = None):
        self.every = max(0.0, minutes) * 60.0
        self.tips = tips
        self._i = random.randrange(len(tips)) if start is None else start
        self._next: float | None = None

    def take(self, now: float) -> str:
        if self.every <= 0 or not self.tips:
            return ""
        if self._next is None:
            self._next = now + self.every
            return ""
        if now < self._next:
            return ""
        self._next = now + self.every
        tip = self.tips[self._i % len(self.tips)]
        self._i += 1
        return tip
