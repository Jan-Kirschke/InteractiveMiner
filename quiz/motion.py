"""
The Lifelong Quiz - motion library
Every move on screen goes through these curves, so the show has one feel: things arrive fast
and settle (out-expo), physical objects overshoot a touch (out-back), stamps and medals land
with a spring. All take t in 0..1 and return 0 at t=0 and 1 at t=1 (out-back, out-elastic and
spring pass through 1 on the way); inputs outside 0..1 are clamped.

    p = progress(age, delay=0.2, dur=0.5)     # 0..1 window of a timeline
    y = lerp(start, end, out_expo(p))
"""

import math

# Durations (seconds): micro for hovers and ticks, short for chips, medium for panels,
# long for full-screen moves. Stagger is the gap between items of a cascade.
MICRO, SHORT, MEDIUM, LONG = 0.15, 0.3, 0.5, 0.8
STAGGER = 0.06


def clamp01(t):
    return 0.0 if t <= 0 else 1.0 if t >= 1 else t


def lerp(a, b, t):
    return a + (b - a) * t


def progress(age, delay, dur):
    """Where `age` is inside the window [delay, delay + dur], as 0..1."""
    return clamp01((age - delay) / dur) if dur > 0 else float(age >= delay)


def out_quad(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 2


def out_cubic(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def out_quart(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 4


def out_expo(t):
    t = clamp01(t)
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def in_cubic(t):
    return clamp01(t) ** 3


def in_expo(t):
    t = clamp01(t)
    return 0.0 if t <= 0 else 2 ** (10 * t - 10)


def in_out_cubic(t):
    t = clamp01(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def in_out_expo(t):
    t = clamp01(t)
    if t <= 0 or t >= 1:
        return t
    return 2 ** (20 * t - 10) / 2 if t < 0.5 else (2 - 2 ** (-20 * t + 10)) / 2


def smoothstep(t):
    t = clamp01(t)
    return 3 * t * t - 2 * t * t * t


def out_back(t, s=1.70158):
    t = clamp01(t)
    return 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2


def out_elastic(t, period=0.3):
    t = clamp01(t)
    if t <= 0 or t >= 1:
        return t
    return 2 ** (-10 * t) * math.sin((t - period / 4) * 2 * math.pi / period) + 1


def spring(t, damping=0.42, freq=13.0):
    """Damped spring from 0 to 1: lands on t=1 exactly (the tail below 0.3% is snapped)."""
    t = clamp01(t)
    if t >= 1:
        return 1.0
    wd = freq * math.sqrt(1 - damping * damping)
    env = math.exp(-damping * freq * t)
    return 1 - env * (math.cos(wd * t) + damping * freq / wd * math.sin(wd * t))


def heartbeat(since):
    """0..1 pulse for a lub-dub: `since` = seconds since the beat started (matches sounds.final_countdown)."""
    lub = math.exp(-since * 10) if since >= 0 else 0.0
    dub = 0.6 * math.exp(-(since - 0.22) * 10) if since >= 0.22 else 0.0
    return min(1.0, lub + dub)


def shake(age, amp, decay=10.0, freq=38.0, seed=0.0):
    """Camera shake offset (dx, dy) that dies out: a slam, not a wobble."""
    k = amp * math.exp(-decay * age) if age >= 0 else 0.0
    return (k * math.sin(age * freq + seed), k * math.cos(age * freq * 1.3 + seed * 2))


EASINGS = (out_quad, out_cubic, out_quart, out_expo, in_cubic, in_expo, in_out_cubic, in_out_expo,
           smoothstep, out_back, out_elastic, spring)
