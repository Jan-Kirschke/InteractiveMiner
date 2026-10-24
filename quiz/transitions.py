"""
The Lifelong Quiz - show transitions and the build-up before every question
Drawn on top of the finished frame, for any screen size (16:9 TV and 9:16 Shorts): geometry
comes from the target surface and is laid out once per size.

    buildup     REVEALING -> BUILDUP -> ASKING   a cover style closes over the reveal, the
                build-up scene plays on it (question number, stakes slam, tier ladder, tension
                line, spotlighted player, fuse), the same style opens onto the question
    question    REVEALING -> ASKING              the old bumper, when there is no BUILDUP state
    match_open  LOBBY -> INTRO                   the LQ ring iris: the logo ring closes over
                the lobby, becomes the logo, then opens and the camera pushes through it
    final       REVEALING -> PODIUM              gold-fringed curtain, a searching spotlight,
                "AND THE WINNER IS..."
    next_match  PODIUM -> LOBBY                  four-colour ribbon sweep, "NEXT MATCH 15 -> 16"

Cover styles (STYLES), so consecutive questions never look the same:
    bands      four answer-colour bands lead a slanted violet curtain (the Shorts swipe-up)
    doors      two doors slide shut; on the way out the card splits and leaves with them
    slats      venetian slats roll down; the card is sliced away as they roll up
    tiles      dots grow into squares along a diagonal, colour first, then violet
    slash      lightning: two halves snap together on a zig-zag seam that flashes sky blue
  Brand moments (the big beats only):
    iris       the Spotlight LQ ring is the aperture: it closes, then opens with a wind-up and
               the camera pushes through it (second half, the first question)
    ribbon     the four answer colours as flowing ribbons (halftime, the next match)
    spotlight  lights out, a spotlight searches the dark stage and finds the number; the light
               pool opens into the question (the final question)

Cheap by design: flat polygons, circles and fills straight onto the screen; light is added
with BLEND_RGB_ADD from opaque cached sprites; text is rendered once per cut-away and cached.
While a cut-away covers the screen, `covered()` lets the UI skip the frame underneath.

    fx = Transitions(fonts)
    fx.cue(logic, now)          # every frame before drawing: starts, pre-rolls and anchors
    ...draw the state unless fx.covered(now)...
    fx.draw(screen, now)        # after the state, before confetti; True while active
"""

import math
import random

import pygame
import pygame.gfxdraw

from quiz.config import FONT_DIR, MATCH_LENGTH, LIGHTNING_QUESTION, BONUS_QUESTIONS, LIGHTNING_TIME, DIFFICULTY_RAMP
from quiz import gfx
from quiz.models import GameState
from quiz.motion import (clamp01, heartbeat, in_cubic as _in_cubic, in_expo, in_out_cubic as _in_out, lerp,
                         out_back as _out_back, out_cubic as _out_cubic, out_expo, out_quad as _out_quad,
                         progress as _prog, shake, smoothstep)

# The game loop's tension state before every question (None on branches without it)
BUILDUP = getattr(GameState, "BUILDUP", None)

# ==========================================
# PALETTE (the show palette from quiz/ui.py plus a flat HQ violet for the cut-aways)
# ==========================================
FLAT = (50, 42, 160)          # cut-away stage: brighter and flatter than the navy show stage
NIGHT = (13, 10, 46)          # lights down: the build-up of the big questions
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
TIERS = ("easy", "medium", "hard", "expert")
TIER_COLORS = {"easy": GOOD, "medium": ORANGE, "hard": BAD, "expert": PURPLE}
BAND_COLORS = (PINK, BLUE, ORANGE, TEAL)   # answer 1-4 order, front band first
# Special-round slots (QuizLogic.special_slots): bumper label, colour, sub line
CROWD_PINK = (255, 140, 200)
SPECIAL_BUMPERS = {
    "majority": ("CROWD MIND", CROWD_PINK, [("NO RIGHT ANSWER", INK), ("  ·  MATCH THE CROWD", LILAC)]),
    "higher_lower": ("HIGHER OR LOWER", (150, 230, 90), [("TWO CHOICES", INK), ("  ·  TYPE 1 OR 2", LILAC)]),
    "odd_one_out": ("ODD ONE OUT", (90, 220, 230), [("THREE BELONG", INK), ("  ·  FIND THE ONE THAT DOESN'T", LILAC)]),
}
SPECIAL_BUMPERS["minority"] = SPECIAL_BUMPERS["majority"]   # Lonely Answer's twist waits for the reveal
EVENT_COLORS = {"final": ACCENT, "lightning": SKY, "bonus": PURPLE, "jackpot": PURPLE, "first_blood": (255, 110, 110)}

# YouTube Shorts covers the top and bottom of a 1080x1920 frame with its own UI
SHORTS_SAFE_TOP, SHORTS_SAFE_BOTTOM = 180, 420   # bottom: ui_vertical.SAFE_BOTTOM = 1500

# Cover styles: (seconds to cover, seconds to uncover)
STYLES = {"bands": (0.46, 0.40), "doors": (0.40, 0.42), "slats": (0.50, 0.44), "tiles": (0.56, 0.46),
          "slash": (0.30, 0.34), "iris": (0.55, 0.60), "ribbon": (0.62, 0.50), "spotlight": (0.40, 0.62)}
ROTATION = ("bands", "doors", "slats", "tiles")
SINKERS = ("tiles", "slash", "iris", "spotlight")   # the card sinks away instead of riding the uncover
T_STAKES = 1.2   # the stakes land 1.2 s into BUILDUP, on the controller's "stakes" hit


def pick_style(n, event="", match_no=0, last=None):
    """Cover style for the cut-away into question n: brand moments for the big beats, else a
    rotation that never repeats the previous style."""
    if event == "final" or n >= MATCH_LENGTH:
        return "spotlight"
    if n == 1 or n == MATCH_LENGTH // 2 + 1:   # into the first question, and out of halftime
        return "iris"
    if event == "lightning":
        return "slash"
    i = (n + 2 * match_no) % len(ROTATION)
    s = ROTATION[i]
    return ROTATION[(i + 1) % len(ROTATION)] if s == last else s


# ==========================================
# FONTS / TEXT
# ==========================================
class _Fonts:
    """Fallback when no UIManager.fonts is passed in (same files, same kinds)."""

    _FILES = {"display": "Anton-Regular.ttf", "black": "Barlow-ExtraBold.ttf", "bold": "Barlow-Bold.ttf",
              "semi": "Barlow-SemiBold.ttf", "noto": "NotoSans-Variable.ttf"}

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
    elif kind == "star":
        pts = []
        for k in range(10):
            a = rot - math.pi / 2 + k * math.pi / 5
            rr = r if k % 2 == 0 else r * 0.45
            pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
        pygame.draw.polygon(screen, color, pts)
    elif kind == "arrow":
        s = r / 10
        pts = [(0, -10), (9, 0), (3.5, 0), (3.5, 10), (-3.5, 10), (-3.5, 0), (-9, 0)]
        pygame.draw.polygon(screen, color, [(x + px * s, y + py * s) for px, py in pts])
    elif kind == "crown":
        s = r
        pygame.draw.polygon(screen, color, [(x - s, y + s * 0.55), (x - s, y - s * 0.45), (x - s * 0.5, y + s * 0.05),
                                            (x, y - s * 0.75), (x + s * 0.5, y + s * 0.05), (x + s, y - s * 0.45),
                                            (x + s, y + s * 0.55)])


ANSWER_SHAPES = ("tri", "diamond", "circle", "square")


class _Rider:
    """A shape printed on a curtain: home position, depth (par >= 1 keeps it inside the curtain)."""
    __slots__ = ("kind", "color", "hx", "hy", "r", "rot", "spin", "par", "bob")

    def __init__(self, kind, color, hx, hy, r, par, rng):
        self.kind, self.color, self.hx, self.hy, self.r, self.par = kind, color, hx, hy, r, par
        self.rot = rng.uniform(0, 6.28)
        self.spin = rng.uniform(-0.8, 0.8)
        self.bob = rng.uniform(0, 6.28)

    def draw(self, screen, ox, oy, t, hole=FLAT):
        y = self.hy + oy * self.par + math.sin(t * 2.2 + self.bob) * 5
        _shape(screen, self.kind, self.hx + ox * self.par, y, self.r, self.rot + self.spin * t, self.color, hole)


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
# The build-up stacks more on the card: shapes keep to the edges
BUILDUP_RIDERS = {
    "landscape": (
        ("hex", ACCENT, 0.05, 0.14, 34, 1.0), ("circle", TEAL, 0.95, 0.10, 26, 1.0),
        ("cross", PINK, 0.96, 0.86, 30, 1.0), ("ring", BLUE, 0.04, 0.84, 24, 1.0),
        ("circle", VIOLET, 0.50, 0.06, 14, 1.0), ("circle", ACCENT, 0.50, 0.95, 16, 1.0)),
    "portrait": (
        ("hex", ACCENT, 0.10, 0.12, 40, 1.0), ("circle", TEAL, 0.90, 0.115, 28, 1.0),
        ("cross", PINK, 0.91, 0.82, 34, 1.0), ("ring", BLUE, 0.09, 0.81, 26, 1.0),
        ("circle", VIOLET, 0.06, 0.45, 14, 1.0), ("circle", ACCENT, 0.95, 0.52, 16, 1.0)),
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
    LEAD = {"question": 1.1, "question_event": 1.5, "match_open": 1.5, "final": 1.6, "next_match": 1.1}
    TAIL = {"match_open": 1.0, "final": 0.5}          # cut kinds take their style's uncover time
    CUTS = ("question", "next_match", "buildup")       # cover style + card + the same style's uncover
    # match open (LQ ring iris)
    IRIS_CLOSE, IRIS_FILL = 0.50, 0.20
    # final curtain
    DROP_DUR, DROP_STAG, LIFT_DUR, LIFT_STAG = 0.44, 0.05, 0.34, 0.035
    BAND_LAG = 0.022

    def __init__(self, fonts=None):
        self.fonts = fonts or _Fonts()
        self.kind = None
        self.style = "bands"
        self.boundary = 0.0
        self.info = {}
        self.bg = FLAT
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
        self._last_style = None

    # ------------------------------------------
    # API
    # ------------------------------------------
    def lead_for(self, kind, info):
        if kind == "question" and info.get("event"):
            return self.LEAD["question_event"]
        return self.LEAD[kind]

    def start(self, kind, now, boundary=None, lead=None, **info):
        """Play `kind`. boundary = the moment of the state change (cover before it, uncover after).
        Without a boundary the whole cut-away plays from now. Surfaces are built on the first
        draw, for the size of the surface drawn to."""
        self.kind, self.info = kind, info
        self._lead = self.lead_for(kind, info) if lead is None else lead
        if kind in self.CUTS:
            n = info.get("n", 0)
            self.style = info.get("style") or ("ribbon" if kind == "next_match" else
                                               pick_style(n, info.get("event", ""), info.get("match_no", 0), self._last_style))
            self._last_style = self.style
            self._tail = STYLES[self.style][1]
            k = info.get("intensity", 0.0) if kind == "buildup" else 0.0
            self.bg = NIGHT if self.style == "spotlight" else gfx.mix(FLAT, NIGHT, 0.82 * smoothstep(k))
        else:
            self._tail = self.TAIL[kind]
            self.bg = FLAT
        self.boundary = now + self._lead if boundary is None else boundary
        self._built = False

    def active(self, now):
        return self.kind is not None and now - self.boundary < self._tail

    def covered(self, now):
        """True while the screen is fully covered: the caller may skip drawing the state underneath."""
        if self.kind is None:
            return False
        t = now - self.boundary
        if self.kind in self.CUTS:
            full = STYLES[self.style][0]
        elif self.kind == "match_open":
            full = self.IRIS_CLOSE + self.IRIS_FILL
        else:
            cols = getattr(self, "cols", 9)
            last_panel = (cols - 1) / 2 - (0.5 if cols % 2 == 0 else 0)
            full = last_panel * self.DROP_STAG + self.DROP_DUR
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
            if self.kind in self.CUTS:
                self._draw_cut(screen, t)
            else:
                getattr(self, f"_draw_{self.kind}")(screen, t)
        return True

    def cover(self, screen, style, p, out=False, bg=FLAT):
        """Draw one cover style on its own at progress p (0..1; out=True uncovers). For state
        views that own their data, like the halftime card. Returns the card hint (see _cover)."""
        if screen.get_size() != self._size:
            self._layout(screen.get_size())
        old = self.bg
        self.bg = bg
        try:
            return self._cover(screen, style, clamp01(p), out, p * STYLES[style][0 if not out else 1])
        finally:
            self.bg = old

    def cue(self, logic, now):
        """Auto-wiring, call once per frame: starts the build-up with its state, pre-rolls in the
        dead tail of LOBBY / REVEALING / PODIUM and re-anchors to logic.state_start_time when
        the state really changes."""
        state = logic.state
        if state != self._last_state:
            self._last_state = state
            if BUILDUP is not None and state == BUILDUP:
                info = self.buildup_info(logic)
                self._cued = (state, logic.state_start_time)
                self._target = GameState.ASKING
                dur = max(0.5, logic.state_duration)
                self.start("buildup", now, boundary=now + logic.time_remaining, lead=dur, **info)
                return
            if self.kind is not None and state == self._target:
                self.boundary = logic.state_start_time
            elif self.kind == "buildup":
                self.kind = None   # BUILDUP left for anything but the question (skip key): no uncover
            return
        if self.kind == "buildup" and state == BUILDUP:   # follow the logic's clock; keys may fill late
            b = getattr(logic, "buildup", None)
            if b and not self._built:
                self.info.update(self.buildup_info(logic))
            self.boundary = now + logic.time_remaining
            self._lead = max(0.5, logic.state_duration)
            return
        if self.kind is not None or self._cued == (state, logic.state_start_time):
            return
        if state == GameState.LOBBY:
            kind, target, info = "match_open", GameState.INTRO, {"match_no": logic.match_no}
        elif state == GameState.REVEALING and logic.q_index >= MATCH_LENGTH:
            kind, target, info = "final", GameState.PODIUM, {"match_no": logic.match_no,
                                                             "category": logic.match_category}
        elif state == GameState.REVEALING:
            if BUILDUP is not None:
                return   # the build-up state brings its own cover
            n = logic.q_index + 1
            event = ("final" if n == MATCH_LENGTH else "lightning" if n == LIGHTNING_QUESTION
                     else "bonus" if n in BONUS_QUESTIONS else getattr(logic, "special_slots", {}).get(n, ""))
            kind, target = "question", GameState.ASKING
            info = {"n": n, "event": event, "difficulty": DIFFICULTY_RAMP.get(n, "medium"), "pips": list(logic.pips),
                    "match_no": logic.match_no}
        elif state == GameState.PODIUM:
            kind, target = "next_match", GameState.LOBBY
            info = {"n": logic.match_no + 1, "event": "next_match"}
        else:
            return
        rem = logic.time_remaining
        if 0 < rem <= self.lead_for(kind, info):
            self._cued = (state, logic.state_start_time)
            self._target = target
            self.start(kind, now, boundary=now + rem, **info)

    @staticmethod
    def buildup_info(logic):
        """logic.buildup (the frozen contract keys) with every gap filled, plus the match pips."""
        b = dict(getattr(logic, "buildup", None) or {})
        n = int(b.get("q_no") or logic.q_index + 1)
        of = int(b.get("of") or MATCH_LENGTH)
        tier = str(b.get("tier") or DIFFICULTY_RAMP.get(n, "medium")).lower()
        event = b.get("event") or ""
        if not event and n == of:
            event = "final"
        return {"n": n, "of": of, "tier": tier if tier in TIERS else "medium", "stakes": b.get("stakes"),
                "round": b.get("kind") or "classic", "event": event,
                "headline": str(b.get("headline") or f"QUESTION {n}"), "subline": str(b.get("subline") or ""),
                "spotlight": b.get("spotlight") or None, "intensity": clamp01(float(b.get("intensity") or 0.0)),
                "pips": list(getattr(logic, "pips", [])), "match_no": getattr(logic, "match_no", 0)}

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
            s = _tight(self._font_for(kind, size, text).render(text, True, color))
            self._store(key, s)
        return s

    def _font_for(self, kind, size, text):
        """User text (names, tension lines) may hold letters the show fonts lack: Noto has them."""
        if any(ord(ch) > 0x24F for ch in text):
            try:
                return self.fonts.get("noto", size)
            except Exception:
                pass
        return self.fonts.get(kind, size)

    def _line(self, parts, kind, size, tracking):
        """One tracked line in several colours (spaces kept: only the finished line is cropped)."""
        key = ("l", tuple(parts), kind, size, tracking)
        s = self._cache.get(key)
        if s is None:
            font = self._font_for(kind, size, "".join(t for t, _ in parts))
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

    def _wrap(self, text, kind, sizes, max_w, max_lines):
        """Word-wrap at the biggest size that fits in max_lines; the last size cuts with '...'."""
        for size in sizes:
            font = self._font_for(kind, int(size * self.u), text)
            lines, cur = [], ""
            for word in text.split():
                test = f"{cur} {word}".strip()
                if font.size(test)[0] <= max_w or not cur:
                    cur = test
                else:
                    lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            if len(lines) <= max_lines:
                return lines, int(size * self.u)
        lines = lines[:max_lines]
        while lines and font.size(lines[-1] + "...")[0] > max_w and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "..."
        return lines, int(sizes[-1] * self.u)

    def _store(self, key, s):
        if len(self._cache) > 300:
            self._cache.clear()
        self._cache[key] = s

    def _make_riders(self, layouts, seed):
        rng = random.Random(seed)
        self._riders = [_Rider(k, c, x * self.w, y * self.h, r * self.u, par, rng)
                        for k, c, x, y, r, par in layouts[self._orient()]]

    # ------------------------------------------
    # COVER STYLES
    # ------------------------------------------
    # _cover draws a style at p (0..1 of its cover or uncover time) and returns the card hint:
    # a list of (clip rect or None, dx, dy) to draw the card with. t is seconds into the phase
    # (some styles keep moving after they have closed).
    def _cover(self, screen, style, p, out, t):
        return getattr(self, f"_cov_{style}")(screen, p, out, t)

    def _pt(self, along, c):
        """A point at `along` on the wipe axis and c (0..1) across it."""
        if self.portrait:
            return (c * self.w, self.h - along)
        return (along, self.h - c * self.h)

    def _band(self, a, b, wave=None, n=1):
        """Slanted band between along-positions a < b; wave(c, edge) bends its edges."""
        sl = self.slant
        p1, p2 = [], []
        for i in range(n + 1):
            c = i / n
            wa = wave(c, 0) if wave else 0
            wb = wave(c, 1) if wave else 0
            p1.append(self._pt(a + sl * c + wa, c))
            p2.append(self._pt(b + sl * c + wb, c))
        return p1 + p2[::-1]

    def _ride(self, d):
        return [(None, 0, int(-d)) if self.portrait else (None, int(d), 0)]

    def _cov_bands(self, screen, p, out, t):
        L, sl, bw = self.along, self.slant, self.band_w
        nb = len(BAND_COLORS)
        cin, cout = STYLES["bands"]
        if not out:
            lag = self.BAND_LAG / cin
            e_start, e_end = -nb * bw - sl - 4, L + 4
            e = lerp(e_start, e_end, _in_out(p))
            pygame.draw.polygon(screen, self.bg, self._band(-sl - 40, e))
            for k, col in enumerate(BAND_COLORS[::-1]):     # k = 0 touches the body, front band leads in time
                ek = max(lerp(e_start, e_end, _in_out(p + (k + 1) * lag)) + k * bw, e + k * bw)
                pygame.draw.polygon(screen, col, self._band(ek, ek + bw))
            return self._ride(e - e_end)
        lag = self.BAND_LAG / cout
        f_start, f_end = -sl - 4, L + nb * bw + 4
        f = lerp(f_start, f_end, _in_out(p))
        pygame.draw.polygon(screen, self.bg, self._band(f, L + sl + 40))
        for k, col in enumerate(BAND_COLORS[::-1]):     # trailing bands lag further behind
            fk = min(lerp(f_start, f_end, _in_out(p - (k + 1) * lag)) - (k + 1) * bw, f - (k + 1) * bw)
            pygame.draw.polygon(screen, col, self._band(fk, fk + bw))
        return self._ride(f - f_start)

    def _cov_ribbon(self, screen, p, out, t):
        """Four answer-colour ribbons flow across, each with its own wave; the body follows."""
        L, sl = self.along, self.slant
        rw = int(84 * self.u)
        amp = 46 * self.u
        nb = len(BAND_COLORS)

        def wave(k):
            def f(c, edge):
                return amp * math.sin(c * 5.2 + k * 0.9 + t * 7.0 + edge * 0.5) * (0.6 + 0.4 * math.sin(c * 2.1 + k))
            return f
        span = nb * rw * 1.25
        if not out:
            e_start, e_end = -span - sl - amp - 4, L + amp + 4
            e = lerp(e_start, e_end, _in_out(p))
            pygame.draw.polygon(screen, self.bg, self._band(-sl - 60, e, wave(9), 14))
            for k in range(nb - 1, -1, -1):           # ribbon 0 (pink) leads
                lead = e + (nb - k) * rw * 1.25 * (0.55 + 0.45 * (1 - p))
                pygame.draw.polygon(screen, BAND_COLORS[k], self._band(lead - rw * 1.35, lead, wave(k), 14))
            return self._ride(e - e_end)
        f_start, f_end = -sl - amp - 4, L + span + amp + 4
        f = lerp(f_start, f_end, _in_out(p))
        pygame.draw.polygon(screen, self.bg, self._band(f, L + sl + 60, wave(9), 14))
        for k in range(nb):
            trail = f - (k + 1) * rw * 1.25 * (0.55 + 0.45 * p)
            pygame.draw.polygon(screen, BAND_COLORS[nb - 1 - k], self._band(trail, trail + rw * 1.35, wave(k), 14))
        return self._ride(f - f_start)

    def _cov_doors(self, screen, p, out, t):
        w, h = self.w, self.h
        half = w / 2
        bw = self.band_w * 0.6
        if not out:
            x = half * _in_out(p)
            stripe = bw * min(1.0, (1 - p) * 4)
        else:
            x = half * (1 - _in_out(p))
            stripe = bw * min(1.0, p * 5)
        xl, xr = int(x), int(w - x)
        if xl > 0:
            screen.fill(self.bg, (0, 0, xl, h))
            screen.fill(self.bg, (xr, 0, w - xr, h))
        if stripe >= 1:   # the four colours run along the door edges, left pair and right pair
            for k, col in enumerate(BAND_COLORS[:2]):
                screen.fill(col, (int(xl + k * stripe), 0, int(stripe) + 1, h))
            for k, col in enumerate(BAND_COLORS[2:]):
                screen.fill(col, (int(xr - (2 - k) * stripe), 0, int(stripe) + 1, h))
        if not out:
            return [(None, 0, 0)]
        dx = int(half - x)
        return [(pygame.Rect(0, 0, xl, h), -dx, 0), (pygame.Rect(xr, 0, w - xr, h), dx, 0)]

    def _cov_slats(self, screen, p, out, t):
        w, h = self.w, self.h
        n = 8 if self.portrait else 6
        sh = -(-h // n)
        stag = 0.07
        span = 1 - (n - 1) * stag
        clips = []
        line = max(4, int(8 * self.u))
        for i in range(n):
            q = _in_out(clamp01((p - i * stag) / span))
            if out:
                q = 1 - q
            hh = int(sh * q)
            y = i * sh
            if hh > 0:
                screen.fill(self.bg, (0, y, w, hh))
                if 0 < q < 1:
                    screen.fill(BAND_COLORS[i % 4], (0, y + hh - line // 2, w, line))
                if out:
                    clips.append((pygame.Rect(0, y, w, hh), 0, 0))
        return clips if out else [(None, 0, 0)]

    def _cov_tiles(self, screen, p, out, t):
        w, h = self.w, self.h
        cols = 6 if self.portrait else 10
        ts = -(-w // cols)
        rows = -(-h // ts)
        diag = cols + rows - 2
        reach, dur = 0.58, 0.42
        if (not out and p >= 1) or (out and p <= 0):
            screen.fill(self.bg)
            return [(None, 0, 0)]
        for r in range(rows):
            for c in range(cols):
                d = (c + r) / diag if not out else 1 - (c + r) / diag
                q = clamp01((p - d * reach) / dur)
                q = _out_back(q, 1.4) if not out else 1 - _in_cubic(q)
                if q <= 0.01:
                    continue
                size = ts * min(1.06, q) + 2
                full = q >= 0.97
                col = self.bg if full else BAND_COLORS[(c + 2 * r) % 4]
                x, y = c * ts + (ts - size) / 2, r * ts + (ts - size) / 2
                pygame.draw.rect(screen, col, (int(x), int(y), int(size) + 1, int(size) + 1),
                                 border_radius=0 if full else int(size * 0.5 * (1 - q)))
        return [(None, 0, 0)]

    def _seam(self):
        w, h = self.w, self.h
        rng = random.Random(5)
        n = 9
        slope = -0.32 if self.portrait else -0.55
        pts = []
        for i in range(n + 1):
            x = -30 + (w + 60) * i / n
            y = self.cy + slope * (x - self.cx) + (rng.uniform(26, 60) * self.u) * (1 if i % 2 else -1)
            pts.append((x, y))
        return pts

    def _cov_slash(self, screen, p, out, t):
        """Lightning: two halves snap together on a zig-zag seam, which flashes sky blue."""
        w, h = self.w, self.h
        seam = self._seam()
        far = max(w, h) * 0.9
        if not out:
            k = 1 - out_expo(p)
        else:
            k = _in_cubic(p)
        dx, dy = 0.35 * far * k, far * k
        top = [(x - dx, y - dy) for x, y in seam] + [(w + 40 - dx, -40 - dy - far), (-40 - dx, -40 - dy - far)]
        bot = [(x + dx, y + dy) for x, y in seam] + [(w + 40 + dx, h + 40 + dy + far), (-40 + dx, h + 40 + dy + far)]
        pygame.draw.polygon(screen, self.bg, top)
        pygame.draw.polygon(screen, self.bg, bot)
        if not out and p >= 1:   # the strike: the seam flashes, then cools into the stage
            a = t - STYLES["slash"][0]
            if a < 0.45:
                col = gfx.mix(INK, SKY, a / 0.15) if a < 0.15 else gfx.mix(SKY, self.bg, (a - 0.15) / 0.3)
                pygame.draw.lines(screen, col, False, seam, max(3, int(12 * self.u * (1 - a / 0.45))))
        elif out and p < 0.5:
            pygame.draw.lines(screen, SKY, False, [(x - dx, y - dy) for x, y in seam], max(2, int(6 * self.u)))
            pygame.draw.lines(screen, SKY, False, [(x + dx, y + dy) for x, y in seam], max(2, int(6 * self.u)))
        return [(None, 0, 0)]

    def _aperture(self, screen, r, cx=None, cy=None):
        """Everything outside the circle r in the cover colour (a thick circle, no surfaces)."""
        cx = self.cx if cx is None else cx
        cy = self.cy if cy is None else cy
        big = self.r_full + int(abs(cx - self.cx) + abs(cy - self.cy)) + 8
        if r <= 0:
            screen.fill(self.bg)
        elif r < big:
            pygame.draw.circle(screen, self.bg, (int(cx), int(cy)), big, width=int(big - r))

    def _iris_ring(self, screen, r, rot, drawn=1.0):
        rw = max(8, int(r * 0.075 + 6 * self.u))
        gfx.ring(screen, self.cx, self.cy, r + rw * 0.5, rw, drawn=drawn, track=False, rot=rot, gap=5.0)

    def _cov_iris(self, screen, p, out, t):
        """The LQ ring as the aperture. Closing it spins; opening it winds up (a little smaller,
        turning back), then flies outward: the camera pushes through the logo."""
        R = self.r_full
        logo = int(150 * self.u)
        if not out:
            r = (R + 40) * (1 - _in_out(p))
            self._aperture(screen, r)
            if r > 2:
                self._iris_ring(screen, r, -160 * _out_cubic(p))
            return [(None, 0, 0)]
        wind = _prog(p, 0.0, 0.28)
        fly = in_expo(_prog(p, 0.22, 0.78))
        r = logo * _out_back(wind, 2.2) * (1 - 0.12 * smoothstep(_prog(p, 0.14, 0.12))) + (R + 80) * fly
        self._aperture(screen, r)
        if r > 2:
            self._iris_ring(screen, r, 40 * (1 - wind) - 90 * fly)
        return [(None, 0, 0)]

    def _cov_spotlight(self, screen, p, out, t):
        """In: lights out, two shutters meet at the centre with a gold edge. Out: the light pool
        opens into the question with a warm rim."""
        w, h = self.w, self.h
        if not out:
            k = _in_out(p)
            y = int(self.cy * k)
            yb = int(self.cy + (h - self.cy) * (1 - k))
            screen.fill(self.bg, (0, 0, w, y))
            screen.fill(self.bg, (0, yb, w, h - yb))
            if p < 1:
                e = max(2, int(5 * self.u))
                screen.fill(ACCENT, (0, y - e, w, e))
                screen.fill(ACCENT, (0, yb, w, e))
            return [(None, 0, 0)]
        r = (self.r_full + 60) * _in_cubic(_prog(p, 0.08, 0.92)) + 160 * self.u * _out_back(_prog(p, 0, 0.2))
        self._aperture(screen, r)
        if r > 4:
            pygame.draw.circle(screen, ACCENT, (self.cx, self.cy), int(r + 4 * self.u), max(2, int(7 * self.u)))
            pygame.draw.circle(screen, gfx.mix(ACCENT, self.bg, 0.5), (self.cx, self.cy), int(r + 16 * self.u),
                               max(1, int(4 * self.u)))
        return [(None, 0, 0)]

    # ------------------------------------------
    # CUT: cover style -> card (bumper or build-up) -> the style's uncover
    # ------------------------------------------
    def _draw_cut(self, screen, t):
        cin, cout = STYLES[self.style]
        t_in = t + self._lead
        if t < 0:
            if t_in >= cin:
                screen.fill(self.bg)
                clips = [(None, 0, 0)]
            else:
                clips = self._cover(screen, self.style, t_in / cin, False, t_in)
            sink = 0.0
            if self.style == "slash" and t_in >= cin:
                self._cov_slash(screen, 1.0, False, t_in)
        else:
            clips = self._cover(screen, self.style, t / cout, True, t)
            sink = clamp01(t / (cout * 0.4)) if self.style in SINKERS else 0.0
        card = self._draw_buildup_card if self.kind == "buildup" else self._draw_question_card
        riding = self.style in ("bands", "ribbon")
        riders = riding or (t < 0 and t_in >= cin) or (t >= 0 and (self.style in ("doors", "slats") or sink < 0.25))
        for clip, ox, oy in clips:
            if clip is not None:
                if clip.w <= 0 or clip.h <= 0:
                    continue
                old = screen.get_clip()
                screen.set_clip(clip.clip(old))
            if riders:
                for rd in self._riders:
                    rd.draw(screen, ox, oy, t_in, self.bg)
            card(screen, t_in, ox, oy, sink)
            if clip is not None:
                screen.set_clip(old)

    # ------------------------------------------
    # 1. QUESTION BUMPER (no BUILDUP state): "QUESTION 3 -> 4"
    # ------------------------------------------
    def _build_question(self):
        info, u = self.info, self.u
        n, ev = info["n"], info.get("event", "")
        diff = info.get("difficulty", "")
        label, lcol, sub = {
            "final": ("FINAL QUESTION", ACCENT, [("DOUBLE POINTS", INK), ("  ·  EVERYTHING CAN CHANGE", LILAC)]),
            "lightning": ("LIGHTNING ROUND", SKY, [(f"{LIGHTNING_TIME} SECONDS", INK), ("  ·  1.5x POINTS", LILAC)]),
            "bonus": ("BONUS ROUND", PURPLE, [("EXTRA POINTS", INK), ("  ·  UP FOR GRABS", LILAC)]),
            **SPECIAL_BUMPERS,
            "next_match": ("NEXT MATCH", ACCENT, [("VOTE THE CATEGORY", INK), ("  ·  TYPE 1-4", LILAC)]),
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

    def _build_next_match(self):
        self._build_question()

    def _draw_question_card(self, screen, t_in, ox, oy, sink=0.0):
        s, u = self._s, self.u
        settle = STYLES[self.style][0] - 0.02
        hold = self._lead - self.LEAD["question"] if self.kind == "question" else 0.0   # events hold longer
        keep = 1 - sink
        cx = self.cx + ox
        lab = s["label"]
        _rise(screen, lab, cx - lab.get_width() // 2, s["lab_y"] + oy,
              keep if self.style == "bands" or self.style == "ribbon" else _out_cubic(_prog(t_in, settle - 0.1, 0.3)) * keep)
        # Numeral: the previous question's number rides in on the curtain, then rolls over
        nr = s["num_rect"].move(ox, oy)
        roll = _out_back(_prog(t_in, settle + 0.02 + hold, 0.30), 1.25) if s["old"] is not None else 1.0
        h = nr.h + 40
        if roll < 1:
            old = s["old"]
            _clip_blit(screen, old, cx - old.get_width() // 2, nr.y - roll * h + sink * h, nr)
        new = s["new"]
        _clip_blit(screen, new, cx - new.get_width() // 2, nr.y + (1 - roll) * h + sink * h, nr)
        sub = s["sub"]
        _rise(screen, sub, cx - sub.get_width() // 2, s["sub_y"] + oy,
              _out_cubic(_prog(t_in, settle + 0.12 + hold, 0.28)) * keep)
        # Pips: one per question, the upcoming one lights as the number rolls (not between matches)
        if self.kind == "question" and keep > 0.5:
            self._pips(screen, cx, s["pip_y"] + oy, self.info.get("pips", []), self.info["n"], roll > 0.5)
        ev = self.info.get("event")
        if ev in ("final", "lightning") and keep > 0.3:
            pop = _out_back(_prog(t_in, settle + 0.24 + hold, 0.3), 2.2)
            bx, by = cx + new.get_width() // 2 + int(76 * u), nr.y + int(70 * u)
            if pop > 0 and ev == "final":
                pygame.draw.circle(screen, ACCENT, (bx, by), int(62 * u * pop))
                if pop > 0.7:
                    screen.blit(s["x2"], s["x2"].get_rect(center=(bx, by)))
            elif pop > 0:
                _shape(screen, "bolt", bx, by, 66 * u * pop, 0, ACCENT)

    def _pips(self, screen, cx, py, pips, n, lit_now, count=MATCH_LENGTH):
        u = self.u
        step, pw, ph = int(50 * u), int(40 * u), int(16 * u)
        px = cx - (count * step - (step - pw)) // 2
        off = gfx.mix(PIP_OFF, self.bg, 0.25)
        for i in range(count):
            x = px + i * step
            lit = i == n - 1 and lit_now
            col = (GOOD if pips[i] == "done" else BAD) if i < len(pips) else ACCENT if lit else off
            pygame.draw.rect(screen, col, (x, py, pw, ph), border_radius=ph // 2)
            if lit:
                o = int(6 * u)
                pygame.draw.rect(screen, ACCENT, (x - o, py - o, pw + 2 * o, ph + 2 * o), width=3,
                                 border_radius=ph // 2 + o)

    # ------------------------------------------
    # 2. BUILD-UP (BUILDUP state): the next hurdle, escalating with intensity
    # ------------------------------------------
    # t_in = seconds into BUILDUP. After the cover (cin):
    #   cin        headline, the number rides in and rolls from the last question to this one,
    #              the match pips light the new one
    #   1.2 s      the stakes slam ("FOR 40 POINTS") on the controller's "stakes" hit; the
    #              stage shakes in proportion to intensity
    #   +0.25      the tier ladder appears, its rungs light up to this question's tier
    #   +0.75      the tension line rises; then a spotlight sweeps in and finds the player
    #   always     a four-colour fuse burns down to the question
    # intensity 0 (Q1): bright violet, playful shapes, a gentle pop. 1 (Q10): lights down,
    # heartbeat rings and a pool of light behind the number, a hard slam with a shake.
    def _build_buildup(self):
        info, u, P = self.info, self.u, self.portrait
        n, of = info["n"], info.get("of", MATCH_LENGTH)
        k = info["intensity"]
        ev, kind = info["event"], info["round"]
        special = SPECIAL_BUMPERS.get(kind)
        accent = EVENT_COLORS.get(ev) or (special[1] if special else None)
        col_w = (self.w - 2 * self.margin) if P else int(self.w * 0.44)
        s = {"accent": accent or ACCENT, "col_w": col_w}
        s["head"] = self._fit_line([(info["headline"].upper(), accent or LILAC)], "black",
                                   (46, 42, 38, 34, 30), max(2, int(4 * u)), col_w if P else int(self.w * 0.40))
        num_size = int((380 if P else 360) * u)
        s["new"] = self._text("display", num_size, str(n), INK)
        s["old"] = self._text("display", num_size, str(n - 1), INK) if n > 1 else None
        stakes = info.get("stakes")
        try:
            stakes_txt = f"{int(round(float(stakes))):,}" if stakes is not None else ""
        except (TypeError, ValueError):
            stakes_txt = str(stakes)
        s["stakes"] = None
        if stakes_txt and stakes_txt != "0":
            for size in (150, 132, 116, 100, 86):
                font = self.fonts.get("display", int(size * u))
                if font.size(f"FOR {stakes_txt} POINTS")[0] <= col_w:
                    break
            s["stakes"] = _tight(gfx.gold_text(font, f"FOR {stakes_txt} POINTS"))
        lines, size = self._wrap(info["subline"], "semi", (42, 38, 34), col_w, 2) if info["subline"] else ([], 0)
        s["sub"] = [self._text("semi", size, ln, INK) for ln in lines]
        s["sub_lh"] = int(size * 1.22)
        spot = info.get("spotlight")
        s["spot"] = None
        if spot:
            name = str(spot).replace("[Bot] ", "")
            label = self._line([("IN THE SPOTLIGHT", LILAC)], "black", int(24 * u), max(2, int(4 * u)))
            nm = self._text("black", int(46 * u), name, ACCENT)
            if nm.get_width() > col_w - 120 * u:
                nm = self._text("black", int(34 * u), name[:24], ACCENT)
            init = self._text("black", int(40 * u), (name.lstrip("@") or "?")[0].upper(), INK)
            s["spot"] = (label, nm, init)
        # Ladder: four chevron rungs, tier labels
        cur = TIERS.index(info["tier"])
        rung_gap = int(10 * u)
        rung_w = min(int(232 * u), (col_w - 3 * rung_gap) // 4)
        rung_h = int(66 * u)
        s["rungs"] = (cur, rung_w, rung_h, rung_gap,
                      [(self._text("black", int(25 * u), tr.upper(), DARK_INK),
                        self._text("black", int(25 * u), tr.upper(), gfx.mix(LILAC, self.bg, 0.45))) for tr in TIERS])
        # Stack the blocks (portrait: one column; TV: number left, the rest right)
        num_h = s["new"].get_height()
        g = u
        left = [("head", s["head"].get_height(), 30 * g), ("num", num_h, 34 * g), ("pips", int(16 * u), 0)]
        right = []
        if s["stakes"] is not None:
            right.append(("stakes", s["stakes"].get_height(), 48 * g))
        right.append(("ladder", rung_h, 46 * g))
        if s["sub"]:
            right.append(("sub", s["sub_lh"] * len(s["sub"]), 40 * g))
        if s["spot"]:
            right.append(("spot", int(30 * u + 12 * u + 64 * u), 40 * g))
        right.append(("fuse", int(10 * u), 0))
        pos = {}
        if P:
            blocks = left[:-1] + [("pips", int(16 * u), 58 * g)] + right
            total = sum(h + gap for _, h, gap in blocks)
            y = self.cy - total // 2
            for name, h, gap in blocks:
                pos[name] = (int(self.cx), int(y))
                y += h + gap
        else:
            for column, cx in ((left, int(self.w * 0.26)), (right, int(self.w * 0.71))):
                total = sum(h + gap for _, h, gap in column)
                y = self.cy - total // 2
                for name, h, gap in column:
                    pos[name] = (int(cx), int(y))
                    y += h + gap
        s["pos"] = pos
        s["num_rect"] = pygame.Rect(pos["num"][0] - (s["new"].get_width() + int(60 * u)) // 2, pos["num"][1],
                                    s["new"].get_width() + int(60 * u), num_h)
        self._s = s
        self._riders = []
        if k < 0.55 and self.style != "spotlight":
            self._make_riders(BUILDUP_RIDERS, n)
            if k >= 0.3:
                self._riders = self._riders[::2]

    def _draw_buildup_card(self, screen, t_in, ox, oy, sink=0.0):
        s, u, info = self._s, self.u, self.info
        D = self._lead
        k = info["intensity"]
        cin = STYLES[self.style][0]
        keep = 1 - sink
        pos = s["pos"]
        spot_style = self.style == "spotlight"
        # Beats; the ones after the slam squeeze when the state is short
        t_slam = max(T_STAKES, cin + 0.35)
        squeeze = clamp01((D - 0.55 - t_slam) / 1.7) if D > t_slam else 0.3
        t_ladder = t_slam + 0.25 * max(0.5, squeeze)
        t_sub = t_slam + 0.75 * max(0.4, squeeze)
        t_spot = t_sub + 0.4 * max(0.4, squeeze)
        a_slam = t_in - t_slam
        if 0 <= a_slam < 0.6 and k > 0.15 and sink == 0:   # the slam shakes the whole card
            dx, dy = shake(a_slam, 3 + 18 * k, decay=9)
            ox, oy = ox + int(dx), oy + int(dy)
        num_c = (pos["num"][0] + ox, pos["num"][1] + s["new"].get_height() // 2 + oy)
        # Intensity: a pool of light behind the number and heartbeat rings
        if k >= 0.35 and keep > 0 and t_in > cin:
            beat = heartbeat(((t_in - cin) % (1.15 - 0.45 * k)))
            lvl = round((0.35 + 0.65 * k) * (0.75 + 0.25 * beat) * 4) / 4
            col = tuple(int(c * lvl * 0.55) for c in (s["accent"] if self.info["event"] else (140, 120, 255)))
            light = gfx.add_light(int(330 * u), col, 1.8)
            if not spot_style or t_in > cin + 0.85:
                screen.blit(light, light.get_rect(center=num_c), special_flags=pygame.BLEND_RGB_ADD)
            if k >= 0.5:
                per = 1.15 - 0.45 * k
                a = ((t_in - cin) % per) / per
                rr = int((240 + 260 * _out_cubic(a)) * u)
                pygame.draw.circle(screen, gfx.mix(s["accent"], self.bg, 0.35 + 0.65 * a), num_c, rr,
                                   max(1, int(5 * u * (1 - a))))
        # Headline
        hd = s["head"]
        head_t = cin - 0.05 + (0.8 if spot_style else 0.0)
        hx, hy = pos["head"]
        _rise(screen, hd, hx + ox - hd.get_width() // 2, hy + oy, _out_cubic(_prog(t_in, head_t, 0.3)) * keep)
        # Number: rides in, rolls from the last question to this one (spotlight: found in the dark)
        nr = s["num_rect"].move(ox, oy)
        new, old = s["new"], s["old"]
        hgt = nr.h + 40
        if spot_style:
            self._spot_number(screen, t_in, nr, new, cin, sink * hgt)
            roll = 1.0
        else:
            roll = _out_back(_prog(t_in, cin + 0.1, 0.32), 1.25) if old is not None else _out_cubic(_prog(t_in, cin - 0.05, 0.4))
            if old is not None and roll < 1:
                _clip_blit(screen, old, nr.centerx - old.get_width() // 2, nr.y - roll * hgt + sink * hgt, nr)
            if old is not None or roll > 0:
                _clip_blit(screen, new, nr.centerx - new.get_width() // 2, nr.y + (1 - roll) * hgt + sink * hgt, nr)
        if keep > 0.5:
            self._pips(screen, pos["pips"][0] + ox, pos["pips"][1] + oy, info.get("pips", []), info["n"],
                       roll > 0.5 and t_in > cin + 0.2, info.get("of", MATCH_LENGTH))
        # Stakes slam
        st = s["stakes"]
        if st is not None and keep > 0:
            self._stakes(screen, st, pos["stakes"], ox, oy, a_slam, k, keep)
        # Tier ladder
        self._ladder(screen, pos["ladder"], ox, oy, t_in - t_ladder, keep)
        # Tension line
        if s["sub"]:
            sx, sy = pos["sub"]
            for j, ln in enumerate(s["sub"]):
                _rise(screen, ln, sx + ox - ln.get_width() // 2, sy + oy + j * s["sub_lh"],
                      _out_cubic(_prog(t_in, t_sub + j * 0.08, 0.32)) * keep)
        # Spotlighted player: a pool of light sweeps in and finds the name
        if s["spot"]:
            self._spot_player(screen, pos["spot"], ox, oy, t_in - t_spot, keep)
        # Fuse: four colours burning down to the question
        fx_, fy_ = pos["fuse"]
        fw = s["col_w"] if self.portrait else int(self.w * 0.40)
        grow = _out_cubic(_prog(t_in, cin + 0.2, 0.35)) * keep
        if grow > 0:
            frac = clamp01(1 - (t_in - cin - 0.2) / max(0.4, D - cin - 0.2)) * grow
            fh = max(4, int(10 * u))
            x0 = fx_ + ox - fw // 2
            pygame.draw.rect(screen, gfx.mix(PIP_OFF, self.bg, 0.55), (x0, fy_ + oy, fw, fh), border_radius=fh // 2)
            seg = fw / 4
            burn = fw * frac
            for i, col in enumerate(BAND_COLORS):
                a, b = i * seg, min((i + 1) * seg, burn)
                if b > a:
                    pygame.draw.rect(screen, col, (int(x0 + a), fy_ + oy, int(b - a) + 1, fh),
                                     border_radius=fh // 2 if i in (0, 3) else 0)
            if 0.01 < frac < 1:
                spark = gfx.add_light(int(30 * u), (255, 220, 150), 1.6)
                screen.blit(spark, spark.get_rect(center=(int(x0 + burn), fy_ + oy + fh // 2)),
                            special_flags=pygame.BLEND_RGB_ADD)

    def _spot_number(self, screen, t_in, nr, num, cin, drop):
        """Final question: the number sits in the dark; a light pool searches the stage, finds
        it and the number lights up."""
        u = self.u
        find = _prog(t_in, cin + 0.02, 0.85)
        cx, cy = nr.centerx, nr.centery
        swing = math.sin(find * math.pi * 2.4) * (1 - find) ** 1.25
        px = int(cx + swing * self.w * 0.48)
        py = int(cy + math.sin(find * math.pi * 3.1) * 70 * u * (1 - find))
        pool_r = int(300 * u)
        pool = gfx.add_light(pool_r, (190, 170, 120), 1.7)
        screen.blit(pool, pool.get_rect(center=(px, py)), special_flags=pygame.BLEND_RGB_ADD)
        x, y = nr.centerx - num.get_width() // 2, nr.y + drop
        lit = clamp01((t_in - cin - 0.87) / 0.22)
        if lit >= 1:
            _clip_blit(screen, num, x, y, nr)
            return
        dim = gfx.faded(num, 34, ("bu_num_dim", num.get_size(), self.info["n"]))
        _clip_blit(screen, dim, x, y, nr)
        # The bright number, masked by the pool: only what the light touches shows
        m = pygame.Surface(num.get_size(), pygame.SRCALPHA)
        m.fill((255, 255, 255, 0))
        mask = gfx.radial(int(pool_r * 0.8), (255, 255, 255), 255, 1.3)
        m.blit(mask, (px - pool_r * 0.8 - x, py - pool_r * 0.8 - y))
        m.blit(num, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        _clip_blit(screen, m, x, y, nr)
        if lit > 0:
            _clip_blit(screen, gfx.faded(num, 255 * lit, ("bu_num_lit", num.get_size(), self.info["n"]), levels=8), x, y, nr)

    def _stakes(self, screen, st, p0, ox, oy, a, k, keep):
        u = self.u
        cx, top = p0[0] + ox, p0[1] + oy
        fall = 0.16 if k > 0.25 else 0.24
        if a < -fall:
            return
        w, h = st.get_size()
        if a < 0:
            q = (a + fall) / fall
            sc = lerp(2.2 if k > 0.25 else 1.35, 1.0, _in_cubic(q) if k > 0.25 else _out_cubic(q))
        else:
            sc = 1 - 0.07 * math.exp(-a * 10) * math.sin(a * 38) if a < 0.6 else 1.0
        if keep < 1:   # sinks into its baseline on the way out
            _rise(screen, st, cx - w // 2, top, keep)
            return
        if sc != 1.0:
            sw, sh = max(1, int(w * sc)), max(1, int(h * sc))
            img = pygame.transform.smoothscale(st, (sw, sh))
            if a < 0 and a + fall < 0.08:
                img.set_alpha(int(255 * clamp01((a + fall) / 0.08)))
            screen.blit(img, (cx - sw // 2, top + h // 2 - sh // 2))
        else:
            screen.blit(st, (cx - w // 2, top))
        if 0 <= a < 0.42:   # the hit: a ring of light leaves the stakes
            q = a / 0.42
            g = int(70 * u * _out_cubic(q))
            rect = pygame.Rect(cx - w // 2 - int(24 * u) - g, top - int(18 * u) - g, w + int(48 * u) + 2 * g,
                               h + int(36 * u) + 2 * g)
            pygame.draw.rect(screen, gfx.mix(ACCENT, self.bg, q), rect, width=max(1, int(7 * u * (1 - q))),
                             border_radius=int(30 * u) + g // 2)

    def _ladder(self, screen, p0, ox, oy, a, keep):
        cur, rw, rh, gap, labels = self._s["rungs"]
        u = self.u
        total = 4 * rw + 3 * gap
        x0 = p0[0] + ox - total // 2
        y0 = p0[1] + oy
        sk = int(18 * u)
        off = gfx.mix(PIP_OFF, self.bg, 0.2)
        for i, tier in enumerate(TIERS):
            appear = _out_back(_prog(a, i * 0.05, 0.3), 1.6) * keep
            if appear <= 0:
                continue
            x = x0 + i * (rw + gap)
            y = y0 + (1 - appear) * 26 * u
            pts = [(x + (sk if i else 0), y + rh / 2), (x, y), (x + rw - sk, y), (x + rw, y + rh / 2),
                   (x + rw - sk, y + rh), (x, y + rh)]
            if i == 0:
                pts = [(x, y), (x + rw - sk, y), (x + rw, y + rh / 2), (x + rw - sk, y + rh), (x, y + rh)]
            light = _prog(a, 0.22 + i * 0.13, 0.18) if i <= cur else 0.0
            col = TIER_COLORS[tier]
            if light > 0:
                fill = gfx.mix(INK, col, light) if i == cur else gfx.mix(gfx.mix(INK, col, light), self.bg, 0.42)
                if i == cur and light >= 1:   # the rung that counts breathes
                    fill = gfx.mix(col, INK, 0.18 * (0.5 + 0.5 * math.sin(a * 6)))
                pygame.draw.polygon(screen, fill, pts)
                pygame.gfxdraw.aapolygon(screen, [(int(px), int(py)) for px, py in pts], fill)
                lab = labels[i][0]
            else:
                pygame.draw.polygon(screen, gfx.mix(off, self.bg, 0.55), pts)
                pygame.draw.lines(screen, off, True, pts, max(2, int(3 * u)))
                lab = labels[i][1]
            screen.blit(lab, lab.get_rect(center=(int(x + rw / 2 + (sk / 3 if i else -sk / 4)), int(y + rh / 2))))
            if i == cur and light > 0:
                g = 1 - light if light < 1 else 0.0
                if g > 0:   # the flash as it lights
                    pygame.draw.polygon(screen, INK, [(px + (px - x - rw / 2) * 0.15 * g, py + (py - y - rh / 2) * 0.4 * g)
                                                      for px, py in pts], max(2, int(4 * u)))

    def _spot_player(self, screen, p0, ox, oy, a, keep):
        label, nm, init = self._s["spot"]
        u = self.u
        cx, top = p0[0] + ox, p0[1] + oy
        if a < 0:
            return
        _rise(screen, label, cx - label.get_width() // 2, top, _out_cubic(_prog(a, 0, 0.3)) * keep)
        ar = int(32 * u)
        plate_w = 2 * ar + int(18 * u) + nm.get_width()
        px0 = cx - plate_w // 2
        py = top + int(30 * u + 12 * u) + int(32 * u)
        land = _out_back(_prog(a, 0.05, 0.6), 1.3)
        pool_x = int(lerp(self.w + 260 * u, cx, land))
        if keep > 0:
            pool = gfx.add_light(int(190 * u), (150, 130, 90), 1.6)
            screen.blit(pool, pool.get_rect(center=(pool_x, py)), special_flags=pygame.BLEND_RGB_ADD)
        p = _out_cubic(_prog(a, 0.4, 0.3)) * keep
        if p > 0:
            ay = int(py + (1 - p) * 30 * u)
            pygame.draw.circle(screen, gfx.mix(self.bg, (0, 0, 0), 0.3), (px0 + ar, ay), ar)
            pygame.draw.circle(screen, ACCENT, (px0 + ar, ay), ar, max(2, int(4 * u)))
            screen.blit(init, init.get_rect(center=(px0 + ar, ay)))
            _rise(screen, nm, px0 + 2 * ar + int(18 * u), py - nm.get_height() // 2, p)

    # ------------------------------------------
    # 3. MATCH OPEN: the LQ ring iris
    # ------------------------------------------
    # Cover:  the logo ring closes over the lobby as an aperture, spinning into place, and
    #         swallows what is left inside it.
    # Hold:   LQ and the wordmark rise in the ring, "• LIVE · MATCH N", a dotted orbit.
    # Uncover (after LOBBY -> INTRO): the ring winds up, then the camera pushes through it
    #         and the answer shapes plus a burst of HQ shapes fly out over "MATCH N".
    def _build_match_open(self):
        u = self.u
        orbit = int(min(self.w, self.safe_bottom - self.safe_top) * 0.46)
        ring = int(orbit * 0.6)    # the Spotlight LQ logo, at the logo's own proportions
        lq = self._ring_logo_lq(int(ring * 0.86))
        word = gfx.tracked(self.fonts.get("black", max(12, int(ring * 0.105))), "THE LIFELONG QUIZ", INK, max(2, ring // 45))
        tag = self._line([(f"LIVE  ·  MATCH {self.info.get('match_no', '')}", LILAC)], "black", int(34 * u), 6)
        s = {"lq": lq, "word": word, "tag": tag, "ring": ring, "orbit": orbit, "rw": max(6, ring // 11),
             "lq_y": self.cy - int(ring * 0.044) - lq.get_height() // 2,
             "word_y": self.cy + int(ring * 0.51) - word.get_height() // 2,
             "tag_y": self.cy + orbit + int(30 * u)}
        if s["tag_y"] + tag.get_height() > self.safe_bottom:
            s["tag_y"] = self.cy + ring + int(36 * u)
        self._s = s
        rng = random.Random(self.info.get("match_no", 0))
        self._burst = []
        sp_u = self.r_full / 1100
        for k in range(4):   # the answer shapes launch first, each out of its own quarter of the ring
            a = math.radians(-45 + k * 90)
            self._burst.append((ANSWER_SHAPES[k], BAND_COLORS[k], self.cx + math.cos(a) * ring, self.cy + math.sin(a) * ring,
                                math.cos(a) * 1900 * sp_u, math.sin(a) * 1500 * sp_u, 34 * u, rng.uniform(-3, 3)))
        for _ in range(30):
            a = rng.uniform(0, 6.283)
            sp = rng.uniform(1300, 2600) * sp_u
            self._burst.append((rng.choice(("circle", "circle", "ring", "cross", "hex")), rng.choice(SHAPE_COLORS),
                                self.cx + math.cos(a) * 60 * u, self.cy + math.sin(a) * 40 * u,
                                math.cos(a) * sp, math.sin(a) * sp * 0.75, rng.choice((10, 14, 18, 24, 30)) * u,
                                rng.uniform(-4, 4)))

    def _ring_logo_lq(self, size):
        key = ("lq", size)
        s = self._cache.get(key)
        if s is None:
            s = _tight(gfx.gold_text(self.fonts.get("display", size), "LQ"))
            self._store(key, s)
        return s

    def _draw_match_open(self, screen, t):
        t_in = t + self._lead
        s, u, R = self._s, self.u, self.r_full
        ring, rw = s["ring"], s["rw"]
        if t < 0:
            close = _in_out(_prog(t_in, 0, self.IRIS_CLOSE))
            r = lerp(R + 60, ring + rw, close)                 # the aperture's edge = the ring's outer edge
            self._aperture(screen, r)
            fill = _in_out(_prog(t_in, self.IRIS_CLOSE - 0.08, self.IRIS_FILL))
            if fill > 0:                                       # the inside closes too: the lobby is swallowed
                pygame.draw.circle(screen, self.bg, (self.cx, self.cy), max(1, int(r * fill)))
            width = lerp(max(rw, R * 0.06), rw, close)
            gfx.ring(screen, self.cx, self.cy, r, int(width), track=False, rot=-200 * (1 - _out_cubic(_prog(t_in, 0, 0.6))))
            settle = self.IRIS_CLOSE + self.IRIS_FILL
            # Dotted orbit draws on clockwise
            orbit = _out_cubic(_prog(t_in, settle - 0.05, 0.45)) * (1 - _in_cubic(_prog(t, -0.2, 0.2)))
            ro = s["orbit"]
            if orbit > 0:
                n_dots = 72
                spin = t_in * 0.35
                for i in range(int(n_dots * orbit)):
                    a = spin + i * 6.2832 / n_dots
                    pygame.draw.circle(screen, PIP_OFF, (int(self.cx + math.cos(a) * ro), int(self.cy + math.sin(a) * ro)),
                                       max(2, int(4 * u)))
            sink = 1 - _in_cubic(_prog(t, -0.2, 0.2))
            lq, word = s["lq"], s["word"]
            _rise(screen, lq, self.cx - lq.get_width() // 2, s["lq_y"], _out_cubic(_prog(t_in, settle + 0.02, 0.32)) * sink)
            _rise(screen, word, self.cx - word.get_width() // 2, s["word_y"], _out_cubic(_prog(t_in, settle + 0.16, 0.3)) * sink)
            tag = s["tag"]
            tp = _out_cubic(_prog(t_in, settle + 0.32, 0.28)) * sink
            if tp > 0:
                tx = self.cx - tag.get_width() // 2 + int(14 * u)
                _rise(screen, tag, tx, s["tag_y"], tp)
                pygame.draw.circle(screen, BAD, (tx - int(26 * u), s["tag_y"] + tag.get_height() // 2), int(9 * u * tp))
            return
        # Uncover: wind up (the ring tightens and turns back while its inside opens onto the
        # intro), then the camera pushes through it
        wind = _prog(t, 0.0, 0.18)
        fly = in_expo(_prog(t, 0.14, 0.5))
        width = rw * (1 + 3 * fly)
        r_mid = ring * (1 - 0.1 * math.sin(math.pi * wind)) + (R + 140) * fly
        r_in = r_mid - width / 2
        self._aperture(screen, r_mid + width / 2)
        hole = r_in * _out_cubic(_prog(t, 0.03, 0.16))
        if r_in - hole >= 1:
            if hole < 1:
                pygame.draw.circle(screen, self.bg, (self.cx, self.cy), int(r_in) + 1)
            else:
                pygame.draw.circle(screen, self.bg, (self.cx, self.cy), int(r_in) + 1, width=int(r_in - hole) + 1)
        gfx.ring(screen, self.cx, self.cy, r_mid + width / 2, int(width), track=False, rot=-35 * wind + 120 * fly)
        if t > 0.18:
            self._draw_burst(screen, t - 0.18)

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
    # 4. FINAL CURTAIN: "AND THE WINNER IS..." into the podium
    # ------------------------------------------
    # Cover:  violet panels drop centre-out with a gold fringe and a small bounce.
    # Hold:   match line, the big line (one line on TV, stacked on Shorts), a spotlight pool
    #         searches across the words and settles on them, three gold dots tick in.
    # Uncover (after REVEALING -> PODIUM): panels fly up centre-out; the text rides the
    #         first panels so it never sits over the podium.
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
        self._s = {"label": label, "lines": list(zip(surfs, ys)), "x": x, "lab_y": top, "block": (x, top, block_w, total),
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
        s = self._s
        settle = (cols // 2) * self.DROP_STAG + self.DROP_DUR - 0.1
        # The searching spotlight: sweeps the words, settles on them, goes out as the panels lift
        if t < 0 and t_in > settle - 0.15:
            bx, by, bw, bh = s["block"]
            q = _prog(t_in, settle - 0.15, self._lead - settle - 0.1)
            px = bx + bw * (0.5 + 0.62 * math.sin(q * math.pi * 2.2) * (1 - q) ** 1.1)
            py = by + bh * (0.55 + 0.18 * math.sin(q * math.pi * 3.0) * (1 - q))
            pool = gfx.add_light(int(360 * self.u), (120, 105, 70), 1.6)
            screen.blit(pool, pool.get_rect(center=(int(px), int(py))), special_flags=pygame.BLEND_RGB_ADD)
        oy_card = int(min(bottoms) - full) if t >= 0 else 0      # ride the first panel that lifts
        for rd in self._riders:
            oy = bottoms[min(cols - 1, max(0, int(rd.hx // cw)))] - full
            rd.draw(screen, 0, min(oy, oy_card) if t >= 0 else oy, t_in)
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
