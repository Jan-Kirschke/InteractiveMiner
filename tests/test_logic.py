"""Scoring, chat parsing and bot isolation for the quiz logic (no network)."""

import time

import pytest

import quiz.logic as logic_mod
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic, BOT_PREFIX
from quiz.models import GameState, Question


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)  # no OTDB calls
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.mini_event = ""
    g.is_double_points = False
    g.state = GameState.ASKING
    g.current_question = Question("Q?", "B", ["A", "B", "C", "D"], 1, "Test", "easy")
    g.current_answers = {}
    g.question_start_time = time.time()
    g.question_duration = 30.0
    yield g
    db.close()


def answer_at(game, user, choice, seconds):
    game.current_answers[user] = (choice, game.question_start_time + seconds)


def test_bare_digit_counts_as_answer(game):
    game.process_message("alice", "2")
    assert game.current_answers["alice"][0] == 1


@pytest.mark.parametrize("msg", ["2nd place", "1000", "3am", "answer 2"])
def test_chatter_starting_with_digit_is_not_an_answer(game, msg):
    game.process_message("alice", msg)
    assert "alice" not in game.current_answers


def test_speed_bonus_uses_round_duration(game):
    # 5 s into a 15 s lightning round is 33% of the time: 1.5x, not the 2x a 30 s round would give.
    game.question_duration = 15.0
    pts = game._calculate_points(game.question_start_time + 5, current_streak=0)
    assert pts == 15


def test_fast_answer_in_normal_round_gets_double(game):
    pts = game._calculate_points(game.question_start_time + 3, current_streak=0)
    assert pts == 20


def test_correct_answer_scores_and_wrong_does_not(game):
    answer_at(game, "alice", 1, 3)
    answer_at(game, "bob", 0, 3)
    result = game._resolve_question()
    assert [p[0] for p in result.correct_players] == ["alice"]
    assert game.db.get_or_create_player("alice").score == 20
    assert game.db.get_or_create_player("bob").score == 0


def test_bots_score_but_are_never_ranked_or_saved(game, tmp_path):
    bot = BOT_PREFIX + "Professor"
    answer_at(game, bot, 1, 1)
    answer_at(game, "alice", 1, 20)
    game._resolve_question()
    assert game.db.get_or_create_player(bot).score > 0
    assert [p.username for p in game.db.get_top_players()] == ["alice"]

    game.db.save_all()
    reloaded = QuizDatabase(str(tmp_path / "quiz.db"))
    assert bot not in reloaded._players
    assert "alice" in reloaded._players
    reloaded.close()


def test_stored_bot_rows_are_purged_on_load(tmp_path):
    path = str(tmp_path / "quiz.db")
    db = QuizDatabase(path)
    db._conn.execute("INSERT INTO players (username, score) VALUES (?, ?)", (BOT_PREFIX + "Rookie", 141))
    db._conn.execute("INSERT INTO players (username, score) VALUES (?, ?)", ("human", 20))
    db._conn.commit()
    db.close()

    db = QuizDatabase(path)
    assert set(db._players) == {"human"}
    db.close()
