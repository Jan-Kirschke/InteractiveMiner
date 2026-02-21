"""
The Lifelong Quiz - Sound Manager
Smooth, atmospheric procedural sounds with a dark poker room vibe.
Low volume, warm tones, gentle transitions.
"""

import pygame
import math
import array
import random as _rnd


SAMPLE_RATE = 44100
# Master volume (0.0 to 1.0) - keeps everything gentle
MASTER_VOL = 0.18


def _get_mixer_channels():
    """Get the actual number of output channels the mixer is using."""
    init = pygame.mixer.get_init()
    if init:
        return init[2]
    return 2


def _make_sound(mono_buf):
    """Convert a mono sample buffer into a Sound matching the mixer's channel count."""
    channels = _get_mixer_channels()
    if channels <= 1:
        return pygame.mixer.Sound(buffer=mono_buf)

    out = array.array("h")
    for sample in mono_buf:
        for _ in range(channels):
            out.append(sample)
    return pygame.mixer.Sound(buffer=out)


# ------------------------------------------
# LOW-PASS FILTER (softens harsh edges)
# ------------------------------------------
def _lowpass(buf, cutoff=0.15):
    """Simple one-pole low-pass filter. cutoff 0.0 = muffled, 1.0 = no filter."""
    out = array.array("h")
    prev = 0.0
    for sample in buf:
        prev += cutoff * (sample - prev)
        out.append(max(-32767, min(32767, int(prev))))
    return out


# ------------------------------------------
# SOUND GENERATORS - Dark Poker Room Theme
# ------------------------------------------

def _generate_correct_ding():
    """Warm, mellow two-note chime - like a soft vibraphone in a jazz lounge."""
    n_samples = int(SAMPLE_RATE * 0.7)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE

        # D5 then F#5 - warm major third
        if t < 0.25:
            freq = 587
            env = min(1.0, t / 0.03) * math.exp(-t * 4)
        else:
            freq = 740
            lt = t - 0.25
            env = min(1.0, lt / 0.03) * math.exp(-lt * 3.5)

        # Pure fundamental with gentle second harmonic
        val = math.sin(2 * math.pi * freq * t)
        val += 0.2 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t * 6)
        val *= env * MASTER_VOL

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.25))


def _generate_wrong_buzz():
    """Soft, low 'mm-mm' - gentle disappointment, not harsh."""
    n_samples = int(SAMPLE_RATE * 0.4)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        progress = i / n_samples

        # Two low notes descending - Bb3 to G3
        if t < 0.2:
            freq = 233
        else:
            freq = 196

        env = math.exp(-progress * 3) * min(1.0, t / 0.02)

        val = math.sin(2 * math.pi * freq * t)
        val += 0.15 * math.sin(2 * math.pi * freq * 3 * t)
        val *= env * MASTER_VOL * 0.7

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.2))


def _generate_tick():
    """Soft poker chip click - gentle wooden tap."""
    n_samples = int(SAMPLE_RATE * 0.05)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        env = math.exp(-i / n_samples * 8)

        # Mix of click transient + muted tone
        val = (_rnd.random() * 2 - 1) * env * 0.3  # noise click
        val += math.sin(2 * math.pi * 800 * t) * env * 0.15
        val *= MASTER_VOL * 0.5

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.4))


def _generate_tick_urgent():
    """Slightly brighter chip click for low time - still gentle."""
    n_samples = int(SAMPLE_RATE * 0.06)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        env = math.exp(-i / n_samples * 7)

        val = (_rnd.random() * 2 - 1) * env * 0.2
        val += math.sin(2 * math.pi * 1000 * t) * env * 0.25
        val += math.sin(2 * math.pi * 1500 * t) * env * 0.08
        val *= MASTER_VOL * 0.6

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.45))


def _generate_fanfare():
    """Smooth jazz-style ascending chord - muted trumpet feel."""
    n_samples = int(SAMPLE_RATE * 1.2)
    buf = array.array("h")

    # Cmaj7 arpeggio - classy jazz chord
    notes = [
        (262, 0.00, 0.5),   # C4
        (330, 0.20, 0.5),   # E4
        (392, 0.40, 0.5),   # G4
        (494, 0.60, 0.6),   # B4
    ]

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        val = 0

        for freq, start, dur in notes:
            if start <= t < start + dur:
                lt = t - start
                env = min(1.0, lt / 0.02) * math.exp(-lt * 2.5)
                val += math.sin(2 * math.pi * freq * t) * env
                val += 0.12 * math.sin(2 * math.pi * freq * 2 * t) * env * math.exp(-lt * 4)

        val *= MASTER_VOL
        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.3))


def _generate_whoosh():
    """Soft breeze - like velvet curtain movement in the poker room."""
    n_samples = int(SAMPLE_RATE * 0.25)
    buf = array.array("h")

    for i in range(n_samples):
        progress = i / n_samples
        env = math.sin(math.pi * progress) ** 0.7 * MASTER_VOL * 0.5

        val = (_rnd.random() * 2 - 1) * env

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.12))


def _generate_streak_up():
    """Gentle ascending shimmer - like coins being stacked softly."""
    n_samples = int(SAMPLE_RATE * 0.5)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        progress = i / n_samples

        # Gentle rising pitch
        freq = 400 + 600 * (progress ** 0.7)
        env = math.exp(-progress * 2) * min(1.0, t / 0.015)

        val = math.sin(2 * math.pi * freq * t) * env
        # Soft shimmer overtone
        val += 0.15 * math.sin(2 * math.pi * freq * 1.5 * t) * env * math.exp(-progress * 3)
        val *= MASTER_VOL * 0.8

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.3))


def _generate_vote_blip():
    """Soft chip toss onto felt - quick muted tap."""
    n_samples = int(SAMPLE_RATE * 0.08)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        env = math.exp(-i / n_samples * 10)

        val = math.sin(2 * math.pi * 660 * t) * env * 0.4
        val += (_rnd.random() * 2 - 1) * env * 0.15  # felt texture
        val *= MASTER_VOL * 0.5

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.3))


def _generate_double_points():
    """Rich, warm rising tone - like a slot machine's gentle payout bell."""
    n_samples = int(SAMPLE_RATE * 0.8)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        progress = i / n_samples

        # Slow rise through a warm interval
        freq = 330 + 220 * (progress ** 0.4)
        env = min(1.0, t / 0.03) * math.exp(-progress * 1.8)

        val = math.sin(2 * math.pi * freq * t) * env
        # Subtle chorus/shimmer effect
        val += 0.2 * math.sin(2 * math.pi * (freq * 1.002) * t) * env
        val += 0.1 * math.sin(2 * math.pi * freq * 2 * t) * env * math.exp(-progress * 4)
        val *= MASTER_VOL * 0.9

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.25))


def _generate_new_question():
    """Soft card flip / deal sound - brief, atmospheric."""
    n_samples = int(SAMPLE_RATE * 0.15)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        progress = i / n_samples

        env = math.exp(-progress * 6) * min(1.0, t / 0.003)

        # Brief noise burst (card snap) + gentle tone
        val = (_rnd.random() * 2 - 1) * env * 0.4
        val += math.sin(2 * math.pi * 523 * t) * env * 0.3
        val *= MASTER_VOL * 0.7

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.35))


def _generate_countdown_warning():
    """Deep, muffled heartbeat-like pulse - tension without harshness."""
    n_samples = int(SAMPLE_RATE * 0.12)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        progress = i / n_samples

        freq = 100 + 40 * math.exp(-progress * 4)
        env = math.exp(-progress * 5) * min(1.0, t / 0.003)

        val = math.sin(2 * math.pi * freq * t) * env
        val += 0.3 * math.sin(2 * math.pi * freq * 2 * t) * env * math.exp(-progress * 8)
        val *= MASTER_VOL * 0.8

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.2))


def _generate_rank_up():
    """Elegant ascending chord progression - smooth jazz rank-up."""
    n_samples = int(SAMPLE_RATE * 1.5)
    buf = array.array("h")

    # Dm7 to Cmaj7 - classy jazz resolution
    notes = [
        (294, 0.00, 0.7),   # D4
        (349, 0.05, 0.65),  # F4
        (440, 0.10, 0.6),   # A4
        (523, 0.15, 0.55),  # C5
        (330, 0.50, 0.9),   # E4
        (392, 0.55, 0.85),  # G4
        (494, 0.60, 0.8),   # B4
        (659, 0.65, 0.85),  # E5
    ]

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        val = 0

        for freq, start, dur in notes:
            if start <= t < start + dur:
                lt = t - start
                env = min(1.0, lt / 0.02) * math.exp(-lt * 1.8)
                val += math.sin(2 * math.pi * freq * t) * env * 0.12
                val += 0.05 * math.sin(2 * math.pi * freq * 2 * t) * env * math.exp(-lt * 3)

        val *= MASTER_VOL * 1.2
        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.25))


def _generate_answer_lock():
    """Soft click - like a poker chip being placed with confidence."""
    n_samples = int(SAMPLE_RATE * 0.04)
    buf = array.array("h")

    for i in range(n_samples):
        t = i / SAMPLE_RATE
        env = math.exp(-i / n_samples * 12)

        val = (_rnd.random() * 2 - 1) * env * 0.25
        val += math.sin(2 * math.pi * 900 * t) * env * 0.2
        val *= MASTER_VOL * 0.5

        buf.append(max(-32767, min(32767, int(val * 32767))))

    return _make_sound(_lowpass(buf, 0.4))


class SoundManager:
    """Generates and manages all quiz sound effects."""

    def __init__(self):
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=1024)
        except pygame.error:
            print("[Sound] Mixer init failed, sounds disabled")
            self._enabled = False
            return

        self._enabled = True
        self._sounds = {}
        self._last_play_time = {}
        self._generate_all()

    def _generate_all(self):
        init = pygame.mixer.get_init()
        print(f"[Sound] Mixer: {init[0]}Hz, {init[2]}ch")
        print("[Sound] Generating sound effects...")

        self._sounds["correct"] = _generate_correct_ding()
        self._sounds["wrong"] = _generate_wrong_buzz()
        self._sounds["tick"] = _generate_tick()
        self._sounds["tick_urgent"] = _generate_tick_urgent()
        self._sounds["fanfare"] = _generate_fanfare()
        self._sounds["whoosh"] = _generate_whoosh()
        self._sounds["streak"] = _generate_streak_up()
        self._sounds["vote"] = _generate_vote_blip()
        self._sounds["double_points"] = _generate_double_points()
        self._sounds["new_question"] = _generate_new_question()
        self._sounds["countdown"] = _generate_countdown_warning()
        self._sounds["rank_up"] = _generate_rank_up()
        self._sounds["answer_lock"] = _generate_answer_lock()

        for name, snd in self._sounds.items():
            print(f"  {name}: {snd.get_length():.2f}s")
        print("[Sound] All sounds ready")

    def play(self, name: str):
        if not self._enabled:
            return
        sound = self._sounds.get(name)
        if sound:
            sound.play()

    def play_throttled(self, name: str, cooldown: float = 0.5):
        """Play a sound with rate limiting."""
        if not self._enabled:
            return
        import time
        now = time.time()
        last = self._last_play_time.get(name, 0)
        if now - last < cooldown:
            return
        self._last_play_time[name] = now
        self.play(name)
