"""Bank tiers: a dry tier serves the nearest one (lower first), and "expert" for the final."""

import sqlite3
import time

import pytest

import quiz.logic as logic_mod
from quiz.bank import QuestionBank, measured_difficulty
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic
from quiz.models import GameState


def bank_with(**tiers):
    """bank_with(easy=3, hard=2): that many questions of each label, all one category."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    bank = QuestionBank(conn)
    bank.add([{"text": f"{tier} {i}?", "correct": "A", "wrong": ["B", "C", "D"], "category": "Geography",
               "cat_id": 22, "difficulty": tier} for tier, n in tiers.items() for i in range(n)], "test")
    return bank


def test_a_dry_tier_serves_the_nearest_tier():
    bank = bank_with(easy=10, medium=10)
    assert {bank.pick(22, "hard").difficulty for _ in range(6)} == {"medium"}


def test_a_tie_between_two_neighbours_serves_the_lower():
    bank = bank_with(easy=10, hard=10)
    assert {bank.pick(22, "medium").difficulty for _ in range(6)} == {"easy"}


def test_a_rare_tier_is_found_in_a_big_bank():
    bank = bank_with(easy=300, expert=1)                 # a 60-row random sample would miss it 4 in 5
    assert bank.pick(22, "expert").difficulty == "expert"


def test_expert_falls_back_to_hard():
    bank = bank_with(easy=5, medium=5, hard=5)
    assert {bank.pick(22, "expert").difficulty for _ in range(5)} == {"hard"}


def test_expert_survives_measurement_only_while_it_measures_hard():
    assert measured_difficulty("expert", 20, 2) == "expert"     # 10% right: as hard as we can measure
    assert measured_difficulty("expert", 20, 15) == "easy"      # chat found it easy: no longer expert
    assert measured_difficulty("hard", 20, 2) == "hard"         # a hard label never becomes expert


# ------------------------------------------
# The final asks for expert
# ------------------------------------------
@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.special_slots = {}
    # start from a bank without expert rows; each test adds what it needs
    g.bank._conn.execute("DELETE FROM questions WHERE difficulty = 'expert'")
    yield g
    db.close()


def final_buildup(game):
    game._enter_intro()
    game.tier_reached = 2                                  # hard already reached at Q8
    game.q_index = 9
    game.sound_queue.clear()
    game._transition_to(GameState.BUILDUP)
    return game.buildup


def test_the_final_serves_expert_when_a_pack_has_it(game):
    game.bank.add([{"text": "Expert one?", "correct": "A", "wrong": ["B", "C", "D"],
                    "category": "Geography", "difficulty": "expert"}], "test")
    b = final_buildup(game)
    assert b["tier"] == "expert" and game.current_question.text == "Expert one?"
    assert b["stakes"] == 80 and "level_up" in game.sound_queue          # 20 x2 expert x2 final


def test_the_final_falls_back_to_hard_without_expert_questions(game):
    b = final_buildup(game)
    assert b["tier"] == "hard" and b["stakes"] == 60 and "level_up" not in game.sound_queue
