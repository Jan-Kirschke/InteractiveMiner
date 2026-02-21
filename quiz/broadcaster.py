"""
The Lifelong Quiz - YouTube Live Broadcaster
Pipes pygame frames + system audio to FFmpeg -> RTMPS -> YouTube Live.

The game loop captures frames into a queue (non-blocking).
A writer thread drains the queue at exactly the target FPS,
feeding FFmpeg at real-time speed so anullsrc audio stays in sync.
"""

import subprocess
import threading
import queue
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
    """Check if FFmpeg has NVIDIA h264_nvenc encoder available."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        return "h264_nvenc" in result.stdout
    except Exception:
        return False


def _find_audio_device(ffmpeg_path: str) -> str | None:
    """Find a DirectShow audio device for loopback capture."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stderr.split("\n")
        audio_section = False
        for line in lines:
            if "DirectShow audio devices" in line:
                audio_section = True
                continue
            if audio_section and '"' in line:
                start = line.index('"') + 1
                end = line.index('"', start)
                device_name = line[start:end]
                if device_name:
                    return device_name
    except Exception:
        pass
    return None


class YouTubeBroadcaster:
    """Streams the pygame display to YouTube Live via FFmpeg."""

    def __init__(self, stream_key: str, width: int = 1920, height: int = 1080,
                 fps: int = 30, bitrate: str = "4500k", ffmpeg_path: str = "ffmpeg"):
        self._stream_key = stream_key
        self._width = width
        self._height = height
        self._fps = fps
        self._bitrate = bitrate
        self._ffmpeg_path = _find_ffmpeg(ffmpeg_path)
        self._proc = None
        self._active = False
        self._error_logged = False
        self._game_fps = 60
        self._skip_ratio = max(1, self._game_fps // self._fps)
        self._frame_queue = queue.Queue(maxsize=3)
        self._stderr_lines = []  # collect stderr for diagnostics

    def start(self):
        """Launch the FFmpeg subprocess and begin streaming."""
        if not self._stream_key:
            print("[Broadcast] No stream key configured")
            return False

        rtmp_url = f"rtmps://a.rtmps.youtube.com/live2/{self._stream_key}"

        # Detect GPU encoder
        use_nvenc = _detect_nvenc(self._ffmpeg_path)
        if use_nvenc:
            video_codec = ["-c:v", "h264_nvenc", "-preset", "p3",
                           "-tune:v", "ll", "-rc", "cbr"]
            print("[Broadcast] Using NVIDIA GPU encoding (h264_nvenc)")
        else:
            video_codec = ["-c:v", "libx264", "-preset", "veryfast",
                           "-tune", "zerolatency"]
            print("[Broadcast] Using CPU encoding (libx264)")

        # Build audio input args
        audio_device = _find_audio_device(self._ffmpeg_path)
        if audio_device:
            audio_input = ["-f", "dshow", "-i", f"audio={audio_device}"]
            print(f"[Broadcast] Audio device: {audio_device}")
        else:
            audio_input = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            print("[Broadcast] No audio device found, streaming with silent audio")

        bufsize_val = int(self._bitrate.replace("k", "")) * 2

        cmd = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
            "-y",

            # Video input: raw RGB from stdin
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{self._width}x{self._height}",
            "-r", str(self._fps),
            "-thread_queue_size", "512",
            "-i", "pipe:0",

            # Audio input
            *audio_input,

            # Explicit stream mapping
            "-map", "0:v:0",
            "-map", "1:a:0",

            # Video encoding
            *video_codec,
            "-b:v", self._bitrate,
            "-maxrate", self._bitrate,
            "-bufsize", f"{bufsize_val}k",
            "-g", str(self._fps * 2),
            "-pix_fmt", "yuv420p",

            # Audio encoding
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",

            # Stop when video pipe closes (anullsrc is infinite)
            "-shortest",

            # Output
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
                bufsize=1024 * 1024,  # 1MB buffer for 6MB raw frames
                startupinfo=startupinfo,
            )
            self._active = True
            self._error_logged = False

            # Background threads
            threading.Thread(target=self._monitor_stderr, daemon=True).start()
            threading.Thread(target=self._writer_loop, daemon=True).start()

            print(f"[Broadcast] Streaming to YouTube at {self._fps}fps ({self._bitrate})")
            return True

        except FileNotFoundError:
            print(f"[Broadcast] FFmpeg not found at '{self._ffmpeg_path}'")
            print("[Broadcast] Run: python scripts/download_ffmpeg.py")
            return False
        except Exception as e:
            print(f"[Broadcast] Failed to start: {e}")
            return False

    def send_frame(self, surface: pygame.Surface, frame_count: int):
        """Capture a frame into the queue (non-blocking). Drops frames if behind."""
        if not self._active or self._proc is None:
            return

        if frame_count % self._skip_ratio != 0:
            return

        try:
            raw = pygame.image.tobytes(surface, "RGB")
            self._frame_queue.put_nowait(raw)
        except queue.Full:
            pass  # Drop frame - writer thread is behind

    def _writer_loop(self):
        """Drain frame queue and write to FFmpeg stdin at a steady real-time rate."""
        frame_interval = 1.0 / self._fps
        next_write = time.perf_counter()

        while self._active:
            proc = self._proc
            if proc is None:
                break

            # Check if FFmpeg is still alive
            if proc.poll() is not None:
                if not self._error_logged:
                    code = proc.returncode
                    print(f"[Broadcast] FFmpeg exited (code {code})")
                    for line in self._stderr_lines:
                        print(f"[Broadcast]   {line}")
                    self._error_logged = True
                self._active = False
                break

            # Get next frame from queue
            try:
                raw = self._frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Rate limit: sleep until it's time for the next frame
            now = time.perf_counter()
            sleep_time = next_write - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            next_write = time.perf_counter() + frame_interval

            # Write to FFmpeg pipe
            try:
                if self._active and self._proc and self._proc.stdin and not self._proc.stdin.closed:
                    self._proc.stdin.write(raw)
            except (BrokenPipeError, OSError, ValueError):
                if not self._error_logged:
                    print("[Broadcast] Stream pipe broken, stopping")
                    self._error_logged = True
                self._active = False
                break

    def stop(self):
        """Gracefully stop streaming."""
        self._active = False
        # Drain the queue so writer thread can exit
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        # Give writer thread a moment to notice _active=False
        time.sleep(0.1)
        if self._proc:
            try:
                if not self._proc.stdin.closed:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
            print("[Broadcast] Stopped")

    def _monitor_stderr(self):
        """Read FFmpeg stderr and collect + log errors (masking stream key)."""
        try:
            proc = self._proc
            if not proc:
                return
            for line in proc.stderr:
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                # Mask the stream key
                if self._stream_key and self._stream_key in text:
                    text = text.replace(self._stream_key, "****")
                # Skip progress lines
                if text.startswith("frame=") or text.startswith("size="):
                    continue
                self._stderr_lines.append(text)
                print(f"[Broadcast] FFmpeg: {text}")
        except Exception:
            pass

    @property
    def is_active(self) -> bool:
        return self._active
