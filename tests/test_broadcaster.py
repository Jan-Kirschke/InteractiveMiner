"""FFmpeg supervision: a dying encoder is relaunched, stop() ends it for good."""

import sys
import time

from quiz.broadcaster import YouTubeBroadcaster, _audio_input_args


class FastRestart(YouTubeBroadcaster):
    RESTART_MIN = 0.1
    RESTART_MAX = 0.2


def test_dead_ffmpeg_is_restarted_until_stopped():
    # The Python interpreter rejects FFmpeg's arguments and exits at once, like a crashing encoder.
    b = FastRestart(stream_key="test-key", ffmpeg_path=sys.executable)
    assert b.start()
    deadline = time.monotonic() + 15
    while b.restarts < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
    assert b.restarts >= 2
    b.stop()
    count = b.restarts
    time.sleep(0.5)
    assert b.restarts == count
    assert not b.is_active


def test_no_stream_key_does_not_start():
    assert not YouTubeBroadcaster(stream_key="").start()


def test_audio_is_silent_unless_configured():
    assert _audio_input_args("")[-1].startswith("anullsrc")
    assert _audio_input_args("pulse:quiz_sink.monitor")[-4:] == ["-f", "pulse", "-i", "quiz_sink.monitor"]


class _Pipe:
    def __init__(self):
        self.frames = []

    def write(self, raw):
        self.frames.append(raw)


class _Proc:
    def __init__(self):
        self.stdin = _Pipe()

    def poll(self):
        return None


def _picture(w=216, h=384):
    import pygame
    s = pygame.Surface((w, h))
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            pygame.draw.rect(s, ((x * 7) % 256, (y * 3) % 256, (x + y) % 256), (x, y, 8, 8))
    return s


def _as_rgb(raw: bytes, pix_fmt: str) -> bytes:
    """Decode what FFmpeg is told it gets (-pix_fmt) back to packed RGB."""
    if pix_fmt == "rgb24":
        return raw
    order = {"bgr0": (2, 1, 0), "bgra": (2, 1, 0), "rgb0": (0, 1, 2), "rgba": (0, 1, 2),
             "0rgb": (1, 2, 3), "argb": (1, 2, 3), "0bgr": (3, 2, 1), "abgr": (3, 2, 1)}[pix_fmt]
    out = bytearray(len(raw) // 4 * 3)
    for c in range(3):
        out[c::3] = raw[order[c]::4]
    return bytes(out)


def _streaming(**kw):
    b = YouTubeBroadcaster(stream_key="k", width=216, height=384, fps=30, game_fps=30, out_height=256, **kw)
    b._active = True
    return b


def test_frame_sent_to_ffmpeg_is_the_scaled_picture():
    # The bytes in the pipe, read as the -pix_fmt FFmpeg is given, are exactly the scaled RGB picture.
    import pygame
    screen = _picture()
    b = _streaming()
    b.send_frame(screen, 0)
    assert b.wait_frame(2.0)
    want = pygame.image.tobytes(pygame.transform.smoothscale(screen, (144, 256)), "RGB")
    assert _as_rgb(b._latest, b.pix_fmt) == want


def test_ffmpeg_is_told_the_pixel_format_and_size(monkeypatch):
    import quiz.broadcaster as B
    seen = {}

    class Popen:
        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            self.stderr = iter(())

    monkeypatch.setattr(B.subprocess, "Popen", Popen)
    monkeypatch.setattr(B, "_detect_nvenc", lambda path: False)
    b = _streaming()
    b._launch()
    cmd = seen["cmd"]
    i = cmd.index("rawvideo")
    assert cmd[i + 1:i + 5] == ["-pix_fmt", b.pix_fmt, "-s", "144x256"]


def test_surface_is_free_once_wait_frame_returns(monkeypatch):
    # The conversion runs off the game thread; after wait_frame() the game may draw again and the
    # frame already handed over must not change.
    import pygame
    import quiz.broadcaster as B
    real = pygame.transform.smoothscale

    def slow(*a):
        time.sleep(0.2)
        return real(*a)
    monkeypatch.setattr(B.pygame.transform, "smoothscale", slow)
    screen = _picture()
    want = pygame.image.tobytes(real(screen, (144, 256)), "RGB")
    b = _streaming()
    b.send_frame(screen, 0)
    assert b.wait_frame(2.0)
    screen.fill((255, 0, 0))  # the next frame being drawn
    assert _as_rgb(b._latest, b.pix_fmt) == want


def test_send_frame_does_not_wait_for_a_busy_converter(monkeypatch):
    import pygame
    import quiz.broadcaster as B
    real = pygame.transform.smoothscale

    def slow(*a):
        time.sleep(0.5)
        return real(*a)
    monkeypatch.setattr(B.pygame.transform, "smoothscale", slow)
    screen = _picture()
    b = _streaming()
    b.send_frame(screen, 0)
    t0 = time.perf_counter()
    b.send_frame(screen, 1)  # converter still busy with frame 0: drop, never stall the game
    assert time.perf_counter() - t0 < 0.1
    assert b.wait_frame(2.0)


class _HungProc:
    """FFmpeg that stopped reading its input (network stalled): writes block until it is killed."""

    def __init__(self):
        import threading
        self.killed = threading.Event()
        self.returncode = None
        proc = self

        class Stdin:
            def write(self, raw):
                if not proc.killed.wait(10):
                    raise AssertionError("never killed")
                raise BrokenPipeError

            def close(self):  # a real pipe's close() waits for the writer's lock
                proc.killed.wait(10)

        self.stdin = Stdin()

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self.killed.set()


def test_stalled_ffmpeg_is_killed_so_the_supervisor_restarts_it():
    import threading

    class Quick(YouTubeBroadcaster):
        STALL_KILL = 0.3
    b = Quick(stream_key="k", width=216, height=384, fps=30, game_fps=30, out_height=256)
    b._proc, b._want, b._active, b._latest = _HungProc(), True, True, b"frame"
    t = threading.Thread(target=b._writer_loop)
    t.start()
    screen = _picture()
    deadline = time.monotonic() + 3
    while t.is_alive() and time.monotonic() < deadline:
        b.send_frame(screen, 0)  # the game loop keeps handing over frames
        b.wait_frame(1.0)
        time.sleep(1 / 30)
    assert b._proc.killed.is_set()
    t.join(2)
    assert not t.is_alive()


def test_fresh_ffmpeg_is_not_taken_for_a_stalled_one(monkeypatch):
    # After a long restart backoff the last write is old; a frame handed over before the writer
    # loop starts must not kill the FFmpeg that was just launched.
    import quiz.broadcaster as B

    class Popen:
        killed = False

        def __init__(self, cmd, **kw):
            self.stderr = iter(())

        def kill(self):
            Popen.killed = True

    monkeypatch.setattr(B.subprocess, "Popen", Popen)
    monkeypatch.setattr(B, "_detect_nvenc", lambda path: False)
    b = _streaming()
    b._last_write -= 2 * b.STALL_KILL   # the previous FFmpeg died long ago
    b._launch()
    b.send_frame(_picture(), 0)
    b.wait_frame(2.0)
    assert not Popen.killed


def test_stop_returns_when_ffmpeg_hangs():
    # Shutdown (SIGTERM) must not wait on a writer stuck in a pipe FFmpeg no longer reads.
    import threading

    class Quick(YouTubeBroadcaster):
        STOP_WAIT = 0.3
    b = Quick(stream_key="k", fps=30)
    proc = _HungProc()
    b._proc, b._want, b._active, b._latest = proc, True, True, b"frame"
    b._thread = threading.Thread(target=b._writer_loop)
    b._thread.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    b.stop()
    assert time.monotonic() - t0 < 3
    assert proc.killed.is_set()


def test_writer_keeps_real_time_when_the_game_stalls():
    # One game frame, then nothing: YouTube must still get 30 frames per second.
    import threading
    b = YouTubeBroadcaster(stream_key="k", fps=30)
    b._proc, b._want, b._latest = _Proc(), True, b"frame"
    t = threading.Thread(target=b._writer_loop)
    t.start()
    time.sleep(1.0)
    b._want = False
    t.join()
    assert 27 <= len(b._proc.stdin.frames) <= 32


class _BurstyPipe(_Pipe):
    """FFmpeg on a busy CPU: every 4th write blocks for ~3 frame times, then it takes input fast."""

    def write(self, raw):
        super().write(raw)
        if len(self.frames) % 4 == 0:
            time.sleep(0.1)


def test_every_game_frame_goes_out_once_while_ffmpeg_takes_input_in_bursts():
    # Server, 2026-10-24: after each blocked write the writer caught up by re-sending the newest
    # frame, and the frames that came meanwhile were overwritten: ~1,330 of 1,800 frames a minute
    # repeated and as many game frames lost. Every game frame must go out once, in order.
    import threading
    screen = _picture()
    b = _streaming()
    b._proc = _Proc()
    b._proc.stdin = _BurstyPipe()
    b._want = True
    writer = threading.Thread(target=b._writer_loop, daemon=True)
    writer.start()
    period, sent = 1 / 29.7, 0
    t = time.perf_counter()
    for i in range(90):                      # 3 s of game frames
        assert b.wait_frame(2.0)
        b.send_frame(screen, i)
        sent += 1
        t += period
        time.sleep(max(0.0, t - time.perf_counter()))
    assert b.wait_frame(2.0)
    time.sleep(0.1)
    b._want = False
    writer.join(2.0)
    frames = b._proc.stdin.frames
    unique = len({id(f) for f in frames})
    assert unique >= sent * 0.9                 # nearly no game frame lost
    assert len(frames) - unique <= len(frames) * 0.15   # repeats only to keep in step (~1 %)
