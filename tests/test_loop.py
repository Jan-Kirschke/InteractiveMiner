"""Game loop 2 (docs/game-modes.md): difficulty that pays, level ups, the ramp fallback,
fresh categories, host-line variety, combo steps, rotating formats, the community goal and
!double. Every rule at its seam, no network."""

import time

import pytest

import quiz.logic as logic_mod
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic, BOT_PREFIX
from quiz.models import GameState, Question

BOT = BOT_PREFIX + "Rookie"


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)  # no OTDB calls
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.state = GameState.ASKING
    g.mini_event = ""
    g.is_double_points = False
    g.special_slots = {}
    g.question_start_time = time.time()
    g.question_duration = 30.0
    yield g
    db.close()


def classic(game, difficulty="easy", correct=1, kind="classic"):
    game.current_question = Question("Q?", "B", ["A", "B", "C", "D"], correct, "Test", difficulty, kind=kind)
    game.current_answers, game.lock_order, game.half_picks = {}, [], {}


def answer_at(game, user, choice, seconds=3):
    game.current_answers[user] = (choice, game.question_start_time + seconds)


def points(res):
    return {u: p for u, p, _ in res.correct_players}


def ask(game, n):
    game.q_index = n - 1
    game._transition_to(GameState.ASKING)
    return game.current_question


def served(difficulties):
    """A _pop_question stand-in: question n gets difficulties[n - 1] (or the ramp's tier)."""
    def pop(game):
        def _pop(want=""):
            d = difficulties[game.q_index - 1] if difficulties else want
            return Question(f"Q{game.q_index}?", "B", ["A", "B", "C", "D"], 1, "Test", d)
        return _pop
    return pop


# ------------------------------------------
# 1. DIFFICULTY PAYS, LEVEL UP, GRACEFUL RAMP
# ------------------------------------------
@pytest.mark.parametrize("difficulty,pts", [("easy", 20), ("medium", 25), ("hard", 30)])
def test_points_scale_with_the_shown_difficulty(game, difficulty, pts):
    classic(game, difficulty)
    answer_at(game, "alice", 1, 3)                  # 10 x 2 speed, then x difficulty
    assert points(game._resolve_question()) == {"alice": pts}


def test_crowd_rounds_ignore_the_difficulty_label(game):
    classic(game, "hard", correct=-1, kind="majority")
    for u in ("alice", "bob", "carol"):
        answer_at(game, u, 0, 3)
    assert set(points(game._resolve_question()).values()) == {20}


def level_ups(game, upto=10):
    fired = []
    for n in range(1, upto + 1):
        game.sound_queue.clear()                    # update() clears it every frame
        ask(game, n)
        if "level_up" in game.sound_queue:
            fired.append(n)
    return fired


def test_level_up_fires_once_per_ramp_step(game):
    game._enter_intro()
    game._pop_question = served(None)(game)
    assert level_ups(game) == [4, 8]
    assert any("LEVEL UP" in e.text and "HARD" in e.text for e in game.event_feed)


def test_level_up_waits_for_a_question_of_the_new_tier(game):
    game._enter_intro()
    game._pop_question = served(["easy"] * 4 + ["medium"] * 4 + ["medium", "hard"])(game)
    assert level_ups(game) == [5, 10]               # Q4 and Q8-9 served below the ramp's tier


def test_a_new_match_levels_up_again(game):
    game._pop_question = served(None)(game)
    game._enter_intro()
    level_ups(game)
    game._enter_intro()
    assert level_ups(game) == [4, 8]


def test_dry_tier_serves_the_nearest_tier(game, monkeypatch):
    # No bank, no cache: the built-in questions have no hard ones, so "hard" must get medium.
    monkeypatch.setattr(game.bank, "pick", lambda *a, **k: None)
    game._question_cache = []
    assert {game._pop_question("hard").difficulty for _ in range(5)} == {"medium"}


def test_dry_tier_in_the_cache_serves_the_nearest_tier(game, monkeypatch):
    monkeypatch.setattr(game.bank, "pick", lambda *a, **k: None)
    game._question_cache = [Question(f"{d}?", "B", ["A", "B"], 1, "T", d) for d in ("easy", "medium", "easy")]
    assert game._pop_question("hard").difficulty == "medium"
