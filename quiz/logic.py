"""
The Lifelong Quiz - Game Logic
A show is an endless cycle of matches:
LOBBY (vote, !ready) -> INTRO -> 10 x (ASKING -> LOCKING -> REVEALING) -> PODIUM.
Match points reset every match; weekly and lifetime points keep growing.
"""

import heapq
import math
import time
import html
import random
import re
import threading
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

from quiz.config import (
    REVEAL_AT,
    MATCH_LENGTH, LOBBY_TIME, INTRO_TIME, BUILDUP_TIME, BUILDUP_TIME_BIG, QUESTION_DISPLAY_TIME,
    LATE_ANSWER_GRACE, REVEAL_DISPLAY_TIME, PODIUM_TIME,
    LIGHTNING_QUESTION, BONUS_QUESTIONS, FINAL_QUESTION_MULT, DIFFICULTY_RAMP,
    DIFFICULTY_TIERS, DIFFICULTY_MULT,
    BASE_POINTS, SPEED_BONUS_TIER1_THRESHOLD, SPEED_BONUS_TIER2_THRESHOLD,
    SPEED_BONUS_TIER1_MULT, SPEED_BONUS_TIER2_MULT,
    STREAK_BONUS_PER, MAX_STREAK_MULT,
    OTDB_BASE_URL, OTDB_TOKEN_URL, OTDB_BATCH_SIZE,
    OTDB_MIN_CACHE, OTDB_REQUEST_COOLDOWN, OTDB_SEEN_EXPIRY,
    VOTABLE_CATEGORIES,
    COMEBACK_BONUS, COMEBACK_STREAK_THRESHOLD,
    STREAK_MILESTONES,
    CHAT_FEED_MAX, CHAT_FEED_DURATION,
    MIN_PLAYERS, BOT_DIFFICULTY,
    COLOR_CORRECT, COLOR_TEXT_GOLD, COLOR_AMBER, COLOR_RANK_DIAMOND,
    LIGHTNING_TIME, LIGHTNING_MULT, JACKPOT_BONUS, FIRST_BLOOD_BONUS,
    PARTICIPATION_MILESTONES, PARTICIPATION_BONUS, STREAK_SHIELD_THRESHOLD,
    COMMAND_COOLDOWN, SPECIAL_SLOTS, CROWD_MIN_REAL, LONELY_CHANCE, HALF_STREAK,
)
from quiz.models import (
    GameState, Player, Question, RoundResult, ThemeVoteState, GameEvent, MatchStanding, Duel,
)
from quiz.db import QuizDatabase
from quiz.bank import QuestionBank, REPEAT_WINDOWS, MEASURE_AFTER
from quiz.import_questions import load_items
from quiz.special import SpecialDecks

PACK_DIR = Path(__file__).resolve().parent / "packs"


# Hardcoded fallback questions if API is unavailable (80+ across many categories)
# correct_index is placeholder — options get shuffled before serving
def _q(text, correct, wrong, category="General", difficulty="easy"):
    """Helper: build a Question with correct answer placed at index 0 (shuffled later)."""
    return Question(text, correct, [correct] + wrong, 0, category, difficulty)

FALLBACK_QUESTIONS = [
    # --- Geography ---
    _q("What is the capital of France?", "Paris", ["London", "Berlin", "Madrid"], "Geography"),
    _q("What is the largest ocean on Earth?", "Pacific Ocean", ["Atlantic Ocean", "Indian Ocean", "Arctic Ocean"], "Geography"),
    _q("What is the smallest country in the world?", "Vatican City", ["Monaco", "San Marino", "Liechtenstein"], "Geography"),
    _q("Which country has the longest coastline?", "Canada", ["Russia", "Australia", "Indonesia"], "Geography"),
    _q("What is the tallest mountain in the world?", "Mount Everest", ["K2", "Kangchenjunga", "Mont Blanc"], "Geography"),
    _q("Which river is the longest in the world?", "Nile", ["Amazon", "Yangtze", "Mississippi"], "Geography"),
    _q("What is the capital of Japan?", "Tokyo", ["Osaka", "Kyoto", "Nagoya"], "Geography"),
    _q("Which desert is the largest in the world?", "Sahara", ["Gobi", "Kalahari", "Arabian"], "Geography"),
    _q("In which country would you find Machu Picchu?", "Peru", ["Bolivia", "Chile", "Colombia"], "Geography"),
    _q("What is the capital of Australia?", "Canberra", ["Sydney", "Melbourne", "Brisbane"], "Geography"),
    _q("Which continent has the most countries?", "Africa", ["Asia", "Europe", "South America"], "Geography"),
    _q("What is the deepest ocean trench?", "Mariana Trench", ["Tonga Trench", "Java Trench", "Puerto Rico Trench"], "Geography", "medium"),
    # --- Science ---
    _q("What planet is known as the Red Planet?", "Mars", ["Venus", "Jupiter", "Saturn"], "Science"),
    _q("What element does 'O' represent on the periodic table?", "Oxygen", ["Gold", "Osmium", "Oganesson"], "Science"),
    _q("What is the hardest natural substance on Earth?", "Diamond", ["Gold", "Iron", "Platinum"], "Science", "medium"),
    _q("Which gas do plants absorb from the atmosphere?", "Carbon Dioxide", ["Oxygen", "Nitrogen", "Hydrogen"], "Science"),
    _q("What is the speed of light approximately?", "300,000 km/s", ["150,000 km/s", "500,000 km/s", "1,000,000 km/s"], "Science", "medium"),
    _q("How many bones are in the adult human body?", "206", ["180", "215", "256"], "Science"),
    _q("What planet is closest to the Sun?", "Mercury", ["Venus", "Earth", "Mars"], "Science"),
    _q("What is the chemical symbol for gold?", "Au", ["Ag", "Go", "Gd"], "Science"),
    _q("What is the largest planet in our solar system?", "Jupiter", ["Saturn", "Neptune", "Uranus"], "Science"),
    _q("What is the powerhouse of the cell?", "Mitochondria", ["Nucleus", "Ribosome", "Golgi apparatus"], "Science"),
    _q("What gas makes up most of Earth's atmosphere?", "Nitrogen", ["Oxygen", "Carbon Dioxide", "Argon"], "Science"),
    _q("How many planets are in our solar system?", "8", ["7", "9", "10"], "Science"),
    _q("What is the boiling point of water in Celsius?", "100", ["90", "110", "120"], "Science"),
    _q("Which planet has the most moons?", "Saturn", ["Jupiter", "Uranus", "Neptune"], "Science", "medium"),
    # --- History ---
    _q("In what year did the Titanic sink?", "1912", ["1905", "1920", "1898"], "History"),
    _q("Who was the first person to walk on the Moon?", "Neil Armstrong", ["Buzz Aldrin", "Yuri Gagarin", "John Glenn"], "History"),
    _q("In which year did World War II end?", "1945", ["1943", "1944", "1946"], "History"),
    _q("Who was the first President of the United States?", "George Washington", ["Thomas Jefferson", "Abraham Lincoln", "John Adams"], "History"),
    _q("Which ancient wonder was located in Egypt?", "Great Pyramid of Giza", ["Hanging Gardens", "Colossus of Rhodes", "Temple of Artemis"], "History"),
    _q("What year did the Berlin Wall fall?", "1989", ["1987", "1991", "1985"], "History"),
    _q("Which empire built the Colosseum?", "Roman Empire", ["Greek Empire", "Ottoman Empire", "Byzantine Empire"], "History"),
    _q("Who discovered penicillin?", "Alexander Fleming", ["Louis Pasteur", "Marie Curie", "Joseph Lister"], "History"),
    _q("In what year did Columbus reach the Americas?", "1492", ["1488", "1500", "1476"], "History"),
    _q("What was the name of the ship the Pilgrims sailed to America?", "Mayflower", ["Santa Maria", "Endeavour", "Beagle"], "History"),
    # --- Animals ---
    _q("How many legs does a spider have?", "8", ["6", "10", "12"], "Animals"),
    _q("What is the fastest land animal?", "Cheetah", ["Lion", "Horse", "Gazelle"], "Animals"),
    _q("What is the largest mammal?", "Blue Whale", ["Elephant", "Giraffe", "Hippopotamus"], "Animals"),
    _q("How many hearts does an octopus have?", "3", ["1", "2", "5"], "Animals"),
    _q("What is a group of wolves called?", "Pack", ["Herd", "Flock", "Swarm"], "Animals"),
    _q("Which bird is known for its ability to mimic speech?", "Parrot", ["Crow", "Owl", "Eagle"], "Animals"),
    _q("What is the tallest animal in the world?", "Giraffe", ["Elephant", "Ostrich", "Moose"], "Animals"),
    _q("Which animal can change its color to blend in?", "Chameleon", ["Gecko", "Iguana", "Frog"], "Animals"),
    _q("What is the only mammal capable of true flight?", "Bat", ["Flying squirrel", "Sugar glider", "Colugo"], "Animals"),
    # --- Art & Literature ---
    _q("Who painted the Mona Lisa?", "Leonardo da Vinci", ["Michelangelo", "Raphael", "Donatello"], "Art"),
    _q("Who wrote 'Romeo and Juliet'?", "William Shakespeare", ["Charles Dickens", "Jane Austen", "Mark Twain"], "Literature"),
    _q("Who wrote '1984'?", "George Orwell", ["Aldous Huxley", "Ray Bradbury", "H.G. Wells"], "Literature"),
    _q("Which artist painted the ceiling of the Sistine Chapel?", "Michelangelo", ["Leonardo da Vinci", "Raphael", "Caravaggio"], "Art"),
    _q("Who wrote 'The Great Gatsby'?", "F. Scott Fitzgerald", ["Ernest Hemingway", "John Steinbeck", "William Faulkner"], "Literature"),
    _q("Which art movement did Salvador Dali belong to?", "Surrealism", ["Impressionism", "Cubism", "Pop Art"], "Art", "medium"),
    _q("Who wrote 'Harry Potter'?", "J.K. Rowling", ["J.R.R. Tolkien", "C.S. Lewis", "Roald Dahl"], "Literature"),
    _q("Who painted 'Starry Night'?", "Vincent van Gogh", ["Claude Monet", "Pablo Picasso", "Edvard Munch"], "Art"),
    # --- Music ---
    _q("How many strings does a standard guitar have?", "6", ["4", "5", "8"], "Music"),
    _q("Who is known as the 'King of Pop'?", "Michael Jackson", ["Elvis Presley", "Prince", "Freddie Mercury"], "Music"),
    _q("What instrument has 88 keys?", "Piano", ["Organ", "Accordion", "Harpsichord"], "Music"),
    _q("Which band released 'Bohemian Rhapsody'?", "Queen", ["The Beatles", "Led Zeppelin", "Pink Floyd"], "Music"),
    _q("What is the highest female singing voice?", "Soprano", ["Alto", "Mezzo-soprano", "Contralto"], "Music"),
    _q("Who composed the 'Moonlight Sonata'?", "Beethoven", ["Mozart", "Chopin", "Bach"], "Music"),
    # --- Film & TV ---
    _q("What is the highest-grossing film of all time?", "Avatar", ["Avengers: Endgame", "Titanic", "Star Wars"], "Film"),
    _q("Who directed 'Jurassic Park'?", "Steven Spielberg", ["James Cameron", "George Lucas", "Ridley Scott"], "Film"),
    _q("Which movie features the quote 'I'll be back'?", "The Terminator", ["Predator", "Total Recall", "Commando"], "Film"),
    _q("In 'The Wizard of Oz', what color are Dorothy's slippers?", "Ruby red", ["Silver", "Gold", "Blue"], "Film"),
    _q("Who played Jack in the movie 'Titanic'?", "Leonardo DiCaprio", ["Brad Pitt", "Matt Damon", "Johnny Depp"], "Film"),
    # --- Food & Drink ---
    _q("What fruit is known as the 'king of fruits'?", "Durian", ["Mango", "Pineapple", "Jackfruit"], "Food", "medium"),
    _q("What country is sushi originally from?", "Japan", ["China", "Korea", "Thailand"], "Food"),
    _q("What is the main ingredient in guacamole?", "Avocado", ["Tomato", "Lime", "Onion"], "Food"),
    _q("Which nut is used to make marzipan?", "Almond", ["Walnut", "Cashew", "Pistachio"], "Food"),
    _q("What is the most consumed beverage in the world after water?", "Tea", ["Coffee", "Milk", "Juice"], "Food"),
    # --- Sports ---
    _q("How many players are on a soccer team on the field?", "11", ["9", "10", "12"], "Sports"),
    _q("In which sport is the term 'love' used for zero?", "Tennis", ["Badminton", "Cricket", "Golf"], "Sports"),
    _q("How long is an Olympic swimming pool in meters?", "50", ["25", "75", "100"], "Sports"),
    _q("What country hosted the 2016 Summer Olympics?", "Brazil", ["Russia", "Japan", "China"], "Sports"),
    _q("Which sport uses a puck?", "Ice Hockey", ["Field Hockey", "Lacrosse", "Polo"], "Sports"),
    # --- Technology ---
    _q("What does 'HTTP' stand for?", "HyperText Transfer Protocol", ["High Tech Transfer Protocol", "HyperText Transmission Process", "High Transfer Text Protocol"], "Technology"),
    _q("Who co-founded Apple with Steve Jobs?", "Steve Wozniak", ["Bill Gates", "Tim Cook", "Elon Musk"], "Technology"),
    _q("What year was the first iPhone released?", "2007", ["2005", "2008", "2010"], "Technology"),
    _q("What does 'CPU' stand for?", "Central Processing Unit", ["Computer Personal Unit", "Central Program Utility", "Core Processing Unit"], "Technology"),
    _q("Which programming language is named after a type of coffee?", "Java", ["Python", "Ruby", "Go"], "Technology"),
    # --- Mythology ---
    _q("In Greek mythology, who is the king of the gods?", "Zeus", ["Poseidon", "Hades", "Apollo"], "Mythology"),
    _q("What creature has the body of a lion and the head of a human?", "Sphinx", ["Griffin", "Manticore", "Chimera"], "Mythology", "medium"),
    _q("Who is the Norse god of thunder?", "Thor", ["Odin", "Loki", "Freya"], "Mythology"),
    _q("In mythology, what was Medusa's hair made of?", "Snakes", ["Worms", "Vines", "Eels"], "Mythology"),
    # --- Math ---
    _q("What is the value of Pi rounded to two decimals?", "3.14", ["3.16", "3.12", "3.41"], "Mathematics"),
    _q("What is a triangle with all equal sides called?", "Equilateral", ["Isosceles", "Scalene", "Right"], "Mathematics"),
    _q("What is the square root of 144?", "12", ["11", "13", "14"], "Mathematics"),
    _q("How many sides does a hexagon have?", "6", ["5", "7", "8"], "Mathematics"),
]

del _q  # clean up helper from module namespace


BOT_PREFIX = "[Bot] "
BOT_PROFILES = [
    "[Bot] Rookie",
    "[Bot] Scholar",
    "[Bot] Professor",
    "[Bot] Maverick",
]




def host_line_for_rate(rate: float, answers: int) -> str:
    """The AI host's one-liner after a reveal, by how many players got it right."""
    if answers == 0:
        return "Nobody answered that one. Type 1 to 4 in chat to play!"
    pct = round(rate * 100)
    if pct == 0:
        return "Ouch! Nobody got that one."
    if pct < 25:
        return f"Brutal! Only {pct}% knew it."
    if pct < 50:
        return f"Tricky one: {pct}% got it right."
    if pct < 80:
        return f"Nice work, chat: {pct}% got it."
    return f"Too easy? {pct}% knew that."


def tier_rank(difficulty: str) -> int:
    """easy 0, medium 1, hard 2 (an unknown label counts as medium)."""
    return DIFFICULTY_TIERS.index(difficulty) if difficulty in DIFFICULTY_TIERS else 1


def nearest_tier(questions: list, difficulty: str) -> list:
    """The questions of the wanted tier, or else of the nearest tier (the lower one on a tie)."""
    if not questions:
        return []
    want = tier_rank(difficulty)
    best = min((abs(tier_rank(q.difficulty) - want), tier_rank(q.difficulty) > want) for q in questions)
    return [q for q in questions
            if (abs(tier_rank(q.difficulty) - want), tier_rank(q.difficulty) > want) == best]


# Tension build-up (GameState.BUILDUP): "QUESTION 8 · THE HARD ROUND", then one fact from the match
BUILDUP_EVENT_HEADLINE = {"final": "FOR DOUBLE POINTS", "lightning": "LIGHTNING ROUND",
                          "first_blood": "FIRST BLOOD BONUS", "jackpot": "JACKPOT ROUND"}
BUILDUP_KIND_HEADLINE = {"majority": "CROWD MIND", "higher_lower": "HIGHER OR LOWER", "odd_one_out": "ODD ONE OUT"}
BUILDUP_HEADLINES = ("THE NEXT HURDLE", "NO MISTAKES NOW", "KEEP IT ALIVE", "STAY SHARP", "EYES ON THE PRIZE")
BUILDUP_OPENERS = ("Here comes question {n}.", "Question {n}, get ready.", "On to question {n}.",
                   "Next hurdle: question {n}.", "Eyes up for question {n}.", "Question {n} is on its way.")
BUILDUP_FILLERS = ("The fastest right answers score the most", "Streaks multiply your points",
                   "Type 1 to 4 in chat the moment it appears", "Every point counts on the weekly ladder")
BUILDUP_FACTS = ("perfect", "lead", "streak", "hardest", "tier_history", "last")   # rotated, never twice in a row


CROWD_KINDS = ("majority", "minority")
_CROWD_INTRO = "Crowd Mind! No right answer: pick what you think most of chat will pick."
SPECIAL_INTROS = {
    "majority": _CROWD_INTRO, "minority": _CROWD_INTRO,   # Lonely Answer hides as Crowd Mind
    "higher_lower": "Higher or lower! Just two choices: type 1 or 2.",
    "odd_one_out": "Odd one out! Three of these belong together. Which one does not?",
}


def crowd_winners(counts: list[int], minority: bool = False) -> list[int]:
    """Crowd Mind: the most-picked options win (ties all win). Lonely Answer: the least-picked
    option that anyone picked."""
    picked = [c for c in counts if c > 0]
    if not picked:
        return []
    target = min(picked) if minority else max(picked)
    return [i for i, c in enumerate(counts) if c == target]


def host_line_for_result(res: RoundResult) -> str:
    q = res.question
    if q.kind not in CROWD_KINDS:
        return host_line_for_rate(res.correct_rate, res.total_answers)
    if res.void:
        return f"Only {res.total_answers} real players: a crowd round needs {CROWD_MIN_REAL}, so this one does not count."
    picks = " and ".join(q.options[i] for i in res.winners)
    if q.kind == "minority":
        return f"Twist! Lonely Answer: the LEAST picked answer wins. {picks} takes it!"
    pct = round(res.correct_rate * 100)
    return f"Chat went with {picks}! {pct}% read the crowd."


CREW_TEAM_SIZE = 3          # a crew scores its best 3 members, so small friend groups can win
CREW_NAME_MAX = 20
_CREW_CLEAN_RE = re.compile(r"[^\w &'.-]+")


def clean_crew_name(raw: str) -> str:
    """'night owls!!' -> 'Night Owls' (letters of any script, digits, space, & ' . -)."""
    name = _CREW_CLEAN_RE.sub("", raw).strip()
    name = re.sub(r"\s+", " ", name)[:CREW_NAME_MAX].strip()
    return name.title() if name == name.lower() else name


def _rest_after_command(raw: str) -> str:
    parts = raw.strip().split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


STATE_DURATIONS = {
    GameState.LOBBY: LOBBY_TIME,
    GameState.INTRO: INTRO_TIME,
    GameState.BUILDUP: BUILDUP_TIME,
    GameState.ASKING: QUESTION_DISPLAY_TIME,
    GameState.LOCKING: LATE_ANSWER_GRACE,
    GameState.REVEALING: REVEAL_DISPLAY_TIME,
    GameState.PODIUM: PODIUM_TIME,
}

COLOR_EVENT_BLUE = (100, 180, 255)
COLOR_EVENT_RED = (255, 80, 80)
COLOR_EVENT_PURPLE = (180, 100, 255)


class QuizLogic:
    def __init__(self, db: QuizDatabase):
        self.db = db
        self.state = GameState.WAITING
        self.state_timer = 0.0
        self.state_start_time = 0.0
        self.state_duration = 0.0

        # Questions
        self._question_cache: list[Question] = []
        self._session_token = ""
        self._last_fetch_time = 0.0
        self._fetch_in_progress = False
        self._current_category_id = None
        self._seen_questions: dict[str, float] = {}  # question_text -> timestamp

        # Match
        self.match_no = db.next_match_number()
        self.match_started_at = 0.0
        self.match_category = "Mixed bag"
        self.q_index = 0
        self.standings: dict[str, MatchStanding] = {}
        self.pips: list[str] = []          # one per finished question: "done" (most got it) / "miss"
        self.podium: list[MatchStanding] = []
        self.match_stats: dict = {}
        self.match_player_count = 0
        self.ready_players: list[str] = []
        self.duels: list[Duel] = []
        self.duel_results: list[tuple[str, str, int, int]] = []  # (winner, loser, w_pts, l_pts)
        self.cards: list[tuple[str, float]] = []                # player cards requested with !card

        # Current round
        self.current_question: Question | None = None
        self.current_answers: dict[str, tuple[int, float]] = {}
        self.lock_order: list[tuple[str, float]] = []  # (username, seconds after question start)
        self.half_picks: dict[str, tuple[int, int]] = {}  # 50:50 joker this question: the two options named
        self.halves_used: set[str] = set()                # who spent their joker this match
        self.question_start_time = 0.0
        self.question_duration = float(QUESTION_DISPLAY_TIME)
        self.last_result: RoundResult | None = None
        self.round_count = 0
        self.session_start_time = time.time()

        # Lobby vote
        self.vote_state: ThemeVoteState | None = None

        # Weekly ladder movement (shown on the podium)
        self._prev_weekly_positions: dict[str, int] = {}
        self.ladder_changes: dict[str, int | None] = {}  # username -> places gained, None = new

        # Show moments
        self.is_double_points = False  # final question
        self.mini_event = ""            # "lightning", "jackpot", "first_blood", ""
        self.tier_reached = 0           # highest ramp tier served this match (tier_rank): LEVEL UP fires above it
        self.level_up = ""              # the tier this question levelled up to ("medium", "hard"), else ""
        # Tension build-up (GameState.BUILDUP; the contract is in docs/game-modes.md)
        self.buildup: dict | None = None   # q_no, of, tier, stakes, kind, event, headline, subline, spotlight, intensity
        self.buildup_intensity = 0.0       # the last build-up's intensity, 0..1: scales the tension while asking
        self.perfect: set[str] | None = None   # real players with every question right so far (None before Q1)
        self._prepared = False             # BUILDUP served this question already
        self._hardest_rate = 1.0           # lowest all-time right rate of a question served this match
        self._last_fact = ""               # the build-up fact kind used last, never twice in a row
        self._line_turn = 0                # rotates the build-up wordings
        self._tier_results: dict[str, list[int]] = {}   # this match: tier -> [real answers, right]
        self._tier_last: dict[str, list[int]] = {}      # the same for the last match
        self.event_feed: list[GameEvent] = []
        self.sound_queue: list[str] = []
        self._last_countdown_second = None
        self._stinger_due = False
        self._bots_in_round = 0
        self.host_line = ""
        self.host_line_time = 0.0
        self.new_players_this_round: list[str] = []
        self._known_players: set[str] = set(db._players.keys())
        self._command_cooldowns: dict[str, float] = {}

        # Filler bots (in memory only, never ranked)
        self._scheduled_bots: list[tuple[str, int, float]] = []
        self._last_round_real_players: set[str] = set()
        self._active_bot_names: list[str] = []
        self._bots_active = False

        self.bank = QuestionBank(db._conn, db._lock)
        self.bank.add([_question_to_item(q) for q in FALLBACK_QUESTIONS], "builtin")
        for pack in sorted(p for p in PACK_DIR.glob("*.json") if not p.name.startswith("special_")):  # bundled packs; existing texts are skipped (special_* need their round type)
            self.bank.add(load_items(str(pack)), pack.name)
        self.special = SpecialDecks()
        self.special_slots = dict(SPECIAL_SLOTS)   # question number -> round type

        self._fetch_session_token()
        self._ensure_cache()

    def _say(self, line: str):
        self.host_line = line
        self.host_line_time = time.time()


    # ------------------------------------------
    # EVENT FEED
    # ------------------------------------------
    def _push_event(self, text: str, color: tuple, icon: str = ""):
        self.event_feed.append(GameEvent(text=text, color=color, icon=icon))
        if len(self.event_feed) > CHAT_FEED_MAX * 2:
            self.event_feed = self.event_feed[-CHAT_FEED_MAX:]

    def get_recent_events(self) -> list[GameEvent]:
        now = time.time()
        alive = [e for e in self.event_feed if now - e.timestamp < CHAT_FEED_DURATION]
        return alive[-CHAT_FEED_MAX:]

    # ------------------------------------------
    # SESSION TOKEN
    # ------------------------------------------
    def _fetch_session_token(self):
        if not requests:
            return
        try:
            resp = requests.get(
                OTDB_TOKEN_URL, params={"command": "request"}, timeout=10,
            )
            data = resp.json()
            if data.get("response_code") == 0:
                self._session_token = data["token"]
                print("[OTDB] Got session token")
        except Exception as e:
            print(f"[OTDB] Token fetch error: {e}")

    def _reset_session_token(self):
        if not requests or not self._session_token:
            return
        try:
            resp = requests.get(
                OTDB_TOKEN_URL,
                params={"command": "reset", "token": self._session_token},
                timeout=10,
            )
            if resp.json().get("response_code") == 0:
                print("[OTDB] Session token reset")
        except Exception as e:
            print(f"[OTDB] Token reset error: {e}")

    # ------------------------------------------
    # QUESTION FETCHING
    # ------------------------------------------
    def _ensure_cache(self):
        if self.bank.count(self._current_category_id, unseen_for=REPEAT_WINDOWS[0]) >= 3 * OTDB_MIN_CACHE:
            return  # the bank still holds plenty this category has not asked for a week
        if len(self._question_cache) >= OTDB_MIN_CACHE:
            return
        if self._fetch_in_progress:
            return
        if time.time() - self._last_fetch_time < OTDB_REQUEST_COOLDOWN:
            return
        self._fetch_in_progress = True
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        cat_at_fetch = self._current_category_id
        try:
            questions = self._fetch_questions(cat_at_fetch)
            if questions:
                added = self.bank.add([_question_to_item(q, cat_at_fetch) for q in questions], "otdb")
                print(f"[Bank] +{added} new questions")
                # Only add if category hasn't changed while we were fetching
                if self._current_category_id == cat_at_fetch:
                    # Filter out recently seen questions
                    self._purge_seen()
                    fresh = [q for q in questions if self._hash_question(q) not in self._seen_questions]
                    if len(fresh) < len(questions):
                        print(f"[OTDB] Filtered {len(questions) - len(fresh)} duplicate(s)")
                    self._question_cache.extend(fresh)
                    random.shuffle(self._question_cache)
                    print(f"[OTDB] Cached {len(fresh)} questions (total: {len(self._question_cache)}, seen: {len(self._seen_questions)})")
                else:
                    print(f"[OTDB] Discarded {len(questions)} questions (category changed during fetch)")
        except Exception as e:
            print(f"[OTDB] Fetch error: {e}")
        finally:
            self._last_fetch_time = time.time()
            self._fetch_in_progress = False

    def _fetch_questions(self, category_id=None) -> list[Question]:
        if not requests:
            return []
        params = {"amount": OTDB_BATCH_SIZE, "type": "multiple"}
        if category_id:
            params["category"] = category_id
        if self._session_token:
            params["token"] = self._session_token

        resp = requests.get(OTDB_BASE_URL, params=params, timeout=10)
        data = resp.json()

        if data.get("response_code") == 4:
            self._reset_session_token()
            if self._session_token:
                params["token"] = self._session_token
            resp = requests.get(OTDB_BASE_URL, params=params, timeout=10)
            data = resp.json()

        if data.get("response_code") != 0:
            return []

        questions = []
        for item in data["results"]:
            text = html.unescape(item["question"])
            correct = html.unescape(item["correct_answer"])
            incorrect = [html.unescape(a) for a in item["incorrect_answers"]]
            options = incorrect + [correct]
            random.shuffle(options)
            correct_index = options.index(correct)
            questions.append(Question(
                text=text, correct_answer=correct, options=options,
                correct_index=correct_index,
                category=html.unescape(item["category"]),
                difficulty=item["difficulty"],
            ))
        return questions

    @staticmethod
    def _hash_question(q: Question) -> str:
        return q.text

    def _purge_seen(self):
        now = time.time()
        self._seen_questions = {
            h: t for h, t in self._seen_questions.items()
            if now - t < OTDB_SEEN_EXPIRY
        }

    def _pop_question(self, difficulty: str = "") -> Question:
        """Next question, preferring the requested difficulty (match ramp: easy -> hard)."""
        q = self.bank.pick(self._current_category_id, difficulty)
        if q:
            self._seen_questions[self._hash_question(q)] = time.time()
            self._question_cache = [c for c in self._question_cache if c.text != q.text]
            return q
        if self._question_cache:
            q = nearest_tier(self._question_cache, difficulty)[0]
            self._question_cache.remove(q)
            self._seen_questions[self._hash_question(q)] = time.time()
            return q
        self._purge_seen()
        unseen = [q for q in FALLBACK_QUESTIONS
                  if self._hash_question(q) not in self._seen_questions]
        if not unseen:
            unseen = list(FALLBACK_QUESTIONS)
        q = random.choice(nearest_tier(unseen, difficulty))
        self._seen_questions[self._hash_question(q)] = time.time()
        options = list(q.options)
        random.shuffle(options)
        return Question(
            text=q.text, correct_answer=q.correct_answer,
            options=options, correct_index=options.index(q.correct_answer),
            category=q.category, difficulty=q.difficulty,
        )

    def _special_question(self, slot: str) -> Question | None:
        """The special round for this match slot, or None (no slot, or its deck is empty)."""
        if not slot:
            return None
        if slot not in CROWD_KINDS:
            return self.special.draw(slot)
        q = self.special.draw("majority")   # Lonely Answer plays the Crowd Mind pack
        if q and (slot == "minority" or random.random() < LONELY_CHANCE):
            q.kind = "minority"             # the twist: shown only on the reveal
        return q

    # ------------------------------------------
    # STATE MACHINE
    # ------------------------------------------
    def update(self, dt: float):
        self.sound_queue.clear()
        self._ensure_cache()

        if self.state == GameState.WAITING:
            self._transition_to(GameState.LOBBY)
            return

        self.state_timer -= dt

        if self.state in (GameState.ASKING, GameState.LOCKING):
            self._process_bot_answers()

        if self.state == GameState.ASKING:
            # Last five seconds: one beep per second, the heartbeat riser on the first
            second = math.ceil(self.state_timer)
            if second <= 5 and second != self._last_countdown_second and self.state_timer > 0:
                if self._last_countdown_second is None or second == 5:
                    self.sound_queue.append("final_countdown")
                self._last_countdown_second = second
                self.sound_queue.append("countdown")

        if (self.state == GameState.REVEALING and self._stinger_due
                and self.state_duration - self.state_timer >= REVEAL_AT):
            self._stinger_due = False
            self.sound_queue.append("correct" if self.last_result.correct_players else "wrong")

        if self.state_timer <= 0:
            self._on_state_expired()

    def _transition_to(self, state: GameState):
        self.state = state
        self.state_start_time = time.time()
        self.state_duration = STATE_DURATIONS[state]
        self.state_timer = self.state_duration
        self.sound_queue.append("whoosh")
        getattr(self, f"_enter_{state.name.lower()}")()

    def _on_state_expired(self):
        s = self.state
        if s == GameState.LOBBY:
            self._resolve_vote()
            self._transition_to(GameState.INTRO)
        elif s == GameState.INTRO:
            self._transition_to(GameState.BUILDUP)
        elif s == GameState.BUILDUP:
            self._transition_to(GameState.ASKING)
        elif s == GameState.ASKING:
            self._transition_to(GameState.LOCKING)
        elif s == GameState.LOCKING:
            self._transition_to(GameState.REVEALING)
        elif s == GameState.REVEALING:
            if self.q_index >= MATCH_LENGTH:
                self._transition_to(GameState.PODIUM)
            else:
                self._transition_to(GameState.BUILDUP)
        elif s == GameState.PODIUM:
            self._transition_to(GameState.LOBBY)

    # ------------------------------------------
    # STATE ENTRY ACTIONS
    # ------------------------------------------
    def _enter_lobby(self):
        self.match_no = self.db.next_match_number()
        self.ready_players = []
        self.current_question = None
        self.last_result = None
        self.mini_event = ""
        self.is_double_points = False
        self.buildup = None
        self.buildup_intensity = 0.0
        available = list(VOTABLE_CATEGORIES.items())
        if self._current_category_id:
            available = [(c, n) for c, n in available if c != self._current_category_id]
        chosen = random.sample(available, 3) + [(None, "Mixed bag")]
        self.vote_state = ThemeVoteState(options={i: opt for i, opt in enumerate(chosen, 1)})
        self._say(f"Match {self.match_no} starts in {LOBBY_TIME} seconds. "
                  "Vote for the category: type 1 to 4!")

    def _enter_intro(self):
        self.q_index = 0
        self.standings = {}
        self.halves_used = set()
        self.tier_reached = 0
        self.perfect = None
        self.buildup_intensity = 0.0
        self._hardest_rate = 1.0
        self._tier_results = {}
        self.pips = []
        self.podium = []
        self.match_started_at = time.time()
        self._prev_weekly_positions = {
            p.username: i for i, p in enumerate(self.db.get_weekly_top(n=1_000_000), 1)
        }
        self.sound_queue.append("show_open")
        self._say(f"Match {self.match_no}: {self.match_category}. "
                  f"{MATCH_LENGTH} questions, fastest right answers score most. Good luck!")

    def _prepare_question(self):
        """Serve the next question and its event: BUILDUP does it, so the build-up can talk about it."""
        self._update_participation_streaks()
        self._last_round_real_players = {u for u in self.current_answers if not is_bot(u)}

        self.q_index += 1
        self._ensure_cache()
        self.current_question = (self._special_question(self.special_slots.get(self.q_index, ""))
                                 or self._pop_question(DIFFICULTY_RAMP.get(self.q_index, "medium")))
        self.current_answers = {}
        self.lock_order = []
        self.half_picks = {}
        self.new_players_this_round = []
        self._check_level_up()

        # Fixed event slots give every match the same shape.
        self.is_double_points = self.q_index == MATCH_LENGTH
        self.mini_event = ""
        if self.q_index == LIGHTNING_QUESTION:
            self.mini_event = "lightning"
        elif self.q_index in BONUS_QUESTIONS:
            self.mini_event = random.choice(["first_blood", "jackpot"])

    def _enter_buildup(self):
        self._prepare_question()
        self._prepared = True
        if self.is_double_points or self.level_up:
            self.state_duration = self.state_timer = BUILDUP_TIME_BIG
        self.buildup = self._make_buildup()
        self.buildup_intensity = self.buildup["intensity"]

    def _enter_asking(self):
        if not self._prepared:      # straight into ASKING (tests, or a skipped build-up)
            self._prepare_question()
        self._prepared = False
        self.buildup = None
        self.question_start_time = time.time()
        self._last_countdown_second = None
        self._bots_in_round = 0
        self.sound_queue.append("new_question")

        if self.is_double_points:
            self._push_event("FINAL QUESTION: DOUBLE POINTS!", COLOR_TEXT_GOLD, "2X")
            self.sound_queue.append("double_points")
            self._say("Final question, and it pays double. Everything can still change!")
        elif self.mini_event == "lightning":
            self.state_duration = LIGHTNING_TIME
            self.state_timer = LIGHTNING_TIME
            self._push_event(f"LIGHTNING ROUND! {LIGHTNING_TIME}s, 1.5x points", COLOR_EVENT_BLUE, "ZAP")
            self.sound_queue.append("double_points")
            self._say(f"Lightning round! Only {LIGHTNING_TIME} seconds, but 1.5 times the points.")
        elif self.mini_event == "first_blood":
            self._push_event(f"FIRST BLOOD: fastest right answer +{FIRST_BLOOD_BONUS}", COLOR_EVENT_RED, "1ST")
            self.sound_queue.append("double_points")
            self._say(f"First blood! The fastest right answer wins {FIRST_BLOOD_BONUS} extra points.")
        elif self.mini_event == "jackpot":
            self._push_event(f"JACKPOT: one right answer wins +{JACKPOT_BONUS}", COLOR_EVENT_PURPLE, "JP")
            self.sound_queue.append("double_points")
            self._say(f"Jackpot round! One lucky right answer wins {JACKPOT_BONUS} points.")
        elif self.current_question.kind in SPECIAL_INTROS:
            self._say(SPECIAL_INTROS[self.current_question.kind])
        elif self.level_up:
            self._say(f"Level up! {self.level_up.capitalize()} questions from here, "
                      f"worth {DIFFICULTY_MULT[self.level_up]:g}x points.")
        else:
            diff = self.current_question.difficulty
            self._say(f"Question {self.q_index} of {MATCH_LENGTH}. "
                      f"{self.current_question.category}, {diff}.")

        self.question_duration = self.state_duration
        self._schedule_bots()

    def _check_level_up(self):
        """LEVEL UP once per ramp step, when a question of the new tier is really served."""
        q, self.level_up = self.current_question, ""
        ramp = DIFFICULTY_RAMP.get(self.q_index, "medium")
        if q.kind in CROWD_KINDS or tier_rank(ramp) <= self.tier_reached or tier_rank(q.difficulty) < tier_rank(ramp):
            return
        self.tier_reached = tier_rank(ramp)
        self.level_up = ramp
        self._push_event(f"LEVEL UP: {ramp.upper()} questions, {DIFFICULTY_MULT[ramp]:g}x points",
                         COLOR_TEXT_GOLD, "LVL")
        self.sound_queue.append("level_up")

    # ------------------------------------------
    # TENSION BUILD-UP (once per question: the scans here are over this match's players, never per frame)
    # ------------------------------------------
    def _make_buildup(self) -> dict:
        q, n = self.current_question, self.q_index
        crowd = q.kind in CROWD_KINDS
        event = "final" if self.is_double_points else (self.mini_event or None)
        stakes = self.question_stakes()
        leaders = heapq.nlargest(2, (s for s in self.standings.values() if s.points > 0 and not is_bot(s.username)),
                                 key=lambda s: s.points)
        facts = self._buildup_facts(q, leaders, stakes)
        prefer = ["tier"] if self.level_up else ["lead"] if event == "final" else []
        turn = n % len(BUILDUP_FACTS)
        order = prefer + list(BUILDUP_FACTS[turn:] + BUILDUP_FACTS[:turn])
        pick = next((k for k in order if k in facts and k != self._last_fact), None)
        if pick:
            subline, spotlight = facts[pick]
        else:
            pick = f"filler{self._line_turn % len(BUILDUP_FILLERS)}"
            if pick == self._last_fact:
                self._line_turn += 1
                pick = f"filler{self._line_turn % len(BUILDUP_FILLERS)}"
            subline, spotlight = BUILDUP_FILLERS[self._line_turn % len(BUILDUP_FILLERS)], None
        self._last_fact = pick
        if spotlight is None and leaders:
            spotlight = leaders[0].username

        if event:                   # the event names the question; a step-up then says so in the subline
            headline = BUILDUP_EVENT_HEADLINE[event]
        elif self.level_up:
            headline = f"THE {self.level_up.upper()} ROUND"
        elif q.kind in BUILDUP_KIND_HEADLINE or q.kind == "minority":
            headline = BUILDUP_KIND_HEADLINE["majority" if q.kind == "minority" else q.kind]
        elif n == 1:
            headline = "THE WARM-UP"
        elif n == MATCH_LENGTH - 1:
            headline = "THE LAST HURDLE"
        else:
            headline = BUILDUP_HEADLINES[n % len(BUILDUP_HEADLINES)]

        # Intensity: Q1 light, rising every question, a bump for step-ups, events and a close race; the final is 1
        close = len(leaders) == 2 and leaders[0].points - leaders[1].points <= stakes
        level = 0.15 + 0.7 * (n - 1) / max(1, MATCH_LENGTH - 1)
        level += 0.1 * bool(self.level_up) + 0.05 * bool(event) + 0.05 * close
        intensity = 1.0 if event == "final" else min(0.95, level)
        intensity = round(max(self.buildup_intensity, intensity), 3)

        if event == "final":
            opener = "The final question, and it pays double."
        elif self.level_up and pick == "tier":
            opener = f"Level up at question {n}!"
        else:
            self._line_turn += 1
            opener = BUILDUP_OPENERS[self._line_turn % len(BUILDUP_OPENERS)].format(n=n)
        self._say(f"{opener} {subline}. Up to {stakes} points.")
        return {
            "q_no": n, "of": MATCH_LENGTH,
            "tier": DIFFICULTY_RAMP.get(n, "medium") if crowd else q.difficulty,
            "stakes": stakes, "kind": "majority" if q.kind == "minority" else q.kind,   # the twist stays hidden
            "event": event, "headline": f"QUESTION {n} · {headline}", "subline": subline,
            "spotlight": spotlight, "intensity": intensity,
        }

    def _buildup_facts(self, q: Question, leaders: list, stakes: int) -> dict:
        """fact kind -> (subline, player to spotlight or None), from what really happened."""
        facts = {}
        if self.level_up:
            facts["tier"] = (f"{self.level_up.capitalize()} questions from here, "
                             f"{DIFFICULTY_MULT[self.level_up]:g}x points", None)
        if self.perfect is not None:
            alive = [u for u in self.perfect if not is_bot(u)]
            if len(alive) == 1:
                facts["perfect"] = (f"Only {alive[0]} is still perfect", alive[0])
            elif alive:
                only = "Only " if len(alive) <= 5 else ""
                facts["perfect"] = (f"{only}{len(alive)} players are still perfect", None)
        if leaders:
            a = leaders[0]
            if len(leaders) == 1:
                facts["lead"] = (f"{a.username} leads with {a.points}", a.username)
            elif a.points == leaders[1].points:
                facts["lead"] = (f"{a.username} and {leaders[1].username} are level on {a.points}", a.username)
            else:
                tail = f", and {stakes} points are up for grabs" if self.is_double_points else ""
                facts["lead"] = (f"{a.username} leads by {a.points - leaders[1].points}{tail}", a.username)
        best = max(((self.db._players[u].streak, u) for u in self.standings
                    if not is_bot(u) and u in self.db._players), default=(0, ""))
        if best[0] >= 3:
            facts["streak"] = (f"{best[1]}'s {best[0]}-answer streak is on the line", best[1])
        if q.kind == "classic":
            asked, right = self.bank.stats(q.text)
            if asked >= MEASURE_AFTER:
                rate = right / asked
                pct = round(rate * 100)
                if self.q_index > 1 and rate < min(0.5, self._hardest_rate):
                    facts["hardest"] = (f"The hardest question so far: only {pct}% ever got it right", None)
                else:
                    facts["hardest"] = (f"{pct}% of players have ever got this one right", None)
                self._hardest_rate = min(self._hardest_rate, rate)
        answers, right = self._tier_last.get(q.difficulty, (0, 0))
        if q.kind not in CROWD_KINDS and answers >= 3:
            pct = round(100 * right / answers)
            facts["tier_history"] = (f"Last match, {'only ' if pct < 40 else ''}{pct}% got the "
                                     f"{q.difficulty} ones right", None)
        res = self.last_result
        if res and res.total_answers and res.question.kind not in CROWD_KINDS:
            right = len([u for u, _, _ in res.correct_players])
            only = "Only " if right * 2 < res.total_answers else ""
            facts["last"] = (f"{only}{right} of {res.total_answers} got the last one right", None)
        return facts

    def _enter_locking(self):
        self.sound_queue += ["times_up", "drumroll"]
        self._say("Time's up! Locking in the last answers...")

    def _enter_revealing(self):
        self.round_count += 1
        if self.current_question and self.current_question.kind == "classic":  # specials are not in the bank
            real = [(u, c) for u, (c, _) in self.current_answers.items() if not is_bot(u)]
            self.bank.record_result(self.current_question.text, len(real),
                                    sum(1 for _, c in real if c == self.current_question.correct_index))
        before = {p.username: i for i, p in enumerate(self.db.get_weekly_top(n=50), 1)}
        self.last_result = self._resolve_question()
        self._announce_overtakes(before)
        res = self.last_result
        self._track_perfect(res)
        self.pips.append("done" if res.total_answers and res.correct_rate >= 0.5 else "miss")
        self._stinger_due = True
        self._say(host_line_for_result(res))
        if res.question.kind == "minority" and not res.void:
            self._push_event("TWIST! Lonely Answer: the least picked answer wins", COLOR_AMBER, "TWST")
            self.sound_queue.append("double_points")

    def _track_perfect(self, res: RoundResult):
        """Who is still perfect (every answer right; a crowd round only needs an answer), and how
        each tier went for real players. O(answers), once per question."""
        q = res.question
        if res.void or not q.text:
            return
        scored = {u for u, _, _ in res.correct_players if not is_bot(u)}
        if q.kind in CROWD_KINDS:
            scored |= {u for u, _ in res.wrong_players if not is_bot(u)}
        else:
            real = sum(1 for u in self.current_answers if not is_bot(u))
            tally = self._tier_results.setdefault(q.difficulty, [0, 0])
            tally[0] += real
            tally[1] += len(scored)
        self.perfect = scored if self.perfect is None else self.perfect & scored

    def _enter_podium(self):
        if self._tier_results:
            self._tier_last = self._tier_results
        real = [s for s in self.standings.values() if not is_bot(s.username)]
        real.sort(key=lambda s: (-s.points, s.fastest or 999))
        self.podium = [s for s in real if s.points > 0][:3]
        self.match_player_count = len(real)
        fastest = min((s for s in real if s.fastest > 0), key=lambda s: s.fastest, default=None)
        streak = max(real, key=lambda s: s.best_streak, default=None)
        race = self.crew_race()
        self.match_stats = {
            "fastest": (fastest.username, fastest.fastest) if fastest else None,
            "best_streak": (streak.username, streak.best_streak) if streak and streak.best_streak else None,
            "crew": race[0][:2] if race and race[0][1] > 0 else None,
        }
        self._resolve_duels()
        winner = self.podium[0] if self.podium else None
        self.db.record_match(
            self.match_started_at, self.match_category, len(real),
            winner.username if winner else "", winner.points if winner else 0,
        )
        self._detect_ladder_changes()
        self.sound_queue.append("fanfare")
        if winner:
            self._push_event(f"{winner.username} wins match {self.match_no}!", COLOR_TEXT_GOLD, "WIN")
            self._say(f"{winner.username} wins match {self.match_no} with {winner.points} points! "
                      "Next match starts soon.")
        else:
            self._say("No winner this time. Next match starts soon: type 1 to 4 to play!")

    def _announce_overtakes(self, before: dict[str, int]):
        """Rivals: "Lena_K passed owlbert on the weekly ladder!" (at most two per round)."""
        after = self.db.get_weekly_top(n=50)
        said = 0
        for i, p in enumerate(after[:-1]):
            below = after[i + 1].username
            old_me, old_below = before.get(p.username), before.get(below)
            if (old_below is not None and (old_me is None or old_me > old_below)
                    and p.username in self.current_answers):
                self._push_event(f"{p.username} passed {below} on the weekly ladder!", COLOR_TEXT_GOLD, "UP")
                said += 1
                if said == 2:
                    break

    def crew_race(self) -> list[tuple[str, int, int]]:
        """(crew, points, members playing) in this match; the best CREW_TEAM_SIZE members count."""
        groups: dict[str, list[int]] = {}
        for st in self.standings.values():
            p = self.db._players.get(st.username)
            if p and p.crew and not is_bot(st.username):
                groups.setdefault(p.crew, []).append(st.points)
        race = [(c, sum(sorted(v, reverse=True)[:CREW_TEAM_SIZE]), len(v)) for c, v in groups.items()]
        race.sort(key=lambda r: -r[1])
        return race

    def crew_ladder(self, n: int = 8) -> list[tuple[str, int, int]]:
        """(crew, weekly points of its best 3, members) for this ISO week."""
        groups: dict[str, list[int]] = {}
        for p in self.db._players.values():
            if p.crew and not is_bot(p.username):
                groups.setdefault(p.crew, []).append(p.current_weekly())
        ladder = [(c, sum(sorted(v, reverse=True)[:CREW_TEAM_SIZE]), len(v)) for c, v in groups.items()]
        ladder = [r for r in ladder if r[1] > 0]
        ladder.sort(key=lambda r: -r[1])
        return ladder[:n]

    def active_duels(self) -> list[Duel]:
        return [d for d in self.duels if d.accepted and d.match_no == self.match_no]

    def _resolve_duels(self):
        self.duel_results = []
        for d in self.active_duels():
            pa = self.standings[d.a].points if d.a in self.standings else 0
            pb = self.standings[d.b].points if d.b in self.standings else 0
            if pa == pb:
                self._push_event(f"Duel {d.a} vs {d.b}: a draw at {pa}!", COLOR_AMBER, "DUEL")
                continue
            (w, wp), (l, lp) = sorted(((d.a, pa), (d.b, pb)), key=lambda x: -x[1])
            self.db.get_or_create_player(w).duel_wins += 1
            self.db.get_or_create_player(l).duel_losses += 1
            self.db.mark_dirty(w)
            self.db.mark_dirty(l)
            self.duel_results.append((w, l, wp, lp))
            self._push_event(f"{w} wins the duel vs {l} ({wp}-{lp})!", COLOR_EVENT_RED, "DUEL")
        self.duels = [d for d in self.duels if d.match_no > self.match_no]

    def _detect_ladder_changes(self):
        """Places gained on the weekly ladder during this match (None = new on the ladder)."""
        self.ladder_changes = {}
        for i, p in enumerate(self.db.get_weekly_top(), 1):
            old = self._prev_weekly_positions.get(p.username)
            self.ladder_changes[p.username] = None if old is None else old - i
        if any(v is None or v > 0 for v in self.ladder_changes.values()):
            self.sound_queue.append("rank_up")

    # ------------------------------------------
    # PARTICIPATION STREAKS
    # ------------------------------------------
    def _update_participation_streaks(self):
        """Count consecutive rounds played (for the previous round)."""
        if not self.current_answers:
            return
        participated = {u for u in self.current_answers if not is_bot(u)}
        for username in participated:
            player = self.db._players.get(username)
            if not player:
                continue
            player.participation_streak += 1
            if player.streak >= STREAK_SHIELD_THRESHOLD and not player.streak_shield:
                player.streak_shield = True
            if player.participation_streak in PARTICIPATION_MILESTONES:
                player.add_points(PARTICIPATION_BONUS)
                self._push_event(
                    f"{username} played {player.participation_streak} rounds in a row! +{PARTICIPATION_BONUS}",
                    COLOR_AMBER, "PLAY",
                )
                self.sound_queue.append("streak")
            self.db.mark_dirty(username)
        for username, player in self.db._players.items():
            if username not in participated and player.participation_streak and not is_bot(username):
                player.participation_streak = 0
                self.db.mark_dirty(username)

    # ------------------------------------------
    # QUESTION RESOLUTION & SCORING
    # ------------------------------------------
    def _standing(self, username: str) -> MatchStanding:
        st = self.standings.get(username)
        if st is None:
            st = self.standings[username] = MatchStanding(username)
        return st

    def _award_bonus(self, username: str, points: int):
        self.db.get_or_create_player(username).add_points(points)
        self._standing(username).points += points
        self.db.mark_dirty(username)

    def _resolve_question(self) -> RoundResult:
        q = self.current_question
        if not q:
            return RoundResult(Question("?", "?", [], 0, "", ""), [], [], 0)

        correct_players, wrong_players = [], []
        crowd = q.kind in CROWD_KINDS
        # A crowd round is decided and scored by real players only: bots must never sway it
        answers = {u: a for u, a in self.current_answers.items() if not is_bot(u)} if crowd else self.current_answers
        option_counts = [0] * len(q.options)
        for username, (choice, _) in answers.items():
            picks = self.half_picks.get(username, (choice,))
            for c in picks:   # a 50:50 is half a vote for each option it named: the split still adds up to 100%
                if 0 <= c < len(option_counts):
                    option_counts[c] += 1 / len(picks)
        winners, void = [q.correct_index], False
        if crowd:
            void = len(answers) < CROWD_MIN_REAL
            winners = [] if void else crowd_winners(option_counts, q.kind == "minority")

        for username, (choice, timestamp) in ({} if void else answers).items():
            player = self.db.get_or_create_player(username)
            st = self._standing(username)
            old_rank = player.rank
            answer_time = max(0.0, timestamp - self.question_start_time)
            half = self.half_picks.get(username)

            if choice in winners or (half and q.correct_index in half):
                pts = int(self._calculate_points(timestamp, player.streak) * self.question_mult(q))
                if half:
                    pts = max(1, pts // 2)   # 50:50 joker: two guesses, half the points
                if player.wrong_streak >= COMEBACK_STREAK_THRESHOLD:
                    pts += COMEBACK_BONUS
                    self._push_event(f"{username} COMEBACK! +{COMEBACK_BONUS}", COLOR_CORRECT, "BACK")
                    self.sound_queue.append("streak")
                player.record_correct(pts)
                st.points += pts
                st.correct += 1
                st.streak += 1
                st.best_streak = max(st.best_streak, st.streak)
                if not st.fastest or answer_time < st.fastest:
                    st.fastest = answer_time
                if not is_bot(username):
                    self._check_achievements(player, answer_time, old_rank)
                correct_players.append((username, pts, answer_time))
            elif crowd:
                wrong_players.append((username, choice))  # no right answer to miss: the streak stays
            else:
                player.record_wrong()
                st.streak = 0
                if getattr(player, "_shield_used", False):
                    self._push_event(f"{username} SHIELD! Streak saved (x{player.streak})",
                                     COLOR_EVENT_BLUE, "SHD")
                    self.sound_queue.append("streak")
                wrong_players.append((username, choice))
            self.db.mark_dirty(username)

        correct_players.sort(key=lambda c: c[2])
        fastest_player, fastest_time = (correct_players[0][0], correct_players[0][2]) if correct_players else ("", 0.0)

        unlocked = [u for u, _, _ in correct_players if not is_bot(u) and u not in self.halves_used
                    and self.standings[u].streak == HALF_STREAK]
        if unlocked:
            who = ", ".join(unlocked[:3]) + (f" +{len(unlocked) - 3}" if len(unlocked) > 3 else "")
            self._push_event(f"{who}: 50:50 joker unlocked! Type !half and two numbers", COLOR_EVENT_PURPLE, "50")

        if self.mini_event == "first_blood" and correct_players:
            self._award_bonus(fastest_player, FIRST_BLOOD_BONUS)
            self._push_event(f"{fastest_player} FIRST BLOOD! +{FIRST_BLOOD_BONUS} ({fastest_time:.1f}s)",
                             COLOR_EVENT_RED, "1ST")
            self.sound_queue.append("rank_up")
        if self.mini_event == "jackpot" and correct_players:
            jp_name = random.choice(correct_players)[0]
            self._award_bonus(jp_name, JACKPOT_BONUS)
            self._push_event(f"{jp_name} wins the JACKPOT! +{JACKPOT_BONUS}", COLOR_EVENT_PURPLE, "JP")
            self.sound_queue.append("rank_up")

        return RoundResult(
            question=q, correct_players=correct_players, wrong_players=wrong_players,
            total_answers=len(answers),
            fastest_player=fastest_player, fastest_time=fastest_time,
            option_counts=option_counts, winners=winners, void=void,
        )

    def question_mult(self, q: Question | None = None) -> float:
        """This question's multiplier on every right answer: difficulty (not on crowd rounds),
        lightning, final double."""
        q = q or self.current_question
        mult = 1.0 if q.kind in CROWD_KINDS else DIFFICULTY_MULT.get(q.difficulty, 1.0)
        if self.mini_event == "lightning":
            mult *= LIGHTNING_MULT
        if self.is_double_points:
            mult *= FINAL_QUESTION_MULT
        return mult

    def question_stakes(self) -> int:
        """What this question is worth: the fastest right answer from a player with no streak."""
        return int(BASE_POINTS * SPEED_BONUS_TIER1_MULT * self.question_mult())

    def _calculate_points(self, answer_timestamp: float, current_streak: int) -> int:
        elapsed = answer_timestamp - self.question_start_time
        time_fraction = max(0, min(1, elapsed / self.question_duration))
        if time_fraction <= SPEED_BONUS_TIER1_THRESHOLD:
            speed_mult = SPEED_BONUS_TIER1_MULT
        elif time_fraction <= SPEED_BONUS_TIER2_THRESHOLD:
            speed_mult = SPEED_BONUS_TIER2_MULT
        else:
            speed_mult = 1.0
        streak_mult = min(MAX_STREAK_MULT, 1.0 + current_streak * STREAK_BONUS_PER)
        return max(1, int(BASE_POINTS * speed_mult * streak_mult))

    def _check_achievements(self, player: Player, answer_time: float, old_rank: str):
        if player.correct_answers == 1:
            self._push_event(f"{player.username} got their first answer right!", COLOR_TEXT_GOLD, "ACH")
        if player.streak in STREAK_MILESTONES:
            names = {3: "On Fire", 5: "Unstoppable", 10: "Legendary Streak", 15: "Quiz Machine",
                     25: "GODLIKE", 50: "Transcendent", 100: "The Chosen One"}
            self._push_event(f"{player.username}: {names.get(player.streak, 'Streak')} (x{player.streak})",
                             COLOR_TEXT_GOLD, "FIRE")
            self.sound_queue.append("streak")
        if answer_time < 2.0:
            self._push_event(f"{player.username} SPEED DEMON ({answer_time:.1f}s)", COLOR_RANK_DIAMOND, "FAST")
        if player.rank != old_rank:
            self._push_event(f"{player.username} ranked up to {player.rank}!", COLOR_TEXT_GOLD, "UP")
            self.sound_queue.append("rank_up")

    # ------------------------------------------
    # ADMIN ACTIONS
    # ------------------------------------------
    def clear_bots(self):
        self._scheduled_bots = []
        self._bots_active = False
        self.db.remove_players(BOT_PROFILES)
        for bot_name in BOT_PROFILES:
            self.current_answers.pop(bot_name, None)
            self.standings.pop(bot_name, None)
        self._push_event("Bots cleared!", COLOR_CORRECT, "ADM")

    def reset_all_scores(self):
        count = self.db.reset_all_players()
        self._push_event(f"All {count} players reset!", COLOR_AMBER, "ADM")

    def reset_bot_scores(self):
        for bot_name in BOT_PROFILES:
            player = self.db._players.get(bot_name)
            if player:
                player.reset()
        self._push_event("Bot scores reset!", COLOR_AMBER, "ADM")

    # ------------------------------------------
    # FILLER BOTS (in memory only, never saved or ranked)
    # ------------------------------------------
    def _count_real_in_round(self) -> int:
        return sum(1 for u in self.current_answers if not is_bot(u))

    def _count_bots_in_round(self) -> int:
        return sum(1 for u in self.current_answers if is_bot(u))

    def _retire_bots(self, reason: str):
        if self._bots_active:
            self._bots_active = False
            self._active_bot_names = []
            self.db.remove_players(BOT_PROFILES)
            self._push_event(reason, COLOR_CORRECT, "BYE")

    def _schedule_bots(self):
        self._scheduled_bots = []
        bots_needed = max(0, MIN_PLAYERS - len(self._last_round_real_players))
        if bots_needed == 0:
            self._retire_bots("Enough players! Bots retired.")
            return
        active_bots = random.sample(BOT_PROFILES, bots_needed)
        retired = [b for b in BOT_PROFILES if b not in active_bots]
        if retired and self._bots_active:
            self.db.remove_players(retired)
        self._active_bot_names = active_bots
        self._bots_active = True
        if not self.current_question:
            return
        correct_idx = self.current_question.correct_index
        n = len(self.current_question.options)
        diff = BOT_DIFFICULTY["easy"]
        for bot_name in active_bots:
            if correct_idx < 0:  # crowd round: no right answer, and bot picks never count
                choice = random.randrange(n)
            elif random.random() < diff["accuracy"]:
                choice = correct_idx
            else:
                choice = random.choice([i for i in range(n) if i != correct_idx])
            at = self.question_start_time + random.uniform(diff["speed_min"], diff["speed_max"]) * self.state_duration
            self._scheduled_bots.append((bot_name, choice, at))

    def _remove_excess_bots(self):
        if not self._scheduled_bots and not self._bots_in_round:
            return  # the common case, and O(1): scanning every answer per answer was quadratic
        real_in_round = self._count_real_in_round()
        bots_in_round = [u for u in self.current_answers if is_bot(u)]
        excess = real_in_round + len(bots_in_round) - MIN_PLAYERS
        if real_in_round >= MIN_PLAYERS:
            excess = len(bots_in_round)
            self._scheduled_bots = []
            self._retire_bots("Enough players! Bots retired.")
        if excess > 0:
            random.shuffle(bots_in_round)
            for bot_name in bots_in_round[:excess]:
                del self.current_answers[bot_name]
                self.lock_order = [x for x in self.lock_order if x[0] != bot_name]
                self._bots_in_round -= 1

    def _process_bot_answers(self):
        if not self._scheduled_bots:
            return
        now = time.time()
        remaining = []
        real_in_round = self._count_real_in_round()
        bots_in_round = self._count_bots_in_round()
        for bot_name, choice, answer_time in self._scheduled_bots:
            if now < answer_time:
                remaining.append((bot_name, choice, answer_time))
                continue
            if real_in_round + bots_in_round >= MIN_PLAYERS:
                continue
            if bot_name not in self.current_answers:
                self.current_answers[bot_name] = (choice, now)
                self.lock_order.append((bot_name, now - self.question_start_time))
                self.db.get_or_create_player(bot_name)
                self.sound_queue.append("answer_lock")
                bots_in_round += 1
                self._bots_in_round += 1
        self._scheduled_bots = remaining

    # ------------------------------------------
    # VOTE RESOLUTION
    # ------------------------------------------
    def _resolve_vote(self):
        if not self.vote_state:
            return
        counts = self.vote_state.vote_counts()
        top = max(counts.values()) if counts else 0
        if top == 0:
            winner = random.choice(list(self.vote_state.options))
        else:
            winner = random.choice([o for o, c in counts.items() if c == top])
        cid, name = self.vote_state.options[winner]
        self._set_category(cid)
        self.match_category = name
        self._push_event(f"Category: {name}!", COLOR_TEXT_GOLD, "VOTE")

    def _set_category(self, category_id):
        """Change category and flush stale questions from the cache."""
        if category_id != self._current_category_id:
            self._question_cache.clear()
        self._current_category_id = category_id

    # ------------------------------------------
    # CHAT COMMANDS
    # ------------------------------------------
    def _check_command_cooldown(self, username: str) -> bool:
        now = time.time()
        if now - self._command_cooldowns.get(username, 0) < COMMAND_COOLDOWN:
            return False
        self._command_cooldowns[username] = now
        return True

    def _cmd_crew(self, username: str, rest: str):
        if is_bot(username):
            return
        player = self.db.get_or_create_player(username)
        if not rest:
            if player.crew:
                n = len(self.db.crew_members(player.crew))
                self._push_event(f"{username} is in crew {player.crew} ({n} members)", COLOR_AMBER, "CREW")
            return
        if rest.lower() in ("leave", "quit", "none"):
            if player.crew:
                self._push_event(f"{username} left crew {player.crew}", (150, 140, 130), "CREW")
                player.crew = ""
                self.db.mark_dirty(username)
            return
        name = clean_crew_name(rest)
        if not name or name == player.crew:
            return
        existing = next((p.crew for p in self.db._players.values() if p.crew.lower() == name.lower()), None)
        player.crew = existing or name
        self.db.mark_dirty(username)
        verb = "joined" if len(self.db.crew_members(player.crew)) > 1 else "founded"
        self._push_event(f"{username} {verb} crew {player.crew}!", COLOR_AMBER, "CREW")
        self.sound_queue.append("vote")

    def _cmd_duel(self, username: str, rest: str):
        if is_bot(username) or not rest:
            return
        target = self.db.find_player(rest.split()[0])
        if not target or target == username:
            return
        match_no = self.match_no if self.state in (GameState.LOBBY, GameState.WAITING) else self.match_no + 1
        self.duels = [d for d in self.duels if not (d.a == username and not d.accepted)]
        self.duels.append(Duel(username, target, match_no))
        self._push_event(f"{username} challenges {target} to a duel! {target}: type !accept",
                         COLOR_EVENT_RED, "DUEL")
        self.sound_queue.append("double_points")

    def _cmd_accept(self, username: str):
        for d in self.duels:
            if d.b == username and not d.accepted:
                if any(x.accepted and x.match_no == d.match_no and username in (x.a, x.b) for x in self.duels):
                    return  # one duel per match
                d.accepted = True
                self._push_event(f"DUEL ON: {d.a} vs {d.b} in match {d.match_no}!", COLOR_EVENT_RED, "DUEL")
                self.sound_queue.append("rank_up")
                return

    def _cmd_half(self, username: str, rest: str, at: float | None = None):
        """50:50 joker: "!half 1 3" answers with two options; right if either is, for half the points.
        Once per match, from a HALF_STREAK answer streak in this match; not on crowd or two-option rounds."""
        q = self.current_question
        if (is_bot(username) or self.state not in (GameState.ASKING, GameState.LOCKING) or not q
                or q.kind in CROWD_KINDS or len(q.options) < 4 or username in self.halves_used):
            return
        st = self.standings.get(username)
        if not st or st.streak < HALF_STREAK:
            return
        digits = [c for c in rest if not c.isspace()]
        picks = sorted({int(c) - 1 for c in digits if c in "1234"})
        if len(digits) != 2 or len(picks) != 2:
            return   # exactly two different options, nothing else
        old = self.current_answers.get(username)
        if old and self.state != GameState.ASKING:
            return   # answers are locked once time is up
        self._record_answer(username, picks[0], at)
        self.half_picks[username] = (picks[0], picks[1])
        self.halves_used.add(username)
        self._push_event(f"{username} plays the 50:50 joker!", COLOR_EVENT_PURPLE, "50")
        self.sound_queue.append("vote")

    def process_message(self, username: str, message: str, raw: str = "", at: float | None = None):
        """at: when the answer arrived (the answer page stamps it on receipt); None = now."""
        msg = message.strip().lower()  # chat already stripped punctuation: "!rank" arrives as "rank"

        if msg in ("reset", "clear"):
            if self._check_command_cooldown(username):
                self.db.reset_player(username)
                self._push_event(f"{username} reset their score", (150, 140, 130), "RST")
            return

        if msg in ("score", "points", "rank", "me"):
            if self._check_command_cooldown(username):
                p = self.db.get_or_create_player(username)
                pos = self.db.weekly_rank(username)
                where = f"#{pos} this week" if pos else "not on this week's ladder yet"
                self._push_event(
                    f"{username}: {where}, {p.current_weekly():,} pts, level {p.level}, {p.day_streak}-day streak",
                    COLOR_TEXT_GOLD, "PTS",
                )
            return

        cmd = msg.split(" ", 1)[0]
        if cmd == "crew":
            self._cmd_crew(username, _rest_after_command(raw or msg))
            return
        if cmd == "duel":
            self._cmd_duel(username, _rest_after_command(raw or msg))
            return
        if msg == "accept":
            self._cmd_accept(username)
            return
        if cmd in ("half", "5050"):
            self._cmd_half(username, _rest_after_command(msg), at)
            return
        if msg == "card":
            if self._check_command_cooldown(username) and not is_bot(username):
                self.db.get_or_create_player(username)
                start = max(time.time(), self.cards[-1][1] + 6.0 if self.cards else 0.0)  # cards queue, 6 s each
                if start - time.time() < 30:
                    self.cards = (self.cards + [(username, start)])[-5:]
            return

        if msg in ("ready", "join", "play"):
            if self.state == GameState.LOBBY and username not in self.ready_players:
                self.ready_players.append(username)
                self.sound_queue.append("vote")
            return

        if username.lower() in ("themomatthias", "@themomatthias"):
            if msg in ("clear_bots", "clearbots"):
                self.clear_bots()
                return
            if msg in ("reset_bots", "resetbots"):
                self.reset_bot_scores()
                return
            if msg in ("reset_all", "resetall"):
                self.reset_all_scores()
                return

        # Only a bare digit counts ("2nd place" or "1000" do not).
        if msg not in ("1", "2", "3", "4"):
            return
        choice = int(msg) - 1

        if self.state in (GameState.ASKING, GameState.LOCKING):
            if self.current_question and choice < len(self.current_question.options):  # "3" on true/false
                if self.state == GameState.ASKING:
                    self.half_picks.pop(username, None)   # a plain answer replaces the 50:50 (the joker stays spent)
                self._record_answer(username, choice, at)
        elif self.state == GameState.LOBBY and self.vote_state:
            vote = choice + 1
            if vote in self.vote_state.options:
                if username not in self.vote_state.votes:
                    self.sound_queue.append("vote")
                self.vote_state.votes[username] = vote
                if username not in self.ready_players and not is_bot(username):
                    self.ready_players.append(username)

    def _record_answer(self, username: str, choice: int, at: float | None = None):
        now = time.time()
        if at:  # sent-at time, but never before this question started or in the future
            now = min(max(at, self.question_start_time), now)
        old = self.current_answers.get(username)
        if old is None:
            self.current_answers[username] = (choice, now)
            self.lock_order.append((username, now - self.question_start_time))
            self.sound_queue.append("answer_lock")
        elif old[0] != choice and self.state == GameState.ASKING:
            self.current_answers[username] = (choice, now)  # changing costs speed bonus
            self.sound_queue.append("answer_lock")
        else:
            return

        if is_bot(username):
            return
        self._remove_excess_bots()
        player = self.db.get_or_create_player(username)
        if player.mark_played(now) and player.day_streak > 1:
            self._push_event(f"{username}: {player.day_streak}-day streak!", COLOR_AMBER, "DAY")
        self.db.mark_dirty(username)
        if username not in self._known_players:
            self._known_players.add(username)
            self.new_players_this_round.append(username)
            self._push_event(f"Welcome {username}! First time here", COLOR_CORRECT, "NEW")

    # ------------------------------------------
    # ACCESSORS
    # ------------------------------------------
    @property
    def time_remaining(self) -> float:
        return max(0, self.state_timer)

    @property
    def time_fraction(self) -> float:
        if self.state_duration <= 0:
            return 0
        return max(0, min(1, self.state_timer / self.state_duration))

    @property
    def phase_age(self) -> float:
        return time.time() - self.state_start_time

    @property
    def answer_count(self) -> int:
        return len(self.current_answers)

    @property
    def active_player_count(self) -> int:
        """Real players in this round, or last round's if this one has just started."""
        return max(self._count_real_in_round(), len(self._last_round_real_players))

    def announce(self, text: str):
        self._push_event(text, COLOR_CORRECT, "LINK")

    def match_ranking(self, n: int = 5) -> list[MatchStanding]:
        ranked = sorted(self.standings.values(), key=lambda s: (-s.points, s.fastest or 999))
        return ranked[:n]

    @property
    def leaderboard(self) -> list[Player]:
        """This week's ladder."""
        return self.db.get_weekly_top()

    @property
    def current_category_name(self) -> str:
        if self.current_question and self.current_question.category:
            return self.current_question.category
        return self.match_category

    @property
    def uptime(self) -> float:
        return time.time() - self.session_start_time


def _question_to_item(q: Question, cat_id=None) -> dict:
    return {
        "text": q.text, "correct": q.correct_answer,
        "wrong": [o for o in q.options if o != q.correct_answer],
        "category": q.category, "difficulty": q.difficulty, "fact": q.fact, "cat_id": cat_id,
    }


def is_bot(username: str) -> bool:
    return username.startswith(BOT_PREFIX)
