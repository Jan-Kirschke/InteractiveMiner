"""Friends: a mutual !friend handshake that survives restarts, !unfriend, caps, and the compact
!friends line the show posts in chat (in-match places, else all-time)."""

import sqlite3
import time

import pytest

import quiz.logic as logic_mod
from quiz import db as db_mod
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic, BOT_PREFIX
from quiz.models import GameState, MatchStanding


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)  # no OTDB calls
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.state = GameState.LOBBY
    for name in ("alice", "Bob_K", "carol"):
        db.get_or_create_player(name)
    yield g
    db.close()


def _say(game, user, raw):
    """What chat.py hands the logic: punctuation stripped, lower case, plus the raw text."""
    from quiz.chat import _PUNCTUATION_RE
    game.process_message(user, _PUNCTUATION_RE.sub("", raw).strip().lower(), raw)


def _events(game):
    return [e.text for e in game.event_feed]


def test_friendship_is_mutual_and_survives_a_restart(game, tmp_path):
    _say(game, "alice", "!friend @Bob_K")
    assert game.db.friends_of("alice") == []                       # a request, not a friendship
    assert "Bob_K: type !friend alice to accept" in _events(game)[-1]
    _say(game, "Bob_K", "!friend alice")                            # without the @ works too
    assert game.db.friends_of("alice") == ["Bob_K"] and game.db.friends_of("Bob_K") == ["alice"]
    assert "alice and Bob_K are now friends!" in _events(game)[-1]
    _say(game, "carol", "!friend @alice")                           # still pending at the restart
    game.db.save_all()

    db2 = QuizDatabase(str(tmp_path / "quiz.db"))
    try:
        assert db2.friends_of("alice") == ["Bob_K"]
        assert db2.request_friend("alice", "carol") == "friends"   # the stored request is accepted
        assert db2.friends_of("carol") == ["alice"]
    finally:
        db2.close()


def test_unfriend_removes_both_sides_and_the_removal_is_saved(game, tmp_path):
    _say(game, "alice", "!friend Bob_K")
    _say(game, "Bob_K", "!friend alice")
    _say(game, "Bob_K", "!unfriend @alice")
    assert game.db.friends_of("alice") == [] and game.db.friends_of("Bob_K") == []
    _say(game, "carol", "!friend alice")
    _say(game, "carol", "!unfriend alice")                          # also withdraws a pending request
    game.db.save_all()
    db2 = QuizDatabase(str(tmp_path / "quiz.db"))
    try:
        assert db2.friends_of("alice") == []
        assert db2.request_friend("alice", "carol") == "requested"   # carol's request is gone
    finally:
        db2.close()


def test_unknown_names_self_and_bots_are_ignored_quietly(game):
    bot = BOT_PREFIX + "Rookie"
    game.db.get_or_create_player(bot)
    before = len(game.event_feed)
    _say(game, "alice", "!friend @nobody_here")
    _say(game, "alice", "!friend alice")
    _say(game, "alice", "!friend " + bot)
    _say(game, bot, "!friend alice")
    _say(game, "alice", "!friend")
    assert len(game.event_feed) == before
    assert game.db.friends_of("alice") == [] and game.db.friends_of(bot) == []


def test_friend_and_request_caps(game):
    for i in range(db_mod.FRIENDS_MAX):
        game.db.get_or_create_player(f"f{i}")
        assert game.db.request_friend("alice", f"f{i}") == "requested"
        assert game.db.request_friend(f"f{i}", "alice") == "friends"
    assert game.db.request_friend("alice", "carol") == "full"
    assert game.db.request_friend("carol", "alice") == "requested"
    assert game.db.request_friend("alice", "carol") == "full"         # accepting would pass the cap
    assert len(game.db.friends_of("alice")) == db_mod.FRIENDS_MAX
    # one player cannot pile up requests: the oldest outgoing ones are dropped
    for i in range(db_mod.REQUESTS_OUT_MAX + 5):
        game.db.get_or_create_player(f"t{i}")
        game.db.request_friend("carol", f"t{i}")
    assert game.db.request_friend("t0", "carol") == "requested"       # t0's old request expired
    assert game.db.request_friend(f"t{db_mod.REQUESTS_OUT_MAX + 4}", "carol") == "friends"


def test_an_existing_database_opens_unchanged(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)   # the players table of an older version, no friends tables
    con.execute("CREATE TABLE players (username TEXT PRIMARY KEY, score INTEGER DEFAULT 0, streak INTEGER DEFAULT 0,"
                " best_streak INTEGER DEFAULT 0, rank TEXT DEFAULT 'Bronze', games_played INTEGER DEFAULT 0,"
                " correct_answers INTEGER DEFAULT 0, wrong_answers INTEGER DEFAULT 0, last_seen REAL DEFAULT 0)")
    con.execute("INSERT INTO players (username, score) VALUES ('old_timer', 4321)")
    con.commit()
    con.close()
    db = QuizDatabase(path)
    try:
        assert db._players["old_timer"].score == 4321
        assert db.friends_of("old_timer") == []
    finally:
        db.close()


def test_friends_line_shows_match_places_while_a_match_runs(game):
    for a, b in (("alice", "Bob_K"), ("alice", "carol")):
        game.db.request_friend(a, b)
        game.db.request_friend(b, a)
    game.state = GameState.REVEALING
    game.standings = {u: MatchStanding(u, points=p) for u, p in
                      (("zed", 300), ("carol", 200), ("alice", 150), (BOT_PREFIX + "Pro", 999))}
    line = game.friends_line("alice")
    assert line == "@alice friends this match: carol 200 pts #2 (+1 not playing)"
    game.state = GameState.LOBBY                                       # between matches: all-time
    game.db.get_or_create_player("Bob_K").add_points(5000)
    game.db.get_or_create_player("carol").add_points(70)
    assert game.friends_line("alice") == "@alice friends all-time: Bob_K 5,000 pts #1, carol 70 pts #2"
    assert game.friends_line("zed").startswith("@zed no friends yet")


def test_friends_line_never_passes_200_characters(game):
    for i in range(db_mod.FRIENDS_MAX):
        name = f"a_rather_long_handle_{i:02d}"
        game.db.get_or_create_player(name).add_points(1000 + i)
        game.db.request_friend("alice", name)
        game.db.request_friend(name, "alice")
    line = game.friends_line("alice")
    assert len(line) <= 200 and line.endswith("more")
    assert "a_rather_long_handle_19 1,019 pts" in line                 # the best come first


def test_friends_without_chat_posting_show_on_screen(game):
    game.db.request_friend("alice", "carol")
    game.db.request_friend("carol", "alice")
    _say(game, "alice", "!friends")
    assert _events(game)[-1].startswith("@alice friends all-time: carol")
    asked = []
    game.chat_reply = asked.append                                     # the poster is on: reply in chat
    game._command_cooldowns.clear()
    shown = len(game.event_feed)
    _say(game, "alice", "!friends")
    assert asked == ["alice"] and len(game.event_feed) == shown


def test_two_friends_in_the_top_five_get_a_line_at_the_podium(game):
    game.db.request_friend("alice", "carol")
    game.db.request_friend("carol", "alice")
    game.standings = {u: MatchStanding(u, points=p) for u, p in
                      (("alice", 300), ("x1", 250), ("carol", 200), ("x2", 100))}
    game.match_started_at = time.time()
    game._enter_podium()
    assert any("Friends alice and carol both finished in the top 5" in t for t in _events(game))
