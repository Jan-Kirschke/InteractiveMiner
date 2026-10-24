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
    STREAM_ENABLED, YOUTUBE_STREAM_KEY, STREAM_FPS, STREAM_BITRATE, STREAM_OUT_HEIGHT, VERTICAL, STREAM_AUDIO_GAIN_DB, FFMPEG_PATH,
    STREAM_AUDIO_INPUT, STREAM_OUTPUT, LATE_ANSWER_GRACE, REVEAL_AT, MATCH_LENGTH, CHAT_TIPS_MINUTES,
)
from quiz.chatpost import ChatPoster, FriendsReplies, TipTicker
from quiz.models import GameState
from quiz.db import QuizDatabase
from quiz.chat import ChatManager
from quiz.logic import QuizLogic
from quiz.ui import UIManager
from quiz.ui_vertical import VerticalUI
from quiz.sounds import ShowCues, SoundManager
from quiz.ytchat import page_url
from quiz.broadcaster import YouTubeBroadcaster
from quiz import ytapi

END_BROADCAST_SECONDS = 8   # shutdown waits at most this long for YouTube (TimeoutStopSec=20)


def init_pygame():
    """Only the subsystems the game uses (SoundManager starts the mixer itself). Not pygame.init():
    its joystick subsystem, under the dummy video driver on Windows, leaks ~100 USER objects per
    second (10,000 cap in ~2 min), and quitting it afterwards leaves device events in the queue
    that make pygame.event.get() raise KeyError."""
    pygame.display.init()
    pygame.font.init()


class MainGameController:
    def __init__(self, video_id: str = "", offline: bool = False):
        init_pygame()
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
        self.ui = (VerticalUI if VERTICAL else UIManager)(self.screen)
        self.sounds = SoundManager(drumroll_seconds=LATE_ANSWER_GRACE + REVEAL_AT)
        self._cues = ShowCues()

        # YouTube Live broadcaster (started in run() so frames are available immediately)
        self.broadcaster = YouTubeBroadcaster(
            stream_key=YOUTUBE_STREAM_KEY,
            width=SCREEN_WIDTH, height=SCREEN_HEIGHT,
            fps=STREAM_FPS, bitrate=STREAM_BITRATE,
            ffmpeg_path=FFMPEG_PATH,
            game_fps=FPS, audio_input=STREAM_AUDIO_INPUT, output=STREAM_OUTPUT,
            out_height=STREAM_OUT_HEIGHT, audio_gain_db=STREAM_AUDIO_GAIN_DB,
        )
        self.youtube = self._make_youtube(offline)
        # The show's own chat posts (tips, !friends replies) ride on the same API token; none without it
        self.poster = self._make_poster()
        self.replies = FriendsReplies()
        self.tips = TipTicker(CHAT_TIPS_MINUTES)
        if self.poster:
            self.logic.chat_reply = self.replies.ask

        # Periodic save timer
        self._last_save_time = time.time()
        self._frame_count = 0
        self._shutdown_done = False

        # Track tick sounds to avoid flooding
        self._last_tick_time = 0
        self._prev_logic_state = None
        self._music_started = False

    def _make_youtube(self, offline: bool):
        """The broadcast keeper when the YouTube API is set up (a token file exists), else None:
        then YouTube's own broadcast handling and the /live chat lookup run exactly as before."""
        if offline or not STREAM_ENABLED or not YOUTUBE_STREAM_KEY or not ytapi.configured():
            return None
        api = ytapi.YouTubeAPI(YOUTUBE_STREAM_KEY)
        return ytapi.BroadcastKeeper(api, is_streaming=lambda: self.broadcaster.is_active,
                                     on_video=self._pin_chat)

    def _make_poster(self):
        if not getattr(self, "youtube", None):
            return None
        return ChatPoster(self.youtube.api, on_channel=self.chat.ignore_channel)

    def _pin_chat(self, video_id: str):
        print(f"YouTube: chat pinned to video {video_id}")
        self.chat.pin([page_url(video_id=video_id)])
        poster = getattr(self, "poster", None)
        if poster:
            poster.set_video(video_id)

    def _chat_out(self):
        """Hand due tips and !friends replies to the poster (its thread does the HTTP), only while
        we stream to a known broadcast. Lines are built here, on the game thread that owns the state."""
        poster = self.poster
        if not poster or not self.broadcaster.is_active or not poster.ready:
            return
        now = time.time()
        text = self.replies.take(now, self.logic.friends_line)
        if text:
            poster.post(text, "reply")
        tip = self.tips.take(now)
        if tip:
            poster.post(tip, "tip")

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
            if self.youtube:
                self.youtube.start()   # its own thread: creates/binds/starts the broadcast, then watches it
            if self.poster:
                self.poster.start()    # its own thread: posts tips and !friends replies to the chat

        print("[Game] The Lifelong Quiz is running!")

        frame_ms, work_ms, stats_at = [], [], time.monotonic() + 60
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            began = time.perf_counter()
            frame_ms.append(dt * 1000)

            self._handle_events()
            self._process_chat()
            self._chat_out()
            self.logic.update(dt)
            self._save_on_state_change()
            self._play_sounds()
            self._start_music_when_ready()
            self._render()
            self._broadcast_frame()
            self._periodic_save()
            self._watchdog_ping()
            work_ms.append((time.perf_counter() - began) * 1000)
            if time.monotonic() >= stats_at:   # frame pacing: averages hide the hitches viewers see
                f, w = sorted(frame_ms), sorted(work_ms)
                print(f"[Game] Frame ms p50 {f[len(f) // 2]:.0f} p99 {f[len(f) * 99 // 100]:.0f} "
                      f"max {f[-1]:.0f} | work p50 {w[len(w) // 2]:.1f} p99 {w[len(w) * 99 // 100]:.1f} "
                      f"max {w[-1]:.0f} | over 50 ms: {sum(x > 50 for x in f)}")
                frame_ms, work_ms, stats_at = [], [], time.monotonic() + 60

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
        queue = self.logic.sound_queue
        played = len(queue)   # the last update's cues, already played
        while not self.msg_queue.empty():
            msg = self.msg_queue.get()
            if msg.username.lower() in CHAT_BOTS:
                continue  # moderator bots post how-to-play timers; they never play
            # Speed counts from when the player sent it (YouTube's timestamp)
            self.logic.process_message(msg.username, msg.message, msg.raw, at=msg.timestamp)
        # Chat runs before logic.update(), which clears the queue: play what chat queued now
        # (answer clicks, votes, !half, !crew, !duel, !accept; SoundManager caps the bursts).
        for name in self._cues.route(queue[played:], self.logic):
            self.sounds.play(name)
        del queue[played:]

    def _play_sounds(self):
        """The logic's queued cues, plus the cues ShowCues derives from its state clock (reveal
        sweep, points, standings, halftime, podium places, sweeps, BUILDUP bed and stakes).
        SoundManager rate-limits repeats and ignores names it has no sound for."""
        logic = self.logic
        for sound_name in self._cues.route(logic.sound_queue, logic):   # some wait for their visual beat
            self.sounds.play(sound_name)
        for cue in self._cues.update(logic):
            if cue == "buildup":
                info = getattr(logic, "buildup", None) or {}
                self.sounds.play_buildup(info.get("intensity", getattr(logic, "buildup_intensity", 0.0)),
                                         logic.state_duration)
            elif cue == "stakes":
                self.sounds.play_stakes()
            else:
                self.sounds.play(cue)
        self.sounds.set_tension(getattr(logic, "buildup_intensity", 0.0) or 0.0)
        self.sounds.update()

    def _start_music_when_ready(self):
        """Start background music once it's finished generating."""
        if not self._music_started and self.sounds.music_ready:
            self.sounds.start_music()
            self._music_started = True

    def _render(self):
        # The broadcaster converts the last frame on its own thread; never draw over it mid-read.
        if not self.broadcaster.wait_frame():
            print("[Game] Frame conversion is late, skipping a render")
            return
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
                self.db.save_in_background()

    def _periodic_save(self):
        now = time.time()
        if now - self._last_save_time >= DB_SAVE_INTERVAL:
            self.db.save_in_background()  # never on this thread: a slow commit would stall the show
            self._last_save_time = now

    def shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        print("[Game] Shutting down...")
        # End the YouTube broadcast in parallel with the rest of the shutdown, bounded in time.
        deadline = time.monotonic() + END_BROADCAST_SECONDS
        youtube = getattr(self, "youtube", None)
        ending = youtube.end(END_BROADCAST_SECONDS) if youtube else None
        poster = getattr(self, "poster", None)
        if poster:
            poster.stop()
        self.sounds.stop_music()
        self.broadcaster.stop()
        self.chat.stop()
        self.db.save_all()
        self.db.close()
        pygame.quit()
        if ending:
            ending.join(max(0.0, deadline - time.monotonic()))
            if ending.is_alive():
                print("YouTube: no answer in time, leaving the broadcast to YouTube")
        print("[Game] Goodbye!")
