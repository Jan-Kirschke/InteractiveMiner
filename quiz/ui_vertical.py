"""
The Lifelong Quiz - vertical (9:16) show for YouTube Shorts and phones
Same look and primitives as the TV layout (quiz/ui.py), composed for a phone held upright:
one column, big type, four full-width answer buttons. Everything that matters sits between
y=190 and y=1500, clear of the Shorts overlays (top bar; title, chat and buttons at the bottom).
"""

import math
import random
import time

import pygame

from quiz.config import SCREEN_WIDTH as W, SCREEN_HEIGHT as H, MATCH_LENGTH, REVEAL_AT
from quiz.logic import is_bot
from quiz.models import GameState
from quiz.ui import (
    UIManager, ACCENT, BAD, DARK_INK, DIFF_COLORS, DIM, EVENT_STYLE, FAINT, GOOD, INK, OPTION_COLORS, TRACK,
    reveal_lines, round_style, winners_title, clamp01, ease_in_out, ease_out_back, ease_out_cubic, heartbeat, lerp, mix, progress,
)

M = 56                 # side margin
CW = W - 2 * M         # content width
SAFE_BOTTOM = 1500     # below this, Shorts draws the title and live chat over the video


class VerticalUI(UIManager):
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
        self.fx.cue(logic, now)

        self._draw_stage(now, dt)
        if state == GameState.INTRO:
            self._draw_intro(logic, age)
        else:
            self._v_header(logic, status, now)
            if state == GameState.LOBBY:
                self._v_lobby(logic, age, dt)
            elif state in (GameState.ASKING, GameState.LOCKING):
                self._v_question(logic, age, now)
                self._draw_toast(logic, now)
            elif state == GameState.REVEALING:
                self._v_reveal(logic, age)
            elif state == GameState.PODIUM:
                self._v_podium(logic, age)
            else:
                self._text("display", 96, "THE LIFELONG", ACCENT, (W // 2, 760), "center")
                self._text("display", 96, "QUIZ", ACCENT, (W // 2, 870), "center")
            self._draw_player_card(logic, now)
        self.fx.draw(self.screen, now)
        self._draw_confetti(dt)
        pygame.display.flip()

    # ------------------------------------------
    # HEADER: brand, match pips, live count
    # ------------------------------------------
    def _v_header(self, logic, status, now):
        self._text("display", 56, "THE LIFELONG QUIZ", ACCENT, (W // 2, 112), "center")
        cy = 182
        in_match = logic.state not in (GameState.LOBBY, GameState.WAITING)
        if in_match:
            pw, g = 58, 12
            x = (W - MATCH_LENGTH * pw - (MATCH_LENGTH - 1) * g) // 2
            for i in range(MATCH_LENGTH):
                live_pip = i == logic.q_index - 1 and logic.state in (GameState.ASKING, GameState.LOCKING)
                if i < len(logic.pips):
                    col = GOOD if logic.pips[i] == "done" else BAD
                elif live_pip:
                    col = mix(TRACK, ACCENT, 0.5 + 0.5 * math.sin(now * 6))
                else:
                    col = TRACK
                pygame.draw.rect(self.screen, col, (x, cy - 8, pw, 16), border_radius=8)
                x += pw + g
        else:
            self._text("black", 30, f"MATCH {logic.match_no}  -  LOBBY", INK, (W // 2, cy), "center")
        if not status.get("connected"):
            self._text("black", 24, "CHAT OFFLINE", BAD, (W // 2, cy + 34), "center")

    def _chip(self, x, y, text, color, filled=False):
        surf = self._render_name(text, 30, DARK_INK if filled else color, kind="black")
        w = surf.get_width() + 44
        if filled:
            self.screen.blit(self._alpha_rect(w, 56, (*color, 255), 28), (x, y))
        else:
            self._panel(x, y, w, 56, radius=28, border=(*color, 255))
        self._blit(surf, (x + 22, y + 28), "midleft")
        return w

    def _chips(self, logic, q, y, revealed=False):
        items = [(q.category.upper(), INK, False), (q.difficulty.upper(), DIFF_COLORS.get(q.difficulty, DIM), False)]
        ev = "final" if logic.is_double_points else logic.mini_event
        filled = []
        if ev in EVENT_STYLE:
            filled.append((*EVENT_STYLE[ev], True))
        rs = round_style(q, revealed)
        if rs:
            filled.append((*rs[:2], True))
        items = filled + items
        widths = [self._render_name(t, 30, INK, kind="black").get_width() + 44 for t, _, _ in items]
        while sum(widths) + 16 * (len(widths) - 1) > CW and len(items) > 1:
            # too wide: drop the category first, then the difficulty; the filled chips stay
            items.pop(len(filled) if len(items) > len(filled) else len(items) - 1)
            widths = [self._render_name(t, 30, INK, kind="black").get_width() + 44 for t, _, _ in items]
        x = (W - sum(widths) - 16 * (len(widths) - 1)) // 2
        for (text, col, filled), w in zip(items, widths):
            self._chip(x, y, text, col, filled)
            x += w + 16

    def _question_text(self, q, y, age, sizes, max_lines, color=INK, animate=True):
        lines, size = self._fit_wrap(q.text.upper(), "display", sizes, CW, max_lines)
        lh = int(size * 1.1)
        for i, line in enumerate(lines):
            p = ease_out_cubic(progress(age, 0.05 + i * 0.08, 0.4)) if animate else 1.0
            self._blit(self._render_name(line, size, color, kind="display"),
                       (W // 2, y + i * lh + (1 - p) * 30), "midtop", alpha=255 * p)
        return y + len(lines) * lh

    # ------------------------------------------
    # ANSWER BUTTONS: full width, stacked
    # ------------------------------------------
    def _v_option_rects(self, top, h, g=22):
        return [(M, top + i * (h + g), CW, h) for i in range(4)]

    def _v_option(self, i, text, rect, alpha=255, scale=1.0, dim=0.0, outline=None, lift=0, right_pad=40):
        x, y, w, h = rect
        if scale != 1.0:
            cx, cy = x + w / 2, y + h / 2
            w, h = int(w * scale), int(h * scale)
            x, y = int(cx - w / 2), int(cy - h / 2)
        y -= lift
        a = int(alpha) // 8 * 8
        col = mix(OPTION_COLORS[i], (40, 44, 90), dim)
        self.screen.blit(self._alpha_rect(w, h, (0, 0, 0, int(90 * a / 255)), 26), (x, y + 10))
        if outline:
            self.screen.blit(self._alpha_rect(w + 24, h + 24, (*outline, 70), 36), (x - 12, y - 12))
        self.screen.blit(self._alpha_rect(w, h, (*col, a), 26), (x, y))
        if outline:
            pygame.draw.rect(self.screen, outline, (x - 4, y - 4, w + 8, h + 8), width=7, border_radius=30)
        r = int(min(46, h * 0.33))
        kx, ky = x + 26 + r, y + h // 2
        knob = mix(INK, (150, 150, 170), dim)
        if a >= 160:
            pygame.draw.circle(self.screen, knob, (kx, ky), r)
            self._text("display", int(r * 1.3), str(i + 1), DARK_INK, (kx, ky), "center", alpha=a)
        tx = kx + r + 30
        lines, size = self._fit_wrap(text, "black", (58, 52, 46, 40), x + w - tx - right_pad, 2)
        lh = int(size * 1.08)
        for j, line in enumerate(lines):
            self._blit(self._render_name(line, size, mix(INK, (190, 190, 210), dim), kind="black"),
                       (tx, ky - len(lines) * lh / 2 + j * lh + lh / 2), "midleft", alpha=a)
        return (x, y, w, h)

    # ------------------------------------------
    # QUESTION (ASKING / LOCKING)
    # ------------------------------------------
    def _v_question(self, logic, age, now):
        q = logic.current_question
        if not q:
            return
        locking = logic.state == GameState.LOCKING
        q_age = now - logic.question_start_time
        self._chips(logic, q, 236)
        bottom = self._question_text(q, 326, q_age, (88, 78, 68, 60), 4)
        rs = round_style(q)
        if rs:   # the special round's rule, in its colour
            lines, size = self._fit_wrap(rs[2].upper(), "black", (38, 34), CW, 2)
            p = ease_out_cubic(progress(q_age, 0.3, 0.4))
            for j, line in enumerate(lines):
                self._text("black", size, line, rs[1], (W // 2, bottom + 22 + j * int(size * 1.2)), "midtop", alpha=255 * p)
            bottom += 22 + len(lines) * int(size * 1.2)

        tcx, tcy = W // 2, max(bottom + 110, 720)
        if not locking:
            rem = logic.time_remaining
            urgent = rem <= 5
            beat = heartbeat(math.ceil(rem) - rem) if urgent else 0.0
            self._ring(tcx, tcy, int(82 * (1 + 0.08 * beat)), 16, logic.time_fraction, BAD if urgent else ACCENT)
            self._text("display", 80, str(int(math.ceil(rem))), INK, (tcx, tcy), "center",
                       scale=1 + 0.4 * beat if urgent else 1.0)
            if urgent:
                self._draw_vignette(BAD, 0.35 + 0.65 * beat)
        else:
            p = ease_out_back(age / 0.35)
            build = clamp01(age / max(0.1, logic.state_duration))
            stamp = self._render("display", 72, "TIME'S UP", INK)
            sw, sh = stamp.get_width() + 60, stamp.get_height() + 20
            base = pygame.Surface((sw, sh), pygame.SRCALPHA)
            pygame.draw.rect(base, BAD, (0, 0, sw, sh), border_radius=18)
            base.blit(stamp, (30, 10))
            rot = pygame.transform.rotozoom(base, 6, max(0.05, lerp(2.0, 1.0, p)))
            jitter = 6 * build ** 2
            self.screen.blit(rot, rot.get_rect(center=(tcx + random.uniform(-jitter, jitter),
                                                       tcy - 14 + random.uniform(-jitter, jitter))))
            self._draw_vignette(ACCENT, 0.25 + 0.6 * build * (0.7 + 0.3 * math.sin(now * 30)))
            bar_w = 420
            bx, by = tcx - bar_w // 2, tcy + 62
            self.screen.blit(self._alpha_rect(bar_w, 12, (255, 255, 255, 40), 6), (bx, by))
            if build > 0.04:
                self.screen.blit(self._alpha_rect(int(bar_w * build), 12, (*ACCENT, 255), 6), (bx, by))

        top = tcy + 116
        n = len(q.options)   # two (true/false, higher or lower) get taller buttons
        h = min(150 if n > 2 else 200, (SAFE_BOTTOM - 70 - top - (n - 1) * 22) // max(1, n))
        for i, (opt, rect) in enumerate(zip(q.options, self._v_option_rects(top, h))):
            p = ease_out_back(progress(q_age, 0.25 + i * 0.07, 0.45))
            if p <= 0:
                continue
            self._v_option(i, opt, rect, alpha=255 * clamp01(p * 1.4), scale=lerp(0.85, 1.0, p),
                           dim=0.35 if locking else 0.0)

        # Who just locked in (newest first) under the buttons
        ly = top + n * h + (n - 1) * 22 + 44
        locked = logic.answer_count
        hint = "TYPE 1 OR 2 IN CHAT" if n == 2 else "TYPE 1, 2, 3 OR 4 IN CHAT"
        label = f"{locked} LOCKED IN" if locked else hint
        r = self._text("black", 34, label, ACCENT, (W // 2, ly), "center")
        names = [nm.replace("[Bot] ", "") for nm, _ in reversed(logic.lock_order[-3:])]
        if names:
            self._blit(self._fit_name("  -  ".join(names), 28, DIM, CW, kind="semi"), (W // 2, r.bottom + 22), "center")

    # ------------------------------------------
    # REVEAL
    # ------------------------------------------
    def _v_reveal(self, logic, age):
        res = logic.last_result
        if not res or not res.question.options:
            return
        q = res.question
        self._chips(logic, q, 236, revealed=True)
        bottom = self._question_text(q, 318, 10.0, (64, 56, 50), 3, color=DIM, animate=False)
        top = bottom + 34
        h = 118
        total = max(1, res.total_answers)
        reveal = age >= REVEAL_AT
        k = ease_out_cubic(progress(age, REVEAL_AT, 0.4))
        rects = self._v_option_rects(top, h, g=18)
        for i, (opt, rect) in enumerate(zip(q.options, rects)):
            correct = i in res.winners
            x, y, w, hh = self._v_option(i, opt, rect, dim=(0.55 * k if reveal and not correct and res.winners else 0.0),
                                         outline=INK if reveal and correct else None,
                                         lift=int(8 * k) if reveal and correct else 0, right_pad=170)
            if reveal and not correct and q.kind == "odd_one_out":
                self._strike(x + 2 * min(46, int(hh * 0.33)) + 40, x + w - 190, y + hh // 2, k)   # clear of the knob
            target = res.option_counts[i] / total if i < len(res.option_counts) else 0
            shown = target * ease_out_cubic(progress(age, 0.25, 0.9))
            bw = int(w * shown)
            if bw > 16:
                self.screen.blit(self._alpha_rect(bw, 16, (0, 0, 0, 110), 8), (x, y + hh - 16))
            self._text("display", 60, f"{int(round(shown * 100))}%", INK, (x + w - 28, y + hh // 2), "midright")
            if reveal and correct:
                flash = progress(age, REVEAL_AT, 0.6)
                if flash < 1:
                    grow = int(40 * ease_out_cubic(flash))
                    ring = pygame.Surface((w + 2 * grow, hh + 2 * grow), pygame.SRCALPHA)
                    pygame.draw.rect(ring, (*INK, int(230 * (1 - flash))), ring.get_rect(), width=7, border_radius=28 + grow // 2)
                    self.screen.blit(ring, (x - grow, y - grow))
                if "burst" not in self._burst_done and res.correct_players:
                    self._burst_done.add("burst")
                    self.burst(x + w // 2, y + hh // 2, n=70, power=0.8)

        # How many knew it, and the fact
        p = ease_out_cubic(progress(age, 1.5, 0.4))
        y = rects[len(q.options) - 1][1] + h + 36 + int((1 - p) * 30)
        head, hcol, line = reveal_lines(res)
        self._text("display", 64, head, hcol, (W // 2, y), "midtop", alpha=255 * p)
        y += 86
        lines, size = self._fit_wrap(line, "semi", (36, 32, 28), CW, 3)
        for j, part in enumerate(lines):
            self._blit(self._render_name(part, size, INK, kind="semi"), (W // 2, y + j * int(size * 1.2)), "midtop", alpha=255 * p)
        y += len(lines) * int(size * 1.2) + 28

        # Fastest right answers
        if y + 150 < SAFE_BOTTOM and not res.void:
            self._text("black", 28, winners_title(q), DIM, (W // 2, y), "midtop", alpha=255 * p)
            y += 48
            players = res.correct_players[:3]
            for i, (name, pts, t) in enumerate(players):
                pp = ease_out_back(progress(age, 1.3 + i * 0.15, 0.35))
                if pp <= 0 or y + i * 52 > SAFE_BOTTOM:
                    continue
                ry = y + i * 52
                self._blit(self._fit_name(name.replace("[Bot] ", ""), 36, INK, CW - 300, kind="black"),
                           (M + 20, ry), "topleft", alpha=255 * clamp01(pp))
                self._text("bold", 28, f"{t:.1f}s", DIM, (W - M - 150, ry + 6), "topright")
                self._text("black", 36, f"+{pts}", GOOD, (W - M - 20, ry), "topright", scale=lerp(1.6, 1.0, clamp01(pp)))
            if not players:
                self._text("bold", 32, "Nobody got this one", FAINT, (W // 2, y), "midtop")

    # ------------------------------------------
    # LOBBY
    # ------------------------------------------
    def _v_lobby(self, logic, age, dt):
        rem = logic.time_remaining
        secs = int(math.ceil(rem))
        pop = 1.0 + 0.08 * ease_out_cubic(rem - math.floor(rem)) if secs <= 10 else 1.0
        self._text("black", 34, "NEXT MATCH STARTS IN", DIM, (W // 2, 262), "center")
        self._text("display", 190, f"0:{secs:02d}", ACCENT if secs > 5 else BAD, (W // 2, 400), "center", scale=pop)
        self._text("black", 40, "VOTE THE CATEGORY: TYPE 1-4", INK, (W // 2, 540), "center")

        vs = logic.vote_state
        y = 600
        if vs:
            counts = vs.vote_counts()
            total = max(1, vs.total_votes())
            lead = vs.leading_option()
            ch, g = 124, 18
            for opt, (_, name) in vs.options.items():
                i = opt - 1
                p = ease_out_back(progress(age, 0.15 + i * 0.08, 0.45))
                if p <= 0:
                    continue
                yy = y + i * (ch + g) + int((1 - p) * 40)
                is_lead = opt == lead and vs.total_votes() > 0
                self._panel(M, yy, CW, ch, radius=24, border=(*ACCENT, 255) if is_lead else (255, 255, 255, 38))
                col = OPTION_COLORS[i]
                pygame.draw.circle(self.screen, col, (M + 66, yy + ch // 2), 42)
                self._text("display", 54, str(opt), INK, (M + 66, yy + ch // 2), "center")
                self._blit(self._fit_name(name, 46, INK, CW - 330, kind="black"), (M + 134, yy + 46), "midleft")
                target = counts.get(opt, 0) / total
                cur = self._vote_bars.get(opt, 0.0)
                cur += (target - cur) * min(1.0, dt * 6)
                self._vote_bars[opt] = cur
                bx, by, bw = M + 134, yy + 88, CW - 330
                pygame.draw.rect(self.screen, TRACK, (bx, by, bw, 16), border_radius=8)
                if cur > 0.005:
                    pygame.draw.rect(self.screen, ACCENT if is_lead else col, (bx, by, max(16, int(bw * cur)), 16), border_radius=8)
                n = counts.get(opt, 0)
                self._text("black", 34, f"{n}", INK, (W - M - 30, yy + ch // 2), "midright")
            y += 4 * ch + 3 * g + 30

        # How to play
        self.screen.blit(self._alpha_rect(CW, 150, (*ACCENT, 255), 24), (M, y))
        self._text("black", 30, "NEW HERE?", DARK_INK, (M + 30, y + 22))
        self._text("bold", 34, "Type 1, 2, 3 or 4 in chat when", DARK_INK, (M + 30, y + 62))
        self._text("bold", 34, "the question shows. That's it!", DARK_INK, (M + 30, y + 102))
        y += 180

        # This week's top players
        rows = max(0, min(5, (SAFE_BOTTOM - y - 60) // 50))
        players = logic.leaderboard[:rows]
        if rows:
            self._text("black", 30, "THIS WEEK", DIM, (M + 10, y))
            self._text("black", 30, f"{logic.active_player_count} PLAYING", DIM, (W - M - 10, y), "topright")
            for i, pl in enumerate(players):
                ry = y + 64 + i * 50
                pp = ease_out_cubic(progress(age, 0.3 + i * 0.07, 0.35))
                self._text("display", 38, str(i + 1), ACCENT if i == 0 else DIM, (M + 30, ry), "center", alpha=255 * pp)
                self._blit(self._fit_name(pl.username, 36, INK, CW - 300), (M + 80, ry), "midleft", alpha=255 * pp)
                self._text("black", 36, f"{pl.weekly_score:,}", INK, (W - M - 10, ry), "midright", alpha=255 * pp)
            if not players:
                self._text("bold", 32, "Empty so far: answer to get on it!", FAINT, (M + 10, y + 64))

    # ------------------------------------------
    # PODIUM
    # ------------------------------------------
    def _v_podium(self, logic, age):
        a = 255 * ease_out_cubic(age / 0.4)
        self._text("display", 96, f"MATCH {logic.match_no}", INK, (W // 2, 300), "center", alpha=a)
        self._text("display", 96, "WINNERS", ACCENT, (W // 2, 400), "center", alpha=a)
        self._blit(self._render_name(f"{logic.match_player_count} PLAYERS  -  {logic.match_category.upper()}",
                                     30, DIM, kind="black"), (W // 2, 476), "center")
        base_y = 1080
        bw, g = 290, 24
        x0 = (W - 3 * bw - 2 * g) // 2
        slots = [(1, x0, 200, 0.9), (0, x0 + bw + g, 260, 1.6), (2, x0 + 2 * (bw + g), 150, 0.3)]
        if not logic.podium:
            self._text("display", 70, "NO WINNER", DIM, (W // 2, base_y - 230), "center")
            self._text("bold", 34, "Type 1-4 next match and", INK, (W // 2, base_y - 150), "center")
            self._text("bold", 34, "the podium is yours", INK, (W // 2, base_y - 104), "center")
        for place, x, height, delay in slots:
            if place >= len(logic.podium):
                continue
            st = logic.podium[place]
            p = ease_out_back(progress(age, delay, 0.6))
            hh = int(height * max(0.0, p))
            top = base_y - hh
            if hh > 0:
                col = ACCENT if place == 0 else (70, 78, 170)
                pygame.draw.rect(self.screen, col, (x, top, bw, hh + 4), border_top_left_radius=24, border_top_right_radius=24)
                self._text("display", 90, str(place + 1), DARK_INK if place == 0 else INK, (x + bw // 2, top + 14), "midtop")
            np_ = ease_out_back(progress(age, delay + 0.45, 0.45))
            if np_ > 0:
                r = 60 if place == 0 else 50
                ay = int(top - 96 - r - (1 - np_) * 40)
                self._avatar(st.username, x + bw // 2, ay, r, ACCENT if place == 0 else DIM)
                if place == 0:
                    self._crown(x + bw // 2, ay - r - 24, 30, ACCENT)
                self._blit(self._fit_name(st.username, 34, INK, bw, kind="black"), (x + bw // 2, ay + r + 26), "center", alpha=255 * clamp01(np_))
                self._text("bold", 28, f"{st.points:,} pts", DIM, (x + bw // 2, ay + r + 62), "center", alpha=255 * clamp01(np_))
            if place == 0 and age >= delay + 0.5 and "podium" not in self._burst_done:
                self._burst_done.add("podium")
                self.burst(x + bw // 2, top, n=160, power=1.3)
        pygame.draw.rect(self.screen, TRACK, (M, base_y, CW, 6), border_radius=3)

        # This week's ladder with movement
        y = base_y + 50
        self._text("black", 30, "THIS WEEK'S LADDER", DIM, (M + 10, y))
        rows = max(1, min(6, (SAFE_BOTTOM - y - 40) // 50))
        for i, pl in enumerate(logic.leaderboard[:rows]):
            ry = y + 66 + i * 50
            pp = ease_out_cubic(progress(age, 1.0 + i * 0.07, 0.35))
            ch = logic.ladder_changes.get(pl.username, 0)
            mv, mc = ("NEW", GOOD) if ch is None else (f"+{ch}", GOOD) if ch > 0 else (str(ch), BAD) if ch < 0 else ("-", FAINT)
            self._text("display", 38, str(i + 1), ACCENT if i == 0 else DIM, (M + 30, ry), "center", alpha=255 * pp)
            self._text("black", 24, mv, mc, (M + 100, ry), "center", alpha=255 * pp)
            self._blit(self._fit_name(pl.username, 36, INK, CW - 380), (M + 150, ry), "midleft", alpha=255 * pp)
            self._text("black", 36, f"{pl.weekly_score:,}", INK, (W - M - 10, ry), "midright", alpha=255 * pp)

    # ------------------------------------------
    # OVERLAYS
    # ------------------------------------------
    def _draw_toast(self, logic, now):
        events = [e for e in logic.get_recent_events() if now - e.timestamp < 3.5]
        if not events:
            return
        e = events[-1]
        a = now - e.timestamp
        slide = ease_out_back(a / 0.35)
        fade = 1 - progress(a, 3.0, 0.5)
        txt = self._fit_name(e.text, 34, DARK_INK, CW - 60, kind="black")
        w = txt.get_width() + 60
        x = W // 2 - w // 2
        y = int(lerp(300, 262, slide))
        self.screen.blit(self._alpha_rect(w, 60, (*e.color[:3], int(235 * fade) // 16 * 16), 30), (x, y))
        self._blit(txt, (W // 2, y + 30), "center", alpha=255 * fade)

    def _draw_player_card(self, logic, now):
        """!card: profile card that rises over the middle of the screen for 6 s."""
        cards = [(u, t) for u, t in logic.cards if 0 <= now - t < self.CARD_TIME]
        if not cards:
            return
        user, t = cards[0]
        a = now - t
        p = ease_out_back(a / 0.45) * (1 - ease_in_out(progress(a, self.CARD_TIME - 0.4, 0.4)))
        player = logic.db._players.get(user)
        if player is None or p <= 0:
            return
        w, h = CW, 330
        x = M
        y = int(lerp(H + 20, 1100, p))
        self.screen.blit(self._alpha_rect(w, h, (0, 0, 0, 120), 28), (x, y + 12))
        self.screen.blit(self._alpha_rect(w, h, (22, 26, 88, 250), 28), (x, y))
        pygame.draw.rect(self.screen, ACCENT, (x, y, w, h), width=4, border_radius=28)
        self._avatar(user, x + 90, y + 90, 56, ACCENT)
        self._blit(self._fit_name(user, 44, INK, w - 200, kind="black"), (x + 170, y + 68), "midleft")
        self._text("bold", 30, f"LV {player.level}  -  {player.rank}", ACCENT, (x + 170, y + 116), "midleft")
        pos = logic.db.weekly_rank(user)
        stats = [("THIS WEEK", f"#{pos}" if pos else "-"), ("DAY STREAK", str(player.day_streak)),
                 ("DUELS W-L", f"{player.duel_wins}-{player.duel_losses}")]
        cw = (w - 60) // 3
        for i, (label, value) in enumerate(stats):
            cx = x + 30 + i * cw
            self._text("black", 22, label, DIM, (cx, y + 190))
            self._text("display", 54, value, INK, (cx, y + 220))
