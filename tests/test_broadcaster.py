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
