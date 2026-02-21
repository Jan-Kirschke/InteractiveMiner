"""
The Lifelong Quiz - Data Models
Enums, dataclasses, and core data structures.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
import time

from quiz.config import RANK_THRESHOLDS


class GameState(Enum):
    WAITING = auto()
    ASKING = auto()
    REVEALING = auto()
    LEADERBOARD = auto()
    THEME_VOTE = auto()


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
    last_seen: float = field(default_factory=time.time)

    def record_correct(self, points: int):
        was_wrong_streak = getattr(self, "wrong_streak", 0)
        self.wrong_streak = 0
        self.score += points
        self.streak += 1
        self.correct_answers += 1
        self.games_played += 1
        self.last_seen = time.time()
        if self.streak > self.best_streak:
            self.best_streak = self.streak
        old_rank = self.rank
        self.update_rank()
        self._rank_changed = (self.rank != old_rank)
        self._was_comeback = (was_wrong_streak >= 3)  # for comeback detection

    def record_wrong(self):
        self.wrong_streak = getattr(self, "wrong_streak", 0) + 1
        self.streak = 0
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


@dataclass
class Question:
    text: str
    correct_answer: str
    options: list  # list of strings (4 options, shuffled)
    correct_index: int  # 0-based index of correct answer in options
    category: str
    difficulty: str


@dataclass
class RoundResult:
    question: Question
    correct_players: list  # list of (username, points_earned, answer_time_seconds)
    wrong_players: list  # list of (username, choice_index)
    total_answers: int
    fastest_player: str = ""
    fastest_time: float = 0.0


@dataclass
class ChatMessage:
    username: str
    message: str
    timestamp: float


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
