"""Ladders and saving at scale: the cached ladders equal a full sort, saves never lose a change."""

import random
import sqlite3
import threading
import time

import pytest

import quiz.models as models
from quiz.db import QuizDatabase, is_bot, BOT_PREFIX


# The ladders exactly as they were computed before caching (full scan + stable sort each call)
def ref_weekly_top(db, n=10):
    wk = models.utc_week()
    players = [p for p in db._players.values() if not is_bot(p.username) and p.current_weekly(wk) > 0]
    players.sort(key=lambda p: p.weekly_score, reverse=True)
    return players[:n]


def ref_weekly_rank(db, username):
    for i, p in enumerate(ref_weekly_top(db, n=1_000_000), 1):
        if p.username == username:
            return i
    return 0


def ref_lifetime_top(db, n=10):
    return sorted((p for p in db._players.values() if not is_bot(p.username)),
                  key=lambda p: p.score, reverse=True)[:n]


def names(players):
    return [p.username for p in players]


@pytest.fixture
def db(tmp_path):
    d = QuizDatabase(str(tmp_path / "quiz.db"))
    yield d
    d.close()


def test_cached_ladders_equal_a_full_sort_through_random_play(db, monkeypatch):
    rng = random.Random(7)
    clock = [time.time()]
    monkeypatch.setattr(models.time, "time", lambda: clock[0])
    users = [f"u{i}" for i in range(60)] + [BOT_PREFIX + "Rookie", BOT_PREFIX + "Scholar"]
    for step in range(1500):
        op = rng.random()
        u = rng.choice(users)
        if op < 0.55:
            p = db.get_or_create_player(u)
            p.add_points(rng.choice([1, 5, 10, 10, 20]))      # small values: many ties
            if rng.random() < 0.7:
                db.mark_dirty(u)                              # tests and callers do not always mark
        elif op < 0.65:
            db.get_or_create_player(u).record_correct(rng.randint(1, 30))
        elif op < 0.70:
            db.get_or_create_player(u).record_wrong()
        elif op < 0.74:
            db.reset_player(u)
        elif op < 0.75:
            db.reset_all_players()
        elif op < 0.78:
            db.remove_players([users[-1]])                     # bot cleanup
        elif op < 0.80:
            clock[0] += 3.5 * 86400                            # crosses into a new ISO week sometimes
        elif op < 0.83:
            db.get_or_create_player(f"new{step}")              # newcomer, 0 points
        if step % 3 == 0:
            for n in (1, 3, 10, 50, 1_000_000):
                assert names(db.get_weekly_top(n)) == names(ref_weekly_top(db, n)), step
            assert names(db.get_top_players(10)) == names(ref_lifetime_top(db, 10)), step
            for who in rng.sample(users, 5):
                assert db.weekly_rank(who) == ref_weekly_rank(db, who), (step, who)


def test_ladders_follow_the_week_and_the_roster_without_points_changing(db, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(models.time, "time", lambda: clock[0])
    db.get_or_create_player("ann").add_points(30)
    db.get_or_create_player("ben").add_points(20)
    assert names(db.get_weekly_top()) == ["ann", "ben"]
    db.get_or_create_player("cat")                     # newcomer: on the lifetime ladder at 0
    assert names(db.get_top_players()) == names(ref_lifetime_top(db)) == ["ann", "ben", "cat"]
    db.remove_players(["ben"])
    assert names(db.get_weekly_top()) == ["ann"] and db.weekly_rank("ben") == 0
    clock[0] += 7 * 86400                              # Monday came: the weekly ladder is empty
    assert db.get_weekly_top() == [] and db.weekly_rank("ann") == 0
    assert names(db.get_top_players()) == ["ann", "cat"]


def ref_find_player(db, name):
    want = name.strip().lstrip("@").lower()
    for u in db._players:
        if u.lstrip("@").lower() == want and not is_bot(u):
            return u
    return None


def test_find_player_matches_the_scan(db):
    # Mentions resolve like the old full scan: case-insensitive, "@" ignored, first player wins
    # when two names differ only in case, bots never.
    for u in ["Lena_K", "@owlbert", "lena_k", "Ünal", BOT_PREFIX + "Rookie", "Max"]:
        db.get_or_create_player(u)
    probes = ["lena_k", "@LENA_K", " owlbert ", "@@owlbert", "ünal", "ÜNAL", "[bot] rookie",
              BOT_PREFIX + "Rookie", "max", "nobody", "", "@"]
    for p in probes:
        assert db.find_player(p) == ref_find_player(db, p), p
    db.remove_players(["Lena_K"])
    db.get_or_create_player("Newbie")
    for p in probes + ["newbie"]:
        assert db.find_player(p) == ref_find_player(db, p), p


def test_find_player_does_not_scan_every_player_per_mention(db):
    class Counting(dict):
        scans = 0

        def __iter__(self):
            Counting.scans += 1
            return super().__iter__()
    for i in range(1000):
        db.get_or_create_player(f"u{i}")
    db._players = Counting(db._players)
    for i in range(50):                  # 50 "!duel @u.." in a row
        db.find_player(f"@u{i * 7}")
    assert Counting.scans <= 1


FIELDS = ("score", "streak", "best_streak", "rank", "games_played", "correct_answers", "wrong_answers",
          "wrong_streak", "participation_streak", "streak_shield", "weekly_score", "week", "day_streak",
          "last_day", "crew", "duel_wins", "duel_losses")


def snapshot(players):
    return {u: tuple(getattr(p, f) for f in FIELDS) for u, p in players.items() if not is_bot(u)}


class SlowWrites(QuizDatabase):
    """The writer's SQL takes 50 ms per batch, like a busy disk at a WAL checkpoint."""

    def _write_rows(self, conn, rows):
        time.sleep(0.05)
        super()._write_rows(conn, rows)


def test_background_saves_keep_every_change_while_the_game_plays(tmp_path):
    # The game keeps scoring while saves run on the writer thread; after close() the file holds
    # exactly what memory held, field for field.
    path = str(tmp_path / "quiz.db")
    db = SlowWrites(path)
    rng = random.Random(3)
    users = [f"u{i}" for i in range(300)] + [BOT_PREFIX + "Rookie"]
    t_end = time.monotonic() + 1.5
    while time.monotonic() < t_end:
        for _ in range(50):
            u = rng.choice(users)
            p = db.get_or_create_player(u)
            if rng.random() < 0.8:
                p.record_correct(rng.randint(1, 40))
            else:
                p.record_wrong()
            p.crew = rng.choice(["", "Owls", "Larks"])
            db.mark_dirty(u)
        db.save_in_background()
        time.sleep(0.005)
    want = snapshot(db._players)
    db.close()
    assert not any(t.name == "db-writer" and t.is_alive() for t in threading.enumerate())
    again = QuizDatabase(path)
    assert snapshot(again._players) == want
    again.close()


def test_background_save_returns_at_once(tmp_path):
    db = SlowWrites(str(tmp_path / "quiz.db"))
    for i in range(2000):
        db.get_or_create_player(f"u{i}").add_points(i)
    t0 = time.perf_counter()
    db.save_in_background()
    db.save_in_background()           # the first is still writing: nothing waits
    assert time.perf_counter() - t0 < 0.03
    db.close()


def test_failed_background_save_is_retried(tmp_path, monkeypatch):
    path = str(tmp_path / "quiz.db")
    db = QuizDatabase(path)
    real = QuizDatabase._write_rows
    fails = [1]

    def flaky(self, conn, rows):
        if fails[0]:
            fails[0] -= 1
            raise sqlite3.OperationalError("database is locked")
        real(self, conn, rows)
    monkeypatch.setattr(QuizDatabase, "_write_rows", flaky)
    db.get_or_create_player("ann").add_points(70)
    db.save_in_background()
    db.wait_saved()
    db.save_in_background()
    db.wait_saved()
    db.close()
    again = QuizDatabase(path)
    assert again._players["ann"].score == 70
    again.close()


def test_ladder_is_not_rebuilt_while_points_do_not_change(db):
    for i in range(200):
        db.get_or_create_player(f"u{i}").add_points(i + 1)
    db.get_weekly_top()
    first = db._ladder_key
    for i in range(200):
        db.mark_dirty(f"u{i}")       # answers mark players dirty all question long
        db.get_weekly_top()
        db.weekly_rank(f"u{i}")
    assert db._ladder_key == first
