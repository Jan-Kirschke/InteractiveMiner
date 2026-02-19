import pygame
import random
from config import *
from utils import safe_load_img

class EndermanBoss:
    def __init__(self, hp_mult=1.0):
        self.w, self.h = 100, 250
        self.x = random.randint(BLOCK_SIZE, WIDTH-BLOCK_SIZE-100); self.y = -250
        self.target_y = 150; self.rect = pygame.Rect(self.x, self.y, self.w, self.h)
        self.hp = max(3, int(3 * hp_mult)); self.max_hp = self.hp
        self.speed = 4; self.base_speed = 4; self.dir = 1
        self.repair_timer = 0; self.hit_flash = 0
        self.phase = 1; self.repair_count = 1
        self.img = safe_load_img("assets/images/enderman_boss.png", (self.w, self.h), (20, 20, 20))

    def update(self, blocks, game):
        if self.y < self.target_y: self.y += 5; self.rect.y = self.y; return

        hp_pct = self.hp / self.max_hp if self.max_hp > 0 else 0
        if hp_pct < 0.3:
            self.phase = 3; self.speed = 8; self.repair_count = 2
        elif hp_pct < 0.6:
            self.phase = 2; self.speed = 6; self.repair_count = 1
        else:
            self.phase = 1; self.speed = self.base_speed; self.repair_count = 1

        self.x += self.speed * self.dir
        if self.x < BLOCK_SIZE: self.dir = 1
        elif self.x + self.w > WIDTH - BLOCK_SIZE: self.dir = -1
        self.rect.x = self.x

        self.repair_timer += 1
        repair_speed = max(20, BOSS_REPAIR_SPEED - game.current_depth_blocks // 100)
        if self.repair_timer > repair_speed:
            self.repair_timer = 0
            repaired = 0
            for b in blocks:
                if repaired >= self.repair_count: break
                if not b.active and not b.is_bedrock and abs(b.rect.centerx - self.rect.centerx) < 150:
                    b.active = True; b.hp = b.max_hp; repaired += 1
        if self.hit_flash > 0: self.hit_flash -= 1

    def take_damage(self): self.hp -= 1; self.hit_flash = 10; return self.hp <= 0
    def draw(self, screen):
        if self.hit_flash > 0:
            mask = pygame.mask.from_surface(self.img)
            screen.blit(mask.to_surface(setcolor=(255,255,255,200), unsetcolor=(0,0,0,0)), self.rect)
        else: screen.blit(self.img, self.rect)
        pygame.draw.rect(screen, (0,0,0), (self.rect.x, self.rect.y-15, self.w, 8))
        pygame.draw.rect(screen, ENDER_PURPLE, (self.rect.x, self.rect.y-15, int(self.w*(self.hp/self.max_hp)), 8))

class HerobrineBoss:
    def __init__(self, hp_mult=1.0):
        self.w, self.h = 80, 180
        self.x = WIDTH//2; self.y = 150; self.rect = pygame.Rect(self.x, self.y, self.w, self.h)
        self.hp = max(5, int(5 * hp_mult)); self.max_hp = self.hp
        self.tp_timer = 0; self.atk_timer = 0; self.hit_flash = 0
        self.phase = 1
        self.img = safe_load_img("assets/images/herobrine.png", (self.w, self.h), (0, 150, 150))

    def update(self, blocks, game):
        hp_pct = self.hp / self.max_hp if self.max_hp > 0 else 0
        if hp_pct < 0.5:
            self.phase = 2; tp_threshold = 60; atk_threshold = 90
        else:
            self.phase = 1; tp_threshold = 120; atk_threshold = 180

        self.tp_timer += 1
        if self.tp_timer > tp_threshold:
            self.tp_timer = 0; self.x = random.randint(BLOCK_SIZE, WIDTH-BLOCK_SIZE-self.w); self.y = random.randint(50, 250)
            self.rect.x = self.x; self.rect.y = self.y; game.sfx['teleport'].play()
        self.atk_timer += 1
        if self.atk_timer > atk_threshold:
            self.atk_timer = 0; tx = random.randint(BLOCK_SIZE, WIDTH-BLOCK_SIZE)
            
            # --- SICHERHEITS-IMPORT ---
            # Sucht die LightningEntity entweder in der main.py oder (später) in entities.py
            try:
                from entities import LightningEntity
            except ImportError:
                from main import LightningEntity
            # --------------------------

            game.tnts.append(LightningEntity(tx))
            if self.phase == 2:
                tx2 = random.randint(BLOCK_SIZE, WIDTH-BLOCK_SIZE)
                game.tnts.append(LightningEntity(tx2))
        if self.hit_flash > 0: self.hit_flash -= 1

    def take_damage(self): self.hp -= 1; self.hit_flash = 10; self.tp_timer = max(0, self.tp_timer - 20); return self.hp <= 0
    def draw(self, screen):
        if self.hit_flash > 0:
            mask = pygame.mask.from_surface(self.img)
            screen.blit(mask.to_surface(setcolor=(255,255,255,200), unsetcolor=(0,0,0,0)), self.rect)
        else: screen.blit(self.img, self.rect)
        pygame.draw.rect(screen, (0,0,0), (self.rect.x, self.rect.y-15, self.w, 8))
        pygame.draw.rect(screen, (255,255,255), (self.rect.x, self.rect.y-15, int(self.w*(self.hp/self.max_hp)), 8))

def create_boss(game):
    depth = game.current_depth_blocks
    prestige = game.prestige_level
    hp_mult = 1.0 + (depth / 500) + (prestige * 2.0)
    biome_idx = game.get_current_biome_index()
    fire_biomes = [4, 9, 15]
    if biome_idx in fire_biomes or random.random() < 0.3:
        return HerobrineBoss(hp_mult)
    else:
        return EndermanBoss(hp_mult)