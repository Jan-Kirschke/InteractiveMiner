# --- KONFIGURATION ---
CHANNEL_ID = "UCmDgp2YS176ot2n7nFpLRzA"
COLS = 9
BLOCK_SIZE = 80
WIDTH = BLOCK_SIZE * COLS
HEIGHT = 1280
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