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
    OTDB_MIN_CACHE, OTDB_REQUEST_COOLDOWN,
    VOTABLE_CATEGORIES,
    DOUBLE_POINTS_CHANCE, DOUBLE_POINTS_MULT,
    COMEBACK_BONUS, COMEBACK_STREAK_THRESHOLD,
    STREAK_MILESTONES, ACHIEVEMENTS,
    CHAT_FEED_MAX, CHAT_FEED_DURATION,
    COMPETITION_ALERT_THRESHOLD,
    MIN_PLAYERS, BOT_DIFFICULTY, LATE_ANSWER_GRACE,
    COLOR_CORRECT, COLOR_TEXT_GOLD, COLOR_AMBER, COLOR_RANK_DIAMOND,
)
from quiz.models import (
    GameState, Player, Question, RoundResult, ThemeVoteState, GameEvent,
)
from quiz.db import QuizDatabase


# Hardcoded fallback questions if API is unavailable
FALLBACK_QUESTIONS = [
    Question("What is the capital of France?", "Paris",
             ["London", "Berlin", "Paris", "Madrid"], 2, "Geography", "easy"),
    Question("How many legs does a spider have?", "8",
             ["6", "8", "10", "12"], 1, "Animals", "easy"),
    Question("What planet is known as the Red Planet?", "Mars",
             ["Venus", "Mars", "Jupiter", "Saturn"], 1, "Science", "easy"),
    Question("Who painted the Mona Lisa?", "Leonardo da Vinci",
             ["Michelangelo", "Leonardo da Vinci", "Raphael", "Donatello"], 1, "Art", "easy"),
    Question("What is the largest ocean on Earth?", "Pacific Ocean",
             ["Atlantic Ocean", "Indian Ocean", "Pacific Ocean", "Arctic Ocean"], 2, "Geography", "easy"),
    Question("In what year did the Titanic sink?", "1912",
             ["1905", "1912", "1920", "1898"], 1, "History", "easy"),
    Question("What element does 'O' represent on the periodic table?", "Oxygen",
             ["Gold", "Osmium", "Oxygen", "Oganesson"], 2, "Science", "easy"),
    Question("How many strings does a standard guitar have?", "6",
             ["4", "5", "6", "8"], 2, "Music", "easy"),
    Question("What is the smallest country in the world?", "Vatican City",
             ["Monaco", "Vatican City", "San Marino", "Liechtenstein"], 1, "Geography", "easy"),
    Question("Which gas do plants absorb from the atmosphere?", "Carbon Dioxide",
             ["Oxygen", "Nitrogen", "Carbon Dioxide", "Hydrogen"], 2, "Science", "easy"),
    Question("What is the hardest natural substance on Earth?", "Diamond",
             ["Gold", "Iron", "Diamond", "Platinum"], 2, "Science", "medium"),
    Question("Who wrote 'Romeo and Juliet'?", "William Shakespeare",
             ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"], 1, "Literature", "easy"),
]


BOT_PREFIX = "[Bot] "
BOT_PROFILES = [
    "[Bot] Rookie",
    "[Bot] Scholar",
    "[Bot] Professor",
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

        # Leaderboard cache
        self._leaderboard: list[Player] = []

        # --- Addictive mechanics ---
        self.is_double_points = False
        self.event_feed: list[GameEvent] = []
        self.sound_queue: list[str] = []  # sound names to play this frame
        self.competition_alert = ""  # close race message
        self.new_players_this_round: list[str] = []
        self._known_players: set[str] = set(db._players.keys())

        # Filler bots
        self._scheduled_bots: list[tuple[str, int, float]] = []  # (name, choice, answer_time)
        self._recent_real_answers: list[set[str]] = []  # rolling window of real player sets
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
        try:
            questions = self._fetch_questions(self._current_category_id)
            if questions:
                self._question_cache.extend(questions)
                print(f"[OTDB] Cached {len(questions)} questions (total: {len(self._question_cache)})")
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

    def _pop_question(self) -> Question:
        if self._question_cache:
            return self._question_cache.pop(0)
        q = FALLBACK_QUESTIONS[self._fallback_idx % len(FALLBACK_QUESTIONS)]
        self._fallback_idx += 1
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
        # Track real players from previous round (before clearing answers)
        if self.current_answers:
            real_this_round = {
                u for u in self.current_answers if not u.startswith(BOT_PREFIX)
            }
            self._recent_real_answers.append(real_this_round)
            if len(self._recent_real_answers) > 5:
                self._recent_real_answers.pop(0)

        self.current_question = self._pop_question()
        self.current_answers = {}
        self.question_start_time = time.time()
        self.new_players_this_round = []
        self.sound_queue.append("new_question")

        # Double points roll
        self.is_double_points = random.random() < DOUBLE_POINTS_CHANCE
        if self.is_double_points:
            self._push_event(
                "DOUBLE POINTS ROUND!", COLOR_TEXT_GOLD, "2X",
            )
            self.sound_queue.append("double_points")

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
        self.sound_queue.append("fanfare")
        self._check_competition()

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

                # Double points
                if self.is_double_points:
                    pts = int(pts * DOUBLE_POINTS_MULT)

                # Comeback bonus
                was_wrong = getattr(player, "wrong_streak", 0)
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
                wrong_players.append((username, choice))

            self.db.mark_dirty(username)

        # Find fastest
        fastest_player = ""
        fastest_time = 0.0
        if correct_players:
            fastest = min(correct_players, key=lambda x: x[2])
            fastest_player = fastest[0]
            fastest_time = fastest[2]

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

    # ------------------------------------------
    # FILLER BOTS
    # ------------------------------------------
    def _schedule_bots(self):
        """Schedule filler bot answers for this round."""
        self._scheduled_bots = []

        # Count unique real players across last 5 rounds
        if self._recent_real_answers:
            real_players = set().union(*self._recent_real_answers)
        else:
            real_players = set()
        real_count = len(real_players)

        # Fill to exactly MIN_PLAYERS (proportional: 3 real = 1 bot, 2 real = 2 bots, etc.)
        bots_needed = max(0, MIN_PLAYERS - real_count)

        if bots_needed == 0:
            if self._bots_active:
                self._bots_active = False
                self.db.remove_players(BOT_PROFILES)
                self._push_event(
                    "Enough players! Bots retired.", COLOR_CORRECT, "BYE",
                )
                print(f"[Game] Bots retired ({real_count} real players)")
            return

        # Remove bots that are no longer needed
        active_bots = BOT_PROFILES[:bots_needed]
        retired_bots = BOT_PROFILES[bots_needed:]
        if retired_bots and self._bots_active:
            self.db.remove_players(retired_bots)
            print(f"[Game] Retired {len(retired_bots)} bot(s), {bots_needed} remain ({real_count} real players)")

        self._bots_active = True

        if not self.current_question:
            return

        correct_idx = self.current_question.correct_index
        num_options = len(self.current_question.options)
        diff = BOT_DIFFICULTY["easy"]

        for bot_name in active_bots:
            # Pick answer based on easy accuracy
            if random.random() < diff["accuracy"]:
                choice = correct_idx
            else:
                wrong_choices = [i for i in range(num_options) if i != correct_idx]
                choice = random.choice(wrong_choices)

            # Schedule answer time
            speed_frac = random.uniform(diff["speed_min"], diff["speed_max"])
            answer_time = self.question_start_time + speed_frac * QUESTION_DISPLAY_TIME

            self._scheduled_bots.append((bot_name, choice, answer_time))

    def _process_bot_answers(self):
        """Process any scheduled bot answers whose time has arrived."""
        now = time.time()
        remaining = []
        for bot_name, choice, answer_time in self._scheduled_bots:
            if now >= answer_time:
                if bot_name not in self.current_answers:
                    self.current_answers[bot_name] = (choice, now)
                    self.db.get_or_create_player(bot_name)
                    self.sound_queue.append("answer_lock")
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
            self._current_category_id = cid
            return

        counts = self.vote_state.vote_counts()
        max_votes = max(counts.values())
        winners = [opt for opt, cnt in counts.items() if cnt == max_votes]
        winner = random.choice(winners)
        cid, name = self.vote_state.options[winner]
        self._current_category_id = cid
        self._push_event(
            f"Next category: {name}!", COLOR_TEXT_GOLD, "VOTE",
        )
        print(f"[Vote] Winner: {name} ({max_votes} votes)")

    # ------------------------------------------
    # CHAT COMMAND PROCESSING
    # ------------------------------------------
    def process_message(self, username: str, message: str):
        msg = message.strip().lower()

        if msg == "reset":
            self.db.reset_player(username)
            self._push_event(
                f"{username} reset their score", (150, 140, 130), "RST",
            )
            return

        # Admin commands (themomatthias only)
        if username.lower() == "themomatthias":
            if msg in ("clear_bots", "clearbots"):
                self.clear_bots()
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
        if self._current_category_id and self._current_category_id in VOTABLE_CATEGORIES:
            return VOTABLE_CATEGORIES[self._current_category_id]
        return "General"

    @property
    def uptime(self) -> float:
        return time.time() - self.session_start_time
