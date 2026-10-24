"""
The Lifelong Quiz - YouTube Live Broadcaster
Pipes pygame frames + system audio to FFmpeg -> RTMPS -> YouTube Live.

The game loop hands over its newest frame. A converter thread scales it to the output size
(smoothscale releases the GIL, so this runs on the second core) and copies the surface's own
32-bit pixels, telling FFmpeg their layout (-pix_fmt bgr0 on x86) instead of repacking to RGB
in Python. The game must call wait_frame() before drawing on the surface again.
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


# FFmpeg rawvideo name for a 32-bit surface, by (R, G, B) masks, as the bytes lie in memory
_RAW_FORMATS = {
    "little": {(0xFF0000, 0xFF00, 0xFF): "bgr", (0xFF, 0xFF00, 0xFF0000): "rgb"},
    "big": {(0xFF0000, 0xFF00, 0xFF): "0rgb", (0xFF, 0xFF00, 0xFF0000): "0bgr"},
}
_TOBYTES = {"rgb24": "RGB", "bgr0": "BGRA", "bgra": "BGRA", "rgb0": "RGBX", "rgba": "RGBA",
            "0rgb": "ARGB", "argb": "ARGB", "0bgr": "ABGR", "abgr": "ABGR"}


def raw_pix_fmt(surface) -> str:
    """FFmpeg -pix_fmt for the surface's own pixel buffer, or "rgb24" if it must be repacked."""
    if surface is None or surface.get_bytesize() != 4 or surface.get_pitch() != surface.get_width() * 4:
        return "rgb24"
    r, g, b, a = surface.get_masks()
    base = _RAW_FORMATS[sys.byteorder].get((r, g, b))
    if not base:
        return "rgb24"
    if len(base) == 4:  # big endian: the unused byte leads
        return base if not a else base.replace("0", "a")
    return base + ("a" if a else "0")


class YouTubeBroadcaster:
    """Streams the pygame display to YouTube Live via FFmpeg, restarting FFmpeg if it dies."""

    RESTART_MIN = 5    # seconds before the first restart
    RESTART_MAX = 60   # backoff ceiling
    STABLE_RUN = 60    # a run this long resets the backoff
    STALL_KILL = 20    # FFmpeg took no frame for this long (network hung): kill it, the supervisor restarts it
    STOP_WAIT = 8      # stop(): how long the writer may take to finish before FFmpeg is killed

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
        self._sent = None       # the frame bytes the writer sent last
        self._dropped = 0       # game frames replaced before they were sent, since the last stats line
        self._stderr_lines = []
        self._force_cpu = False  # set True after GPU encoding fails
        self._thread = None
        self.restarts = 0
        # Converter: one thread for the broadcaster's lifetime, fed one surface at a time
        self.pix_fmt = raw_pix_fmt(self._scaled) if self._scaled is not None else "rgb24"
        self._source = None
        self._idle = threading.Event()
        self._idle.set()
        self._work = threading.Event()
        self._converter = None
        self._last_write = time.monotonic()

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
        if self._scaled is None:  # frames are the display surface itself
            self.pix_fmt = raw_pix_fmt(pygame.display.get_surface())
        frame_bytes = self._out_size[0] * self._out_size[1] * (3 if self.pix_fmt == "rgb24" else 4)

        cmd = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            # Video input: raw pixels from stdin, in the surface's own layout
            "-f", "rawvideo",
            "-pix_fmt", self.pix_fmt,
            "-s", f"{self._out_size[0]}x{self._out_size[1]}",
            "-r", str(self._fps),
            "-thread_queue_size", "8",   # if FFmpeg falls behind, the writer notices instead of lag piling up
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
            # Gain for the stream, with a limiter so overlapping effects never clip
            *(["-af", f"volume={self._audio_gain_db}dB,alimiter=limit=0.89:level=false"]
              if self._audio_gain_db else []),
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
                bufsize=frame_bytes * 4,  # 4 raw frames
                startupinfo=startupinfo,
            )
        except FileNotFoundError:
            print(f"[Broadcast] FFmpeg not found at '{self._ffmpeg_path}'")
            return use_nvenc, False
        except Exception as e:
            print(f"[Broadcast] Failed to start FFmpeg: {e}")
            return use_nvenc, False

        threading.Thread(target=self._monitor_stderr, args=(self._proc,), daemon=True).start()
        self._last_write = time.monotonic()  # a new FFmpeg is not stalled; the writer loop takes over
        self._active = True
        print(f"[Broadcast] Streaming to YouTube at {self._fps}fps ({self._bitrate})")
        return use_nvenc, True

    def send_frame(self, surface: pygame.Surface, frame_count: int):
        """Hand the newest frame to the converter thread (never blocks the game loop).
        The surface is read after this returns: call wait_frame() before drawing on it again."""
        if not self._active:
            return
        self._kill_if_stalled()
        if frame_count % self._skip_ratio != 0:
            return
        if not self._idle.is_set():
            return  # still converting the previous frame: drop this one, the writer repeats the last
        if self._converter is None:
            self._converter = threading.Thread(target=self._convert_loop, name="frame-convert", daemon=True)
            self._converter.start()
        self._idle.clear()
        self._source = surface
        self._work.set()

    def wait_frame(self, timeout: float = 2.0) -> bool:
        """Block until the surface handed to send_frame has been read. False on timeout."""
        return self._idle.wait(timeout)

    def _convert_loop(self):
        while True:
            self._work.wait()
            self._work.clear()
            surface, self._source = self._source, None
            try:
                if surface is None:
                    continue
                if self._scaled is not None:
                    pygame.transform.smoothscale(surface, self._out_size, self._scaled)  # releases the GIL
                    surface = self._scaled
                if raw_pix_fmt(surface) == self.pix_fmt != "rgb24":
                    raw = surface.get_buffer().raw  # one copy, no repacking
                else:
                    raw = pygame.image.tobytes(surface, _TOBYTES[self.pix_fmt])
                if self._latest is not None and self._latest is not self._sent:
                    self._dropped += 1   # the previous frame was replaced before the writer sent it
                self._latest = raw
                self._fresh += 1
            except Exception as e:  # never kill the thread: the game would wait for it
                print(f"[Broadcast] Frame conversion failed: {e}")
            finally:
                self._idle.set()

    def _kill_if_stalled(self):
        """FFmpeg that stopped taking frames (hung RTMPS connection) never exits by itself."""
        proc = self._proc
        if proc is not None and time.monotonic() - self._last_write > self.STALL_KILL:
            print(f"[Broadcast] FFmpeg took no frame for {self.STALL_KILL}s, killing it")
            self._last_write = time.monotonic()
            try:
                proc.kill()
            except Exception:
                pass

    STATS_EVERY = 60  # seconds between "[Broadcast] Health" lines

    def _writer_loop(self):
        """Write one frame every 1/fps seconds until FFmpeg exits or stop() is called."""
        interval = 1.0 / self._fps
        proc = self._proc
        next_write = time.perf_counter()
        stats_at = next_write + self.STATS_EVERY
        written = late = repeats = 0
        self._fresh = self._dropped = 0
        self._last_write = time.monotonic()
        while self._want and proc.poll() is None:
            raw = self._latest
            if raw is None:
                time.sleep(0.01)
                next_write = time.perf_counter()
                self._last_write = time.monotonic()  # nothing to send is not a stall
                continue
            try:
                proc.stdin.write(raw)
            except (BrokenPipeError, OSError, ValueError):
                break
            if raw is self._sent:
                repeats += 1   # no new game frame since the last write: viewers see a held frame
            self._sent = raw
            self._last_write = time.monotonic()
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
                      f"{self._fresh / self.STATS_EVERY:.1f} fps from the game, {late} stalls, "
                      f"{repeats} repeated, {self._dropped} dropped")
                stats_at, written, late, repeats = now + self.STATS_EVERY, 0, 0, 0
                self._fresh = self._dropped = 0
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
            self._thread.join(timeout=self.STOP_WAIT)
            if self._thread.is_alive() and self._proc is not None:
                # The writer is stuck in a pipe FFmpeg stopped reading; closing it would wait on
                # the writer's lock forever. Killing FFmpeg breaks the pipe and frees the writer.
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._thread.join(timeout=5)
            self._thread = None
        self._close_proc()
        self.wait_frame(2.0)  # the converter may still be reading the game's surface
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
