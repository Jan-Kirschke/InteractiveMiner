"""
The Lifelong Quiz - Data Models
Enums, dataclasses, and core data structures.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
import time

from quiz.config import RANK_THRESHOLDS


class GameState(Enum):
    WAITING = auto()
    LOBBY = auto()
    INTRO = auto()
    ASKING = auto()
    LOCKING = auto()
    REVEALING = auto()
    PODIUM = auto()


def utc_day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else time.time()))


def utc_week(ts: float | None = None) -> str:
    """ISO week, e.g. "2026-W43". Weekly ladders reset Monday 00:00 UTC."""
    y, w, _ = datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


@dataclass
class Player:
    username: str
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    rank: str = "Bronze"
    games_played: int = 0
    correct_answers: int = 0
    wrong_answers: int = 0
    wrong_streak: int = 0
    participation_streak: int = 0
    streak_shield: bool = False
    last_seen: float = field(default_factory=time.time)
    weekly_score: int = 0
    week: str = ""
    day_streak: int = 0
    last_day: str = ""
    crew: str = ""
    duel_wins: int = 0
    duel_losses: int = 0

    @property
    def level(self) -> int:
        """Lifetime level from lifetime points (score). Never goes down."""
        return int(math.sqrt(max(0, self.score) / 10)) + 1

    def current_weekly(self, week: str | None = None) -> int:
        return self.weekly_score if self.week == (week or utc_week()) else 0

    def add_points(self, points: int):
        """Lifetime and weekly points (match points are kept by the match)."""
        wk = utc_week()
        if self.week != wk:
            self.week = wk
            self.weekly_score = 0
        self.score += points
        self.weekly_score += points
        self.update_rank()  # bonuses go through here too

    def mark_played(self, now: float | None = None) -> bool:
        """Update the day streak. Returns True on the first play of a new UTC day."""
        today = utc_day(now)
        if self.last_day == today:
            return False
        yesterday = utc_day((now if now is not None else time.time()) - 86400)
        self.day_streak = self.day_streak + 1 if self.last_day == yesterday else 1
        self.last_day = today
        return True

    def record_correct(self, points: int):
        was_wrong_streak = self.wrong_streak
        self.wrong_streak = 0
        old_rank = self.rank
        self.add_points(points)
        self.streak += 1
        self.correct_answers += 1
        self.games_played += 1
        self.last_seen = time.time()
        if self.streak > self.best_streak:
            self.best_streak = self.streak
        self._rank_changed = (self.rank != old_rank)
        self._was_comeback = (was_wrong_streak >= 3)  # for comeback detection

    def record_wrong(self):
        self.wrong_streak += 1
        # Streak shield: halve streak instead of resetting to 0
        if self.streak_shield and self.streak > 0:
            self.streak = self.streak // 2
            self.streak_shield = False
            self._shield_used = True
        else:
            self.streak = 0
            self._shield_used = False
        self.wrong_answers += 1
        self.games_played += 1
        self.last_seen = time.time()

    def update_rank(self):
        new_rank = "Bronze"
        for threshold, rank_name in RANK_THRESHOLDS:
            if self.score >= threshold:
                new_rank = rank_name
        self.rank = new_rank

    def reset(self):
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.rank = "Bronze"
        self.games_played = 0
        self.correct_answers = 0
        self.wrong_answers = 0
        self.wrong_streak = 0
        self.participation_streak = 0
        self.streak_shield = False
        self.weekly_score = 0
        self.day_streak = 0


@dataclass
class Question:
    text: str
    correct_answer: str
    options: list  # list of strings (4 options, shuffled)
    correct_index: int  # 0-based index of correct answer in options
    category: str
    difficulty: str
    fact: str = ""  # one line shown on the reveal


@dataclass
class RoundResult:
    question: Question
    correct_players: list  # list of (username, points_earned, answer_time_seconds)
    wrong_players: list  # list of (username, choice_index)
    total_answers: int
    fastest_player: str = ""
    fastest_time: float = 0.0
    option_counts: list = field(default_factory=lambda: [0, 0, 0, 0])

    @property
    def correct_rate(self) -> float:
        return len(self.correct_players) / self.total_answers if self.total_answers else 0.0


@dataclass
class MatchStanding:
    username: str
    points: int = 0
    correct: int = 0
    best_streak: int = 0
    streak: int = 0
    fastest: float = 0.0  # fastest correct answer time in this match (0 = none)


@dataclass
class ChatMessage:
    username: str
    message: str      # normalized: lowercase, punctuation stripped
    timestamp: float
    raw: str = ""     # original text (crew names, @mentions)


@dataclass
class Duel:
    a: str
    b: str
    match_no: int
    accepted: bool = False
    created: float = field(default_factory=time.time)


@dataclass
class GameEvent:
    """An event to display in the live feed."""
    text: str
    color: tuple  # RGB
    icon: str  # emoji-like label: "STREAK", "ACH", "FIRE", etc.
    timestamp: float = field(default_factory=time.time)


@dataclass
class ThemeVoteState:
    options: dict  # {option_number (1-4): (category_id, category_name)}
    votes: dict = field(default_factory=dict)  # {username: option_number}
    start_time: float = field(default_factory=time.time)

    def vote_counts(self) -> dict:
        """Returns {option_number: vote_count}."""
        counts = {opt: 0 for opt in self.options}
        for vote in self.votes.values():
            if vote in counts:
                counts[vote] += 1
        return counts

    def total_votes(self) -> int:
        return len(self.votes)

    def leading_option(self) -> int:
        """Returns the option number with most votes, or 0 if no votes."""
        counts = self.vote_counts()
        if not counts or all(v == 0 for v in counts.values()):
            return 0
        return max(counts, key=counts.get)
