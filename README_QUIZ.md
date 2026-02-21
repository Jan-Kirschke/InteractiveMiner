# The Lifelong Quiz

A 24/7 YouTube livestream quiz game where viewers compete in trivia by typing answers in the chat. Built with Python, Pygame, and pytchat.

## How It Works

The Lifelong Quiz runs as a continuous loop on a YouTube livestream. Questions from the Open Trivia Database appear on screen at regular intervals. Viewers answer by typing `1`, `2`, `3`, or `4` in the YouTube chat. Points accumulate permanently in a SQLite database, so progress is never lost - even across restarts.

Every 5 rounds, players vote on the next trivia category. The game tracks streaks, awards achievements, and creates a competitive atmosphere with real-time leaderboards and close-race alerts.

## Quick Start

### Prerequisites
- Python 3.10+
- A YouTube livestream (for live mode)

### Install & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run in offline dev mode (fake chat bots)
python quiz_game.py

# Run connected to a YouTube livestream
python quiz_game.py YOUR_VIDEO_ID
```

Or use the batch files:
- **`start_quiz.bat`** - Offline mode with fake chat bots
- **`start_quiz_live.bat`** - Prompts for YouTube video ID, then connects

### Finding Your Video ID
The video ID is the part after `v=` in a YouTube URL:
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
                                 ^^^^^^^^^^^^
                                 This is the video ID
```

## Chat Commands

| Command | What It Does |
|---------|-------------|
| `1` | Select answer option 1 (or vote for category 1) |
| `2` | Select answer option 2 (or vote for category 2) |
| `3` | Select answer option 3 (or vote for category 3) |
| `4` | Select answer option 4 (or vote for category 4) |
| `reset` | Clear your own score and start fresh |

## Host Controls (Keyboard)

| Key | Action |
|-----|--------|
| `ESC` | Quit the game |
| `F1` | Skip current phase (debug) |

## Game Flow

The game cycles through these phases:

```
ASKING (30s) -> REVEALING (8s) -> LEADERBOARD (10s) -> ASKING ...
                                                        |
                                         (every 5 rounds)
                                                        |
                                                   THEME VOTE (20s) -> ASKING
```

### 1. ASKING (30 seconds)
A trivia question appears with 4 answer options. Players type `1`-`4` in chat. Each player can only answer once per question. The timer bar counts down and turns red when time is low.

### 2. REVEALING (8 seconds)
The correct answer glows green, wrong answers fade to red. A results banner shows how many players got it right and who was fastest. Gold particles celebrate correct answers.

### 3. LEADERBOARD (10 seconds)
The top 10 players are displayed with their scores, streaks, and rank badges. Rows animate in with a stagger effect. A close-race alert appears if two players are neck-and-neck.

### 4. THEME VOTE (every 5 rounds, 20 seconds)
Four random trivia categories appear. Players type `1`-`4` to vote. The category with the most votes determines the next 5 rounds of questions. Live vote bars show the standings in real-time.

## Scoring System

### Base Points
Every correct answer earns **10 base points**.

### Speed Bonus
Answer faster for more points:
| Timing | Multiplier |
|--------|-----------|
| First 25% of time (< 7.5s) | **2x** |
| First 50% of time (< 15s) | **1.5x** |
| Later than 50% | **1x** |

### Streak Bonus
Consecutive correct answers build a streak multiplier:
- Each consecutive correct answer adds **+10%** to your multiplier
- Maximum multiplier: **3x** (at 20 streak)
- One wrong answer resets your streak to 0

### Comeback Bonus
If you get 3+ wrong answers in a row and then answer correctly, you earn **+5 bonus points** and a "Comeback Kid" notification.

### Double Points Rounds
There is a **12% chance** each round is a Double Points round. All points earned during that round are multiplied by 2x. A golden banner announces it.

### Example Scoring
| Scenario | Calculation | Points |
|----------|------------|--------|
| Correct in 3s, no streak | 10 x 2.0 x 1.0 | **20** |
| Correct in 12s, 5-streak | 10 x 1.5 x 1.5 | **22** |
| Correct in 3s, 10-streak, double points | 10 x 2.0 x 2.0 x 2.0 | **80** |

## Ranks

Your rank is based on total accumulated score:

| Score | Rank |
|-------|------|
| 0 - 99 | Bronze |
| 100 - 499 | Silver |
| 500 - 1,499 | Gold |
| 1,500 - 4,999 | Platinum |
| 5,000 - 14,999 | Diamond |
| 15,000+ | Legend |

## Achievements & Events

The game awards achievements shown in the live event feed:

| Achievement | Trigger |
|-------------|---------|
| First Blood | Answer your first question correctly |
| On Fire | 3 correct in a row |
| Unstoppable | 5 correct in a row |
| Legendary Streak | 10 correct in a row |
| GODLIKE | 25 correct in a row |
| Speed Demon | Answer within 2 seconds |
| Comeback Kid | Correct after 3+ wrong answers |
| Rank Up | Reach a new rank tier |
| Centurion | Play 100 rounds |

New players get a welcome message when they first answer.

## Trivia Categories

Questions are fetched from the [Open Trivia Database](https://opentdb.com/) and include:

- General Knowledge
- Film
- Music
- Video Games
- Science & Nature
- Computers
- Sports
- Geography
- History
- Animals
- Anime & Manga

A session token prevents repeat questions. If the API is unavailable, hardcoded fallback questions are used.

## Configuration

All settings are in `quiz_config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `SCREEN_WIDTH` / `SCREEN_HEIGHT` | 1920 x 1080 | Window resolution |
| `FPS` | 60 | Frame rate |
| `QUESTION_DISPLAY_TIME` | 30s | Time to answer each question |
| `REVEAL_DISPLAY_TIME` | 8s | Time showing the correct answer |
| `LEADERBOARD_DISPLAY_TIME` | 10s | Time showing the leaderboard |
| `THEME_VOTE_TIME` | 20s | Time for category voting |
| `ROUNDS_BEFORE_VOTE` | 5 | Questions between each vote |
| `BASE_POINTS` | 10 | Points per correct answer |
| `DOUBLE_POINTS_CHANCE` | 0.12 | Probability of a double points round |
| `DB_SAVE_INTERVAL` | 30s | How often player data is flushed to disk |

## Data Persistence

Player data is stored in `quiz_data.db` (SQLite). The database is:
- Created automatically on first run
- Loaded into memory at startup for fast access
- Flushed to disk every 30 seconds and on shutdown
- Survives across restarts - scores are permanent
- If corrupted, automatically backed up and recreated

## Code Structure

```
quiz_game.py          Entry point
quiz_config.py        All configuration constants
quiz_models.py        Data structures (Player, Question, GameState, etc.)
quiz_db.py            SQLite database with in-memory cache
quiz_chat.py          YouTube chat reader (pytchat) + fake chat fallback
quiz_logic.py         State machine, scoring, question API, theme voting
quiz_ui.py            Pygame renderer with animations and particles
quiz_sounds.py        Procedurally generated sound effects
quiz_controller.py    Main game loop connecting all subsystems
```

### Architecture

```
                    ┌──────────────┐
                    │  quiz_game   │  Entry point
                    └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │  Controller  │  Game loop: events → chat → logic → render
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┬──────────────┐
           │               │               │              │
    ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴─────┐ ┌─────┴──────┐
    │ ChatManager │ │  QuizLogic  │ │  UIManager  │ │   Sounds   │
    │  (pytchat)  │ │(state mach.)│ │  (pygame)   │ │ (generated)│
    └──────┬──────┘ └──────┬──────┘ └────────────┘ └────────────┘
           │               │
     YouTube Chat    ┌─────┴─────┐
                     │  Database  │  SQLite + memory cache
                     └─────┬─────┘
                           │
                    ┌──────┴──────┐
                    │ quiz_data.db│  Persistent storage
                    └─────────────┘
```

### Key Design Decisions

- **In-memory dict + periodic SQLite flush**: Avoids I/O pressure from hundreds of concurrent score updates
- **Background thread for API**: OTDB has ~1-2s response time; non-blocking fetch prevents frame drops
- **Procedural sound generation**: No external sound files needed; all effects are synthesized from sine/square waves
- **Easing functions**: All animations use cubic/back easing for smooth, polished transitions
- **Thread-safe queue**: Chat messages flow from the pytchat thread to the game loop without locks

## Sound Effects

All sounds are procedurally generated at startup (no external files needed):

| Sound | Trigger |
|-------|---------|
| Correct chime | Players answer correctly |
| Wrong buzz | Nobody got it right |
| Timer tick | Timer below 50% |
| Urgent tick | Timer below 25% |
| Fanfare | Leaderboard display / rank up |
| Whoosh | Phase transitions |
| Streak sparkle | Streak milestones |
| Vote blip | New vote received |
| Double points | Double points round activation |

## Dependencies

| Package | Purpose |
|---------|---------|
| `pygame` | Game rendering and audio |
| `pytchat` | YouTube live chat reading |
| `requests` | Open Trivia DB API calls |
| `scrapetube` | YouTube stream discovery (used by mining game) |

## Tips for Running 24/7

1. Use a dedicated machine or VM
2. Run via OBS or similar to capture the Pygame window for the stream
3. Set `VIDEO_ID` in `quiz_config.py` for automatic connection on restart
4. The game auto-reconnects if the chat connection drops
5. Player data persists in `quiz_data.db` across restarts
6. Use `Ctrl+C` or `ESC` for graceful shutdown (saves all data)
