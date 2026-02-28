"""
The Lifelong Quiz - Game Logic
State machine, question fetching, scoring, theme voting, addictive mechanics.
"""

import time
import html
import random
import threading

try:
    import requests
except ImportError:
    requests = None

from quiz.config import (
    QUESTION_DISPLAY_TIME, REVEAL_DISPLAY_TIME, LEADERBOARD_DISPLAY_TIME,
    THEME_VOTE_TIME, ROUNDS_BEFORE_VOTE,
    BASE_POINTS, SPEED_BONUS_TIER1_THRESHOLD, SPEED_BONUS_TIER2_THRESHOLD,
    SPEED_BONUS_TIER1_MULT, SPEED_BONUS_TIER2_MULT,
    STREAK_BONUS_PER, MAX_STREAK_MULT,
    OTDB_BASE_URL, OTDB_TOKEN_URL, OTDB_BATCH_SIZE,
    OTDB_MIN_CACHE, OTDB_REQUEST_COOLDOWN, OTDB_SEEN_EXPIRY,
    VOTABLE_CATEGORIES,
    DOUBLE_POINTS_CHANCE, DOUBLE_POINTS_MULT,
    COMEBACK_BONUS, COMEBACK_STREAK_THRESHOLD,
    STREAK_MILESTONES, ACHIEVEMENTS,
    CHAT_FEED_MAX, CHAT_FEED_DURATION,
    COMPETITION_ALERT_THRESHOLD,
    MIN_PLAYERS, BOT_DIFFICULTY, LATE_ANSWER_GRACE,
    COLOR_CORRECT, COLOR_TEXT_GOLD, COLOR_AMBER, COLOR_RANK_DIAMOND,
    LIGHTNING_ROUND_CHANCE, JACKPOT_CHANCE, FIRST_BLOOD_CHANCE,
    LIGHTNING_TIME, LIGHTNING_MULT, JACKPOT_BONUS, FIRST_BLOOD_BONUS,
    PARTICIPATION_MILESTONES, PARTICIPATION_BONUS, STREAK_SHIELD_THRESHOLD,
    COMMAND_COOLDOWN,
)
from quiz.models import (
    GameState, Player, Question, RoundResult, ThemeVoteState, GameEvent,
)
from quiz.db import QuizDatabase


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


class QuizLogic:
    def __init__(self, db: QuizDatabase):
        self.db = db
        self.state = GameState.WAITING
        self.state_timer = 0.0
        self.state_start_time = 0.0
        self.state_duration = 0.0

        # Grace period: remember previous state so late messages still count
        self._prev_state = GameState.WAITING
        self._prev_state_end_time = 0.0

        # Questions
        self._question_cache: list[Question] = []
        self._session_token = ""
        self._last_fetch_time = 0.0
        self._fetch_in_progress = False
        self._current_category_id = None
        self._fallback_idx = 0
        self._seen_questions: dict[str, float] = {}  # question_text -> timestamp

        # Current round
        self.current_question: Question | None = None
        self.current_answers: dict[str, tuple[int, float]] = {}
        self.question_start_time = 0.0

        # Results
        self.last_result: RoundResult | None = None
        self.round_count = 0
        self.session_start_time = time.time()

        # Theme voting
        self.vote_state: ThemeVoteState | None = None

        # Leaderboard cache & position change tracking
        self._leaderboard: list[Player] = []
        self._prev_positions: dict[str, int] = {}  # username -> 1-indexed position
        self.leaderboard_changes: list[dict] = []   # [{username, old_pos, new_pos}]

        # --- Addictive mechanics ---
        self.is_double_points = False
        self.mini_event = ""  # "lightning", "jackpot", "first_blood", or ""
        self.event_feed: list[GameEvent] = []
        self.sound_queue: list[str] = []  # sound names to play this frame
        self.competition_alert = ""  # close race message
        self.new_players_this_round: list[str] = []
        self._known_players: set[str] = set(db._players.keys())
        self._command_cooldowns: dict[str, float] = {}  # username -> last command time
        self._participants_this_round: set[str] = set()  # tracks who answered this round

        # Filler bots
        self._scheduled_bots: list[tuple[str, int, float]] = []  # (name, choice, answer_time)
        self._last_round_real_players: set[str] = set()  # who played last round
        self._active_bot_names: list[str] = []  # bots currently in play (random subset)
        self._bots_active = False

        # Kick off token fetch + pre-fill cache
        self._fetch_session_token()
        self._ensure_cache()

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

    def _pop_question(self) -> Question:
        if self._question_cache:
            q = self._question_cache.pop(0)
            self._seen_questions[self._hash_question(q)] = time.time()
            return q
        # Fallback: pick a random unseen question from the pool
        self._purge_seen()
        unseen = [q for q in FALLBACK_QUESTIONS
                  if self._hash_question(q) not in self._seen_questions]
        if not unseen:
            # All seen recently — allow any and clear seen fallbacks
            unseen = list(FALLBACK_QUESTIONS)
        q = random.choice(unseen)
        self._seen_questions[self._hash_question(q)] = time.time()
        options = list(q.options)
        random.shuffle(options)
        correct_index = options.index(q.correct_answer)
        return Question(
            text=q.text, correct_answer=q.correct_answer,
            options=options, correct_index=correct_index,
            category=q.category, difficulty=q.difficulty,
        )

    # ------------------------------------------
    # STATE MACHINE
    # ------------------------------------------
    def update(self, dt: float):
        self.sound_queue.clear()
        self._ensure_cache()

        if self.state == GameState.WAITING:
            # Fallback questions are always available, so always ready
            self._transition_to(GameState.ASKING)
            return

        self.state_timer -= dt

        # Bot answers + timer sounds during ASKING
        if self.state == GameState.ASKING:
            self._process_bot_answers()

            remaining = self.time_remaining
            frac = self.time_fraction
            if remaining <= 5:
                self.sound_queue.append("countdown")
            elif frac < 0.25:
                self.sound_queue.append("tick_urgent")
            elif frac < 0.5:
                self.sound_queue.append("tick")

        if self.state_timer <= 0:
            self._on_state_expired()

    def _transition_to(self, state: GameState):
        self._prev_state = self.state
        self._prev_state_end_time = time.time()
        self.state = state
        self.state_start_time = time.time()
        self.sound_queue.append("whoosh")

        if state == GameState.ASKING:
            self.state_duration = QUESTION_DISPLAY_TIME
            self.state_timer = QUESTION_DISPLAY_TIME
            self._enter_asking()
        elif state == GameState.REVEALING:
            self.state_duration = REVEAL_DISPLAY_TIME
            self.state_timer = REVEAL_DISPLAY_TIME
            self._enter_revealing()
        elif state == GameState.LEADERBOARD:
            self.state_duration = LEADERBOARD_DISPLAY_TIME
            self.state_timer = LEADERBOARD_DISPLAY_TIME
            self._enter_leaderboard()
        elif state == GameState.THEME_VOTE:
            self.state_duration = THEME_VOTE_TIME
            self.state_timer = THEME_VOTE_TIME
            self._enter_theme_vote()

    def _on_state_expired(self):
        if self.state == GameState.ASKING:
            self._transition_to(GameState.REVEALING)
        elif self.state == GameState.REVEALING:
            self._transition_to(GameState.LEADERBOARD)
        elif self.state == GameState.LEADERBOARD:
            if self.round_count > 0 and self.round_count % ROUNDS_BEFORE_VOTE == 0:
                self._transition_to(GameState.THEME_VOTE)
            else:
                self._transition_to(GameState.ASKING)
        elif self.state == GameState.THEME_VOTE:
            self._resolve_vote()
            self._transition_to(GameState.ASKING)

    # ------------------------------------------
    # STATE ENTRY ACTIONS
    # ------------------------------------------
    def _enter_asking(self):
        # Track participation streaks from previous round
        self._update_participation_streaks()

        # Snapshot real players from previous round (before clearing answers)
        self._last_round_real_players = {
            u for u in self.current_answers if not u.startswith(BOT_PREFIX)
        }

        self._ensure_cache()
        self.current_question = self._pop_question()
        self.current_answers = {}
        self._participants_this_round = set()
        self.question_start_time = time.time()
        cat_name = VOTABLE_CATEGORIES.get(self._current_category_id, "Any")
        print(f"[Game] Question: category={self.current_question.category} (requested={cat_name}, cache={len(self._question_cache)})")
        self.new_players_this_round = []
        self.sound_queue.append("new_question")

        # Double points roll
        self.is_double_points = random.random() < DOUBLE_POINTS_CHANCE
        if self.is_double_points:
            self._push_event(
                "DOUBLE POINTS ROUND!", COLOR_TEXT_GOLD, "2X",
            )
            self.sound_queue.append("double_points")

        # Mini event roll (only one per round, priority order)
        self.mini_event = ""
        if not self.is_double_points:
            roll = random.random()
            if roll < LIGHTNING_ROUND_CHANCE:
                self.mini_event = "lightning"
                self._push_event(
                    "LIGHTNING ROUND! 15s, 1.5x points!",
                    (100, 180, 255), "ZAP",
                )
                self.sound_queue.append("double_points")
            elif roll < LIGHTNING_ROUND_CHANCE + FIRST_BLOOD_CHANCE:
                self.mini_event = "first_blood"
                self._push_event(
                    f"FIRST BLOOD! +{FIRST_BLOOD_BONUS} pts for fastest!",
                    (255, 80, 80), "1ST",
                )
                self.sound_queue.append("double_points")
            elif roll < LIGHTNING_ROUND_CHANCE + FIRST_BLOOD_CHANCE + JACKPOT_CHANCE:
                self.mini_event = "jackpot"
                self._push_event(
                    f"JACKPOT ROUND! Random winner gets +{JACKPOT_BONUS} pts!",
                    (180, 100, 255), "JP",
                )
                self.sound_queue.append("double_points")

        # Override question time for lightning round
        if self.mini_event == "lightning":
            self.state_duration = LIGHTNING_TIME
            self.state_timer = LIGHTNING_TIME

        # Schedule filler bots
        self._schedule_bots()

    def _enter_revealing(self):
        self.round_count += 1
        self.last_result = self._resolve_question()

        # Sound based on results
        if self.last_result.correct_players:
            self.sound_queue.append("correct")
        else:
            self.sound_queue.append("wrong")

    def _enter_leaderboard(self):
        self._leaderboard = self.db.get_top_players()
        self._detect_position_changes()
        self.sound_queue.append("fanfare")
        self._check_competition()

    def _detect_position_changes(self):
        """Compare new leaderboard to previous positions, track top-5 climbers."""
        self.leaderboard_changes = []
        new_positions = {}
        for i, player in enumerate(self._leaderboard):
            new_positions[player.username] = i + 1  # 1-indexed

        for username, new_pos in new_positions.items():
            if new_pos > 5:
                continue  # only track top 5
            old_pos = self._prev_positions.get(username)
            if old_pos is None:
                # New entry into top 5
                if len(self._prev_positions) > 0:  # skip first round
                    self.leaderboard_changes.append({
                        "username": username,
                        "old_pos": 0,
                        "new_pos": new_pos,
                    })
            elif new_pos < old_pos:
                # Climbed up
                self.leaderboard_changes.append({
                    "username": username,
                    "old_pos": old_pos,
                    "new_pos": new_pos,
                })

        if self.leaderboard_changes:
            self.sound_queue.append("rank_up")
            for change in self.leaderboard_changes:
                name = change["username"]
                if change["old_pos"] == 0:
                    self._push_event(
                        f"{name} enters the TOP {change['new_pos']}!",
                        COLOR_TEXT_GOLD, "UP",
                    )
                else:
                    self._push_event(
                        f"{name} climbs to #{change['new_pos']}!",
                        COLOR_TEXT_GOLD, "UP",
                    )

        # Save current positions for next comparison
        self._prev_positions = new_positions

    def _enter_theme_vote(self):
        available = list(VOTABLE_CATEGORIES.items())
        if self._current_category_id:
            available = [
                (cid, name) for cid, name in available
                if cid != self._current_category_id
            ]
        chosen = random.sample(available, min(4, len(available)))
        options = {i: (cid, name) for i, (cid, name) in enumerate(chosen, 1)}
        self.vote_state = ThemeVoteState(options=options)

    # ------------------------------------------
    # PARTICIPATION STREAKS
    # ------------------------------------------
    def _update_participation_streaks(self):
        """Update participation streaks at the start of a new round (for previous round)."""
        if not self.current_answers:
            return
        all_players = set(self.db._players.keys())
        participated = {
            u for u in self.current_answers if not u.startswith(BOT_PREFIX)
        }
        for username in participated:
            player = self.db._players.get(username)
            if not player:
                continue
            player.participation_streak += 1
            # Award streak shield when threshold reached
            if player.streak >= STREAK_SHIELD_THRESHOLD and not player.streak_shield:
                player.streak_shield = True
            # Participation milestones
            if player.participation_streak in PARTICIPATION_MILESTONES:
                player.score += PARTICIPATION_BONUS
                self._push_event(
                    f"{username} played {player.participation_streak} rounds! +{PARTICIPATION_BONUS} pts",
                    COLOR_AMBER, "PLAY",
                )
                self.sound_queue.append("streak")
            self.db.mark_dirty(username)

        # Reset participation streak for players who didn't participate
        for username in all_players - participated:
            player = self.db._players.get(username)
            if player and player.participation_streak > 0 and not username.startswith(BOT_PREFIX):
                player.participation_streak = 0
                self.db.mark_dirty(username)

    # ------------------------------------------
    # QUESTION RESOLUTION & SCORING
    # ------------------------------------------
    def _resolve_question(self) -> RoundResult:
        if not self.current_question:
            return RoundResult(
                question=Question("?", "?", [], 0, "", ""),
                correct_players=[], wrong_players=[], total_answers=0,
            )

        correct_idx = self.current_question.correct_index
        correct_players = []
        wrong_players = []

        for username, (choice, timestamp) in self.current_answers.items():
            player = self.db.get_or_create_player(username)
            old_streak = player.streak
            old_rank = player.rank

            if choice == correct_idx:
                pts = self._calculate_points(timestamp, player.streak)

                # Lightning round multiplier
                if self.mini_event == "lightning":
                    pts = int(pts * LIGHTNING_MULT)

                # Double points
                if self.is_double_points:
                    pts = int(pts * DOUBLE_POINTS_MULT)

                # Comeback bonus
                was_wrong = player.wrong_streak
                if was_wrong >= COMEBACK_STREAK_THRESHOLD:
                    pts += COMEBACK_BONUS
                    self._push_event(
                        f"{username} COMEBACK! +{COMEBACK_BONUS} bonus",
                        COLOR_CORRECT, "BACK",
                    )
                    self.sound_queue.append("streak")

                player.record_correct(pts)
                answer_time = timestamp - self.question_start_time

                # Achievement checks
                self._check_achievements(player, answer_time, old_streak, old_rank)

                correct_players.append((username, pts, answer_time))
            else:
                player.record_wrong()
                # Streak shield notification
                if getattr(player, '_shield_used', False):
                    self._push_event(
                        f"{username} SHIELD! Streak saved (x{player.streak})",
                        (100, 180, 255), "SHD",
                    )
                    self.sound_queue.append("streak")
                wrong_players.append((username, choice))

            self.db.mark_dirty(username)

        # Find fastest
        fastest_player = ""
        fastest_time = 0.0
        if correct_players:
            fastest = min(correct_players, key=lambda x: x[2])
            fastest_player = fastest[0]
            fastest_time = fastest[2]

        # Mini event: First Blood bonus
        if self.mini_event == "first_blood" and correct_players:
            fb_name = fastest_player
            fb_player = self.db.get_or_create_player(fb_name)
            fb_player.score += FIRST_BLOOD_BONUS
            self.db.mark_dirty(fb_name)
            self._push_event(
                f"{fb_name} FIRST BLOOD! +{FIRST_BLOOD_BONUS} bonus ({fastest_time:.1f}s)",
                (255, 80, 80), "1ST",
            )
            self.sound_queue.append("rank_up")

        # Mini event: Jackpot - random correct player wins bonus
        if self.mini_event == "jackpot" and correct_players:
            jp_name, _, _ = random.choice(correct_players)
            jp_player = self.db.get_or_create_player(jp_name)
            jp_player.score += JACKPOT_BONUS
            self.db.mark_dirty(jp_name)
            self._push_event(
                f"{jp_name} wins the JACKPOT! +{JACKPOT_BONUS} pts!",
                (180, 100, 255), "JP",
            )
            self.sound_queue.append("rank_up")

        return RoundResult(
            question=self.current_question,
            correct_players=correct_players,
            wrong_players=wrong_players,
            total_answers=len(self.current_answers),
            fastest_player=fastest_player,
            fastest_time=fastest_time,
        )

    def _calculate_points(self, answer_timestamp: float, current_streak: int) -> int:
        elapsed = answer_timestamp - self.question_start_time
        time_fraction = max(0, min(1, elapsed / QUESTION_DISPLAY_TIME))

        if time_fraction <= SPEED_BONUS_TIER1_THRESHOLD:
            speed_mult = SPEED_BONUS_TIER1_MULT
        elif time_fraction <= SPEED_BONUS_TIER2_THRESHOLD:
            speed_mult = SPEED_BONUS_TIER2_MULT
        else:
            speed_mult = 1.0

        streak_mult = min(MAX_STREAK_MULT, 1.0 + current_streak * STREAK_BONUS_PER)

        total = int(BASE_POINTS * speed_mult * streak_mult)
        return max(1, total)

    # ------------------------------------------
    # ACHIEVEMENT CHECKS
    # ------------------------------------------
    def _check_achievements(self, player: Player, answer_time: float,
                            old_streak: int, old_rank: str):
        # First correct ever
        if player.correct_answers == 1:
            self._push_event(
                f"{player.username} earned FIRST BLOOD!",
                COLOR_TEXT_GOLD, "ACH",
            )

        # Streak milestones
        if player.streak in STREAK_MILESTONES:
            names = {
                3: "On Fire", 5: "Unstoppable", 10: "Legendary Streak",
                15: "Quiz Machine", 25: "GODLIKE", 50: "Transcendent",
                100: "The Chosen One",
            }
            name = names.get(player.streak, f"{player.streak} Streak!")
            self._push_event(
                f"{player.username}: {name} (x{player.streak})",
                COLOR_TEXT_GOLD, "FIRE",
            )
            self.sound_queue.append("streak")

        # Speed demon (under 2 seconds)
        if answer_time < 2.0:
            self._push_event(
                f"{player.username} SPEED DEMON ({answer_time:.1f}s)",
                COLOR_RANK_DIAMOND, "FAST",
            )

        # Rank up
        if player.rank != old_rank:
            self._push_event(
                f"{player.username} ranked up to {player.rank}!",
                COLOR_TEXT_GOLD, "UP",
            )
            self.sound_queue.append("rank_up")

        # Centurion (100 games)
        if player.games_played == 100:
            self._push_event(
                f"{player.username} played 100 rounds! CENTURION",
                COLOR_AMBER, "100",
            )

    # ------------------------------------------
    # COMPETITION ALERTS
    # ------------------------------------------
    def _check_competition(self):
        self.competition_alert = ""
        if len(self._leaderboard) < 2:
            return
        top = self._leaderboard[0]
        second = self._leaderboard[1]
        gap = top.score - second.score
        if 0 < gap <= COMPETITION_ALERT_THRESHOLD:
            self.competition_alert = (
                f"{second.username} is only {gap} pts behind {top.username}!"
            )

    # ------------------------------------------
    # ADMIN ACTIONS
    # ------------------------------------------
    def clear_bots(self):
        """Remove all bot players from DB and cancel scheduled bot answers."""
        self._scheduled_bots = []
        self._bots_active = False
        self.db.remove_players(BOT_PROFILES)
        # Also remove from current round answers
        for bot_name in BOT_PROFILES:
            self.current_answers.pop(bot_name, None)
        self._push_event("Bots cleared!", COLOR_CORRECT, "ADM")
        print("[Game] Admin: all bots cleared")

    def reset_all_scores(self):
        """Reset scores for all players."""
        count = self.db.reset_all_players()
        self._push_event(f"All {count} players reset!", COLOR_AMBER, "ADM")
        print(f"[Game] Admin: reset all {count} player scores")

    def reset_bot_scores(self):
        """Reset bot scores to 0 but keep them playing."""
        count = 0
        for bot_name in BOT_PROFILES:
            player = self.db._players.get(bot_name)
            if player:
                player.score = 0
                player.streak = 0
                player.best_streak = 0
                player.games_played = 0
                player.correct_answers = 0
                player.wrong_answers = 0
                player.wrong_streak = 0
                self.db.mark_dirty(bot_name)
                count += 1
        self._push_event(f"{count} bot scores reset!", COLOR_AMBER, "ADM")
        print(f"[Game] Admin: reset {count} bot scores")

    # ------------------------------------------
    # FILLER BOTS
    # ------------------------------------------
    def _count_real_players(self) -> int:
        """Count active real players: those who played last round."""
        return len(self._last_round_real_players)

    def _count_real_in_round(self) -> int:
        """Count real players who have answered in the current round."""
        return sum(
            1 for u in self.current_answers if not u.startswith(BOT_PREFIX)
        )

    def _count_bots_in_round(self) -> int:
        """Count bots who have answered in the current round."""
        return sum(
            1 for u in self.current_answers if u.startswith(BOT_PREFIX)
        )

    def _schedule_bots(self):
        """Schedule filler bot answers for this round."""
        self._scheduled_bots = []

        # Use last round's real player count as our estimate
        real_count = self._count_real_players()

        # Fill to exactly MIN_PLAYERS total
        bots_needed = max(0, MIN_PLAYERS - real_count)

        if bots_needed == 0:
            if self._bots_active:
                self._bots_active = False
                self._active_bot_names = []
                self.db.remove_players(BOT_PROFILES)
                self._push_event(
                    "Enough players! Bots retired.", COLOR_CORRECT, "BYE",
                )
                print(f"[Game] Bots retired ({real_count} real players)")
            return

        # Randomly select which bots to use this round
        available_bots = list(BOT_PROFILES)
        random.shuffle(available_bots)
        active_bots = available_bots[:bots_needed]

        # Remove bots that are no longer needed
        retired_bots = [b for b in BOT_PROFILES if b not in active_bots]
        if retired_bots and self._bots_active:
            self.db.remove_players(retired_bots)

        self._active_bot_names = active_bots
        self._bots_active = True

        if not self.current_question:
            return

        correct_idx = self.current_question.correct_index
        num_options = len(self.current_question.options)
        diff = BOT_DIFFICULTY["easy"]
        q_time = self.state_duration  # respects lightning round

        for bot_name in active_bots:
            if random.random() < diff["accuracy"]:
                choice = correct_idx
            else:
                wrong_choices = [i for i in range(num_options) if i != correct_idx]
                choice = random.choice(wrong_choices)

            speed_frac = random.uniform(diff["speed_min"], diff["speed_max"])
            answer_time = self.question_start_time + speed_frac * q_time
            self._scheduled_bots.append((bot_name, choice, answer_time))

        print(f"[Game] Bots: scheduled {bots_needed} bots "
              f"(real_count={real_count}, bots={[b.replace(BOT_PREFIX,'') for b in active_bots]})")

    def _remove_excess_bots(self):
        """Remove bots mid-round when real players join. Called after a real player answers."""
        real_in_round = self._count_real_in_round()

        # If real players alone fill the lobby, remove ALL bots
        if real_in_round >= MIN_PLAYERS:
            bots_to_remove = [u for u in self.current_answers if u.startswith(BOT_PREFIX)]
            for bot_name in bots_to_remove:
                del self.current_answers[bot_name]
            self._scheduled_bots = []
            if bots_to_remove:
                print(f"[Game] Removed {len(bots_to_remove)} bot(s) "
                      f"(real players: {real_in_round})")
            if self._bots_active:
                self._bots_active = False
                self._active_bot_names = []
                self.db.remove_players(BOT_PROFILES)
                self._push_event(
                    "Enough players! Bots retired.", COLOR_CORRECT, "BYE",
                )
            return

        # Otherwise, trim bots so total = MIN_PLAYERS
        bots_in_round = [u for u in self.current_answers if u.startswith(BOT_PREFIX)]
        total = real_in_round + len(bots_in_round)
        excess = total - MIN_PLAYERS

        if excess > 0:
            # Randomly pick which bots to remove
            random.shuffle(bots_in_round)
            to_remove = bots_in_round[:excess]
            for bot_name in to_remove:
                del self.current_answers[bot_name]
            # Also cancel any scheduled bots that are now excess
            scheduled_names = {b[0] for b in self._scheduled_bots}
            active_bot_answers = {u for u in self.current_answers if u.startswith(BOT_PREFIX)}
            self._scheduled_bots = [
                (name, choice, t) for name, choice, t in self._scheduled_bots
                if name in active_bot_answers or (real_in_round + len(active_bot_answers) < MIN_PLAYERS)
            ]
            print(f"[Game] Trimmed {len(to_remove)} bot(s) "
                  f"(real: {real_in_round}, bots remaining: {len(bots_in_round) - len(to_remove)})")

    def _process_bot_answers(self):
        """Process scheduled bot answers, dynamically adjusting for real player count."""
        now = time.time()
        remaining = []

        real_in_round = self._count_real_in_round()
        bots_in_round = self._count_bots_in_round()

        for bot_name, choice, answer_time in self._scheduled_bots:
            if now >= answer_time:
                # Dynamic cap: skip if we already have enough total players
                if real_in_round + bots_in_round >= MIN_PLAYERS:
                    print(f"[Game] {bot_name} skipped (lobby full: "
                          f"{real_in_round} real + {bots_in_round} bots)")
                    continue

                if bot_name not in self.current_answers:
                    self.current_answers[bot_name] = (choice, now)
                    self.db.get_or_create_player(bot_name)
                    self.sound_queue.append("answer_lock")
                    bots_in_round += 1
                    print(f"[Game] {bot_name} locked in answer {choice + 1}")
            else:
                remaining.append((bot_name, choice, answer_time))
        self._scheduled_bots = remaining

    # ------------------------------------------
    # VOTE RESOLUTION
    # ------------------------------------------
    def _resolve_vote(self):
        if not self.vote_state or not self.vote_state.votes:
            cid = random.choice(list(VOTABLE_CATEGORIES.keys()))
            self._set_category(cid)
            return

        counts = self.vote_state.vote_counts()
        max_votes = max(counts.values())
        winners = [opt for opt, cnt in counts.items() if cnt == max_votes]
        winner = random.choice(winners)
        cid, name = self.vote_state.options[winner]
        self._set_category(cid)
        self._push_event(
            f"Next category: {name}!", COLOR_TEXT_GOLD, "VOTE",
        )
        print(f"[Vote] Winner: {name} ({max_votes} votes)")

    def _set_category(self, category_id):
        """Change category and flush stale questions from the cache."""
        if category_id != self._current_category_id:
            old_count = len(self._question_cache)
            self._question_cache.clear()
            if old_count > 0:
                cat_name = VOTABLE_CATEGORIES.get(category_id, category_id)
                print(f"[OTDB] Category changed to {cat_name}, flushed {old_count} cached questions")
        self._current_category_id = category_id

    # ------------------------------------------
    # CHAT COMMAND PROCESSING
    # ------------------------------------------
    def _check_command_cooldown(self, username: str) -> bool:
        """Return True if the player can use a command (not on cooldown)."""
        now = time.time()
        last = self._command_cooldowns.get(username, 0)
        if now - last < COMMAND_COOLDOWN:
            return False
        self._command_cooldowns[username] = now
        return True

    def process_message(self, username: str, message: str):
        msg = message.strip().lower()

        if msg in ("reset", "clear"):
            if not self._check_command_cooldown(username):
                return
            self.db.reset_player(username)
            self._push_event(
                f"{username} reset their score", (150, 140, 130), "RST",
            )
            return

        if msg in ("score", "points"):
            if not self._check_command_cooldown(username):
                return
            player = self.db.get_or_create_player(username)
            self._push_event(
                f"{username}: {player.score:,} pts | {player.rank} | x{player.streak} streak",
                COLOR_TEXT_GOLD, "PTS",
            )
            return

        # Admin commands (themomatthias only)
        if username.lower() == "themomatthias":
            if msg in ("clear_bots", "clearbots"):
                self.clear_bots()
                return
            elif msg in ("reset_bots", "resetbots"):
                self.reset_bot_scores()
                return
            elif msg in ("reset_all", "resetall"):
                self.reset_all_scores()
                return

        # Accept "1", "2", "3", "4" — already normalized by chat (punctuation stripped)
        # Also handle edge cases: "1 ", "answer 2", etc. — check first char
        answer = ""
        if msg in ("1", "2", "3", "4"):
            answer = msg
        elif len(msg) <= 10 and msg and msg[0] in "1234":
            # Short message starting with a valid digit (e.g. "1!" normalized to "1")
            answer = msg[0]

        if answer:
            choice = int(answer) - 1

            # Determine effective state: use grace period for late messages
            effective_state = self.state
            in_grace = False
            if self.state not in (GameState.ASKING, GameState.THEME_VOTE):
                elapsed = time.time() - self._prev_state_end_time
                if elapsed < LATE_ANSWER_GRACE and self._prev_state in (GameState.ASKING, GameState.THEME_VOTE):
                    effective_state = self._prev_state
                    in_grace = True

            if effective_state == GameState.ASKING:
                player = self.db.get_or_create_player(username)
                old_answer = self.current_answers.get(username)

                if in_grace and self.current_question:
                    if old_answer is None:
                        # Late first answer — score immediately
                        self.current_answers[username] = (choice, time.time())
                        correct_idx = self.current_question.correct_index
                        if choice == correct_idx:
                            pts = BASE_POINTS  # no speed bonus for late
                            player.record_correct(pts)
                            print(f"[Game] {username} late answer {msg} - CORRECT (+{pts} pts, grace period)")
                        else:
                            player.record_wrong()
                            print(f"[Game] {username} late answer {msg} - wrong (grace period)")
                        self.db.mark_dirty(username)
                        self.sound_queue.append("answer_lock")
                    else:
                        # Can't change answer after time expired
                        print(f"[Game] {username} tried to change answer during grace period (denied)")
                elif old_answer is None:
                    # First answer
                    self.current_answers[username] = (choice, time.time())
                    self.sound_queue.append("answer_lock")
                    print(f"[Game] {username} locked in answer {msg}")
                else:
                    # Changed answer — update choice and timestamp
                    old_choice = old_answer[0]
                    if old_choice != choice:
                        self.current_answers[username] = (choice, time.time())
                        self.sound_queue.append("answer_lock")
                        print(f"[Game] {username} changed answer from {old_choice + 1} to {msg}")
                    else:
                        print(f"[Game] {username} already picked {msg}")

                # Dynamically adjust bots when a real player answers
                if not username.startswith(BOT_PREFIX):
                    self._remove_excess_bots()

                # Welcome new players (skip bots)
                if username not in self._known_players:
                    self._known_players.add(username)
                    if not username.startswith(BOT_PREFIX):
                        self.new_players_this_round.append(username)
                        self._push_event(
                            f"Welcome {username}! First time here",
                            COLOR_CORRECT, "NEW",
                        )

            elif effective_state == GameState.THEME_VOTE:
                if self.vote_state:
                    vote_num = int(answer)
                    if vote_num in self.vote_state.options:
                        old_vote = self.vote_state.votes.get(username)
                        self.vote_state.votes[username] = vote_num
                        cat_name = self.vote_state.options[vote_num][1]
                        late_tag = " (late, grace period)" if in_grace else ""
                        if old_vote is None:
                            self.sound_queue.append("vote")
                            print(f"[Game] {username} voted #{vote_num} ({cat_name}){late_tag}")
                        else:
                            print(f"[Game] {username} changed vote to #{vote_num} ({cat_name}){late_tag}")
                    else:
                        print(f"[Game] {username} voted {vote_num} but options are {list(self.vote_state.options.keys())}")

            else:
                print(f"[Game] {username} sent '{msg}' during {self.state.name} (ignored)")

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
    def answer_count(self) -> int:
        return len(self.current_answers)

    @property
    def leaderboard(self) -> list[Player]:
        return self._leaderboard

    @property
    def current_category_name(self) -> str:
        # Show the actual question's category (from OTDB), not the configured one
        if self.current_question and self.current_question.category:
            return self.current_question.category
        if self._current_category_id and self._current_category_id in VOTABLE_CATEGORIES:
            return VOTABLE_CATEGORIES[self._current_category_id]
        return "General"

    @property
    def uptime(self) -> float:
        return time.time() - self.session_start_time
