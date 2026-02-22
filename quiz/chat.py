"""
The Lifelong Quiz - Chat Manager
YouTube live chat reading via pytchat with fake chat fallback.
Supports dynamic reconnection when a new stream is detected.
"""

import threading
import queue
import time
import random
import re

from quiz.models import ChatMessage


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
    def __init__(self, video_id: str, message_queue: queue.Queue,
                 offline: bool = False):
        self._video_id = video_id
        self._queue = message_queue
        self._offline = offline
        self._running = False
        self._connected = False
        self._thread = None
        self._use_fake = offline or not video_id
        self._reconnect_event = threading.Event()

        # Diagnostics
        self._message_count = 0
        self._status_text = "Initializing..."
        self._last_status_log = 0.0

    def start(self):
        self._running = True
        if self._use_fake:
            if self._offline:
                self._status_text = "Offline mode (fake bots)"
                print("[Chat] Offline mode - starting fake chat bots")
                self._thread = threading.Thread(
                    target=self._fake_chat_thread, daemon=True
                )
            else:
                self._status_text = "Waiting for stream..."
                print("[Chat] No video ID yet, waiting for live stream connection...")
                self._thread = threading.Thread(
                    target=self._waiting_thread, daemon=True
                )
        else:
            self._status_text = f"Connecting to {self._video_id}..."
            self._thread = threading.Thread(
                target=self._real_chat_thread, daemon=True
            )
        self._thread.start()

    def connect_to(self, video_id: str):
        """Switch to a new video ID (called by StreamWatcher when a stream is found)."""
        if not video_id:
            return
        print(f"[Chat] Switching to video {video_id}")
        self._video_id = video_id
        self._use_fake = False
        self._status_text = f"Connecting to {video_id}..."
        self._reconnect_event.set()

    def _waiting_thread(self):
        """Silently wait for a real stream connection (no fake bots)."""
        while self._running:
            if self._reconnect_event.wait(timeout=2.0):
                self._reconnect_event.clear()
                if self._video_id:
                    print("[Chat] Stream found! Connecting to live chat...")
                    self._status_text = f"Connecting to {self._video_id}..."
                    self._real_chat_thread()
                    return

    def _real_chat_thread(self):
        try:
            import pytchat
        except ImportError:
            self._status_text = "ERROR: pytchat not installed"
            print("[Chat] pytchat not installed!")
            print("[Chat] Install it: pip install pytchat")
            if self._offline:
                self._use_fake = True
                self._fake_chat_thread()
            return

        consecutive_failures = 0
        while self._running:
            self._reconnect_event.clear()
            try:
                vid = self._video_id
                print(f"[Chat] Connecting to video {vid}...")
                self._status_text = f"Connecting to {vid}..."
                chat = pytchat.create(video_id=vid, interruptable=False)
                self._connected = True
                self._status_text = f"LIVE - reading chat ({vid})"
                consecutive_failures = 0
                print(f"[Chat] Connected to YouTube live chat! (video: {vid})")

                while chat.is_alive() and self._running:
                    if self._reconnect_event.is_set():
                        print("[Chat] Reconnect requested, switching stream...")
                        break

                    items = chat.get().sync_items()
                    for c in items:
                        text = c.message.strip()
                        if not text:
                            continue
                        # Normalize the message: lowercase, strip punctuation for matching
                        normalized = _PUNCTUATION_RE.sub('', text).strip().lower()
                        msg = ChatMessage(
                            username=c.author.name,
                            message=normalized,
                            timestamp=time.time(),
                        )
                        self._queue.put(msg)
                        self._message_count += 1
                        print(f"[Chat] {msg.username}: {text} -> normalized: '{normalized}'")

                    # Periodic status log (every 30s)
                    now = time.time()
                    if now - self._last_status_log > 30:
                        self._last_status_log = now
                        self._status_text = f"LIVE ({self._message_count} msgs)"
                        print(f"[Chat] Status: connected, {self._message_count} messages received total")

                    time.sleep(0.1)

                self._connected = False
                if self._reconnect_event.is_set():
                    continue  # Skip backoff, reconnect immediately
                # Stream not broadcasting yet or ended — short retry
                self._status_text = f"Waiting for stream {vid} to go live..."
                print(f"[Chat] Stream {vid} not active yet, retrying in 10s...")
                self._reconnect_event.wait(timeout=10)

            except Exception as e:
                self._connected = False
                if self._reconnect_event.is_set():
                    continue  # New stream available, reconnect immediately
                consecutive_failures += 1
                wait_time = min(60, 10 * consecutive_failures)
                self._status_text = f"Error #{consecutive_failures}, retry in {wait_time}s"
                print(
                    f"[Chat] Error (attempt {consecutive_failures}): {e}. "
                    f"Retrying in {wait_time}s"
                )
                # Wait but wake up early if reconnect is requested
                self._reconnect_event.wait(timeout=wait_time)

    def _fake_chat_thread(self):
        self._connected = True
        self._status_text = "Offline (fake bots)"
        print("[Chat] Fake chat running (offline testing mode)")

        while self._running:
            # If reconnect requested, switch to real chat
            if self._reconnect_event.is_set():
                self._connected = False
                print("[Chat] Stream found! Switching from fake chat to live...")
                self._real_chat_thread()
                return

            time.sleep(random.uniform(0.3, 1.5))
            user = random.choice(FAKE_USERNAMES)
            roll = random.random()
            if roll < 0.03:
                msg_text = "reset"
            else:
                msg_text = str(random.randint(1, 4))

            self._queue.put(ChatMessage(user, msg_text, time.time()))
            self._message_count += 1

    def stop(self):
        self._running = False
        self._reconnect_event.set()  # Wake up any waiting threads
        print(f"[Chat] Stopped ({self._message_count} messages total)")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_fake(self) -> bool:
        return self._use_fake and self._offline

    @property
    def message_count(self) -> int:
        return self._message_count

    @property
    def status_text(self) -> str:
        return self._status_text
