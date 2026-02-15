import pygame
import threading
import queue
import time
import random
import math
import sys
import scrapetube # pip install scrapetube

# --- KONFIGURATION ---
CHANNEL_ID = "HIER_DEINE_KANAL_ID_EINFUEGEN"
COLS = 9
BLOCK_SIZE = 80
WIDTH = BLOCK_SIZE * COLS
HEIGHT = 800
FPS = 60

# Balance
SCROLL_SPEED = 0.8
GRAVITY = 0.5
MOVE_FORCE = 2
JUMP_FORCE = -0
BOSS_SUMMON_REQ = 20
MAX_ACTIVE_BOSSES = 3
BOSS_REPAIR_SPEED = 60
MAX_PARTICLES = 200
BIOME_TRANSITION_ROWS = 20

# Events
EVENT_CHECK_INTERVAL = 300
EVENT_CHANCE = 0.15
EVENT_SUMMON_REQ = 30

# Farben
UI_BG = (0, 0, 0, 180)
TEXT_COLOR = (255, 255, 255)
ENDER_PURPLE = (200, 0, 255)

# Milestones
MILESTONES = [100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 5000, 10000]

# --- PICKAXE TIERS ---
PICKAXE_TIERS = [
    {"name": "Wooden Pickaxe",    "image": "wooden_pickaxe.png",    "damage": 10,  "depth_req": 0,    "ores_req": 0},
    {"name": "Stone Pickaxe",     "image": "stone_pickaxe.png",     "damage": 18,  "depth_req": 50,   "ores_req": 10},
    {"name": "Copper Pickaxe",    "image": "copper_pickaxe.png",    "damage": 25,  "depth_req": 150,  "ores_req": 30},
    {"name": "Iron Pickaxe",      "image": "iron_pickaxe.png",      "damage": 35,  "depth_req": 400,  "ores_req": 80},
    {"name": "Golden Pickaxe",    "image": "golden_pickaxe.png",    "damage": 45,  "depth_req": 800,  "ores_req": 150},
    {"name": "Diamond Pickaxe",   "image": "diamond_pickaxe.png",   "damage": 60,  "depth_req": 1200, "ores_req": 300},
    {"name": "Netherite Pickaxe", "image": "netherite_pickaxe.png", "damage": 80,  "depth_req": 1800, "ores_req": 500},
]

# --- THEMEN (BIOME) ---
THEME_CHANGE_INTERVAL = 200
THEMES = [
    {"name": "Surface", "bg": (100, 149, 237), "blocks": {"dirt": 40, "stone": 40, "coal_ore": 10, "copper_ore": 10}},
    {"name": "Limestone Cave", "bg": (180, 170, 140), "blocks": {"sandstone": 40, "limestone": 40, "iron_ore": 15, "lapis_ore": 5}},
    {"name": "Lush Jungle", "bg": (20, 50, 20), "blocks": {"moss_block": 50, "clay": 30, "emerald_ore": 10, "gold_ore": 10}},
    {"name": "Redstone Mines", "bg": (100, 20, 20), "blocks": {"stone": 40, "redstone_ore": 20, "iron_ore": 20, "diamond_ore": 5}},
    {"name": "Magma Depths", "bg": (50, 0, 0), "blocks": {"netherrack": 50, "magma": 30, "nether_gold_ore": 10, "nether_quartz_ore": 10}},
    {"name": "Amethyst Geode", "bg": (40, 0, 60), "blocks": {"calcite": 40, "amethyst_block": 50, "diamond_ore": 10}},
    {"name": "Deep Dark", "bg": (5, 10, 15), "blocks": {"deepslate": 50, "sculk": 10, "deepslate_diamond_ore": 5, "deepslate_redstone_ore": 10, "deepslate_iron_ore": 15, "deepslate_gold_ore": 10}},
    {"name": "The Core", "bg": (0, 0, 0), "blocks": {"deepslate": 30, "bedrock": 10, "deepslate_emerald_ore": 20, "deepslate_diamond_ore": 20}},
    # --- NEW BIOMES ---
    {"name": "Frozen Depths", "bg": (140, 180, 220), "blocks": {"ice": 35, "packed_ice": 30, "stone": 15, "diamond_ore": 8, "iron_ore": 12}},
    {"name": "Nether Fortress", "bg": (80, 10, 0), "blocks": {"netherrack": 30, "magma": 25, "nether_gold_ore": 20, "nether_quartz_ore": 15, "gold_ore": 10}},
    {"name": "Crystal Caverns", "bg": (60, 20, 80), "blocks": {"amethyst_block": 40, "calcite": 25, "diamond_ore": 15, "deepslate_diamond_ore": 10, "lapis_ore": 10}},
    {"name": "Emerald Kingdom", "bg": (10, 60, 20), "blocks": {"moss_block": 35, "emerald_ore": 25, "deepslate_emerald_ore": 15, "clay": 15, "gold_ore": 10}},
    {"name": "Obsidian Abyss", "bg": (5, 0, 10), "blocks": {"deepslate": 40, "bedrock": 5, "diamond_ore": 15, "deepslate_diamond_ore": 20, "coal_ore": 20}},
    {"name": "Void Rift", "bg": (0, 0, 5), "blocks": {"sculk": 45, "deepslate": 25, "deepslate_redstone_ore": 10, "deepslate_lapis_ore": 10, "amethyst_block": 10}},
    {"name": "Ancient Ruins", "bg": (70, 60, 40), "blocks": {"sandstone": 20, "stone": 15, "gold_ore": 12, "diamond_ore": 10, "emerald_ore": 10, "lapis_ore": 8, "redstone_ore": 10, "iron_ore": 15}},
    {"name": "Molten Core", "bg": (60, 5, 0), "blocks": {"magma": 40, "netherrack": 20, "deepslate": 15, "deepslate_gold_ore": 10, "deepslate_diamond_ore": 10, "nether_gold_ore": 5}},
]

# Block HP Definitionen
BLOCK_STATS = {
    "dirt": 50, "stone": 100, "sandstone": 80, "limestone": 120, "moss_block": 60, "clay": 90,
    "ice": 40, "packed_ice": 150, "netherrack": 80, "magma": 200, "calcite": 200,
    "amethyst_block": 150, "deepslate": 300, "sculk": 100, "bedrock": 999999,
    "coal_ore": 150, "copper_ore": 180, "iron_ore": 250, "gold_ore": 350, "redstone_ore": 300,
    "lapis_ore": 300, "diamond_ore": 800, "emerald_ore": 600, "nether_gold_ore": 350,
    "nether_quartz_ore": 250, "deepslate_coal_ore": 300, "deepslate_copper_ore": 350,
    "deepslate_iron_ore": 500, "deepslate_gold_ore": 700, "deepslate_redstone_ore": 600,
    "deepslate_lapis_ore": 600, "deepslate_diamond_ore": 1600, "deepslate_emerald_ore": 1200
}

# Block particle colors
BLOCK_PARTICLE_COLORS = {
    "dirt": (139, 90, 43), "stone": (128, 128, 128), "sandstone": (210, 190, 130),
    "limestone": (200, 195, 170), "moss_block": (60, 140, 50), "clay": (160, 145, 130),
    "ice": (180, 220, 255), "packed_ice": (140, 180, 230), "netherrack": (120, 40, 40),
    "magma": (220, 120, 20), "calcite": (220, 215, 200), "amethyst_block": (140, 80, 200),
    "deepslate": (60, 60, 70), "sculk": (10, 50, 60), "bedrock": (50, 50, 50),
    "coal_ore": (40, 40, 40), "copper_ore": (180, 110, 70), "iron_ore": (200, 180, 160),
    "gold_ore": (255, 215, 0), "redstone_ore": (200, 0, 0), "lapis_ore": (30, 60, 180),
    "diamond_ore": (100, 230, 230), "emerald_ore": (50, 200, 50),
    "nether_gold_ore": (255, 200, 50), "nether_quartz_ore": (230, 220, 210),
}
for _ore in ["coal","copper","iron","gold","redstone","lapis","diamond","emerald"]:
    BLOCK_PARTICLE_COLORS[f"deepslate_{_ore}_ore"] = BLOCK_PARTICLE_COLORS.get(f"{_ore}_ore", (100,100,100))

# Item icon mapping: ore block type -> item image filename
ITEM_ICON_MAP = {
    "coal_ore": "coal.png", "deepslate_coal_ore": "coal.png",
    "copper_ore": "copper_ingot.png", "deepslate_copper_ore": "copper_ingot.png",
    "iron_ore": "iron_ingot.png", "deepslate_iron_ore": "iron_ingot.png",
    "gold_ore": "gold_ingot.png", "deepslate_gold_ore": "gold_ingot.png", "nether_gold_ore": "gold_ingot.png",
    "diamond_ore": "diamond.png", "deepslate_diamond_ore": "diamond.png",
    "emerald_ore": "emerald.png", "deepslate_emerald_ore": "emerald.png",
    "redstone_ore": "redstone.png", "deepslate_redstone_ore": "redstone.png",
    "lapis_ore": "lapis_ore.png", "deepslate_lapis_ore": "lapis_ore.png",
    "nether_quartz_ore": "nether_quartz_ore.png",
}

# --- HELPER FUNKTIONEN ---
def safe_load_img(path, size=None, color=(255, 0, 255)):
    try:
        img = pygame.image.load(path).convert_alpha()
        if size: img = pygame.transform.scale(img, size)
        return img
    except (FileNotFoundError, pygame.error):
        s = pygame.Surface(size if size else (BLOCK_SIZE, BLOCK_SIZE))
        s.fill(color)
        pygame.draw.rect(s, (0,0,0), s.get_rect(), 2)
        return s

def safe_load_snd(path, vol=0.3):
    try:
        s = pygame.mixer.Sound(path)
        s.set_volume(vol)
        return s
    except (FileNotFoundError, pygame.error):
        class DummySound:
            def play(self): pass
            def set_volume(self, v): pass
        return DummySound()

# --- KLASSEN ---

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
        x = (WIDTH - text_surf.get_width()) // 2
        y = HEIGHT // 3
        screen.blit(text_surf, (x, y))

        if ann['subtext']:
            sub_surf = big_font.render(ann['subtext'], True, (200, 200, 200))
            sub_surf.set_alpha(alpha)
            sx = (WIDTH - sub_surf.get_width()) // 2
            screen.blit(sub_surf, (sx, y + text_surf.get_height() + 10))

class Atmosphere:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.frame_surf = safe_load_img("assets/images/overlay.png", (width, height), (0,0,0,0))
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
        x = (WIDTH - self.bar_width) // 2; y = 70
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

class FloatingText:
    def __init__(self, x, y, text, color=(255, 255, 255), size=24):
        self.x = x; self.y = y; self.text = text; self.color = color
        self.font = pygame.font.SysFont("Arial", size, bold=True)
        self.life = 60; self.vel_y = -2.0
    def update(self): self.y += self.vel_y; self.life -= 1
    def draw(self, screen):
        if self.life > 0:
            surf = self.font.render(str(self.text), True, self.color)
            surf.set_alpha(min(255, self.life*5))
            screen.blit(surf, (self.x, self.y))

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

# --- MAIN GAME CLASS ---

class Game:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()

        # --- YouTube Setup ---
        try:
            print("Suche Livestream...")
            vids = scrapetube.get_channel(CHANNEL_ID, content_type="streams", limit=5)
            for v in vids:
                if v.get('thumbnailOverlays') and any('LIVE' in str(o) for o in v['thumbnailOverlays']):
                    print(f"Verbunden mit: {v['videoId']}"); break
        except: print("Offline Mode / Fallback ID")

        # --- Window Setup ---
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Infinite Miner Ultimate")
        self.clock = pygame.time.Clock()

        # --- Schriften ---
        try:
            self.font = pygame.font.Font("assets/fonts/minecraft.ttf", 18)
            self.big_font = pygame.font.Font("assets/fonts/minecraft.ttf", 30)
            self.mega_font = pygame.font.Font("assets/fonts/minecraft.ttf", 50)
        except:
            self.font = pygame.font.SysFont("Arial", 16, bold=True)
            self.big_font = pygame.font.SysFont("Arial", 24, bold=True)
            self.mega_font = pygame.font.SysFont("Arial", 40, bold=True)

        # --- Listen Initialisierung ---
        self.blocks = []
        self.particles = []
        self.floating_texts = []
        self.tnts = []
        self.anvils = []
        self.potions = []
        self.bosses = []
        self.inventory = {}
        self.user_stats = {}

        self.screen_shake = 0
        self.boss_summon_progress = 0
        self.current_depth_blocks = 0
        self.mvp_text = "MVP: -"
        self.stats_timer = 0

        # Pickaxe tier system
        self.pickaxe_tier = 0
        self.total_ores_mined = 0
        self.pickaxe_base_damage = PICKAXE_TIERS[0]['damage']

        # Prestige system
        self.prestige_level = 0
        self.last_biome_idx = 0

        # Milestone tracking
        self.next_milestone_idx = 0
        self.max_depth_ever = 0

        # Random events
        self.event_timer = 0
        self.active_event = None
        self.event_summon_progress = 0

        # Announcement system
        self.announcements = AnnouncementSystem()

        # --- Assets Laden ---
        self.load_sounds()
        self.load_images()

        # --- Systeme Starten ---
        self.atmosphere = Atmosphere(WIDTH, HEIGHT)
        self.streak_system = LikeStreakSystem()

        # --- Load all pickaxe images ---
        self.pickaxe_images = []
        for tier in PICKAXE_TIERS:
            img = safe_load_img(f"assets/images/{tier['image']}", (BLOCK_SIZE, BLOCK_SIZE), (200, 200, 200))
            self.pickaxe_images.append(img)

        # --- Held Erstellen (start with wooden pickaxe) ---
        h_img = self.pickaxe_images[0]
        self.hero = HeroPickaxe(WIDTH//2, 200, h_img)

        # --- Welt Generieren ---
        for i in range(12): self.spawn_row(i*BLOCK_SIZE + 400)

    def load_sounds(self):
        self.sfx = {}
        self.sfx['stone'] = [safe_load_snd(f"assets/sounds/stone{i}.wav", 0.25) for i in range(1, 5)]
        self.sfx['explode'] = [safe_load_snd(f"assets/sounds/explode{i}.wav", 0.5) for i in range(1, 5)]
        self.sfx['grass'] = safe_load_snd("assets/sounds/grass1.wav", 0.25)
        self.sfx['gravel'] = safe_load_snd("assets/sounds/gravel1.wav", 0.25)
        self.sfx['wood'] = safe_load_snd("assets/sounds/wood1.wav", 0.4)
        self.sfx['hit'] = safe_load_snd("assets/sounds/stone2.wav", 0.4)
        self.sfx['teleport'] = safe_load_snd("assets/sounds/teleport.wav", 0.5)
        if isinstance(self.sfx['teleport'], type(safe_load_snd("x"))):
             self.sfx['teleport'] = safe_load_snd("assets/sounds/stare.wav", 0.5)

    def load_images(self):
        self.assets = {}
        self.ui_assets = {}
        self.item_icons = {}
        self.assets['bedrock'] = safe_load_img("assets/images/bedrock.png", (BLOCK_SIZE, BLOCK_SIZE), (20,20,20))

        for theme in THEMES:
            for b_name in theme['blocks'].keys():
                if b_name not in self.assets:
                    col = (random.randint(50,200), random.randint(50,200), random.randint(50,200))
                    self.assets[b_name] = safe_load_img(f"assets/images/{b_name}.png", (BLOCK_SIZE, BLOCK_SIZE), col)
                    self.ui_assets[b_name] = pygame.transform.scale(self.assets[b_name], (25, 25))

        # Load item icons for inventory display
        for block_name, icon_file in ITEM_ICON_MAP.items():
            if icon_file not in [v for v in self.item_icons.values()]:
                self.item_icons[block_name] = safe_load_img(f"assets/images/{icon_file}", (25, 25), (200, 200, 50))

        self.crack_images = []
        for i in range(10):
            self.crack_images.append(safe_load_img(f"assets/images/destroy_stage_{i}.png", (BLOCK_SIZE, BLOCK_SIZE), (0,0,0,0)))

    def play_sound(self, category):
        if category in self.sfx:
            sound_obj = self.sfx[category]
            if isinstance(sound_obj, list) and len(sound_obj) > 0:
                random.choice(sound_obj).play()
            elif hasattr(sound_obj, 'play'):
                sound_obj.play()

    def get_current_biome_index(self):
        total_biomes = len(THEMES)
        raw_idx = self.current_depth_blocks // THEME_CHANGE_INTERVAL
        if raw_idx >= total_biomes:
            cycle = raw_idx // total_biomes
            if cycle > self.prestige_level:
                self.prestige_level = cycle
                self.announcements.add(f"PRESTIGE {self.prestige_level}!", "Blocks are tougher. Ores are richer.", 240, (255, 100, 255))
                self.screen_shake = 60
            return raw_idx % total_biomes
        return raw_idx

    def get_blended_bg(self):
        depth = self.current_depth_blocks
        total_biomes = len(THEMES)
        # For prestige cycling, calculate effective position within theme list
        raw_idx = depth // THEME_CHANGE_INTERVAL
        effective_idx = raw_idx % total_biomes if raw_idx >= total_biomes else raw_idx
        t_idx = min(effective_idx, total_biomes - 1)

        pos_in_biome = depth % THEME_CHANGE_INTERVAL
        remaining = THEME_CHANGE_INTERVAL - pos_in_biome

        if remaining <= BIOME_TRANSITION_ROWS:
            next_idx = (t_idx + 1) % total_biomes
            t = 1.0 - (remaining / BIOME_TRANSITION_ROWS)
            curr_bg = THEMES[t_idx]['bg']
            next_bg = THEMES[next_idx]['bg']
            return tuple(int(curr_bg[i] + (next_bg[i] - curr_bg[i]) * t) for i in range(3))
        return THEMES[t_idx]['bg']

    def spawn_row(self, offset_y=None):
        if offset_y is None:
            if self.blocks: offset_y = max(self.blocks, key=lambda b: b.rect.y).rect.y + BLOCK_SIZE
            else: offset_y = HEIGHT
            self.current_depth_blocks += 1

        t_idx = self.get_current_biome_index()
        theme = THEMES[t_idx]

        # Biome transition blending
        pos_in_biome = self.current_depth_blocks % THEME_CHANGE_INTERVAL
        remaining = THEME_CHANGE_INTERVAL - pos_in_biome

        if remaining <= BIOME_TRANSITION_ROWS and t_idx < len(THEMES) - 1:
            next_idx = (t_idx + 1) % len(THEMES)
            next_theme = THEMES[next_idx]
            blend_factor = 1.0 - (remaining / BIOME_TRANSITION_ROWS)
            merged = {}
            for k, v in theme['blocks'].items():
                merged[k] = v * (1.0 - blend_factor)
            for k, v in next_theme['blocks'].items():
                merged[k] = merged.get(k, 0) + v * blend_factor
            opts = list(merged.keys())
            weights = list(merged.values())
        else:
            opts = list(theme['blocks'].keys()); weights = list(theme['blocks'].values())

        # Ore vein event: boost ore weights
        if self.active_event and self.active_event['type'] == 'ore_vein':
            boosted = []
            for i, opt in enumerate(opts):
                boosted.append(weights[i] * 3 if "ore" in opt else weights[i])
            weights = boosted
            self.active_event['rows_remaining'] -= 1
            if self.active_event['rows_remaining'] <= 0:
                self.active_event = None

        # Ensure new block textures are loaded
        for opt in opts:
            if opt not in self.assets and opt != "bedrock":
                col = (random.randint(50,200), random.randint(50,200), random.randint(50,200))
                self.assets[opt] = safe_load_img(f"assets/images/{opt}.png", (BLOCK_SIZE, BLOCK_SIZE), col)
                self.ui_assets[opt] = pygame.transform.scale(self.assets[opt], (25, 25))

        start_x = (WIDTH - (COLS * BLOCK_SIZE)) // 2
        for c in range(COLS):
            x = start_x + c * BLOCK_SIZE
            if c == 0 or c == COLS - 1:
                b = Block(x, offset_y, "bedrock", self.assets['bedrock'], 99999, True)
            else:
                typ = random.choices(opts, weights=weights, k=1)[0]
                base_hp = BLOCK_STATS.get(typ, 100)
                # Prestige HP scaling
                hp = int(base_hp * (1.0 + self.prestige_level * 0.5))
                if typ == "bedrock":
                    b = Block(x, offset_y, "bedrock", self.assets['bedrock'], 999999, True)
                else:
                    b = Block(x, offset_y, typ, self.assets[typ], hp)
            self.blocks.append(b)

    def draw_shadow(self, rect, scale=1.0):
        w = int(rect.width * scale); h = int(rect.width * 0.3 * scale)
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (0,0,0,100), (0,0,w,h))
        self.screen.blit(s, (rect.centerx - w//2, rect.bottom - h//2 + 5))

    def check_pickaxe_upgrade(self):
        next_tier = self.pickaxe_tier + 1
        if next_tier >= len(PICKAXE_TIERS): return
        tier_data = PICKAXE_TIERS[next_tier]
        if self.current_depth_blocks >= tier_data['depth_req'] and self.total_ores_mined >= tier_data['ores_req']:
            self.pickaxe_tier = next_tier
            self.pickaxe_base_damage = tier_data['damage']
            new_img = self.pickaxe_images[next_tier]
            self.hero.original_image = new_img
            self.hero.image = new_img
            self.announcements.add(f"UPGRADE: {tier_data['name']}!", f"DMG: {tier_data['damage']}", 180, (255, 215, 0))
            self.screen_shake = 30
            self.play_sound('explode')
            if len(self.particles) < MAX_PARTICLES:
                for _ in range(30):
                    self.particles.append(Particle(self.hero.rect.centerx, self.hero.rect.centery, (255, 215, 0)))

    def check_milestones(self):
        if self.next_milestone_idx >= len(MILESTONES): return
        target = MILESTONES[self.next_milestone_idx]
        if self.current_depth_blocks >= target:
            self.next_milestone_idx += 1
            self.announcements.add(f"DEPTH {target}!", "Keep mining!", 150, (50, 255, 50))
            self.screen_shake = 25
            for _ in range(3): self.streak_system.add_like()
            if len(self.particles) < MAX_PARTICLES:
                for _ in range(40):
                    self.particles.append(Particle(WIDTH // 2, HEIGHT // 2, (random.randint(200, 255), random.randint(200, 255), 0)))

    def check_biome_change(self):
        current_idx = self.get_current_biome_index()
        if current_idx != self.last_biome_idx:
            self.last_biome_idx = current_idx
            biome = THEMES[current_idx]
            prestige_text = f" (Prestige {self.prestige_level})" if self.prestige_level > 0 else ""
            self.announcements.add(biome['name'].upper() + prestige_text, f"Biome {current_idx + 1} of {len(THEMES)}", 180, (255, 255, 255))
            self.screen_shake = 15

    def check_random_events(self, forced=False):
        if not forced:
            self.event_timer += 1
            if self.event_timer < EVENT_CHECK_INTERVAL: return
            self.event_timer = 0
            if self.active_event: return
            if random.random() > EVENT_CHANCE: return

        event_type = random.choice(["ore_vein", "treasure_room", "cave_in", "golden_rush"])

        if event_type == "ore_vein":
            self.active_event = {"type": "ore_vein", "rows_remaining": 5}
            self.announcements.add("ORE VEIN!", "Rich deposits ahead!", 120, (255, 200, 50))
        elif event_type == "treasure_room":
            for b in self.blocks:
                if b.active and not b.is_bedrock and b.rect.y > HEIGHT * 0.5:
                    if random.random() < 0.3:
                        new_type = random.choice(["diamond_ore", "emerald_ore"])
                        if new_type in self.assets:
                            b.type = new_type
                            b.image = self.assets[new_type]
                            b.hp = BLOCK_STATS[new_type]
                            b.max_hp = b.hp
            self.announcements.add("TREASURE ROOM!", "Rare ores everywhere!", 120, (0, 255, 200))
        elif event_type == "cave_in":
            for b in self.blocks:
                if b.active and not b.is_bedrock:
                    b.hp = max(1, b.hp // 2)
            self.announcements.add("CAVE-IN!", "Blocks weakened!", 120, (255, 100, 50))
            self.screen_shake = 40
        elif event_type == "golden_rush":
            self.streak_system.streak += 20
            self.streak_system.current_time = self.streak_system.max_time
            self.streak_system.active = True
            self.streak_system.multiplier = min(5.0, self.streak_system.multiplier + 2.0)
            self.announcements.add("GOLDEN RUSH!", "x2 bonus damage!", 120, (255, 215, 0))

    def check_depth_record(self):
        if self.current_depth_blocks > self.max_depth_ever:
            self.max_depth_ever = self.current_depth_blocks
            if self.max_depth_ever % 100 == 0 and self.max_depth_ever > 0:
                self.floating_texts.append(FloatingText(WIDTH // 2 - 80, HEIGHT // 2, f"NEW RECORD: {self.max_depth_ever}!", (255, 50, 50), 30))

    def update(self):
        # 1. Systeme
        self.streak_system.update()
        self.announcements.update()
        self.stats_timer += 1
        if self.stats_timer > 120 and self.user_stats:
            top = max(self.user_stats, key=self.user_stats.get)
            self.mvp_text = f"MVP: {top} ({self.user_stats[top]})"
            self.stats_timer = 0

        # 2. Boss Logic
        if len(self.bosses) > 0:
            for b in self.bosses:
                b.update(self.blocks, self)

            for a in self.anvils[:]:
                hit = a.update(self.bosses)
                if hit:
                    self.screen_shake = 20; self.anvils.remove(a); self.sfx['hit'].play()
                    if hit.take_damage(): self.kill_boss(hit)
                elif not a.active: self.anvils.remove(a)

            for p in self.potions[:]:
                hit = p.update(self.bosses)
                if hit:
                    self.screen_shake = 20; self.potions.remove(p); self.sfx['hit'].play()
                    if hit.take_damage(): self.kill_boss(hit)
                elif not p.active: self.potions.remove(p)

        # 3. Held & Kamera
        self.hero.update(self.blocks, self.particles, self.sfx['hit'], self.floating_texts, self.inventory, self.streak_system.multiplier, self.pickaxe_base_damage)

        cam_target = HEIGHT * 0.4
        if self.hero.rect.centery > cam_target:
            diff = self.hero.rect.centery - cam_target
            self.hero.rect.centery -= diff
            for b in self.blocks: b.rect.y -= diff
            for p in self.particles: p.rect.y -= diff
            for ft in self.floating_texts: ft.y -= diff
            for t in self.tnts:
                if hasattr(t, 'rect'): t.rect.y -= diff

        # Welt generieren
        lowest = 0;
        if self.blocks: lowest = max(b.rect.y for b in self.blocks)
        if lowest < HEIGHT + 100: self.spawn_row()
        self.blocks = [b for b in self.blocks if b.rect.y > -200]

        # 4. Mining & Sound
        for b in self.blocks:
            if b.active and b.hp <= 0 and not b.is_bedrock:
                b.active = False
                snd = 'stone'
                if any(x in b.type for x in ['dirt', 'clay', 'sand']): snd = 'gravel'
                elif any(x in b.type for x in ['moss', 'sculk', 'leaves']): snd = 'grass'
                elif any(x in b.type for x in ['wood', 'chest', 'plank']): snd = 'wood'
                elif any(x in b.type for x in ['ice']): snd = 'grass'
                self.play_sound(snd)
                self.inventory[b.type] = self.inventory.get(b.type, 0) + 1
                self.floating_texts.append(FloatingText(b.rect.x, b.rect.y, "+1"))
                if "ore" in b.type:
                    self.total_ores_mined += 1

        # Progression checks
        self.check_pickaxe_upgrade()
        self.check_milestones()
        self.check_biome_change()
        self.check_random_events()
        self.check_depth_record()

        # Bomben Update
        for t in self.tnts[:]:
            if isinstance(t, LightningEntity): t.update()
            else: t.update()

            if hasattr(t, 'explode') and t.explode:
                self.screen_shake = 40
                self.play_sound('explode')
                cy = 0 if isinstance(t, LightningEntity) else t.rect.centery
                cx = t.x if isinstance(t, LightningEntity) else t.rect.centerx

                if isinstance(t, LightningEntity):
                    for b in self.blocks:
                        if b.active and not b.is_bedrock and b.rect.colliderect(t.rect): b.hp = 0
                elif t.type == "nuke":
                    for b in self.blocks:
                        if not b.is_bedrock: b.hp = 0
                elif t.type == "x":
                    for b in self.blocks:
                        if not b.is_bedrock and abs(abs(b.rect.centerx - cx) - abs(b.rect.centery - cy)) < 40: b.hp = 0
                self.tnts.remove(t)

        # Cleanup
        for p in self.particles[:]:
            p.update()
            if p.life <= 0: self.particles.remove(p)
        for ft in self.floating_texts[:]:
            ft.update()
            if ft.life <= 0: self.floating_texts.remove(ft)
        if self.screen_shake > 0: self.screen_shake -= 1

    def kill_boss(self, boss):
        self.bosses.remove(boss); self.screen_shake = 60

        depth = self.current_depth_blocks
        base_loot = 10 + depth // 100 + self.prestige_level * 5
        biome_idx = self.get_current_biome_index()
        biome = THEMES[biome_idx]
        ore_types = [k for k in biome['blocks'].keys() if "ore" in k]
        if not ore_types: ore_types = ["diamond_ore"]

        for ore in ore_types:
            amount = max(1, base_loot // len(ore_types))
            self.inventory[ore] = self.inventory.get(ore, 0) + amount
            self.total_ores_mined += amount
            self.floating_texts.append(FloatingText(boss.rect.centerx - 40, boss.rect.y + random.randint(-20, 20), f"+{amount} {ore.replace('_',' ').title()}", (255, 215, 0), 18))

        self.streak_system.streak += 10
        self.streak_system.current_time = self.streak_system.max_time
        self.streak_system.active = True
        self.streak_system.multiplier = min(5.0, self.streak_system.multiplier + 1.0)

        if not self.bosses: self.boss_summon_progress = 0
        self.check_pickaxe_upgrade()

    def draw(self):
        bg = self.get_blended_bg()
        self.screen.fill(bg)

        if self.screen_shake > 0:
            intensity = min(self.screen_shake, 15)
            sx = random.randint(-intensity // 3, intensity // 3)
            sy = random.randint(-intensity // 3, intensity // 3)
        else:
            sx, sy = 0, 0
        surf = self.screen.copy()

        for b in self.blocks:
            if b.active:
                surf.blit(b.image, b.rect)
                if b.hp < b.max_hp and not b.is_bedrock and self.crack_images:
                    damage_pct = 1.0 - (b.hp / b.max_hp)
                    crack_idx = int(damage_pct * 10)
                    if 0 <= crack_idx < len(self.crack_images):
                        surf.blit(self.crack_images[crack_idx], b.rect)

        self.draw_shadow(self.hero.rect, 0.6); self.hero.draw(surf)

        for t in self.tnts:
            if isinstance(t, LightningEntity): t.draw(surf)
            else: self.draw_shadow(t.rect); t.draw(surf)
        for a in self.anvils: self.draw_shadow(a.rect); a.draw(surf)
        for po in self.potions: po.draw(surf)
        for b in self.bosses: self.draw_shadow(b.rect, 1.2); b.draw(surf)
        for p in self.particles: p.draw(surf)
        for ft in self.floating_texts: ft.draw(surf)

        self.atmosphere.draw_foreground(surf)
        self.screen.blit(surf, (sx, sy))
        self.draw_ui()
        pygame.display.flip()

    def draw_ui(self):
        t_idx = self.get_current_biome_index()

        # Depth and biome name (bottom right)
        pygame.draw.rect(self.screen, UI_BG, (WIDTH-220, HEIGHT-70, 200, 60))
        t1 = self.font.render(f"Depth: {self.current_depth_blocks}", True, (200,200,200))
        biome_name = THEMES[t_idx]['name']
        if self.prestige_level > 0: biome_name += f" P{self.prestige_level}"
        t2 = self.big_font.render(biome_name, True, (50, 255, 50))
        self.screen.blit(t1, (WIDTH-210, HEIGHT-65)); self.screen.blit(t2, (WIDTH-210, HEIGHT-45))

        # MVP display (top right)
        if self.mvp_text:
            s = self.font.render(self.mvp_text, True, (255, 215, 0))
            pygame.draw.rect(self.screen, UI_BG, (WIDTH - s.get_width()-20, 10, s.get_width()+10, 30))
            self.screen.blit(s, (WIDTH - s.get_width()-15, 15))

        # Boss fight UI
        if self.bosses:
            has_ender = any(isinstance(b, EndermanBoss) for b in self.bosses)
            has_hero = any(isinstance(b, HerobrineBoss) for b in self.bosses)
            yp = 400
            if has_ender:
                for i, c in enumerate(["!LEFT", "!MID", "!RIGHT"]):
                    s = self.mega_font.render(c, True, ENDER_PURPLE)
                    if time.time()%0.5>0.25: self.screen.blit(s, (WIDTH//2 - 100 + i*100, yp))
                yp += 50
            if has_hero:
                s = self.mega_font.render("!SPLASH", True, (255, 255, 0))
                if time.time()%0.5>0.25: self.screen.blit(s, (WIDTH//2 - 50, yp))
        else:
            # Boss summon bar
            w = 300; x = (WIDTH-w)//2
            pygame.draw.rect(self.screen, UI_BG, (x, 10, w, 30))
            pct = min(1.0, self.boss_summon_progress / BOSS_SUMMON_REQ)
            pygame.draw.rect(self.screen, ENDER_PURPLE, (x+5, 15, int((w-10)*pct), 20))
            txt = self.font.render("BOSS SUMMON", True, TEXT_COLOR)
            self.screen.blit(txt, (x+90, 15))

            # Event summon bar
            pygame.draw.rect(self.screen, UI_BG, (x, 50, w, 30))
            epct = min(1.0, self.event_summon_progress / EVENT_SUMMON_REQ)
            pygame.draw.rect(self.screen, (255, 200, 50), (x+5, 55, int((w-10)*epct), 20))
            etxt = self.font.render("!EVENT", True, TEXT_COLOR)
            self.screen.blit(etxt, (x+120, 55))

        # Inventory display (top left) - use item icons for ores
        y = 20
        top_inv = sorted(self.inventory.items(), key=lambda x:x[1], reverse=True)[:5]
        for k, v in top_inv:
            pygame.draw.rect(self.screen, UI_BG, (10, y, 180, 35))
            if k in self.item_icons:
                self.screen.blit(self.item_icons[k], (15, y+5))
            elif k in self.ui_assets:
                self.screen.blit(self.ui_assets[k], (15, y+5))
            t = self.font.render(f"{k.replace('_',' ').title()}: {v}", True, TEXT_COLOR)
            self.screen.blit(t, (45, y+8))
            y += 40

        # Pickaxe tier display (bottom left)
        tier_name = PICKAXE_TIERS[self.pickaxe_tier]['name']
        small_icon = pygame.transform.scale(self.pickaxe_images[self.pickaxe_tier], (25, 25))
        pygame.draw.rect(self.screen, UI_BG, (10, HEIGHT - 45, 200, 35))
        self.screen.blit(small_icon, (15, HEIGHT - 40))
        t = self.font.render(tier_name, True, (255, 215, 0))
        self.screen.blit(t, (45, HEIGHT - 38))

        # Streak system
        self.streak_system.draw(self.screen)

        # Announcements
        self.announcements.draw(self.screen, self.mega_font, self.big_font)

    def handle_input(self, data):
        cmd, user = data
        if cmd == "!like": self.streak_system.add_like(); return

        if cmd == "!event":
            self.event_summon_progress += 1
            if self.event_summon_progress >= EVENT_SUMMON_REQ:
                self.event_summon_progress = 0
                self.check_random_events(forced=True)
            if user != "Admin": self.user_stats[user] = self.user_stats.get(user, 0) + 1
            return

        if (cmd == "!boss" or cmd == "!hero") and len(self.bosses) < MAX_ACTIVE_BOSSES:
            self.boss_summon_progress += 1
            if self.boss_summon_progress >= BOSS_SUMMON_REQ:
                self.boss_summon_progress = 0; self.screen_shake = 50
                boss = create_boss(self)
                if cmd == "!hero" or isinstance(boss, HerobrineBoss):
                    if not isinstance(boss, HerobrineBoss):
                        hp_mult = 1.0 + (self.current_depth_blocks / 500) + (self.prestige_level * 2.0)
                        boss = HerobrineBoss(hp_mult)
                    self.bosses.append(boss); self.floating_texts.append(FloatingText(WIDTH//2, 200, "HEROBRINE!", (255,0,0), 50))
                else:
                    self.bosses.append(boss); self.floating_texts.append(FloatingText(WIDTH//2, 200, "ENDERMAN!", ENDER_PURPLE, 50))
            if user != "Admin": self.user_stats[user] = self.user_stats.get(user, 0) + 1
            return

        if self.bosses:
            if cmd in ["!left", "!mid", "!right"]:
                x = WIDTH//4 if cmd=="!left" else (WIDTH//2 if cmd=="!mid" else WIDTH*3//4)
                self.anvils.append(PhysicsAnvil(x))
            elif cmd == "!splash":
                self.potions.append(PhysicsPotion(random.randint(50, WIDTH-50)))
            if user != "Admin": self.user_stats[user] = self.user_stats.get(user, 0) + 1
            return

        if cmd == "!left": self.hero.apply_force(-MOVE_FORCE, -2)
        elif cmd == "!right": self.hero.apply_force(MOVE_FORCE, -2)
        elif cmd == "!dig": self.hero.apply_force(0, 12)
        elif cmd == "XBOMB": self.tnts.append(BombEntity(WIDTH//2, "x"))
        elif cmd == "NUKE": self.tnts.append(BombEntity(WIDTH//2, "nuke"))

        if user != "Admin": self.user_stats[user] = self.user_stats.get(user, 0) + 1

    def run(self, q):
        while True:
            for e in pygame.event.get():
                if e.type==pygame.QUIT: pygame.quit(); sys.exit()
            while not q.empty(): self.handle_input(q.get())
            self.update(); self.draw(); self.clock.tick(FPS)

if __name__ == "__main__":
    q = queue.Queue()
    def fake_spammer():
        usrs = ["Steve", "Alex", "Pro", "Noob", "Miner42", "DiamondKing", "CreeperHunter"]
        while True:
            time.sleep(0.1); u = random.choice(usrs); r = random.random()
            if r < 0.08: q.put(("!like", u))
            elif r < 0.12: q.put(("!event", u))
            elif r < 0.18: q.put(("!dig", u))
            elif r < 0.22: q.put(("!tnt", u))
            elif r < 0.26: q.put(("!hero", u))
            elif r < 0.30: q.put(("!tnt", u))
            elif r < 0.85: q.put((random.choice(["!left","!mid","!right","!splash"]), u))
    threading.Thread(target=fake_spammer, daemon=True).star1t()
    Game().run(q)
