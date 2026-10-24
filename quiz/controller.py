"""
The Lifelong Quiz - Main Game Controller
Ties together chat, logic, database, sounds, and UI into the game loop.
"""

import pygame
import queue
import signal
import time
import sys

from quiz.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, WINDOW_TITLE,
    DB_SAVE_INTERVAL, DB_PATH, DB_PATH_OFFLINE,
    VIDEO_ID, CHANNEL_IDS,
    STREAM_ENABLED, YOUTUBE_STREAM_KEY, STREAM_FPS, STREAM_BITRATE, STREAM_HEIGHT, STREAM_AUDIO_GAIN_DB, FFMPEG_PATH,
    STREAM_AUDIO_INPUT, STREAM_OUTPUT, LATE_ANSWER_GRACE, REVEAL_AT, ANSWER_PORT, ANSWER_URL, MATCH_LENGTH,
)
from quiz.models import GameState
from quiz.db import QuizDatabase
from quiz.chat import ChatManager
from quiz.logic import QuizLogic
from quiz.ui import UIManager
from quiz.sounds import SoundManager
from quiz.ytchat import page_url
from quiz.broadcaster import YouTubeBroadcaster
from quiz.answer_server import AnswerHub, serve


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
        self.answers = AnswerHub(self.db._conn, self.db._lock, self.msg_queue) if ANSWER_PORT else None
        if self.answers and not serve(self.answers, ANSWER_PORT):
            self.answers = None
        self._snapshot_at = 0.0
        self._snapshot_state = None
        self._points_snapshot: dict[str, dict] = {}
        self.ui = UIManager(self.screen, answer_url=ANSWER_URL if self.answers else "")
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

    def _process_chat(self):
        while not self.msg_queue.empty():
            msg = self.msg_queue.get()
            if msg.message.startswith("link ") and self.answers:
                if self.answers.link(msg.message.split()[1], msg.username):
                    self.logic.announce(f"{msg.username} plays on the answer page")
                continue
            self.logic.process_message(msg.username, msg.message, msg.raw,
                                       at=msg.timestamp if msg.source == "web" else None)
        self._publish_answer_state()

    def _publish_answer_state(self):
        """Hand the answer page a fresh snapshot 4 times a second (and on every state change)."""
        if not self.answers:
            return
        now = time.time()
        lg = self.logic
        changed = lg.state != self._snapshot_state
        if not changed and now - self._snapshot_at < 0.25:
            return
        self._snapshot_at = now
        q = lg.current_question if lg.state.name in ("ASKING", "LOCKING", "REVEALING") else None
        state = {
            "phase": lg.state.name, "match": lg.match_no, "q": lg.q_index, "of": MATCH_LENGTH,
            "remaining": round(lg.time_remaining, 2), "duration": lg.state_duration,
            "answers": lg.answer_count, "category": lg.current_category_name,
            "event": lg.mini_event or ("double" if lg.is_double_points else ""),
        }
        if q:
            state.update(question=q.text, options=q.options)
            if lg.state.name == "REVEALING":
                state["correct"] = q.correct_index
        if lg.state.name == "LOBBY" and lg.vote_state:
            state["vote"] = {str(k): v[1] for k, v in lg.vote_state.options.items()}
        if changed:
            self._snapshot_state = lg.state
            ranked = [s for s in lg.match_ranking(n=100_000) if not s.username.startswith("[Bot]")]
            self._points_snapshot = {s.username: {"points": s.points, "rank": i} for i, s in enumerate(ranked, 1)}
        self.answers.publish(state, self._points_snapshot)

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
