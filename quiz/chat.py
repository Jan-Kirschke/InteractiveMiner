"""
The Lifelong Quiz - Chat Manager
YouTube live chat reading (quiz.ytchat) with fake chat for offline testing.
Finds the chat again by itself when YouTube starts a new live video.
"""

import threading
import queue
import time
import random
import re

from quiz.models import ChatMessage
from quiz.ytchat import LiveChat


# Fake bot usernames (used for offline testing only)
FAKE_USERNAMES = [
    "QuizMaster", "BrainiacBob", "TriviaQueen", "Lucky7",
    "NerdAlert", "BookWorm42", "HistoryBuff", "ScienceGuy",
    "MovieFan", "GeoGuesser", "SportsFan99", "MusicLover",
    "GamerzUnite", "PixelPirate", "CosmicCat", "ThinkTank",
]

# Strip these from chat messages before checking for answers
_PUNCTUATION_RE = re.compile(r'[^\w\s]')


class ChatManager:
    """Reads YouTube live chat from the first of `urls` that is live, re-finding the chat when it ends."""

    RETRY_SECONDS = 15   # how often to look for a live chat while none is found
    POLL_BACKOFF = 2     # seconds x failures between failed polls
    POLL_FAILURES = 5    # then re-open the page: the token may be stale

    def __init__(self, urls: list[str], message_queue: queue.Queue, offline: bool = False):
        self._urls = urls
        self._queue = message_queue
        self._offline = offline
        self._running = False
        self._connected = False
        self._thread = None
        self._use_fake = offline

        # Diagnostics
        self._message_count = 0
        self._status_text = "Initializing..."
        self._last_status_log = 0.0
        self._wake = threading.Event()
        self._reopen = False
        self._ignored: set[str] = set()   # channel ids whose messages are not plays (the show's own posts)

    def ignore_channel(self, channel_id: str):
        """Drop messages from this channel: the show posts tips and replies as the channel itself,
        and the reader sees them come back like any other message."""
        if channel_id:
            self._ignored = self._ignored | {channel_id}   # swap, never mutate: the reader thread reads it

    def pin(self, urls: list[str]):
        """Read chat from `urls` from now on (the YouTube API made a new broadcast): drop the
        current chat and open the new one at once."""
        self._urls = urls
        self._reopen = True
        self._wake.set()
        if self._running and not self._offline and self._thread is None:
            self._thread = threading.Thread(target=self._real_chat_thread, daemon=True)
            self._thread.start()

    def start(self):
        self._running = True
        if self._offline:
            self._status_text = "Offline mode (fake bots)"
            print("[Chat] Offline mode - starting fake chat bots")
            target = self._fake_chat_thread
        elif not self._urls:
            self._status_text = "No channel configured"
            print("[Chat] No QUIZ_CHANNEL_IDS / QUIZ_VIDEO_ID set: chat is off")
            return
        else:
            target = self._real_chat_thread
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def _find_chat(self):
        for url in self._urls:
            chat = LiveChat(url)
            try:
                if chat.open():
                    return chat
            except Exception as e:
                print(f"[Chat] Could not open {url}: {e}")
        return None

    def _real_chat_thread(self):
        waiting_logged = False
        while self._running:
            self._reopen = False
            self._wake.clear()   # pin() sets it; stop() sets _running first, so this never loses a stop
            if not self._running:
                break
            chat = self._find_chat()
            if not chat:
                self._status_text = "Waiting for the stream to go live..."
                if not waiting_logged:
                    print(f"[Chat] No live chat yet, checking every {self.RETRY_SECONDS}s")
                    waiting_logged = True
                self._wake.wait(self.RETRY_SECONDS)
                continue
            waiting_logged = False
            self._connected = True
            self._status_text = f"LIVE - reading chat ({chat.video_id})"
            print(f"[Chat] Connected to live chat of video {chat.video_id}")
            failures = 0
            while self._running and chat.alive and not self._reopen:
                try:
                    messages, wait = chat.poll()
                    failures = 0
                except Exception as e:
                    failures += 1
                    print(f"[Chat] Poll failed ({failures}): {e}")
                    if failures >= self.POLL_FAILURES:
                        break  # re-open the page: the token may be stale
                    self._wake.wait(self.POLL_BACKOFF * failures)
                    continue
                for author, text, sent, *channel in messages:
                    if channel and channel[0] in self._ignored:
                        continue
                    self._put(author, text, sent)
                self._log_status()
                self._wake.wait(wait)
            self._connected = False
            if self._running and self._reopen:
                print(f"[Chat] Switching to {self._urls[0] if self._urls else 'no chat'}")
            elif self._running:
                print("[Chat] Live chat ended or lost, looking for it again")

    def _put(self, author: str, text: str, sent: float):
        # Normalize the message: lowercase, strip punctuation for matching
        normalized = _PUNCTUATION_RE.sub('', text).strip().lower()
        self._queue.put(ChatMessage(username=author, message=normalized, timestamp=sent, raw=text))
        self._message_count += 1
        if self._message_count <= 300 or self._message_count % 100 == 0:  # keep the log useful at high volume
            print(f"[Chat] {author}: {text}")

    def _log_status(self):
        now = time.time()
        if now - self._last_status_log > 60:
            self._last_status_log = now
            self._status_text = f"LIVE ({self._message_count} msgs)"
            print(f"[Chat] Status: connected, {self._message_count} messages received total")

    def _fake_chat_thread(self):
        self._connected = True
        self._status_text = "Offline (fake bots)"
        print("[Chat] Fake chat running (offline testing mode)")

        while self._running:
            time.sleep(random.uniform(0.3, 1.5))
            user = random.choice(FAKE_USERNAMES)
            roll = random.random()
            if roll < 0.02:
                raw = "!crew " + random.choice(["Night Owls", "Kaffee Klatsch", "Brainrot Busters"])
            elif roll < 0.03:
                raw = "!duel @" + random.choice(FAKE_USERNAMES)
            elif roll < 0.05:
                raw = random.choice(["!accept", "!ready", "!rank", "!card"])
            else:
                raw = str(random.randint(1, 4))
            msg_text = _PUNCTUATION_RE.sub('', raw).strip().lower()
            self._queue.put(ChatMessage(user, msg_text, time.time(), raw=raw))
            self._message_count += 1

    def stop(self):
        self._running = False
        self._wake.set()  # Wake up any waiting threads
        print(f"[Chat] Stopped ({self._message_count} messages total)")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_fake(self) -> bool:
        return self._use_fake

    @property
    def message_count(self) -> int:
        return self._message_count

    @property
    def status_text(self) -> str:
        return self._status_text
