"""
The Lifelong Quiz - Configuration
All tunable constants for the quiz game.
"""

import os as _os
from pathlib import Path as _Path


def _load_dotenv(path):
    """Read KEY=VALUE lines from a gitignored .env file into os.environ (existing vars win)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                _os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv(_Path(__file__).resolve().parent.parent / ".env")

# ==========================================
# WINDOW
# ==========================================
# QUIZ_LAYOUT=vertical renders a 9:16 phone/Shorts show (quiz/ui_vertical.py); default is 16:9 TV
LAYOUT = _os.environ.get("QUIZ_LAYOUT", "horizontal").strip().lower()
VERTICAL = LAYOUT == "vertical"
SCREEN_WIDTH, SCREEN_HEIGHT = (1080, 1920) if VERTICAL else (1920, 1080)
FPS = int(_os.environ.get("QUIZ_FPS", "60"))  # headless servers render at the stream rate (30)
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
# A show is an endless cycle of matches: LOBBY -> INTRO -> 10 x (ASKING -> LOCKING -> REVEALING) -> PODIUM
# The QUIZ_*_SECONDS environment variables (or .env) override these defaults.
def _env_num(name, default):
    try:
        return max(1, int(_os.environ.get(name, default)))
    except ValueError:
        return default


MATCH_LENGTH = 10
LOBBY_TIME = _env_num("QUIZ_LOBBY_SECONDS", 30)          # category vote, !ready check-ins
INTRO_TIME = 4             # "MATCH 15" title sting
BUILDUP_TIME = _env_num("QUIZ_BUILDUP_SECONDS", 4)       # tension beat before every question
BUILDUP_TIME_BIG = max(BUILDUP_TIME, 6)                  # before the final and a difficulty step-up
QUESTION_DISPLAY_TIME = _env_num("QUIZ_QUESTION_SECONDS", 30)
LATE_ANSWER_GRACE = _env_num("QUIZ_LATE_SECONDS", 4)     # "time's up" while late chat messages still arrive
REVEAL_AT = 1.1   # seconds into the reveal before the right answer lights up (answer split counts up first)
REVEAL_DISPLAY_TIME = _env_num("QUIZ_REVEAL_SECONDS", 8)
PODIUM_TIME = _env_num("QUIZ_PODIUM_SECONDS", 14)
LIGHTNING_QUESTION = 5     # fixed event slots inside a match
BONUS_QUESTIONS = (3, 7)   # first blood or jackpot
FINAL_QUESTION_MULT = 2.0  # the last question pays double
# Special rounds (quiz/special.py, packs/special_*.json): question number -> round type
SPECIAL_SLOTS = {2: "higher_lower", 4: "majority", 6: "odd_one_out"}
LONELY_CHANCE = 0.3        # share of Crowd Mind slots secretly played as Lonely Answer (least picked wins)
HALF_STREAK = 3            # 50:50 joker ("!half 1 3"): once per match from this answer streak in the match
DOUBLE_AFTER = 5           # "!double": once per match after this many answers in it...
DOUBLE_STAKE = 20          # ...x2 if right, or this many match points lost if wrong (never below 0)
CROWD_MIN_REAL = 3         # Crowd Mind needs this many real (non-bot) answers, or the question is void
DIFFICULTY_RAMP = {1: "easy", 2: "easy", 3: "easy", 4: "medium", 5: "medium",
                   6: "medium", 7: "medium", 8: "hard", 9: "hard", 10: "hard"}
# Match formats rotate by match number (quiz/special.py FORMATS), so no two matches in a row share one
FORMAT_ROTATION = ("classic", "speed", "survivors", "teams")
SURVIVOR_POT = 200         # Survivors: every answer right, and the survivors split this...
SURVIVOR_MIN = 20          # ...but each gets at least this
TEAM_WIN_BONUS = 15        # Teams: every member who played on the team with the higher average
# Community goal: chat's real right answers on Q1-Q9 reach this many per player of the last match
# (at least the minimum), and every right answer on Q10 earns JACKPOT_BONUS on top
COMMUNITY_GOAL_PER_PLAYER = 5
COMMUNITY_GOAL_MIN = 10
DIFFICULTY_TIERS = ("easy", "medium", "hard")   # a dry tier falls back to its nearest neighbour, lower first
DIFFICULTY_MULT = {"easy": 1.0, "medium": 1.25, "hard": 1.5}   # on the question's shown difficulty

# ==========================================
# SCORING
# ==========================================
BASE_POINTS = 10
SPEED_BONUS_TIER1_THRESHOLD = 0.25  # first 25% of time -> 2x
SPEED_BONUS_TIER2_THRESHOLD = 0.50  # first 50% of time -> 1.5x
SPEED_BONUS_TIER1_MULT = 2.0
SPEED_BONUS_TIER2_MULT = 1.5
# Combo: the streak multiplier steps up at these streaks (right answers in a row before this one)
COMBO_STEPS = ((3, 1.3), (5, 1.5), (10, 2.0), (15, 2.5), (25, 3.0))

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
OTDB_BATCH_SIZE = 50  # max supported by OTDB API
OTDB_MIN_CACHE = 10   # prefetch aggressively for variety
OTDB_REQUEST_COOLDOWN = 6.0
OTDB_SEEN_EXPIRY = 14400  # 4 hours before a seen question can reappear
NUM_ANSWER_OPTIONS = 4

# ==========================================
# VOTABLE CATEGORIES
# ==========================================
RECENT_CATEGORIES = 3   # the vote never offers the last 3 voted categories
VOTABLE_CATEGORIES = {
    9: "General Knowledge",
    10: "Books",
    11: "Film",
    12: "Music",
    13: "Musicals & Theatre",
    14: "Television",
    15: "Video Games",
    16: "Board Games",
    17: "Science & Nature",
    18: "Computers",
    19: "Mathematics",
    20: "Mythology",
    21: "Sports",
    22: "Geography",
    23: "History",
    24: "Politics",
    25: "Art",
    26: "Celebrities",
    27: "Animals",
    28: "Vehicles",
    29: "Comics",
    30: "Gadgets",
    31: "Anime & Manga",
    32: "Cartoons & Animation",
}

# ==========================================
# CHAT / YOUTUBE CONNECTION
# ==========================================
# Set the VIDEO ID of your live stream to read chat from it.
# Find it in YouTube Studio: the part after watch?v= in your stream URL.
# Example: VIDEO_ID = "dQw4w9WgXcQ"
# Leave empty to auto-detect from the channels below.
VIDEO_ID = _os.environ.get("QUIZ_VIDEO_ID", "")

# YouTube channels whose /live chat is read (tried in order)
CHANNEL_IDS = [
    "UCnv51D67E_oLPfHmQU_6prw",  # The Lifelong Quiz (primary)
    "UCmDgp2YS176ot2n7nFpLRzA",  # Chat vs Bedrock
]
if _os.environ.get("QUIZ_CHANNEL_IDS"):  # comma-separated, e.g. only the channel the stream key belongs to
    CHANNEL_IDS = [c.strip() for c in _os.environ["QUIZ_CHANNEL_IDS"].split(",") if c.strip()]

# ==========================================
# FILLER BOTS
# ==========================================
MIN_PLAYERS = _env_num("QUIZ_MIN_PLAYERS", 4) if _os.environ.get("QUIZ_MIN_PLAYERS") != "0" else 0
# Bots fill matches until this many real players take part (0 = no bots)
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
DB_PATH_OFFLINE = str(_ROOT / "data" / "quiz_offline.db")  # fake chat users never touch the live DB
DB_SAVE_INTERVAL = 10  # seconds

# ==========================================
# ASSETS
# ==========================================
FONT_DIR = _ROOT / "shared" / "fonts"
FONT_PATH = str(FONT_DIR / "minecraft.ttf")  # Infinite Miner only

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

# Mini events (only one can trigger per round, checked in priority order)
LIGHTNING_ROUND_CHANCE = 0.08   # 8% chance: shorter time, 1.5x points
JACKPOT_CHANCE = 0.10           # 10% chance: random correct player wins jackpot
FIRST_BLOOD_CHANCE = 0.15       # 15% chance: fastest correct player gets bonus
LIGHTNING_TIME = _env_num("QUIZ_LIGHTNING_SECONDS", 22)   # seconds (instead of the normal 30)
LIGHTNING_MULT = 1.5
JACKPOT_BONUS = 25              # flat bonus for jackpot winner
FIRST_BLOOD_BONUS = 15          # flat bonus for first correct answerer

# Participation rewards
PARTICIPATION_MILESTONES = [5, 10, 20, 50, 100]  # rounds participated in a row
PARTICIPATION_BONUS = 10        # points per milestone
STREAK_SHIELD_THRESHOLD = 5    # correct streak needed to earn a shield

# Command cooldown
COMMAND_COOLDOWN = 30           # seconds between score/clear commands per player

# Chat feed
CHAT_FEED_MAX = 6           # show last N events on screen
CHAT_FEED_DURATION = 5.0    # seconds each message stays visible

# Competition alerts
COMPETITION_ALERT_THRESHOLD = 20  # points gap to trigger "close race" alert

# ==========================================
# YOUTUBE STREAMING (via FFmpeg)
# ==========================================

STREAM_ENABLED = True              # Set True to stream to YouTube Live
# Stream key comes from the environment or the gitignored .env file (see .env.example).
YOUTUBE_STREAM_KEY = _os.environ.get("QUIZ_STREAM_KEY", "")
# Audio source as "format:device", e.g. "pulse:quiz_sink.monitor". Empty = silent audio track.
STREAM_AUDIO_INPUT = _os.environ.get("QUIZ_AUDIO_INPUT", "")
# Optional output override (e.g. a local .flv file for testing). Empty = YouTube RTMPS ingest.
STREAM_OUTPUT = _os.environ.get("QUIZ_STREAM_OUTPUT", "")
STREAM_FPS = 30                     # Stream output framerate (30fps is ideal for quiz content)
# Output size and bitrate. 720p at 3000k needs about half the CPU and upload of 1080p at 6000k.
# Game audio boost in dB applied by FFmpeg (the procedural sounds are quiet next to other streams).
# Moderator bots that post in chat (Nightbot timers) are never players
CHAT_BOTS = {"nightbot", "streamelements", "moobot", "streamlabs"}
STREAM_AUDIO_GAIN_DB = float(_os.environ.get("QUIZ_AUDIO_GAIN_DB", "0"))
STREAM_HEIGHT = int(_os.environ.get("QUIZ_STREAM_HEIGHT", "1080"))   # the short side: 720 = 1280x720 or 720x1280
STREAM_OUT_HEIGHT = STREAM_HEIGHT * 16 // 9 // 2 * 2 if VERTICAL else STREAM_HEIGHT
STREAM_BITRATE = _os.environ.get("QUIZ_STREAM_BITRATE", "6000k" if STREAM_HEIGHT >= 1080 else "3000k")
FFMPEG_PATH = "ffmpeg"              # Path to ffmpeg binary (auto-downloaded to scripts/)
