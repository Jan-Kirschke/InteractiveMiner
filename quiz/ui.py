"""
The Lifelong Quiz - UI Manager
Smooth animations, easing, dark poker room aesthetic, particles, event feed.
"""

import pygame
import math
import time
import random

from quiz.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS,
    COLOR_BG_DARK, COLOR_BG_FELT, COLOR_GOLD, COLOR_AMBER,
    COLOR_CARD_BG, COLOR_CARD_BORDER, COLOR_CARD_HIGHLIGHT,
    COLOR_CORRECT, COLOR_WRONG,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_TEXT_GOLD, COLOR_TEXT_DIM,
    COLOR_TIMER_BAR, COLOR_TIMER_BAR_LOW, COLOR_HUD_BG,
    COLOR_CONNECTED, COLOR_DISCONNECTED,
    RANK_COLORS, FONT_PATH, MAX_PARTICLES,
    CHAT_FEED_DURATION,
)
from quiz.models import GameState, Player, Question, RoundResult, ThemeVoteState, GameEvent


# ==========================================
# EASING FUNCTIONS
# ==========================================
def ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def ease_out_back(t):
    c = 1.7
    return 1 + (c + 1) * ((t - 1) ** 3) + c * ((t - 1) ** 2)

def ease_out_elastic(t):
    if t == 0 or t == 1:
        return t
    return (2 ** (-10 * t)) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1

def ease_in_out_quad(t):
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2

def _alpha(value):
    """Clamp a 0-255 alpha value (guards against easing overshoot)."""
    return max(0, min(255, int(value)))

def lerp(a, b, t):
    return a + (b - a) * max(0, min(1, t))

def lerp_color(c1, c2, t):
    t = max(0, min(1, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ==========================================
# PARTICLE CLASSES
# ==========================================
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "life", "max_life", "size")

    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.vx = random.uniform(-2, 2)
        self.vy = random.uniform(-4, -1)
        self.color = color
        self.max_life = random.uniform(0.8, 2.0)
        self.life = self.max_life
        self.size = random.randint(2, 5)


class SmokeParticle:
    __slots__ = ("x", "y", "vx", "vy", "alpha", "size", "life")

    def __init__(self):
        self.x = random.uniform(0, SCREEN_WIDTH)
        self.y = random.uniform(0, SCREEN_HEIGHT)
        self.vx = random.uniform(-0.3, 0.3)
        self.vy = random.uniform(-0.15, -0.03)
        self.alpha = random.randint(4, 12)
        self.size = random.randint(50, 120)
        self.life = random.uniform(8, 20)


# ==========================================
# UI MANAGER
# ==========================================
class UIManager:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self._load_fonts()
        self._create_background()
        self._create_vignette()

        # Particles
        self.particles: list[Particle] = []
        self.smoke: list[SmokeParticle] = [SmokeParticle() for _ in range(25)]

        # Animation state
        self._state_enter_time = 0.0
        self._last_state = None
        self._leaderboard_anim_start = 0.0

        # Smooth counters
        self._displayed_answer_count = 0.0
        self._displayed_timer_frac = 1.0

        # Card glow cache
        self._glow_caches = {}

    def _load_fonts(self):
        try:
            self.font_tiny = pygame.font.Font(FONT_PATH, 18)
            self.font_small = pygame.font.Font(FONT_PATH, 22)
            self.font_medium = pygame.font.Font(FONT_PATH, 30)
            self.font_large = pygame.font.Font(FONT_PATH, 44)
            self.font_title = pygame.font.Font(FONT_PATH, 64)
            self.font_huge = pygame.font.Font(FONT_PATH, 80)
        except (FileNotFoundError, OSError):
            print("[UI] minecraft.ttf not found, using system font")
            self.font_tiny = pygame.font.SysFont("Arial", 18)
            self.font_small = pygame.font.SysFont("Arial", 22)
            self.font_medium = pygame.font.SysFont("Arial", 30)
            self.font_large = pygame.font.SysFont("Arial", 44)
            self.font_title = pygame.font.SysFont("Arial", 64)
            self.font_huge = pygame.font.SysFont("Arial", 80)

    def _create_background(self):
        """Pre-render radial gradient background."""
        self._bg_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        max_dist = math.sqrt(cx * cx + cy * cy)

        # Render at half resolution then scale up for smoothness
        half_w, half_h = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        small = pygame.Surface((half_w, half_h))
        for y in range(0, half_h, 2):
            for x in range(0, half_w, 2):
                dx = (x * 2 - cx)
                dy = (y * 2 - cy)
                dist = math.sqrt(dx * dx + dy * dy) / max_dist
                t = min(1.0, dist * 1.2)
                r = int(COLOR_BG_FELT[0] * (1 - t) + COLOR_BG_DARK[0] * t)
                g = int(COLOR_BG_FELT[1] * (1 - t) + COLOR_BG_DARK[1] * t)
                b = int(COLOR_BG_FELT[2] * (1 - t) + COLOR_BG_DARK[2] * t)
                pygame.draw.rect(small, (r, g, b), (x, y, 2, 2))
        self._bg_surface = pygame.transform.smoothscale(small, (SCREEN_WIDTH, SCREEN_HEIGHT))

    def _create_vignette(self):
        """Pre-render vignette surface."""
        self._vignette_surf = pygame.Surface(
            (SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA,
        )
        for i in range(150):
            alpha = int(100 * (1 - i / 150))
            pygame.draw.rect(self._vignette_surf, (0, 0, 0, alpha), (0, i, SCREEN_WIDTH, 1))
            pygame.draw.rect(
                self._vignette_surf, (0, 0, 0, alpha),
                (0, SCREEN_HEIGHT - 1 - i, SCREEN_WIDTH, 1),
            )
        for i in range(200):
            alpha = int(80 * (1 - i / 200))
            pygame.draw.rect(self._vignette_surf, (0, 0, 0, alpha), (i, 0, 1, SCREEN_HEIGHT))
            pygame.draw.rect(
                self._vignette_surf, (0, 0, 0, alpha),
                (SCREEN_WIDTH - 1 - i, 0, 1, SCREEN_HEIGHT),
            )

    # ------------------------------------------
    # MAIN DRAW DISPATCH
    # ------------------------------------------
    def draw(self, state: GameState, data: dict):
        if state != self._last_state:
            self._state_enter_time = time.time()
            self._last_state = state
            if state == GameState.LEADERBOARD:
                self._leaderboard_anim_start = time.time()

        dt = 1.0 / FPS

        # Background
        self.screen.blit(self._bg_surface, (0, 0))
        self._draw_smoke(dt)
        self.screen.blit(self._vignette_surf, (0, 0))

        # Smooth counters
        target_count = data.get("answer_count", 0)
        self._displayed_answer_count = lerp(
            self._displayed_answer_count, target_count, 8 * dt,
        )
        target_frac = data.get("time_fraction", 1.0)
        self._displayed_timer_frac = lerp(
            self._displayed_timer_frac, target_frac, 12 * dt,
        )

        # Phase animation
        phase_age = time.time() - self._state_enter_time
        fade = ease_out_cubic(min(1.0, phase_age / 0.6))

        if state == GameState.WAITING:
            self._draw_waiting(fade)
        elif state == GameState.ASKING:
            self._draw_asking(data, fade, phase_age)
        elif state == GameState.REVEALING:
            self._draw_revealing(data, fade, phase_age)
        elif state == GameState.LEADERBOARD:
            self._draw_leaderboard(data, fade)
        elif state == GameState.THEME_VOTE:
            self._draw_theme_vote(data, fade)

        # Event feed (right side)
        events = data.get("events", [])
        if events:
            self._draw_event_feed(events)

        # Double points banner
        if data.get("is_double_points") and state == GameState.ASKING:
            self._draw_double_points_banner(phase_age)

        # Competition alert
        alert = data.get("competition_alert", "")
        if alert and state == GameState.LEADERBOARD:
            self._draw_competition_alert(alert, phase_age)

        # HUD
        self._draw_hud(data)

        # Particles
        self._update_and_draw_particles(dt)

        pygame.display.flip()

    # ------------------------------------------
    # SMOKE
    # ------------------------------------------
    def _draw_smoke(self, dt):
        for i, s in enumerate(self.smoke):
            s.x += s.vx
            s.y += s.vy
            s.life -= dt
            if s.life <= 0 or s.y < -s.size:
                self.smoke[i] = SmokeParticle()
                continue
            surf = pygame.Surface((s.size * 2, s.size * 2), pygame.SRCALPHA)
            pygame.draw.circle(
                surf, (60, 55, 45, s.alpha),
                (s.size, s.size), s.size,
            )
            self.screen.blit(surf, (int(s.x - s.size), int(s.y - s.size)))

    # ------------------------------------------
    # CARD PRIMITIVES
    # ------------------------------------------
    def _draw_card(self, rect, color=COLOR_CARD_BG, border_color=COLOR_CARD_BORDER,
                   border_width=2, radius=12, shadow=True, glow_color=None,
                   alpha=255):
        x, y, w, h = rect

        if alpha < 255:
            card_surf = pygame.Surface((w + 16, h + 16), pygame.SRCALPHA)
            off = 8
        else:
            card_surf = None
            off = 0

        target = card_surf if card_surf else self.screen
        ox = off if card_surf else x
        oy = off if card_surf else y

        # Shadow
        if shadow:
            shadow_surf = pygame.Surface((w + 8, h + 8), pygame.SRCALPHA)
            pygame.draw.rect(
                shadow_surf, (0, 0, 0, min(alpha, 50)),
                (4, 4, w, h), border_radius=radius,
            )
            if card_surf:
                card_surf.blit(shadow_surf, (off - 2, off - 2))
            else:
                self.screen.blit(shadow_surf, (x - 2, y - 2))

        # Glow
        if glow_color:
            glow_surf = pygame.Surface((w + 20, h + 20), pygame.SRCALPHA)
            pulse = 0.5 + 0.5 * math.sin(time.time() * 3.5)
            ga = int(60 * pulse)
            pygame.draw.rect(
                glow_surf, (*glow_color[:3], ga),
                (0, 0, w + 20, h + 20), border_radius=radius + 6,
            )
            if card_surf:
                card_surf.blit(glow_surf, (off - 10, off - 10))
            else:
                self.screen.blit(glow_surf, (x - 10, y - 10))

        # Body
        body_color = (*color[:3], alpha) if card_surf else color
        pygame.draw.rect(target, body_color, (ox, oy, w, h), border_radius=radius)
        if border_width > 0:
            border_c = (*border_color[:3], alpha) if card_surf else border_color
            pygame.draw.rect(
                target, border_c, (ox, oy, w, h),
                width=border_width, border_radius=radius,
            )

        if card_surf:
            self.screen.blit(card_surf, (x - off, y - off))

    def _draw_number_badge(self, num, x, y, color=COLOR_GOLD, size=36):
        # Outer ring
        pygame.draw.circle(self.screen, color, (x, y), size // 2)
        pygame.draw.circle(self.screen, (255, 255, 255), (x, y), size // 2, 2)
        # Inner number
        txt = self.font_medium.render(str(num), True, COLOR_BG_DARK)
        self.screen.blit(txt, (x - txt.get_width() // 2, y - txt.get_height() // 2))

    # ------------------------------------------
    # TEXT HELPERS
    # ------------------------------------------
    def _text_centered(self, text, font, color, y, alpha=255):
        surf = font.render(text, True, color)
        if alpha < 255:
            surf.set_alpha(alpha)
        x = (SCREEN_WIDTH - surf.get_width()) // 2
        self.screen.blit(surf, (x, y))

    def _text_shadowed(self, text, font, color, pos, shadow_offset=2):
        shadow = font.render(text, True, (0, 0, 0))
        self.screen.blit(shadow, (pos[0] + shadow_offset, pos[1] + shadow_offset))
        self.screen.blit(font.render(text, True, color), pos)

    def _wrap_text(self, text, font, max_width):
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    # ------------------------------------------
    # TIMER BAR
    # ------------------------------------------
    def _draw_timer_bar(self, fraction, rect, low_threshold=0.25):
        x, y, w, h = rect
        # Background
        pygame.draw.rect(self.screen, (20, 18, 15), (x, y, w, h), border_radius=h // 2)

        fill_w = max(0, int(w * fraction))
        if fill_w > 0:
            if fraction > low_threshold:
                color = lerp_color(COLOR_TIMER_BAR, COLOR_TIMER_BAR_LOW,
                                   1 - (fraction - low_threshold) / (1 - low_threshold))
                # Actually keep it smooth amber -> red
                color = COLOR_TIMER_BAR if fraction > 0.5 else lerp_color(
                    COLOR_TIMER_BAR_LOW, COLOR_TIMER_BAR, (fraction - low_threshold) / (0.5 - low_threshold),
                )
            else:
                pulse = 0.7 + 0.3 * math.sin(time.time() * 8)
                color = tuple(int(c * pulse) for c in COLOR_TIMER_BAR_LOW)

            pygame.draw.rect(
                self.screen, color, (x, y, fill_w, h), border_radius=h // 2,
            )
            # Bright tip
            if fill_w > 4:
                tip_color = tuple(min(255, c + 60) for c in color)
                pygame.draw.rect(
                    self.screen, tip_color,
                    (x + fill_w - 4, y + 2, 4, h - 4), border_radius=2,
                )

    # ------------------------------------------
    # WAITING STATE
    # ------------------------------------------
    def _draw_waiting(self, fade):
        alpha = _alpha(255 * fade)
        cy = SCREEN_HEIGHT // 2

        # Title with gentle bounce
        bounce = math.sin(time.time() * 1.5) * 5
        self._text_centered(
            "THE LIFELONG QUIZ", self.font_title, COLOR_GOLD,
            int(cy - 120 + bounce), alpha,
        )

        # Pulsing subtitle
        pulse = 0.4 + 0.6 * abs(math.sin(time.time() * 2))
        self._text_centered(
            "Loading questions...", self.font_medium, COLOR_TEXT_SECONDARY,
            cy - 20, int(alpha * pulse),
        )

        # Instructions
        self._text_centered(
            'Type 1-4 to answer   |   Type "reset" to clear score',
            self.font_small, COLOR_TEXT_DIM, cy + 40, alpha,
        )

    # ------------------------------------------
    # ASKING STATE
    # ------------------------------------------
    def _draw_asking(self, data, fade, phase_age):
        question: Question = data.get("question")
        time_frac = self._displayed_timer_frac
        time_rem = data.get("time_remaining", 0)
        answer_count = int(round(self._displayed_answer_count))
        category = data.get("category", "")

        if not question:
            return

        cx = SCREEN_WIDTH // 2
        card_w = 1400
        card_x = cx - card_w // 2

        # Category badge with slide-in
        slide = ease_out_cubic(min(1.0, phase_age / 0.4))
        cat_y = int(lerp(-30, 68, slide))
        diff_colors = {"easy": COLOR_CORRECT, "medium": COLOR_AMBER, "hard": COLOR_WRONG}
        diff_color = diff_colors.get(question.difficulty, COLOR_TEXT_SECONDARY)
        cat_text = f"[ {category}  -  {question.difficulty.upper()} ]"
        self._text_centered(cat_text, self.font_small, diff_color, cat_y)

        # Question card (fade + slide)
        q_card_y = 110
        q_lines = self._wrap_text(question.text, self.font_large, card_w - 80)
        q_card_h = max(140, 50 + len(q_lines) * 52)

        card_slide = ease_out_back(min(1.0, phase_age / 0.5))
        actual_y = int(lerp(q_card_y - 40, q_card_y, card_slide))

        self._draw_card(
            (card_x, actual_y, card_w, q_card_h),
            border_color=COLOR_GOLD, alpha=_alpha(255 * fade),
        )

        for i, line in enumerate(q_lines):
            self._text_centered(
                line, self.font_large, COLOR_TEXT_PRIMARY,
                actual_y + 25 + i * 52, _alpha(255 * fade),
            )

        # Answer cards (staggered entrance)
        ans_y_start = actual_y + q_card_h + 35
        ans_w = (card_w - 20) // 2
        ans_h = 130
        gap = 20

        for i, option_text in enumerate(question.options):
            col = i % 2
            row = i // 2
            ax = card_x + col * (ans_w + gap)
            ay = ans_y_start + row * (ans_h + gap)

            # Stagger animation per card
            delay = 0.3 + i * 0.08
            card_progress = ease_out_back(min(1.0, max(0, (phase_age - delay) / 0.4)))

            if card_progress <= 0:
                continue

            actual_ax = ax + int((1 - card_progress) * (100 if col == 0 else -100))
            card_alpha = _alpha(255 * card_progress)

            self._draw_card(
                (actual_ax, ay, ans_w, ans_h),
                color=COLOR_CARD_BG, border_color=COLOR_CARD_BORDER,
                alpha=card_alpha,
            )

            self._draw_number_badge(i + 1, actual_ax + 35, ay + ans_h // 2)

            opt_lines = self._wrap_text(option_text, self.font_medium, ans_w - 100)
            for j, line in enumerate(opt_lines):
                txt = self.font_medium.render(line, True, COLOR_TEXT_PRIMARY)
                txt.set_alpha(card_alpha)
                self.screen.blit(
                    txt,
                    (actual_ax + 70,
                     ay + ans_h // 2 - len(opt_lines) * 16 + j * 32),
                )

        # Timer bar (smooth)
        timer_y = ans_y_start + 2 * (ans_h + gap) + 25
        self._draw_timer_bar(time_frac, (card_x, timer_y, card_w, 24))

        time_color = COLOR_TIMER_BAR if time_frac > 0.25 else COLOR_TIMER_BAR_LOW
        self._text_centered(
            f"{int(time_rem)}s", self.font_small, time_color, timer_y + 32,
        )

        # Answer count (smooth animated number)
        self._text_centered(
            f"{answer_count} answers", self.font_small,
            COLOR_TEXT_SECONDARY, timer_y + 58,
        )

    # ------------------------------------------
    # REVEALING STATE
    # ------------------------------------------
    def _draw_revealing(self, data, fade, phase_age):
        result: RoundResult = data.get("result")
        if not result or not result.question:
            return

        question = result.question
        cx = SCREEN_WIDTH // 2
        card_w = 1400
        card_x = cx - card_w // 2

        # Question (dimmed)
        q_card_y = 80
        q_lines = self._wrap_text(question.text, self.font_large, card_w - 80)
        q_card_h = max(120, 35 + len(q_lines) * 52)
        self._draw_card(
            (card_x, q_card_y, card_w, q_card_h),
            color=(25, 22, 20), border_color=(60, 55, 45),
        )
        for i, line in enumerate(q_lines):
            self._text_centered(
                line, self.font_large, COLOR_TEXT_SECONDARY,
                q_card_y + 18 + i * 52,
            )

        # Answer cards with correct/wrong
        ans_y_start = q_card_y + q_card_h + 25
        ans_w = (card_w - 20) // 2
        ans_h = 120
        gap = 20

        for i, option_text in enumerate(question.options):
            col = i % 2
            row = i // 2
            ax = card_x + col * (ans_w + gap)
            ay = ans_y_start + row * (ans_h + gap)

            is_correct = (i == question.correct_index)

            # Reveal animation: cards flip after delay
            reveal_delay = 0.2 + i * 0.1
            reveal_progress = ease_out_cubic(
                min(1.0, max(0, (phase_age - reveal_delay) / 0.3)),
            )

            if is_correct:
                border_c = lerp_color(COLOR_CARD_BORDER, COLOR_CORRECT, reveal_progress)
                body_c = lerp_color(COLOR_CARD_BG, (30, 60, 30), reveal_progress)
                glow = COLOR_CORRECT if reveal_progress > 0.5 else None

                self._draw_card(
                    (ax, ay, ans_w, ans_h),
                    color=body_c, border_color=border_c,
                    border_width=3, glow_color=glow,
                )
                text_color = lerp_color(COLOR_TEXT_PRIMARY, COLOR_CORRECT, reveal_progress)

                # Gold particles
                if reveal_progress > 0.8 and random.random() < 0.4:
                    self._spawn_particles(
                        ax + ans_w // 2, ay + ans_h // 2,
                        COLOR_TEXT_GOLD, 2,
                    )
            else:
                dim_alpha = int(lerp(255, 100, reveal_progress))
                self._draw_card(
                    (ax, ay, ans_w, ans_h),
                    color=COLOR_CARD_BG,
                    border_color=lerp_color(COLOR_CARD_BORDER, COLOR_WRONG, reveal_progress),
                    border_width=2, alpha=dim_alpha,
                )
                text_color = lerp_color(COLOR_TEXT_PRIMARY, (100, 80, 70), reveal_progress)

            badge_color = COLOR_CORRECT if is_correct else lerp_color(
                COLOR_GOLD, (100, 60, 60), reveal_progress,
            )
            self._draw_number_badge(i + 1, ax + 35, ay + ans_h // 2, badge_color)

            opt_lines = self._wrap_text(option_text, self.font_medium, ans_w - 100)
            for j, line in enumerate(opt_lines):
                txt = self.font_medium.render(line, True, text_color)
                self.screen.blit(
                    txt,
                    (ax + 70, ay + ans_h // 2 - len(opt_lines) * 16 + j * 32),
                )

        # Result banner (slide up)
        banner_y_target = ans_y_start + 2 * (ans_h + gap) + 15
        banner_slide = ease_out_cubic(min(1.0, max(0, (phase_age - 0.6) / 0.4)))
        banner_y = int(lerp(banner_y_target + 50, banner_y_target, banner_slide))
        banner_alpha = _alpha(255 * banner_slide)

        self._draw_card(
            (card_x, banner_y, card_w, 100),
            color=(25, 35, 25), border_color=COLOR_GOLD,
            border_width=1, alpha=banner_alpha,
        )

        correct_count = len(result.correct_players)
        total = result.total_answers

        if correct_count > 0:
            self._text_centered(
                f"{correct_count} of {total} players got it right!",
                self.font_large, COLOR_CORRECT, banner_y + 8, banner_alpha,
            )
            self._text_centered(
                f"Fastest: {result.fastest_player} ({result.fastest_time:.1f}s)",
                self.font_medium, COLOR_TEXT_GOLD, banner_y + 56, banner_alpha,
            )
        else:
            self._text_centered(
                "Nobody got it right!", self.font_large,
                COLOR_WRONG, banner_y + 8, banner_alpha,
            )
            self._text_centered(
                f"The answer was: {question.correct_answer}",
                self.font_medium, COLOR_TEXT_SECONDARY,
                banner_y + 56, banner_alpha,
            )

        # Mini leaderboard (slide from left)
        top = data.get("leaderboard", [])[:5]
        if top:
            lb_slide = ease_out_cubic(min(1.0, max(0, (phase_age - 0.8) / 0.4)))
            lb_x = int(lerp(-320, 40, lb_slide))
            lb_y = 180
            lb_w = 300
            lb_h = 40 + len(top) * 42

            self._draw_card(
                (lb_x, lb_y, lb_w, lb_h),
                color=(20, 18, 15), border_color=COLOR_AMBER,
                border_width=1, alpha=_alpha(255 * lb_slide),
            )
            header = self.font_small.render("TOP 5", True, COLOR_GOLD)
            header.set_alpha(_alpha(255 * lb_slide))
            self.screen.blit(header, (lb_x + lb_w // 2 - header.get_width() // 2, lb_y + 8))

            for i, p in enumerate(top):
                py = lb_y + 40 + i * 42
                rank_color = RANK_COLORS.get(p.rank, COLOR_TEXT_SECONDARY)
                name = self.font_small.render(f"{i + 1}. {p.username[:14]}", True, COLOR_TEXT_PRIMARY)
                score = self.font_small.render(f"{p.score:,}", True, rank_color)
                name.set_alpha(_alpha(255 * lb_slide))
                score.set_alpha(_alpha(255 * lb_slide))
                self.screen.blit(name, (lb_x + 15, py))
                self.screen.blit(score, (lb_x + lb_w - score.get_width() - 15, py))

    # ------------------------------------------
    # LEADERBOARD STATE
    # ------------------------------------------
    def _draw_leaderboard(self, data, fade):
        top_players: list[Player] = data.get("leaderboard", [])
        round_count = data.get("round_count", 0)
        player_count = data.get("player_count", 0)
        elapsed = time.time() - self._leaderboard_anim_start

        cx = SCREEN_WIDTH // 2

        # Title
        title_slide = ease_out_back(min(1.0, elapsed / 0.6))
        title_y = int(lerp(-50, 55, title_slide))
        self._text_centered("THE LIFELONG QUIZ", self.font_title, COLOR_GOLD, title_y)
        self._text_centered(
            "STANDINGS", self.font_large, COLOR_AMBER,
            title_y + 75, _alpha(255 * min(1, elapsed / 0.8)),
        )

        # Table
        table_w = 1200
        table_x = cx - table_w // 2
        row_h = 62
        header_y = 195

        # Header
        header_fade = min(1.0, max(0, (elapsed - 0.3) / 0.3))
        self._draw_card(
            (table_x, header_y, table_w, 45),
            color=(25, 22, 18), border_color=COLOR_GOLD,
            border_width=1, radius=8, alpha=_alpha(255 * header_fade),
        )
        for hx, label in [
            (table_x + 30, "#"), (table_x + 80, "PLAYER"),
            (table_x + 550, "SCORE"), (table_x + 750, "STREAK"),
            (table_x + 950, "RANK"),
        ]:
            txt = self.font_small.render(label, True, COLOR_GOLD)
            txt.set_alpha(_alpha(255 * header_fade))
            self.screen.blit(txt, (hx, header_y + 10))

        # Player rows
        for i, player in enumerate(top_players):
            delay = 0.5 + i * 0.1
            row_progress = ease_out_back(min(1.0, max(0, (elapsed - delay) / 0.35)))

            if row_progress <= 0:
                continue

            ry = header_y + 55 + i * row_h
            offset_x = int((1 - row_progress) * 300)
            row_alpha = _alpha(255 * row_progress)

            row_surf = pygame.Surface((table_w, row_h - 4), pygame.SRCALPHA)

            row_color = (50, 42, 20, row_alpha) if i == 0 else (
                (35, 32, 28, row_alpha) if i % 2 == 0 else (28, 25, 22, row_alpha)
            )
            pygame.draw.rect(row_surf, row_color, (0, 0, table_w, row_h - 4), border_radius=8)

            # Rank number
            rank_text = "1" if i == 0 else str(i + 1)
            rt = self.font_medium.render(rank_text, True, COLOR_GOLD if i < 3 else COLOR_TEXT_PRIMARY)
            row_surf.blit(rt, (30, (row_h - 4) // 2 - rt.get_height() // 2))

            # Crown for #1
            if i == 0:
                crown = self.font_medium.render("♛", True, COLOR_TEXT_GOLD)
                row_surf.blit(crown, (8, (row_h - 4) // 2 - crown.get_height() // 2 - 2))

            # Username (dim bots)
            is_bot = player.username.startswith("[Bot]")
            name_color = COLOR_TEXT_DIM if is_bot else (COLOR_TEXT_GOLD if i == 0 else COLOR_TEXT_PRIMARY)
            nt = self.font_medium.render(player.username[:18], True, name_color)
            row_surf.blit(nt, (80, (row_h - 4) // 2 - nt.get_height() // 2))

            # Score
            st = self.font_medium.render(f"{player.score:,} pts", True, COLOR_GOLD)
            row_surf.blit(st, (550, (row_h - 4) // 2 - st.get_height() // 2))

            # Streak with fire indicator
            streak_text = f"x{player.streak}"
            if player.streak >= 10:
                streak_text = f"x{player.streak}"
            streak_color = (
                (255, 80, 20) if player.streak >= 10
                else COLOR_CORRECT if player.streak >= 5
                else COLOR_TEXT_SECONDARY
            )
            skt = self.font_medium.render(streak_text, True, streak_color)
            row_surf.blit(skt, (750, (row_h - 4) // 2 - skt.get_height() // 2))

            # Rank badge
            rank_color = RANK_COLORS.get(player.rank, COLOR_TEXT_SECONDARY)
            rkt = self.font_medium.render(player.rank, True, rank_color)
            row_surf.blit(rkt, (950, (row_h - 4) // 2 - rkt.get_height() // 2))

            self.screen.blit(row_surf, (table_x + offset_x, ry))

        # Footer
        footer_y = header_y + 55 + len(top_players) * row_h + 25
        footer_fade = min(1.0, max(0, (elapsed - 1.5) / 0.4))

        uptime_secs = data.get("uptime", 0)
        hours = int(uptime_secs // 3600)
        minutes = int((uptime_secs % 3600) // 60)

        self._text_centered(
            f"Rounds: {round_count}    |    Players: {player_count}    |    Uptime: {hours}h {minutes:02d}m",
            self.font_small, COLOR_TEXT_SECONDARY, footer_y,
            _alpha(255 * footer_fade),
        )
        self._text_centered(
            'Type 1-4 to answer  |  Type "reset" to clear your score',
            self.font_small, COLOR_TEXT_DIM, footer_y + 35,
            _alpha(255 * footer_fade),
        )

    # ------------------------------------------
    # THEME VOTE STATE
    # ------------------------------------------
    def _draw_theme_vote(self, data, fade):
        vote_state: ThemeVoteState = data.get("vote_state")
        time_frac = self._displayed_timer_frac
        time_rem = data.get("time_remaining", 0)

        if not vote_state:
            return

        cx = SCREEN_WIDTH // 2
        card_w = 1400
        card_x = cx - card_w // 2
        phase_age = time.time() - self._state_enter_time

        # Title
        title_slide = ease_out_back(min(1.0, phase_age / 0.5))
        self._text_centered(
            "VOTE FOR THE NEXT CATEGORY!",
            self.font_title, COLOR_GOLD,
            int(lerp(-50, 70, title_slide)),
        )
        self._text_centered(
            "Type 1-4 in chat to vote", self.font_medium,
            COLOR_TEXT_SECONDARY, 150, _alpha(255 * fade),
        )

        # Category cards
        ans_w = (card_w - 20) // 2
        ans_h = 180
        gap = 20
        y_start = 210

        counts = vote_state.vote_counts()
        total = max(1, vote_state.total_votes())
        leading = vote_state.leading_option()

        for opt_num, (cat_id, cat_name) in vote_state.options.items():
            i = opt_num - 1
            col = i % 2
            row = i // 2
            ax = card_x + col * (ans_w + gap)
            ay = y_start + row * (ans_h + gap)

            # Stagger
            delay = 0.2 + i * 0.1
            prog = ease_out_back(min(1.0, max(0, (phase_age - delay) / 0.4)))
            if prog <= 0:
                continue

            actual_ax = ax + int((1 - prog) * (120 if col == 0 else -120))
            alpha = _alpha(255 * prog)

            is_leading = (opt_num == leading and total > 1)
            glow = COLOR_GOLD if is_leading else None
            border_c = COLOR_GOLD if is_leading else COLOR_CARD_BORDER

            self._draw_card(
                (actual_ax, ay, ans_w, ans_h),
                color=COLOR_CARD_BG, border_color=border_c,
                border_width=3 if is_leading else 2,
                glow_color=glow, alpha=alpha,
            )

            self._draw_number_badge(opt_num, actual_ax + 40, ay + 50)

            name_color = COLOR_TEXT_GOLD if is_leading else COLOR_TEXT_PRIMARY
            txt = self.font_large.render(cat_name, True, name_color)
            txt.set_alpha(alpha)
            self.screen.blit(txt, (actual_ax + 80, ay + 28))

            # Vote bar
            vote_count = counts.get(opt_num, 0)
            bar_x = actual_ax + 30
            bar_y = ay + ans_h - 55
            bar_w = ans_w - 140
            bar_h = 20

            pygame.draw.rect(
                self.screen, (20, 18, 15),
                (bar_x, bar_y, bar_w, bar_h), border_radius=bar_h // 2,
            )
            if vote_count > 0:
                fill_frac = vote_count / total
                fill_w = max(bar_h, int(bar_w * fill_frac))
                bar_color = COLOR_GOLD if is_leading else COLOR_AMBER
                pygame.draw.rect(
                    self.screen, bar_color,
                    (bar_x, bar_y, fill_w, bar_h), border_radius=bar_h // 2,
                )

            vt = self.font_small.render(f"{vote_count} votes", True, COLOR_TEXT_SECONDARY)
            vt.set_alpha(alpha)
            self.screen.blit(vt, (bar_x + bar_w + 10, bar_y - 2))

        # Timer
        timer_y = y_start + 2 * (ans_h + gap) + 15
        self._draw_timer_bar(time_frac, (card_x, timer_y, card_w, 24))

        time_color = COLOR_TIMER_BAR if time_frac > 0.25 else COLOR_TIMER_BAR_LOW
        self._text_centered(f"{int(time_rem)}s", self.font_small, time_color, timer_y + 32)
        self._text_centered(
            f"{vote_state.total_votes()} votes cast",
            self.font_small, COLOR_TEXT_SECONDARY, timer_y + 58,
        )

    # ------------------------------------------
    # EVENT FEED (right side)
    # ------------------------------------------
    def _draw_event_feed(self, events: list[GameEvent]):
        now = time.time()
        x = SCREEN_WIDTH - 420
        base_y = 80

        for i, event in enumerate(events):
            age = now - event.timestamp
            # Fade in then fade out
            if age < 0.3:
                alpha = ease_out_cubic(age / 0.3)
            elif age > CHAT_FEED_DURATION - 1.0:
                alpha = max(0, (CHAT_FEED_DURATION - age))
            else:
                alpha = 1.0

            if alpha <= 0:
                continue

            y = base_y + i * 38
            # Slide in from right
            slide = ease_out_cubic(min(1.0, age / 0.3))
            ax = int(lerp(x + 100, x, slide))

            # Background card
            card_surf = pygame.Surface((400, 32), pygame.SRCALPHA)
            pygame.draw.rect(
                card_surf, (15, 12, 10, int(180 * alpha)),
                (0, 0, 400, 32), border_radius=6,
            )
            self.screen.blit(card_surf, (ax, y))

            # Icon badge
            if event.icon:
                badge = self.font_tiny.render(event.icon, True, event.color)
                badge.set_alpha(_alpha(255 * alpha))
                self.screen.blit(badge, (ax + 8, y + 7))

            # Text
            txt = self.font_tiny.render(event.text[:45], True, event.color)
            txt.set_alpha(_alpha(255 * alpha))
            self.screen.blit(txt, (ax + 55, y + 7))

    # ------------------------------------------
    # DOUBLE POINTS BANNER
    # ------------------------------------------
    def _draw_double_points_banner(self, phase_age):
        pulse = 0.7 + 0.3 * math.sin(time.time() * 4)
        alpha = int(220 * pulse)

        banner_surf = pygame.Surface((400, 50), pygame.SRCALPHA)
        pygame.draw.rect(
            banner_surf, (80, 60, 0, alpha),
            (0, 0, 400, 50), border_radius=10,
        )
        pygame.draw.rect(
            banner_surf, (255, 215, 0, alpha),
            (0, 0, 400, 50), width=2, border_radius=10,
        )
        self.screen.blit(banner_surf, (SCREEN_WIDTH // 2 - 200, 35))

        txt = self.font_medium.render("DOUBLE POINTS!", True, COLOR_TEXT_GOLD)
        txt.set_alpha(alpha)
        self.screen.blit(
            txt,
            (SCREEN_WIDTH // 2 - txt.get_width() // 2, 43),
        )

    # ------------------------------------------
    # COMPETITION ALERT
    # ------------------------------------------
    def _draw_competition_alert(self, alert_text, phase_age):
        if not alert_text:
            return

        delay = 2.0
        if phase_age < delay:
            return

        prog = ease_out_cubic(min(1.0, (phase_age - delay) / 0.5))
        alpha = _alpha(255 * prog)

        top_players = []  # shown in leaderboard section
        footer_y = 870

        # Pulsing alert
        pulse = 0.8 + 0.2 * math.sin(time.time() * 3)
        final_alpha = int(alpha * pulse)

        self._text_centered(
            f"CLOSE RACE: {alert_text}",
            self.font_medium, COLOR_AMBER, footer_y - 30, final_alpha,
        )

    # ------------------------------------------
    # HUD
    # ------------------------------------------
    def _draw_hud(self, data):
        bar_h = 48
        hud_surf = pygame.Surface((SCREEN_WIDTH, bar_h), pygame.SRCALPHA)
        pygame.draw.rect(hud_surf, (*COLOR_HUD_BG, 210), (0, 0, SCREEN_WIDTH, bar_h))
        self.screen.blit(hud_surf, (0, 0))
        pygame.draw.line(
            self.screen, (40, 35, 30), (0, bar_h), (SCREEN_WIDTH, bar_h), 1,
        )

        y = 12
        # Round
        self._text_shadowed(
            f"Round #{data.get('round_count', 0)}",
            self.font_small, COLOR_TEXT_PRIMARY, (20, y),
        )

        # Category
        cat = data.get("category", "")
        ct = self.font_small.render(f"Category: {cat}", True, COLOR_AMBER)
        self.screen.blit(ct, (SCREEN_WIDTH // 2 - ct.get_width() // 2, y))

        # Right side HUD: Players | STREAM | CHAT status
        # Layout from right to left with proper spacing

        # Player count (rightmost group, left side)
        pc = data.get("player_count", 0)
        self._text_shadowed(
            f"{pc} Players", self.font_small, COLOR_TEXT_SECONDARY,
            (SCREEN_WIDTH - 580, y),
        )

        # Broadcast status (STREAM indicator)
        broadcasting = data.get("broadcasting", False)
        stream_color = COLOR_CONNECTED if broadcasting else COLOR_DISCONNECTED
        pygame.draw.circle(self.screen, stream_color, (SCREEN_WIDTH - 470, y + 10), 6)
        stream_label = "STREAM" if broadcasting else "NO STREAM"
        st = self.font_small.render(stream_label, True, stream_color)
        self.screen.blit(st, (SCREEN_WIDTH - 458, y))

        # Chat connection status (detailed, shows status text)
        connected = data.get("connected", False)
        chat_status = data.get("chat_status", "")
        chat_msgs = data.get("chat_msg_count", 0)
        chat_color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        pygame.draw.circle(self.screen, chat_color, (SCREEN_WIDTH - 330, y + 10), 6)
        if connected:
            chat_label = f"CHAT ({chat_msgs} msgs)"
        else:
            chat_label = chat_status if chat_status else "NO CHAT"
        if len(chat_label) > 35:
            chat_label = chat_label[:33] + ".."
        ct2 = self.font_small.render(chat_label, True, chat_color)
        self.screen.blit(ct2, (SCREEN_WIDTH - 318, y))

    # ------------------------------------------
    # PARTICLES
    # ------------------------------------------
    def _spawn_particles(self, x, y, color, count):
        for _ in range(count):
            if len(self.particles) < MAX_PARTICLES:
                self.particles.append(Particle(x, y, color))

    def spawn_celebration(self, x, y):
        for _ in range(40):
            if len(self.particles) < MAX_PARTICLES:
                p = Particle(x, y, COLOR_TEXT_GOLD)
                p.vx = random.uniform(-6, 6)
                p.vy = random.uniform(-10, -3)
                p.size = random.randint(3, 7)
                self.particles.append(p)

    def _update_and_draw_particles(self, dt):
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += 4 * dt  # gravity
            p.x += p.vx
            p.y += p.vy
            frac = p.life / p.max_life
            alpha = _alpha(255 * frac)
            size = max(1, int(p.size * (0.5 + 0.5 * frac)))

            surf = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            pygame.draw.circle(
                surf, (*p.color[:3], alpha), (size, size), size,
            )
            self.screen.blit(surf, (int(p.x - size), int(p.y - size)))
            alive.append(p)
        self.particles = alive
