"""
The Lifelong Quiz - Sound Manager
Prime Time game-show sound, synthesised with numpy at start-up (no audio files).

Music follows the show: an upbeat groove in the lobby and on the podium, a pulsing tension
bed while a question runs, a heartbeat riser over the last five seconds, a drumroll while
late answers lock in, then a stinger on the reveal. Everything shares one key (A minor /
C major) and tempo, so crossfades never clash. Levels are set for streaming: effects peak
near -4 dBFS, music sits around -20 dBFS RMS under them.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import numpy as np
import pygame

SR = 44100
BPM = 112
BEAT = 60.0 / BPM
BAR = 4 * BEAT
_rng = np.random.default_rng(7)  # fixed seed: the show sounds the same every start

# Note frequencies (A4 = 440)
_NOTE = {n: 440.0 * 2 ** ((i - 9) / 12) for i, n in enumerate(
    ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name: str) -> float:
    """'A4' -> 440.0, 'C#3' -> 138.6"""
    return _NOTE[name[:-1]] * 2 ** (int(name[-1]) - 4)


def _t(dur: float) -> np.ndarray:
    return np.arange(int(SR * dur)) / SR


# ------------------------------------------
# BUILDING BLOCKS
# ------------------------------------------
def _env(t, attack=0.005, decay=4.0, hold=0.0):
    """Fast attack, optional hold, exponential decay."""
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.exp(-np.clip(t - attack - hold, 0, None) * decay)
    return a * d


def _fade(x, end=0.02):
    n = min(len(x), int(SR * end))
    if n:
        x[-n:] *= np.linspace(1, 0, n)
    return x


def _voice(freq, dur, harmonics=10, bright=1.0, decay=3.0, attack=0.005, hold=0.0,
           odd_only=False, detune=0.0):
    """Additive saw/square-ish voice. Upper harmonics die faster (bright -> 'brassy pluck')."""
    t = _t(dur)
    out = np.zeros_like(t)
    for d in ((-detune, detune) if detune else (0.0,)):
        f = freq * (1 + d)
        for k in range(1, harmonics + 1):
            if f * k > 16000:
                break
            if odd_only and k % 2 == 0:
                continue
            out += np.sin(2 * np.pi * f * k * t + k) / k * np.exp(-t * decay * bright * (k - 1) * 0.4)
    return _fade(out * _env(t, attack, decay, hold))


def _sine(freq, dur, decay=4.0, attack=0.003):
    t = _t(dur)
    return _fade(np.sin(2 * np.pi * freq * t) * _env(t, attack, decay))


def _bell(freq, dur=1.2, decay=3.5):
    """Glassy bell: inharmonic partials."""
    t = _t(dur)
    out = sum(a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t * decay * (1 + r * 0.3))
              for r, a in ((1, 1.0), (2.76, 0.35), (5.4, 0.15), (8.93, 0.06)))
    return _fade(out * _env(t, 0.002, 0))


def _filter(x, low=0.0, high=None, order=2):
    """Static band filter in the frequency domain (smooth Butterworth-like curves)."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain = np.ones_like(f)
    if high:
        gain /= np.sqrt(1 + (f / high) ** (2 * order))
    if low:
        gain *= 1 / np.sqrt(1 + (low / np.maximum(f, 1)) ** (2 * order))
    return np.fft.irfft(spec * gain, len(x))


def _noise(dur):
    return _rng.uniform(-1, 1, int(SR * dur))


def _glide(f0, f1, dur, curve=4.0):
    """Phase of a sine sweeping from f0 to f1 (exponential)."""
    t = _t(dur)
    f = f1 + (f0 - f1) * np.exp(-t * curve)
    return 2 * np.pi * np.cumsum(f) / SR


# Drums ---------------------------------------------------------------
def _kick(dur=0.45, punch=1.0):
    t = _t(dur)
    body = np.sin(_glide(160 * punch, 45, dur, 22)) * np.exp(-t * 7)
    click = _filter(_noise(dur), 1500) * np.exp(-t * 120) * 0.25
    return _fade(body + click)


def _snare(dur=0.25, tone=0.35):
    t = _t(dur)
    rattle = _filter(_noise(dur), 1200, 9000) * np.exp(-t * 18)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30) * tone
    return _fade(rattle + body)


def _clap(dur=0.3):
    t = _t(dur)
    n = _filter(_noise(dur), 900, 6000)
    env = np.zeros_like(t)
    for off in (0.0, 0.011, 0.022):
        env += np.exp(-np.clip(t - off, 0, None) * 60) * (t >= off)
    env += np.exp(-t * 14) * 0.5
    return _fade(n * env * 0.7)


def _hat(dur=0.07, open_=False):
    t = _t(dur if not open_ else 0.35)
    return _fade(_filter(_noise(len(t) / SR), 7000) * np.exp(-t * (14 if open_ else 70)))


def _crash(dur=2.5):
    t = _t(dur)
    shimmer = sum(np.sin(2 * np.pi * f * t) for f in (3150, 4870, 6230, 7710)) * 0.05
    return _fade((_filter(_noise(dur), 4500) + shimmer) * np.exp(-t * 2.2))


def _reverb(x, seconds=1.6, wet=0.22, stereo=True):
    """Convolution with a decaying-noise impulse (a bright room). Returns (n, 2) stereo."""
    ir_len = int(SR * seconds)
    t = np.arange(ir_len) / SR
    out = []
    for ch in range(2 if stereo else 1):
        ir = _filter(_rng.normal(0, 1, ir_len), 200, 7000) * np.exp(-t * 4.5 / seconds)
        ir /= np.sqrt(np.sum(ir ** 2))
        n = len(x) + ir_len
        size = 1 << (n - 1).bit_length()
        tail = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x) + ir_len]
        dry = np.concatenate([x, np.zeros(ir_len)])
        out.append(dry + tail * wet)
    st = np.stack(out * (1 if stereo else 2), axis=1)
    return _fade_st(st, 0.3)


def _fade_st(st, end):
    n = min(len(st), int(SR * end))
    if n:
        st[-n:] *= np.linspace(1, 0, n)[:, None]
    return st


def _mono_to_st(x, pan=0.0):
    left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    return np.stack([x * left * 1.414, x * right * 1.414], axis=1)


def _mix(*parts, length=None):
    """Sum (start_seconds, stereo_or_mono_array, gain) parts into one stereo buffer."""
    total = length or max(int(s * SR) + len(a) for s, a, _ in parts)
    out = np.zeros((total, 2))
    for start, a, gain in parts:
        a = _mono_to_st(a) if a.ndim == 1 else a
        i = max(0, int(start * SR))
        n = min(len(a), total - i)
        if n > 0:
            out[i:i + n] += a[:n] * gain
    return out


def _norm(st, peak=0.62):
    m = np.max(np.abs(st)) or 1.0
    return st * (peak / m)


def _loop_mix(parts, bars):
    """Like _mix but wraps everything past the loop end back to the start (seamless loops)."""
    total = int(bars * BAR * SR)
    out = np.zeros((total, 2))
    for start, a, gain in parts:
        a = _mono_to_st(a) if a.ndim == 1 else a
        i = int(start * SR) % total
        while len(a):
            n = min(len(a), total - i)
            out[i:i + n] += a[:n] * gain
            a, i = a[n:], 0
    return out


def _loop_reverb(mono, seconds, wet):
    """Reverb for a loop: the tail past the end is folded onto the start, so the seam is inaudible."""
    st = _reverb(mono, seconds, wet)
    n = len(mono)
    out = st[:n].copy()
    out[:len(st) - n] += st[n:]
    return out


def _chord(names, dur, **kw):
    return sum(_voice(hz(n), dur, **kw) for n in names) / len(names)


# ------------------------------------------
# MUSIC
# ------------------------------------------
_PROG_LOBBY = [("A2", ["A3", "C4", "E4", "G4"]), ("F2", ["F3", "A3", "C4", "E4"]),
               ("C3", ["G3", "C4", "E4", "G4"]), ("G2", ["G3", "B3", "D4", "F#4"])]


def _music_lobby():
    """Inviting mid-tempo groove: four-on-the-floor, offbeat hats, funky bass, chord stabs."""
    bars = 8
    parts = []
    kick, clap, hat, ohat = _kick(punch=0.9), _clap(), _hat(), _hat(open_=True)
    for bar in range(bars):
        root, chord = _PROG_LOBBY[(bar // 2) % 4]
        b0 = bar * BAR
        for beat in range(4):
            parts.append((b0 + beat * BEAT, kick, 0.55))
            parts.append((b0 + beat * BEAT + BEAT / 2, hat if beat != 3 else ohat, 0.16))
            if beat in (1, 3):
                parts.append((b0 + beat * BEAT, clap, 0.32))
        # Bass: syncopated root / octave figure
        for pos, octave in ((0, 1), (0.75, 1), (1.5, 2), (2.0, 1), (2.5, 2), (3.25, 1)):
            f = hz(root) * octave
            parts.append((b0 + pos * BEAT, _voice(f, 0.32, harmonics=8, bright=1.6, decay=7), 0.42))
        # Stabs on the "and" of 2 and 4
        stab = _chord(chord, 0.28, harmonics=12, bright=1.4, decay=9, detune=0.004)
        for pos in (1.5, 3.5):
            parts.append((b0 + pos * BEAT, _mono_to_st(stab, -0.25), 0.36))
        # Soft pad over each chord (2 bars), slow attack
        if bar % 2 == 0:
            pad = _chord(chord, BAR * 2, harmonics=5, bright=0.3, decay=0.25, attack=0.35, detune=0.003)
            parts.append((b0, _mono_to_st(pad, 0.3), 0.22))
        # Little bell hook at the end of every 4 bars
        if bar % 4 == 3:
            for i, n in enumerate(("E5", "G5", "A5", "C6")):
                parts.append((b0 + (2 + i * 0.5) * BEAT, _bell(hz(n), 0.9), 0.12))
    return _norm(_loop_reverb(_loop_mix(parts, bars).mean(axis=1), 1.2, 0.14), 0.45)


def _music_question():
    """Thinking music: pulsing low bass on eighths, ticking clock, dark pad, E chord suspense."""
    bars = 4
    parts = []
    prog = [("A1", ["A3", "C4", "E4"]), ("A1", ["A3", "C4", "F4"]),
            ("F1", ["F3", "A3", "C4"]), ("E1", ["E3", "G#3", "B3"])]
    tick = _filter(_noise(0.03), 2500, 9000) * np.exp(-_t(0.03) * 120)
    tock = _sine(1800, 0.05, 60) * 0.6
    kick = _kick(0.5, punch=0.7)
    for bar, (root, chord) in enumerate(prog):
        b0 = bar * BAR
        parts.append((b0, kick, 0.5))
        parts.append((b0 + 2.5 * BEAT, kick, 0.25))
        for e in range(8):
            accent = 1.0 if e % 2 == 0 else 0.7
            parts.append((b0 + e * BEAT / 2,
                          _voice(hz(root) * 2, 0.2, harmonics=6, bright=2.0, decay=10), 0.33 * accent))
        for beat in range(4):
            parts.append((b0 + beat * BEAT, _mono_to_st(tick if beat % 2 else tock, 0.4), 0.22))
        pad = _chord(chord, BAR, harmonics=4, bright=0.4, decay=0.4, attack=0.25, detune=0.004)
        parts.append((b0, _mono_to_st(pad, -0.3), 0.3))
    return _norm(_loop_reverb(_loop_mix(parts, bars).mean(axis=1), 1.0, 0.12), 0.42)


# ------------------------------------------
# ONE-SHOTS
# ------------------------------------------
def _sfx_final_countdown(dur=5.0):
    """Last five seconds: accelerating heartbeat, rising tone and noise swell, ends on time-up."""
    t = _t(dur)
    sweep_f = hz("A3") * 2 ** (2 * t / dur)                        # two octaves up over 5 s
    sweep = np.sin(2 * np.pi * np.cumsum(sweep_f) / SR)
    sweep += 0.4 * np.sin(2 * np.pi * np.cumsum(sweep_f * 1.5) / SR)
    sweep *= (t / dur) ** 1.6 * 0.5
    swell = _filter(_noise(dur), 1500, 9000) * (t / dur) ** 2.5 * 0.35
    parts = [(0, sweep + swell, 1.0)]
    beat = _kick(0.35, punch=0.6)
    for s in range(5):  # lub-dub on every second
        parts.append((s, beat, 0.9))
        parts.append((s + 0.22, beat, 0.55))
    return _norm(_mix(*parts, length=int(dur * SR)), 0.55)


def _sfx_times_up():
    """Time's up: low impact plus a two-note horn."""
    horn = _chord(["E4", "B4"], 0.5, harmonics=12, bright=0.8, decay=4, detune=0.003)
    hit = _kick(0.8, punch=1.3)
    return _norm(_reverb(_mix((0, hit, 1.0), (0, horn, 0.6)).mean(axis=1), 1.4, 0.25), 0.6)


def _sfx_drumroll(dur=4.0):
    """Snare roll that builds while the last answers lock in."""
    hits = []
    step = 1 / 22
    n = int(dur / step)
    for i in range(n):
        k = i / n
        hits.append((i * step + _rng.uniform(-0.003, 0.003), _snare(0.12, 0.15), 0.15 + 0.6 * k ** 1.5))
    return _norm(_reverb(_mix(*hits, length=int(dur * SR)).mean(axis=1), 0.8, 0.12)[:int(dur * SR)], 0.5)


def _sfx_correct():
    """Reveal with right answers: crash, bright major stab, sparkle arpeggio."""
    stab = _chord(["C4", "E4", "G4", "C5"], 1.4, harmonics=14, bright=0.7, decay=2.2, detune=0.004)
    parts = [(0, _crash(), 0.35), (0, _kick(0.6, 1.2), 0.8), (0, stab, 0.9)]
    for i, n in enumerate(("C6", "E6", "G6", "C7")):
        parts.append((0.08 + i * 0.07, _bell(hz(n), 1.0, 4), 0.25))
    return _norm(_reverb(_mix(*parts).mean(axis=1), 1.8, 0.25), 0.66)


def _sfx_wrong():
    """Nobody got it: soft crash and a falling minor phrase (sympathetic, not mocking)."""
    parts = [(0, _crash(1.5), 0.15), (0, _kick(0.6, 0.8), 0.6)]
    for i, n in enumerate(("E4", "D#4", "D4")):
        parts.append((i * 0.22, _voice(hz(n), 0.5 if i < 2 else 1.0, harmonics=6, bright=1.2,
                                       decay=3 if i < 2 else 1.6, detune=0.003), 0.55))
    parts.append((0.44, _voice(hz("A2"), 1.1, harmonics=5, decay=1.5), 0.45))
    return _norm(_reverb(_mix(*parts).mean(axis=1), 1.5, 0.22), 0.5)


def _sfx_new_question():
    """Question appears: sub boom, bright stab, shimmer tail."""
    stab = _chord(["A3", "E4", "A4", "C5"], 0.6, harmonics=14, bright=1.2, decay=5, detune=0.005)
    boom = np.sin(_glide(90, 38, 1.2, 3)) * np.exp(-_t(1.2) * 3.2)
    parts = [(0, boom, 0.9), (0, stab, 0.5), (0, _filter(_noise(0.6), 6000) * np.exp(-_t(0.6) * 6), 0.12)]
    return _norm(_reverb(_mix(*parts).mean(axis=1), 1.4, 0.22), 0.6)


def _sfx_show_open():
    """Match intro: rising swell into a big chord, the 'here we go' moment."""
    swell_t = _t(1.0)
    swell = _filter(_noise(1.0), 800, 8000) * swell_t ** 3 * 0.5
    up = np.sin(2 * np.pi * np.cumsum(hz("A3") * 2 ** swell_t) / SR) * swell_t ** 2 * 0.4
    chord = _chord(["A3", "C#4", "E4", "A4", "C#5"], 2.2, harmonics=14, bright=0.6, decay=1.3, detune=0.005)
    return _norm(_reverb(_mix((0, swell + up, 1.0), (1.0, chord, 0.9), (1.0, _kick(0.8, 1.3), 0.9),
                              (1.0, _crash(), 0.3)).mean(axis=1), 1.8, 0.25), 0.62)


def _sfx_fanfare():
    """Podium: brass fanfare, pick-up triplet into a held C major."""
    parts = []
    for i, n in enumerate(("G4", "G4", "G4")):
        parts.append((i * 0.13, _chord([n, "D5" if i == 2 else "B4"], 0.16, harmonics=12, bright=0.6,
                                       decay=5, detune=0.004), 0.8))
    parts.append((0.42, _chord(["C4", "E4", "G4", "C5", "E5"], 2.4, harmonics=14, bright=0.5,
                               decay=1.0, hold=0.6, detune=0.005), 1.0))
    parts.append((0.42, _crash(), 0.3))
    for i in range(10):  # timpani roll under the held chord
        parts.append((0.42 + i * 0.07, np.sin(2 * np.pi * hz("C2") * _t(0.3)) * np.exp(-_t(0.3) * 9),
                      0.25 * (1 - i / 12)))
    return _norm(_reverb(_mix(*parts).mean(axis=1), 2.0, 0.28), 0.66)


def _sfx_whoosh():
    t = _t(0.45)
    env = np.sin(np.pi * t / 0.45) ** 2
    n = _filter(_noise(0.45), 500, 4000) * env
    pan = np.linspace(-0.8, 0.8, len(t))
    return _norm(np.stack([n * np.cos((pan + 1) * np.pi / 4), n * np.sin((pan + 1) * np.pi / 4)], axis=1), 0.3)


def _sfx_countdown():
    """One clean beep per second in the last five seconds."""
    beep = _voice(hz("A5"), 0.16, harmonics=3, decay=14, odd_only=True)
    return _norm(_mono_to_st(beep), 0.4)


def _sfx_answer_lock():
    """Soft bubble pop when someone answers."""
    t = _t(0.07)
    pop = np.sin(_glide(1100, 520, 0.07, 45)) * np.exp(-t * 55)
    return _norm(_mono_to_st(_fade(pop)), 0.22)


def _sfx_vote():
    return _norm(_mono_to_st(_bell(hz("E6"), 0.25, 14)), 0.2)


def _sfx_streak():
    parts = [(i * 0.06, _bell(hz(n), 0.6, 6), 0.6) for i, n in enumerate(("A5", "C#6", "E6", "A6"))]
    return _norm(_reverb(_mix(*parts).mean(axis=1), 1.0, 0.2), 0.42)


def _sfx_rank_up():
    stab = _chord(["D4", "F#4", "A4", "D5"], 0.9, harmonics=12, bright=0.8, decay=3, detune=0.004)
    parts = [(0, _chord(["A3", "C#4", "E4"], 0.18, harmonics=12, decay=8), 0.6), (0.14, stab, 0.8)]
    parts += [(0.14 + i * 0.05, _bell(hz(n), 0.8, 5), 0.25) for i, n in enumerate(("D6", "F#6", "A6"))]
    return _norm(_reverb(_mix(*parts).mean(axis=1), 1.3, 0.22), 0.5)


def _sfx_event():
    """Special round alert (double points, lightning, jackpot): fast riser into a hit."""
    t = _t(0.6)
    rise = np.sin(2 * np.pi * np.cumsum(hz("A4") * 2 ** (t / 0.6 * 1.5)) / SR) * (t / 0.6) ** 2
    hit = _chord(["A3", "E4", "A4", "C#5", "E5"], 1.3, harmonics=14, bright=0.7, decay=2.5, detune=0.006)
    return _norm(_reverb(_mix((0, rise, 0.35), (0.6, hit, 1.0), (0.6, _kick(0.6, 1.2), 0.8),
                              (0.6, _crash(1.8), 0.25)).mean(axis=1), 1.6, 0.24), 0.62)


_SFX = {
    "correct": _sfx_correct, "wrong": _sfx_wrong, "countdown": _sfx_countdown,
    "final_countdown": _sfx_final_countdown, "times_up": _sfx_times_up, "fanfare": _sfx_fanfare,
    "whoosh": _sfx_whoosh, "streak": _sfx_streak, "vote": _sfx_vote, "double_points": _sfx_event,
    "new_question": _sfx_new_question, "show_open": _sfx_show_open, "rank_up": _sfx_rank_up,
    "answer_lock": _sfx_answer_lock,
}
_MUSIC = {"lobby": _music_lobby, "question": _music_question}

# Which bed plays in which game state (None = music out, the moment belongs to the effects)
SCENE_MUSIC = {"WAITING": "lobby", "LOBBY": "lobby", "INTRO": None, "ASKING": "question",
               "LOCKING": None, "REVEALING": None, "PODIUM": "lobby"}
STINGERS = ("correct", "wrong")   # the reveal: drumroll ends, music returns under the stinger


SFX_GAIN = 0.8   # effects stacked on music and drumroll stay below full scale


def _to_sound(st: np.ndarray, gain: float = 1.0) -> pygame.mixer.Sound:
    channels = (pygame.mixer.get_init() or (SR, -16, 2))[2]
    data = np.clip(st * gain, -1, 1)
    data = data.mean(axis=1, keepdims=True) if channels == 1 else data
    pcm = np.ascontiguousarray((data * 32767).astype(np.int16))
    return pygame.sndarray.make_sound(pcm)


_CACHE_DIR = Path(__file__).resolve().parent.parent / "data"


def load_or_render(drumroll_seconds: float) -> dict[str, np.ndarray]:
    """Rendering takes 5-40 s on a busy CPU; keep the result next to the database.
    The cache name hashes this file, so any change to the sound design re-renders."""
    digest = hashlib.sha1(Path(__file__).read_bytes() + str(drumroll_seconds).encode()).hexdigest()[:12]
    path = _CACHE_DIR / f"sounds_{digest}.npz"
    try:
        with np.load(path) as cached:
            return {k: cached[k] / 32767.0 for k in cached.files}
    except (OSError, ValueError):
        pass
    arrays = render_all(drumroll_seconds)
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        for old in _CACHE_DIR.glob("sounds_*.npz"):
            old.unlink()
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, **{k: (np.clip(v, -1, 1) * 32767).astype(np.int16) for k, v in arrays.items()})
        tmp.replace(path)
    except OSError as e:
        print(f"[Sound] Could not cache sounds: {e}")
    return arrays


def render_all(drumroll_seconds: float = 4.0) -> dict[str, np.ndarray]:
    """Every effect and music bed as stereo float arrays (also used to export previews)."""
    out = {name: fn() for name, fn in _SFX.items()}
    out["drumroll"] = _sfx_drumroll(max(1.0, drumroll_seconds))
    out.update({f"music_{name}": fn() for name, fn in _MUSIC.items()})
    return out


class SoundManager:
    """Generates the show's sounds in the background and plays them by game state."""

    MUSIC_VOLUME = 0.8
    MUSIC_FADE_MS = 900

    def __init__(self, drumroll_seconds: float = 4.0):
        self._enabled = False
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._last_play_time: dict[str, float] = {}
        self._music: dict[str, pygame.mixer.Sound] = {}
        self._scene_bed = None
        self._wanted_bed = "lobby"
        self._drumroll_seconds = drumroll_seconds
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=1024)
        except pygame.error:
            print("[Sound] Mixer init failed, sounds disabled")
            return
        pygame.mixer.set_num_channels(20)
        pygame.mixer.set_reserved(3)
        self._bed_channels = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
        self._roll_channel = pygame.mixer.Channel(2)
        self._enabled = True
        threading.Thread(target=self._generate, daemon=True).start()

    def _generate(self):
        try:
            began = time.monotonic()
            arrays = load_or_render(self._drumroll_seconds)
            for name, st in arrays.items():
                if name.startswith("music_"):
                    self._music[name[6:]] = _to_sound(st)
                else:
                    self._sounds[name] = _to_sound(st, SFX_GAIN)
            print(f"[Sound] {len(arrays)} sounds ready in {time.monotonic() - began:.1f}s")
        except Exception as e:
            print(f"[Sound] Generation failed: {e}")

    @property
    def music_ready(self) -> bool:
        return bool(self._music)

    def start_music(self):
        self._apply_bed()

    def set_scene(self, state_name: str):
        """Called on every game state change: switch the music bed and stop a finished drumroll."""
        if not self._enabled:
            return
        if state_name not in ("LOCKING", "REVEALING"):
            self._roll_channel.fadeout(150)
        self._wanted_bed = SCENE_MUSIC.get(state_name, "lobby")
        self._apply_bed()

    def _apply_bed(self):
        if not self._enabled or not self._music or self._wanted_bed == self._scene_bed:
            return
        old, new = self._bed_channels
        if self._scene_bed:
            old.fadeout(self.MUSIC_FADE_MS if self._wanted_bed else 250)
        self._scene_bed = self._wanted_bed
        if self._wanted_bed:
            new.play(self._music[self._wanted_bed], loops=-1, fade_ms=self.MUSIC_FADE_MS)
            new.set_volume(self.MUSIC_VOLUME)
            self._bed_channels = [new, old]

    def stop_music(self):
        if self._enabled:
            for ch in self._bed_channels:
                ch.fadeout(1000)
            self._scene_bed = None

    def play(self, name: str):
        if not self._enabled:
            return
        sound = self._sounds.get(name)
        if not sound:
            return
        if name == "drumroll":
            self._roll_channel.play(sound)
            return
        sound.play()
        if name in STINGERS:
            self._roll_channel.stop()
            self._wanted_bed = "lobby"
            self._apply_bed()

    def play_throttled(self, name: str, cooldown: float = 0.5):
        """Play a sound with rate limiting."""
        now = time.time()
        if now - self._last_play_time.get(name, 0) < cooldown:
            return
        self._last_play_time[name] = now
        self.play(name)


if __name__ == "__main__":  # pre-render the cache (quizctl update runs this before restarting the show)
    from quiz.config import LATE_ANSWER_GRACE, REVEAL_AT
    began = time.monotonic()
    print(f"[Sound] {len(load_or_render(LATE_ANSWER_GRACE + REVEAL_AT))} sounds cached "
          f"in {time.monotonic() - began:.1f}s")
