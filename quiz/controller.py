"""
The Lifelong Quiz - Main Game Controller
Ties together chat, logic, database, sounds, and UI into the game loop.
"""

import pygame
import queue
import time
import sys

from quiz.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, WINDOW_TITLE,
    DB_SAVE_INTERVAL, FAKE_CHAT_ENABLED,
    VIDEO_ID, CHANNEL_USERNAME, CHANNEL_ID, CHANNEL_URL,
    STREAM_ENABLED, YOUTUBE_STREAM_KEY, STREAM_FPS, STREAM_BITRATE, FFMPEG_PATH,
)
from quiz.models import GameState
from quiz.db import QuizDatabase
from quiz.chat import ChatManager, FAKE_USERNAMES
from quiz.logic import QuizLogic
from quiz.ui import UIManager
from quiz.sounds import SoundManager
from quiz.stream import resolve_video_id, StreamWatcher
from quiz.broadcaster import YouTubeBroadcaster


class MainGameController:
    def __init__(self, video_id: str = ""):
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.running = True

        # Resolve video ID: explicit arg > config VIDEO_ID > auto-detect from channel
        effective_id = video_id or VIDEO_ID
        resolved = resolve_video_id(
            video_id=effective_id,
            channel_username=CHANNEL_USERNAME,
            channel_id=CHANNEL_ID,
            channel_url=CHANNEL_URL,
        )

        # Subsystems
        self.msg_queue = queue.Queue()
        self.db = QuizDatabase()

        # Clean up fake bot data if fake chat is disabled
        if not FAKE_CHAT_ENABLED:
            self.db.remove_players(FAKE_USERNAMES)

        self.logic = QuizLogic(self.db)
        self.chat = ChatManager(resolved, self.msg_queue)
        self.ui = UIManager(self.screen)
        self.sounds = SoundManager()

        # Background stream watcher (polls for stream if none found yet)
        self._stream_watcher = StreamWatcher(
            on_stream_found=self._on_stream_found,
            channel_username=CHANNEL_USERNAME,
            channel_id=CHANNEL_ID,
            channel_url=CHANNEL_URL,
        )
        # Only start watcher if we didn't already find a stream
        if not resolved:
            self._stream_watcher.start()

        # YouTube Live broadcaster (started in run() so frames are available immediately)
        self.broadcaster = YouTubeBroadcaster(
            stream_key=YOUTUBE_STREAM_KEY,
            width=SCREEN_WIDTH, height=SCREEN_HEIGHT,
            fps=STREAM_FPS, bitrate=STREAM_BITRATE,
            ffmpeg_path=FFMPEG_PATH,
        )

        # Periodic save timer
        self._last_save_time = time.time()
        self._frame_count = 0
        self._shutdown_done = False

        # Track tick sounds to avoid flooding
        self._last_tick_time = 0

    def _on_stream_found(self, video_id: str):
        """Callback from StreamWatcher when a live stream is detected."""
        self.chat.connect_to(video_id)

    def run(self):
        self.chat.start()

        # Render the first frame, then start broadcaster so FFmpeg has data immediately
        self._render()
        pygame.display.flip()
        if STREAM_ENABLED and YOUTUBE_STREAM_KEY:
            self._broadcast_frame()  # Pre-fill queue with first frame
            self.broadcaster.start()

        print("[Game] The Lifelong Quiz is running!")

        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            self._handle_events()
            self._process_chat()
            self.logic.update(dt)
            self._play_sounds()
            self._render()
            self._broadcast_frame()
            self._periodic_save()

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

    def _process_chat(self):
        while not self.msg_queue.empty():
            msg = self.msg_queue.get()
            self.logic.process_message(msg.username, msg.message)

    def _play_sounds(self):
        """Play all queued sounds from logic with appropriate rate limiting."""
        for sound_name in self.logic.sound_queue:
            if sound_name in ("tick", "tick_urgent", "countdown"):
                cooldown = 0.4 if sound_name in ("tick_urgent", "countdown") else 0.8
                self.sounds.play_throttled(sound_name, cooldown)
            elif sound_name == "answer_lock":
                self.sounds.play_throttled(sound_name, 0.15)
            elif sound_name == "vote":
                self.sounds.play_throttled(sound_name, 0.3)
            else:
                self.sounds.play(sound_name)

    def _render(self):
        state = self.logic.state

        data = {
            "state_name": state.name,
            "round_count": self.logic.round_count,
            "category": self.logic.current_category_name,
            "player_count": self.db.get_player_count(),
            "connected": self.chat.is_connected,
            "time_fraction": self.logic.time_fraction,
            "time_remaining": self.logic.time_remaining,
            "uptime": self.logic.uptime,
            "question": self.logic.current_question,
            "answer_count": self.logic.answer_count,
            "result": self.logic.last_result,
            "leaderboard": self.logic.leaderboard,
            "vote_state": self.logic.vote_state,
            "is_double_points": self.logic.is_double_points,
            "events": self.logic.get_recent_events(),
            "competition_alert": self.logic.competition_alert,
        }

        self.ui.draw(state, data)

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
        self.broadcaster.stop()
        self._stream_watcher.stop()
        self.chat.stop()
        self.db.save_all()
        self.db.close()
        pygame.quit()
        print("[Game] Goodbye!")
