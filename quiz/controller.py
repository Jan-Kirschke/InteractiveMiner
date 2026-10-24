"""
The Lifelong Quiz - Main Game Controller
Ties together chat, logic, database, sounds, and UI into the game loop.
"""

import os
import socket
import pygame
import queue
import signal
import time
import sys

from quiz.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, WINDOW_TITLE,
    DB_SAVE_INTERVAL, DB_PATH, DB_PATH_OFFLINE,
    VIDEO_ID, CHANNEL_IDS, CHAT_BOTS,
    STREAM_ENABLED, YOUTUBE_STREAM_KEY, STREAM_FPS, STREAM_BITRATE, STREAM_HEIGHT, STREAM_AUDIO_GAIN_DB, FFMPEG_PATH,
    STREAM_AUDIO_INPUT, STREAM_OUTPUT, LATE_ANSWER_GRACE, REVEAL_AT, MATCH_LENGTH,
)
from quiz.models import GameState
from quiz.db import QuizDatabase
from quiz.chat import ChatManager
from quiz.logic import QuizLogic
from quiz.ui import UIManager
from quiz.sounds import SoundManager
from quiz.ytchat import page_url
from quiz.broadcaster import YouTubeBroadcaster


class MainGameController:
    def __init__(self, video_id: str = "", offline: bool = False):
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        # Chat source: an explicit video ID pins chat to that video, else each channel's /live page
        pinned = video_id or VIDEO_ID
        chat_urls = [] if offline else (
            [page_url(video_id=pinned)] if pinned else [page_url(channel_id=c) for c in CHANNEL_IDS])

        # Subsystems
        self.msg_queue = queue.Queue()
        self.db = QuizDatabase(DB_PATH_OFFLINE if offline else DB_PATH)
        self.logic = QuizLogic(self.db)
        self.chat = ChatManager(chat_urls, self.msg_queue, offline=offline)
        self.ui = UIManager(self.screen)
        self.sounds = SoundManager(drumroll_seconds=LATE_ANSWER_GRACE + REVEAL_AT)

        # YouTube Live broadcaster (started in run() so frames are available immediately)
        self.broadcaster = YouTubeBroadcaster(
            stream_key=YOUTUBE_STREAM_KEY,
            width=SCREEN_WIDTH, height=SCREEN_HEIGHT,
            fps=STREAM_FPS, bitrate=STREAM_BITRATE,
            ffmpeg_path=FFMPEG_PATH,
            game_fps=FPS, audio_input=STREAM_AUDIO_INPUT, output=STREAM_OUTPUT,
            out_height=STREAM_HEIGHT, audio_gain_db=STREAM_AUDIO_GAIN_DB,
        )

        # Periodic save timer
        self._last_save_time = time.time()
        self._frame_count = 0
        self._shutdown_done = False

        # Track tick sounds to avoid flooding
        self._last_tick_time = 0
        self._prev_logic_state = None
        self._music_started = False

    def _request_stop(self, signum, _frame):
        print(f"[Game] Signal {signum} received, shutting down")
        self.running = False

    def run(self):
        # systemd / supervisors stop us with SIGTERM: finish the frame, save, exit cleanly.
        signal.signal(signal.SIGTERM, self._request_stop)
        self.chat.start()

        # Render the first frame, then start broadcaster so FFmpeg has data immediately
        self._render()
        pygame.display.flip()
        if STREAM_ENABLED and (YOUTUBE_STREAM_KEY or STREAM_OUTPUT):
            self._broadcast_frame()  # Pre-fill queue with first frame
            self.broadcaster.start()

        print("[Game] The Lifelong Quiz is running!")

        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            self._handle_events()
            self._process_chat()
            self.logic.update(dt)
            self._save_on_state_change()
            self._play_sounds()
            self._start_music_when_ready()
            self._render()
            self._broadcast_frame()
            self._periodic_save()
            self._watchdog_ping()

        self.shutdown()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_F1:
                    self.logic.state_timer = 0
                elif event.key == pygame.K_F2:
                    self._toggle_broadcast()
                elif event.key == pygame.K_F3:
                    self.logic.clear_bots()
                    print("[Game] Bots cleared (F3)")
                elif event.key == pygame.K_F4:
                    self.logic.reset_all_scores()
                    print("[Game] All scores reset (F4)")
                elif event.key == pygame.K_F5:
                    self.logic.reset_bot_scores()
                    print("[Game] Bot scores reset (F5)")

    def _watchdog_ping(self):
        """Tell systemd the loop is alive (WatchdogSec in quiz.service restarts a hung game)."""
        now = time.monotonic()
        if now - getattr(self, "_last_ping", 0) < 5:
            return
        self._last_ping = now
        addr = os.environ.get("NOTIFY_SOCKET")
        if not addr:
            return
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
                s.sendto(b"WATCHDOG=1", addr)
        except OSError:
            pass

    def _process_chat(self):
        while not self.msg_queue.empty():
            msg = self.msg_queue.get()
            if msg.username.lower() in CHAT_BOTS:
                continue  # moderator bots post how-to-play timers; they never play
            # Speed counts from when the player sent it (YouTube's timestamp)
            self.logic.process_message(msg.username, msg.message, msg.raw, at=msg.timestamp)

    def _play_sounds(self):
        """Play all queued sounds from logic with appropriate rate limiting."""
        for sound_name in self.logic.sound_queue:
            if sound_name == "answer_lock":
                self.sounds.play_throttled(sound_name, 0.15)
            elif sound_name == "vote":
                self.sounds.play_throttled(sound_name, 0.3)
            else:
                self.sounds.play(sound_name)

    def _start_music_when_ready(self):
        """Start background music once it's finished generating."""
        if not self._music_started and self.sounds.music_ready:
            self.sounds.start_music()
            self._music_started = True

    def _render(self):
        self.ui.draw(self.logic, {
            "connected": self.chat.is_connected,
            "broadcasting": self.broadcaster.is_active,
        })

    def _broadcast_frame(self):
        self._frame_count += 1
        self.broadcaster.send_frame(self.screen, self._frame_count)

    def _toggle_broadcast(self):
        if self.broadcaster.is_active:
            self.broadcaster.stop()
            print("[Game] Streaming stopped (F2)")
        else:
            if YOUTUBE_STREAM_KEY:
                self.broadcaster.start()
                print("[Game] Streaming started (F2)")
            else:
                print("[Game] No stream key configured in quiz/config.py")

    def _save_on_state_change(self):
        """Save DB immediately on state transitions (scores update during REVEALING)."""
        current = self.logic.state
        if current != self._prev_logic_state:
            self._prev_logic_state = current
            self.sounds.set_scene(current.name)
            if current in (GameState.REVEALING, GameState.PODIUM):
                self.db.save_all()

    def _periodic_save(self):
        now = time.time()
        if now - self._last_save_time >= DB_SAVE_INTERVAL:
            self.db.save_all()
            self._last_save_time = now

    def shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        print("[Game] Shutting down...")
        self.sounds.stop_music()
        self.broadcaster.stop()
        self.chat.stop()
        self.db.save_all()
        self.db.close()
        pygame.quit()
        print("[Game] Goodbye!")
