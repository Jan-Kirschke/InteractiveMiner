import pygame
import pytchat
import threading
import queue
import time
import random
import math

# --- KONFIGURATION ---
VIDEO_ID = "HIER_DEINE_VIDEO_ID" 
COLS = 13
BLOCK_SIZE = 50
# Wir berechnen die Breite automatisch:
WIDTH = BLOCK_SIZE * COLS 
HEIGHT = 1000
FPS = 60


SCROLL_SPEED = 1.0

# Limiter
MAX_PICKAXES = 3    
SPAWN_COOLDOWN = 100    

# Farben & Fonts
UI_BG = (0, 0, 0, 180)
TEXT_COLOR = (255, 255, 255)

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
    def __init__(self, x, y, color):
        self.rect = pygame.Rect(x, y, 6, 6) # Etwas größere Partikel
        self.color = color
        self.vel_x = random.uniform(-5, 5)
        self.vel_y = random.uniform(-5, 5)
        self.gravity = 0.5
        self.life = random.randint(20, 40)

    def update(self):
        self.vel_y += self.gravity
        self.rect.x += self.vel_x
        self.rect.y += self.vel_y
        self.life -= 1

    def draw(self, screen):
        if self.life > 0:
            pygame.draw.rect(screen, self.color, self.rect)

# --- NEU: TNT KLASSE ---
class PhysicsTNT:
    def __init__(self, x, y, image):
        self.image = image
        self.rect = self.image.get_rect(center=(x, y))
        self.vel_x = random.uniform(-2, 2)
        self.vel_y = -5 
        self.gravity = 0.5
        self.friction = 0.99 
        self.bounce = -0.5
        self.timer = 120 # 2 Sekunden Zündschnur (bei 60 FPS)
        self.explode_now = False # Flag für Explosion
        
        # Pulsieren Effekt
        self.scale_dir = 1
        self.scale = 1.0

    def update(self, blocks):
        # Physik
        self.vel_y += self.gravity
        self.vel_x *= self.friction
        self.rect.x += self.vel_x
        self.rect.y += self.vel_y
        
        # Timer runterzählen
        self.timer -= 1
        
        # Pulsieren (Visueller Effekt kurz vor Explosion)
        if self.timer < 60: # Letzte Sekunde
            if self.timer % 10 == 0: # Blinken simulieren
                self.scale = 1.2 if self.scale == 1.0 else 1.0

        if self.timer <= 0:
            self.explode_now = True

        # Kollisionen (TNT bleibt liegen)
        for block in blocks:
            if block.active and self.rect.colliderect(block.rect):
                if abs(self.rect.bottom - block.rect.top) < 20 and self.vel_y > 0:
                    self.vel_y *= self.bounce
                    self.rect.bottom = block.rect.top
                    self.vel_x *= 0.8 # Reibung am Boden
                elif abs(self.rect.right - block.rect.left) < 20 or abs(self.rect.left - block.rect.right) < 20:
                    self.vel_x *= -0.8

        if self.rect.y > HEIGHT + 100: 
            self.explode_now = False # Verschwindet ohne Schaden wenn es rausfällt

    def draw(self, screen):
        # Zeichnen mit Skalierung (für den Pumpeffekt)
        if self.scale != 1.0:
            w = int(self.rect.width * self.scale)
            h = int(self.rect.height * self.scale)
            scaled_img = pygame.transform.scale(self.image, (w, h))
            new_rect = scaled_img.get_rect(center=self.rect.center)
            screen.blit(scaled_img, new_rect)
        else:
            screen.blit(self.image, self.rect)


class PhysicsPickaxe:
    def __init__(self, x, y, image):
        self.image = image
        self.original_image = image # Wichtig für saubere Rotation
        self.rect = self.image.get_rect(center=(x, y))
        self.vel_x = random.uniform(-3, 3)
        self.vel_y = -8 
        self.gravity = 0.5
        self.friction = 0.99 
        self.bounce = -0.6 
        self.angle = random.randint(0, 360)
        self.rot_speed = random.uniform(-15, 15)
        self.active = True
        
        # Berechne die Grenzen der Bedrock-Wände
        # Links: Eine Blockbreite (64)
        # Rechts: Fensterbreite - Eine Blockbreite (500 - 64 = 436)
        self.min_x = BLOCK_SIZE 
        self.max_x = WIDTH - BLOCK_SIZE

    def update(self, blocks, particles_list):
        self.vel_y += self.gravity
        self.vel_x *= self.friction
        
        # Bewegung anwenden
        self.rect.x += self.vel_x
        self.rect.y += self.vel_y
        
        # --- 1. HARTE GRENZEN (Bedrock Wände) ---
        # Verhindert, dass die Hacke links in den Bedrock fliegt
        if self.rect.left < self.min_x:
            self.rect.left = self.min_x # Rausdrücken
            self.vel_x *= -0.8 # Abprallen
            self.rot_speed *= -0.5 # Rotation bremsen/ändern bei Wandkontakt
            
        # Verhindert, dass die Hacke rechts in den Bedrock fliegt
        if self.rect.right > self.max_x:
            self.rect.right = self.max_x # Rausdrücken
            self.vel_x *= -0.8 # Abprallen
            self.rot_speed *= -0.5

        # --- ROTATION ---
        self.angle = (self.angle + self.rot_speed) % 360
        self.rot_image = pygame.transform.rotate(self.original_image, self.angle)
        self.display_rect = self.rot_image.get_rect(center=self.rect.center)

        # WICHTIG: Nach Rotation prüfen, ob wir wieder in der Wand sind
        # (Weil das rotierte Bild breiter sein kann als das gerade)
        if self.display_rect.left < self.min_x:
            diff = self.min_x - self.display_rect.left
            self.rect.x += diff # Das Haupt-Rect verschieben
            self.display_rect.left = self.min_x # Nur für Anzeige korrigieren
            self.vel_x = abs(self.vel_x) * 0.5 + 2 # Impuls weg von der Wand
            
        elif self.display_rect.right > self.max_x:
            diff = self.display_rect.right - self.max_x
            self.rect.x -= diff
            self.display_rect.right = self.max_x
            self.vel_x = -abs(self.vel_x) * 0.5 - 2

        # --- KOLLISION MIT BLÖCKEN ---
        for block in blocks:
            # Wir prüfen nur Kollision, wenn der Block aktiv ist UND kein Bedrock ist
            # (Bedrock Kollision machen wir ja oben über die harten Grenzen min_x/max_x)
            if block.active and not block.is_bedrock and self.rect.colliderect(block.rect):
                
                # Partikel & Schaden Logik
                p_color = (100, 100, 100) 
                if "diamond" in block.type: p_color = (0, 255, 255)
                elif "gold" in block.type: p_color = (255, 215, 0)
                elif "dirt" in block.type: p_color = (139, 69, 19)
                
                if abs(self.vel_y) > 2 or abs(self.vel_x) > 2:
                    block.hp -= 15
                    for _ in range(3):
                        particles_list.append(Particle(self.rect.centerx, self.rect.centery, p_color))

                # ABPRALLEN (Nur an Spiel-Blöcken)
                collision = False
                
                # Wir berechnen, wie tief wir eingedrungen sind
                overlap_left = self.rect.right - block.rect.left
                overlap_right = block.rect.right - self.rect.left
                overlap_top = self.rect.bottom - block.rect.top
                overlap_bottom = block.rect.bottom - self.rect.top

                # Finde die kleinste Überlappung (das ist die Seite, von der wir kamen)
                min_overlap = min(overlap_left, overlap_right, overlap_top, overlap_bottom)

                if min_overlap == overlap_top and self.vel_y > 0: # Von Oben
                    self.rect.bottom = block.rect.top
                    self.vel_y *= self.bounce
                    collision = True
                elif min_overlap == overlap_bottom and self.vel_y < 0: # Von Unten
                    self.rect.top = block.rect.bottom
                    self.vel_y *= self.bounce
                    collision = True
                elif min_overlap == overlap_left and self.vel_x > 0: # Von Links
                    self.rect.right = block.rect.left
                    self.vel_x *= -0.8
                    collision = True
                elif min_overlap == overlap_right and self.vel_x < 0: # Von Rechts
                    self.rect.left = block.rect.right
                    self.vel_x *= -0.8
                    collision = True

                if collision:
                    self.rot_speed = -self.rot_speed * 0.5 + random.uniform(-5, 5)
                    self.vel_x += random.uniform(-1, 1)

        if self.rect.y > HEIGHT + 100: 
            self.active = False

    def draw(self, screen):
        # Wir zeichnen das rotierte Bild an der (eventuell korrigierten) Position
        screen.blit(self.rot_image, self.display_rect)


# --- GAME KLASSE ---
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Infinite Miner Final")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 16, bold=True)
        self.big_font = pygame.font.SysFont("Arial", 30, bold=True)
        
        self.particles = [] 
        self.tnts = [] 
        self.screen_shake = 0 
        
        # --- HINTERGRUND ---
        try:
            bg_raw = pygame.image.load("assets/images/wp7269751-minecraft-3d-wallpapers.jpg").convert()
            scale_factor = HEIGHT / bg_raw.get_height()
            new_width = int(bg_raw.get_width() * scale_factor)
            bg_scaled = pygame.transform.scale(bg_raw, (new_width, HEIGHT))
            x_offset = (WIDTH - new_width) // 2
            self.background = pygame.Surface((WIDTH, HEIGHT))
            self.background.blit(bg_scaled, (x_offset, 0))
        except:
            self.background = pygame.Surface((WIDTH, HEIGHT))
            self.background.fill((100, 149, 237))

        # --- SOUNDS LADEN ---
        pygame.mixer.init() # Mixer starten
        
        self.sfx = {}
        try:
            # Lautstärke: 0.0 bis 1.0 (0.3 ist angenehm, 1.0 ist sehr laut)
            self.sfx['hit'] = pygame.mixer.Sound("assets/sounds/hit.wav")
            self.sfx['hit'].set_volume(0.2) 
            
            self.sfx['break'] = pygame.mixer.Sound("assets/sounds/break.wav")
            self.sfx['break'].set_volume(0.3)
            
            self.sfx['explode'] = pygame.mixer.Sound("assets/sounds/tnt.wav")
            self.sfx['explode'].set_volume(0.4)
        except Exception as e:
            print(f"Sound-Fehler: {e}")
            # Fallback: Leere Sounds erstellen, damit das Spiel nicht abstürzt
            # (Dummy-Klasse, die nichts tut)
            class DummySound: 
                def play(self): pass
                def set_volume(self, v): pass
            self.sfx['hit'] = DummySound()
            self.sfx['break'] = DummySound()
            self.sfx['explode'] = DummySound()

        # --- BLOCK DEFINITIONEN & ICONS ---
        # "file": Das Bild für den Block im Spiel
        # "icon": Das Bild für das Inventar (Ingot, Gem, etc.)
        self.block_types = {
            "stone":       {"hp": 100, "rarity": 60, "file": "stone",       "icon": "stone"},
            "dirt":        {"hp": 50,  "rarity": 20, "file": "dirt",        "icon": "dirt"},
            "coal_ore":    {"hp": 150, "rarity": 10, "file": "coal_ore",    "icon": "coal"},
            "copper_ore":  {"hp": 200, "rarity": 8,  "file": "copper_ore",  "icon": "copper_ingot"}, # Neu!
            "iron_ore":    {"hp": 250, "rarity": 6,  "file": "iron_ore",    "icon": "iron_ingot"},
            "gold_ore":    {"hp": 400, "rarity": 3,  "file": "gold_ore",    "icon": "gold_ingot"},
            "redstone_ore":{"hp": 300, "rarity": 4,  "file": "redstone_ore","icon": "redstone"},     # Neu!
            "diamond_ore": {"hp": 800, "rarity": 1,  "file": "diamond_ore", "icon": "diamond"},
            "emerald_ore": {"hp": 1000,"rarity": 0.5,"file": "emerald_ore", "icon": "emerald"},
            "bedrock":     {"hp": 9999,"rarity": 0,  "file": "bedrock",     "icon": "bedrock"},
            "tnt_side":    {"hp": 0,   "rarity": 0,  "file": "tnt_side",    "icon": "tnt_side"}
        }

        # Assets laden (Blöcke UND Icons getrennt)
        self.assets = {}      # Für die Spiel-Blöcke
        self.ui_assets = {}   # Für das Inventar
        
        for key, data in self.block_types.items():
            # 1. Block Bild laden
            try:
                img = pygame.image.load(f"assets/images/{data['file']}.png").convert_alpha()
                self.assets[key] = pygame.transform.scale(img, (BLOCK_SIZE, BLOCK_SIZE))
            except:
                s = pygame.Surface((BLOCK_SIZE, BLOCK_SIZE))
                s.fill((255, 0, 255))
                self.assets[key] = s
            
            # 2. Icon Bild laden
            try:
                icon_img = pygame.image.load(f"assets/images/{data['icon']}.png").convert_alpha()
                # Icons skalieren wir etwas kleiner für die GUI
                self.ui_assets[key] = pygame.transform.scale(icon_img, (25, 25))
            except:
                # Falls Icon fehlt, nimm das Block-Bild als Fallback
                self.ui_assets[key] = pygame.transform.scale(self.assets[key], (25, 25))

        # Pickaxe & Cracks laden
        self.pickaxe_img = pygame.image.load("assets/images/diamond_pickaxe.png").convert_alpha()
        # Größe anpassen basierend auf Blockgröße
        pick_size = int(BLOCK_SIZE * 0.8)
        self.pickaxe_img = pygame.transform.scale(self.pickaxe_img, (pick_size, pick_size))
        
        self.crack_images = []
        for i in range(10):
            try:
                img = pygame.image.load(f"assets/images/destroy_stage_{i}.png").convert_alpha()
                self.crack_images.append(pygame.transform.scale(img, (BLOCK_SIZE, BLOCK_SIZE)))
            except: pass

        self.blocks = []
        self.pickaxes = []
        self.last_spawn_time = 0
        self.inventory = {key: 0 for key in self.block_types if key not in ["bedrock", "tnt_side"]}
        self.current_y_level = 64 
        self.cols = COLS
        
        for i in range(10): 
            self.spawn_row(offset_y=i*BLOCK_SIZE + 200)

    def spawn_row(self, offset_y=None):
        if offset_y is None:
            if self.blocks:
                lowest_block = max(self.blocks, key=lambda b: b.rect.y)
                offset_y = lowest_block.rect.y + BLOCK_SIZE
            else:
                offset_y = HEIGHT

        # Automatische Breite berechnen, damit es zentriert ist
        grid_width = self.cols * BLOCK_SIZE
        start_x = (WIDTH - grid_width) // 2
        
        spawnable_ores = [k for k, v in self.block_types.items() if v["rarity"] > 0]
        weights = [self.block_types[k]["rarity"] for k in spawnable_ores]

        for c in range(self.cols):
            x = start_x + c * BLOCK_SIZE
            if c == 0 or c == self.cols - 1:
                b_type = "bedrock"
                hp = 999999
                is_bedrock = True
            else:
                is_bedrock = False
                b_type = random.choices(spawnable_ores, weights=weights, k=1)[0]
                hp = self.block_types[b_type]["hp"]
            
            b = Block(x, offset_y, b_type, self.assets[b_type], hp, is_bedrock)
            self.blocks.append(b)
        
        if offset_y is None or offset_y > HEIGHT:
            self.current_y_level -= 1

    def update(self):
        # 1. Scrolling
        move_speed = SCROLL_SPEED
        if self.blocks and self.blocks[0].rect.y > 200:
            move_speed = 3.0 
            
        for b in self.blocks:
            b.rect.y -= move_speed
        
        # TNTs müssen auch scrollen, wenn sie auf dem Boden liegen (einfache Annäherung)
        for tnt in self.tnts:
             if tnt.vel_y == 0 or abs(tnt.vel_y) < 0.1: # Wenn es liegt
                 tnt.rect.y -= move_speed

        # 2. Spawnen
        lowest_y = 0
        if self.blocks: lowest_y = max(b.rect.y for b in self.blocks)
        if lowest_y < HEIGHT: self.spawn_row()

        # 3. Cleanup
        self.blocks = [b for b in self.blocks if b.rect.y + BLOCK_SIZE > -50]

        # 4. Block Status Check & Inventar
        for b in self.blocks:
            if not b.active: continue 
            if b.hp <= 0 and not b.is_bedrock:
                b.active = False
                if b.type in self.inventory: self.inventory[b.type] += 1
                else: self.inventory[b.type] = 1

        # 5. Spitzhacken
        for p in self.pickaxes[:]:
            p.update(self.blocks, self.particles)
            if not p.active:
                self.pickaxes.remove(p)

        # 6. TNT
        for tnt in self.tnts[:]:
            tnt.update(self.blocks)
            if tnt.explode_now:
                self.screen_shake = 30
                # Partikel
                for _ in range(20):
                     self.particles.append(Particle(tnt.rect.centerx, tnt.rect.centery, (255, 0, 0)))
                     self.particles.append(Particle(tnt.rect.centerx, tnt.rect.centery, (255, 255, 255)))
                
                # Schaden
                center_x, center_y = tnt.rect.centerx, tnt.rect.centery
                for b in self.blocks:
                    if b.active and not b.is_bedrock:
                        dist = ((b.rect.centerx - center_x)**2 + (b.rect.centery - center_y)**2)**0.5
                        if dist < 250:
                            b.hp = 0
                self.tnts.remove(tnt)

        # 7. Partikel
        for p in self.particles[:]:
            p.update()
            if p.life <= 0:
                self.particles.remove(p)

        if self.screen_shake > 0:
            self.screen_shake -= 1

    def draw(self):
        shake_x = 0
        shake_y = 0
        if self.screen_shake > 0:
            shake_x = random.randint(-2, 3)
            shake_y = random.randint(-2,3)

        self.screen.blit(self.background, (shake_x, shake_y))

        # Bedrock Ränder
        grid_width = self.cols * BLOCK_SIZE
        start_x = (WIDTH - grid_width) // 2
        end_x = start_x + grid_width
        bedrock_img = self.assets['bedrock']
        
        if start_x > 0:
            for y in range(0, HEIGHT, BLOCK_SIZE):
                for x in range(0, start_x, BLOCK_SIZE):
                    self.screen.blit(bedrock_img, (x + shake_x, y + shake_y))
        if end_x < WIDTH:
            for y in range(0, HEIGHT, BLOCK_SIZE):
                for x in range(end_x, WIDTH, BLOCK_SIZE):
                    self.screen.blit(bedrock_img, (x + shake_x, y + shake_y))

        # Blöcke
        for b in self.blocks:
            if b.active:
                draw_rect = b.rect.move(shake_x, shake_y)
                self.screen.blit(b.image, draw_rect)
                if b.hp < b.max_hp and not b.is_bedrock:
                    idx = int((1 - b.hp/b.max_hp) * 9)
                    if idx < len(self.crack_images):
                        self.screen.blit(self.crack_images[idx], draw_rect)

        # TNT & Hacken
        for tnt in self.tnts:
            tnt.rect.x += shake_x
            tnt.rect.y += shake_y
            tnt.draw(self.screen)
            tnt.rect.x -= shake_x
            tnt.rect.y -= shake_y

        for p in self.pickaxes:
            p.draw(self.screen)

        for p in self.particles:
            p.rect.x += shake_x
            p.draw(self.screen)
            p.rect.x -= shake_x 

        self.draw_ui()
        pygame.display.flip()

    def draw_ui(self):
        # Y-Level Anzeige
        pygame.draw.rect(self.screen, UI_BG, (WIDTH - 120, HEIGHT - 60, 100, 40))
        y_txt = self.big_font.render(f"Y: {self.current_y_level}", True, (50, 255, 50))
        self.screen.blit(y_txt, (WIDTH - 110, HEIGHT - 55))

        # Inventar (Links)
        y_off = 20
        # Sortieren: Wir zeigen nur Items an, die auch im "block_types" definiert sind
        for name, count in self.inventory.items():
            # Überspringe Bedrock/TNT im Inventar
            if name == "bedrock" or name == "tnt_side": continue
            
            # Hintergrund Kasten
            pygame.draw.rect(self.screen, UI_BG, (10, y_off-5, 100, 35))
            
            # ICON ZEICHNEN (Das ist neu!)
            # Wir holen das Icon aus ui_assets, nicht das Block-Bild
            if name in self.ui_assets:
                self.screen.blit(self.ui_assets[name], (15, y_off))
            
            # Zahl zeichnen
            txt = self.font.render(f"{count}", True, TEXT_COLOR)
            self.screen.blit(txt, (50, y_off + 2)) # +2 für Zentrierung
            
            y_off += 40

    def handle_input(self, cmd):
        current_time = pygame.time.get_ticks()
        
        if cmd == "HIT_BLOCK":
            if len(self.pickaxes) < MAX_PICKAXES and (current_time - self.last_spawn_time > SPAWN_COOLDOWN):
                # Zufällige X-Position innerhalb des Grids
                grid_width = self.cols * BLOCK_SIZE
                start_x = (WIDTH - grid_width) // 2
                x = random.randint(start_x + 20, start_x + grid_width - 20)
                
                self.pickaxes.append(PhysicsPickaxe(x, -50, self.pickaxe_img))
                self.last_spawn_time = current_time
        
        elif cmd == "SPAWN_TNT":
            grid_width = self.cols * BLOCK_SIZE
            start_x = (WIDTH - grid_width) // 2
            x = random.randint(start_x + 20, start_x + grid_width - 20)
            
            tnt_img = self.assets['tnt_side'] # Wir nutzen tnt_side als Bild
            self.tnts.append(PhysicsTNT(x, -50, tnt_img))

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

# --- HAUPTPROGRAMM ---
if __name__ == "__main__":
    q = queue.Queue()
    
    def fake_spammer():
        while True:
            time.sleep(0.02) 
            q.put("HIT_BLOCK")
            if random.random() < 0.01: q.put("SPAWN_TNT")

    threading.Thread(target=fake_spammer, daemon=True).start()
    
    game = Game()
    game.run(q)