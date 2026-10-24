"""
The Lifelong Quiz - Game Logic
A show is an endless cycle of matches:
LOBBY (vote, !ready) -> INTRO -> 10 x (ASKING -> LOCKING -> REVEALING) -> PODIUM.
Match points reset every match; weekly and lifetime points keep growing.
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
    MATCH_LENGTH, LOBBY_TIME, INTRO_TIME, QUESTION_DISPLAY_TIME,
    LATE_ANSWER_GRACE, REVEAL_DISPLAY_TIME, PODIUM_TIME,
    LIGHTNING_QUESTION, BONUS_QUESTIONS, FINAL_QUESTION_MULT, DIFFICULTY_RAMP,
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
    COMMAND_COOLDOWN,
)
from quiz.models import (
    GameState, Player, Question, RoundResult, ThemeVoteState, GameEvent, MatchStanding,
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


STATE_DURATIONS = {
    GameState.LOBBY: LOBBY_TIME,
    GameState.INTRO: INTRO_TIME,
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

        # Current round
        self.current_question: Question | None = None
        self.current_answers: dict[str, tuple[int, float]] = {}
        self.lock_order: list[tuple[str, float]] = []  # (username, seconds after question start)
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
        self.event_feed: list[GameEvent] = []
        self.sound_queue: list[str] = []
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

    def _pop_question(self, difficulty: str = "") -> Question:
        """Next question, preferring the requested difficulty (match ramp: easy -> hard)."""
        if self._question_cache:
            idx = next((i for i, q in enumerate(self._question_cache)
                        if q.difficulty == difficulty), 0)
            q = self._question_cache.pop(idx)
            self._seen_questions[self._hash_question(q)] = time.time()
            return q
        self._purge_seen()
        unseen = [q for q in FALLBACK_QUESTIONS
                  if self._hash_question(q) not in self._seen_questions]
        if not unseen:
            unseen = list(FALLBACK_QUESTIONS)
        preferred = [q for q in unseen if q.difficulty == difficulty]
        q = random.choice(preferred or unseen)
        self._seen_questions[self._hash_question(q)] = time.time()
        options = list(q.options)
        random.shuffle(options)
        return Question(
            text=q.text, correct_answer=q.correct_answer,
            options=options, correct_index=options.index(q.correct_answer),
            category=q.category, difficulty=q.difficulty,
        )

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
            self._transition_to(GameState.ASKING)
        elif s == GameState.ASKING:
            self._transition_to(GameState.LOCKING)
        elif s == GameState.LOCKING:
            self._transition_to(GameState.REVEALING)
        elif s == GameState.REVEALING:
            if self.q_index >= MATCH_LENGTH:
                self._transition_to(GameState.PODIUM)
            else:
                self._transition_to(GameState.ASKING)
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
        self.pips = []
        self.podium = []
        self.match_started_at = time.time()
        self._prev_weekly_positions = {
            p.username: i for i, p in enumerate(self.db.get_weekly_top(n=1_000_000), 1)
        }
        self.sound_queue.append("new_question")
        self._say(f"Match {self.match_no}: {self.match_category}. "
                  f"{MATCH_LENGTH} questions, fastest right answers score most. Good luck!")

    def _enter_asking(self):
        self._update_participation_streaks()
        self._last_round_real_players = {u for u in self.current_answers if not is_bot(u)}

        self.q_index += 1
        self._ensure_cache()
        self.current_question = self._pop_question(DIFFICULTY_RAMP.get(self.q_index, "medium"))
        self.current_answers = {}
        self.lock_order = []
        self.question_start_time = time.time()
        self.new_players_this_round = []
        self.sound_queue.append("new_question")

        # Fixed event slots give every match the same shape.
        self.is_double_points = self.q_index == MATCH_LENGTH
        self.mini_event = ""
        if self.q_index == LIGHTNING_QUESTION:
            self.mini_event = "lightning"
        elif self.q_index in BONUS_QUESTIONS:
            self.mini_event = random.choice(["first_blood", "jackpot"])

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
        else:
            diff = self.current_question.difficulty
            self._say(f"Question {self.q_index} of {MATCH_LENGTH}. "
                      f"{self.current_question.category}, {diff}.")

        self.question_duration = self.state_duration
        self._schedule_bots()

    def _enter_locking(self):
        self.sound_queue.append("tick_urgent")
        self._say("Time's up! Locking in the last answers...")

    def _enter_revealing(self):
        self.round_count += 1
        self.last_result = self._resolve_question()
        res = self.last_result
        self.pips.append("done" if res.total_answers and res.correct_rate >= 0.5 else "miss")
        self.sound_queue.append("correct" if res.correct_players else "wrong")
        self._say(host_line_for_rate(res.correct_rate, res.total_answers))

    def _enter_podium(self):
        real = [s for s in self.standings.values() if not is_bot(s.username)]
        real.sort(key=lambda s: (-s.points, s.fastest or 999))
        self.podium = [s for s in real if s.points > 0][:3]
        self.match_player_count = len(real)
        fastest = min((s for s in real if s.fastest > 0), key=lambda s: s.fastest, default=None)
        streak = max(real, key=lambda s: s.best_streak, default=None)
        self.match_stats = {
            "fastest": (fastest.username, fastest.fastest) if fastest else None,
            "best_streak": (streak.username, streak.best_streak) if streak and streak.best_streak else None,
        }
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
        option_counts = [0] * len(q.options)

        for username, (choice, timestamp) in self.current_answers.items():
            if 0 <= choice < len(option_counts):
                option_counts[choice] += 1
            player = self.db.get_or_create_player(username)
            st = self._standing(username)
            old_rank = player.rank
            answer_time = max(0.0, timestamp - self.question_start_time)

            if choice == q.correct_index:
                pts = self._calculate_points(timestamp, player.streak)
                if self.mini_event == "lightning":
                    pts = int(pts * LIGHTNING_MULT)
                if self.is_double_points:
                    pts = int(pts * FINAL_QUESTION_MULT)
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
            total_answers=len(self.current_answers),
            fastest_player=fastest_player, fastest_time=fastest_time,
            option_counts=option_counts,
        )

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
            if random.random() < diff["accuracy"]:
                choice = correct_idx
            else:
                choice = random.choice([i for i in range(n) if i != correct_idx])
            at = self.question_start_time + random.uniform(diff["speed_min"], diff["speed_max"]) * self.state_duration
            self._scheduled_bots.append((bot_name, choice, at))

    def _remove_excess_bots(self):
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

    def _process_bot_answers(self):
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

    def process_message(self, username: str, message: str):
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
            self._record_answer(username, choice)
        elif self.state == GameState.LOBBY and self.vote_state:
            vote = choice + 1
            if vote in self.vote_state.options:
                if username not in self.vote_state.votes:
                    self.sound_queue.append("vote")
                self.vote_state.votes[username] = vote
                if username not in self.ready_players and not is_bot(username):
                    self.ready_players.append(username)

    def _record_answer(self, username: str, choice: int):
        now = time.time()
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


def is_bot(username: str) -> bool:
    return username.startswith(BOT_PREFIX)
