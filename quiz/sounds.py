"""
The Lifelong Quiz - Sound Manager
Prime Time game-show sound, synthesised with numpy (no audio files, no samples).

Identity
    key      C major / A minor everywhere, 112 BPM, so beds and effects never clash
    palette  felt mallets (timpani, marimba), warm electric piano, soft brass, glassy bells,
             sine shimmer instead of cymbals, low air instead of noise sweeps. Everything is
             band-limited (~3 kHz) with rounded attacks: warm on a phone speaker, never hissy.
    brand    the four-note motif "the LIFE-long QUIZ": G4 C5 E5 + an ending. "question" ends on
             D5 (open, wants to resolve), "answer" ends on G5 (home). The match open plays the
             question form over the logo and resolves it on the show_open hit; podium, stakes,
             halftime, team_win and the stings reuse it in other voices and tempos.

Music follows the show: a groove in the lobby and on the podium, a thinking bed while a
question runs (a tension layer on top, scaled by logic.buildup_intensity), a lighter results
bed after the reveal. Beds duck under stings. Short cues have voicing variants, picked at random
per play, so repeats don't sound mechanical.

Levels (as heard, before the server's QUIZ_AUDIO_GAIN_DB=3): beds about -23 LUFS integrated,
the loudest 400 ms of a big sting at most the question bed's level, everything else below.
`python -m quiz.sounds` pre-renders the cache and prints every cue's measurements.
"""

from __future__ import annotations

import hashlib
import random
import threading
import time
from functools import lru_cache
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
CEILING = 2900.0   # no partial above this: the warmth rule


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


@lru_cache(maxsize=256)
def _voice(freq, dur, harmonics=10, bright=1.0, decay=3.0, attack=0.005, hold=0.0,
           odd_only=False, detune=0.0):
    """Additive saw/square-ish voice. Upper harmonics die faster (bright -> 'brassy pluck').
    Cached (the beds repeat notes every bar), so the result is read-only."""
    t = _t(dur)
    out = np.zeros_like(t)
    step = np.exp(-t * decay * bright * 0.4)   # each harmonic decays one step faster
    for d in ((-detune, detune) if detune else (0.0,)):
        f = freq * (1 + d)
        damp = np.ones_like(t)
        for k in range(1, harmonics + 1):
            if k > 1 and f * k > CEILING:
                break
            if not (odd_only and k % 2 == 0):
                out += np.sin(2 * np.pi * f * k * t + k) * (damp / k)
            damp *= step
    out = _fade(out * _env(t, attack, decay, hold))
    out.setflags(write=False)
    return out


def _sine(freq, dur, decay=4.0, attack=0.003):
    t = _t(dur)
    return _fade(np.sin(2 * np.pi * freq * t) * _env(t, attack, decay))


def _bell(freq, dur=1.2, decay=3.5):
    """Glassy bell: inharmonic partials (the ones under the ceiling)."""
    t = _t(dur)
    out = sum(a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t * decay * (1 + r * 0.3))
              for r, a in ((1, 1.0), (2.76, 0.35), (5.4, 0.15), (8.93, 0.06)) if r == 1 or freq * r < CEILING)
    return _fade(out * _env(t, 0.002, 0))


def _marimba(freq, dur=0.5, decay=8.0):
    """Wooden bar: the fundamental plus its 4th and 10th partial, dying fast."""
    t = _t(dur)
    out = np.sin(2 * np.pi * freq * t) * np.exp(-t * decay)
    for r, a, d in ((4, 0.25, 3), (10, 0.06, 6)):
        if freq * r < CEILING:
            out = out + a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t * decay * d)
    return _fade(out * np.clip(t / 0.002, 0, 1))


def _epiano(freq, dur=1.5, decay=2.0):
    """Warm electric piano: a sine tine with a short second and third harmonic."""
    t = _t(dur)
    out = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t * 3)
    if 3 * freq < CEILING:
        out = out + 0.1 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-t * 8)
    return _fade(out * _env(t, 0.004, decay))


def _brass(freq, dur, decay=2.0, hold=0.0, attack=0.02):
    """Soft section brass: few harmonics, a 20 ms bloom."""
    return _voice(freq, dur, harmonics=8, bright=1.0, decay=decay, attack=attack, hold=hold, detune=0.003)


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


def _air(dur, low=150, high=1100, rise=False):
    """Soft moving air (low-passed noise): a swell, or a rise that peaks at the end."""
    t = _t(dur)
    env = (t / dur) ** 2 if rise else np.sin(np.pi * t / dur) ** 2
    return _filter(_noise(dur), low, high, order=3) * env


def _glide(f0, f1, dur, curve=4.0):
    """Phase of a sine sweeping from f0 to f1 (exponential)."""
    t = _t(dur)
    f = f1 + (f0 - f1) * np.exp(-t * curve)
    return 2 * np.pi * np.cumsum(f) / SR


def _riser(f0, octaves, dur, power=2.0):
    """A sine (plus fifth) rising `octaves` over dur, growing in."""
    t = _t(dur)
    f = f0 * 2 ** (octaves * t / dur)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) + 0.35 * np.sin(1.5 * ph)) * (t / dur) ** power


# Warm kit: every hit is band-limited below ~2.5 kHz and has a few ms of attack, so nothing
# cracks like a snare or hisses like a cymbal on a phone speaker.
def _kick(dur=0.45, punch=1.0):
    t = _t(dur)
    body = np.sin(_glide(160 * punch, 45, dur, 22)) * np.exp(-t * 7)
    knock = np.sin(2 * np.pi * 700 * t) * np.exp(-t * 160) * 0.12   # a tonal knock, not a noise click
    return _fade((body + knock) * np.clip(t / 0.002, 0, 1))


def _clap(dur=0.3):
    """Soft hand clap: three low-passed bursts and a short warm tail."""
    t = _t(dur)
    n = _filter(_noise(dur), 500, 1600, order=4)
    env = np.zeros_like(t)
    for off in (0.0, 0.012, 0.025):
        env += np.exp(-np.clip(t - off, 0, None) * 50) * np.clip((t - off) / 0.003, 0, 1)
    env += np.exp(-t * 16) * 0.4 * np.clip(t / 0.006, 0, 1)
    return _fade(n * env * 0.7)


def _hat(dur=0.07, open_=False):
    """A shaker rather than a hi-hat: band-limited, rounded attack."""
    t = _t(dur if not open_ else 0.3)
    n = _filter(_noise(len(t) / SR), 1400, 2400, order=4)
    return _fade(n * np.exp(-t * (16 if open_ else 55)) * np.clip(t / 0.004, 0, 1))


def _crash(dur=2.5):
    """Cymbal stand-in: a slow glassy shimmer of sine partials (no noise), blooming in 25 ms."""
    t = _t(dur)
    shimmer = sum(a * np.sin(2 * np.pi * f * t + i) for i, (f, a) in
                  enumerate(((1046.5, 0.5), (1318.5, 0.35), (1568.0, 0.3), (2093.0, 0.15))))
    return _fade(shimmer * np.exp(-t * 2.2) * np.clip(t / 0.025, 0, 1) * 0.6)


def _mallet(freq, dur=0.35):
    """Soft felt-mallet timpani hit: round sine partials, a 6 ms attack, nothing above 1 kHz."""
    t = _t(dur)
    out = sum(a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t * d)
              for r, a, d in ((1.0, 1.0, 9), (1.5, 0.3, 14), (2.0, 0.12, 18)))
    return _fade(out * np.clip(t / 0.006, 0, 1))


def _thump(dur=0.5, freq=70.0):
    """Heartbeat / spotlight thump: a low sine that drops a little, no click."""
    t = _t(dur)
    return _fade(np.sin(_glide(freq * 1.4, freq, dur, 18)) * np.exp(-t * 9) * np.clip(t / 0.004, 0, 1))


def _crowd(dur=2.6, density=90):
    """A soft crowd swell: many low-passed clap grains, rising and falling."""
    n = int(SR * dur)
    grains = np.zeros(n)
    count = int(density * dur)
    pos = _rng.integers(0, n, count)
    np.add.at(grains, pos, _rng.uniform(0.3, 1.0, count))
    kern = np.exp(-_t(0.03) * 140)
    clap = np.fft.irfft(np.fft.rfft(grains, 2 * n) * np.fft.rfft(kern, 2 * n), 2 * n)[:n]
    tone = _filter(_noise(dur), 400, 1700, order=4)
    t = _t(dur)
    return _fade(clap * tone * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5, 0.3)


@lru_cache(maxsize=48)
def _room(seconds, size):
    """Spectra (size-point rfft, both channels) of the warm room's impulse responses: one pair
    per length, shared by every cue."""
    ir_len = int(SR * seconds)
    rng = np.random.default_rng(int(seconds * 1000))
    irs = np.stack([_filter(rng.normal(0, 1, ir_len), 200, 4000) for _ in range(2)], axis=1)
    irs *= np.exp(-np.arange(ir_len) / SR * 4.5 / seconds)[:, None]
    irs /= np.sqrt(np.sum(irs ** 2, axis=0))
    spec = np.fft.rfft(irs, size, axis=0)
    spec.setflags(write=False)
    return spec


def _reverb(x, seconds=1.6, wet=0.22):
    """Convolution with a decaying-noise impulse per channel (a warm room). Returns (n, 2) stereo."""
    ir_len = int(SR * seconds)
    n = len(x) + ir_len
    size = 1 << (n - 1).bit_length()
    tail = np.fft.irfft(np.fft.rfft(x, size)[:, None] * _room(seconds, size), size, axis=0)[:n]
    st = tail * wet
    st[:len(x)] += x[:, None]
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


def _finish(parts, room=1.4, wet=0.22, length=None):
    """Mix the parts, put them in the room (stereo tail)."""
    return _reverb(_mix(*parts, length=length).mean(axis=1), room, wet)


@lru_cache(maxsize=8)
def _kgain(n):
    """ITU-R BS.1770 K-weighting (pre-filter shelf + RLB high-pass) as a magnitude response for
    an n-point rfft. The 48 kHz biquads are evaluated at f / 48000, so the curve in Hz is the
    standard one at any sample rate."""
    z = np.exp(1j * 2 * np.pi * np.fft.rfftfreq(n, 1 / SR) / 48000)

    def biquad(b, a):
        return (b[0] + b[1] / z + b[2] / z ** 2) / (a[0] + a[1] / z + a[2] / z ** 2)
    h = biquad((1.53512485958697, -2.69169618940638, 1.19839281085285),
               (1.0, -1.69065929318241, 0.73248077421585))
    return np.abs(h * biquad((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621)))[:, None]


def _db(v):
    return float(20 * np.log10(v + 1e-9))


def _lufs(st):
    """(integrated, momentary max) loudness in LUFS: K-weighted, 400 ms blocks, BS.1770 gating."""
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    size = 1 << max(len(st), blk).bit_length()          # power-of-two FFTs, few distinct sizes
    k = np.fft.irfft(np.fft.rfft(st, size, axis=0) * _kgain(size), size, axis=0)[:max(len(st), blk)]
    power = np.cumsum(np.concatenate([[0.0], np.sum(k ** 2, axis=1)]))
    starts = np.arange(0, len(k) - blk + 1, hop)
    ms = (power[starts + blk] - power[starts]) / blk
    lk = -0.691 + 10 * np.log10(ms + 1e-12)
    gated = ms[lk > -70]
    if not len(gated):
        return -99.0, float(np.max(lk))
    rel = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    return float(-0.691 + 10 * np.log10(np.mean(ms[(lk > -70) & (lk > rel)]))), float(np.max(lk))


def measure(st: np.ndarray) -> dict[str, float]:
    """How a stereo buffer is heard: peak and RMS (dBFS), integrated and momentary-max loudness
    (LUFS, BS.1770 gating), the share of energy above 3 kHz, and the loudest 30 ms above 3 kHz
    (dBFS RMS): the last two catch hissy, snare-like transients."""
    integrated, loudest = _lufs(st)
    mono = st.mean(axis=1)
    spec = np.fft.rfft(mono)
    f = np.fft.rfftfreq(len(mono), 1 / SR)
    p = np.abs(spec) ** 2
    spec[f < 3000] = 0
    high = np.fft.irfft(spec, len(mono))
    n = min(int(0.03 * SR), len(high))
    e = np.cumsum(np.concatenate([[0.0], high ** 2]))
    return {"peak": _db(np.max(np.abs(st))), "rms": _db(np.sqrt(np.mean(st ** 2))),
            "lufs": integrated, "lufs_max": loudest,
            "hf_share": float(p[f >= 3000].sum() / max(p.sum(), 1e-12)),
            "hf_peak": _db(np.sqrt(np.max(e[n:] - e[:-n]) / n)),
            "seconds": len(st) / SR}


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


def _ep_chord(names, dur, decay=2.0):
    return sum(_epiano(hz(n), dur, decay) for n in names) / len(names)


def _brass_chord(names, dur, decay=2.0, hold=0.0):
    return sum(_brass(hz(n), dur, decay, hold) for n in names) / len(names)


def _pad(names, dur, attack=0.3):
    return _chord(names, dur, harmonics=5, bright=0.3, decay=0.3, attack=attack, detune=0.004)


# ------------------------------------------
# THE BRAND MOTIF: "the LIFE-long QUIZ"
# ------------------------------------------
MOTIF_TIMES = (0.0, 0.13, 0.27, 0.54)          # pick-up, LIFE, long, QUIZ (seconds at speed 1)
MOTIF = {"question": ("G4", "C5", "E5", "D5"),  # open: the show is asking
         "answer": ("G4", "C5", "E5", "G5"),    # home: the show resolves
         "head": ("G4", "C5", "E5")}            # a fragment for stings


def _motif(form="answer", voice=None, start=0.0, speed=1.0, gain=1.0, octave=0, last=1.2):
    """The motif as mix parts, in any voice (a function freq, dur -> mono), tempo or octave."""
    voice = voice or (lambda f, d: _brass(f, d, decay=2.5))
    parts = []
    for i, (n, t0) in enumerate(zip(MOTIF[form], MOTIF_TIMES)):
        dur = last if i == 3 else 0.35 * speed + 0.1
        parts.append((start + t0 * speed, voice(hz(n) * 2 ** octave, dur), gain * (1.0 if i in (1, 3) else 0.72)))
    return parts


# ------------------------------------------
# MUSIC
# ------------------------------------------
_PROG_LOBBY = [("A2", ["A3", "C4", "E4", "G4"]), ("F2", ["F3", "A3", "C4", "E4"]),
               ("C3", ["G3", "C4", "E4", "G4"]), ("G2", ["G3", "B3", "D4", "F#4"])]


def _music_lobby():
    """Inviting mid-tempo groove: four-on-the-floor, shaker, funky bass, chord stabs, the motif on bells."""
    bars = 8
    parts = []
    kick, clap, hat, ohat = _kick(punch=0.9), _clap(), _hat(), _hat(open_=True)
    for bar in range(bars):
        root, chord = _PROG_LOBBY[(bar // 2) % 4]
        b0 = bar * BAR
        for beat in range(4):
            parts.append((b0 + beat * BEAT, kick, 0.35))
            parts.append((b0 + beat * BEAT + BEAT / 2, hat if beat != 3 else ohat, 0.16))
            if beat in (1, 3):
                parts.append((b0 + beat * BEAT, clap, 0.24))
        for pos, octave in ((0, 1), (0.75, 1), (1.5, 2), (2.0, 1), (2.5, 2), (3.25, 1)):
            f = hz(root) * octave
            parts.append((b0 + pos * BEAT, _voice(f, 0.32, harmonics=8, bright=1.6, decay=7), 0.42))
        stab = _chord(chord, 0.28, harmonics=12, bright=1.4, decay=9, detune=0.004)
        for pos in (1.5, 3.5):
            parts.append((b0 + pos * BEAT, _mono_to_st(stab, -0.25), 0.36))
        if bar % 2 == 0:
            pad = _chord(chord, BAR * 2, harmonics=5, bright=0.3, decay=0.25, attack=0.35, detune=0.003)
            parts.append((b0, _mono_to_st(pad, 0.3), 0.22))
        if bar % 4 == 3:   # the brand on bells, end of every phrase
            parts += _motif("answer", lambda f, d: _bell(f, d + 0.4, 4), b0 + 2 * BEAT, 1.0, 0.12, octave=1, last=0.9)
    return _loop_reverb(_loop_mix(parts, bars).mean(axis=1), 1.2, 0.14)


_PROG_QUESTION = [("A1", ["A3", "C4", "E4"]), ("A1", ["A3", "C4", "F4"]),
                  ("F1", ["F3", "A3", "C4"]), ("E1", ["E3", "G#3", "B3"])]


def _music_question():
    """Thinking music: pulsing low bass on eighths, a wooden clock, dark pad, E chord suspense."""
    bars = 4
    parts = []
    tick, tock = _marimba(hz("E6"), 0.06, 40) * 0.5, _marimba(hz("A5"), 0.08, 30) * 0.6
    kick = _kick(0.5, punch=0.7)
    for bar, (root, chord) in enumerate(_PROG_QUESTION):
        b0 = bar * BAR
        parts.append((b0, kick, 0.22))
        parts.append((b0 + 2.5 * BEAT, kick, 0.1))
        for e in range(8):
            accent = 1.0 if e % 2 == 0 else 0.7
            parts.append((b0 + e * BEAT / 2,
                          _voice(hz(root) * 2, 0.2, harmonics=6, bright=2.0, decay=10), 0.33 * accent))
        for beat in range(4):
            parts.append((b0 + beat * BEAT, _mono_to_st(tick if beat % 2 else tock, 0.4), 0.22))
        pad = _chord(chord, BAR, harmonics=4, bright=0.4, decay=0.4, attack=0.25, detune=0.004)
        parts.append((b0, _mono_to_st(pad, -0.3), 0.3))
    return _loop_reverb(_loop_mix(parts, bars).mean(axis=1), 1.0, 0.12)


def _music_question_tension():
    """Layer over the question bed, same length and chords: a sixteenth marimba ostinato, a
    swelling low string, timpani on 1 and 3. Its volume follows logic.buildup_intensity."""
    bars = 4
    parts = []
    for bar, (root, chord) in enumerate(_PROG_QUESTION):
        b0 = bar * BAR
        hi = [hz(chord[2]) * 2, hz(chord[0]) * 2]
        for s in range(16):
            parts.append((b0 + s * BEAT / 4, _marimba(hi[s % 2], 0.12, 20), 0.18 + 0.08 * (s % 4 == 0)))
        for beat in (0, 2):
            parts.append((b0 + beat * BEAT, _mallet(hz(root) * 2, 0.45), 0.5))
        string = _voice(hz(root) * 2, BAR, harmonics=6, bright=0.4, decay=0.2, attack=BAR * 0.8, detune=0.004)
        parts.append((b0, _mono_to_st(string, 0.35), 0.35))
    return _loop_reverb(_loop_mix(parts, bars).mean(axis=1), 1.0, 0.12)


def _music_reveal():
    """Results bed: a light half-time groove under the answer, the fastest players and the
    standings. C - Am - F - G on electric piano, soft kick and shaker, the motif tail on bells."""
    bars = 4
    parts = []
    prog = [("C2", ["C4", "E4", "G4", "D5"]), ("A1", ["A3", "C4", "E4", "G4"]),
            ("F1", ["F3", "A3", "C4", "E4"]), ("G1", ["G3", "B3", "D4", "F4"])]
    kick, hat = _kick(0.4, punch=0.8), _hat()
    for bar, (root, chord) in enumerate(prog):
        b0 = bar * BAR
        for beat in (0, 2):
            parts.append((b0 + beat * BEAT, kick, 0.22))
        for e in range(8):
            parts.append((b0 + e * BEAT / 2, hat, 0.08 if e % 2 else 0.05))
        ep = _ep_chord(chord, 1.6, 1.6)
        parts.append((b0, _mono_to_st(ep, -0.2), 0.42))
        parts.append((b0 + 2.5 * BEAT, _mono_to_st(_ep_chord(chord, 0.9, 3), -0.2), 0.25))
        parts.append((b0, _epiano(hz(root) * 2, BAR, 0.8), 0.4))
        parts.append((b0 + 2 * BEAT, _epiano(hz(root) * 3, BEAT * 2, 1.2), 0.22))
    parts += _motif("answer", lambda f, d: _bell(f, d + 0.4, 4), 3 * BAR + 2 * BEAT, 1.0, 0.1, octave=1, last=0.9)
    return _loop_reverb(_loop_mix(parts, bars).mean(axis=1), 1.4, 0.18)


# ------------------------------------------
# ONE-SHOTS (each takes a variant index v)
# ------------------------------------------
def _sfx_final_countdown(v=0, dur=5.0):
    """Last five seconds, soft: a lub-dub heartbeat on every second (timed like motion.heartbeat)
    and a gentle A minor pad that rises with it. No noise."""
    t = _t(dur)
    pad = _pad(["A3", "C4", "E4"], dur, attack=dur * 0.9) * (t / dur)
    parts = [(0, pad, 0.5), (0, _riser(hz("A3"), 1.0, dur, 2.2), 0.08)]
    for s in range(5):
        k = 1 + s * 0.08
        parts.append((s, _thump(0.4, 62), 0.7 * k))
        parts.append((s + 0.22, _thump(0.4, 58), 0.42 * k))
    return _finish(parts, 0.9, 0.12, length=int(dur * SR))


def _sfx_countdown(v=0):
    """A soft wooden tick on each of the last five seconds."""
    return _mono_to_st(_marimba(hz(("A5", "E5")[v]), 0.2, 16))


def _sfx_tick_soft(v=0):
    return _mono_to_st(_marimba(hz(("E5", "C5")[v]), 0.12, 28))


def _sfx_times_up(v=0):
    """Time's up: a felt hit and a two-note horn on the fifth (A minor)."""
    horn = _brass_chord(["E4", "A4"], 0.6, decay=4)
    return _finish([(0, _kick(0.8, 1.3), 0.6), (0, _mallet(hz("A2"), 0.8), 0.5), (0, horn, 0.55)], 1.4, 0.25)


def _sfx_drumroll(dur=4.0):
    """Soft timpani roll (A and E, the key's root and fifth) that swells gently while the
    last answers lock in, then eases off just before the reveal so the stinger lands on air."""
    hits = []
    step = 1 / 14
    n = int(dur / step)
    low, high = _mallet(hz("A2")), _mallet(hz("E3"))
    for i in range(n):
        k = i / n
        swell = 0.25 + 0.75 * k ** 1.3
        ease = min(1.0, (n - i) / (0.25 * 14))   # last 0.25 s fades down
        hits.append((i * step + _rng.uniform(-0.005, 0.005), low if i % 2 else high,
                     swell * ease * _rng.uniform(0.85, 1.0)))
    t = _t(dur)
    drone = np.sin(2 * np.pi * hz("A1") * t) * 0.25 * (t / dur) ** 1.5   # felt under the roll
    hits.append((0, drone, 1.0))
    return _reverb(_mix(*hits, length=int(dur * SR)).mean(axis=1), 0.8, 0.12)[:int(dur * SR)]


def _sfx_reveal_sweep(v=0):
    """The answer split fills: a marimba run accelerating up A minor into the stinger."""
    notes = ("A4", "C5", "D5", "E5", "G5", "A5")
    times = (0.0, 0.2, 0.36, 0.49, 0.59, 0.67)
    parts = [(tt, _marimba(hz(n), 0.4, 9), 0.3 + 0.06 * i) for i, (n, tt) in enumerate(zip(notes, times))]
    parts.append((0, _air(0.8, 200, 1200, rise=True), 0.25))
    return _finish(parts, 1.0, 0.18)


_CORRECT_VOICINGS = (("C4", "E4", "G4", "C5"), ("E4", "G4", "C5", "E5"), ("C4", "G4", "D5", "E5"))


def _sfx_correct(v=0):
    """Right answers: the motif's ending (E5 -> G5) on brass over a warm C major chord,
    a shimmer and a sparkle arpeggio."""
    parts = [(0, _crash(), 0.3), (0, _kick(0.6, 1.1), 0.6), (0, _mallet(hz("C2"), 0.8), 0.5),
             (0, _ep_chord(_CORRECT_VOICINGS[v], 1.8, 1.6), 0.8),
             (0, _brass(hz("E5"), 0.3, 4), 0.35), (0.13, _brass(hz("G5"), 1.2, 2.2), 0.45)]
    sparkle = ("C5", "E5", "G5", "C6") if v != 1 else ("G5", "E5", "G5", "C6")
    for i, n in enumerate(sparkle):
        parts.append((0.2 + i * 0.07, _bell(hz(n), 1.0, 4), 0.22))
    return _finish(parts, 1.8, 0.25)


def _sfx_wrong(v=0):
    """Nobody got it: a gentle marimba fall in A minor over a low A (sympathetic, not a buzzer)."""
    notes = (("E5", "C5", "A4"), ("C5", "A4", "E4"))[v]
    parts = [(0, _kick(0.6, 0.8), 0.4), (0.4, _ep_chord(["A2", "E3", "C4"], 1.6, 1.4), 0.6)]
    for i, n in enumerate(notes):
        parts.append((i * 0.2, _marimba(hz(n), 0.8, 5), 0.5))
    return _finish(parts, 1.5, 0.22)


def _sfx_new_question(v=0):
    """Question appears: a soft rising two-note chime (it plays every question)."""
    a, b = (("G5", "C6"), ("E5", "G5"), ("C5", "G5"))[v]
    return _finish([(0, _bell(hz(a), 1.0, 4), 0.5), (0.09, _bell(hz(b), 1.2, 3.5), 0.45)], 1.4, 0.25)


def _sfx_whoosh(v=0):
    """State change: soft air across the stereo field (direction and colour vary)."""
    t = _t(0.45)
    env = np.sin(np.pi * t / 0.45) ** 2
    lo, hi = ((150, 1100), (120, 900), (180, 1300))[v]
    n = _filter(_noise(0.45), lo, hi, order=3) * env
    pan = np.linspace(-0.8, 0.8, len(t)) * (1 if v % 2 == 0 else -1)
    return np.stack([n * np.cos((pan + 1) * np.pi / 4), n * np.sin((pan + 1) * np.pi / 4)], axis=1)


def _sfx_match_open(v=0):
    """The colour iris (last 1.5 s of the lobby): air swells, the motif's question form plays on
    bells as the logo draws on, and hangs on D for show_open to resolve at the state change."""
    parts = [(0, _air(1.5, 200, 1200, rise=True), 0.4), (0, _riser(hz("G3"), 1.0, 1.5, 2.0), 0.12)]
    parts += _motif("question", lambda f, d: _bell(f, d + 0.4, 3.5), 0.4, 1.0, 0.4, octave=1, last=1.1)
    parts.append((0.4, _pad(["G3", "C4", "D4"], 1.2, 0.4), 0.25))
    return _finish(parts, 1.4, 0.25)


def _sfx_show_open(v=0):
    """INTRO: the motif resolves (G5 over C add9, timpani, shimmer), then soft 3-2-1 ticks
    climbing G A B towards question 1's C."""
    parts = [(0, _brass_chord(["C4", "E4", "G4", "D5"], 2.2, 1.3, 0.3), 0.8), (0, _brass(hz("G5"), 1.6, 1.6), 0.4),
             (0, _kick(0.8, 1.3), 0.8), (0, _mallet(hz("C2"), 1.0), 0.7), (0, _crash(), 0.35)]
    for i, n in enumerate(("G5", "A5", "B5")):
        parts.append((1.0 + i, _marimba(hz(n), 0.3, 12), 0.22))
    return _finish(parts, 1.8, 0.25)


def _sfx_fanfare(v=0):
    """PODIUM: the motif in full on brass into a held C major, with a timpani roll."""
    parts = _motif("answer", lambda f, d: _brass(f, d, 2.0), 0.0, 1.0, 0.7, last=1.6)
    parts.append((0.54, _brass_chord(["C4", "E4", "G4", "C5"], 2.4, 1.0, 0.6), 0.75))
    parts.append((0.54, _crash(), 0.3))
    for i in range(10):   # timpani roll under the held chord
        parts.append((0.54 + i * 0.07, _mallet(hz("C2"), 0.4), 0.35 * (1 - i / 12)))
    return _finish(parts, 2.0, 0.28)


def _sfx_podium(place):
    """A spotlight switches on: 3rd one bell, 2nd two, 1st the full chord, bells and a crowd."""
    parts = [(0, _thump(0.6, 55), 0.7), (0, _mallet(hz("C2"), 0.6), 0.4)]
    if place == 3:
        parts += [(0, _bell(hz("E5"), 1.2, 3), 0.4), (0, _ep_chord(["C4", "E4"], 1.2, 2), 0.3)]
    elif place == 2:
        parts += [(0, _bell(hz("E5"), 1.2, 3), 0.4), (0.12, _bell(hz("G5"), 1.3, 3), 0.4),
                  (0, _ep_chord(["E4", "G4"], 1.4, 2), 0.35)]
    else:
        parts += [(0, _brass_chord(["C4", "E4", "G4", "C5", "E5"], 2.6, 0.9, 0.7), 0.8), (0, _crash(), 0.35)]
        parts += [(0.35 + i * 0.08, _bell(hz(n), 1.2, 3.5), 0.3) for i, n in enumerate(("G5", "C6", "E6"))]
        parts.append((0.4, _crowd(2.6), 0.6))
    return _finish(parts, 1.8, 0.26)


def _sfx_final_curtain(v=0):
    """'AND THE WINNER IS': five felt thumps as the panels drop, then three rising timpani dots."""
    parts = [(i * 0.05, _thump(0.5, 50 + i * 4), 0.4 * (1 - i * 0.12)) for i in range(5)]
    for i, (lo, hi) in enumerate((("G2", "G4"), ("B2", "B4"), ("D3", "D5"))):
        tt = 0.79 + i * 0.275
        parts += [(tt, _mallet(hz(lo), 0.5), 0.5 + 0.1 * i), (tt, _marimba(hz(hi), 0.4, 9), 0.2)]
    return _finish(parts, 1.4, 0.22)


def _sweep(roll_at, land, brand=False):
    """Bands wipe across (air), the numeral rolls (marimba ticks), the card lands (a pluck)."""
    parts = [(0, _air(0.5, 150, 1100), 0.6)]
    for i, n in enumerate(("C5", "D5", "E5", "G5")):
        parts.append((roll_at + i * 0.08, _marimba(hz(n), 0.25, 14), 0.22 + 0.03 * i))
    parts.append((roll_at + 0.32, _ep_chord(land, 1.2, 2.2), 0.45))
    if brand:
        parts += _motif("head", lambda f, d: _brass(f, d, 3), roll_at + 0.32, 0.8, 0.35)
        parts.append((roll_at + 0.32, _mallet(hz("C2"), 0.6), 0.4))
    return _finish(parts, 1.2, 0.2)


def _sfx_question_sweep(v=0):
    return _sweep(0.48, (("C5", "G5"), ("E5", "C6"))[v])


def _sfx_event_sweep(v=0):
    return _sweep(0.88, ("C5", "G5"), brand=True)


def _sfx_next_match(v=0):
    """PODIUM to LOBBY: the sweep, then the motif's question form: here we go again."""
    parts = [(0, _air(0.5, 150, 1100), 0.6)]
    parts += _motif("question", lambda f, d: _marimba(f, d, 6), 0.48, 0.8, 0.4, octave=1, last=0.8)
    return _finish(parts, 1.3, 0.22)


def _sfx_points_fly(n):
    """+points fly from the right answer to a player's row (0.5 s), and land with a pluck
    that climbs per row: E5, G5, C6."""
    land = hz(("E5", "G5", "C6")[n - 1])
    t = _t(0.48)
    fly = np.sin(_glide(land * 0.5, land, 0.48, 6)) * (t / 0.48) ** 1.5 * 0.25
    return _finish([(0, fly, 1.0), (0.5, _marimba(land, 0.5, 8), 0.5), (0.5, _bell(land * 2, 0.6, 6), 0.12)], 0.9, 0.16)


def _sfx_standings_move(v=0):
    """The standings re-order: a quick marimba ripple and a plink as the arrows appear."""
    notes = (("C5", "E5", "G5", "A5"), ("D5", "E5", "G5", "C6"))[v]
    parts = [(i * 0.09, _marimba(hz(n), 0.35, 10), 0.3) for i, n in enumerate(notes)]
    parts += [(0, _air(0.4, 200, 1200), 0.25), (0.5, _bell(hz("E6"), 0.6, 6), 0.15)]
    return _finish(parts, 1.0, 0.18)


def _sfx_halftime(v=0):
    """The halftime card: the bands sweep in, then the motif relaxed on electric piano over
    F maj7 -> C maj7."""
    parts = [(0, _air(0.4, 150, 1000), 0.5)]
    parts += _motif("answer", lambda f, d: _epiano(f, d + 0.4, 1.8), 0.35, 1.6, 0.5, last=1.6)
    parts += [(0.35, _pad(["F3", "A3", "C4", "E4"], 1.3, 0.2), 0.35), (1.25, _pad(["C3", "E3", "G3", "B3"], 2.0, 0.3), 0.35),
              (0.35, _kick(0.5, 0.8), 0.3)]
    return _finish(parts, 1.6, 0.25)


def _sfx_streak(v=0):
    notes = (("C5", "E5", "G5", "C6"), ("E5", "G5", "C6", "E6"), ("G4", "C5", "E5", "G5"))[v]
    parts = [(i * 0.06, _bell(hz(n), 0.6, 6), 0.6) for i, n in enumerate(notes)]
    return _finish(parts, 1.0, 0.2)


def _sfx_combo(v=0):
    """One combo step: a marimba note and its octave, a different step of the pentatonic each play."""
    n = hz(("C5", "D5", "E5", "G5")[v])
    return _finish([(0, _marimba(n, 0.4, 9), 0.5), (0.05, _marimba(n * 2, 0.35, 11), 0.3)], 0.8, 0.15)


def _sfx_rank_up(v=0):
    lo, hi = (("G4", "C5"), ("E4", "G4"))[v]
    parts = [(0, _brass(hz(lo), 0.2, 6), 0.5), (0.14, _brass_chord([hi, "E5" if v == 0 else "C5"], 0.9, 3), 0.6)]
    parts += [(0.14 + i * 0.05, _bell(hz(n), 0.8, 5), 0.22) for i, n in enumerate(("C6", "E6", "G6"))]
    return _finish(parts, 1.3, 0.22)


def _sfx_event(v=0):
    """Special event (double points, lightning, bonus): air rises into the motif head and a hit."""
    parts = [(0, _air(0.6, 200, 1200, rise=True), 0.35), (0, _riser(hz("G4"), 1.0, 0.6), 0.15)]
    parts += _motif("head", lambda f, d: _brass(f, d, 3), 0.3, 0.6, 0.45)
    parts += [(0.6, _brass_chord(["C4", "E4", "G4", "C5"], 1.3, 2.5), 0.8), (0.6, _kick(0.6, 1.2), 0.6),
              (0.6, _mallet(hz("C2"), 0.8), 0.5), (0.6, _crash(1.8), 0.25)]
    return _finish(parts, 1.6, 0.24)


def _sfx_round_sting(v=0):
    """Special-round bumper: the motif's question form on marimba over a short roll, landing
    on A minor add9 (a twist, not a triumph)."""
    parts = _motif("question", lambda f, d: _marimba(f, d, 6), 0.0, 1.0, 0.45, octave=1, last=0.9)
    parts += [(i * 0.06, _mallet(hz("A2"), 0.3), 0.15 + i * 0.03) for i in range(9)]
    parts += [(0.54, _ep_chord(["A3", "C4", "E4", "B4"], 1.6, 1.6), 0.6), (0.54, _crash(1.6), 0.25)]
    return _finish(parts, 1.5, 0.24)


def _sfx_power_up(v=0):
    parts = [(0, _riser(hz("C5"), 1.0, 0.5, 1.5), 0.25)]
    parts += [(0.1 + i * 0.06, _marimba(hz(n), 0.3, 10), 0.35) for i, n in enumerate(("C5", "E5", "G5", "C6"))]
    parts.append((0.55, _bell(hz("C6"), 0.9, 4), 0.35))
    return _finish(parts, 1.0, 0.2)


def _sfx_jackpot(v=0):
    """A big payout: a cascade of bells down two octaves of the pentatonic onto a brass C."""
    notes = ("G6", "E6", "D6", "C6", "A5", "G5", "E5", "D5", "C5", "G4")
    parts = [(i * 0.05, _bell(hz(n), 0.8, 5), 0.3) for i, n in enumerate(notes)]
    parts += [(0.5, _brass_chord(["C4", "E4", "G4", "C5"], 1.8, 1.5, 0.3), 0.75), (0.5, _kick(0.6, 1.1), 0.5),
              (0.5, _crash(), 0.3), (0.5, _crowd(2.0), 0.4)]
    return _finish(parts, 1.6, 0.25)


def _sfx_crowd(v=0):
    return _finish([(0, _crowd(2.6), 1.0)], 1.2, 0.2)


def _sfx_level_up(v=0):
    """The difficulty steps up: brass climbs a ladder G -> A minor -> B dim -> C."""
    chords = (["G3", "B3", "D4"], ["A3", "C4", "E4"], ["B3", "D4", "F4"], ["C4", "E4", "G4", "C5"])
    parts = [(i * 0.18, _brass_chord(c, 0.3 if i < 3 else 1.6, 4 if i < 3 else 1.6), 0.55 + 0.1 * i)
             for i, c in enumerate(chords)]
    parts += [(i * 0.18, _marimba(hz(n), 0.3, 10), 0.25) for i, n in enumerate(("G5", "A5", "B5", "C6"))]
    return _finish(parts, 1.4, 0.22)


def _sfx_team_win(v=0):
    parts = _motif("answer", lambda f, d: _brass(f, d, 2.0), 0.0, 0.9, 0.6, last=1.4)
    parts += [(0.5, _brass_chord(["C4", "E4", "G4", "C5"], 2.0, 1.2, 0.4), 0.6), (0.5, _crash(), 0.3),
              (0.4, _crowd(2.4), 0.6)]
    return _finish(parts, 1.6, 0.25)


def _sfx_answer_lock(v=0):
    """Soft bubble pop when someone answers (the landing pitch varies)."""
    land = (520, 587, 659, 784)[v]
    t = _t(0.07)
    return _mono_to_st(_fade(np.sin(_glide(land * 2.1, land, 0.07, 45)) * np.exp(-t * 55)))


def _sfx_vote(v=0):
    return _mono_to_st(_marimba(hz(("C6", "D6", "E6")[v]), 0.25, 14))


BUILDUP_STEPS = (0.0, 0.5, 1.0)           # pre-rendered intensities
BUILDUP_LENGTHS = (4.0, 6.0)               # BUILDUP_TIME: normal, final / big moments
STAKES_AT = 1.2                            # seconds into BUILDUP when the stakes land


def _sfx_buildup(v=0):
    """BUILDUP before a question: a riser into the stakes hit at 1.2 s, then a tension pulse
    that swells into the question. Intensity adds layers (Q1 light, Q10 full); still warm."""
    dur = BUILDUP_LENGTHS[v // len(BUILDUP_STEPS)]
    k = BUILDUP_STEPS[v % len(BUILDUP_STEPS)]
    parts = [(0, _air(STAKES_AT, 150, 1000 + 400 * k, rise=True), 0.35 + 0.2 * k),
             (0, _riser(hz("A2"), 1.0 + k, STAKES_AT, 2.0), 0.2 + 0.1 * k)]
    roll = int(6 + 10 * k)                 # timpani accelerating into the stakes
    for i in range(roll):
        tt = STAKES_AT * (1 - (1 - i / roll) ** 1.6)
        parts.append((tt, _mallet(hz("A2" if i % 2 else "E3"), 0.3), 0.15 + 0.3 * i / roll))
    pulse_t = np.arange(STAKES_AT + BEAT / 2, dur - 0.05, BEAT / (2 if k < 0.5 else 4))
    for i, tt in enumerate(pulse_t):      # the pulse after the stakes: A and E, growing
        g = (tt - STAKES_AT) / (dur - STAKES_AT)
        parts.append((tt, _marimba(hz("A4" if i % 2 == 0 else "E5"), 0.15, 16), (0.12 + 0.15 * g) * (0.7 + 0.3 * k)))
    if k > 0:                               # a heartbeat on the beat
        for tt in np.arange(STAKES_AT + BEAT, dur - 0.1, BEAT):
            parts.append((tt, _thump(0.35, 60), 0.3 * k))
    if k >= 0.5:                            # a low string swelling to the question
        swell = _voice(hz("A2"), dur - STAKES_AT, harmonics=6, bright=0.4, decay=0.1, attack=dur - STAKES_AT - 0.2,
                       detune=0.004)
        parts.append((STAKES_AT, swell, 0.3 * k))
    parts.append((dur - 0.9, _air(0.9, 150, 1200, rise=True), 0.25 + 0.2 * k))
    return _fade_st(_finish(parts, 1.2, 0.18, length=int(dur * SR))[:int(dur * SR)], 0.1)   # ends with the state


def _sfx_stakes(v=0):
    """The stakes land: the motif head on brass punched by timpani; the big version adds a full
    chord and the shimmer (picked by the build-up's intensity)."""
    parts = _motif("head", lambda f, d: _brass(f, d, 3), 0.0, 0.5, 0.5)
    parts += [(0.14, _mallet(hz("C2"), 0.8), 0.6), (0.14, _kick(0.6, 1.1), 0.5)]
    if v:
        parts += [(0.14, _brass_chord(["C4", "G4", "C5", "E5"], 1.4, 2.0), 0.6), (0.14, _crash(1.6), 0.25)]
    return _finish(parts, 1.4, 0.22)


# name: (render function, variants, target level in LUFS: the loudest 400 ms as heard)
BIG, MID, LOW, TINY = -23.5, -26.0, -29.0, -33.0
_SFX = {
    "correct": (_sfx_correct, 3, BIG), "show_open": (_sfx_show_open, 1, BIG), "fanfare": (_sfx_fanfare, 1, BIG),
    "podium_1": (lambda v: _sfx_podium(1), 1, BIG), "jackpot": (_sfx_jackpot, 1, BIG),
    "team_win": (_sfx_team_win, 1, BIG), "halftime": (_sfx_halftime, 1, BIG - 1), "stakes": (_sfx_stakes, 2, BIG),
    "wrong": (_sfx_wrong, 2, MID), "double_points": (_sfx_event, 1, MID), "round_sting": (_sfx_round_sting, 1, MID),
    "level_up": (_sfx_level_up, 1, MID), "podium_2": (lambda v: _sfx_podium(2), 1, MID),
    "podium_3": (lambda v: _sfx_podium(3), 1, MID - 1), "rank_up": (_sfx_rank_up, 2, MID),
    "streak": (_sfx_streak, 3, MID), "combo": (_sfx_combo, 4, MID - 1), "power_up": (_sfx_power_up, 1, MID),
    "crowd": (_sfx_crowd, 1, MID), "match_open": (_sfx_match_open, 1, MID), "final_curtain": (_sfx_final_curtain, 1, MID),
    "question_sweep": (_sfx_question_sweep, 2, LOW), "event_sweep": (_sfx_event_sweep, 1, MID),
    "next_match": (_sfx_next_match, 1, MID), "new_question": (_sfx_new_question, 3, MID - 1),
    "times_up": (_sfx_times_up, 1, MID - 1),
    "buildup": (_sfx_buildup, len(BUILDUP_STEPS) * len(BUILDUP_LENGTHS), None),
    "whoosh": (_sfx_whoosh, 3, LOW), "final_countdown": (_sfx_final_countdown, 1, LOW),
    "reveal_sweep": (_sfx_reveal_sweep, 1, LOW), "standings_move": (_sfx_standings_move, 2, LOW),
    "points_fly": (lambda v: _sfx_points_fly(1), 1, LOW), "points_fly_2": (lambda v: _sfx_points_fly(2), 1, LOW),
    "points_fly_3": (lambda v: _sfx_points_fly(3), 1, LOW),
    "answer_lock": (_sfx_answer_lock, 4, TINY), "vote": (_sfx_vote, 3, TINY), "countdown": (_sfx_countdown, 2, TINY),
    "tick_soft": (_sfx_tick_soft, 2, TINY - 2),
}
DRUMROLL_LEVEL = LOW
_MUSIC = {"lobby": (_music_lobby, -23.5), "question": (_music_question, -23.0),
          "question_tension": (_music_question_tension, -26.0), "reveal": (_music_reveal, -25.0)}
PEAK_CAP = 10 ** (-7 / 20)   # heard peak; the server's +3 dB still leaves 4 dB to its limiter


def _buildup_level(v):
    """Riser loudness rises with intensity: Q1 is light, the final question is full."""
    return -30.0 + 5.0 * BUILDUP_STEPS[v % len(BUILDUP_STEPS)]


def _level(st, target, integrated=False):
    """Scale to a loudness target (momentary max, or integrated for beds), capped in peak;
    one-shots lose their silent tail (mixer memory)."""
    lufs, loudest = _lufs(st)
    st = st * 10 ** ((target - (lufs if integrated else loudest)) / 20)
    peak = np.max(np.abs(st))
    st = st * (PEAK_CAP / peak) if peak > PEAK_CAP else st
    if integrated:   # a loop: never trimmed
        return st
    loud = np.nonzero(np.max(np.abs(st), axis=1) > 10 ** (-66 / 20))[0]   # drop the silent tail
    end = min(len(st), (loud[-1] if len(loud) else 0) + int(0.05 * SR))
    return _fade_st(st[:end].copy(), 0.05) if end < len(st) else st


def variant_key(name: str, v: int) -> str:
    return name if v == 0 else f"{name}~{v}"


# Which bed plays in which game state (None = music out, the moment belongs to the effects)
SCENE_MUSIC = {"WAITING": "lobby", "LOBBY": "lobby", "INTRO": None, "BUILDUP": None, "ASKING": "question",
               "LOCKING": None, "REVEALING": None, "PODIUM": "lobby"}
STINGERS = ("correct", "wrong")   # the reveal: drumroll ends, the results bed comes in under the stinger
# Beds duck under these (gain while the sting rings); everything else plays over the bed
DUCK = {**{n: 0.5 for n in ("correct", "show_open", "fanfare", "podium_1", "jackpot", "team_win", "stakes")},
        **{n: 0.7 for n in ("halftime", "wrong", "double_points", "round_sting", "level_up", "podium_2", "podium_3",
                            "event_sweep", "rank_up", "crowd")}}
# Minimum spacing per cue (s): repeats inside it are dropped (chat bursts, a cue queued twice)
COOLDOWN = {"answer_lock": 0.15, "vote": 0.3, "tick_soft": 0.2, "countdown": 0.5, "combo": 0.25, "streak": 0.4}
DEFAULT_COOLDOWN = 0.8


def _to_sound(st: np.ndarray) -> pygame.mixer.Sound:
    channels = (pygame.mixer.get_init() or (SR, -16, 2))[2]
    data = np.clip(st, -1, 1)
    data = data.mean(axis=1, keepdims=True) if channels == 1 else data
    pcm = np.ascontiguousarray((data * 32767).astype(np.int16))
    return pygame.sndarray.make_sound(pcm)


_CACHE_DIR = Path(__file__).resolve().parent.parent / "data"


def load_or_render(drumroll_seconds: float) -> dict[str, np.ndarray]:
    """Rendering takes seconds on a busy CPU; keep the result next to the database.
    The cache name hashes this file, so any change to the sound design re-renders."""
    digest = hashlib.sha1(Path(__file__).read_bytes() + str(drumroll_seconds).encode()).hexdigest()[:12]
    path = _CACHE_DIR / f"sounds_{digest}.npz"
    try:
        with np.load(path) as cached:
            return {k: cached[k].astype(np.float32) / 32767 for k in cached.files}
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
    """Every effect (variants as 'name~k') and music bed ('music_name') as stereo float arrays,
    levelled to their targets as heard."""
    out = {}
    for name, (fn, variants, target) in _SFX.items():
        for v in range(variants):
            out[variant_key(name, v)] = _level(fn(v), _buildup_level(v) if target is None else target)
    out["drumroll"] = _level(_sfx_drumroll(max(1.0, drumroll_seconds)), DRUMROLL_LEVEL)
    out.update({f"music_{name}": _level(fn(), target, integrated=True) for name, (fn, target) in _MUSIC.items()})
    return out


# ------------------------------------------
# CUES DERIVED FROM THE SHOW'S STATE AND CLOCK
# ------------------------------------------
def _ui_timing():
    """Reveal and podium choreography from the UI, so the cues follow the visuals; the values
    after `or` are the ones measured when this was written (2026-10-24)."""
    try:
        from quiz import ui_vertical as uv
        from quiz.transitions import Transitions
        lead = getattr(Transitions, "LEAD", {})
        podium = {place: cue for place, _x, _h, cue in getattr(uv.VerticalUI, "PODIUM", ())}
    except Exception:   # no UI (tools, tests): the measured values
        uv, lead, podium = None, {}, {}
    return {"split": getattr(uv, "T_SPLIT", 0.3), "panel": getattr(uv, "T_PANEL", 1.85),
            "reorder": getattr(uv, "T_REORDER", 4.85), "half": getattr(uv, "T_HALF", 3.9),
            "lead": {"question": 1.1, "question_event": 1.5, "match_open": 1.5, "final": 1.6, "next_match": 1.1, **lead},
            "podium": {0: podium.get(0, 3.0), 1: podium.get(1, 1.95), 2: podium.get(2, 0.9)}}


class ShowCues:
    """Cues the logic does not queue, derived each frame from logic.state and its clock, timed to
    the visuals in quiz/ui_vertical.py and quiz/transitions.py (docs/transitions.md). Each cue
    fires once per state visit."""

    def __init__(self):
        from quiz.config import BONUS_QUESTIONS, LIGHTNING_QUESTION, MATCH_LENGTH
        self.match_length, self.lightning, self.bonus = MATCH_LENGTH, LIGHTNING_QUESTION, BONUS_QUESTIONS
        self.timing = _ui_timing()
        self._visit = None
        self._fired: set[str] = set()

    def update(self, logic) -> list[str]:
        state = getattr(logic.state, "name", str(logic.state))
        visit = (state, logic.state_start_time)
        if visit != self._visit:
            self._visit, self._fired = visit, set()
        rem = logic.state_timer
        age = logic.state_duration - rem
        out: list[str] = []

        def at(name, due):
            if due and name not in self._fired:
                self._fired.add(name)
                out.append(name)

        tm, q = self.timing, getattr(logic, "q_index", 0)
        if state == "BUILDUP":
            at("buildup", True)
            at("stakes", age >= STAKES_AT)
        elif state == "LOBBY":
            at("match_open", 0 < rem <= tm["lead"]["match_open"])
        elif state == "REVEALING":
            at("reveal_sweep", age >= tm["split"])
            res = getattr(logic, "last_result", None)
            for i in range(min(3, len(getattr(res, "correct_players", None) or ()))):
                at(("points_fly", "points_fly_2", "points_fly_3")[i], age >= tm["panel"] + 0.35 + i * 0.13)
            if q == self.match_length // 2:
                at("halftime", age >= tm["half"])
            elif getattr(logic, "standings", None):
                at("standings_move", age >= tm["reorder"])
            if q >= self.match_length:
                at("final_curtain", 0 < rem <= tm["lead"]["final"])
            elif not hasattr(type(logic.state), "BUILDUP"):   # with BUILDUP, the build-up owns this moment
                n = q + 1
                event = n == self.match_length or n == self.lightning or n in self.bonus or \
                    bool(getattr(logic, "special_slots", {}).get(n))
                lead = tm["lead"]["question_event" if event else "question"]
                at("event_sweep" if event else "question_sweep", 0 < rem <= lead)
        elif state == "PODIUM":
            podium = getattr(logic, "podium", None) or ()
            for place in (2, 1, 0):
                if len(podium) > place:
                    at(f"podium_{place + 1}", age >= tm["podium"][place])
            at("next_match", 0 < rem <= tm["lead"]["next_match"])
        return out


# ------------------------------------------
# PLAYBACK
# ------------------------------------------
class SoundManager:
    """Generates the show's sounds in the background and plays them by game state."""

    MUSIC_VOLUME = 1.0
    MUSIC_FADE_MS = 900
    DUCK_ATTACK, DUCK_RELEASE = 0.5, 0.06   # per-frame approach to the ducked / full level

    def __init__(self, drumroll_seconds: float = 4.0):
        self._enabled = False
        self._sounds: dict[str, list[pygame.mixer.Sound]] = {}
        self._last_play_time: dict[str, float] = {}
        self._last_variant: dict[str, int] = {}
        self._music: dict[str, pygame.mixer.Sound] = {}
        self._scene_bed = None
        self._wanted_bed = "lobby"
        self._drumroll_seconds = drumroll_seconds
        self._duck_until, self._duck_depth, self._duck = 0.0, 1.0, 1.0
        self._tension, self._intensity = 0.0, 0.0
        self._applied: tuple | None = None
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=1024)
        except pygame.error:
            print("[Sound] Mixer init failed, sounds disabled")
            return
        pygame.mixer.set_num_channels(22)
        pygame.mixer.set_reserved(5)
        self._bed_channels = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
        self._roll_channel = pygame.mixer.Channel(2)
        self._layer_channel = pygame.mixer.Channel(3)   # the question bed's tension layer
        self._riser_channel = pygame.mixer.Channel(4)   # the BUILDUP riser
        self._enabled = True
        threading.Thread(target=self._generate, daemon=True).start()

    def _generate(self):
        try:
            began = time.monotonic()
            arrays = load_or_render(self._drumroll_seconds)
            sounds: dict[str, list] = {}
            for name in sorted(arrays, key=lambda k: (k.split("~")[0], int(k.split("~")[1]) if "~" in k else 0)):
                if name.startswith("music_"):
                    self._music[name[6:]] = _to_sound(arrays[name])
                else:
                    sounds.setdefault(name.split("~")[0], []).append(_to_sound(arrays[name]))
            self._sounds = sounds
            print(f"[Sound] {len(arrays)} sounds ready in {time.monotonic() - began:.1f}s")
        except Exception as e:
            print(f"[Sound] Generation failed: {e}")

    @property
    def music_ready(self) -> bool:
        return bool(self._music)

    def start_music(self):
        self._apply_bed()

    def set_scene(self, state_name: str):
        """Called on every game state change: switch the music bed, stop a finished roll or riser."""
        if not self._enabled:
            return
        if state_name not in ("LOCKING", "REVEALING"):
            self._roll_channel.fadeout(150)
        if state_name != "BUILDUP":
            self._riser_channel.fadeout(250)
        self._wanted_bed = SCENE_MUSIC.get(state_name, "lobby")
        self._apply_bed()

    def _apply_bed(self):
        if not self._enabled or not self._music or self._wanted_bed == self._scene_bed:
            return
        old, new = self._bed_channels
        if self._scene_bed:
            old.fadeout(self.MUSIC_FADE_MS if self._wanted_bed else 250)
        if self._scene_bed == "question":
            self._layer_channel.fadeout(self.MUSIC_FADE_MS if self._wanted_bed else 250)
        self._scene_bed = self._wanted_bed
        if self._wanted_bed:
            new.play(self._music[self._wanted_bed], loops=-1, fade_ms=self.MUSIC_FADE_MS)
            layer = self._music.get("question_tension")
            if self._wanted_bed == "question" and layer:   # same length, started together: in sync
                self._layer_channel.play(layer, loops=-1, fade_ms=self.MUSIC_FADE_MS)
            self._bed_channels = [new, old]
        self._applied = None

    def stop_music(self):
        if self._enabled:
            for ch in (*self._bed_channels, self._layer_channel):
                ch.fadeout(1000)
            self._scene_bed = None

    def set_tension(self, intensity: float):
        """0..1 (logic.buildup_intensity): how much of the tension layer sits on the question bed."""
        self._tension = min(1.0, max(0.0, float(intensity or 0.0)))

    def update(self):
        """Once per frame: ride the bed volumes (ducking, tension). Touches the mixer only when a
        level moves, so a steady frame costs two float compares."""
        if not self._enabled or not self._music:
            return
        target = self._duck_depth if time.monotonic() < self._duck_until else 1.0
        rate = self.DUCK_ATTACK if target < self._duck else self.DUCK_RELEASE
        self._duck += (target - self._duck) * rate
        if abs(target - self._duck) < 0.005:
            self._duck = target
        levels = (round(self._duck, 3), round(self._tension, 3))
        if levels == self._applied:
            return
        self._applied = levels
        for name, snd in self._music.items():
            snd.set_volume(self.MUSIC_VOLUME * self._duck * (self._tension if name == "question_tension" else 1.0))

    def play(self, name: str, variant: int | None = None):
        """Play a cue by name; unknown names are ignored. Short cues pick a random voicing
        (never the same twice in a row); repeats inside COOLDOWN are dropped."""
        if not self._enabled:
            return
        variants = self._sounds.get(name)
        if not variants:
            return
        now = time.monotonic()
        if now - self._last_play_time.get(name, -1e9) < COOLDOWN.get(name, DEFAULT_COOLDOWN):
            return
        self._last_play_time[name] = now
        if variant is None:
            choices = [i for i in range(len(variants)) if i != self._last_variant.get(name)] or [0]
            variant = random.choice(choices)
        variant = min(max(0, variant), len(variants) - 1)
        self._last_variant[name] = variant
        sound = variants[variant]
        if name == "drumroll":
            self._roll_channel.play(sound)
            return
        if name == "buildup":
            self._riser_channel.play(sound)
        else:
            sound.play()
        if name in STINGERS:
            self._roll_channel.stop()
            self._wanted_bed = "reveal" if "reveal" in self._music else "lobby"
            self._apply_bed()
        if name in DUCK:
            self._duck_depth = DUCK[name] if now >= self._duck_until else min(self._duck_depth, DUCK[name])
            self._duck_until = max(self._duck_until, now + min(sound.get_length(), 2.5))

    def play_buildup(self, intensity: float, seconds: float):
        """The BUILDUP riser for this intensity (0..1) and state length; the stakes hit that
        follows uses the big voicing from intensity 0.5 up."""
        self._intensity = min(1.0, max(0.0, float(intensity or 0.0)))
        step = min(range(len(BUILDUP_STEPS)), key=lambda i: abs(BUILDUP_STEPS[i] - self._intensity))
        length = min(range(len(BUILDUP_LENGTHS)), key=lambda i: abs(BUILDUP_LENGTHS[i] - (seconds or 4.0)))
        self.play("buildup", length * len(BUILDUP_STEPS) + step)

    def play_stakes(self):
        self.play("stakes", 1 if self._intensity >= 0.5 else 0)


if __name__ == "__main__":  # pre-render the cache (quizctl update runs this before restarting the show)
    from quiz.config import LATE_ANSWER_GRACE, REVEAL_AT
    began = time.monotonic()
    arrays = load_or_render(LATE_ANSWER_GRACE + REVEAL_AT)
    print(f"[Sound] {len(arrays)} sounds cached in {time.monotonic() - began:.1f}s")
    print(f"{'cue':24}{'sec':>6}{'peak':>7}{'LUFSmax':>9}{'LUFS':>7}{'>3kHz':>7}")
    for name in sorted(arrays):
        m = measure(arrays[name])
        print(f"{name:24}{m['seconds']:6.2f}{m['peak']:7.1f}{m['lufs_max']:9.1f}{m['lufs']:7.1f}{m['hf_share']:7.1%}")
