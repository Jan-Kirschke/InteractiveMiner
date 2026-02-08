import pygame
import threading
import queue
import time
import random
import math

# --- KONFIGURATION ---
VIDEO_ID = "HIER_DEINE_VIDEO_ID" 
COLS = 9
BLOCK_SIZE = 80
WIDTH = BLOCK_SIZE * COLS 
HEIGHT = 800
FPS = 60

SCROLL_SPEED = 1.0

# Gameplay Balance
MAX_PICKAXES = 25       
SPAWN_COOLDOWN = 80    

# Boss Settings
BOSS_SUMMON_REQ = 20    
BOSS_MAX_HP = 3         # Enderman hält 3 Amboss-Treffer aus
BOSS_REPAIR_SPEED = 60  # Alle 60 Frames setzt er einen Block

# Farben & Fonts
UI_BG = (0, 0, 0, 180)
TEXT_COLOR = (255, 255, 255)
ENDER_PURPLE = (200, 0, 255)

# --- KLASSEN ---

class Block:
    def __init__(self, x, y, type_name, image, hp, is_bedrock=False):
        self.rect = pygame.Rect(x, y, BLOCK_SIZE, BLOCK_SIZE)
        self.type = type_name
        self.image = image
        self.max_hp = hp
        self.hp = hp
        self.active = True
        self.is_bedrock = is_bedrock

class Particle:
    def __init__(self, x, y, color, speed_mult=1.0):
        self.rect = pygame.Rect(x, y, 6, 6)
        self.color = color
        self.vel_x = random.uniform(-5, 5) * speed_mult
        self.vel_y = random.uniform(-5, 5) * speed_mult
        self.gravity = 0.5
        self.life = random.randint(30, 60)

    def update(self):
        self.vel_y += self.gravity
        self.rect.x += self.vel_x
        self.rect.y += self.vel_y
        self.life -= 1

    def draw(self, screen):
        if self.life > 0:
            pygame.draw.rect(screen, self.color, self.rect)

class FloatingText:
    def __init__(self, x, y, text, color=(255, 255, 255), size=24):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.font = pygame.font.SysFont("Arial", size, bold=True)
        self.life = 60 
        self.vel_y = -2.0 

    def update(self):
        self.y += self.vel_y
        self.life -= 1

    def draw(self, screen):
        if self.life > 0:
            alpha = min(255, self.life * 5)
            surf = self.font.render(str(self.text), True, self.color)
            surf.set_alpha(alpha)
            screen.blit(surf, (self.x, self.y))

# --- ENDERMAN BOSS ---
class EndermanBoss:
    def __init__(self):
        self.width = 100
        self.height = 250 # Groß und schlank
        self.x = WIDTH // 2
        self.y = 100
        self.rect = pygame.Rect(self.x, self.y, self.width, self.height)
        
        self.hp = BOSS_MAX_HP
        self.max_hp = BOSS_MAX_HP
        self.speed = 5
        self.direction = 1 # 1 = Rechts, -1 = Links
        self.repair_timer = 0
        
        # Grafik erstellen (Schwarz mit lila Augen)
        self.image = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pygame.draw.rect(self.image, (20, 20, 20), (10, 0, 80, 250)) # Körper
        pygame.draw.rect(self.image, (0, 0, 0), (10, 0, 80, 80))   # Kopf
        # Augen
        pygame.draw.rect(self.image, ENDER_PURPLE, (15, 30, 25, 10)) 
        pygame.draw.rect(self.image, ENDER_PURPLE, (60, 30, 25, 10))
        # Arme (halten einen Block)
        pygame.draw.rect(self.image, (20, 20, 20), (-10, 80, 20, 150)) 
        pygame.draw.rect(self.image, (20, 20, 20), (90, 80, 20, 150)) 
        
        # Block in der Hand
        pygame.draw.rect(self.image, (100, 200, 100), (20, 150, 60, 60)) # Grasblock

        self.hit_flash = 0

    def update(self, blocks, assets):
        # 1. Bewegung
        self.x += self.speed * self.direction
        
        # Randprüfung (bleibt im Grid)
        grid_start = (WIDTH - (COLS * BLOCK_SIZE)) // 2
        grid_end = grid_start + (COLS * BLOCK_SIZE)
        
        if self.x < grid_start + BLOCK_SIZE: # Nicht in den Bedrock laufen
            self.direction = 1
        elif self.x + self.width > grid_end - BLOCK_SIZE:
            self.direction = -1
            
        self.rect.x = self.x
        
        # 2. Blöcke reparieren (Fies!)
        self.repair_timer += 1
        if self.repair_timer > BOSS_REPAIR_SPEED:
            self.repair_timer = 0
            # Suche kaputten Block in der Nähe
            for b in blocks:
                if not b.active and not b.is_bedrock:
                    # Prüfe Distanz
                    if abs(b.rect.centerx - self.rect.centerx) < 100 and b.rect.y > self.rect.bottom:
                        # REPARIEREN!
                        b.active = True
                        b.hp = b.max_hp
                        return # Nur einen pro Tick reparieren

        if self.hit_flash > 0: self.hit_flash -= 1

    def take_damage(self):
        self.hp -= 1
        self.hit_flash = 10
        if self.hp <= 0: return True
        return False

    def draw(self, screen):
        if self.hit_flash > 0:
             # Weiß aufblinken
            mask = pygame.mask.from_surface(self.image)
            white = mask.to_surface(setcolor=(255, 100, 100, 200), unsetcolor=(0,0,0,0))
            screen.blit(white, self.rect)
        else:
            screen.blit(self.image, self.rect)
        
        # HP Bar
        bar_w = 200
        pygame.draw.rect(screen, (0, 0, 0), (self.rect.centerx - 100, self.rect.y - 20, bar_w, 10))
        pct = self.hp / self.max_hp
        pygame.draw.rect(screen, ENDER_PURPLE, (self.rect.centerx - 100, self.rect.y - 20, bar_w * pct, 10))


class PhysicsAnvil:
    def __init__(self, x, y):
        self.width = 60
        self.height = 80
        self.rect = pygame.Rect(x, y, self.width, self.height)
        self.vel_y = 0
        self.gravity = 1.5 # Fällt sehr schnell (schwer)
        self.active = True
        
        # Grafik (Grauer Amboss)
        self.image = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pygame.draw.rect(self.image, (80, 80, 80), (10, 0, 40, 20)) # Top
        pygame.draw.rect(self.image, (80, 80, 80), (20, 20, 20, 40)) # Hals
        pygame.draw.rect(self.image, (80, 80, 80), (0, 60, 60, 20))  # Basis

    def update(self, boss):
        self.vel_y += self.gravity
        self.rect.y += self.vel_y
        
        # Kollision mit Boss
        if boss and self.rect.colliderect(boss.rect):
            self.active = False
            return "HIT"
            
        if self.rect.y > HEIGHT:
            self.active = False
        return None

    def draw(self, screen):
        screen.blit(self.image, self.rect)

# --- BOMBEN ---
class BombEntity:
    def __init__(self, x, y, bomb_type="x"):
        self.rect = pygame.Rect(x, y, 64, 64)
        self.type = bomb_type # "x" oder "nuke"
        self.vel_y = -5
        self.gravity = 0.5
        self.timer = 60 if bomb_type == "x" else 100
        self.explode = False
        
        # Grafik
        self.image = pygame.Surface((64, 64), pygame.SRCALPHA)
        color = (0, 0, 0) if bomb_type == "x" else (255, 255, 255)
        text_char = "X" if bomb_type == "x" else "☢"
        pygame.draw.circle(self.image, color, (32, 32), 30)
        font = pygame.font.SysFont("Arial", 40, bold=True)
        txt = font.render(text_char, True, (255, 0, 0))
        self.image.blit(txt, (15, 10))

    def update(self):
        self.vel_y += self.gravity
        self.rect.y += self.vel_y
        self.timer -= 1
        if self.timer <= 0: self.explode = True

    def draw(self, screen):
        # Blinken
        if self.timer < 30 and self.timer % 5 == 0:
            temp = self.image.copy()
            temp.fill((255, 255, 255, 100), special_flags=pygame.BLEND_RGBA_ADD)
            screen.blit(temp, self.rect)
        else:
            screen.blit(self.image, self.rect)


class PhysicsPickaxe:
    def __init__(self, x, y, image, user="Unknown"):
        self.image = image
        self.original_image = image 
        self.rect = self.image.get_rect(center=(x, y))
        self.vel_x = random.uniform(-3, 3)
        self.vel_y = -8 
        self.gravity = 0.5
        self.friction = 0.99 
        self.bounce = -0.6 
        self.angle = random.randint(0, 360)
        self.rot_speed = random.uniform(-15, 15)
        self.active = True
        self.min_x = BLOCK_SIZE 
        self.max_x = WIDTH - BLOCK_SIZE
        self.user = user # Wer hat die Hacke geworfen?

    def update(self, blocks, particles_list, hit_sound, floating_texts, stats_tracker):
        self.vel_y += self.gravity
        self.vel_x *= self.friction
        self.rect.x += self.vel_x
        self.rect.y += self.vel_y
        
        # Wandkollision (Bedrock)
        if self.rect.left < self.min_x:
            self.rect.left = self.min_x; self.vel_x *= -0.8
        if self.rect.right > self.max_x:
            self.rect.right = self.max_x; self.vel_x *= -0.8

        # Rotation
        self.angle = (self.angle + self.rot_speed) % 360
        self.rot_image = pygame.transform.rotate(self.original_image, self.angle)
        self.display_rect = self.rot_image.get_rect(center=self.rect.center)
        
        # Rotations-Korrektur
        if self.display_rect.left < self.min_x: self.rect.x += 5
        elif self.display_rect.right > self.max_x: self.rect.x -= 5

        # Block Kollision
        for block in blocks:
            if block.active and not block.is_bedrock and self.rect.colliderect(block.rect):
                
                # Wenn Schaden macht
                if abs(self.vel_y) > 2 or abs(self.vel_x) > 2:
                    block.hp -= 15
                    hit_sound.play()
                    
                    # USER STATS UPDATE (Wer hat abgebaut?)
                    # Wir zählen einfach "Hits" oder "Damage"
                    if self.user in stats_tracker:
                        stats_tracker[self.user] += 1
                    else:
                        stats_tracker[self.user] = 1

                    # Partikel
                    p_color = (100, 100, 100)
                    if "diamond" in block.type: p_color = (0, 255, 255)
                    for _ in range(3):
                        particles_list.append(Particle(self.rect.centerx, self.rect.centery, p_color))

                # Abprallen (Einfache Version)
                if abs(self.rect.bottom - block.rect.top) < 20 and self.vel_y > 0:
                    self.rect.bottom = block.rect.top; self.vel_y *= self.bounce
                elif abs(self.rect.top - block.rect.bottom) < 20 and self.vel_y < 0:
                    self.rect.top = block.rect.bottom; self.vel_y *= self.bounce
                
        if self.rect.y > HEIGHT + 100: 
            self.active = False

    def draw(self, screen):
        screen.blit(self.rot_image, self.display_rect)


# --- GAME KLASSE ---
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Infinite Miner - Enderman Update")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 16, bold=True)
        self.big_font = pygame.font.SysFont("Arial", 24, bold=True)
        self.mega_font = pygame.font.SysFont("Arial", 40, bold=True)
        
        self.particles = [] 
        self.tnts = []      # Normale TNTs (werden zu XBombs/Nukes)
        self.anvils = []    # Ambosse gegen Boss
        self.pickaxes = []
        self.floating_texts = [] 
        self.screen_shake = 0 
        
        # --- STATISTIK ---
        self.user_stats = {} # {"Username": Score}
        self.top_miner_text = "Top Miner: -"
        self.stats_timer = 0
        
        # --- EVENT SYSTEM ---
        self.boss = None
        self.boss_summon_progress = 0
        self.nuke_charge = 0
        
        # --- SOUNDS ---
        pygame.mixer.init()
        # (Platzhalter Sounds)
        class Dummy: 
            def play(self): pass
        self.sfx = {k: Dummy() for k in ['hit', 'break', 'explode', 'teleport']}

        # --- ASSETS SETUP ---
        # Hintergrund
        try:
            bg_raw = pygame.image.load("assets/images/wp7269751-minecraft-3d-wallpapers.jpg").convert()
            scale = HEIGHT / bg_raw.get_height()
            new_w = int(bg_raw.get_width() * scale)
            bg_s = pygame.transform.scale(bg_raw, (new_w, HEIGHT))
            self.background = pygame.Surface((WIDTH, HEIGHT))
            self.background.blit(bg_s, ((WIDTH-new_w)//2, 0))
        except:
            self.background = pygame.Surface((WIDTH, HEIGHT)); self.background.fill((50, 50, 100))

        # Blöcke definieren
        self.block_types = {
            "stone":       {"hp": 100, "rarity": 60, "file": "stone",       "icon": "stone"},
            "dirt":        {"hp": 50,  "rarity": 20, "file": "dirt",        "icon": "dirt"},
            "coal_ore":    {"hp": 150, "rarity": 10, "file": "coal_ore",    "icon": "coal"},
            "copper_ore":  {"hp": 200, "rarity": 8,  "file": "copper_ore",  "icon": "copper_ingot"},
            "iron_ore":    {"hp": 250, "rarity": 6,  "file": "iron_ore",    "icon": "iron_ingot"},
            "gold_ore":    {"hp": 400, "rarity": 3,  "file": "gold_ore",    "icon": "gold_ingot"},
            "redstone_ore":{"hp": 300, "rarity": 4,  "file": "redstone_ore","icon": "redstone"},
            "diamond_ore": {"hp": 800, "rarity": 1,  "file": "diamond_ore", "icon": "diamond"},
            "emerald_ore": {"hp": 1000,"rarity": 0.5,"file": "emerald_ore", "icon": "emerald"},
            "bedrock":     {"hp": 9999,"rarity": 0,  "file": "bedrock",     "icon": "bedrock"},
            "tnt_side":    {"hp": 0,   "rarity": 0,  "file": "tnt_side",    "icon": "tnt_side"}
        }

        # Assets laden
        self.assets = {}      
        self.ui_assets = {}   
        for key, data in self.block_types.items():
            try:
                img = pygame.image.load(f"assets/images/{data['file']}.png").convert_alpha()
                self.assets[key] = pygame.transform.scale(img, (BLOCK_SIZE, BLOCK_SIZE))
            except:
                s = pygame.Surface((BLOCK_SIZE, BLOCK_SIZE)); s.fill((100, 100, 100))
                self.assets[key] = s
            try:
                icon = pygame.image.load(f"assets/images/{data['icon']}.png").convert_alpha()
                self.ui_assets[key] = pygame.transform.scale(icon, (25, 25))
            except:
                self.ui_assets[key] = pygame.transform.scale(self.assets[key], (25, 25))

        # Pickaxe
        try:
            p_img = pygame.image.load("assets/images/diamond_pickaxe.png").convert_alpha()
            self.pickaxe_img = pygame.transform.scale(p_img, (int(BLOCK_SIZE*0.8), int(BLOCK_SIZE*0.8)))
        except:
            self.pickaxe_img = pygame.Surface((50, 50)); self.pickaxe_img.fill((0, 255, 255))
        
        self.crack_images = []
        # Crack Images laden (optional)
        
        self.blocks = []
        self.last_spawn_time = 0
        self.inventory = {key: 0 for key in self.block_types if key not in ["bedrock", "tnt_side"]}
        self.current_y_level = 64 
        self.cols = COLS 
        
        for i in range(10): self.spawn_row(offset_y=i*BLOCK_SIZE + 200)

    def spawn_row(self, offset_y=None):
        if offset_y is None:
            if self.blocks:
                lowest = max(self.blocks, key=lambda b: b.rect.y)
                offset_y = lowest.rect.y + BLOCK_SIZE
            else: offset_y = HEIGHT

        grid_w = self.cols * BLOCK_SIZE
        start_x = (WIDTH - grid_w) // 2
        
        spawnable = [k for k, v in self.block_types.items() if v["rarity"] > 0]
        weights = [self.block_types[k]["rarity"] for k in spawnable]

        for c in range(self.cols):
            x = start_x + c * BLOCK_SIZE
            if c == 0 or c == self.cols - 1:
                b = Block(x, offset_y, "bedrock", self.assets["bedrock"], 9999, True)
            else:
                typ = random.choices(spawnable, weights=weights, k=1)[0]
                b = Block(x, offset_y, typ, self.assets[typ], self.block_types[typ]["hp"])
            self.blocks.append(b)
        
        if offset_y is None or offset_y > HEIGHT: self.current_y_level -= 1

    def update_leaderboard(self):
        # Zeige den aktivsten Miner an
        if self.user_stats:
            top_user = max(self.user_stats, key=self.user_stats.get)
            score = self.user_stats[top_user]
            self.top_miner_text = f"MVP: {top_user} ({score})"

    def update(self):
        # --- STATS TICKER ---
        self.stats_timer += 1
        if self.stats_timer > 120: # Alle 2 Sekunden
            self.update_leaderboard()
            self.stats_timer = 0

        # --- BOSS UPDATE ---
        if self.boss:
            self.boss.update(self.blocks, self.assets)
            
            # Anvils (nur wenn Boss da ist)
            for anvil in self.anvils[:]:
                res = anvil.update(self.boss)
                if res == "HIT":
                    killed = self.boss.take_damage()
                    self.screen_shake = 20
                    self.floating_texts.append(FloatingText(self.boss.rect.centerx, self.boss.rect.y, "CRITICAL HIT!", (255, 0, 0), 40))
                    self.anvils.remove(anvil)
                    
                    if killed:
                        self.boss = None
                        self.boss_summon_progress = 0
                        self.screen_shake = 100
                        # Loot Regen
                        for _ in range(30): self.floating_texts.append(FloatingText(WIDTH//2+random.randint(-100,100), 300, "+50 DIAMOND", (0,255,255)))
                        self.inventory["diamond_ore"] += 50
                elif not anvil.active:
                    self.anvils.remove(anvil)
        else:
            # Normales Scrolling
            move_speed = SCROLL_SPEED
            if self.blocks and self.blocks[0].rect.y > 200: move_speed = 3.0
            
            for b in self.blocks: b.rect.y -= move_speed
            
            # Spawning
            lowest_y = 0
            if self.blocks: lowest_y = max(b.rect.y for b in self.blocks)
            if lowest_y < HEIGHT: self.spawn_row()
            
            # Cleanup
            self.blocks = [b for b in self.blocks if b.rect.y + BLOCK_SIZE > -50]

        # --- ENTITY UPDATES ---
        
        # Blöcke Kaputt machen
        for b in self.blocks:
            if not b.active: continue
            if b.hp <= 0 and not b.is_bedrock:
                b.active = False
                self.sfx['break'].play()
                if b.type in self.inventory: self.inventory[b.type] += 1
                self.floating_texts.append(FloatingText(b.rect.x, b.rect.y, "+1"))

        # Hacken
        for p in self.pickaxes[:]:
            p.update(self.blocks, self.particles, self.sfx['hit'], self.floating_texts, self.user_stats)
            if not p.active: self.pickaxes.remove(p)

        # Bomben (X-Bomb / Nuke)
        for bomb in self.tnts[:]:
            bomb.update()
            if bomb.explode:
                self.screen_shake = 40
                cx, cy = bomb.rect.centerx, bomb.rect.centery
                
                # Nuke Logic
                if bomb.type == "nuke":
                    self.background.fill((255, 255, 255)) # Weißer Blitz
                    for b in self.blocks: 
                        if not b.is_bedrock: b.hp = 0
                
                # X-Bomb Logic
                elif bomb.type == "x":
                    for b in self.blocks:
                        if not b.is_bedrock:
                            dx = abs(b.rect.centerx - cx)
                            dy = abs(b.rect.centery - cy)
                            # Toleranz für Diagonale
                            if abs(dx - dy) < 40: b.hp = 0

                self.tnts.remove(bomb)

        # Partikel & Text - SAUBERE SCHLEIFENSTRUKTUR
        for p in self.particles[:]:
            p.update()
            if p.life <= 0:
                self.particles.remove(p)
            
        for ft in self.floating_texts[:]:
            ft.update()
            if ft.life <= 0:
                self.floating_texts.remove(ft)

        if self.screen_shake > 0: self.screen_shake -= 1

    def draw(self):
        sx = random.randint(-5, 5) if self.screen_shake > 0 else 0
        sy = random.randint(-5, 5) if self.screen_shake > 0 else 0
        
        # Blitz Effekt (Nuke)
        if self.screen_shake > 30 and random.random() < 0.2:
            self.screen.fill((255, 255, 255))
        else:
            self.screen.blit(self.background, (sx, sy))
        
        # Bedrock Rand füllen
        if self.background.get_width() < WIDTH:
            # Falls Hintergrund schmaler als Screen ist (Passiert bei breitem Layout)
            pass 

        # Blöcke
        for b in self.blocks:
            if b.active:
                r = b.rect.move(sx, sy)
                self.screen.blit(b.image, r)

        # Entities
        for t in self.tnts: t.draw(self.screen)
        for p in self.pickaxes: p.draw(self.screen)
        for a in self.anvils: a.draw(self.screen)
        for p in self.particles: 
            p.rect.x+=sx; p.draw(self.screen); p.rect.x-=sx
        
        if self.boss: self.boss.draw(self.screen)
        for ft in self.floating_texts: ft.draw(self.screen)

        self.draw_ui()
        pygame.display.flip()

    def draw_ui(self):
        # Y-Level
        pygame.draw.rect(self.screen, UI_BG, (WIDTH - 120, HEIGHT - 60, 100, 40))
        txt = self.big_font.render(f"Y: {self.current_y_level}", True, (50, 255, 50))
        self.screen.blit(txt, (WIDTH - 110, HEIGHT - 55))
        
        # MVP Anzeige (Oben Rechts)
        if self.top_miner_text:
            surf = self.font.render(self.top_miner_text, True, (255, 215, 0))
            pygame.draw.rect(self.screen, UI_BG, (WIDTH - surf.get_width()-20, 10, surf.get_width()+10, 30))
            self.screen.blit(surf, (WIDTH - surf.get_width()-15, 15))

        # BOSS COMMANDS (Nur wenn Boss da ist)
        if self.boss:
            cmds = ["!LEFT", "!MID", "!RIGHT"]
            for i, cmd in enumerate(cmds):
                c_surf = self.mega_font.render(cmd, True, (255, 0, 0))
                # Blinken
                if time.time() % 0.5 > 0.25:
                    self.screen.blit(c_surf, (WIDTH//2 - 100 + i*100, 400))
        else:
            # Boss Summon Bar
            bar_w = 300
            bx = (WIDTH - bar_w) // 2
            pygame.draw.rect(self.screen, UI_BG, (bx, 10, bar_w, 30))
            pct = min(1.0, self.boss_summon_progress / BOSS_SUMMON_REQ)
            pygame.draw.rect(self.screen, ENDER_PURPLE, (bx+5, 15, (bar_w-10)*pct, 20))
            txt = self.font.render("BOSS SUMMON", True, (255, 255, 255))
            self.screen.blit(txt, (bx+90, 15))

        # Inventar (Links)
        y_off = 20
        for name, count in self.inventory.items():
            if name == "bedrock" or name == "tnt_side": continue
            pygame.draw.rect(self.screen, UI_BG, (10, y_off-5, 100, 35))
            if name in self.ui_assets: self.screen.blit(self.ui_assets[name], (15, y_off))
            txt = self.font.render(f"{count}", True, TEXT_COLOR)
            self.screen.blit(txt, (50, y_off+2))
            y_off += 40

    def handle_input(self, data):
        # data ist jetzt ein Tuple: (command, username)
        cmd, user = data
        now = pygame.time.get_ticks()

        # BOSS SPAWNN
        if cmd == "!boss" and not self.boss:
            self.boss_summon_progress += 1
            if self.boss_summon_progress >= BOSS_SUMMON_REQ:
                self.boss = EndermanBoss()
                self.screen_shake = 50
                self.floating_texts.append(FloatingText(WIDTH//2, 200, "ENDERMAN APPEARED!", ENDER_PURPLE, 40))
            return

        # BOSS KAMPF (Ambosse)
        if self.boss:
            drop_x = None
            if cmd == "!left": drop_x = WIDTH // 4
            elif cmd == "!mid": drop_x = WIDTH // 2
            elif cmd == "!right": drop_x = WIDTH * 3 // 4
            
            if drop_x:
                self.anvils.append(PhysicsAnvil(drop_x, -100))
            return # Keine normalen Hacken wenn Boss da ist

        # NORMALE EVENTS
        if cmd == "HIT_BLOCK":
            if len(self.pickaxes) < MAX_PICKAXES and (now - self.last_spawn_time > SPAWN_COOLDOWN):
                grid_w = self.cols * BLOCK_SIZE
                sx = (WIDTH - grid_w) // 2
                rx = random.randint(sx+20, sx+grid_w-20)
                self.pickaxes.append(PhysicsPickaxe(rx, -50, self.pickaxe_img, user))
                self.last_spawn_time = now
        
        elif cmd == "XBOMB":
             self.tnts.append(BombEntity(WIDTH//2, -50, "x"))
        
        elif cmd == "NUKE":
             # Nur bei genug Likes/Charge
             self.tnts.append(BombEntity(WIDTH//2, -50, "nuke"))

    def run(self, event_queue):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT: running = False
            
            while not event_queue.empty():
                self.handle_input(event_queue.get())
                
            self.update()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()

if __name__ == "__main__":
    q = queue.Queue()
    
    def fake_spammer():
        usernames = ["MinerSteve", "CraftGirl", "TNT_Lover", "NoobMaster69", "ProGamer"]
        while True:
            time.sleep(0.05)
            user = random.choice(usernames)
            rnd = random.random()
            
            # Simulator Logik
            if rnd < 0.7: q.put(("HIT_BLOCK", user))
            elif rnd < 0.8: q.put(("!boss", user))
            elif rnd < 0.9: 
                # Zufällige Amboss Position simulieren
                cmd = random.choice(["!left", "!mid", "!right"])
                q.put((cmd, user))
            elif rnd < 0.95: q.put(("XBOMB", "Admin"))
            elif rnd > 0.99: q.put(("NUKE", "Admin"))

    threading.Thread(target=fake_spammer, daemon=True).start()
    
    game = Game()
    game.run(q)