"""
The Lifelong Quiz - Chat Manager
YouTube live chat reading via pytchat with fake chat fallback.
Supports dynamic reconnection when a new stream is detected.
"""

import threading
import queue
import time
import random

from quiz.config import FAKE_CHAT_ENABLED
from quiz.models import ChatMessage


# Fake bot usernames (used for offline testing only)
FAKE_USERNAMES = [
    "QuizMaster", "BrainiacBob", "TriviaQueen", "Lucky7",
    "NerdAlert", "BookWorm42", "HistoryBuff", "ScienceGuy",
    "MovieFan", "GeoGuesser", "SportsFan99", "MusicLover",
    "GamerzUnite", "PixelPirate", "CosmicCat", "ThinkTank",
]


class ChatManager:
    def __init__(self, video_id: str, message_queue: queue.Queue):
        self._video_id = video_id
        self._queue = message_queue
        self._running = False
        self._connected = False
        self._thread = None
        self._use_fake = not video_id
        self._reconnect_event = threading.Event()

    def start(self):
        self._running = True
        if self._use_fake:
            if FAKE_CHAT_ENABLED:
                print("[Chat] No video ID provided, starting fake chat mode")
                self._thread = threading.Thread(
                    target=self._fake_chat_thread, daemon=True
                )
            else:
                print("[Chat] Waiting for live stream connection...")
                self._thread = threading.Thread(
                    target=self._waiting_thread, daemon=True
                )
        else:
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
        self._reconnect_event.set()

    def _waiting_thread(self):
        """Silently wait for a real stream connection (no fake bots)."""
        while self._running:
            if self._reconnect_event.wait(timeout=2.0):
                self._reconnect_event.clear()
                if self._video_id:
                    print("[Chat] Stream found! Connecting to live chat...")
                    self._real_chat_thread()
                    return

    def _real_chat_thread(self):
        try:
            import pytchat
        except ImportError:
            print("[Chat] pytchat not installed, falling back to fake chat")
            if FAKE_CHAT_ENABLED:
                self._use_fake = True
                self._fake_chat_thread()
            else:
                print("[Chat] Cannot connect without pytchat. Install it: pip install pytchat")
            return

        consecutive_failures = 0
        while self._running:
            self._reconnect_event.clear()
            try:
                print(f"[Chat] Connecting to video {self._video_id}...")
                chat = pytchat.create(video_id=self._video_id)
                self._connected = True
                consecutive_failures = 0
                print("[Chat] Connected to YouTube live chat!")

                while chat.is_alive() and self._running:
                    if self._reconnect_event.is_set():
                        print("[Chat] Reconnect requested, switching stream...")
                        break
                    for c in chat.get().sync_items():
                        text = c.message.strip()
                        if not text:
                            continue
                        msg = ChatMessage(
                            username=c.author.name,
                            message=text.lower(),
                            timestamp=time.time(),
                        )
                        self._queue.put(msg)
                        print(f"[Chat] {msg.username}: {text}")
                    time.sleep(0.5)

                self._connected = False
                if self._reconnect_event.is_set():
                    continue  # Skip backoff, reconnect immediately
                print("[Chat] Chat stream ended")

            except Exception as e:
                self._connected = False
                if self._reconnect_event.is_set():
                    continue  # New stream available, reconnect immediately
                consecutive_failures += 1
                wait_time = min(60, 10 * consecutive_failures)
                print(
                    f"[Chat] Error (attempt {consecutive_failures}): {e}. "
                    f"Retrying in {wait_time}s"
                )
                # Wait but wake up early if reconnect is requested
                self._reconnect_event.wait(timeout=wait_time)

    def _fake_chat_thread(self):
        self._connected = True
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
                msg = "reset"
            else:
                msg = str(random.randint(1, 4))

            self._queue.put(ChatMessage(user, msg, time.time()))

    def stop(self):
        self._running = False
        self._reconnect_event.set()  # Wake up any waiting threads
        print("[Chat] Stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_fake(self) -> bool:
        return self._use_fake and FAKE_CHAT_ENABLED
