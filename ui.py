import pygame
import random


from config import WIDTH, HEIGHT
from utils import safe_load_img



class AnnouncementSystem:
    def __init__(self):
        self.queue = []
        self.current = None

    def add(self, text, subtext="", duration=180, color=(255, 255, 255)):
        self.queue.append({"text": text, "subtext": subtext, "timer": duration, "max_timer": duration, "color": color})

    def update(self):
        if self.current:
            self.current['timer'] -= 1
            if self.current['timer'] <= 0:
                self.current = None
        if not self.current and self.queue:
            self.current = self.queue.pop(0)

    def draw(self, screen, mega_font, big_font):
        if not self.current: return
        ann = self.current
        t = ann['timer']; mt = ann['max_timer']
        if t > mt - 30: alpha = int((mt - t) / 30 * 255)
        elif t < 30: alpha = int(t / 30 * 255)
        else: alpha = 255

        text_surf = mega_font.render(ann['text'], True, ann['color'])
        text_surf.set_alpha(alpha)
        # HINWEIS: Benötigt globale Konstante WIDTH
        x = (WIDTH - text_surf.get_width()) // 2
        # HINWEIS: Benötigt globale Konstante HEIGHT
        y = HEIGHT // 3
        screen.blit(text_surf, (x, y))

        if ann['subtext']:
            sub_surf = big_font.render(ann['subtext'], True, (200, 200, 200))
            sub_surf.set_alpha(alpha)
            sx = (WIDTH - sub_surf.get_width()) // 2
            screen.blit(sub_surf, (sx, y + text_surf.get_height() + 10))

class Atmosphere:
    def __init__(self, width, height, load_img_func):
        self.width = width
        self.height = height
        # load_img_func wird beim Erstellen übergeben (z.B. safe_load_img aus utils.py oder dem main script)
        self.frame_surf = load_img_func("assets/images/overlay.png", (width, height), (0,0,0,0))
        self.fog_surf = pygame.Surface((width, 200), pygame.SRCALPHA)
        for y in range(200):
            alpha = int((y / 200) * 255)
            pygame.draw.line(self.fog_surf, (0, 0, 0, alpha), (0, y), (width, y))

    def draw_foreground(self, screen):
        screen.blit(self.fog_surf, (0, self.height - 200))
        screen.blit(self.frame_surf, (0, 0))

class LikeStreakSystem:
    def __init__(self):
        self.streak = 0; self.max_time = 180; self.current_time = 0
        self.multiplier = 1.0; self.active = False
        self.bar_width = 300; self.bar_height = 15
        self.tier = 0

    def add_like(self):
        self.streak += 1; self.current_time = self.max_time; self.active = True
        self.multiplier = min(5.0, 1.0 + (self.streak * 0.1))
        if self.streak >= 50: self.tier = 3
        elif self.streak >= 25: self.tier = 2
        elif self.streak >= 10: self.tier = 1
        else: self.tier = 0

    def update(self):
        if self.active:
            self.current_time -= 1
            if self.current_time <= 0:
                self.active = False; self.streak = 0; self.multiplier = 1.0; self.tier = 0

    def draw(self, screen):
        if not self.active and self.streak == 0: return
        # HINWEIS: Benötigt globale Konstante WIDTH
        x = (WIDTH - self.bar_width) // 2; y = 220
        font = pygame.font.SysFont("Arial", 18, bold=True)
        tier_labels = ["", "SUPER ", "EPIC ", "LEGENDARY "]
        tier_colors = [(255, 255, 255), (0, 255, 255), (200, 100, 255), (255, 215, 0)]
        col = tier_colors[self.tier]
        label = tier_labels[self.tier]
        txt = font.render(f"{label}STREAK: {self.streak} (x{self.multiplier:.1f} DMG)", True, col)
        shake = random.randint(-2, 2) if self.tier >= 2 else (random.randint(-1, 1) if self.multiplier > 3 else 0)
        screen.blit(txt, (x + shake, y - 22))
        pygame.draw.rect(screen, (50, 50, 50), (x, y, self.bar_width, self.bar_height))
        pct = self.current_time / self.max_time
        bar_col = col if self.tier > 0 else ((0, 255, 0) if pct > 0.5 else ((255, 165, 0) if pct > 0.2 else (255, 0, 0)))
        pygame.draw.rect(screen, bar_col, (x, y, int(self.bar_width * pct), self.bar_height))
        pygame.draw.rect(screen, (255, 255, 255), (x, y, self.bar_width, self.bar_height), 2)

class FloatingText:
    def __init__(self, x, y, text, color=(255, 255, 255), size=24):
        self.x = x; self.y = y; self.text = text; self.color = color
        self.font = pygame.font.SysFont("assets/fonts/minecraft.ttf", size, bold=True)
        self.life = 60; self.vel_y = -2.0
    def update(self): self.y += self.vel_y; self.life -= 1
    def draw(self, screen):
        if self.life > 0:
            surf = self.font.render(str(self.text), True, self.color)
            surf.set_alpha(min(255, self.life*5))
            screen.blit(surf, (self.x, self.y))