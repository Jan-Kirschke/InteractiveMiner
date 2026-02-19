import pygame
import random
from config import *
from utils import safe_load_img
from ui import FloatingText

class Particle:
    def __init__(self, x, y, color):
        self.rect = pygame.Rect(x, y, 6, 6)
        self.color = color
        self.vel_x = random.uniform(-4, 4); self.vel_y = random.uniform(-4, 4)
        self.gravity = 0.5; self.life = random.randint(20, 40); self.max_life = self.life
    def update(self):
        self.vel_y += self.gravity; self.rect.x += self.vel_x; self.rect.y += self.vel_y; self.life -= 1
    def draw(self, screen):
        if self.life > 0:
            s = pygame.Surface((6,6), pygame.SRCALPHA)
            alpha = int((self.life/self.max_life)*255)
            s.fill((*self.color, alpha))
            screen.blit(s, self.rect)

class Block:
    def __init__(self, x, y, type_name, image, hp, is_bedrock=False):
        self.rect = pygame.Rect(x, y, BLOCK_SIZE, BLOCK_SIZE)
        self.type = type_name; self.image = image
        self.max_hp = hp; self.hp = hp
        self.active = True; self.is_bedrock = is_bedrock

class HeroPickaxe:
    def __init__(self, x, y, image):
        self.image = image; self.original_image = image
        self.rect = self.image.get_rect(center=(x, y))
        self.vel_x = 0; self.vel_y = 0; self.rot_speed = 0; self.angle = 0
        self.gravity = GRAVITY; self.friction = 0.98; self.bounce = -0.4
        self.min_x = BLOCK_SIZE; self.max_x = WIDTH - BLOCK_SIZE
        self.rot_image = image
        self.display_rect = self.rect

    def apply_force(self, x, y):
        self.vel_x += x; self.vel_y += y; self.rot_speed += x * 2
        self.rot_speed = max(-15, min(15, self.rot_speed))

    def update(self, blocks, particles, sfx, texts, inventory, dmg_mult, base_damage=25):
        self.vel_y += self.gravity; self.vel_x *= self.friction

        self.rect.x += self.vel_x
        self.check_collision(blocks, particles, sfx, texts, inventory, 'x', dmg_mult, base_damage)

        self.rect.y += self.vel_y
        self.check_collision(blocks, particles, sfx, texts, inventory, 'y', dmg_mult, base_damage)

        self.rot_speed *= 0.90
        self.rot_speed = max(-12, min(12, self.rot_speed))
        self.angle = (self.angle + self.rot_speed) % 360

        scale = 1.0 + (dmg_mult - 1.0) * 0.2
        try:
            scaled_img = pygame.transform.scale(self.original_image, (int(BLOCK_SIZE*scale), int(BLOCK_SIZE*scale)))
            self.rot_image = pygame.transform.rotate(scaled_img, self.angle)
            self.display_rect = self.rot_image.get_rect(center=self.rect.center)
        except: pass

        if self.rect.left < self.min_x: self.rect.left = self.min_x; self.vel_x *= -0.5; self.rot_speed *= -0.3
        if self.rect.right > self.max_x: self.rect.right = self.max_x; self.vel_x *= -0.5; self.rot_speed *= -0.3

    def check_collision(self, blocks, particles, sfx, texts, inventory, axis, dmg_mult, base_damage=25):
        for b in blocks:
            if b.active and not b.is_bedrock and self.rect.colliderect(b.rect):
                force = abs(self.vel_x) if axis == 'x' else abs(self.vel_y)
                if force > 2:
                    dmg = base_damage * dmg_mult
                    b.hp -= dmg; sfx.play()
                    if dmg_mult > 1.5: texts.append(FloatingText(b.rect.x, b.rect.y, f"{int(dmg)}!", (255, 215, 0)))

                    p_col = BLOCK_PARTICLE_COLORS.get(b.type, (100, 100, 100))
                    p_col = tuple(max(0, min(255, c + random.randint(-20, 20))) for c in p_col)
                    count = 5 if "ore" in b.type else 3
                    if len(particles) < MAX_PARTICLES:
                        for _ in range(count): particles.append(Particle(self.rect.centerx, self.rect.centery, p_col))

                    if axis == 'x':
                        if self.vel_x > 0: self.rect.right = b.rect.left
                        else: self.rect.left = b.rect.right
                        self.vel_x *= -0.5
                        self.rot_speed *= -0.3
                    else:
                        if self.vel_y > 0: self.rect.bottom = b.rect.top; self.vel_y *= self.bounce; self.vel_x *= 0.9
                        else: self.rect.top = b.rect.bottom; self.vel_y *= -0.5
                        self.rot_speed *= -0.3

    def draw(self, screen): screen.blit(self.rot_image, self.display_rect)

class PhysicsAnvil:
    def __init__(self, x):
        self.rect = pygame.Rect(x, -100, 60, 80); self.vel_y = 0; self.active = True
        self.img = safe_load_img("assets/images/anvil.png", (60, 80), (80, 80, 80))
    def update(self, bosses):
        self.vel_y += 1.5; self.rect.y += self.vel_y
        for b in bosses:
            if self.rect.colliderect(b.rect): self.active = False; return b
        if self.rect.y > HEIGHT: self.active = False
        return None
    def draw(self, s): s.blit(self.img, self.rect)

class PhysicsPotion:
    def __init__(self, x):
        self.rect = pygame.Rect(x, -50, 30, 40); self.vel_y = 0; self.active = True
        self.img = safe_load_img("assets/images/potion.png", (30, 40), (255, 50, 50))
    def update(self, bosses):
        self.vel_y += 0.8; self.rect.y += self.vel_y
        
        # Lokaler Import, um Zirkelbezug mit bosses.py zu vermeiden
        from bosses import HerobrineBoss 
        
        for b in bosses:
            if isinstance(b, HerobrineBoss) and self.rect.colliderect(b.rect): self.active = False; return b
        if self.rect.y > HEIGHT: self.active = False
        return None
    def draw(self, s): s.blit(self.img, self.rect)

class BombEntity:
    def __init__(self, x, type="x"):
        self.rect = pygame.Rect(x, -50, 64, 64); self.type = type; self.vel_y = -5; self.timer = 60; self.explode = False
        self.img = safe_load_img(f"assets/images/tnt_{type}.png", (64, 64), (255, 0, 0))
    def update(self):
        self.vel_y += 0.5; self.rect.y += self.vel_y; self.timer -= 1
        if self.timer <= 0: self.explode = True
    def draw(self, s): s.blit(self.img, self.rect)

class LightningEntity:
    def __init__(self, x): self.x = x; self.timer = 20; self.rect = pygame.Rect(x-20, 0, 40, HEIGHT); self.explode=False
    def update(self):
        self.timer -= 1
        if self.timer == 10: self.explode = True
    def draw(self, s):
        if self.timer > 0:
            pts = [(self.x+random.randint(-10,10), y) for y in range(0, HEIGHT, 20)]
            if len(pts)>1: pygame.draw.lines(s, (200,255,255), False, pts, 5)