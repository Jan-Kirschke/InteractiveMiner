"""
The Lifelong Quiz - vertical (9:16) show for YouTube Shorts and phones
A TV game-show motion package composed for a phone held upright: one column, big type, four
full-width answer buttons. Everything that matters sits between y=190 and y=1500, clear of the
Shorts overlays (top bar; title, chat and buttons at the bottom).

The system:
    stage    pre-rendered radial stage with two light shafts (the logo's), bokeh drifting at
             three depths (parallax), sparkle motes; nothing full-screen is drawn per frame
    brand    the Spotlight LQ ring is the clock: the lobby countdown, the intro's 3-2-1 and
             the question timer all drain the logo's four answer-colour arcs
    type     Anton for headlines and numbers, Barlow ExtraBold for answers and labels; sizes
             come from TYPE, never ad hoc
    motion   quiz/motion.py only: entrances out-expo, physical things out-back or spring,
             cascades staggered by STAGGER; every surface is cached (per question in _qc)

Choreography per state (seconds from the state change):
    LOBBY      ring countdown draws on, vote cards cascade in, bars tween, leader glows
    INTRO      MATCH N letters rise, the ring draws on around LQ, then counts 3-2-1 and the
               camera pushes through it into question 1
    ASKING     chips slide in, the question rises line by line out of a mask, the ring charges
               up, answers cascade in with a glint; last 5 s: the ring turns red and beats
    LOCKING    the ring collapses, a TIME'S UP band slams across with a camera shake, shutters
               close over the answers while late answers still lock in
    REVEALING  answers glide from their question layout into the results layout, the answer
               split fills and counts up; at REVEAL_AT the wrong ones dim and step back, the
               right one flares (flash, glow, ring burst, light sweep); points fly to the fastest
               players, then the match standings re-order with rank arrows. After question 5 a
               HALFTIME card takes over the reveal's tail.
    PODIUM     camera push-in, spotlights switch on 3rd, 2nd, then 1st with a sunburst, crown
               and confetti; the weekly ladder slides in under the floor
"""

import math
import random
import time

import pygame
import pygame.gfxdraw

from quiz import gfx
from quiz.config import (SCREEN_WIDTH as W, SCREEN_HEIGHT as H, MATCH_LENGTH, REVEAL_AT, REVEAL_DISPLAY_TIME,
                         LIGHTNING_QUESTION, BONUS_QUESTIONS, COMBO_STEPS, JACKPOT_BONUS, SURVIVOR_POT,
                         TEAM_WIN_BONUS)
from quiz.logic import is_bot
from quiz.models import GameState
from quiz.special import FORMATS, TEAMS
from quiz.motion import (STAGGER, clamp01, heartbeat, in_cubic, in_expo, in_out_cubic, lerp, out_back, out_cubic,
                         out_expo, progress, shake, smoothstep, spring)
from quiz.transitions import BUILDUP, FLAT, LILAC, STYLES, _shape
from quiz.ui import (UIManager, ACCENT, BAD, BG_DEEP, BG_STAGE, DARK_INK, DIFF_COLORS, DIM, EVENT_STYLE, FAINT,
                     GOOD, INK, OPTION_COLORS, ROUND_STYLE, TRACK, mix, reveal_lines, round_style, winners_title)

# ==========================================
# TOKENS
# ==========================================
M = 56                    # side margin
CW = W - 2 * M            # content width
SAFE_TOP, SAFE_BOTTOM = 190, 1500   # Shorts draws its own UI outside this band

# Type scale (px): a perfect-fourth-ish ladder from captions to the hero numbers
TYPE = {"cap": 24, "small": 28, "body": 34, "label": 38, "answer": 56, "head": 64, "q": 88,
        "big": 130, "hero": 190}

GAP = 18                  # between answer buttons
R_BTN = 28                # answer button corner radius
CHIPS_Y = 262             # chip row (both layouts of a question, so it never jumps)
Q_Y = 340                 # first line of the question
STRIP = 100               # "N LOCKED IN" and the newest names, under the answers
NAVY = (16, 19, 64)       # what a dimmed answer sinks towards
SILVER, BRONZE = (206, 214, 240), (222, 146, 84)
PLACE_COLORS = (gfx.GOLD, SILVER, BRONZE)
BOKEH_COLORS = ((120, 150, 255), (150, 130, 255), (200, 210, 255), (90, 200, 240))   # cool: warm discs go muddy on navy

# Reveal timeline (seconds into REVEALING)
T_GLIDE = 0.6             # answers glide from the question layout to the results layout
T_SPLIT = 0.3             # the answer split starts filling
T_HEAD = 1.45             # "62% KNEW IT" and the fact
T_PANEL = 1.85            # fastest players, points fly in
T_STAND = 4.2             # match standings replace them ...
T_REORDER = 4.85          # ... and re-order
T_HALF = 3.9              # halftime card (after question 5) instead of the standings
T_HALF_COVER = STYLES["ribbon"][0]   # the four-colour ribbon has covered the reveal by then

# Event toasts: the badge each icon code gets (a flat glyph; anything else prints its code)
BADGE_GLYPHS = {"ZAP": "bolt", "FAST": "bolt", "UP": "arrow", "ACH": "star", "WIN": "crown", "NEW": "star",
                "DAY": "star", "BACK": "arrow"}
TOAST_LIFE = 3.6
LADDER = ("easy", "medium", "hard")
TIER_INK = {"easy": GOOD, "medium": (255, 166, 60), "hard": BAD, "expert": (190, 140, 255)}
GOAL_INK = (190, 140, 255)   # the community goal: chat's colour (the logic's event purple)
T_FORMAT_CARD = 4.4          # podium: the survivors / team result card, then the ladder ...
T_LADDER_LATE = 8.2          # ... which waits for it


class _Bokeh:
    __slots__ = ("x", "y", "depth", "sprite", "ph")

    def __init__(self, rng, i):
        self.depth = (0.35, 0.6, 1.0)[i % 3]
        r = int(lerp(14, 60, self.depth) * rng.uniform(0.85, 1.2)) // 4 * 4
        self.sprite = gfx.bokeh(r, rng.choice(BOKEH_COLORS), int(lerp(46, 18, self.depth)))
        self.x, self.y = rng.uniform(0, W), rng.uniform(0, H)
        self.ph = rng.uniform(0, 6.28)


def _slot_color(logic, n):
    """Colour of question n's event or special round (the pip row shows the match's shape)."""
    if n == MATCH_LENGTH:
        return ACCENT
    if n == LIGHTNING_QUESTION:
        return EVENT_STYLE["lightning"][1]
    kind = getattr(logic, "special_slots", {}).get(n)
    if kind in ROUND_STYLE:
        return ROUND_STYLE[kind][1]
    if n in BONUS_QUESTIONS:
        return EVENT_STYLE["jackpot"][1]
    return None


class VerticalUI(UIManager):
    def __init__(self, screen):
        super().__init__(screen)
        self._stage = self._v_build_stage()
        rng = random.Random(7)
        self._bokeh = [_Bokeh(rng, i) for i in range(15)]
        self.dust = self.dust[:22]
        self._uc = gfx.SurfCache(64)       # UI surfaces that live across questions (chips, banners, rows)
        self._qcache = gfx.SurfCache(32)   # surfaces of the current question (buttons, its text lines)
        self._rays = None                   # scratch for the podium sunburst
        self._freeze = None                 # the last frame before BUILDUP (its cover closes over it)
        self._stakes = 0                    # logic.question_stakes(), once per question
        self._pre_points = {}    # match points before this question was scored
        self._lock_shown = 0.0   # rolling "N LOCKED IN"
        self._kick = -99.0       # last stage energy kick (bokeh speeds up)
        self._shake = (-99.0, 0.0)

    # ------------------------------------------
    # CACHES AND TEXT
    # ------------------------------------------
    def _qc(self, key, make):
        return gfx.cached(key, make, self._qcache)

    def _ucache(self, key, make):
        return gfx.cached(key, make, self._uc)

    def _stext(self, kind, size, text, color, pos, anchor="topleft", alpha=255, name=False, store=None):
        """Text over a soft drop shadow, anchored by the text itself (not the padding)."""
        core = self._render_name(text, size, color, kind) if name else self._render(kind, size, text, color)
        spread = max(4, size // 12)
        padded = gfx.with_shadow(core, ("st", kind, size, text, color), dy=max(2, size // 16), spread=spread,
                                 alpha=150, store=self._uc if store is None else store)
        r = core.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
        padded.set_alpha(int(max(0, min(255, alpha))))
        self.screen.blit(padded, (r.x - 2 * spread, r.y - 2 * spread))
        padded.set_alpha(255)
        return r

    def _label(self, text, pos, anchor="topleft", alpha=255, color=DIM):
        """Section label: small tracked capitals (one look for every panel title)."""
        return self._blit(gfx.tracked(self.fonts.get("black", TYPE["small"]), text, color, 3), pos, anchor, alpha)

    def _gold(self, size, text):
        return self._ucache(("gold", size, text), lambda: gfx.with_shadow(
            gfx.gold_text(self.fonts.get("display", size), text), ("g", size, text),
            dy=max(3, size // 24), spread=max(4, size // 14), alpha=170))

    def _blit_padded(self, padded, core_size, pos, anchor="center", alpha=255):
        """Blit a with_shadow() surface so its core lands at pos."""
        pad = (padded.get_width() - core_size[0]) // 2
        r = pygame.Rect((0, 0), core_size)
        setattr(r, anchor, (int(pos[0]), int(pos[1])))
        padded.set_alpha(int(max(0, min(255, alpha))))
        self.screen.blit(padded, (r.x - pad, r.y - pad))
        padded.set_alpha(255)
        return r

    def _rise_blit(self, surf, x, top, h, p, alpha=255):
        """surf rising out of the slot [top, top + h] through its baseline (a mask, not a fade)."""
        if p <= 0:
            return
        old = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(0, int(top) - 30, W, int(h) + 60).clip(old))
        surf.set_alpha(int(alpha))
        self.screen.blit(surf, (int(x), int(top + (1 - p) * (h + 30))))
        surf.set_alpha(255)
        self.screen.set_clip(old)

    # ------------------------------------------
    # FRAME
    # ------------------------------------------
    def draw(self, logic, status: dict):
        now = time.time()
        dt = min(0.1, now - self._t)
        self._t = now
        state = logic.state
        if state != self._last_state:
            self._on_enter(logic, state, now)
        age = now - self._state_enter
        self.fx.cue(logic, now)

        # The reveal also sits under the build-up's cover while it closes
        r_age = age if state == GameState.REVEALING else REVEAL_DISPLAY_TIME + age
        if self._halftime_covered(logic, state, r_age):   # the ribbon has covered it: only the card
            self.screen.fill(FLAT)
            self._v_halftime(logic, r_age - T_HALF)
        elif state == BUILDUP:
            # The next question is already served; its options must not show before ASKING. The
            # build-up's cover closes over the last frame of the state before, frozen at entry.
            if not self.fx.covered(now) and self._freeze is not None:
                self.screen.blit(self._freeze, (0, 0))        elif not self.fx.covered(now):   # a cut-away hides everything: skip the frame underneath
            self._v_stage(now, dt)
            if state == GameState.INTRO:
                self._v_intro(logic, age)
            else:
                self._v_header(logic, status, now)
                if state == GameState.LOBBY:
                    self._v_lobby(logic, age, dt, now)
                elif state in (GameState.ASKING, GameState.LOCKING):
                    self._v_question(logic, age, now, dt)
                elif state == GameState.REVEALING:
                    self._v_reveal(logic, r_age, now)
                elif state == GameState.PODIUM:
                    self._v_podium(logic, age, now)
                else:
                    lq = gfx.lq_mark(self.fonts.get("display", 220))
                    self.screen.blit(lq, lq.get_rect(center=(W // 2, 900)))
                self._v_toast(logic, now)
                self._draw_player_card(logic, now)
            t0, amp = self._shake
            if now - t0 < 0.6:
                dx, dy = shake(now - t0, amp)
                self.screen.scroll(int(dx), int(dy))
        self.fx.draw(self.screen, now)
        self._draw_confetti(dt)
        pygame.display.flip()

    def _on_enter(self, logic, state, now):
        self._last_state = state
        self._state_enter = now
        self._burst_done = set()
        if state == GameState.LOBBY:
            self._vote_bars = {}
        elif state == GameState.ASKING:
            self._qcache.clear()
            self._lock_shown = 0.0
            self._pre_points = {u: s.points for u, s in logic.standings.items()}
            try:
                self._stakes = int(logic.question_stakes())
            except (AttributeError, TypeError, ValueError):
                self._stakes = 0
        elif state == GameState.INTRO:
            self._pre_points = {}
        elif state == BUILDUP:
            self._freeze = self.screen.copy()   # see draw(): the cover closes over this frame

    def _halftime_covered(self, logic, state, r_age):
        return (logic.q_index == MATCH_LENGTH // 2 and r_age >= T_HALF + T_HALF_COVER and logic.last_result is not None
                and (state == GameState.REVEALING or (state == BUILDUP and not self.fx.covered(time.time()))))

    def _kick_stage(self, now):
        self._kick = now

    # ------------------------------------------
    # STAGE: radial light, two shafts, bokeh at three depths, motes
    # ------------------------------------------
    def _v_build_stage(self):
        w, h = W // 8, H // 8
        small = pygame.Surface((w, h))
        cx, cy = w * 0.5, h * 0.40
        core = (56, 62, 184)
        for y in range(h):
            for x in range(w):
                d = math.hypot((x - cx) / w, (y - cy) / (h * 0.62))
                small.set_at((x, y), mix(core, BG_STAGE, d / 0.45) if d < 0.45
                             else mix(BG_STAGE, BG_DEEP, (d - 0.45) / 0.6))
        bg = pygame.transform.smoothscale(small, (W, H))
        sw, sh = 640, 1560
        left = gfx.beam(sw, sh, 100, 170, 300, 300, 30)
        right = gfx.beam(sw, sh, sw - 270, 170, sw - 600, 300, 30)
        bg.blit(left, (40, -60), special_flags=pygame.BLEND_RGB_ADD)
        bg.blit(right, (W - 40 - sw, -60), special_flags=pygame.BLEND_RGB_ADD)
        self._v_floor(bg)
        return bg

    FLOOR_Y = 1536   # the studio floor's horizon, just under the safe zone

    def _v_floor(self, bg):
        """A studio floor in the band Shorts overlays (decoration only, baked into the stage):
        a lit horizon with the four answer colours at its centre and perspective lines."""
        y0 = self.FLOOR_Y
        fh = H - y0
        shade = gfx.vgradient(W, fh, [(150, 150, 170), (92, 92, 120), (60, 60, 84)])
        bg.blit(shade, (0, y0), special_flags=pygame.BLEND_RGB_MULT)
        lines = pygame.Surface((W, fh), pygame.SRCALPHA)
        lines.fill((0, 0, 0, 0))
        vx, vy = W / 2, -520                      # vanishing point, far above the horizon
        for k in range(-9, 10):
            xb = vx + k * 150 * (fh - vy) / (0 - vy)
            x0 = vx + k * 150
            pygame.draw.aaline(lines, (150, 160, 255, 34), (x0, 0), (xb, fh))
        for i in range(1, 9):
            y = int(fh * (i / 8) ** 1.8)
            pygame.draw.line(lines, (150, 160, 255, 16 + i * 2), (0, y), (W, y))
        bg.blit(lines, (0, y0))
        haze = pygame.transform.smoothscale(gfx.add_light(300, (44, 48, 120), 1.6), (W + 200, 150))
        bg.blit(haze, (-100, y0 - 75), special_flags=pygame.BLEND_RGB_ADD)
        bg.fill((112, 120, 230), (0, y0, W, 2))
        seg = 120
        x = W // 2 - 2 * seg
        for col in gfx.RING_COLORS:
            bg.fill(col, (x, y0 - 1, seg - 6, 4))
            x += seg

    def _v_stage(self, now, dt):
        self.screen.blit(self._stage, (0, 0))
        energy = 1 + 4 * math.exp(-(now - self._kick) * 1.8)
        for b in self._bokeh:
            b.y -= (6 + 20 * b.depth) * dt * energy
            b.x += math.sin(now * 0.25 + b.ph) * 8 * b.depth * dt
            s = b.sprite
            if b.y < -s.get_height():
                b.y = H + s.get_height()
                b.x = (b.x + 397) % W
            self.screen.blit(s, (int(b.x - s.get_width() / 2), int(b.y - s.get_height() / 2)))
        for d in self.dust:
            d.y -= d.vy * dt * energy
            if d.y < -10:
                d.__init__(anywhere=False)
            a = int(d.a * (0.5 + 0.5 * math.sin(now * 2.4 + d.tw)))
            self.screen.blit(self._alpha_rect(d.r * 2, d.r * 2, (255, 255, 255, a // 8 * 8), d.r), (d.x, d.y))

    # ------------------------------------------
    # HEADER: logo lockup (decorative band above the safe zone), the match in pips
    # ------------------------------------------
    def _lockup(self):
        def make():
            r, wd = 40, 7
            lq = gfx.lq_mark(self.fonts.get("display", 50))
            word = gfx.tracked(self.fonts.get("black", 30), "THE LIFELONG QUIZ", INK, 6)
            w = 2 * r + 24 + word.get_width() + 8
            s = pygame.Surface((w, 2 * r + 16), pygame.SRCALPHA)
            s.fill((0, 0, 0, 0))
            gfx.ring(s, r + 6, r + 8, r, wd, gap=8)
            s.blit(lq, lq.get_rect(center=(r + 6, r + 8)))
            s.blit(word, word.get_rect(midleft=(2 * r + 26, r + 10)))
            return s
        return self._ucache(("lockup",), make)

    def _v_header(self, logic, status, now):
        lock = self._lockup()
        x, y = (W - lock.get_width()) // 2, 66
        self.screen.blit(lock, (x, y))
        gfx.sweep(self.screen, gfx.silhouette(lock, "lockup"), x, y, ((now % 7.0) - 0.4) / 1.2, 150)
        state = logic.state
        if state in (GameState.ASKING, GameState.LOCKING, GameState.REVEALING, GameState.PODIUM):
            self._v_pips(logic, now)
        if not status.get("connected"):
            self._text("black", TYPE["cap"], "CHAT OFFLINE", BAD, (W - M, 248), "topright")

    def _v_pips(self, logic, now):
        n, pw, g, ph, y = MATCH_LENGTH, 72, 12, 14, 206
        x = (W - n * pw - (n - 1) * g) // 2
        live = logic.q_index if logic.state in (GameState.ASKING, GameState.LOCKING) else 0
        fresh = len(logic.pips) - 1 if logic.state == GameState.REVEALING else -1
        k = progress(now - self._state_enter, REVEAL_AT, 0.4)
        for i in range(n):
            q = i + 1
            if i < len(logic.pips):
                col = GOOD if logic.pips[i] == "done" else BAD
                if i == fresh:   # this question's result fills its pip at the reveal
                    col = mix(TRACK, col, k)
                self.screen.blit(self._alpha_rect(pw, ph, (*col, 255), ph // 2), (x, y))
            elif q == live:
                pulse = 0.5 + 0.5 * math.sin(now * 5)
                glow = gfx.faded(gfx.glow(pw, ph, ph // 2, ACCENT, 14, 200), 120 + 120 * pulse, ("pipglow",), self._uc, 8)
                self.screen.blit(glow, (x - 14, y - 14))
                self.screen.blit(self._alpha_rect(pw, ph, (*ACCENT, 255), ph // 2), (x, y))
            else:
                self.screen.blit(self._alpha_rect(pw, ph, (*TRACK, 255), ph // 2), (x, y))
                ev = _slot_color(logic, q)
                if ev:   # the match's shape: a dot in the colour of a special round or event
                    gfx.disc(self.screen, x + pw // 2, y + ph // 2, 4, ev)
            x += pw + g

    # ------------------------------------------
    # CHIPS
    # ------------------------------------------
    def _chip(self, text, color, filled):
        def make():
            t = self._render_name(text, 30, DARK_INK if filled else color, kind="black")
            w, h = t.get_width() + 48, 54
            s = (gfx.face(w, h, h // 2, color, light=0.22, dark=0.10, rim=0.5) if filled
                 else gfx.glass(w, h, h // 2, edge=color, edge_alpha=150 if color != INK else 70)).copy()
            s.blit(t, t.get_rect(center=(w // 2, h // 2 + 1)))
            return s
        return self._ucache(("chip", text, color, filled), make)

    def _chip_items(self, logic, q, revealed):
        items = [(q.category.upper(), INK, False), (q.difficulty.upper(), DIFF_COLORS.get(q.difficulty, DIM), False)]
        ev = "final" if logic.is_double_points else logic.mini_event
        filled = [(*EVENT_STYLE[ev], True)] if ev in EVENT_STYLE else []
        rs = round_style(q, revealed)
        if rs:
            filled.append((*rs[:2], True))
        fmt = FORMATS.get(getattr(logic, "match_format", "classic"))
        if fmt and logic.match_format != "classic":   # the format chip leads; classic is the default
            filled.insert(0, (fmt[0], fmt[1], True))
        items = filled + items
        surfs = [self._chip(*it) for it in items]
        while sum(s.get_width() for s in surfs) + 14 * (len(surfs) - 1) > CW and len(items) > 1:
            # too wide: drop the category first, then the difficulty; the filled chips stay
            drop = len(filled) if len(items) > len(filled) else len(items) - 1
            items.pop(drop)
            surfs.pop(drop)
        return items, surfs

    def _v_chips(self, logic, q, age, revealed=False, twist=None):
        """Chip row; twist = 0..1 flips the Crowd Mind chip over into Lonely Answer at the reveal."""
        if twist is not None:
            revealed = twist >= 0.5
        items, surfs = self._chip_items(logic, q, revealed)
        flipping = twist is not None and 0 < twist < 1
        x = (W - sum(s.get_width() for s in surfs) - 14 * (len(surfs) - 1)) // 2
        for i, s in enumerate(surfs):
            p = out_expo(progress(age, 0.05 + i * STAGGER, 0.5))
            if p <= 0:
                continue
            w = s.get_width()
            if flipping and items[i][0] in (ROUND_STYLE["majority"][0], ROUND_STYLE["minority"][0]):
                sy = abs(math.cos(twist * math.pi))   # squash to a line, open as the twist
                if sy > 0.04:
                    ss = pygame.transform.smoothscale(s, (w, max(1, int(s.get_height() * sy))))
                    self.screen.blit(ss, ss.get_rect(center=(x + w // 2, CHIPS_Y + s.get_height() // 2)))
            else:
                s.set_alpha(int(255 * p))
                self.screen.blit(s, (int(x - (1 - p) * 60), CHIPS_Y))
                s.set_alpha(255)
            x += w + 14

    # ------------------------------------------
    # QUESTION TEXT AND LAYOUTS
    # ------------------------------------------
    def _ask_layout(self, q, rule):
        """Positions for ASKING / LOCKING, once per question. The answers sit on a fixed floor
        (always the same place on the phone); the timer ring centres in the gap above them."""
        def make():
            lines, size = self._fit_wrap(q.text.upper(), "display", (88, 78, 68, 60), CW, 4)
            lh = int(size * 1.06)
            bottom = Q_Y + len(lines) * lh
            rule_lines, rule_size = [], 0
            if rule:
                rule_lines, rule_size = self._fit_wrap(rule.upper(), "black", (36, 32), CW, 2)
                bottom += 16 + len(rule_lines) * int(rule_size * 1.2)
            n = len(q.options)
            h = 140 if n > 2 else 196
            floor = SAFE_BOTTOM - STRIP
            while h > 96 and floor - (n * h + (n - 1) * GAP) - bottom < 2.2 * 72 + 56:
                h -= 4   # a long question: shorter buttons before the ring gets too small
            top = floor - n * h - (n - 1) * GAP
            ring_r = int(max(52, min(96, (top - bottom - 56) / 2.2)))   # the track and glow need air
            return {"lines": lines, "size": size, "lh": lh, "rule": rule_lines, "rule_size": rule_size,
                    "rule_y": Q_Y + len(lines) * lh + 16, "rects": [(M, top + i * (h + GAP), CW, h) for i in range(n)],
                    "ring": (W // 2, (bottom + top) // 2, ring_r), "floor": floor}
        return self._qc(("ask", q.text, rule), make)

    def _reveal_layout(self, q):
        def make():
            lines, size = self._fit_wrap(q.text.upper(), "display", (58, 52, 46), CW, 3)
            lh = int(size * 1.06)
            n = len(q.options)
            h, g = (114 if n > 2 else 140), 16
            top = Q_Y + len(lines) * lh + 26
            return {"lines": lines, "size": size, "lh": lh, "rects": [(M, top + i * (h + g), CW, h) for i in range(n)],
                    "after": top + n * h + (n - 1) * g + 34}
        return self._qc(("rev", q.text), make)

    def _q_lines(self, lines, size, lh, y, color, age, delay=0.12, alpha=255, dy=0.0):
        for i, line in enumerate(lines):
            core = self._render_name(line, size, color, kind="display")
            padded = gfx.with_shadow(core, ("ql", line, size, color), dy=5, spread=7, alpha=140, store=self._qcache)
            p = out_expo(progress(age, delay + i * 0.07, 0.6))
            pad = (padded.get_width() - core.get_width()) // 2
            top = y + i * lh + dy
            self._rise_blit(padded, W // 2 - core.get_width() // 2 - pad, top - pad, lh + 2 * pad, p, alpha)

    # ------------------------------------------
    # ANSWER BUTTONS
    # ------------------------------------------
    def _btn(self, i, text, w, h, dim=False, pad=40):
        """One answer button, composed once per question: lit face, key cap, answer text.
        dim is the locked / wrong look: the face sinks to navy and the text turns light."""
        def make():
            col = OPTION_COLORS[i]
            base = mix(col, NAVY, 0.7) if dim else col
            s = gfx.face(w, h, R_BTN, base, light=0.10 if dim else 0.16, rim=0.22 if dim else 0.45).copy()
            r = int(min(44, h * 0.31))
            kx, ky = 22 + r, h // 2
            gfx.disc(s, kx, ky + 3, r, mix(base, (0, 0, 0), 0.4))
            gfx.disc(s, kx, ky, r, mix(col, NAVY, 0.45) if dim else (24, 26, 56))
            num = self._render("display", int(r * 1.25), str(i + 1), mix(col, INK, 0.55) if dim else INK)
            s.blit(num, num.get_rect(center=(kx, ky + 1)))
            tx = kx + r + 26
            ink = mix(INK, col, 0.25) if dim else DARK_INK
            lines, size = self._fit_wrap(text, "black", (56, 50, 44, 38), w - tx - pad, 2)
            lh = int(size * 1.04)
            y0 = ky - len(lines) * lh / 2
            for j, line in enumerate(lines):
                t = self._render_name(line, size, ink, kind="black")
                s.blit(t, t.get_rect(midleft=(tx, int(y0 + j * lh + lh / 2))))
            return s
        return self._qc(("btn", i, text, w, h, dim, pad), make)

    def _btn_shadow(self, x, y, w, h, alpha=255):
        sh = gfx.shadow(w, h, R_BTN, 16, 150)
        sh.set_alpha(int(alpha))
        self.screen.blit(sh, (x - 16, y - 16 + 10))
        sh.set_alpha(255)

    def _btn_lit(self, i, text, w, h, pad=40):
        """The answer button already composed over its shadow: one blit instead of two in every
        frame where it stands still. Blit at (x - 16, y - 6)."""
        def make():
            s = gfx.shadow(w, h, R_BTN, 16, 150).copy()
            s.blit(self._btn(i, text, w, h, pad=pad), (16, 6))
            return s
        return self._qc(("btnlit", i, text, w, h, pad), make)

    # ------------------------------------------
    # QUESTION (ASKING / LOCKING)
    # ------------------------------------------
    def _v_question(self, logic, age, now, dt):
        q = logic.current_question
        if not q:
            return
        locking = logic.state == GameState.LOCKING
        q_age = now - logic.question_start_time
        rs = round_style(q)
        L = self._ask_layout(q, rs[2] if rs else "")
        self._v_chips(logic, q, q_age)
        self._q_lines(L["lines"], L["size"], L["lh"], Q_Y, INK, q_age)
        if rs:   # the special round's rule, in its colour
            p = out_expo(progress(q_age, 0.45, 0.5))
            for j, line in enumerate(L["rule"]):
                y = L["rule_y"] + j * int(L["rule_size"] * 1.2)
                self._stext("black", L["rule_size"], line, rs[1], (W // 2, y + (1 - p) * 16), "midtop", alpha=255 * p)

        self._v_pods(logic, q, L, q_age)   # under the timer and the TIME'S UP band
        cx, cy, R = L["ring"]
        if not locking:
            self._v_timer(logic, cx, cy, R, q_age, now)
        else:
            self._v_times_up(logic, cx, cy, R, age, now)

        for i, (opt, rect) in enumerate(zip(q.options, L["rects"])):
            x, y, w, h = rect
            p = out_expo(progress(q_age, 0.4 + i * 0.07, 0.6))
            if p <= 0:
                continue
            x = int(x + (1 - p) * 140)
            a = 255 * clamp01(p * 1.3)
            if a >= 255:
                self.screen.blit(self._btn_lit(i, opt, w, h), (x - 16, y - 6))
            else:
                self._btn_shadow(x, y, w, h, a)
                b = self._btn(i, opt, w, h)
                b.set_alpha(int(a))
                self.screen.blit(b, (x, y))
                b.set_alpha(255)
            gfx.sweep(self.screen, gfx.mask(w, h, R_BTN), x, y, progress(q_age, 0.75 + i * 0.07, 0.6), 140)
            if locking:   # shutters close top-down, a lit edge riding each one
                c = out_expo(progress(age, 0.1 + i * 0.05, 0.4))
                if c > 0:
                    old = self.screen.get_clip()
                    self.screen.set_clip(pygame.Rect(x, y, w, int(h * c)))
                    self.screen.blit(self._btn(i, opt, w, h, dim=True), (x, y))
                    self.screen.set_clip(old)
                    if c < 0.99:
                        self.screen.blit(self._alpha_rect(w - 2 * R_BTN, 4, (255, 255, 255, 200), 2), (x + R_BTN, y + int(h * c) - 2))
        self._v_lock_strip(logic, L, dt)

    def _v_lock_strip(self, logic, L, dt):
        """N LOCKED IN (rolling) and the newest three names, under the answers; a joker or a
        !double shows as a pill tag after the name."""
        n = len(logic.current_question.options)
        locked = logic.answer_count
        self._lock_shown += (locked - self._lock_shown) * min(1.0, dt * 8)
        shown = int(round(self._lock_shown))
        y = L["floor"] + 32
        if locked:
            label = f"{shown} LOCKED IN"
        else:
            label = "TYPE 1 OR 2 IN CHAT" if n == 2 else "TYPE 1, 2, 3 OR 4 IN CHAT"
        self._stext("black", TYPE["label"], label, ACCENT, (W // 2, y), "center")
        halves, doubles = logic.half_picks, getattr(logic, "double_picks", ())
        names = tuple((nm.replace("[Bot] ", ""), "50:50" if nm in halves else "x2" if nm in doubles else "")
                      for nm, _ in reversed(logic.lock_order[-3:]))
        if names:
            s = self._qc(("names", names), lambda: self._names_line(names))
            self.screen.blit(s, s.get_rect(center=(W // 2, y + 46)))

    def _names_line(self, names):
        """'alice · bob [x2] · carol [50:50]', dropping the oldest names until it fits."""
        size = TYPE["label"] - 6
        sep = self._render("semi", size, "  ·  ", DIM)
        for k in range(len(names), 0, -1):
            parts = []   # (surface, air before it)
            for nm, tag in names[:k]:
                if parts:
                    parts.append((sep, 0))
                parts.append((self._fit_name(nm, size, INK, CW // k - (100 if tag else 0), kind="semi"), 0))
                if tag:
                    parts.append((self._pill(tag, ACCENT if tag == "x2" else LILAC, 34), 10))
            w = sum(p.get_width() + air for p, air in parts)
            if w <= CW or k == 1:
                break
        h = max(p.get_height() for p, _ in parts)
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill((0, 0, 0, 0))
        x = 0
        for p, air in parts:
            x += air
            s.blit(p, (x, (h - p.get_height()) // 2))
            x += p.get_width()
        return s

    # ------------------------------------------
    # FEATURE KIT: one look for every game-loop feature. A glass pod with a tracked label, a
    # display value and a segmented meter; pills for tags. Composed once per value, blitted once.
    # ------------------------------------------
    def _pill(self, text, color, h=34, ink=DARK_INK):
        def make():
            t = self._render("black", int(h * 0.62), text, ink)
            w = t.get_width() + int(h * 0.7)
            s = gfx.face(w, h, h // 2, color, light=0.22, dark=0.10, rim=0.4).copy()
            s.blit(t, t.get_rect(center=(w // 2, h // 2 + 1)))
            return s
        return self._ucache(("pill", text, color, h, ink), make)

    def _segments(self, s, x, y, w, h, n, lit, colors, off=TRACK, gap=6):
        """n rounded segments across w; the first `lit` take their colour (colors: one or n)."""
        sw = (w - gap * (n - 1)) / n
        for i in range(n):
            col = (colors[i] if isinstance(colors[0], tuple) else colors) if i < lit else off
            pygame.draw.rect(s, col, (int(x + i * (sw + gap)), y, int(sw), h), border_radius=h // 2)

    def _pod_base(self, w, h, edge):
        s = gfx.glass(w, h, 22, tint=(22, 24, 84), alpha=225, edge=edge, edge_alpha=90).copy()
        return s

    def _pod_label(self, s, text, color=DIM, right=None, right_col=INK):
        lab = gfx.tracked(self.fonts.get("black", 24), text, color, 3)
        s.blit(lab, (20, 16))
        if right:
            r = gfx.tracked(self.fonts.get("black", 24), right, right_col, 3)
            s.blit(r, (s.get_width() - 20 - r.get_width(), 16))

    def _mode_pod(self, logic, w, h):
        """Left of the timer: the format's live state; classic and speed show the community goal."""
        fmt = getattr(logic, "match_format", "classic")
        if fmt == "survivors" and FORMATS.get("survivors"):
            col = FORMATS["survivors"][1]
            alive = logic.perfect
            n = None if alive is None else sum(1 for u in alive if not is_bot(u))
            key = ("pod_surv", w, h, n)

            def make():
                s = self._pod_base(w, h, col)
                self._pod_label(s, "SURVIVORS", col)
                v = self._render("display", 64, "ALL" if n is None else str(n), DIM if n == 0 else INK)
                s.blit(v, (20, h - 26 - v.get_height()))
                sub = self._render("black", 26, f"SPLIT {SURVIVOR_POT}" if n is None or n else "WIPED OUT", DIM)
                s.blit(sub, (w - 20 - sub.get_width(), h - 30 - sub.get_height()))
                return s
        elif fmt == "teams" and getattr(logic, "team_points", None) is not None:
            sc = logic.team_scores()
            g, t = sc.get("gold", 0), sc.get("teal", 0)
            key = ("pod_team", w, h, g, t)

            def make():
                gc, tc = TEAMS["gold"][1], TEAMS["teal"][1]
                s = self._pod_base(w, h, mix(gc, tc, 0.5))
                self._pod_label(s, "GOLD", gc, "TEAL", tc)
                vg = self._render("display", 56, str(g), gc)
                vt = self._render("display", 56, str(t), tc)
                yv = 44
                s.blit(vg, (20, yv))
                s.blit(vt, (w - 20 - vt.get_width(), yv))
                avg = gfx.tracked(self.fonts.get("black", 18), "AVG PTS", DIM, 2)
                s.blit(avg, avg.get_rect(center=(w // 2, yv + vg.get_height() // 2)))
                bw, by = w - 40, h - 30
                share = 0.5 if g + t == 0 else g / (g + t)
                split = int(bw * share)
                pygame.draw.rect(s, tc, (20, by, bw, 12), border_radius=6)
                pygame.draw.rect(s, gc, (20, by, max(12, split), 12), border_radius=6)
                pygame.draw.rect(s, INK, (20 + split - 2, by - 5, 4, 22), border_radius=2)
                return s
        else:
            goal = max(1, getattr(logic, "community_goal", 0) or 1)
            got = min(goal, getattr(logic, "community_correct", 0))
            jack = getattr(logic, "community_jackpot", False)
            key = ("pod_goal", w, h, got, goal, jack)

            def make():
                s = self._pod_base(w, h, GOAL_INK)
                self._pod_label(s, "COMMUNITY GOAL", GOAL_INK)
                if jack:
                    v = self._render("display", 52, "UNLOCKED", gfx.GOLD)
                    sub = self._render("black", 24, f"FINAL: +{JACKPOT_BONUS} EACH RIGHT", INK)
                else:
                    v = self._render("display", 52, f"{got}/{goal}", INK)
                    sub = self._render("black", 24, "RIGHT ANSWERS", DIM)
                s.blit(v, (20, 42))
                s.blit(sub, (20 + v.get_width() + 14 if not jack else 20, 42 + v.get_height() - sub.get_height() - 6
                             if not jack else 42 + v.get_height() + 2))
                if not jack:
                    bw, by = w - 40, h - 28
                    pygame.draw.rect(s, TRACK, (20, by, bw, 12), border_radius=6)
                    if got:
                        pygame.draw.rect(s, GOAL_INK, (20, by, max(12, int(bw * got / goal)), 12), border_radius=6)
                return s
        return self._qc(key, make)

    def _stakes_pod(self, logic, q, w, h):
        """Right of the timer: what the question is worth and where the ladder stands."""
        tier = q.difficulty if q.difficulty in TIER_INK else "medium"   # the tier actually served
        stakes = self._stakes
        key = ("pod_stakes", w, h, tier, stakes)

        def make():
            col = TIER_INK.get(tier, DIM)
            s = self._pod_base(w, h, col)
            self._pod_label(s, "UP TO", DIM, tier.upper(), col)
            if stakes:
                v = gfx.gold_text(self.fonts.get("display", 56), f"{stakes:,}")
                s.blit(v, (20, 42))
                pts = self._render("black", 24, "PTS", DIM)
                s.blit(pts, (24 + v.get_width(), 42 + v.get_height() - pts.get_height() - 8))
            rung = LADDER.index(tier) + 1 if tier in LADDER else len(LADDER)
            self._segments(s, 20, h - 30, w - 40, 12, len(LADDER), rung, tuple(TIER_INK[t] for t in LADDER))
            return s
        return self._qc(key, make)

    def _v_pods(self, logic, q, L, q_age):
        """The two pods beside the timer ring, if the question leaves them room."""
        cx, cy, R = L["ring"]
        top = L["rects"][0][1]
        bottom = 2 * cy - top
        h = min(150, top - bottom - 28)
        w = W // 2 - R - 44 - M
        if h < 112 or w < 230:
            return
        p = out_expo(progress(q_age, 0.6, 0.55))
        if p <= 0:
            return
        y = cy - h // 2
        for surf, x0, dx, tag in ((self._mode_pod(logic, w, h), M, -1, "podL"),
                                  (self._stakes_pod(logic, q, w, h), W - M - w, 1, "podR")):
            if p < 1:   # the pods' values only change at a reveal, never during this slide-in
                surf = gfx.faded(surf, 255 * p, (tag, q.text, surf.get_size()), levels=8)
            self.screen.blit(surf, (int(x0 + dx * (1 - p) * 90), y))

    def _format_card(self, logic):
        """Podium: the survivors' payout or the team win (logic.match_stats), or None."""
        stats = getattr(logic, "match_stats", None) or {}
        if "survivors" in stats:
            n, share = stats["survivors"]
            col = FORMATS["survivors"][1]
            key = ("card_surv", n, share)

            def make():
                s = self._pod_base(CW, 230, col)
                self._pod_label(s, "SURVIVORS", col)
                if n:
                    big = self._render("display", 96, f"{n} SURVIVED" if n > 1 else "1 SURVIVOR", INK)
                    pay = gfx.gold_text(self.fonts.get("display", 72), f"+{share} EACH")
                else:
                    big = self._render("display", 96, "WIPED OUT", DIM)
                    pay = self._render("black", 34, f"Nobody takes the {SURVIVOR_POT}", INK)
                s.blit(big, big.get_rect(midleft=(28, 108)))
                s.blit(pay, pay.get_rect(midleft=(28, 186)))
                self._segments(s, CW - 40 - 200, 104, 200, 14, 5, min(5, n), col)
                return s
            return self._ucache(key, make)
        if "team" in stats:
            win, g, t = stats["team"]
            key = ("card_team", win, g, t)

            def make():
                gc, tc = TEAMS["gold"][1], TEAMS["teal"][1]
                col = TEAMS[win][1] if win in TEAMS else INK
                s = self._pod_base(CW, 230, col)
                self._pod_label(s, "GOLD VS TEAL", DIM)
                head = f"{TEAMS[win][0]} WINS" if win in TEAMS else "A DEAD HEAT"
                big = self._render("display", 84, head, col)
                s.blit(big, big.get_rect(midleft=(28, 96)))
                if win in TEAMS:
                    pay = gfx.gold_text(self.fonts.get("display", 48), f"+{TEAM_WIN_BONUS} EACH")
                    s.blit(pay, pay.get_rect(midright=(CW - 28, 96)))
                bw, by = CW - 56, 168
                share = 0.5 if g + t == 0 else g / (g + t)
                split = int(bw * share)
                pygame.draw.rect(s, tc, (28, by, bw, 16), border_radius=8)
                pygame.draw.rect(s, gc, (28, by, max(16, split), 16), border_radius=8)
                lg = self._render("black", 26, f"GOLD {g}", gc)
                lt = self._render("black", 26, f"{t} TEAL", tc)
                s.blit(lg, (28, by + 22))
                s.blit(lt, (CW - 28 - lt.get_width(), by + 22))
                return s
            return self._ucache(key, make)
        return None

    def _combo_tag(self, streak):
        """A player's combo step: five pills (x1.3 .. x3) and the multiplier, or None below 3."""
        step = sum(1 for at, _ in COMBO_STEPS if streak >= at)
        if not step:
            return None
        mult = COMBO_STEPS[step - 1][1]

        def make():
            t = self._render("black", 26, f"x{mult:g}", gfx.GOLD)
            seg_w = 64
            s = pygame.Surface((seg_w + 10 + t.get_width(), 30), pygame.SRCALPHA)
            s.fill((0, 0, 0, 0))
            self._segments(s, 0, 10, seg_w, 10, len(COMBO_STEPS), step, gfx.GOLD, off=(60, 64, 130), gap=3)
            s.blit(t, (seg_w + 10, (30 - t.get_height()) // 2))
            return s
        return self._ucache(("combo", step), make)

    def _v_timer(self, logic, cx, cy, R, q_age, now):
        rem = logic.time_remaining
        urgent = 0 < rem <= 5
        u = smoothstep(progress(5 - rem, 0, 0.6)) if urgent else 0.0
        beat = heartbeat(math.ceil(rem) - rem) if urgent else 0.0
        drawn = out_expo(progress(q_age, 0.3, 0.8))
        if drawn <= 0:
            return
        # The build-up's intensity carries into the question: a stronger, breathing glow late in the match
        k = clamp01(getattr(logic, "buildup_intensity", 0.0) or 0.0)
        breathe = 0.5 + 0.5 * math.sin(now * 2.4)
        glow = gfx.radial(int(R * 2.1), BAD if urgent else ACCENT, 255, 2.4)
        glow = gfx.faded(glow, (60 + 70 * k * (0.6 + 0.4 * breathe) + u * (90 + 105 * beat)) * drawn,
                         ("tglow", R, urgent), levels=8)
        self.screen.blit(glow, glow.get_rect(center=(cx, cy)))
        jx = math.sin(now * 53) * 3 * u * beat
        jy = math.cos(now * 41) * 3 * u * beat
        colors = gfx.RING_COLORS if u <= 0 else tuple(mix(c, BAD, u) for c in gfx.RING_COLORS)
        width = max(12, R // 5)
        gfx.ring(self.screen, cx + jx, cy + jy, R * (1 + 0.07 * beat), width, remaining=logic.time_fraction,
                 drawn=drawn, colors=colors)
        # The seconds roll like an odometer: the new number rises in, the old one leaves upwards
        secs = int(math.ceil(rem))
        inner = R - width
        size = int(inner * 1.25)                  # Anton digits: ink 0.87 x size tall, 0.47 x size wide
        since = secs - rem
        p = out_cubic(since / 0.28) if q_age > 1.0 else 1.0
        dist = size * 1.25   # far enough that the two numbers never share the window
        old = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(cx - inner, cy - int(inner * 0.86), 2 * inner, int(inner * 1.72)).clip(old))
        scale = 1 + 0.22 * beat
        num = self._render("display", size, str(secs), INK)
        if scale != 1.0:
            num = pygame.transform.smoothscale(num, (int(num.get_width() * scale), int(num.get_height() * scale)))
        num.set_alpha(int(255 * drawn))
        self.screen.blit(num, num.get_rect(center=(cx + jx, cy + jy + 4 + (1 - p) * dist)))
        num.set_alpha(255)
        if p < 1:
            prev = self._render("display", size, str(secs + 1), INK)
            self.screen.blit(prev, prev.get_rect(center=(cx, cy + 4 - p * dist)))
        self.screen.set_clip(old)
        if urgent:
            self._draw_vignette(BAD, 0.25 + 0.55 * beat * u)

    def _times_up_band(self):
        def make():
            w, h, lean = CW + 40, 124, 30
            body = gfx.vgradient(w, h, [mix(BAD, INK, 0.12), BAD, mix(BAD, (0, 0, 0), 0.3)])
            stripes = pygame.Surface((w, h), pygame.SRCALPHA)
            stripes.fill((0, 0, 0, 0))
            for x0 in range(-h, w, 46):
                pygame.draw.polygon(stripes, (0, 0, 0, 34), [(x0, h), (x0 + 20, h), (x0 + 20 + h, 0), (x0 + h, 0)])
            body.blit(stripes, (0, 0))
            shape = pygame.Surface((w * 2, h * 2), pygame.SRCALPHA)
            shape.fill((255, 255, 255, 0))
            pygame.draw.polygon(shape, (255, 255, 255, 255), [(0, h * 2), (lean * 2, 0), (w * 2, 0), (w * 2 - lean * 2, h * 2)])
            out = pygame.transform.smoothscale(shape, (w, h))
            out.blit(body, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            return gfx.with_shadow(out, ("band",), dy=10, spread=12, alpha=170)
        return self._ucache(("timesup",), make)

    def _v_times_up(self, logic, cx, cy, R, age, now, closing=0.0):
        """LOCKING: the ring collapses, a red band slams across, the words land with a shake.
        closing (0..1) folds it away again in the reveal's first frames."""
        out = closing
        shrink = in_expo(progress(age, 0, 0.18))
        if shrink < 1 and out == 0:
            gfx.ring(self.screen, cx, cy, R * (1 - shrink), max(4, int(R // 5 * (1 - shrink))),
                     remaining=0.02 + 0.98 * logic.time_fraction)
        band = self._times_up_band()
        open_ = out_expo(progress(age, 0.06, 0.28)) * (1 - in_expo(out))
        if open_ <= 0:
            return
        bw = band.get_width()
        vis = int(bw * open_)
        old = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(W // 2 - vis // 2, 0, vis, H).clip(old))
        self.screen.blit(band, band.get_rect(center=(W // 2, cy)))
        self.screen.set_clip(old)
        land = progress(age, 0.12, 0.26)
        if land > 0 and out < 0.6:
            words = self._render("display", 84, "TIME'S UP", INK)
            sc = lerp(1.7, 1.0, out_back(land, 2.2))
            if sc != 1.0:
                words = pygame.transform.smoothscale(words, (int(words.get_width() * sc), int(words.get_height() * sc)))
            words.set_alpha(int(255 * clamp01(land * 3) * (1 - out / 0.6)))
            self.screen.blit(words, words.get_rect(center=(W // 2, cy - 6)))
            words.set_alpha(255)
            if "slam" not in self._burst_done and land >= 1 and out == 0:
                self._burst_done.add("slam")
                self._shake = (now, 16.0)
        if out == 0:   # late answers still lock in: a fuse burns along the band's foot
            build = clamp01(age / max(0.1, logic.state_duration))
            bx, by, bwid = M + 120, cy + 40, CW - 240
            self.screen.blit(self._alpha_rect(bwid, 8, (0, 0, 0, 90), 4), (bx, by))
            if build > 0.03:
                self.screen.blit(self._alpha_rect(int(bwid * build), 8, (*ACCENT, 255), 4), (bx, by))
                spark = gfx.radial(26, ACCENT, 255, 1.6)
                self.screen.blit(spark, spark.get_rect(center=(bx + int(bwid * build), by + 4)))
            self._draw_vignette(ACCENT, 0.2 + 0.4 * build * (0.7 + 0.3 * math.sin(now * 30)))

    # ------------------------------------------
    # REVEAL
    # ------------------------------------------
    def _v_reveal(self, logic, age, now):
        res = logic.last_result
        if not res or not res.question.options:
            return
        q = res.question
        rs_ask = round_style(q)
        A = self._ask_layout(q, rs_ask[2] if rs_ask else "")
        Rv = self._reveal_layout(q)
        twist = progress(age, REVEAL_AT, 0.32) if q.kind == "minority" and not res.void else None
        self._v_chips(logic, q, 10.0, revealed=age >= REVEAL_AT, twist=twist)

        # The question hands over from its big asking size to the small results size
        fade = 1 - out_cubic(progress(age, 0, 0.22))
        if fade > 0:
            self._q_lines(A["lines"], A["size"], A["lh"], Q_Y, INK, 10.0, alpha=255 * fade, dy=-30 * (1 - fade))
        self._q_lines(Rv["lines"], Rv["size"], Rv["lh"], Q_Y, DIM, age, delay=0.1)
        if age < 0.3:
            cx, cy, R = A["ring"]
            self._v_times_up(logic, cx, cy, R, 10.0, now, closing=max(0.001, progress(age, 0, 0.3)))

        glide = in_out_cubic(progress(age, 0, T_GLIDE))
        reveal = age >= REVEAL_AT
        k = out_cubic(progress(age, REVEAL_AT, 0.35))
        total = max(1, res.total_answers)
        split = out_cubic(progress(age, T_SPLIT, 0.85))
        winners = set(res.winners)
        order = sorted(range(len(q.options)), key=lambda j: j in winners)   # the right one draws last, on top
        rects = {}
        for i in order:
            opt = q.options[i]
            ax, ay, aw, ah = A["rects"][i]
            x, ry, w, h = Rv["rects"][i]
            y = int(lerp(ay + ah / 2, ry + h / 2, glide) - h / 2)
            correct = i in winners
            dim = 1 - out_cubic(progress(age, 0.15, 0.4))          # locked look fades off as they glide
            loser = reveal and not correct and bool(winners)
            if loser:
                dim = max(dim, k)
                x += int(16 * k)
            if reveal and correct:
                y -= int(10 * out_back(progress(age, REVEAL_AT, 0.4)))
                self._v_flare_under(x, y, w, h, age, now)
            if dim >= 0.99:   # sunk: the dimmed face covers the lit one completely
                self._btn_shadow(x, y, w, h)
            else:
                self.screen.blit(self._btn_lit(i, opt, w, h, pad=170), (x - 16, y - 6))
            if dim > 0.01:
                d = self._btn(i, opt, w, h, dim=True, pad=170)
                d.set_alpha(255 if dim >= 0.99 else int(255 * dim))   # transient fades only
                self.screen.blit(d, (x, y))
                d.set_alpha(255)
            # Answer split: a light fill grows along the button, the percentage counts up
            share = (res.option_counts[i] / total if i < len(res.option_counts) else 0) * split
            fw = int(w * share)
            if fw > 8:
                fill = gfx.faded(gfx.tinted(w, h, R_BTN, INK), lerp(70, 34, dim), ("fill", w, h), levels=32)
                self.screen.blit(fill, (x, y), (0, 0, fw, h))
            pct = f"{int(round(share * 100))}%"
            for col, a in ((DARK_INK, 1 - dim), (INK, dim)):
                if a > 0.02:
                    self._text("display", TYPE["answer"], pct, col, (x + w - 28, y + h // 2 + 2), "midright", alpha=255 * a)
            if loser and q.kind == "odd_one_out":   # the three that belong are struck through
                r = int(min(44, h * 0.31))
                self._strike(x + 2 * r + 40, x + w - 190, y + h // 2, out_expo(progress(age, REVEAL_AT + 0.1 + i * 0.06, 0.4)))
            if reveal and correct:
                self._v_flare_over(q, x, y, w, h, age, now, res)
            rects[i] = (x, y, w, h)

        p = out_expo(progress(age, T_HEAD, 0.6))
        y = Rv["after"]
        head, hcol, line = reveal_lines(res)
        if p > 0:
            head = self._count_head(head, progress(age, T_HEAD, 0.7))
            self._stext("display", TYPE["head"], head, hcol, (W // 2, y + (1 - p) * 40), "midtop", alpha=255 * p)
        y += 82
        lines, size = self._fit_wrap(line, "semi", (40, 36, 32), CW, 3)
        for j, part in enumerate(lines):
            pj = out_expo(progress(age, T_HEAD + 0.12 + j * 0.07, 0.5))
            if pj > 0:
                self._blit(self._render_name(part, size, INK, kind="semi"), (W // 2, y + j * int(size * 1.22) + (1 - pj) * 24),
                           "midtop", alpha=255 * pj)
        y += len(lines) * int(size * 1.22) + 26

        halftime = logic.q_index == MATCH_LENGTH // 2
        if halftime and age >= T_HALF:
            self._v_halftime(logic, age - T_HALF)
            return
        win_rect = rects.get(res.winners[0]) if res.winners else None
        self._v_result_panel(logic, res, y, age, win_rect, standings=not halftime)

    def _count_head(self, head, p):
        """'62% KNEW IT' counts up from 0%."""
        num, sep, rest = head.partition("%")
        if sep and num.isdigit():
            return f"{int(round(int(num) * out_cubic(p)))}%{rest}"
        return head

    def _v_flare_under(self, x, y, w, h, age, now):
        k = progress(age, REVEAL_AT, 0.5)
        glow = gfx.glow(w, h, R_BTN, (255, 236, 170), 40, 230)
        glow = gfx.faded(glow, 255 * (1 - 0.55 * smoothstep(k)) * (0.85 + 0.15 * math.sin(now * 4)), ("flare", w, h),
                         levels=8)
        self.screen.blit(glow, (x - 40, y - 40))
        if "kick" not in self._burst_done:
            self._burst_done.add("kick")
            self._kick_stage(now)

    def _v_flare_over(self, q, x, y, w, h, age, now, res):
        t = age - REVEAL_AT
        flash = 1 - out_cubic(t / 0.4)
        if flash > 0:
            f = gfx.tinted(w, h, R_BTN, INK)
            f.set_alpha(int(230 * flash))
            self.screen.blit(f, (x, y))
        burst = progress(t, 0, 0.55)
        if 0 < burst < 1:   # a light ring leaves the right answer, thinning as it grows
            g = int(46 * out_expo(burst))
            pygame.draw.rect(self.screen, mix(INK, ACCENT, burst), (x - g, y - g, w + 2 * g, h + 2 * g),
                             width=max(1, int(7 * (1 - burst))), border_radius=R_BTN + g // 2)
        shape = gfx.mask(w, h, R_BTN)
        gfx.sweep(self.screen, shape, x, y, progress(t, 0.12, 0.6), 200)
        gfx.sweep(self.screen, shape, x, y, progress((t - 0.8) % 2.8, 0, 0.7) if t > 0.8 else 0, 120)
        rs = round_style(q, revealed=True)
        tag = rs[3] if rs else "CORRECT"
        pop = out_back(progress(t, 0.15, 0.35), 2.0)
        if pop > 0:
            base = self._ucache(("tag", tag), lambda: self._tag_surface(tag))
            s = base if pop == 1 else pygame.transform.smoothscale(
                base, (max(1, int(base.get_width() * pop)), max(1, int(base.get_height() * pop))))
            self.screen.blit(s, s.get_rect(center=(x + w - 40 - base.get_width() // 2, y)))
        if "burst" not in self._burst_done and res.correct_players:
            self._burst_done.add("burst")
            self.burst(x + w // 2, y + h // 2, n=70, power=0.8)

    def _tag_surface(self, tag):
        t = self._render("black", TYPE["cap"], tag, DARK_INK)
        w, h = t.get_width() + 30, 38
        s = gfx.face(w, h, h // 2, INK, light=0.0, dark=0.1, rim=0.0).copy()
        s.blit(t, t.get_rect(center=(w // 2, h // 2 + 1)))
        return s

    # ------------------------------------------
    # REVEAL PANEL: fastest players (points fly in), then the match standings re-order
    # ------------------------------------------
    def _v_result_panel(self, logic, res, y0, age, win_rect, standings=True):
        rh = 62
        rows = max(0, min(5, (SAFE_BOTTOM - y0 - 48) // rh))
        if rows == 0:
            return
        q = res.question
        a_out = out_expo(progress(age, T_STAND, 0.35)) if standings else 0.0
        if a_out < 1:
            p = out_expo(progress(age, T_PANEL, 0.4)) * (1 - a_out)
            if p > 0:
                self._label(winners_title(q), (M + 8 - a_out * 80, y0), alpha=255 * p)
            players = res.correct_players[:min(3, rows)]
            for i, (name, pts, t) in enumerate(players):
                pp = out_expo(progress(age, T_PANEL + 0.1 + i * 0.1, 0.5))
                if pp <= 0:
                    continue
                ry = y0 + 46 + i * rh
                ox = (1 - pp) * -120 - a_out * (200 + i * 60)
                al = 255 * pp * (1 - a_out)
                self._row_bg(ry, al)
                bot = is_bot(name)
                plr = logic.db._players.get(name)
                combo = None if bot or plr is None else self._combo_tag(getattr(plr, "streak", 0))
                room = CW - 330 - (combo.get_width() + 16 if combo else 0)
                ns = self._fit_name(name.replace("[Bot] ", ""), 40, FAINT if bot else INK, room, kind="black")
                self._blit(ns, (M + 22 + ox, ry + rh // 2 - 4), "midleft", alpha=al)
                if combo:   # the combo step meter: how far up the streak multiplier this player is
                    self._blit(combo, (M + 22 + ox + ns.get_width() + 16, ry + rh // 2 - 4), "midleft", alpha=al)
                self._text("bold", TYPE["body"], f"{t:.1f}s", DIM, (W - M - 150 + ox, ry + rh // 2 - 4), "midright", alpha=al)
                # +points fly in from the right answer and land in the row
                fly = in_out_cubic(progress(age, T_PANEL + 0.35 + i * 0.13, 0.5))
                dest = (W - M - 22 + ox, ry + rh // 2 - 4)
                if win_rect and fly < 1:
                    if fly > 0:
                        sx, sy = win_rect[0] + win_rect[2] // 2, win_rect[1] + win_rect[3] // 2
                        cx, cy = (sx + dest[0]) / 2 + 160, min(sy, dest[1]) - 60
                        bx = (1 - fly) ** 2 * sx + 2 * (1 - fly) * fly * cx + fly ** 2 * dest[0]
                        by = (1 - fly) ** 2 * sy + 2 * (1 - fly) * fly * cy + fly ** 2 * dest[1]
                        chip = self._ucache(("fly", pts), lambda: self._fly_chip(pts))
                        self.screen.blit(chip, chip.get_rect(center=(int(bx), int(by))))
                else:
                    land = progress(age, T_PANEL + 0.85 + i * 0.13, 0.3)
                    self._text("black", 42, f"+{pts}", GOOD, dest, "midright", alpha=al,
                               scale=lerp(1.5, 1.0, out_back(land)) if land < 1 else 1.0)
            if not players and p > 0:
                self._text("bold", 32, "Round void: nobody scores" if res.void else "Nobody got this one", FAINT,
                           (M + 8, y0 + 56), alpha=255 * p)
        if standings and age >= T_STAND:
            self._v_standings(logic, y0, rows, rh, age)

    def _row_bg(self, y, alpha):
        g = gfx.glass(CW, 54, 16, alpha=110, edge_alpha=24)
        g.set_alpha(int(alpha))
        self.screen.blit(g, (M, y))
        g.set_alpha(255)

    def _fly_chip(self, pts):
        t = self._render("black", 34, f"+{pts}", DARK_INK)
        w, h = t.get_width() + 30, 50
        s = pygame.Surface((w + 40, h + 40), pygame.SRCALPHA)
        s.fill((0, 0, 0, 0))
        s.blit(gfx.glow(w, h, h // 2, GOOD, 20, 200), (0, 0))
        s.blit(gfx.face(w, h, h // 2, GOOD, rim=0.4), (20, 20))
        s.blit(t, t.get_rect(center=(20 + w // 2, 20 + h // 2 + 1)))
        return s

    def _v_standings(self, logic, y0, rows, rh, age):
        """Match standings: rows enter in the order before this question, then glide to the new
        order while totals count up; arrows show who climbed."""
        p_in = out_expo(progress(age, T_STAND + 0.1, 0.45))
        self._label(f"MATCH {logic.match_no}  ·  STANDINGS", (M + 8 + (1 - p_in) * 80, y0), alpha=255 * p_in)
        ranked = logic.match_ranking(n=rows)
        old = self._pre_points
        old_order = sorted(old, key=lambda u: (-old[u], logic.standings[u].fastest if u in logic.standings else 999))
        old_rank = {u: i for i, u in enumerate(old_order) if old[u] > 0}
        move = out_back(progress(age, T_REORDER, 0.7), 1.3)
        count = out_cubic(progress(age, T_REORDER, 0.8))
        arrows = progress(age, T_REORDER + 0.5, 0.3)
        items = []
        for ni, st in enumerate(ranked):
            oi = old_rank.get(st.username)
            start = oi if oi is not None and oi < rows else rows + 0.6
            items.append((oi, ni, st, lerp(start, ni, move)))
        for oi, ni, st, slot in sorted(items, key=lambda it: (rows if it[0] is None else it[0]) - it[1]):   # climbers on top
            pr = out_expo(progress(age, T_STAND + 0.15 + min(ni, oi if oi is not None else ni) * 0.08, 0.45))
            if pr <= 0:
                continue
            ry = y0 + 46 + slot * rh
            if ry > SAFE_BOTTOM - rh + 8:
                continue
            ox = (1 - pr) * 160
            al = 255 * pr
            self._row_bg(ry, al)
            bot = is_bot(st.username)
            col = FAINT if bot else (ACCENT if ni == 0 and move > 0.5 else INK)
            self._text("display", 42, str(ni + 1), PLACE_COLORS[ni] if ni < 3 else DIM, (M + 38 + ox, ry + rh // 2 - 4), "center", alpha=al)
            self._blit(self._fit_name(st.username.replace("[Bot] ", ""), 38, col, CW - 360, kind="black"),
                       (M + 80 + ox, ry + rh // 2 - 4), "midleft", alpha=al)
            pts = int(round(lerp(old.get(st.username, 0), st.points, count)))
            self._text("black", 40, f"{pts:,}", col, (W - M - 22 + ox, ry + rh // 2 - 4), "midright", alpha=al)
            if arrows > 0 and oi is not None and oi != ni:
                self._rank_arrow(W - M - 190 + ox, ry + rh // 2 - 4, oi - ni, out_back(arrows, 2.0))

    def _rank_arrow(self, cx, cy, delta, p):
        up = delta > 0
        col = GOOD if up else BAD
        s = 11 * p
        if s < 1:
            return
        pts = [(cx - 22 - s, cy + (s * 0.6 if up else -s * 0.6)), (cx - 22 + s, cy + (s * 0.6 if up else -s * 0.6)),
               (cx - 22, cy + (-s * 0.8 if up else s * 0.8))]
        pygame.draw.polygon(self.screen, col, pts)
        self._text("black", 26, str(abs(delta)), col, (cx - 6, cy), "midleft", alpha=255 * clamp01(p))

    # ------------------------------------------
    # HALFTIME (after question 5): a card takes the reveal's tail; the bumper wipes over it
    # ------------------------------------------
    def _halftime_ring(self):
        """The logo ring as a quiet watermark behind HALFTIME (rendered once)."""
        def make():
            r = 250
            s = pygame.Surface((2 * r + 20, 2 * r + 20), pygame.SRCALPHA)
            s.fill((0, 0, 0, 0))
            gfx.ring(s, r + 10, r + 10, r, 26, colors=tuple(mix(c, FLAT, 0.72) for c in gfx.RING_COLORS), track=False)
            return s
        return self._ucache(("htring",), make)

    def _v_halftime(self, logic, t):
        """Brand moment: the four-colour ribbon sweeps over the reveal, then the standings card."""
        if t < T_HALF_COVER:
            self.fx.cover(self.screen, "ribbon", t / T_HALF_COVER, bg=FLAT)
            return
        h = t - T_HALF_COVER
        ring = self._halftime_ring()
        spin = out_expo(progress(h, 0.0, 1.2))
        self.screen.blit(ring, ring.get_rect(center=(W // 2, 330 - int((1 - spin) * 60))))
        p = out_expo(progress(h, 0.0, 0.5))
        s = self._gold(150, "HALFTIME")
        self._rise_blit(s, (W - s.get_width()) // 2, 200, s.get_height(), p)
        self._text("black", 34, f"MATCH {logic.match_no}  ·  {logic.q_index} OF {MATCH_LENGTH} PLAYED", LILAC,
                   (W // 2, 500), "center", alpha=255 * progress(h, 0.15, 0.3))
        ranked = logic.match_ranking(n=5)
        if not ranked:
            self._text("bold", 34, "No points yet: the second half starts now", INK, (W // 2, 700), "center")
            return
        top = max(1, ranked[0].points)
        old = self._pre_points
        old_order = sorted(old, key=lambda u: -old[u])
        old_rank = {u: i for i, u in enumerate(old_order) if old[u] > 0}
        for i, st in enumerate(ranked):
            ry = 580 + i * 150
            pr = out_expo(progress(h, 0.2 + i * 0.09, 0.5))
            if pr <= 0:
                continue
            bot = is_bot(st.username)
            col = PLACE_COLORS[i] if i < 3 else INK
            self._text("display", 70, str(i + 1), col, (M + 30, ry + 50), "center", alpha=255 * pr)
            self._blit(self._fit_name(st.username.replace("[Bot] ", ""), 40, FAINT if bot else INK, CW - 260, kind="black"),
                       (M + 90, ry + 22), "midleft", alpha=255 * pr)
            bar = int((CW - 260) * st.points / top * out_expo(progress(h, 0.35 + i * 0.09, 0.8)))
            self.screen.blit(self._alpha_rect(CW - 260, 26, (255, 255, 255, 30), 13), (M + 90, ry + 60))
            if bar > 26:
                self.screen.blit(self._alpha_rect(bar, 26, (*col, 255), 13), (M + 90, ry + 60))
            self._text("display", 54, f"{st.points:,}", INK, (W - M, ry + 70), "midright", alpha=255 * pr)
            oi = old_rank.get(st.username)
            if oi is not None and oi != i:
                self._rank_arrow(W - M - 150, ry + 22, oi - i, out_back(progress(h, 0.8 + i * 0.09, 0.3), 2.0))

    # ------------------------------------------
    # LOBBY
    # ------------------------------------------
    def _v_lobby(self, logic, age, dt, now):
        rem = logic.time_remaining
        secs = int(math.ceil(rem))
        # Hero: the logo ring is the countdown; the time sits beside it
        rcx, rcy, R = M + 150, 362, 130
        drawn = out_expo(progress(age, 0.1, 1.0))
        glow = gfx.faded(gfx.radial(int(R * 1.9), ACCENT if secs > 5 else BAD, 255, 2.6), 80 * drawn,
                         ("lobbyglow", secs > 5), levels=8)
        self.screen.blit(glow, glow.get_rect(center=(rcx, rcy)))
        gfx.ring(self.screen, rcx, rcy, R, 22, remaining=logic.time_fraction, drawn=drawn)
        lq = gfx.lq_mark(self.fonts.get("display", 150))
        lp = out_expo(progress(age, 0.3, 0.6))
        self._blit(lq, (rcx, rcy + (1 - lp) * 40), "center", alpha=255 * lp)
        tx = M + 330
        self._text("black", TYPE["body"], f"MATCH {logic.match_no} STARTS IN", DIM, (tx + 6, 262))
        pop = 1.0 + 0.1 * (1 - out_cubic((secs - rem) / 0.35)) if secs <= 10 else 1.0
        clock = f"0:{secs:02d}" if secs < 60 else f"{secs // 60}:{secs % 60:02d}"
        if secs > 5:
            big = self._gold(190, clock)
            core = gfx.gold_text(self.fonts.get("display", 190), clock).get_size()
        else:
            core = self._render("display", 190, clock, BAD).get_size()
            big = gfx.with_shadow(self._render("display", 190, clock, BAD), ("red", clock), dy=8, spread=13, alpha=170, store=self._uc)
        if pop != 1.0:
            big = pygame.transform.smoothscale(big, (int(big.get_width() * pop), int(big.get_height() * pop)))
            core = (int(core[0] * pop), int(core[1] * pop))
        self._blit_padded(big, core, (tx, 400), "midleft")
        self._stext("black", TYPE["label"], "VOTE THE CATEGORY: TYPE 1-4", INK, (W // 2, 532), "center")

        vs = logic.vote_state
        y = 572
        ch, g = 110, 14
        if vs:
            counts = vs.vote_counts()
            total = max(1, vs.total_votes())
            lead = vs.leading_option() if vs.total_votes() > 0 else None
            for opt, (_, name) in vs.options.items():
                i = opt - 1
                p = out_expo(progress(age, 0.25 + i * STAGGER, 0.6))
                if p <= 0:
                    continue
                x = int(M + (1 - p) * 160)
                yy = y + i * (ch + g)
                is_lead = opt == lead
                if is_lead:
                    gl = gfx.faded(gfx.glow(CW, ch, 26, ACCENT, 26, 150), 150 + 70 * math.sin(now * 3), ("leadglow",), levels=8)
                    self.screen.blit(gl, (x - 26, yy - 26))
                panel = gfx.glass(CW, ch, 26, edge=ACCENT if is_lead else INK, edge_alpha=200 if is_lead else 40)
                panel.set_alpha(int(255 * p))
                self.screen.blit(panel, (x, yy))
                panel.set_alpha(255)
                col = OPTION_COLORS[i]
                gfx.disc(self.screen, x + 62, yy + ch // 2 + 3, 38, mix(col, (0, 0, 0), 0.4))
                gfx.disc(self.screen, x + 62, yy + ch // 2, 38, col)
                self._text("display", 50, str(opt), DARK_INK, (x + 62, yy + ch // 2 + 1), "center")
                self._blit(self._fit_name(name, 44, INK, CW - 330, kind="black"), (x + 124, yy + 44), "midleft", alpha=255 * p)
                target = counts.get(opt, 0) / total
                cur = self._vote_bars.get(opt, 0.0)
                cur += (target - cur) * min(1.0, dt * 6)
                self._vote_bars[opt] = cur
                bx, by, bw = x + 124, yy + 78, CW - 124 - 120
                self.screen.blit(self._alpha_rect(bw, 14, (255, 255, 255, 34), 7), (bx, by))
                if cur > 0.01:
                    self.screen.blit(self._alpha_rect(max(14, int(bw * cur)), 14, (*(ACCENT if is_lead else col), 255), 7), (bx, by))
                self._text("display", 56, str(counts.get(opt, 0)), ACCENT if is_lead else INK, (x + CW - 30, yy + ch // 2), "midright")
            y += 4 * ch + 3 * g + 26

        # How to play
        p = out_expo(progress(age, 0.6, 0.6))
        card_h = 126
        card = self._ucache(("newcard",), self._new_here_card)
        card.set_alpha(int(255 * p))
        self.screen.blit(card, (M, y + (1 - p) * 40))
        card.set_alpha(255)
        gfx.sweep(self.screen, gfx.mask(CW, card_h, 24), M, y, ((now % 6.0) - 1.0) / 1.1, 160)
        y += card_h + 32

        # This week's top players
        rows = max(0, min(5, (SAFE_BOTTOM - y - 50) // 50))
        players = logic.leaderboard[:rows]
        if rows:
            self._label("THIS WEEK", (M + 8, y))
            self._label(f"{logic.active_player_count} PLAYING", (W - M - 8, y), "topright")
            for i, pl in enumerate(players):
                ry = y + 64 + i * 50
                pp = out_expo(progress(age, 0.7 + i * STAGGER, 0.5))
                ox = (1 - pp) * -80
                col = PLACE_COLORS[i] if i < 3 else DIM
                self._text("display", 38, str(i + 1), col, (M + 30 + ox, ry), "center", alpha=255 * pp)
                self._blit(self._fit_name(pl.username, 36, INK, CW - 300), (M + 80 + ox, ry), "midleft", alpha=255 * pp)
                self._text("black", 36, f"{pl.weekly_score:,}", INK, (W - M - 10 + ox, ry), "midright", alpha=255 * pp)
            if not players:
                self._text("bold", 32, "Empty so far: answer to get on it!", FAINT, (M + 10, y + 64))

    def _new_here_card(self):
        w, h = CW, 126
        s = gfx.face(w, h, 24, ACCENT, light=0.2, dark=0.08, rim=0.5).copy()
        s.blit(self._render("black", 26, "NEW HERE?", mix(DARK_INK, ACCENT, 0.3)), (30, 18))
        s.blit(self._render("bold", 34, "Type 1, 2, 3 or 4 in chat when", DARK_INK), (30, 48))
        s.blit(self._render("bold", 34, "the question shows. That's it!", DARK_INK), (30, 84))
        return s

    # ------------------------------------------
    # INTRO (4 s): MATCH N, the ring draws on around LQ, 3-2-1 drains it, push through
    # ------------------------------------------
    def _v_intro(self, logic, age):
        cx, cy, R = W // 2, 880, 200
        push = in_expo(progress(age, 3.7, 0.3))       # camera flies through the ring into question 1
        fade = 1 - push
        # MATCH N: letters rise out of a mask one by one
        text = f"MATCH {logic.match_no}"
        font_size = 150
        glyphs = [self._render("display", font_size, ch, INK) for ch in text]
        total = sum(g.get_width() for g in glyphs) + 4 * (len(glyphs) - 1)
        x = (W - total) // 2
        top = 360
        for k, g in enumerate(glyphs):
            p = out_expo(progress(age, 0.25 + k * 0.035, 0.55))
            self._rise_blit(g, x, top - push * 200, g.get_height(), p, alpha=255 * fade)
            x += g.get_width() + 4
        # The ring
        drawn = out_expo(progress(age, 0.2, 0.9))
        remaining = 1.0 if age < 1.0 else 1 - clamp01((age - 1.0) / 2.75)
        glow = gfx.faded(gfx.radial(int(R * 1.9), ACCENT, 255, 2.4), 110 * drawn * fade, ("introglow",), levels=8)
        self.screen.blit(glow, glow.get_rect(center=(cx, cy)))
        rr = R * (1 + 7 * push)
        gfx.ring(self.screen, cx, cy, rr, int(30 * (1 + 3 * push)), remaining=max(0.02, remaining) if push == 0 else 1.0,
                 drawn=drawn, track=push == 0)
        # LQ inside, then the 3-2-1
        lq_p = out_expo(progress(age, 0.4, 0.5)) * (1 - in_expo(progress(age, 0.9, 0.15)))
        if lq_p > 0:
            lq = gfx.lq_mark(self.fonts.get("display", 230))
            self._rise_blit(lq, cx - lq.get_width() // 2, cy - lq.get_height() // 2, lq.get_height(), lq_p)
        for i, n in enumerate(("3", "2", "1")):
            t0 = 1.0 + i * 0.95
            if t0 <= age < t0 + 0.95 and push == 0:
                p = age - t0
                s = self._gold(260, n)
                core = gfx.gold_text(self.fonts.get("display", 260), n).get_size()
                sc = lerp(1.8, 1.0, out_back(p / 0.35))
                if sc != 1.0:
                    s = pygame.transform.smoothscale(s, (int(s.get_width() * sc), int(s.get_height() * sc)))
                    core = (int(core[0] * sc), int(core[1] * sc))
                self._blit_padded(s, core, (cx, cy + 6), "center", alpha=255 * (1 - progress(p, 0.7, 0.25)))
        # The category and how to play, under the ring
        # The format chip (special.FORMATS) beside the category, and its rule under them
        fmt = FORMATS.get(getattr(logic, "match_format", "classic"), FORMATS["classic"])
        chips = [self._chip(fmt[0], fmt[1], True), self._chip(logic.match_category.upper(), ACCENT, True)]
        x = cx - (sum(c.get_width() for c in chips) + 14) // 2
        for k, chip in enumerate(chips):
            cat = out_expo(progress(age, 0.55 + k * STAGGER, 0.5))
            if cat > 0:
                self._blit(chip, (x, cy + R + 110 + (1 - cat) * 40 + push * 200), "midleft", alpha=255 * cat * fade)
            x += chip.get_width() + 14
        rule = fmt[2] if logic.match_format != "classic" else f"{MATCH_LENGTH} questions  ·  type 1-4 in chat to play"
        lines, size = self._qc(("introrule", rule), lambda: self._fit_wrap(rule, "bold", (34, 32, 30), CW, 2))
        for j, line in enumerate(lines):
            self._text("bold", size, line, INK if logic.match_format != "classic" else DIM,
                       (cx, cy + R + 190 + j * 42 + push * 200), "center", alpha=255 * progress(age, 0.8, 0.4) * fade)

    # ------------------------------------------
    # PODIUM: push-in, spotlights on 3, 2, then 1 with a sunburst and the crown
    # ------------------------------------------
    PODIUM_BASE = 1130
    PODIUM = ((0, 540, 330, 3.0), (1, 228, 240, 1.95), (2, 852, 180, 0.9))   # place, centre x, height, cue
    PODIUM_W = 276

    def _cone(self, place):
        """Soft spotlight from the rig to a plinth (rendered once)."""
        def make():
            _, pcx, ph, _ = self.PODIUM[place]
            top_y, bot_y = 150, self.PODIUM_BASE - ph + 40
            src = W // 2 + (pcx - W // 2) // 3
            x0 = min(src - 40, pcx - self.PODIUM_W // 2 - 60) - 30
            x1 = max(src + 40, pcx + self.PODIUM_W // 2 + 60) + 30
            w, h = x1 - x0, bot_y - top_y
            k = 4
            s = pygame.Surface((w // k, h // k), pygame.SRCALPHA)
            col = (255, 236, 170) if place == 0 else (220, 230, 255)
            s.fill((*col, 0))
            pygame.draw.polygon(s, (*col, 70), [((src - 36 - x0) // k, 0), ((src + 36 - x0) // k, 0),
                                                ((pcx + self.PODIUM_W // 2 + 40 - x0) // k, h // k),
                                                ((pcx - self.PODIUM_W // 2 - 40 - x0) // k, h // k)])
            s = gfx.blur(s, 4)
            fade = gfx.vgradient(w // k, h // k, [(255, 255, 255), (255, 255, 255), (150, 150, 150)])
            s.blit(fade, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
            return pygame.transform.smoothscale(s, (w, h)), (x0, top_y)
        return self._ucache(("cone", place), make)

    def _v_podium(self, logic, age, now):
        base = self.PODIUM_BASE
        z = lerp(0.8, 1.0, out_cubic(progress(age, 0.0, 2.2)))   # the camera pushes in on the podium
        fx_, fy_ = W / 2, base - 160

        def X(x):
            return fx_ + (x - fx_) * z

        def Y(y):
            return fy_ + (y - fy_) * z

        # Titles
        p1 = out_expo(progress(age, 0.25, 0.5))
        self._text("black", TYPE["body"], f"MATCH {logic.match_no}", DIM, (W // 2, 258 - (1 - p1) * 20), "center", alpha=255 * p1)
        wt = self._gold(130, "WINNERS")
        core = gfx.gold_text(self.fonts.get("display", 130), "WINNERS").get_size()
        pw = out_expo(progress(age, 0.35, 0.55))
        self._blit_padded(wt, core, (W // 2, 348 + (1 - pw) * 50), "center", alpha=255 * pw)
        self._blit(self._render_name(f"{logic.match_player_count} PLAYERS  ·  {logic.match_category.upper()}", 30, DIM, kind="black"),
                   (W // 2, 446), "center", alpha=255 * progress(age, 0.6, 0.4))

        podium = logic.podium
        # Sunburst behind the winner
        if podium:
            on = smoothstep(progress(age, 3.0, 0.6))
            if on > 0:
                _, pcx, ph, _ = self.PODIUM[0]
                cx, cy = X(pcx), Y(base - ph - 150)
                rot = now * 0.18
                # Opaque rays on a black scratch, ADDed: on this dark stage that matches the old
                # alpha rays (alpha 7 long, alpha 12 more near the centre) at a third of the cost.
                top, bot = max(0, int(cy - 820)), min(H, int(cy + 820))
                if self._rays is None or self._rays.get_size() != (W, bot - top):
                    self._rays = pygame.Surface((W, bot - top))
                rays = self._rays
                rays.fill((0, 0, 0))
                for r_out, a in ((820, 7), (430, 19)):
                    col = tuple(int(c * a * on / 255) for c in (255, 228, 150))
                    for j in range(12):
                        a0 = rot + j * math.pi / 6
                        pts = [(cx, cy - top), (cx + math.cos(a0 - 0.1) * r_out, cy - top + math.sin(a0 - 0.1) * r_out),
                               (cx + math.cos(a0 + 0.1) * r_out, cy - top + math.sin(a0 + 0.1) * r_out)]
                        pygame.draw.polygon(rays, col, pts)
                self.screen.blit(rays, (0, top), special_flags=pygame.BLEND_RGB_ADD)
        # Spotlights switch on with a flicker, 3rd -> 2nd -> 1st
        for place, pcx, ph, cue in self.PODIUM:
            if place >= len(podium):
                continue
            t = age - cue
            if t > 0:
                flick = 0.0 if t < 0.05 else 0.6 if t < 0.09 else 0.15 if t < 0.13 else min(1.0, 0.7 + t)
                cone, (cx0, cy0) = self._cone(place)
                self.screen.blit(gfx.faded(cone, 255 * flick, ("cone", place), levels=8), (int(X(cx0)), int(Y(cy0))))
        # Floor glow and line
        glow = self._ucache(("floor",), lambda: pygame.transform.smoothscale(gfx.radial(300, (130, 140, 255), 150, 1.8), (1000, 170)))
        glow = gfx.faded(glow, 255 * smoothstep(progress(age, 0.6, 1.0)), ("podfloor",), levels=12)
        self.screen.blit(glow, glow.get_rect(center=(W // 2, int(Y(base)))))
        self.screen.blit(self._alpha_rect(CW, 6, (*TRACK, 255), 3), (M, int(Y(base))))

        if not podium:
            p = out_expo(progress(age, 0.6, 0.5))
            self._stext("display", 76, "NO WINNER", DIM, (W // 2, base - 260), "center", alpha=255 * p)
            self._text("bold", 34, "Type 1-4 next match and", INK, (W // 2, base - 170), "center", alpha=255 * p)
            self._text("bold", 34, "the podium is yours", INK, (W // 2, base - 124), "center", alpha=255 * p)

        for place, pcx, ph, cue in self.PODIUM:
            if place >= len(podium):
                continue
            st = podium[place]
            rise = out_back(progress(age, cue + 0.05, 0.6), 1.2)
            hh = ph * max(0.0, rise)
            if hh <= 1:
                continue
            col = PLACE_COLORS[place]
            bw = self.PODIUM_W * z
            x0, x1 = X(pcx) - bw / 2, X(pcx) + bw / 2
            yt, yb = Y(base - hh), Y(base)
            depth = 26 * z
            pygame.draw.polygon(self.screen, mix(col, INK, 0.35), [(x0, yt), (x1, yt), (x1 - depth * 0.7, yt - depth), (x0 + depth * 0.7, yt - depth)])
            pygame.draw.rect(self.screen, col, (int(x0), int(yt), int(bw), int(yb - yt) + 1))
            pygame.draw.rect(self.screen, mix(col, INK, 0.45), (int(x0), int(yt), int(bw), 4))
            pygame.draw.rect(self.screen, mix(col, (0, 0, 0), 0.22), (int(x1 - bw * 0.14), int(yt), int(bw * 0.14) + 1, int(yb - yt) + 1))
            pygame.draw.rect(self.screen, mix(col, INK, 0.25), (int(x0), int(yt), int(bw * 0.06), int(yb - yt) + 1))
            num_a = progress(age, cue + 0.35, 0.3)
            if num_a > 0:
                self._text("display", 120, str(place + 1), mix(col, DARK_INK, 0.7), (X(pcx), yt + 14), "midtop", alpha=255 * num_a)
            # The player drops in on a spring
            dp = progress(age, cue + 0.35, 0.7)
            if dp <= 0:
                continue
            r = 64 if place == 0 else 52
            top = base - ph
            ay = Y(top) - 132 - r - (1 - spring(dp)) * 120
            ax = X(pcx)
            ring_col = PLACE_COLORS[place]
            halo = gfx.radial(int(r * 2.2), ring_col, 200, 2.0)
            halo.set_alpha(int(255 * clamp01(dp * 3)))
            self.screen.blit(halo, halo.get_rect(center=(int(ax), int(ay))))
            self._avatar(st.username, int(ax), int(ay), r, ring_col)
            if place == 0:
                cp = progress(age, cue + 0.75, 0.6)
                if cp > 0:
                    self._crown(int(ax), int(ay - r - 26 - (1 - out_back(cp, 2.4)) * 60), 32, gfx.GOLD)
            na = 255 * clamp01(dp * 2)
            self._blit(self._fit_name(st.username, 38 if place == 0 else 32, gfx.GOLD if place == 0 else INK,
                                      self.PODIUM_W + 20, kind="black"), (ax, Y(top) - 74), "center", alpha=na)
            self._text("bold", 28, f"{st.points:,} pts", DIM, (ax, Y(top) - 36), "center", alpha=na)
            if place == 0 and dp > 0.35 and "podium" not in self._burst_done:
                self._burst_done.add("podium")
                self._kick_stage(now)
                self.burst(int(ax), int(ay), n=170, power=1.3)
                self.burst(M + 40, base, n=50, power=1.1)
                self.burst(W - M - 40, base, n=50, power=1.1)

        # The format's result (survivors' payout, the team win), then this week's ladder
        y = base + 36
        t_lad = 4.4
        card = self._format_card(logic)
        if card is not None:
            t_lad = T_LADDER_LATE
            cp = out_back(progress(age, T_FORMAT_CARD, 0.5), 1.3)
            out = in_cubic(progress(age, T_LADDER_LATE - 0.5, 0.4))
            if cp > 0 and out < 1:
                a = 255 * clamp01(cp) * (1 - out)
                self._blit(card, (W // 2, int(y + card.get_height() // 2 + (1 - cp) * 80 - out * 60)), "center", alpha=a)
        pl = out_expo(progress(age, t_lad, 0.5))
        if pl > 0:
            self._label("THIS WEEK'S LADDER", (M + 10, y), alpha=255 * pl)
        rows = max(1, min(6, (SAFE_BOTTOM - y - 40) // 50))
        for i, plr in enumerate(logic.leaderboard[:rows]):
            ry = y + 64 + i * 50
            pp = out_expo(progress(age, t_lad + 0.1 + i * STAGGER, 0.5))
            if pp <= 0:
                continue
            ox = (1 - pp) * 120
            ch = logic.ladder_changes.get(plr.username, 0)
            col = PLACE_COLORS[i] if i < 3 else DIM
            self._text("display", 38, str(i + 1), col, (M + 30 + ox, ry), "center", alpha=255 * pp)
            if ch is None:
                self._text("black", 26, "NEW", GOOD, (M + 100 + ox, ry), "center", alpha=255 * pp)
            elif ch:
                self._rank_arrow(M + 112 + ox, ry, ch, pp)
            else:
                self._text("black", 24, "-", FAINT, (M + 100 + ox, ry), "center", alpha=255 * pp)
            self._blit(self._fit_name(plr.username, 36, INK, CW - 380), (M + 150 + ox, ry), "midleft", alpha=255 * pp)
            self._text("black", 36, f"{plr.weekly_score:,}", INK, (W - M - 10 + ox, ry), "midright", alpha=255 * pp)

    # ------------------------------------------
    # OVERLAYS
    # ------------------------------------------
    # Announcements: every toast from logic._push_event(text, color, badge) gets the same
    # broadcast tab: a badge block in the event colour (a glyph for known codes, else the code
    # itself) and a dark panel that unrolls out of it, with a fuse that burns down its life.
    # Text written "KICKER: rest" or "KICKER! rest" with an all-caps kicker prints the kicker in
    # the event colour ("LIGHTNING ROUND! 22s, 1.5x points"), so new features get a headline
    # just by how they word the event.
    T_H = 76

    @staticmethod
    def _split_kicker(text):
        for sep in ("! ", ": "):
            head, s, rest = text.partition(sep)
            if s and rest and head.isupper() and 2 <= len(head) <= 26:
                return head + ("!" if sep == "! " else ""), rest
        return "", text

    def _toast_parts(self, e, col):
        def make():
            h = self.T_H
            badge = gfx.face(h, h, 20, col, light=0.25, dark=0.12, rim=0.5).copy()
            code = (e.icon or "!").upper()
            glyph = BADGE_GLYPHS.get(code)
            if glyph:
                _shape(badge, glyph, h // 2, h // 2 + (2 if glyph != "arrow" else 0), 24, 0, DARK_INK, col)
            else:
                label = "x2" if code == "2X" else code[:4]
                t = self._render("display", 34 if len(label) <= 2 else 26 if len(label) == 3 else 22, label, DARK_INK)
                badge.blit(t, t.get_rect(center=(h // 2, h // 2 + 1)))
            kicker, body = self._split_kicker(e.text)
            ink_k = mix(col, INK, 0.2)
            ks = gfx.tracked(self.fonts.get("black", 30), kicker, ink_k, 2) if kicker else None
            room = CW - h - 70 - (ks.get_width() + 16 if ks else 0)
            bs = self._fit_name(body, 32, INK, room, kind="black")
            tw = (ks.get_width() + 16 if ks else 0) + bs.get_width()
            pw = tw + 64
            panel = gfx.glass(pw, h - 8, 18, tint=(22, 24, 84), alpha=238, edge=col, edge_alpha=110).copy()
            x = 40
            if ks:
                panel.blit(ks, ks.get_rect(midleft=(x, (h - 8) // 2)))
                x += ks.get_width() + 16
            panel.blit(bs, bs.get_rect(midleft=(x, (h - 8) // 2 + 1)))
            return badge, panel
        return self._ucache(("toast2", e.text, col, e.icon), make)

    def _announce(self, e, a, cy, leave=0.0):
        """One toast at a seconds into its life; leave (0..1) forces its exit early."""
        col = tuple(e.color[:3])
        badge, panel = self._toast_parts(e, col)
        h = self.T_H
        pw = panel.get_width()
        total = h - 22 + pw
        x0 = W // 2 - total // 2
        out = max(leave, progress(a, TOAST_LIFE - 0.45, 0.4))
        unroll = out_expo(progress(a, 0.12, 0.45)) * (1 - in_cubic(clamp01(out * 1.6)))
        drop = out_back(progress(a, 0.0, 0.35), 1.6)
        lift = in_cubic(progress(out, 0.45, 0.55))
        by = int(cy - h // 2 - (1 - drop) * 70 - lift * 90)
        if unroll > 0.01:
            vis = int(pw * unroll)
            px, py = x0 + h - 22, cy - (h - 8) // 2
            self.screen.blit(panel, (px, py), (0, 0, vis, panel.get_height()))
            life = clamp01(1 - a / TOAST_LIFE)
            if vis > 40 and life > 0:
                self.screen.fill(col, (px + 22, py + panel.get_height() - 7, int((min(vis, pw) - 40) * life), 3))
            if 0.45 < a < 1.2:
                gfx.sweep(self.screen, gfx.silhouette(panel, ("toast", e.text)), px, py, progress(a, 0.45, 0.6), 110)
        if lift < 1:
            self.screen.blit(badge, (x0, by))

    def _v_toast(self, logic, now):
        """Event toasts drop into the pip band (above the chips, never over the question). A new
        one sends the old one out first."""
        if logic.state not in (GameState.ASKING, GameState.LOCKING, GameState.REVEALING):
            return
        events = [e for e in logic.get_recent_events() if now - e.timestamp < TOAST_LIFE + 0.3]
        if not events:
            return
        e = events[-1]
        cy = 214
        prev = events[-2] if len(events) > 1 else None
        swap = 0.0
        if prev is not None and 0 <= e.timestamp - prev.timestamp < TOAST_LIFE:
            swap = 0.28   # the new tab waits until the old one has rolled up
            if now - e.timestamp < swap:
                self._announce(prev, now - prev.timestamp, cy, leave=progress(now - e.timestamp, 0, swap))
        a = now - e.timestamp - swap
        if 0 <= a < TOAST_LIFE:
            self._announce(e, a, cy)

    def _draw_player_card(self, logic, now):
        """!card: a profile card rises over the lower screen for 6 s."""
        cards = [(u, t) for u, t in logic.cards if 0 <= now - t < self.CARD_TIME]
        if not cards:
            return
        user, t = cards[0]
        a = now - t
        p = spring(a / 0.7) * (1 - in_out_cubic(progress(a, self.CARD_TIME - 0.4, 0.4)))
        player = logic.db._players.get(user)
        if player is None or p <= 0:
            return
        w, h = CW, 330
        x = M
        y = int(lerp(H + 40, 1100, p))
        self._btn_shadow(x, y, w, h)
        self.screen.blit(gfx.glass(w, h, 28, tint=(30, 36, 110), alpha=245, edge=ACCENT, edge_alpha=230), (x, y))
        self._avatar(user, x + 90, y + 90, 56, ACCENT)
        self._blit(self._fit_name(user, 44, INK, w - 200, kind="black"), (x + 170, y + 68), "midleft")
        self._text("bold", 30, f"LV {player.level}  ·  {player.rank}", ACCENT, (x + 170, y + 116), "midleft")
        pos = logic.db.weekly_rank(user)
        stats = [("THIS WEEK", f"#{pos}" if pos else "-"), ("DAY STREAK", str(player.day_streak)),
                 ("DUELS W-L", f"{player.duel_wins}-{player.duel_losses}")]
        cw = (w - 60) // 3
        for i, (label, value) in enumerate(stats):
            cx = x + 30 + i * cw
            self._text("black", 22, label, DIM, (cx, y + 190))
            self._text("display", 54, value, INK, (cx, y + 220))
