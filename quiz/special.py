"""
The Lifelong Quiz - special rounds
Decks of special-round questions read from quiz/packs/special_*.json, one deck per "type".
They never go into the question bank: a Crowd Mind item has no right answer, and the bank
keys on text + correct answer.

    majority       Crowd Mind: an opinion question, the most-picked option wins (logic.py)
                   (the same deck plays as Lonely Answer, "minority", where the least-picked wins)
    higher_lower   two options, "answer" is the right index
    odd_one_out    3-4 options, "answer" is the one that does not belong
"""

import dataclasses
import json
import random
from pathlib import Path

from quiz.config import LIGHTNING_TIME, SURVIVOR_POT, SURVIVOR_MIN, TEAM_WIN_BONUS
from quiz.models import Question

PACK_DIR = Path(__file__).resolve().parent / "packs"

# Match formats (config.FORMAT_ROTATION; logic.match_format): format -> (chip label, colour, one-line rule)
FORMATS = {
    "classic": ("CLASSIC MATCH", (240, 235, 220), "Ten questions: the fastest right answers score most"),
    "speed": ("SPEED MATCH", (110, 190, 255), f"Every question is a {LIGHTNING_TIME} s lightning question: 1.5x points"),
    "survivors": ("SURVIVORS", (255, 90, 95),
                  f"Get every answer right and split {SURVIVOR_POT} points (at least {SURVIVOR_MIN} each)"),
    "teams": ("GOLD VS TEAL", (255, 210, 63),
              f"Your name picks your team: the higher average wins +{TEAM_WIN_BONUS} each"),
}
# Teams (logic.team_of): team -> (label, colour)
TEAMS = {"gold": ("TEAM GOLD", (255, 196, 40)), "teal": ("TEAM TEAL", (20, 201, 168))}

OPTION_RANGE = {"majority": (2, 4), "higher_lower": (2, 2), "odd_one_out": (3, 4)}
TITLES = {"majority": "crowd mind", "higher_lower": "higher or lower", "odd_one_out": "odd one out"}
SHUFFLE = {"majority", "odd_one_out"}   # higher/lower keeps its order: "More" before "Less"


def _strip_title(text: str, kind: str) -> str:
    """'Higher or lower: is it tall?' -> 'Is it tall?' (the round chip already names the mode)."""
    text = text.strip()
    head, sep, rest = text.partition(":")
    if sep and head.strip().lower() == TITLES[kind] and rest.strip():
        rest = rest.strip()
        return rest[0].upper() + rest[1:]
    return text


def to_question(item: dict) -> Question | None:
    """One pack item as a Question, or None if its round could not play it."""
    kind = item.get("type")
    if kind not in OPTION_RANGE:
        return None
    options = [str(o).strip() for o in item.get("options") or [] if str(o).strip()]
    lo, hi = OPTION_RANGE[kind]
    if not lo <= len(options) <= hi or len(set(options)) != len(options):
        return None
    text = _strip_title(str(item.get("question", "")), kind)
    if not text:
        return None
    correct = -1  # Crowd Mind: the crowd decides
    if kind != "majority":
        correct = item.get("answer")
        if type(correct) is not int or not 0 <= correct < len(options):
            return None
    return Question(
        text=text, correct_answer=options[correct] if correct >= 0 else "", options=options,
        correct_index=correct, category=str(item.get("category", "")),
        difficulty=str(item.get("difficulty") or "medium").lower(), fact=str(item.get("fact") or ""),
        kind=kind,
    )


class SpecialDecks:
    def __init__(self, paths=None):
        self._items: dict[str, dict[str, Question]] = {}   # kind -> text -> question (texts are unique)
        self._decks: dict[str, list[Question]] = {}
        self._last: dict[str, str] = {}
        for path in sorted(paths if paths is not None else PACK_DIR.glob("special_*.json")):
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"[Special] Could not read {path}: {e}")
                continue
            for item in data if isinstance(data, list) else []:
                q = to_question(item) if isinstance(item, dict) else None
                if q:
                    self._items.setdefault(q.kind, {})[q.text] = q

    def count(self, kind: str) -> int:
        return len(self._items.get(kind, {}))

    def draw(self, kind: str) -> Question | None:
        """The next question of this kind (a copy, options shuffled); every item plays once before any repeats."""
        deck = self._decks.get(kind)
        if not deck:
            deck = list(self._items.get(kind, {}).values())
            if not deck:
                return None
            random.shuffle(deck)
            if len(deck) > 1 and deck[-1].text == self._last.get(kind):
                deck[0], deck[-1] = deck[-1], deck[0]   # pop() takes from the end
            self._decks[kind] = deck
        q = deck.pop()
        self._last[kind] = q.text
        options = list(q.options)
        if kind in SHUFFLE:
            random.shuffle(options)
        return dataclasses.replace(q, options=options,
                                   correct_index=options.index(q.correct_answer) if q.correct_index >= 0 else -1)
