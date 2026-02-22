"""
The Lifelong Quiz - Configuration
All tunable constants for the quiz game.
"""

# ==========================================
# WINDOW
# ==========================================
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
FPS = 60
WINDOW_TITLE = "The Lifelong Quiz"

# ==========================================
# COLORS (dark poker room palette)
# ==========================================
COLOR_BG_DARK = (15, 12, 10)
COLOR_BG_FELT = (20, 45, 25)
COLOR_GOLD = (212, 175, 55)
COLOR_AMBER = (191, 144, 64)
COLOR_CARD_BG = (35, 30, 28)
COLOR_CARD_BORDER = (80, 70, 55)
COLOR_CARD_HIGHLIGHT = (55, 48, 40)
COLOR_CORRECT = (50, 205, 50)
COLOR_WRONG = (180, 40, 40)
COLOR_TEXT_PRIMARY = (240, 235, 220)
COLOR_TEXT_SECONDARY = (160, 150, 130)
COLOR_TEXT_GOLD = (255, 215, 0)
COLOR_TEXT_DIM = (100, 95, 85)
COLOR_TIMER_BAR = (200, 160, 50)
COLOR_TIMER_BAR_LOW = (200, 50, 40)
COLOR_HUD_BG = (10, 8, 6)
COLOR_CONNECTED = (50, 205, 50)
COLOR_DISCONNECTED = (200, 50, 40)
COLOR_SHADOW = (0, 0, 0)

# Rank colors
COLOR_RANK_BRONZE = (205, 127, 50)
COLOR_RANK_SILVER = (192, 192, 192)
COLOR_RANK_GOLD = (255, 215, 0)
COLOR_RANK_PLATINUM = (229, 228, 226)
COLOR_RANK_DIAMOND = (185, 242, 255)
COLOR_RANK_LEGEND = (255, 69, 0)

# ==========================================
# TIMING (seconds)
# ==========================================
QUESTION_DISPLAY_TIME = 30
REVEAL_DISPLAY_TIME = 8
LEADERBOARD_DISPLAY_TIME = 10
THEME_VOTE_TIME = 20
ROUNDS_BEFORE_VOTE = 5
LATE_ANSWER_GRACE = 5  # seconds to accept answers/votes after a phase ends (chat delay)

# ==========================================
# SCORING
# ==========================================
BASE_POINTS = 10
SPEED_BONUS_TIER1_THRESHOLD = 0.25  # first 25% of time -> 2x
SPEED_BONUS_TIER2_THRESHOLD = 0.50  # first 50% of time -> 1.5x
SPEED_BONUS_TIER1_MULT = 2.0
SPEED_BONUS_TIER2_MULT = 1.5
STREAK_BONUS_PER = 0.1  # +10% per consecutive correct
MAX_STREAK_MULT = 3.0

# ==========================================
# RANKS
# ==========================================
RANK_THRESHOLDS = [
    (0, "Bronze"),
    (100, "Silver"),
    (500, "Gold"),
    (1500, "Platinum"),
    (5000, "Diamond"),
    (15000, "Legend"),
]

RANK_COLORS = {
    "Bronze": COLOR_RANK_BRONZE,
    "Silver": COLOR_RANK_SILVER,
    "Gold": COLOR_RANK_GOLD,
    "Platinum": COLOR_RANK_PLATINUM,
    "Diamond": COLOR_RANK_DIAMOND,
    "Legend": COLOR_RANK_LEGEND,
}

# ==========================================
# OPEN TRIVIA DB
# ==========================================
OTDB_BASE_URL = "https://opentdb.com/api.php"
OTDB_TOKEN_URL = "https://opentdb.com/api_token.php"
OTDB_BATCH_SIZE = 10
OTDB_MIN_CACHE = 3
OTDB_REQUEST_COOLDOWN = 6.0
NUM_ANSWER_OPTIONS = 4

# ==========================================
# VOTABLE CATEGORIES
# ==========================================
VOTABLE_CATEGORIES = {
    9: "General Knowledge",
    11: "Film",
    12: "Music",
    15: "Video Games",
    17: "Science & Nature",
    18: "Computers",
    21: "Sports",
    22: "Geography",
    23: "History",
    27: "Animals",
    31: "Anime & Manga",
}

# ==========================================
# CHAT / YOUTUBE CONNECTION
# ==========================================
# Set the VIDEO ID of your live stream to read chat from it.
# Find it in YouTube Studio: the part after watch?v= in your stream URL.
# Example: VIDEO_ID = "dQw4w9WgXcQ"
# Leave empty to auto-detect from the channels below.
VIDEO_ID = ""

# YouTube channels to search for livestreams (tried in order)
# Auto-detection uses HTTP /live page + scrapetube as fallback.
CHANNEL_IDS = [
    "UCnv51D67E_oLPfHmQU_6prw",  # The Lifelong Quiz (primary)
    "UCmDgp2YS176ot2n7nFpLRzA",  # Chat vs Bedrock
]

# How often to retry finding a livestream if none is active (seconds)
STREAM_POLL_INTERVAL = 20

# ==========================================
# FILLER BOTS
# ==========================================
MIN_PLAYERS = 4  # Bots fill lobby until this many real players participate
BOT_DIFFICULTY = {
    "easy":   {"accuracy": 0.25, "speed_min": 0.50, "speed_max": 0.90},
    "medium": {"accuracy": 0.55, "speed_min": 0.25, "speed_max": 0.70},
    "hard":   {"accuracy": 0.70, "speed_min": 0.05, "speed_max": 0.45},
}
# speed = fraction of question time when bot answers (0.0 = instant, 1.0 = deadline)

# ==========================================
# DATABASE
# ==========================================
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent

DB_PATH = str(_ROOT / "data" / "quiz_data.db")
DB_SAVE_INTERVAL = 10  # seconds

# ==========================================
# ASSETS
# ==========================================
FONT_PATH = str(_ROOT / "shared" / "fonts" / "minecraft.ttf")

# ==========================================
# LEADERBOARD
# ==========================================
LEADERBOARD_SIZE = 10

# ==========================================
# PARTICLES
# ==========================================
MAX_PARTICLES = 300

# ==========================================
# ADDICTIVE MECHANICS
# ==========================================
DOUBLE_POINTS_CHANCE = 0.12       # 12% chance per round for double points
DOUBLE_POINTS_MULT = 2.0
COMEBACK_BONUS = 5                # extra points when breaking a 3+ wrong streak
COMEBACK_STREAK_THRESHOLD = 3     # wrong answers in a row before comeback triggers

# Streak milestones that trigger special effects
STREAK_MILESTONES = [3, 5, 10, 15, 25, 50, 100]

# Achievement definitions
ACHIEVEMENTS = {
    "first_blood":   {"name": "First Blood",     "desc": "Answer your first question correctly"},
    "streak_3":      {"name": "On Fire",          "desc": "3 correct answers in a row"},
    "streak_5":      {"name": "Unstoppable",      "desc": "5 correct answers in a row"},
    "streak_10":     {"name": "Legendary Streak",  "desc": "10 correct answers in a row"},
    "streak_25":     {"name": "GODLIKE",           "desc": "25 correct answers in a row"},
    "speed_demon":   {"name": "Speed Demon",      "desc": "Answer within 2 seconds"},
    "comeback_kid":  {"name": "Comeback Kid",     "desc": "Get one right after 3+ wrong"},
    "rank_silver":   {"name": "Rising Star",      "desc": "Reach Silver rank"},
    "rank_gold":     {"name": "Going for Gold",   "desc": "Reach Gold rank"},
    "rank_platinum": {"name": "Elite Player",     "desc": "Reach Platinum rank"},
    "rank_diamond":  {"name": "Diamond Hands",    "desc": "Reach Diamond rank"},
    "rank_legend":   {"name": "Living Legend",     "desc": "Reach Legend rank"},
    "centurion":     {"name": "Centurion",        "desc": "Play 100 rounds"},
}

# Chat feed
CHAT_FEED_MAX = 6           # show last N events on screen
CHAT_FEED_DURATION = 5.0    # seconds each message stays visible

# Competition alerts
COMPETITION_ALERT_THRESHOLD = 20  # points gap to trigger "close race" alert

# ==========================================
# YOUTUBE STREAMING (via FFmpeg)
# ==========================================
STREAM_ENABLED = True              # Set True to stream to YouTube Live
YOUTUBE_STREAM_KEY = "d4t6-3q2b-0hem-5hms-3y37"             # Your YouTube stream key (from YouTube Studio)
STREAM_FPS = 30                     # Stream output framerate (game runs at 60, stream at 30)
STREAM_BITRATE = "4500k"            # Video bitrate for 1080p
FFMPEG_PATH = "ffmpeg"              # Path to ffmpeg binary (auto-downloaded to scripts/)
