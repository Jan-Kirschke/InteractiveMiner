"""
The Lifelong Quiz - "Prime Time" broadcast UI
A TV game-show look: deep stage blue, moving spotlights, tall condensed headlines,
colour + number + shape coded answers, and show moments (match intro, suspense lock,
animated answer split, podium rise with confetti, a typewriter AI-host caption).

Layout (1920x1080): header (brand, match pips, live pill) / main stage left /
social rail right (460 px) / footer (host caption + commands).
"""

import math
import random
import time

import pygame

from quiz.config import SCREEN_WIDTH, SCREEN_HEIGHT, FONT_DIR, MATCH_LENGTH
from quiz.models import GameState
from quiz.logic import is_bot

# ==========================================
# PALETTE
# ==========================================
BG_DEEP = (5, 6, 26)
BG_STAGE = (26, 31, 107)
INK = (255, 255, 255)
DIM = (176, 181, 222)
FAINT = (110, 116, 170)
TRACK = (52, 58, 120)
ACCENT = (255, 210, 63)
GOOD = (46, 229, 157)
BAD = (255, 90, 95)
DARK_INK = (17, 17, 34)
OPTION_COLORS = [(255, 77, 109), (58, 134, 255), (255, 159, 28), (20, 201, 168)]
EVENT_STYLE = {
    "final": ("FINAL QUESTION  x2", ACCENT),
    "lightning": ("LIGHTNING  1.5x", (110, 190, 255)),
    "first_blood": ("FIRST BLOOD BONUS", (255, 110, 110)),
    "jackpot": ("JACKPOT ROUND", (190, 120, 255)),
}
DIFF_COLORS = {"easy": GOOD, "medium": (255, 159, 28), "hard": BAD}

# ==========================================
# LAYOUT
# ==========================================
PAD = 44
HEADER_Y, HEADER_H = 36, 88
RAIL_W = 460
GAP = 40
MAIN_X = PAD
MAIN_W = SCREEN_WIDTH - 2 * PAD - RAIL_W - GAP
RAIL_X = SCREEN_WIDTH - PAD - RAIL_W
BODY_Y = HEADER_Y + HEADER_H + 28
FOOTER_Y = SCREEN_HEIGHT - 36 - 64
BODY_BOTTOM = FOOTER_Y - 28


# ==========================================
# EASING
# ==========================================
def clamp01(t):
    return max(0.0, min(1.0, t))


def ease_out_cubic(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_out_back(t):
    t = clamp01(t)
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def ease_in_out(t):
    t = clamp01(t)
    return 3 * t * t - 2 * t * t * t


def progress(age, delay, dur):
    return clamp01((age - delay) / dur)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    t = clamp01(t)
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ==========================================
# FONTS (international names fall back to Noto Sans, then system fonts)
# ==========================================
SYSTEM_FALLBACKS = [
    "notosanscjksc", "notosanscjk", "notosanscjkjp", "microsoftyahei", "msgothic",
    "malgungothic", "notosansarabic", "segoeui", "arial", "dejavusans",
]


class Fonts:
    def __init__(self):
        self._cache = {}
        self._paths = {
            "display": FONT_DIR / "Anton-Regular.ttf",
            "black": FONT_DIR / "Barlow-ExtraBold.ttf",
            "bold": FONT_DIR / "Barlow-Bold.ttf",
            "semi": FONT_DIR / "Barlow-SemiBold.ttf",
            "noto": FONT_DIR / "NotoSans-Variable.ttf",
        }
        self._system = [p for p in (pygame.font.match_font(n) for n in SYSTEM_FALLBACKS) if p]

    def get(self, kind, size):
        key = (kind, size)
        f = self._cache.get(key)
        if f is None:
            try:
                f = pygame.font.Font(str(self._paths[kind]), size)
            except (FileNotFoundError, OSError, KeyError):
                f = pygame.font.SysFont("arial", size, bold=True)
            self._cache[key] = f
        return f

    def chain(self, kind, size):
        """Fonts to try in order for user-supplied text (names, event lines)."""
        key = ("chain", kind, size)
        c = self._cache.get(key)
        if c is None:
            c = [self.get(kind, size), self.get("noto", size)]
            for path in self._system:
                try:
                    c.append(pygame.font.Font(path, size))
                except (FileNotFoundError, OSError):
                    pass
            self._cache[key] = c
        return c


_NOTDEF = {}
_GLYPH = {}


def _missing(font, ch):
    """True if the font would draw its "missing glyph" box for ch (metrics() is unreliable)."""
    key = (id(font), ch)
    hit = _GLYPH.get(key)
    if hit is None:
        nd = _NOTDEF.get(id(font))
        if nd is None:
            s = font.render("󰀀", False, (255, 255, 255))
            nd = _NOTDEF[id(font)] = (s.get_size(), pygame.image.tobytes(s, "RGBA"))
        try:
            s = font.render(ch, False, (255, 255, 255))
            hit = (s.get_size(), pygame.image.tobytes(s, "RGBA")) == nd or s.get_width() == 0
        except (pygame.error, UnicodeError):
            hit = True
        _GLYPH[key] = hit
    return hit


def _covers(font, text):
    return all(ch.isspace() or not _missing(font, ch) for ch in set(text))


# ==========================================
# PARTICLES
# ==========================================
class Confetti:
    __slots__ = ("x", "y", "vx", "vy", "color", "w", "h", "spin", "phase", "life")

    def __init__(self, x, y, power=1.0):
        a = random.uniform(-math.pi * 0.95, -math.pi * 0.05)
        sp = random.uniform(6, 16) * power
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(a) * sp, math.sin(a) * sp
        self.color = random.choice(OPTION_COLORS + [ACCENT, INK])
        self.w, self.h = random.randint(8, 14), random.randint(12, 22)
        self.spin = random.uniform(5, 12)
        self.phase = random.uniform(0, 6.28)
        self.life = random.uniform(2.2, 3.6)


class Dust:
    __slots__ = ("x", "y", "vy", "r", "a", "tw")

    def __init__(self, anywhere=True):
        self.x = random.uniform(0, SCREEN_WIDTH)
        self.y = random.uniform(0, SCREEN_HEIGHT) if anywhere else SCREEN_HEIGHT + 10
        self.vy = random.uniform(8, 22)
        self.r = random.choice([1, 2, 2, 3])
        self.a = random.randint(40, 120)
        self.tw = random.uniform(0, 6.28)


# ==========================================
# UI MANAGER
# ==========================================
class UIManager:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.fonts = Fonts()
        self._text_cache = {}
        self._surf_cache = {}
        self._bg = self._make_background()
        self._spot = self._make_spotlight(820)
        self._shine = self._make_shine()
        self.confetti: list[Confetti] = []
        self.dust = [Dust() for _ in range(45)]
        self._last_state = None
        self._state_enter = time.time()
        self._vote_bars = {}
        self._burst_done = set()
        self._t = time.time()

    # ------------------------------------------
    # PRE-RENDERED SURFACES
    # ------------------------------------------
    def _make_background(self):
        w, h = SCREEN_WIDTH // 8, SCREEN_HEIGHT // 8
        small = pygame.Surface((w, h))
        cx, cy = w * 0.5, h * 0.62
        for y in range(h):
            for x in range(w):
                d = math.hypot((x - cx) / w, (y - cy) / h) * 1.6
                small.set_at((x, y), mix(BG_STAGE, BG_DEEP, d))
        bg = pygame.transform.smoothscale(small, (SCREEN_WIDTH, SCREEN_HEIGHT))
        stripes = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        slant = SCREEN_HEIGHT * 0.47
        for x0 in range(-SCREEN_HEIGHT, SCREEN_WIDTH, 200):
            pygame.draw.polygon(stripes, (255, 255, 255, 6), [
                (x0, SCREEN_HEIGHT), (x0 + 80, SCREEN_HEIGHT), (x0 + 80 + slant, 0), (x0 + slant, 0)])
        bg.blit(stripes, (0, 0))
        return bg

    def _make_spotlight(self, size):
        s = pygame.Surface((size, size))
        c = size // 2
        for r in range(c, 0, -6):
            v = int(38 * (1 - r / c) ** 1.6)
            pygame.draw.circle(s, (v, v, min(255, int(v * 1.3))), (c, c), r)
        return s

    def _make_shine(self):
        s = pygame.Surface((260, SCREEN_HEIGHT), pygame.SRCALPHA)
        for x in range(260):
            a = int(46 * math.sin(math.pi * x / 260))
            pygame.draw.line(s, (255, 255, 255, a), (x, 0), (x, SCREEN_HEIGHT))
        return s

    def _alpha_rect(self, w, h, color, radius):
        key = ("ar", w, h, color, radius)
        s = self._surf_cache.get(key)
        if s is None:
            s = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
            pygame.draw.rect(s, color, (0, 0, w, h), border_radius=radius)
            if len(self._surf_cache) > 800:
                self._surf_cache.clear()
            self._surf_cache[key] = s
        return s

    # ------------------------------------------
    # TEXT
    # ------------------------------------------
    def _render(self, kind, size, text, color):
        key = (kind, size, text, color)
        s = self._text_cache.get(key)
        if s is None:
            s = self.fonts.get(kind, size).render(text, True, color)
            if len(self._text_cache) > 3000:
                self._text_cache.clear()
            self._text_cache[key] = s
        return s

    def _render_name(self, text, size, color, kind="bold"):
        """User-supplied text: pick the first font that has every glyph (Latin, Cyrillic, CJK...)."""
        key = ("name", kind, size, text, color)
        s = self._text_cache.get(key)
        if s is None:
            chain = self.fonts.chain(kind, size)
            font = next((f for f in chain if _covers(f, text)), None)
            if font is None:  # emoji or unknown script: drop what no font can draw
                font = chain[1]
                text = "".join(ch for ch in text if _covers(font, ch)) or "?"
            s = font.render(text, True, color)
            if len(self._text_cache) > 3000:
                self._text_cache.clear()
            self._text_cache[key] = s
        return s

    def _fit_name(self, text, size, color, max_w, kind="bold"):
        s = self._render_name(text, size, color, kind)
        cut = text
        while s.get_width() > max_w and len(cut) > 4:
            cut = cut[:-2]
            s = self._render_name(cut.rstrip() + "...", size, color, kind)
        return s

    def _blit(self, surf, pos, anchor="topleft", alpha=255, scale=1.0):
        if scale != 1.0:
            w, h = surf.get_size()
            surf = pygame.transform.smoothscale(surf, (max(1, int(w * scale)), max(1, int(h * scale))))
        surf.set_alpha(int(max(0, min(255, alpha))))
        r = surf.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
        self.screen.blit(surf, r)
        surf.set_alpha(255)
        return r

    def _text(self, kind, size, text, color, pos, anchor="topleft", alpha=255, scale=1.0):
        return self._blit(self._render(kind, size, text, color), pos, anchor, alpha, scale)

    def _wrap(self, text, kind, size, max_w):
        font = self.fonts.get(kind, size)
        lines, cur = [], ""
        for w in text.split():
            test = f"{cur} {w}".strip()
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _fit_wrap(self, text, kind, sizes, max_w, max_lines):
        lines = [text]
        for size in sizes:
            lines = self._wrap(text, kind, size, max_w)
            if len(lines) <= max_lines:
                return lines, size
        return lines[:max_lines], sizes[-1]

    # ------------------------------------------
    # PRIMITIVES
    # ------------------------------------------
    def _panel(self, x, y, w, h, radius=20, fill=(255, 255, 255, 17), border=(255, 255, 255, 38)):
        if w <= 0 or h <= 0:
            return
        self.screen.blit(self._alpha_rect(w, h, fill, radius), (x, y))
        if border:
            key = ("pb", w, h, border, radius)
            s = self._surf_cache.get(key)
            if s is None:
                s = pygame.Surface((w, h), pygame.SRCALPHA)
                pygame.draw.rect(s, border, (0, 0, w, h), width=2, border_radius=radius)
                self._surf_cache[key] = s
            self.screen.blit(s, (x, y))

    def _panel_title(self, x, y, w, label, value=None):
        self._text("black", 22, label, DIM, (x + 24, y + 22))
        if value is not None:
            self._text("display", 38, str(value), INK, (x + w - 24, y + 12), anchor="topright")

    def _shape(self, idx, cx, cy, r, color):
        if idx == 0:
            pygame.draw.polygon(self.screen, color, [(cx, cy - r), (cx + r, cy + r * 0.8), (cx - r, cy + r * 0.8)])
        elif idx == 1:
            pygame.draw.polygon(self.screen, color, [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])
        elif idx == 2:
            pygame.draw.circle(self.screen, color, (cx, cy), int(r * 0.85))
        else:
            q = int(r * 0.78)
            pygame.draw.rect(self.screen, color, (cx - q, cy - q, 2 * q, 2 * q), border_radius=3)

    def _ring(self, cx, cy, radius, width, frac, color):
        pygame.draw.circle(self.screen, TRACK, (cx, cy), radius, width)
        if frac <= 0:
            return
        start = -math.pi / 2
        end = start + 2 * math.pi * frac
        steps = max(4, int(90 * frac))
        outer, inner = [], []
        for i in range(steps + 1):
            a = start + (end - start) * i / steps
            outer.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
            inner.append((cx + math.cos(a) * (radius - width), cy + math.sin(a) * (radius - width)))
        pygame.draw.polygon(self.screen, color, outer + inner[::-1])
        for (ox, oy), (ix, iy) in ((outer[0], inner[0]), (outer[-1], inner[-1])):
            pygame.draw.circle(self.screen, color, (int((ox + ix) / 2), int((oy + iy) / 2)), width // 2)

    def _avatar(self, name, cx, cy, r, ring_color):
        pygame.draw.circle(self.screen, (30, 36, 110), (cx, cy), r)
        pygame.draw.circle(self.screen, ring_color, (cx, cy), r, 5)
        initial = (name.lstrip("@") or "?")[0].upper()
        self._blit(self._render_name(initial, int(r * 1.0), INK, kind="black"), (cx, cy), "center")

    def _crown(self, cx, cy, s, color):
        pts = [(cx - s, cy + s * 0.5), (cx - s, cy - s * 0.4), (cx - s * 0.5, cy + s * 0.05),
               (cx, cy - s * 0.7), (cx + s * 0.5, cy + s * 0.05), (cx + s, cy - s * 0.4), (cx + s, cy + s * 0.5)]
        pygame.draw.polygon(self.screen, color, pts)

    def burst(self, x, y, n=90, power=1.0):
        for _ in range(n):
            if len(self.confetti) < 320:
                self.confetti.append(Confetti(x, y, power))

    # ------------------------------------------
    # FRAME
    # ------------------------------------------
    def draw(self, logic, status: dict):
        now = time.time()
        dt = min(0.1, now - self._t)
        self._t = now
        state = logic.state
        if state != self._last_state:
            self._last_state = state
            self._state_enter = now
            self._burst_done = set()
            if state == GameState.LOBBY:
                self._vote_bars = {}
        age = now - self._state_enter

        self._draw_stage(now, dt)
        if state == GameState.INTRO:
            self._draw_intro(logic, age)
        else:
            self._draw_header(logic, status, now)
            if state == GameState.LOBBY:
                self._draw_lobby(logic, age, dt)
            elif state in (GameState.ASKING, GameState.LOCKING):
                self._draw_question(logic, age, now)
                self._draw_rail_live(logic, now)
                self._draw_toast(logic, now)
            elif state == GameState.REVEALING:
                self._draw_reveal(logic, age)
            elif state == GameState.PODIUM:
                self._draw_podium(logic, age)
            else:
                self._text("display", 90, "THE LIFELONG QUIZ", ACCENT, (SCREEN_WIDTH // 2, 470), "center")
            self._draw_footer(logic, now)
        self._draw_confetti(dt)
        pygame.display.flip()

    def _draw_stage(self, now, dt):
        self.screen.blit(self._bg, (0, 0))
        for i, (bx, by, sp) in enumerate(((0.28, 0.12, 0.13), (0.72, 0.18, 0.11))):
            x = SCREEN_WIDTH * bx + math.sin(now * sp + i * 2.1) * 260
            y = SCREEN_HEIGHT * by + math.cos(now * sp * 0.8 + i) * 80
            self.screen.blit(self._spot, (x - 410, y - 410), special_flags=pygame.BLEND_RGB_ADD)
        for d in self.dust:
            d.y -= d.vy * dt
            if d.y < -10:
                d.__init__(anywhere=False)
            a = int(d.a * (0.6 + 0.4 * math.sin(now * 2 + d.tw)))
            self.screen.blit(self._alpha_rect(d.r * 2, d.r * 2, (255, 255, 255, a // 8 * 8), d.r), (d.x, d.y))

    # ------------------------------------------
    # HEADER / FOOTER
    # ------------------------------------------
    def _draw_header(self, logic, status, now):
        cy = HEADER_Y + HEADER_H // 2
        r = self._text("display", 40, "THE LIFELONG QUIZ", ACCENT, (MAIN_X, cy), "midleft")
        x = r.right + 36
        in_match = logic.state not in (GameState.LOBBY, GameState.WAITING)
        label = f"MATCH {logic.match_no}" + ("" if in_match else "  -  LOBBY")
        r = self._text("black", 24, label, INK, (x, cy), "midleft")
        if in_match:
            x = r.right + 18
            for i in range(MATCH_LENGTH):
                live_pip = i == logic.q_index - 1 and logic.state in (GameState.ASKING, GameState.LOCKING)
                if i < len(logic.pips):
                    col = GOOD if logic.pips[i] == "done" else BAD
                elif live_pip:
                    col = ACCENT
                else:
                    col = TRACK
                pygame.draw.rect(self.screen, col, (x, cy - 7, 34, 14), border_radius=7)
                if live_pip:
                    pulse = 0.5 + 0.5 * math.sin(now * 6)
                    pygame.draw.rect(self.screen, mix(TRACK, ACCENT, pulse), (x - 4, cy - 11, 42, 22), width=2, border_radius=11)
                elif i == MATCH_LENGTH - 1:
                    pygame.draw.rect(self.screen, ACCENT, (x - 4, cy - 11, 42, 22), width=1, border_radius=11)
                x += 42
            if logic.state != GameState.PODIUM and logic.q_index:
                self._text("black", 24, f"Q {logic.q_index}/{MATCH_LENGTH}", INK, (x + 8, cy), "midleft")

        # Live pill: players now, pulsing red dot while broadcasting, warning if chat is down
        txt = self._render("black", 24, f"{logic.active_player_count} playing", INK)
        extra = None if status.get("connected") else self._render("bold", 18, "chat offline", BAD)
        w = 70 + txt.get_width() + (extra.get_width() + 18 if extra else 0)
        px = SCREEN_WIDTH - PAD - w
        self._panel(px, cy - 26, w, 52, radius=26)
        live = status.get("broadcasting")
        pr = 7 + (2 * math.sin(now * 4) if live else 0)
        pygame.draw.circle(self.screen, BAD if live else FAINT, (px + 30, cy), int(pr))
        self._blit(txt, (px + 50, cy), "midleft")
        if extra:
            self._blit(extra, (px + 50 + txt.get_width() + 18, cy), "midleft")

    def _draw_footer(self, logic, now):
        cy = FOOTER_Y + 32
        cmds = [("1-4", "answer"), ("!rank", "your place"), ("!ready", "join next match")]
        x = SCREEN_WIDTH - PAD
        for key, label in reversed(cmds):
            lab = self._render("bold", 22, label, DIM)
            x -= lab.get_width()
            self._blit(lab, (x, cy), "midleft")
            k = self._render("black", 22, key, INK)
            x -= k.get_width() + 30
            self._panel(x - 2, cy - 18, k.get_width() + 22, 36, radius=8)
            self._blit(k, (x + 9, cy), "midleft")
            x -= 34
        right_edge = x - 30

        # AI host caption: typewriter with "voice" bars while it is speaking
        line = logic.host_line
        if not line:
            return
        shown = int((now - logic.host_line_time) * 55)
        pygame.draw.circle(self.screen, ACCENT, (MAIN_X + 26, cy), 26)
        self._text("display", 22, "AI", DARK_INK, (MAIN_X + 26, cy), "center")
        if shown < len(line):
            for i in range(3):
                hgt = 6 + 10 * abs(math.sin(now * 12 + i))
                pygame.draw.rect(self.screen, ACCENT, (MAIN_X + 60 + i * 8, cy - hgt / 2, 4, hgt), border_radius=2)
        text = line[:max(0, shown)]
        if text:
            tx = MAIN_X + 96
            surf = self._render("semi", 26, text, INK)
            while surf.get_width() > right_edge - tx and len(text) > 10:
                text = "..." + text[max(4, len(text) // 10):]
                surf = self._render("semi", 26, text, INK)
            self._blit(surf, (tx, cy), "midleft")

    def _draw_toast(self, logic, now):
        events = [e for e in logic.get_recent_events() if now - e.timestamp < 3.5]
        if not events:
            return
        e = events[-1]
        a = now - e.timestamp
        slide = ease_out_back(a / 0.35)
        fade = 1 - progress(a, 3.0, 0.5)
        txt = self._render_name(e.text, 24, DARK_INK, kind="black")
        w = txt.get_width() + 48
        x = MAIN_X + MAIN_W // 2 - w // 2
        y = int(lerp(BODY_BOTTOM + 10, BODY_BOTTOM - 40, slide))
        self.screen.blit(self._alpha_rect(w, 44, (*e.color[:3], int(235 * fade) // 16 * 16), 22), (x, y))
        self._blit(txt, (x + w // 2, y + 22), "center", alpha=255 * fade)

    # ------------------------------------------
    # INTRO STING
    # ------------------------------------------
    def _draw_intro(self, logic, age):
        cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        sweep = progress(age, 0.1, 1.1)
        self.screen.blit(self._shine, (lerp(-300, SCREEN_WIDTH + 40, ease_in_out(sweep)), 0))
        self._text("display", 150, f"MATCH {logic.match_no}", INK, (cx, cy - 150), "center",
                   alpha=255 * ease_out_cubic(age / 0.3), scale=lerp(2.4, 1.0, ease_out_back(age / 0.6)))
        cat = ease_out_cubic(progress(age, 0.45, 0.4))
        self._blit(self._render_name(logic.match_category.upper(), 44, ACCENT, kind="black"),
                   (cx, cy - 30 + (1 - cat) * 30), "center", alpha=255 * cat)
        self._text("bold", 30, f"{MATCH_LENGTH} QUESTIONS  -  TYPE 1-4 IN CHAT TO PLAY", DIM,
                   (cx, cy + 22), "center", alpha=255 * progress(age, 0.7, 0.4))
        for i, n in enumerate(("3", "2", "1")):
            t0 = 1.0 + i
            if t0 <= age < t0 + 1.0:
                p = age - t0
                self._text("display", 220, n, ACCENT, (cx, cy + 230), "center",
                           alpha=255 * (1 - progress(p, 0.6, 0.4)), scale=lerp(1.7, 1.0, ease_out_back(p / 0.35)))

    # ------------------------------------------
    # LOBBY
    # ------------------------------------------
    def _draw_lobby(self, logic, age, dt):
        rem = logic.time_remaining
        secs = int(math.ceil(rem))
        pop = 1.0 + 0.08 * ease_out_cubic(rem - math.floor(rem)) if secs <= 10 else 1.0
        y = BODY_Y
        self._text("black", 30, "NEXT MATCH STARTS IN", DIM, (MAIN_X, y + 8))
        self._text("display", 170, f"0:{secs:02d}", ACCENT if secs > 5 else BAD, (MAIN_X, y + 40), scale=pop)
        self._text("black", 34, "VOTE THE CATEGORY: TYPE 1-4", INK, (MAIN_X + 470, y + 110))
        self._text("bold", 24, f"Match {logic.match_no}  -  {MATCH_LENGTH} questions  -  podium for the top 3",
                   DIM, (MAIN_X + 470, y + 160))

        vs = logic.vote_state
        if vs:
            counts = vs.vote_counts()
            total = max(1, vs.total_votes())
            lead = vs.leading_option()
            cw, ch, g = (MAIN_W - 24) // 2, 170, 24
            top = y + 260
            for opt, (_, name) in vs.options.items():
                i = opt - 1
                x = MAIN_X + (i % 2) * (cw + g)
                p = ease_out_back(progress(age, 0.15 + i * 0.08, 0.45))
                if p <= 0:
                    continue
                yy = top + (i // 2) * (ch + g) + int((1 - p) * 40)
                is_lead = opt == lead and vs.total_votes() > 0
                self._panel(x, yy, cw, ch, radius=20, border=(*ACCENT, 255) if is_lead else (255, 255, 255, 38))
                col = OPTION_COLORS[i]
                pygame.draw.circle(self.screen, col, (x + 62, yy + 62), 36)
                self._text("display", 42, str(opt), INK, (x + 62, yy + 62), "center")
                self._text("black", 40, name, INK, (x + 116, yy + 62), "midleft")
                target = counts.get(opt, 0) / total
                cur = self._vote_bars.get(opt, 0.0)
                cur += (target - cur) * min(1.0, dt * 6)
                self._vote_bars[opt] = cur
                bx, by, bw = x + 28, yy + 122, cw - 170
                pygame.draw.rect(self.screen, TRACK, (bx, by, bw, 18), border_radius=9)
                if cur > 0.005:
                    pygame.draw.rect(self.screen, ACCENT if is_lead else col, (bx, by, max(18, int(bw * cur)), 18), border_radius=9)
                n = counts.get(opt, 0)
                self._text("bold", 22, f"{n} vote{'s' if n != 1 else ''}", DIM, (bx + bw + 16, by + 9), "midleft")

        # Rail: newcomer card, ready list, this week's ladder
        x, y = RAIL_X, BODY_Y
        self.screen.blit(self._alpha_rect(RAIL_W, 190, (*ACCENT, 255), 20), (x, y))
        self._text("black", 22, "NEW HERE?", DARK_INK, (x + 24, y + 20))
        for i, line in enumerate(("Type a number 1-4 in chat when", "the question shows. That's it!",
                                  "Your name appears the moment", "you answer.")):
            self._text("bold", 25, line, DARK_INK, (x + 24, y + 58 + i * 30))
        y += 210
        ready = logic.ready_players
        h = 210
        self._panel(x, y, RAIL_W, h)
        self._panel_title(x, y, RAIL_W, "READY FOR THIS MATCH", len(ready))
        cx, cy = x + 24, y + 70
        for name in ready[-12:]:
            chip = self._fit_name(name, 22, INK, 180)
            w = chip.get_width() + 24
            if cx + w > x + RAIL_W - 20:
                cx, cy = x + 24, cy + 42
                if cy > y + h - 40:
                    break
            self._panel(cx, cy, w, 34, radius=17, fill=(255, 255, 255, 28), border=None)
            self._blit(chip, (cx + 12, cy + 17), "midleft")
            cx += w + 8
        if not ready:
            self._text("bold", 22, "Type !ready or vote to check in", FAINT, (x + 24, y + 80))
        y += h + 20
        self._draw_ladder(logic, x, y, BODY_BOTTOM - y, rows=6, age=age, title="THIS WEEK")

    # ------------------------------------------
    # QUESTION (ASKING / LOCKING)
    # ------------------------------------------
    def _question_block(self, logic, q, age, small=False):
        y = BODY_Y
        x = MAIN_X
        cat = self._render_name(q.category.upper(), 22, INK, kind="black")
        w = cat.get_width() + 36
        self._panel(x, y, w, 44, radius=22)
        self._blit(cat, (x + 18, y + 22), "midleft")
        x += w + 14
        dcol = DIFF_COLORS.get(q.difficulty, DIM)
        d = self._render("black", 22, q.difficulty.upper(), dcol)
        w = d.get_width() + 36
        self._panel(x, y, w, 44, radius=22, border=(*dcol, 255))
        self._blit(d, (x + 18, y + 22), "midleft")
        x += w + 14
        ev = "final" if logic.is_double_points else logic.mini_event
        if ev in EVENT_STYLE:
            label, col = EVENT_STYLE[ev]
            pulse = 0.75 + 0.25 * math.sin(time.time() * 5)
            e = self._render("black", 22, label, DARK_INK)
            w = e.get_width() + 36
            self.screen.blit(self._alpha_rect(w, 44, (*col, int(255 * pulse) // 16 * 16), 22), (x, y))
            self._blit(e, (x + 18, y + 22), "midleft")

        text_w = MAIN_W - (0 if small else 210)
        sizes = (50, 44, 38) if small else (66, 58, 50, 44)
        lines, size = self._fit_wrap(q.text.upper(), "display", sizes, text_w, 3)
        ty = y + 70
        lh = int(size * 1.12)
        for i, line in enumerate(lines):
            p = 1.0 if small else ease_out_cubic(progress(age, 0.05 + i * 0.08, 0.4))
            self._blit(self._render_name(line, size, DIM if small else INK, kind="display"),
                       (MAIN_X, ty + i * lh + (1 - p) * 26), alpha=255 * p)
        return ty + len(lines) * lh

    def _option_rects(self, top, max_h=190):
        g = 24
        w = (MAIN_W - g) // 2
        h = min(max_h, (BODY_BOTTOM - top - g) // 2)
        return [(MAIN_X + (i % 2) * (w + g), top + (i // 2) * (h + g), w, h) for i in range(4)]

    def _draw_option(self, i, text, rect, alpha=255, scale=1.0, dim=0.0, outline=None, lift=0):
        x, y, w, h = rect
        if scale != 1.0:
            cx, cy = x + w / 2, y + h / 2
            w, h = int(w * scale), int(h * scale)
            x, y = int(cx - w / 2), int(cy - h / 2)
        y -= lift
        a = int(alpha) // 8 * 8
        col = mix(OPTION_COLORS[i], (40, 44, 90), dim)
        self.screen.blit(self._alpha_rect(w, h, (0, 0, 0, int(90 * a / 255)), 22), (x, y + 10))
        if outline:
            self.screen.blit(self._alpha_rect(w + 24, h + 24, (*outline, 70), 32), (x - 12, y - 12))
        self.screen.blit(self._alpha_rect(w, h, (*col, a), 22), (x, y))
        if outline:
            pygame.draw.rect(self.screen, outline, (x - 4, y - 4, w + 8, h + 8), width=6, border_radius=26)
        r = int(min(39, h * 0.22))
        kx, ky = x + 34 + r, y + h // 2
        knob = mix(INK, (150, 150, 170), dim)
        pygame.draw.circle(self.screen, knob, (kx, ky), r)
        self._text("display", int(r * 1.15), str(i + 1), DARK_INK, (kx, ky), "center", alpha=a)
        self._shape(i, kx + r + 34, ky, 15, knob)
        tx = kx + r + 66
        lines, size = self._fit_wrap(text, "black", (46, 40, 34, 30), x + w - tx - 110, 2)
        lh = int(size * 1.1)
        for j, line in enumerate(lines):
            self._blit(self._render_name(line, size, mix(INK, (190, 190, 210), dim), kind="black"),
                       (tx, ky - len(lines) * lh / 2 + j * lh + lh / 2), "midleft", alpha=a)
        return (x, y, w, h)

    def _draw_question(self, logic, age, now):
        q = logic.current_question
        if not q:
            return
        locking = logic.state == GameState.LOCKING
        q_age = now - logic.question_start_time
        bottom = self._question_block(logic, q, q_age)

        tcx, tcy = MAIN_X + MAIN_W - 82, BODY_Y + 70 + 82
        if not locking:
            rem = logic.time_remaining
            urgent = rem <= 5
            pulse = 1.0 + (0.06 * math.sin(now * 10) if urgent else 0)
            self._ring(tcx, tcy, int(80 * pulse), 14, logic.time_fraction, BAD if urgent else ACCENT)
            self._text("display", 70, str(int(math.ceil(rem))), INK, (tcx, tcy), "center")
            if urgent:  # red glow on the screen edges for the last 5 seconds
                glow = self._alpha_rect(SCREEN_WIDTH, 18, (*BAD, int(60 + 50 * math.sin(now * 10)) // 8 * 8), 0)
                self.screen.blit(glow, (0, 0))
                self.screen.blit(glow, (0, SCREEN_HEIGHT - 18))
        else:  # suspense: stamp slams in while late chat answers still count
            p = ease_out_back(age / 0.35)
            stamp = self._render("display", 46, "TIME'S UP", INK)
            sw, sh = stamp.get_width() + 40, stamp.get_height() + 16
            base = pygame.Surface((sw, sh), pygame.SRCALPHA)
            pygame.draw.rect(base, BAD, (0, 0, sw, sh), border_radius=14)
            base.blit(stamp, (20, 8))
            rot = pygame.transform.rotozoom(base, 8, max(0.05, lerp(2.0, 1.0, p)))
            self.screen.blit(rot, rot.get_rect(center=(tcx - 20, tcy)))

        top = max(bottom + 30, BODY_Y + 330)
        for i, (opt, rect) in enumerate(zip(q.options, self._option_rects(top))):
            p = ease_out_back(progress(q_age, 0.25 + i * 0.07, 0.45))
            if p <= 0:
                continue
            self._draw_option(i, opt, rect, alpha=255 * clamp01(p * 1.4), scale=lerp(0.85, 1.0, p),
                              dim=0.35 if locking else 0.0)

    def _draw_rail_live(self, logic, now):
        x, y = RAIL_X, BODY_Y
        h = 470
        self._panel(x, y, RAIL_W, h)
        self._panel_title(x, y, RAIL_W, "LOCKED IN", logic.answer_count)
        rows = list(reversed(logic.lock_order))[:9]
        for i, (name, at) in enumerate(rows):
            ry = y + 80 + i * 43
            p = ease_out_cubic((now - (logic.question_start_time + at)) / 0.4)
            ox = (1 - p) * 60
            bot = is_bot(name)
            n = self._fit_name(name.replace("[Bot] ", ""), 26, FAINT if bot else INK, RAIL_W - 170)
            self._blit(n, (x + 24 + ox, ry), "midleft", alpha=255 * p)
            if bot:
                self._text("black", 15, "BOT", FAINT, (x + 34 + n.get_width() + ox, ry), "midleft", alpha=200 * p)
            self._text("bold", 20, f"{at:.1f}s", DIM, (x + RAIL_W - 24, ry), "midright", alpha=255 * p)
        if not rows:
            self._text("bold", 24, "Be the first: type 1-4!", FAINT, (x + 24, y + 80))
        y += h + 20
        self._draw_match_table(logic, x, y, BODY_BOTTOM - y)

    def _draw_match_table(self, logic, x, y, h):
        self._panel(x, y, RAIL_W, h)
        self._panel_title(x, y, RAIL_W, f"MATCH {logic.match_no} STANDINGS")
        ranked = logic.match_ranking(n=max(1, (h - 70) // 42))
        for i, st in enumerate(ranked):
            ry = y + 80 + i * 42
            bot = is_bot(st.username)
            col = FAINT if bot else (ACCENT if i == 0 else INK)
            self._text("display", 26, str(i + 1), col, (x + 24, ry), "midleft")
            self._blit(self._fit_name(st.username.replace("[Bot] ", ""), 25, col, RAIL_W - 200), (x + 60, ry), "midleft")
            self._text("black", 25, f"{st.points:,}", col, (x + RAIL_W - 24, ry), "midright")
        if not ranked:
            self._text("bold", 22, "Points appear after the first reveal", FAINT, (x + 24, y + 80))

    # ------------------------------------------
    # REVEAL
    # ------------------------------------------
    def _draw_reveal(self, logic, age):
        res = logic.last_result
        if not res or not res.question.options:
            return
        q = res.question
        bottom = self._question_block(logic, q, 10.0, small=True)
        top = max(bottom + 26, BODY_Y + 230)
        rects = self._option_rects(top, max_h=160)
        total = max(1, res.total_answers)
        reveal = age >= 1.1
        k = ease_out_cubic(progress(age, 1.1, 0.4))
        for i, (opt, rect) in enumerate(zip(q.options, rects)):
            correct = i == q.correct_index
            x, y, w, h = self._draw_option(
                i, opt, rect,
                dim=(0.55 * k if reveal and not correct else 0.0),
                outline=INK if reveal and correct else None,
                lift=int(8 * k) if reveal and correct else 0,
            )
            # HQ-style answer split: a bar grows along the button while the percentage counts up
            target = res.option_counts[i] / total if i < len(res.option_counts) else 0
            shown = target * ease_out_cubic(progress(age, 0.25, 0.9))
            bw = int(w * shown)
            if bw > 14:
                self.screen.blit(self._alpha_rect(bw, 14, (0, 0, 0, 110), 7), (x, y + h - 14))
            self._text("display", 50, f"{int(round(shown * 100))}%", INK, (x + w - 28, y + h // 2), "midright")
            if reveal and correct:
                tag = self._render("black", 18, "CORRECT", DARK_INK)
                self.screen.blit(self._alpha_rect(tag.get_width() + 24, 30, (*INK, 255), 15), (x + w - tag.get_width() - 44, y + 12))
                self._blit(tag, (x + w - 32, y + 27), "midright")
                if "burst" not in self._burst_done and res.correct_players:
                    self._burst_done.add("burst")
                    self.burst(x + w // 2, y + h // 2, n=70, power=0.8)

        p = ease_out_cubic(progress(age, 1.5, 0.4))
        sy = rects[2][1] + rects[2][3] + 24 + int((1 - p) * 30)
        if sy + 66 <= BODY_BOTTOM + 30:
            self._panel(MAIN_X, sy, MAIN_W, 66, radius=18)
            knew = int(round(res.correct_rate * 100))
            self._text("display", 38, f"{knew}% KNEW IT", GOOD if knew >= 50 else ACCENT, (MAIN_X + 26, sy + 33), "midleft", alpha=255 * p)
            self._blit(self._fit_name(f"The answer: {q.correct_answer}", 28, INK, MAIN_W - 380, kind="semi"),
                       (MAIN_X + 330, sy + 33), "midleft", alpha=255 * p)

        x, y = RAIL_X, BODY_Y
        h = 230
        self._panel(x, y, RAIL_W, h)
        self._panel_title(x, y, RAIL_W, "FASTEST RIGHT")
        for i, (name, pts, t) in enumerate(res.correct_players[:3]):
            ry = y + 84 + i * 46
            pp = ease_out_back(progress(age, 1.3 + i * 0.15, 0.35))
            if pp <= 0:
                continue
            self._blit(self._fit_name(name.replace("[Bot] ", ""), 27, INK, RAIL_W - 210), (x + 24, ry), "midleft", alpha=255 * clamp01(pp))
            self._text("bold", 20, f"{t:.1f}s", DIM, (x + RAIL_W - 110, ry), "midright")
            self._text("black", 28, f"+{pts}", GOOD, (x + RAIL_W - 24, ry), "midright", scale=lerp(1.6, 1.0, clamp01(pp)))
        if not res.correct_players:
            self._text("bold", 24, "Nobody got this one", FAINT, (x + 24, y + 84))
        y += h + 20
        h2 = 250
        self._panel(x, y, RAIL_W, h2)
        self._panel_title(x, y, RAIL_W, "THIS ROUND")
        events = logic.get_recent_events()[-4:]
        for i, e in enumerate(events):
            self._blit(self._fit_name(e.text, 22, e.color, RAIL_W - 48, kind="semi"), (x + 24, y + 84 + i * 40), "midleft")
        if not events:
            self._text("bold", 22, f"{res.total_answers} answers this round", FAINT, (x + 24, y + 84))
        y += h2 + 20
        self._draw_match_table(logic, x, y, BODY_BOTTOM - y)

    # ------------------------------------------
    # PODIUM
    # ------------------------------------------
    def _draw_podium(self, logic, age):
        self._text("display", 84, f"MATCH {logic.match_no} WINNERS", INK, (MAIN_X, BODY_Y - 6), alpha=255 * ease_out_cubic(age / 0.4))
        self._blit(self._render_name(f"{MATCH_LENGTH} QUESTIONS  -  {logic.match_player_count} PLAYERS  -  "
                                     f"{logic.match_category.upper()}", 26, DIM, kind="black"), (MAIN_X, BODY_Y + 92))
        base_y = BODY_BOTTOM - 110
        bw, g = 340, 40
        x0 = MAIN_X + (MAIN_W - 3 * bw - 2 * g) // 2
        slots = [(1, x0, 210, 0.9), (0, x0 + bw + g, 270, 1.6), (2, x0 + 2 * (bw + g), 160, 0.3)]
        if not logic.podium:
            self._text("display", 60, "NO WINNER THIS TIME", DIM, (MAIN_X + MAIN_W // 2, base_y - 170), "center")
            self._text("bold", 30, "Type 1-4 next match and the podium is yours", INK, (MAIN_X + MAIN_W // 2, base_y - 100), "center")
        for place, x, height, delay in slots:
            if place >= len(logic.podium):
                continue
            st = logic.podium[place]
            p = ease_out_back(progress(age, delay, 0.6))
            hh = int(height * max(0.0, p))
            top = base_y - hh
            if hh > 0:
                col = ACCENT if place == 0 else (70, 78, 170)
                pygame.draw.rect(self.screen, col, (x, top, bw, hh + 4), border_top_left_radius=22, border_top_right_radius=22)
                self._text("display", 90, str(place + 1), DARK_INK if place == 0 else INK, (x + bw // 2, top + 16), "midtop")
            np_ = ease_out_back(progress(age, delay + 0.45, 0.45))
            if np_ > 0:
                r = 62 if place == 0 else 52
                ay = int(top - 100 - r - (1 - np_) * 40)
                self._avatar(st.username, x + bw // 2, ay, r, ACCENT if place == 0 else DIM)
                if place == 0:
                    self._crown(x + bw // 2, ay - r - 24, 32, ACCENT)
                self._blit(self._fit_name(st.username, 32, INK, bw + 30, kind="black"), (x + bw // 2, ay + r + 26), "center", alpha=255 * clamp01(np_))
                self._text("bold", 24, f"{st.points:,} pts  -  {st.correct}/{MATCH_LENGTH}", DIM, (x + bw // 2, ay + r + 60), "center", alpha=255 * clamp01(np_))
            if place == 0 and age >= delay + 0.5 and "podium" not in self._burst_done:
                self._burst_done.add("podium")
                self.burst(x + bw // 2, top, n=160, power=1.3)
                self.burst(MAIN_X + 100, base_y, n=60, power=1.1)
                self.burst(MAIN_X + MAIN_W - 100, base_y, n=60, power=1.1)
        pygame.draw.rect(self.screen, TRACK, (MAIN_X + 20, base_y, MAIN_W - 40, 6), border_radius=3)

        stats = logic.match_stats or {}
        cards = []
        if stats.get("fastest"):
            n, t = stats["fastest"]
            cards.append(("FASTEST ANSWER", f"{t:.1f}s  {n}"))
        if stats.get("best_streak"):
            n, s = stats["best_streak"]
            cards.append(("BEST STREAK", f"{s} in a row  {n}"))
        cards.append(("PLAYERS", str(logic.match_player_count)))
        cw = (MAIN_W - 40) // 3
        sp = ease_out_cubic(progress(age, 2.2, 0.4))
        for i, (label, value) in enumerate(cards[:3]):
            cx = MAIN_X + i * (cw + 20)
            cy = BODY_BOTTOM - 84 + int((1 - sp) * 30)
            self._panel(cx, cy, cw, 84, radius=18)
            self._text("black", 18, label, DIM, (cx + 22, cy + 12), alpha=255 * sp)
            self._blit(self._fit_name(value, 32, INK, cw - 44, kind="black"), (cx + 22, cy + 56), "midleft", alpha=255 * sp)

        x, y = RAIL_X, BODY_Y
        h = 560
        self._draw_ladder(logic, x, y, h, rows=10, age=age, title="THIS WEEK'S LADDER", movement=True)
        y += h + 20
        self._panel(x, y, RAIL_W, BODY_BOTTOM - y)
        self._panel_title(x, y, RAIL_W, "LIFETIME LEVELS")
        for i, p in enumerate(logic.db.get_top_players(n=max(1, (BODY_BOTTOM - y - 70) // 42))):
            ry = y + 82 + i * 42
            self._blit(self._fit_name(p.username, 25, INK, RAIL_W - 230), (x + 24, ry), "midleft")
            self._text("black", 22, f"LV {p.level}", ACCENT, (x + RAIL_W - 130, ry), "midright")
            self._text("bold", 22, p.rank, DIM, (x + RAIL_W - 24, ry), "midright")

    def _draw_ladder(self, logic, x, y, h, rows, age, title, movement=False):
        self._panel(x, y, RAIL_W, h)
        self._panel_title(x, y, RAIL_W, title)
        players = logic.leaderboard[:min(rows, max(1, (h - 70) // 44))]
        for i, p in enumerate(players):
            ry = y + 82 + i * 44
            pp = ease_out_cubic(progress(age, 0.3 + i * 0.07, 0.35))
            ox = (1 - pp) * 50
            if movement:
                ch = logic.ladder_changes.get(p.username, 0)
                mv, mc = ("NEW", GOOD) if ch is None else (f"+{ch}", GOOD) if ch > 0 else (str(ch), BAD) if ch < 0 else ("-", FAINT)
                self._text("black", 18, mv, mc, (x + 44 + ox, ry), "center", alpha=255 * pp)
                nx = x + 78
            else:
                self._text("display", 26, str(i + 1), ACCENT if i == 0 else DIM, (x + 30 + ox, ry), "center", alpha=255 * pp)
                nx = x + 60
            self._blit(self._fit_name(p.username, 25, INK, RAIL_W - 210), (nx + ox, ry), "midleft", alpha=255 * pp)
            self._text("black", 25, f"{p.weekly_score:,}", INK, (x + RAIL_W - 24 + ox, ry), "midright", alpha=255 * pp)
        if not players:
            self._text("bold", 22, "Empty so far: answer to get on it!", FAINT, (x + 24, y + 82))

    # ------------------------------------------
    # CONFETTI
    # ------------------------------------------
    def _draw_confetti(self, dt):
        alive = []
        for c in self.confetti:
            c.life -= dt
            if c.life <= 0 or c.y > SCREEN_HEIGHT + 30:
                continue
            c.vy += 22 * dt
            c.vx *= 0.985
            c.x += c.vx * dt * 60
            c.y += c.vy * dt * 30
            c.phase += c.spin * dt
            hh = max(2, int(abs(math.sin(c.phase)) * c.h))
            pygame.draw.rect(self.screen, c.color, (int(c.x), int(c.y), c.w, hh), border_radius=2)
            alive.append(c)
        self.confetti = alive
