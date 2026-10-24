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


def expire(game):
    game.state_timer = 0
    game.update(0)


def test_full_match_cycle_records_winner_and_ladders(game):
    game.state = GameState.WAITING
    game.update(0)
    assert game.state == GameState.LOBBY
    game.process_message("alice", "2")          # category vote in the lobby
    game.process_message("bob", "ready")
    assert game.ready_players == ["alice", "bob"]
    expire(game)
    assert game.state == GameState.INTRO
    match_no = game.match_no

    for q in range(1, 11):
        expire(game)
        assert game.state == GameState.ASKING and game.q_index == q
        correct = game.current_question.correct_index
        game.process_message("alice", str(correct + 1))
        game.process_message("bob", str((correct + 1) % 4 + 1))   # always wrong
        expire(game)
        assert game.state == GameState.LOCKING
        carol = correct if q not in (1, 10) else (correct + 1) % 4  # wrong twice: jackpots cannot lift her past alice
        game.process_message("carol", str(carol + 1))              # late answer still counts
        expire(game)
        assert game.state == GameState.REVEALING
        assert game.last_result.option_counts[correct] == (2 if q not in (1, 10) else 1)

    expire(game)
    assert game.state == GameState.PODIUM
    assert [s.username for s in game.podium] == ["alice", "carol"]  # bob scored 0: no podium
    assert len(game.pips) == 10
    assert game.db.next_match_number() == match_no + 1
    assert game.leaderboard[0].username == "alice"
    assert game.ladder_changes["alice"] is None                     # new on the ladder
    expire(game)
    assert game.state == GameState.LOBBY and game.match_no == match_no + 1


def test_final_question_pays_double_and_lightning_is_shorter(game):
    game.q_index = 4
    game._transition_to(GameState.ASKING)                            # question 5
    assert game.mini_event == "lightning" and game.question_duration == 12
    game.q_index = 9
    game._transition_to(GameState.ASKING)                            # question 10
    assert game.is_double_points
    game.process_message("alice", str(game.current_question.correct_index + 1))
    game.current_answers["alice"] = (game.current_question.correct_index, game.question_start_time + 1)
    res = game._resolve_question()
    assert res.correct_players[0][1] == 40                          # 10 x 2 speed x 2 final


def test_day_streak_counts_consecutive_utc_days():
    from quiz.models import Player
    p = Player("a")
    day = 86400 * 20000
    assert p.mark_played(day) and p.day_streak == 1
    assert not p.mark_played(day + 60)
    assert p.mark_played(day + 86400) and p.day_streak == 2
    assert p.mark_played(day + 3 * 86400) and p.day_streak == 1


def test_crew_join_is_case_insensitive_and_scores_best_three(game):
    game.process_message("alice", "crew night owls", "!crew night owls")
    game.process_message("bob", "crew night owls", "!crew NIGHT OWLS")
    assert game.db.get_or_create_player("alice").crew == "Night Owls"
    assert game.db.get_or_create_player("bob").crew == "Night Owls"
    for name, pts in (("alice", 50), ("bob", 40), ("carol", 30), ("dave", 5)):
        if name in ("carol", "dave"):
            game.process_message(name, "crew x", "!crew Night Owls")
        game.standings[name] = logic_mod.MatchStanding(name, points=pts)
    assert game.crew_race() == [("Night Owls", 120, 4)]       # dave's 5 does not count
    game.process_message("bob", "crew leave", "!crew leave")
    assert game.db.get_or_create_player("bob").crew == ""


def test_duel_needs_accept_and_records_winner(game):
    game.db.get_or_create_player("bob")
    game.state = GameState.LOBBY
    game.process_message("alice", "duel bob", "!duel @Bob")
    assert game.active_duels() == []                         # not accepted yet
    game.process_message("bob", "accept")
    assert len(game.active_duels()) == 1
    game.standings["alice"] = logic_mod.MatchStanding("alice", points=80)
    game.standings["bob"] = logic_mod.MatchStanding("bob", points=60)
    game._resolve_duels()
    assert game.duel_results == [("alice", "bob", 80, 60)]
    assert game.db.get_or_create_player("alice").duel_wins == 1
    assert game.db.get_or_create_player("bob").duel_losses == 1
    assert game.duels == []


def test_bots_cannot_join_crews_or_duel(game):
    bot = BOT_PREFIX + "Rookie"
    game.process_message(bot, "crew x", "!crew X")
    game.process_message(bot, "duel alice", "!duel alice")
    assert game.db.get_or_create_player(bot).crew == "" and game.duels == []


def test_overtake_is_announced(game):
    a = game.db.get_or_create_player("alice"); a.add_points(10)
    b = game.db.get_or_create_player("bob"); b.add_points(50)
    before = {p.username: i for i, p in enumerate(game.db.get_weekly_top(n=50), 1)}
    a.add_points(100)
    game.current_answers = {"alice": (1, game.question_start_time)}
    game._announce_overtakes(before)
    assert any("alice passed bob" in e.text for e in game.event_feed)


def test_crew_and_duel_record_survive_restart(game, tmp_path):
    game.process_message("alice", "crew owls", "!crew Owls")
    game.db.get_or_create_player("alice").duel_wins = 2
    game.db.mark_dirty("alice")
    game.db.save_all()
    db2 = QuizDatabase(str(tmp_path / "quiz.db"))
    p = db2._players["alice"]
    assert (p.crew, p.duel_wins) == ("Owls", 2)
    db2.close()
