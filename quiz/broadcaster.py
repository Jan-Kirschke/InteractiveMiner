"""
The Lifelong Quiz - YouTube Live Broadcaster
Pipes pygame frames + system audio to FFmpeg -> RTMPS -> YouTube Live.

The game loop hands over its newest frame (already scaled to the output size).
A writer thread sends a frame to FFmpeg exactly FPS times per second, repeating the last one
when the game is late, so the video clock never falls behind real time. If it did, YouTube
would report "not receiving enough video" and viewers would buffer.
"""

import subprocess
import threading
import time
import os
import sys

import pygame


def _find_ffmpeg(configured_path: str) -> str:
    """Locate the FFmpeg binary. Checks configured path, scripts/, and system PATH."""
    if os.path.isfile(configured_path):
        return configured_path

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts_path = os.path.join(root, "scripts", "ffmpeg.exe")
    if os.path.isfile(scripts_path):
        return scripts_path

    return configured_path


def _detect_nvenc(ffmpeg_path: str) -> bool:
    """Test if NVIDIA h264_nvenc actually works (not just listed)."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1:r=1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _audio_input_args(audio_input: str) -> list[str]:
    """FFmpeg input args for QUIZ_AUDIO_INPUT ("format:device"), or silence if unset.

    Examples: "pulse:quiz_sink.monitor" (Linux null sink carrying only game audio),
    "dshow:audio=CABLE Output (VB-Audio Virtual Cable)" (Windows).
    Never auto-pick a device: the first Windows device is usually a microphone.
    """
    if audio_input and ":" in audio_input:
        fmt, device = audio_input.split(":", 1)
        return ["-thread_queue_size", "1024", "-f", fmt, "-i", device]
    return ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]


class YouTubeBroadcaster:
    """Streams the pygame display to YouTube Live via FFmpeg, restarting FFmpeg if it dies."""

    RESTART_MIN = 5    # seconds before the first restart
    RESTART_MAX = 60   # backoff ceiling
    STABLE_RUN = 60    # a run this long resets the backoff

    def __init__(self, stream_key: str, width: int = 1920, height: int = 1080,
                 fps: int = 30, bitrate: str = "4500k", ffmpeg_path: str = "ffmpeg",
                 game_fps: int = 60, audio_input: str = "", output: str = "", out_height: int = 0,
                 audio_gain_db: float = 0.0):
        self._stream_key = stream_key
        self._width = width
        self._height = height
        self._out_height = out_height if 0 < out_height < height else 0  # 0 = send at render size
        self._audio_gain_db = audio_gain_db
        self._fps = fps
        self._bitrate = bitrate
        self._ffmpeg_path = _find_ffmpeg(ffmpeg_path)
        self._audio_input = audio_input
        self._output = output
        self._proc = None
        self._want = False      # operator wants the stream on
        self._active = False    # FFmpeg is running and accepting frames
        self._skip_ratio = max(1, game_fps // fps)
        if self._out_height:  # scale in pygame: a third of the bytes through the pipe, no FFmpeg scaler
            self._out_size = (round(width * self._out_height / height) // 2 * 2, self._out_height)
            self._scaled = pygame.Surface(self._out_size)
        else:
            self._out_size = (width, height)
            self._scaled = None
        self._latest = None     # newest frame bytes from the game loop
        self._fresh = 0         # frames handed over since the last stats line
        self._stderr_lines = []
        self._force_cpu = False  # set True after GPU encoding fails
        self._thread = None
        self.restarts = 0

    def start(self):
        """Begin streaming; FFmpeg is relaunched with backoff until stop() is called."""
        if not self._stream_key and not self._output:
            print("[Broadcast] No stream key configured (set QUIZ_STREAM_KEY)")
            return False
        if self._want:
            return True
        self._want = True
        self._thread = threading.Thread(target=self._supervise, daemon=True)
        self._thread.start()
        return True

    def _supervise(self):
        backoff = self.RESTART_MIN
        while self._want:
            used_gpu, started = self._launch()
            if started:
                began = time.monotonic()
                self._writer_loop()
                ran = time.monotonic() - began
                code = self._proc.returncode if self._proc else None
                self._close_proc()
                if not self._want:
                    break
                print(f"[Broadcast] FFmpeg exited (code {code}) after {ran:.0f}s")
                for line in self._stderr_lines[-5:]:
                    print(f"[Broadcast]   {line}")
                if used_gpu and ran < 10:
                    print("[Broadcast] GPU encoding failed, switching to CPU (libx264)")
                    self._force_cpu = True
                    continue
                if ran >= self.STABLE_RUN:
                    backoff = self.RESTART_MIN
            if not self._want:
                break
            print(f"[Broadcast] Restarting stream in {backoff}s")
            self.restarts += 1
            deadline = time.monotonic() + backoff
            while self._want and time.monotonic() < deadline:
                time.sleep(0.2)
            backoff = min(self.RESTART_MAX, backoff * 2)

    def _launch(self) -> tuple[bool, bool]:
        """Start one FFmpeg process. Returns (used_gpu, started)."""
        rtmp_url = self._output or f"rtmps://a.rtmps.youtube.com/live2/{self._stream_key}"

        use_nvenc = not self._force_cpu and _detect_nvenc(self._ffmpeg_path)
        if use_nvenc:
            video_codec = ["-c:v", "h264_nvenc", "-preset", "p3",
                           "-tune:v", "ll", "-rc", "cbr"]
            print("[Broadcast] Using NVIDIA GPU encoding (h264_nvenc)")
        else:
            video_codec = ["-c:v", "libx264", "-preset", "veryfast",
                           "-tune", "zerolatency", "-threads", "0"]
            print("[Broadcast] Using CPU encoding (libx264)")

        audio_input = _audio_input_args(self._audio_input)
        print(f"[Broadcast] Audio: {self._audio_input or 'silent (QUIZ_AUDIO_INPUT not set)'}")

        bufsize_val = int(self._bitrate.replace("k", "")) * 2

        cmd = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            # Video input: raw RGB from stdin
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{self._out_size[0]}x{self._out_size[1]}",
            "-r", str(self._fps),
            "-thread_queue_size", "1024",
            "-i", "pipe:0",
            *audio_input,
            "-map", "0:v:0",
            "-map", "1:a:0",
            *video_codec,
            "-b:v", self._bitrate,
            "-maxrate", self._bitrate,
            "-bufsize", f"{bufsize_val}k",
            "-g", str(self._fps * 2),
            "-pix_fmt", "yuv420p",
            *(["-af", f"volume={self._audio_gain_db}dB"] if self._audio_gain_db else []),
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            # Stop when the video pipe closes (anullsrc is infinite)
            "-shortest",
            "-f", "flv",
            "-flvflags", "no_duration_filesize",
            rtmp_url,
        ]

        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE
            self._stderr_lines = []
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=self._out_size[0] * self._out_size[1] * 3 * 4,  # 4 raw frames
                startupinfo=startupinfo,
            )
        except FileNotFoundError:
            print(f"[Broadcast] FFmpeg not found at '{self._ffmpeg_path}'")
            return use_nvenc, False
        except Exception as e:
            print(f"[Broadcast] Failed to start FFmpeg: {e}")
            return use_nvenc, False

        threading.Thread(target=self._monitor_stderr, args=(self._proc,), daemon=True).start()
        self._active = True
        print(f"[Broadcast] Streaming to YouTube at {self._fps}fps ({self._bitrate})")
        return use_nvenc, True

    def send_frame(self, surface: pygame.Surface, frame_count: int):
        """Hand the newest frame to the writer thread (never blocks the game loop)."""
        if not self._active:
            return
        if frame_count % self._skip_ratio != 0:
            return
        if self._scaled is not None:
            pygame.transform.smoothscale(surface, self._out_size, self._scaled)
            surface = self._scaled
        self._latest = pygame.image.tobytes(surface, "RGB")
        self._fresh += 1

    STATS_EVERY = 60  # seconds between "[Broadcast] Health" lines

    def _writer_loop(self):
        """Write one frame every 1/fps seconds until FFmpeg exits or stop() is called."""
        interval = 1.0 / self._fps
        proc = self._proc
        next_write = time.perf_counter()
        stats_at = next_write + self.STATS_EVERY
        written = late = 0
        self._fresh = 0
        while self._want and proc.poll() is None:
            raw = self._latest
            if raw is None:
                time.sleep(0.01)
                next_write = time.perf_counter()
                continue
            try:
                proc.stdin.write(raw)
            except (BrokenPipeError, OSError, ValueError):
                break
            written += 1
            next_write += interval
            now = time.perf_counter()
            if now > next_write + 1.0:  # stalled over a second (pipe blocked): resync, do not burst
                late += 1
                next_write = now
            elif next_write > now:
                time.sleep(next_write - now)
            if now >= stats_at:
                print(f"[Broadcast] Health: {written / self.STATS_EVERY:.1f} fps sent, "
                      f"{self._fresh / self.STATS_EVERY:.1f} fps from the game, {late} stalls")
                stats_at, written, late, self._fresh = now + self.STATS_EVERY, 0, 0, 0
        self._active = False

    def _close_proc(self):
        proc, self._proc = self._proc, None
        self._active = False
        if not proc:
            return
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        self._latest = None

    def stop(self):
        """Stop streaming and do not restart."""
        was_on = self._want
        self._want = False
        self._active = False
        if self._thread:
            self._thread.join(timeout=8)
            self._thread = None
        self._close_proc()
        if was_on:
            print("[Broadcast] Stopped")

    def _monitor_stderr(self, proc):
        """Collect FFmpeg stderr, masking the stream key."""
        try:
            for line in proc.stderr:
                text = line.decode("utf-8", errors="replace").strip()
                if not text or text.startswith(("frame=", "size=")):
                    continue
                if self._stream_key and self._stream_key in text:
                    text = text.replace(self._stream_key, "****")
                self._stderr_lines.append(text)
                print(f"[Broadcast] FFmpeg: {text}")
        except Exception:
            pass

    @property
    def is_active(self) -> bool:
        return self._active
