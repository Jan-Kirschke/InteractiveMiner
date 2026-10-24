"""
The Lifelong Quiz - show transitions (HQ-style cut-aways)
Drawn on top of the finished frame. Each one straddles a state change: it covers the
screen in the dead tail of the state before (the reveal's fact has been up for seconds by
then) and uncovers during the first few hundred ms of the next state, while that state's
own entry animation plays underneath. State durations and answer windows are untouched.

    question    REVEALING -> ASKING   colour-band wipe, "QUESTION 3 -> 4" odometer bumper
    match_open  LOBBY -> INTRO        iris of answer colours, logo flash, shape burst
    final       REVEALING -> PODIUM   gold-fringed curtain, "AND THE WINNER IS..."

Resolution-independent: geometry comes from the target surface (16:9 TV or 9:16 Shorts)
and is laid out once per size. In portrait the wipe travels bottom to top (the Shorts
"next" swipe) and every card sits inside the Shorts safe zone (clear of the top 180 px
and bottom 320 px that YouTube covers with its own UI).

Cheap by design: flat polygons and circles straight onto the screen (no full-screen alpha),
text rendered once and cached.

    fx = Transitions(fonts)
    fx.cue(logic, now)          # every frame before drawing: pre-rolls and anchors itself
    ...draw the state...
    fx.draw(screen, now)        # after the state, before confetti; True while active
"""

import math
import random

import pygame

from quiz.config import FONT_DIR, MATCH_LENGTH, LIGHTNING_QUESTION, BONUS_QUESTIONS, LIGHTNING_TIME, DIFFICULTY_RAMP
from quiz.models import GameState
from quiz.motion import (in_cubic as _in_cubic, in_out_cubic as _in_out, out_back as _out_back,
                         out_cubic as _out_cubic, out_quad as _out_quad, progress as _prog)

# ==========================================
# PALETTE (the show palette from quiz/ui.py plus a flat HQ violet for the cut-aways)
# ==========================================
FLAT = (50, 42, 160)          # cut-away stage: brighter and flatter than the navy show stage
SEAM = (41, 34, 138)
INK = (255, 255, 255)
LILAC = (200, 194, 255)       # secondary text on FLAT (contrast about 6:1)
PIP_OFF = (88, 80, 200)
ACCENT = (255, 210, 63)
GOOD = (46, 229, 157)
BAD = (255, 90, 95)
DARK_INK = (17, 17, 34)
PINK, BLUE, ORANGE, TEAL = (255, 77, 109), (58, 134, 255), (255, 159, 28), (20, 201, 168)
VIOLET = (150, 140, 255)
SKY = (110, 190, 255)
PURPLE = (190, 120, 255)
SHAPE_COLORS = (PINK, BLUE, ORANGE, TEAL, ACCENT, VIOLET)
DIFF_COLORS = {"easy": GOOD, "medium": ORANGE, "hard": BAD}
BAND_COLORS = (PINK, BLUE, ORANGE, TEAL)   # answer 1-4 order, front band first
# Special-round slots (QuizLogic.special_slots): bumper label, colour, sub line
CROWD_PINK = (255, 140, 200)
SPECIAL_BUMPERS = {
    "majority": ("CROWD MIND", CROWD_PINK, [("NO RIGHT ANSWER", INK), ("  ·  MATCH THE CROWD", LILAC)]),
    "higher_lower": ("HIGHER OR LOWER", (150, 230, 90), [("TWO CHOICES", INK), ("  ·  TYPE 1 OR 2", LILAC)]),
    "odd_one_out": ("ODD ONE OUT", (90, 220, 230), [("THREE BELONG", INK), ("  ·  FIND THE ONE THAT DOESN'T", LILAC)]),
}
SPECIAL_BUMPERS["minority"] = SPECIAL_BUMPERS["majority"]   # Lonely Answer's twist waits for the reveal

# YouTube Shorts covers the top and bottom of a 1080x1920 frame with its own UI
SHORTS_SAFE_TOP, SHORTS_SAFE_BOTTOM = 180, 320


# ==========================================
# FONTS / TEXT
# ==========================================
class _Fonts:
    """Fallback when no UIManager.fonts is passed in (same files, same kinds)."""

    _FILES = {"display": "Anton-Regular.ttf", "black": "Barlow-ExtraBold.ttf", "bold": "Barlow-Bold.ttf"}

    def __init__(self):
        self._cache = {}

    def get(self, kind, size):
        f = self._cache.get((kind, size))
        if f is None:
            try:
                f = pygame.font.Font(str(FONT_DIR / self._FILES[kind]), size)
            except (FileNotFoundError, OSError, KeyError):
                f = pygame.font.SysFont("arial", size, bold=True)
            self._cache[(kind, size)] = f
        return f


def _tight(surf):
    """Crop a rendered string to its ink so baselines and masks line up exactly."""
    r = surf.get_bounding_rect()
    return surf.subsurface(r).copy() if r.w and r.h else surf


def _clip_blit(screen, surf, x, y, clip):
    old = screen.get_clip()
    screen.set_clip(clip.clip(old))
    screen.blit(surf, (int(x), int(y)))
    screen.set_clip(old)


def _rise(screen, surf, x, top, p):
    """Text rising out of (p 0 -> 1) or sinking into (p 1 -> 0) its own baseline: a mask, no alpha."""
    if p > 0:
        h = surf.get_height()
        _clip_blit(screen, surf, x, top + (1 - p) * (h + 10), pygame.Rect(0, int(top) - 2, 100000, h + 2))


# ==========================================
# FLAT SHAPES (the HQ vocabulary: circle, ring, cross, hex nut; plus the answer shapes)
# ==========================================
def _shape(screen, kind, x, y, r, rot, color, hole=FLAT):
    x, y, r = int(x), int(y), max(1, int(r))
    if kind == "circle":
        pygame.draw.circle(screen, color, (x, y), r)
    elif kind == "ring":
        pygame.draw.circle(screen, color, (x, y), r, width=max(3, r // 3))
    elif kind == "cross":
        wd = max(4, int(r * 0.55))
        for a in (rot, rot + math.pi / 2):
            dx, dy = math.cos(a) * r, math.sin(a) * r
            pygame.draw.line(screen, color, (x - dx, y - dy), (x + dx, y + dy), wd)
            for sx in (-1, 1):
                pygame.draw.circle(screen, color, (int(x + sx * dx), int(y + sx * dy)), wd // 2)
    elif kind == "hex":
        pts = [(x + math.cos(rot + k * math.pi / 3) * r, y + math.sin(rot + k * math.pi / 3) * r) for k in range(6)]
        pygame.draw.polygon(screen, color, pts)
        pygame.draw.circle(screen, hole, (x, y), int(r * 0.42))
    elif kind == "tri":
        pygame.draw.polygon(screen, color, [(x, y - r), (x + r * 1.05, y + r * 0.8), (x - r * 1.05, y + r * 0.8)])
    elif kind == "diamond":
        pygame.draw.polygon(screen, color, [(x, y - r), (x + r, y), (x, y + r), (x - r, y)])
    elif kind == "square":
        q = int(r * 0.8)
        pygame.draw.rect(screen, color, (x - q, y - q, 2 * q, 2 * q), border_radius=max(2, r // 6))
    elif kind == "bolt":
        s = r / 10
        pts = [(1, -10), (-6, 1), (-1, 1), (-3, 10), (6, -2), (1, -2), (4, -10)]
        pygame.draw.polygon(screen, color, [(x + px * s, y + py * s) for px, py in pts])


ANSWER_SHAPES = ("tri", "diamond", "circle", "square")


class _Rider:
    """A shape printed on a curtain: home position, depth (par >= 1 keeps it inside the curtain)."""
    __slots__ = ("kind", "color", "hx", "hy", "r", "rot", "spin", "par", "bob")

    def __init__(self, kind, color, hx, hy, r, par, rng):
        self.kind, self.color, self.hx, self.hy, self.r, self.par = kind, color, hx, hy, r, par
        self.rot = rng.uniform(0, 6.28)
        self.spin = rng.uniform(-0.8, 0.8)
        self.bob = rng.uniform(0, 6.28)

    def draw(self, screen, ox, oy, t):
        y = self.hy + oy * self.par + math.sin(t * 2.2 + self.bob) * 5
        _shape(screen, self.kind, self.hx + ox * self.par, y, self.r, self.rot + self.spin * t, self.color)


# Art-directed rider layouts (fractions of the screen, radius at a 1080 px short side):
# kind, colour, x, y, radius, depth. Kept clear of the cards in both orientations.
QUESTION_RIDERS = {
    "landscape": (
        ("hex", ACCENT, 0.24, 0.26, 48, 1.25), ("circle", TEAL, 0.76, 0.19, 34, 1.1),
        ("circle", VIOLET, 0.13, 0.62, 26, 1.4), ("cross", PINK, 0.82, 0.70, 40, 1.2),
        ("ring", BLUE, 0.66, 0.89, 32, 1.5), ("circle", ACCENT, 0.31, 0.83, 22, 1.1),
        ("circle", VIOLET, 0.93, 0.40, 18, 1.3), ("ring", TEAL, 0.07, 0.15, 22, 1.6)),
    "portrait": (
        ("hex", ACCENT, 0.22, 0.20, 50, 1.25), ("circle", TEAL, 0.80, 0.16, 36, 1.1),
        ("circle", VIOLET, 0.90, 0.25, 18, 1.4), ("cross", PINK, 0.84, 0.72, 42, 1.2),
        ("ring", BLUE, 0.64, 0.79, 32, 1.5), ("circle", ACCENT, 0.24, 0.75, 24, 1.1),
        ("circle", VIOLET, 0.10, 0.69, 20, 1.3), ("ring", TEAL, 0.10, 0.11, 22, 1.6)),
}
FINAL_RIDERS = {
    "landscape": (
        ("hex", ACCENT, 0.14, 0.24, 40, 1.0), ("circle", TEAL, 0.84, 0.18, 28, 1.0),
        ("cross", PINK, 0.88, 0.70, 32, 1.0), ("ring", BLUE, 0.10, 0.70, 26, 1.0),
        ("circle", VIOLET, 0.30, 0.12, 16, 1.0), ("circle", ACCENT, 0.66, 0.84, 18, 1.0)),
    "portrait": (
        ("hex", ACCENT, 0.20, 0.20, 44, 1.0), ("circle", TEAL, 0.82, 0.17, 30, 1.0),
        ("cross", PINK, 0.84, 0.74, 36, 1.0), ("ring", BLUE, 0.16, 0.72, 28, 1.0),
        ("circle", VIOLET, 0.55, 0.13, 16, 1.0), ("circle", ACCENT, 0.56, 0.79, 20, 1.0)),
}


# ==========================================
# TRANSITIONS
# ==========================================
class Transitions:
    LEAD = {"question": 1.1, "question_event": 1.5, "match_open": 1.5, "final": 1.6}
    TAIL = {"question": 0.5, "match_open": 1.0, "final": 0.5}

    def __init__(self, fonts=None):
        self.fonts = fonts or _Fonts()
        self.kind = None
        self.boundary = 0.0
        self.info = {}
        self._lead = self._tail = 0.0
        self._target = None
        self._size = None
        self._built = False
        self._cache = {}
        self._s = {}
        self._riders = []
        self._burst = []
        self._last_state = None
        self._cued = None

    # ------------------------------------------
    # API
    # ------------------------------------------
    def lead_for(self, kind, info):
        if kind == "question" and info.get("event"):
            return self.LEAD["question_event"]
        return self.LEAD[kind]

    def start(self, kind, now, boundary=None, **info):
        """Play `kind`. boundary = the moment of the state change (cover before it, uncover after).
        Without a boundary the whole cut-away plays from now. Surfaces are built on the first
        draw, for the size of the surface drawn to."""
        self.kind, self.info = kind, info
        self._lead, self._tail = self.lead_for(kind, info), self.TAIL[kind]
        self.boundary = now + self._lead if boundary is None else boundary
        self._built = False

    def active(self, now):
        return self.kind is not None and now - self.boundary < self._tail

    def covered(self, now):
        """True while the screen is fully covered: the caller may skip drawing the state underneath."""
        if self.kind is None:
            return False
        t = now - self.boundary
        cols = getattr(self, "cols", 9)
        last_panel = (cols - 1) / 2 - (0.5 if cols % 2 == 0 else 0)
        full = {"question": self.IN_DUR,
                "match_open": (len(self.IRIS_COLORS) - 1) * self.IRIS_STAG + self.IRIS_DUR,
                "final": last_panel * self.DROP_STAG + self.DROP_DUR}[self.kind]
        return -self._lead + full + 0.01 <= t < 0

    def draw(self, screen, now):
        if self.kind is None:
            return False
        t = now - self.boundary
        if t >= self._tail:
            self.kind = None
            return False
        if t >= -self._lead:
            if screen.get_size() != self._size:
                self._layout(screen.get_size())
            if not self._built:
                getattr(self, f"_build_{self.kind}")()
                self._built = True
            getattr(self, f"_draw_{self.kind}")(screen, t)
        return True

    def cue(self, logic, now):
        """Auto-wiring, call once per frame: pre-rolls in the dead tail of LOBBY / REVEALING and
        re-anchors to logic.state_start_time when the state really changes."""
        state = logic.state
        if state != self._last_state:
            self._last_state = state
            if self.kind is not None and state == self._target:
                self.boundary = logic.state_start_time
            return
        if self.kind is not None or self._cued == (state, logic.state_start_time):
            return
        if state == GameState.LOBBY:
            kind, target, info = "match_open", GameState.INTRO, {"match_no": logic.match_no}
        elif state == GameState.REVEALING and logic.q_index >= MATCH_LENGTH:
            kind, target, info = "final", GameState.PODIUM, {"match_no": logic.match_no,
                                                             "category": logic.match_category}
        elif state == GameState.REVEALING:
            n = logic.q_index + 1
            event = ("final" if n == MATCH_LENGTH else "lightning" if n == LIGHTNING_QUESTION
                     else "bonus" if n in BONUS_QUESTIONS else getattr(logic, "special_slots", {}).get(n, ""))
            kind, target = "question", GameState.ASKING
            info = {"n": n, "event": event, "difficulty": DIFFICULTY_RAMP.get(n, "medium"), "pips": list(logic.pips)}
        else:
            return
        rem = logic.time_remaining
        if 0 < rem <= self.lead_for(kind, info):
            self._cued = (state, logic.state_start_time)
            self._target = target
            self.start(kind, now, boundary=now + rem, **info)

    # ------------------------------------------
    # LAYOUT (once per surface size)
    # ------------------------------------------
    def _layout(self, size):
        self._size = size
        self._built = False
        self.w, self.h = w, h = size
        self.portrait = h > w
        k = h / 1920
        self.safe_top = int(SHORTS_SAFE_TOP * k) if self.portrait else 0
        self.safe_bottom = h - (int(SHORTS_SAFE_BOTTOM * k) if self.portrait else 0)
        self.cx, self.cy = w // 2, (self.safe_top + self.safe_bottom) // 2
        self.u = min(w, h) / 1080                       # type and shape scale
        self.margin = int(90 * self.u)
        # Wipe: the "along" axis is x on TV (left to right), y on Shorts (bottom to top)
        self.along = h if self.portrait else w
        self.slant = int(0.30 * w) if self.portrait else int(0.47 * h)   # TV: the stage-stripe lean
        self.band_w = int(58 * self.u)
        self.r_full = int(max(math.hypot(x - self.cx, y - self.cy) for x in (0, w) for y in (0, h))) + 6
        self.cols = max(4, round(w / 220))

    def _orient(self):
        return "portrait" if self.portrait else "landscape"

    # ------------------------------------------
    # CACHED TEXT
    # ------------------------------------------
    def _text(self, kind, size, text, color):
        key = ("t", kind, size, text, color)
        s = self._cache.get(key)
        if s is None:
            s = _tight(self.fonts.get(kind, size).render(text, True, color))
            self._store(key, s)
        return s

    def _line(self, parts, kind, size, tracking):
        """One tracked line in several colours (spaces kept: only the finished line is cropped)."""
        key = ("l", tuple(parts), kind, size, tracking)
        s = self._cache.get(key)
        if s is None:
            font = self.fonts.get(kind, size)
            glyphs = [font.render(ch, True, col) for text, col in parts for ch in text]
            w = sum(g.get_width() for g in glyphs) + tracking * (len(glyphs) - 1)
            s = pygame.Surface((max(1, w), font.get_height()), pygame.SRCALPHA)
            x = 0
            for g in glyphs:
                s.blit(g, (x, 0))
                x += g.get_width() + tracking
            s = _tight(s)
            self._store(key, s)
        return s

    def _fit_line(self, parts, kind, sizes, tracking, max_w):
        for size in sizes:
            s = self._line(parts, kind, int(size * self.u), tracking)
            if s.get_width() <= max_w:
                break
        return s

    def _store(self, key, s):
        if len(self._cache) > 300:
            self._cache.clear()
        self._cache[key] = s

    def _make_riders(self, layouts, seed):
        rng = random.Random(seed)
        self._riders = [_Rider(k, c, x * self.w, y * self.h, r * self.u, par, rng)
                        for k, c, x, y, r, par in layouts[self._orient()]]

    # ------------------------------------------
    # 1. QUESTION BUMPER: colour-band wipe (left to right on TV, bottom to top on Shorts)
    # ------------------------------------------
    # Cover:  the body edge runs along the screen, four answer-colour bands lead it.
    # Hold:   the numeral rolls from the last question to this one, the pip lights, the sub
    #         line rises.
    # Uncover (after the state change): the trailing edge sweeps on the same way. On TV the
    #         slant leans right, so the question text (top left) is uncovered first; on Shorts
    #         it is the "swipe up to next" gesture.
    IN_DUR, OUT_DUR, BAND_LAG = 0.46, 0.40, 0.022

    def _build_question(self):
        info, u = self.info, self.u
        n, ev = info["n"], info.get("event", "")
        diff = info.get("difficulty", "")
        label, lcol, sub = {
            "final": ("FINAL QUESTION", ACCENT, [("DOUBLE POINTS", INK), ("  ·  EVERYTHING CAN CHANGE", LILAC)]),
            "lightning": ("LIGHTNING ROUND", SKY, [(f"{LIGHTNING_TIME} SECONDS", INK), ("  ·  1.5x POINTS", LILAC)]),
            "bonus": ("BONUS ROUND", PURPLE, [("EXTRA POINTS", INK), ("  ·  UP FOR GRABS", LILAC)]),
            **SPECIAL_BUMPERS,
        }.get(ev, ("QUESTION", INK, None))
        if sub is None:
            sub = [(f"OF {MATCH_LENGTH}", LILAC)] + ([("  ·  ", LILAC), (diff.upper(), DIFF_COLORS.get(diff, INK))] if diff else [])
        num_size = int((620 if self.portrait else 440) * u)
        max_w = self.w - 2 * self.margin
        s = {
            "new": self._text("display", num_size, str(n), INK),
            "old": self._text("display", num_size, str(n - 1), INK) if n > 1 else None,
            "label": self._text("display", int((120 if self.portrait else 104) * u), label, lcol),
            "sub": self._fit_line(sub, "black", (48, 44, 40, 34) if self.portrait else (40, 36, 32, 28), 4, max_w),
            "x2": self._text("display", int(60 * u), "x2", DARK_INK),
        }
        num_w = max(s["new"].get_width(), s["old"].get_width() if s["old"] else 0) + int(40 * u)
        num_h = s["new"].get_height()
        g1, g2, g3, pip_h = int(46 * u), int(50 * u), int(34 * u), int(16 * u)
        total = s["label"].get_height() + g1 + num_h + g2 + s["sub"].get_height() + g3 + pip_h
        top = self.cy - total // 2
        s["lab_y"] = top
        s["num_rect"] = pygame.Rect(self.cx - num_w // 2, top + s["label"].get_height() + g1, num_w, num_h)
        s["sub_y"] = s["num_rect"].bottom + g2
        s["pip_y"] = s["sub_y"] + s["sub"].get_height() + g3
        self._s = s
        self._make_riders(QUESTION_RIDERS, n)

    def _quad(self, a, b):
        """Band between along-positions a < b; the far side of each edge is `slant` further along."""
        w, h, sl = self.w, self.h, self.slant
        if self.portrait:
            return [(0, h - a), (0, h - b), (w, h - b - sl), (w, h - a - sl)]
        return [(a, h), (b, h), (b + sl, 0), (a + sl, 0)]

    def _draw_question(self, screen, t):
        L, sl, bw = self.along, self.slant, self.band_w
        nb = len(BAND_COLORS)
        e_start, e_end = -nb * bw - sl - 4, L + 4
        f_start, f_end = -sl - 4, L + nb * bw + 4
        t_in = t + self._lead
        if t < 0:
            e = e_start + (e_end - e_start) * _in_out(t_in / self.IN_DUR)
            pygame.draw.polygon(screen, FLAT, self._quad(-sl - 40, e))
            for k, col in enumerate(BAND_COLORS[::-1]):     # k = 0 touches the body, front band leads in time
                ek = e_start + (e_end - e_start) * _in_out((t_in + (k + 1) * self.BAND_LAG) / self.IN_DUR) + k * bw
                ek = max(ek, e + k * bw)
                pygame.draw.polygon(screen, col, self._quad(ek, ek + bw))
            d = e - e_end
        else:
            f = f_start + (f_end - f_start) * _in_out(t / self.OUT_DUR)
            pygame.draw.polygon(screen, FLAT, self._quad(f, L + sl + 40))
            for k, col in enumerate(BAND_COLORS[::-1]):     # trailing bands lag further behind
                fk = f_start + (f_end - f_start) * _in_out((t - (k + 1) * self.BAND_LAG) / self.OUT_DUR) - (k + 1) * bw
                fk = min(fk, f - (k + 1) * bw)
                pygame.draw.polygon(screen, col, self._quad(fk, fk + bw))
            d = f - f_start
        if abs(d) >= L + sl:
            return
        ox, oy = (0, -d) if self.portrait else (d, 0)
        for rd in self._riders:
            rd.draw(screen, ox, oy, t_in)
        self._draw_question_card(screen, t_in, int(ox), int(oy))

    def _draw_question_card(self, screen, t_in, ox, oy):
        s, u = self._s, self.u
        settle = self.IN_DUR - 0.02
        hold = self._lead - self.LEAD["question"]     # event bumpers hold longer before the roll
        cx = self.cx + ox
        lab = s["label"]
        screen.blit(lab, (cx - lab.get_width() // 2, s["lab_y"] + oy))
        # Numeral: the previous question's number rides in on the curtain, then rolls over
        nr = s["num_rect"].move(ox, oy)
        roll = _out_back(_prog(t_in, settle + 0.02 + hold, 0.30), 1.25) if s["old"] is not None else 1.0
        h = nr.h + 40
        if roll < 1:
            old = s["old"]
            _clip_blit(screen, old, cx - old.get_width() // 2, nr.y - roll * h, nr)
        new = s["new"]
        _clip_blit(screen, new, cx - new.get_width() // 2, nr.y + (1 - roll) * h, nr)
        # Sub line rises out of a baseline mask just after the roll
        sub = s["sub"]
        _rise(screen, sub, cx - sub.get_width() // 2, s["sub_y"] + oy,
              _out_cubic(_prog(t_in, settle + 0.12 + hold, 0.28)))
        # Pips: one per question, the upcoming one lights as the number rolls
        pips = self.info.get("pips", [])
        n = self.info["n"]
        py = s["pip_y"] + oy
        step, pw, ph = int(50 * u), int(40 * u), int(16 * u)
        px = cx - (MATCH_LENGTH * step - (step - pw)) // 2
        for i in range(MATCH_LENGTH):
            x = px + i * step
            lit = i == n - 1 and roll > 0.5
            col = (GOOD if pips[i] == "done" else BAD) if i < len(pips) else ACCENT if lit else PIP_OFF
            pygame.draw.rect(screen, col, (x, py, pw, ph), border_radius=ph // 2)
            if lit:
                o = int(6 * u)
                pygame.draw.rect(screen, ACCENT, (x - o, py - o, pw + 2 * o, ph + 2 * o), width=3,
                                 border_radius=ph // 2 + o)
        # Event badge sits on the numeral's shoulder like an exponent
        ev = self.info.get("event")
        if ev in ("final", "lightning"):
            pop = _out_back(_prog(t_in, settle + 0.24 + hold, 0.3), 2.2)
            bx, by = cx + new.get_width() // 2 + int(76 * u), nr.y + int(70 * u)
            if pop > 0 and ev == "final":
                pygame.draw.circle(screen, ACCENT, (bx, by), int(62 * u * pop))
                if pop > 0.7:
                    screen.blit(s["x2"], s["x2"].get_rect(center=(bx, by)))
            elif pop > 0:
                _shape(screen, "bolt", bx, by, 66 * u * pop, 0, ACCENT)

    # ------------------------------------------
    # 2. MATCH OPEN: iris of answer colours, logo flash, shape burst
    # ------------------------------------------
    # Cover:  pink, blue, orange, teal, violet discs swell from the centre (staggered).
    # Hold:   the four answer shapes pop, the justified "THE LIFELONG / QUIZ" lockup rises,
    #         a dotted orbit draws on (the HQ intro's dotted circle).
    # Uncover (after LOBBY -> INTRO): the logo sinks, the colours open again as rings and the
    #         answer shapes plus a burst of HQ shapes fly out over the "MATCH N" sting.
    IRIS_DUR, IRIS_STAG, OPEN_DUR, OPEN_LAG = 0.36, 0.05, 0.55, 0.045
    IRIS_COLORS = (PINK, BLUE, ORANGE, TEAL, FLAT)

    def _justified(self, text, width):
        """Anton line set to an exact width (the lockup's lines share one measure)."""
        probe = self.fonts.get("display", 100).size(text)[0]
        return self._text("display", max(10, int(100 * width / probe)), text, INK)

    def _build_match_open(self):
        u = self.u
        measure = min(int(760 * u), self.w - 2 * self.margin)   # corners stay inside the orbit
        l1, l2 = self._justified("THE LIFELONG", measure), self._justified("QUIZ", measure)
        tag = self._line([(f"LIVE  ·  MATCH {self.info.get('match_no', '')}", LILAC)], "black", int(34 * u), 6)
        gap, shapes_h, tag_gap = int(26 * u), int(110 * u), int(46 * u)
        total = shapes_h + l1.get_height() + gap + l2.get_height() + tag_gap + tag.get_height()
        top = self.cy - total // 2
        s = {"l1": l1, "l2": l2, "tag": tag, "x": self.cx - measure // 2, "shape_y": top + int(34 * u),
             "l1_y": top + shapes_h}
        s["l2_y"] = s["l1_y"] + l1.get_height() + gap
        s["tag_y"] = s["l2_y"] + l2.get_height() + tag_gap
        s["orbit"] = int(min(self.w, self.safe_bottom - self.safe_top) * 0.46)
        self._s = s
        rng = random.Random(self.info.get("match_no", 0))
        self._burst = []
        sp_u = self.r_full / 1100
        for k in range(4):   # the answer shapes launch first, from their place in the logo
            a = -math.pi / 2 + (k - 1.5) * 0.5
            self._burst.append((ANSWER_SHAPES[k], BAND_COLORS[k], self.cx + (k - 1.5) * 120 * u, s["shape_y"],
                                math.cos(a) * 1900 * sp_u, math.sin(a) * 1500 * sp_u, 34 * u, rng.uniform(-3, 3)))
        for _ in range(30):
            a = rng.uniform(0, 6.283)
            sp = rng.uniform(1300, 2600) * sp_u
            self._burst.append((rng.choice(("circle", "circle", "ring", "cross", "hex")), rng.choice(SHAPE_COLORS),
                                self.cx + math.cos(a) * 60 * u, self.cy + math.sin(a) * 40 * u,
                                math.cos(a) * sp, math.sin(a) * sp * 0.75, rng.choice((10, 14, 18, 24, 30)) * u,
                                rng.uniform(-4, 4)))

    def _annulus(self, screen, color, r_in, r_out):
        r_in, r_out = int(r_in), int(r_out)
        if r_out - r_in >= 1 and r_out > 0:
            pygame.draw.circle(screen, color, (self.cx, self.cy), r_out, width=0 if r_in <= 0 else r_out - r_in)

    def _draw_match_open(self, screen, t):
        t_in = t + self._lead
        s, u, R = self._s, self.u, self.r_full
        if t < 0:   # nested discs: each later (smaller) one sits inside the last, so draw rings only
            radii = [R * _in_cubic(_prog(t_in, k * self.IRIS_STAG, self.IRIS_DUR)) for k in range(len(self.IRIS_COLORS))]
            if radii[-1] >= R:
                screen.fill(FLAT)
            else:
                for k, col in enumerate(self.IRIS_COLORS):
                    self._annulus(screen, col, radii[k + 1] if k + 1 < len(radii) else 0, radii[k])
            opened = 0
        else:   # boundaries grow outward: the violet opens first, the content hole last
            n = len(self.IRIS_COLORS) - 1
            rho = [R * _out_quad((t - (n - k) * self.OPEN_LAG) / self.OPEN_DUR) for k in range(n + 1)]
            self._annulus(screen, FLAT, rho[n], R)
            for k in range(n):
                self._annulus(screen, BAND_COLORS[k], rho[k], rho[k + 1])
            opened = rho[n]
            if rho[0] >= R:
                self._draw_burst(screen, t)
                return
        settle = len(self.IRIS_COLORS) * self.IRIS_STAG + self.IRIS_DUR - 0.12
        # Dotted orbit draws on clockwise; the opening violet erases it
        orbit = _out_cubic(_prog(t_in, settle - 0.05, 0.45))
        ro = s["orbit"]
        if orbit > 0 and opened < ro - 4:
            n_dots = 72
            spin = t_in * 0.35
            for i in range(int(n_dots * orbit)):
                a = spin + i * 6.2832 / n_dots
                pygame.draw.circle(screen, PIP_OFF, (int(self.cx + math.cos(a) * ro), int(self.cy + math.sin(a) * ro)),
                                   max(2, int(4 * u)))
        if t >= 0:
            self._draw_burst(screen, t)
            return
        sink = 1 - _in_cubic(_prog(t, -0.2, 0.2))
        for k in range(4):   # four answer shapes pop in a row above the lockup
            p = _out_back(_prog(t_in, settle + k * 0.06, 0.3), 2.0) * sink
            if p > 0:
                _shape(screen, ANSWER_SHAPES[k], self.cx + (k - 1.5) * 120 * u, s["shape_y"], 34 * u * p, 0,
                       BAND_COLORS[k])
        _rise(screen, s["l1"], s["x"], s["l1_y"], _out_cubic(_prog(t_in, settle + 0.08, 0.3)) * sink)
        _rise(screen, s["l2"], s["x"], s["l2_y"], _out_cubic(_prog(t_in, settle + 0.16, 0.32)) * sink)
        tag = s["tag"]
        tp = _out_cubic(_prog(t_in, settle + 0.34, 0.28)) * sink
        if tp > 0:
            tx = self.cx - tag.get_width() // 2 + int(14 * u)
            _rise(screen, tag, tx, s["tag_y"], tp)
            pygame.draw.circle(screen, BAD, (tx - int(26 * u), s["tag_y"] + tag.get_height() // 2), int(9 * u * tp))

    def _draw_burst(self, screen, t):
        drag = 1.6
        travel = (1 - math.exp(-drag * t)) / drag
        fade = 1 - _prog(t, 0.55, 0.45)
        if fade <= 0:
            return
        w, h = self.w, self.h
        for kind, col, x0, y0, vx, vy, r, spin in self._burst:
            x, y = x0 + vx * travel, y0 + vy * travel
            if -60 < x < w + 60 and -60 < y < h + 60:
                _shape(screen, kind, x, y, r * fade, spin * t, col, hole=FLAT)

    # ------------------------------------------
    # 3. FINAL CURTAIN: "AND THE WINNER IS..." into the podium
    # ------------------------------------------
    # Cover:  violet panels drop centre-out with a gold fringe and a small bounce.
    # Hold:   match line, the big line (one line on TV, stacked on Shorts), three gold dots
    #         tick in like a drumroll.
    # Uncover (after REVEALING -> PODIUM): panels fly up centre-out; the text rides the
    #         first panels so it never sits over the podium.
    DROP_DUR, DROP_STAG, LIFT_DUR, LIFT_STAG = 0.44, 0.05, 0.34, 0.035

    def _build_final(self):
        u = self.u
        cat = (self.info.get("category") or "").upper()
        parts = [(f"MATCH {self.info.get('match_no', '')}", LILAC)] + ([(f"  ·  {cat}", LILAC)] if cat else [])
        max_w = self.w - 2 * self.margin
        label = self._fit_line(parts, "black", (40, 34, 30), 6, max_w)
        dot_r, dot_step = int(19 * u), int(52 * u)
        dots_w = int(30 * u) + 2 * dot_step + 2 * dot_r
        for size in (220, 190, 170, 150, 130):   # biggest size whose wrap fits, the dots ending the last line
            font = self.fonts.get("display", int(size * u))
            lines = []
            for word in "AND THE WINNER IS".split():
                if lines and font.size(f"{lines[-1]} {word}")[0] <= max_w:
                    lines[-1] = f"{lines[-1]} {word}"
                else:
                    lines.append(word)
            if font.size(lines[-1])[0] + dots_w > max_w and " " in lines[-1]:
                head, last = lines[-1].rsplit(" ", 1)
                lines[-1:] = [head, last]
            fits = max(font.size(ln)[0] for ln in lines) <= max_w and font.size(lines[-1])[0] + dots_w <= max_w
            if fits and len(lines) <= (3 if self.portrait else 1):
                break
        surfs = [self._text("display", int(size * u), ln, INK) for ln in lines]
        lead = int(size * u * 0.09)
        block_w = max(max(sf.get_width() for sf in surfs), surfs[-1].get_width() + dots_w)
        lab_gap = int(34 * u)
        total = label.get_height() + lab_gap + sum(sf.get_height() for sf in surfs) + lead * (len(surfs) - 1)
        top = self.cy - total // 2
        x = self.cx - block_w // 2
        ys, y = [], top + label.get_height() + lab_gap
        for sf in surfs:
            ys.append(y)
            y += sf.get_height() + lead
        self._s = {"label": label, "lines": list(zip(surfs, ys)), "x": x, "lab_y": top,
                   "dots": (x + surfs[-1].get_width() + int(30 * u) + dot_r, ys[-1] + surfs[-1].get_height() - dot_r,
                            dot_r, dot_step)}
        self.hem = int(30 * u)
        self._make_riders(FINAL_RIDERS, self.info.get("match_no", 0))

    def _col_bottom(self, i, t):
        """Bottom edge (including the fringe) of curtain panel i at time t (0 = state change)."""
        order = abs(i - (self.cols - 1) / 2)
        if self.cols % 2 == 0:
            order -= 0.5
        full = self.h + self.hem
        if t < 0:
            return full * _out_back(_prog(t + self._lead, order * self.DROP_STAG, self.DROP_DUR), 1.1)
        return full * (1 - _in_cubic(_prog(t, order * self.LIFT_STAG, self.LIFT_DUR)))

    def _draw_final(self, screen, t):
        cols, hem, full = self.cols, self.hem, self.h + self.hem
        cw = -(-self.w // cols)
        bottoms = [self._col_bottom(i, t) for i in range(cols)]
        for i, b in enumerate(bottoms):
            if b <= 0:
                continue
            x = i * cw
            body = int(b) - hem
            if body > 0:
                pygame.draw.rect(screen, FLAT, (x, 0, cw, body))
                pygame.draw.rect(screen, SEAM, (x + cw - 3, 0, 3, body))
            pygame.draw.rect(screen, ACCENT, (x, max(0, body), cw, int(b) - max(0, body)))
        t_in = t + self._lead
        oy_card = int(min(bottoms) - full) if t >= 0 else 0      # ride the first panel that lifts
        for rd in self._riders:
            oy = bottoms[min(cols - 1, max(0, int(rd.hx // cw)))] - full
            rd.draw(screen, 0, min(oy, oy_card) if t >= 0 else oy, t_in)
        s = self._s
        settle = (cols // 2) * self.DROP_STAG + self.DROP_DUR - 0.1
        _rise(screen, s["label"], s["x"] + 4, s["lab_y"] + oy_card, _out_cubic(_prog(t_in, settle + 0.12, 0.3)))
        for j, (sf, y) in enumerate(s["lines"]):
            _rise(screen, sf, s["x"], y + oy_card, _out_cubic(_prog(t_in, settle + j * 0.07, 0.32)))
        # Three gold dots tick in: "...", spaced across the hold
        dx, dy, dr, step = s["dots"]
        hold_end = self._lead - 0.12
        for k in range(3):
            p = _out_back(_prog(t_in, settle + 0.3 + k * (hold_end - settle - 0.45) / 3, 0.22), 2.4)
            if p > 0:
                pygame.draw.circle(screen, ACCENT, (int(dx + k * step), int(dy + oy_card)), int(dr * p))
