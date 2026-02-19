import pygame
import random
import time
import sys
import scrapetube

from config import *
from utils import safe_load_img, safe_load_snd
from ui import AnnouncementSystem, Atmosphere, LikeStreakSystem, FloatingText
from entities import Particle, Block, HeroPickaxe, PhysicsAnvil, PhysicsPotion, BombEntity, LightningEntity
from bosses import EndermanBoss, HerobrineBoss, create_boss

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
        self.atmosphere = Atmosphere(WIDTH, HEIGHT, safe_load_img)
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