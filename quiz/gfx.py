"""
The Lifelong Quiz - pre-rendered looks
Glows, soft shadows, lit button faces, light beams, bokeh, specular sweeps, anti-aliased arcs
and the "Spotlight LQ" logo (brand/profile-pictures/1-spotlight-lq.svg, rebuilt here from its
recipe). Everything expensive is rendered once and cached by its parameters; per frame the
show only blits. pygame 2.6 has no gaussian blur: blur() is a smoothscale down and back up.

Imports nothing from the UI modules, so transitions.py can use it too.
"""

import math

import pygame
import pygame.gfxdraw

# Brand: the logo's ring colours (= the answer colours, in answer order) and its gold ramp
PINK, BLUE, ORANGE, TEAL = (255, 77, 109), (58, 134, 255), (255, 159, 28), (20, 201, 168)
RING_COLORS = (PINK, BLUE, ORANGE, TEAL)       # clockwise from 12 o'clock, as on the logo
GOLD_HI, GOLD, GOLD_LO = (255, 241, 176), (255, 210, 63), (224, 154, 0)
RING_TRACK = (11, 13, 51)

def surface_bytes(s):
    return s.get_pitch() * s.get_height() if isinstance(s, pygame.Surface) else 0


class SurfCache(dict):
    """A cache that empties itself past a byte budget. Entry counts alone let a few hundred
    full-screen surfaces grow a 3-hour show past 900 MB."""

    def __init__(self, max_mb):
        super().__init__()
        self.budget = max_mb << 20
        self.nbytes = 0

    def __setitem__(self, key, s):
        old = self.get(key)
        if old is not None:
            self.nbytes -= surface_bytes(old)
        n = surface_bytes(s)
        if self and self.nbytes + n > self.budget:
            self.clear()
        super().__setitem__(key, s)
        self.nbytes += n

    def __delitem__(self, key):
        self.nbytes -= surface_bytes(self[key])
        super().__delitem__(key)

    def pop(self, key, *default):
        if key in self:
            self.nbytes -= surface_bytes(self[key])
        return super().pop(key, *default)

    def clear(self):
        super().clear()
        self.nbytes = 0


_cache = SurfCache(96)


def cached(key, make, store=None):
    """make() once per key. store: the caller's own dict (per-question surfaces that should die
    with the question instead of crowding the shared cache)."""
    store = _cache if store is None else store
    s = store.get(key)
    if s is None:
        if len(store) > 900:
            store.clear()
        s = store[key] = make()
    return s


def mix(c1, c2, t):
    t = 0.0 if t <= 0 else 1.0 if t >= 1 else t
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ==========================================
# BUILDING BLOCKS
# ==========================================
def blur(surf, k):
    """Soft copy of surf: k = how far it spreads, in pixels per sample."""
    w, h = surf.get_size()
    k = max(2, int(k))
    sw, sh = max(1, w // k), max(1, h // k)
    small = pygame.transform.smoothscale(surf, (sw, sh))
    mid = pygame.transform.smoothscale(small, (max(1, w // 2), max(1, h // 2)))
    return pygame.transform.smoothscale(mid, (w, h))


def vgradient(w, h, stops):
    """Opaque vertical gradient through evenly spaced colour stops."""
    col = pygame.Surface((1, max(1, h)))
    n = len(stops) - 1
    for y in range(h):
        t = y / max(1, h - 1) * n
        i = min(n - 1, int(t))
        col.set_at((0, y), mix(stops[i], stops[i + 1], t - i))
    return pygame.transform.scale(col, (max(1, w), max(1, h)))


def mask(w, h, radius):
    """White rounded rect with anti-aliased corners (drawn at 2x and scaled down)."""
    def make():
        big = pygame.Surface((w * 2, h * 2), pygame.SRCALPHA)
        big.fill((255, 255, 255, 0))
        pygame.draw.rect(big, (255, 255, 255, 255), (0, 0, w * 2, h * 2), border_radius=radius * 2)
        return pygame.transform.smoothscale(big, (w, h))
    return cached(("mask", w, h, radius), make)


def rounded(src, radius):
    out = mask(*src.get_size(), radius).copy()
    out.blit(src, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


# ==========================================
# LIGHT
# ==========================================
def glow(w, h, radius, color, spread=30, alpha=210):
    """Soft halo of a rounded rect; blit at (x - spread, y - spread)."""
    def make():
        s = pygame.Surface((w + 2 * spread, h + 2 * spread), pygame.SRCALPHA)
        s.fill((*color, 0))
        pygame.draw.rect(s, (*color, alpha), (spread, spread, w, h), border_radius=radius)
        return blur(s, spread // 2)
    return cached(("glow", w, h, radius, color, spread, alpha), make)


def shadow(w, h, radius, spread=18, alpha=150):
    return glow(w, h, radius, (0, 0, 0), spread, alpha)


def radial(r, color, alpha=255, power=2.0):
    """Round light: full at the centre, falling to nothing at r."""
    def make():
        k = 4
        n = max(2, r // k)
        s = pygame.Surface((2 * n, 2 * n), pygame.SRCALPHA)
        s.fill((*color, 0))
        for i in range(n, 0, -1):
            a = int(alpha * (1 - i / n) ** power)
            pygame.draw.circle(s, (*color, a), (n, n), i)
        return pygame.transform.smoothscale(s, (2 * r, 2 * r))
    return cached(("radial", r, color, alpha, power), make)


def bokeh(r, color, alpha):
    """Out-of-focus light disc with the faint bright rim of a real lens."""
    def make():
        pad = max(4, r // 5)
        s = pygame.Surface((2 * (r + pad), 2 * (r + pad)), pygame.SRCALPHA)
        s.fill((*color, 0))
        c = r + pad
        pygame.draw.circle(s, (*color, alpha), (c, c), r)
        pygame.draw.circle(s, (*mix(color, (255, 255, 255), 0.4), min(255, int(alpha * 1.5))), (c, c), r, max(2, r // 9))
        return blur(s, max(2, r // 6))
    return cached(("bokeh", r, color, alpha), make)


def beam(w, h, top_x, top_w, bottom_x, bottom_w, strength):
    """A stage light shaft for BLEND_RGB_ADD: soft edges, fading towards the floor."""
    def make():
        k = 6
        s = pygame.Surface((w // k, h // k))
        s.fill((0, 0, 0))
        v = strength
        pygame.draw.polygon(s, (v, v, min(255, int(v * 1.25))), [
            (top_x // k, 0), ((top_x + top_w) // k, 0),
            ((bottom_x + bottom_w) // k, h // k), (bottom_x // k, h // k)])
        s = blur(s, 5)
        fade = vgradient(w // k, h // k, [(255, 255, 255), (150, 150, 150), (0, 0, 0)])
        s.blit(fade, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        return pygame.transform.smoothscale(s, (w, h))
    return cached(("beam", w, h, top_x, top_w, bottom_x, bottom_w, strength), make)


def sweep_band(h, width=150, slant=0.45, alpha=120):
    """A slanted soft band of white: the specular highlight that runs across a panel."""
    def make():
        lean = int(h * slant)
        s = pygame.Surface((width + lean, h), pygame.SRCALPHA)
        s.fill((255, 255, 255, 0))
        row = pygame.Surface((width, 1), pygame.SRCALPHA)
        for x in range(width):
            a = math.sin(math.pi * x / width) ** 2
            row.set_at((x, 0), (255, 255, 255, int(alpha * a)))
        for y in range(h):
            s.blit(row, (lean - int(y * slant), y))
        return s
    return cached(("band", h, width, slant, alpha), make)


def silhouette(surf, key):
    """White copy of surf that keeps its alpha: the shape a sweep or a flash is clipped to."""
    def make():
        s = surf.copy()
        s.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MAX)
        return s
    return cached(("sil", key), make)


def sweep(screen, shape, x, y, t, strength=255):
    """Run the specular band across a white shape (mask() or silhouette()) drawn at (x, y);
    t 0..1 = left to right. Only the band's columns are touched: about 200 x h pixels."""
    if not 0 < t < 1:
        return
    w, h = shape.get_size()
    band = sweep_band(h)
    bw = band.get_width()
    bx = int(-bw + (w + bw) * t)
    x0, x1 = max(0, bx), min(w, bx + bw)
    if x1 - x0 < 2:
        return
    piece = shape.subsurface((x0, 0, x1 - x0, h)).copy()
    piece.blit(band, (bx - x0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    piece.set_alpha(strength)
    screen.blit(piece, (x + x0, y))


def tinted(w, h, radius, color):
    """Solid rounded rect in one colour (AA corners): dim overlays, flashes, share fills."""
    def make():
        s = mask(w, h, radius).copy()
        s.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        return s
    return cached(("tint", w, h, radius, color), make)


# ==========================================
# SURFACES FOR PANELS AND BUTTONS
# ==========================================
def face(w, h, radius, base, light=0.16, dark=0.16, rim=0.45):
    """A lit button face: lighter at the top, a bright rim along the top edge, AA corners."""
    def make():
        g = vgradient(w, h, [mix(base, (255, 255, 255), light), base, mix(base, (0, 0, 0), dark)])
        g.fill(mix(base, (255, 255, 255), rim), (0, 0, w, 3))
        g.fill(mix(base, (255, 255, 255), rim * 0.5), (0, 3, w, 2))
        g.fill(mix(base, (0, 0, 0), dark * 2), (0, h - 4, w, 4))
        return rounded(g, radius)
    return cached(("face", w, h, radius, base, light, dark, rim), make)


def glass(w, h, radius, tint=(40, 46, 130), alpha=150, edge=(255, 255, 255), edge_alpha=40):
    """Dark tinted glass panel with a hairline edge that is brighter at the top."""
    def make():
        g = vgradient(w, h, [mix(tint, (255, 255, 255), 0.10), tint, mix(tint, (0, 0, 0), 0.35)])
        s = rounded(g, radius)
        s.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
        line = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(line, (*edge, edge_alpha), (0, 0, w, h), width=2, border_radius=radius)
        pygame.draw.line(line, (*edge, min(255, edge_alpha * 3)), (radius, 1), (w - radius, 1), 2)
        s.blit(line, (0, 0))
        return s
    return cached(("glass", w, h, radius, tint, alpha, edge, edge_alpha), make)


# ==========================================
# ANTI-ALIASED ARCS (the logo ring, the timer)
# ==========================================
def arc(screen, cx, cy, r_out, width, a0, a1, color, caps=True):
    """Thick arc from a0 to a1 degrees, clockwise from 3 o'clock, with round caps."""
    if a1 - a0 < 0.3:
        return
    r_in = r_out - width
    steps = max(2, int((a1 - a0) / 2.5))
    outer, inner = [], []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        ca, sa = math.cos(a), math.sin(a)
        outer.append((cx + ca * r_out, cy + sa * r_out))
        inner.append((cx + ca * r_in, cy + sa * r_in))
    pts = outer + inner[::-1]
    pygame.gfxdraw.aapolygon(screen, pts, color)
    pygame.gfxdraw.filled_polygon(screen, pts, color)
    if caps:
        rc = width / 2
        for a in (a0, a1):
            a = math.radians(a)
            x, y = int(round(cx + math.cos(a) * (r_out - rc))), int(round(cy + math.sin(a) * (r_out - rc)))
            pygame.gfxdraw.aacircle(screen, x, y, int(rc), color)
            pygame.gfxdraw.filled_circle(screen, x, y, int(rc), color)


def disc(screen, cx, cy, r, color):
    cx, cy, r = int(cx), int(cy), max(1, int(r))
    pygame.gfxdraw.aacircle(screen, cx, cy, r, color)
    pygame.gfxdraw.filled_circle(screen, cx, cy, r, color)


def ring(screen, cx, cy, r, width, remaining=1.0, drawn=1.0, colors=RING_COLORS, gap=7.0, track=True):
    """The Spotlight LQ ring: four arcs in the answer colours, clockwise from 12 o'clock.
    remaining < 1 empties it clockwise from the top (a timer); drawn < 1 draws each arc on."""
    if track:
        pygame.draw.circle(screen, RING_TRACK, (int(cx), int(cy)), int(r + width * 0.35), int(width * 1.7))
    start = -90 + 360 * (1 - remaining)
    for i, col in enumerate(colors):
        a0 = -90 + i * 90 + gap
        a1 = a0 + (90 - 2 * gap) * drawn
        a0 = max(a0, start)
        if a1 > a0:
            arc(screen, cx, cy, r, width, a0, a1, col)


# ==========================================
# TEXT EFFECTS
# ==========================================
def gold_text(font, text, stops=(GOLD_HI, GOLD, GOLD_LO)):
    def make():
        white = font.render(text, True, (255, 255, 255))
        grad = vgradient(*white.get_size(), list(stops))
        out = white.copy()
        out.blit(grad, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
        return out
    return cached(("gold", id(font), text, stops), make)


def with_shadow(surf, key, dy=8, spread=10, alpha=150, store=None):
    """surf over its own soft drop shadow; the result is padded by 2 * spread on every side
    (plus dy below), so blit it at the plain text's topleft minus 2 * spread.
    key names surf in the cache: surfaces die and their ids are reused, so it is never id(surf)."""
    def make():
        w, h = surf.get_size()
        pad = spread * 2
        out = pygame.Surface((w + 2 * pad, h + 2 * pad + dy), pygame.SRCALPHA)
        out.fill((0, 0, 0, 0))
        sil = surf.copy()
        sil.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGB_MULT)
        sil.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
        out.blit(sil, (pad, pad + dy))
        out = blur(out, spread)
        out.blit(surf, (pad, pad))
        return out
    return cached(("shadow", key, dy, spread, alpha), make, store)


def tracked(font, text, color, tracking):
    """One line with letter-spacing (the logo's wordmark)."""
    def make():
        glyphs = [font.render(ch, True, color) for ch in text]
        w = sum(g.get_width() for g in glyphs) + tracking * (len(glyphs) - 1)
        s = pygame.Surface((max(1, w), font.get_height()), pygame.SRCALPHA)
        s.fill((*color, 0))
        x = 0
        for g in glyphs:
            s.blit(g, (x, 0))
            x += g.get_width() + tracking
        return s
    return cached(("tracked", id(font), text, color, tracking), make)


def lq_mark(font):
    """The gold "LQ" over its shadow, from a display font at the wanted size."""
    return with_shadow(gold_text(font, "LQ"), ("lq", id(font)), dy=max(3, font.get_height() // 30),
                       spread=max(4, font.get_height() // 18), alpha=160)
