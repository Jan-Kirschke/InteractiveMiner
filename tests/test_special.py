"""Special rounds: the pack loader, the slot map and each round's scoring (no network)."""

import json
import time

import pytest

import quiz.logic as logic_mod
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic, BOT_PREFIX
from quiz.models import GameState
from quiz.special import SpecialDecks, PACK_DIR


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)  # no OTDB calls
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.state = GameState.ASKING
    g.mini_event = ""
    g.is_double_points = False
    g.question_start_time = time.time()
    g.question_duration = 30.0
    yield g
    db.close()


def write_pack(tmp_path, items, name="special_test.json"):
    path = tmp_path / name
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


# ------------------------------------------
# LOADER
# ------------------------------------------
def test_bundled_packs_load_into_decks_by_type():
    decks = SpecialDecks()
    for kind in ("majority", "higher_lower", "odd_one_out"):
        assert decks.count(kind) == 15, kind
    assert decks.count("number") == 0          # Closest Call is not built: its pack stays inert


def test_loader_skips_items_a_round_cannot_play(tmp_path):
    path = write_pack(tmp_path, [
        {"type": "higher_lower", "question": "Higher or lower: x?", "options": ["More", "Less"], "answer": 0},
        {"type": "higher_lower", "question": "No answer?", "options": ["More", "Less"]},
        {"type": "higher_lower", "question": "Answer out of range?", "options": ["More", "Less"], "answer": 2},
        {"type": "odd_one_out", "question": "Two options?", "options": ["A", "B"], "answer": 0},
        {"type": "majority", "question": "Duplicate options?", "options": ["A", "A", "B"]},
        {"type": "number", "question": "Year?", "answer": 1889},
        "not an item",
    ])
    decks = SpecialDecks([path])
    assert decks.count("higher_lower") == 1
    assert decks.count("odd_one_out") == decks.count("majority") == 0


def test_mode_name_prefix_is_dropped_from_the_text(tmp_path):
    # The round chip already says "HIGHER OR LOWER": the text should not say it again.
    path = write_pack(tmp_path, [{"type": "higher_lower", "question": "Higher or lower: is it tall?",
                                  "options": ["Taller", "Shorter"], "answer": 1}])
    q = SpecialDecks([path]).draw("higher_lower")
    assert q.text == "Is it tall?"
    assert (q.kind, q.correct_index, q.correct_answer) == ("higher_lower", 1, "Shorter")


def test_deck_serves_every_item_before_repeating(tmp_path):
    items = [{"type": "odd_one_out", "question": f"Odd one out: set {i}. Which?", "options": ["A", "B", "C", "D"],
              "answer": 2} for i in range(5)]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    first = [decks.draw("odd_one_out").text for _ in range(5)]
    assert len(set(first)) == 5


def test_deck_refill_never_repeats_the_last_question(tmp_path):
    items = [{"type": "odd_one_out", "question": f"Odd one out: set {i}. Which?", "options": ["A", "B", "C", "D"],
              "answer": 2} for i in range(2)]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    drawn = [decks.draw("odd_one_out").text for _ in range(60)]   # 30 refills
    assert all(a != b for a, b in zip(drawn, drawn[1:]))


def test_shuffled_options_keep_the_right_answer(tmp_path):
    items = [{"type": "odd_one_out", "question": "Odd one out: gases. Which?",
              "options": ["Neon", "Argon", "Helium", "Nitrogen"], "answer": 3}]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    for _ in range(20):
        q = decks.draw("odd_one_out")
        assert q.options[q.correct_index] == "Nitrogen" == q.correct_answer


def test_drawn_question_is_a_copy(tmp_path):
    items = [{"type": "majority", "question": "Crowd Mind: pet?", "options": ["Dog", "Cat"]}]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    q = decks.draw("majority")
    q.kind = "minority"
    assert decks.draw("majority").kind == "majority"


def test_special_packs_stay_out_of_the_bank(game):
    texts = {json.loads(p.read_text(encoding="utf-8"))[0]["question"] for p in PACK_DIR.glob("special_*.json")}
    rows = game.bank._conn.execute("SELECT text FROM questions").fetchall()
    assert not texts & {r["text"] for r in rows}


# ------------------------------------------
# SLOT MAP
# ------------------------------------------
def ask(game, n):
    game.q_index = n - 1
    game._transition_to(GameState.ASKING)
    return game.current_question


def test_slot_map_puts_a_special_round_on_its_question(game):
    game.special_slots = {2: "odd_one_out"}
    assert ask(game, 1).kind == "classic"
    assert ask(game, 2).kind == "odd_one_out"
    assert ask(game, 3).kind == "classic"


def test_default_slots_give_every_match_its_special_rounds(game):
    kinds = {n: ask(game, n).kind for n in range(1, 11)}
    assert kinds[4] in ("majority", "minority")
    assert [n for n, k in kinds.items() if k != "classic"] == sorted(game.special_slots)


# ------------------------------------------
# CROWD MIND (majority)
# ------------------------------------------
def crowd(game, kind="majority"):
    from quiz.models import Question
    game.current_question = Question("Which pet?", "", ["Dog", "Cat", "Fish", "Parrot"], -1, "Animals", "easy",
                                     kind=kind)
    game.current_answers = {}


def answer_at(game, user, choice, seconds):
    game.current_answers[user] = (choice, game.question_start_time + seconds)


def test_crowd_mind_most_picked_option_scores_like_a_right_answer(game):
    crowd(game)
    answer_at(game, "alice", 1, 3)     # Cat, fast: 10 x 2 speed
    answer_at(game, "bob", 1, 20)      # Cat, slow: 10
    answer_at(game, "carol", 0, 3)     # Dog: the crowd did not pick it
    res = game._resolve_question()
    assert res.winners == [1] and not res.void
    assert {u: p for u, p, _ in res.correct_players} == {"alice": 20, "bob": 10}
    assert [u for u, _ in res.wrong_players] == ["carol"]
    assert game.standings["alice"].points == 20


def test_crowd_mind_losers_keep_their_streak(game):
    crowd(game)
    carol = game.db.get_or_create_player("carol")
    carol.streak = 4
    game._standing("carol").streak = 4
    for u, c in (("alice", 1), ("bob", 1), ("carol", 0)):
        answer_at(game, u, c, 5)
    game._resolve_question()
    assert carol.streak == 4 and carol.wrong_answers == 0
    assert game.standings["carol"].streak == 4


def test_crowd_mind_tie_lets_every_tied_option_win(game):
    crowd(game)
    for u, c in (("a", 0), ("b", 0), ("c", 2), ("d", 2), ("e", 3)):
        answer_at(game, u, c, 5)
    res = game._resolve_question()
    assert res.winners == [0, 2]
    assert {u for u, _, _ in res.correct_players} == {"a", "b", "c", "d"}


def test_bots_never_decide_or_score_a_crowd_round(game):
    crowd(game)
    for u, c in (("alice", 0), ("bob", 1), ("carol", 1)):
        answer_at(game, u, c, 5)
    for i in range(4):
        answer_at(game, f"{BOT_PREFIX}{i}", 0, 1)   # four bots on Dog would outvote the humans
    res = game._resolve_question()
    assert res.winners == [1]
    assert res.option_counts == [1, 2, 0, 0] and res.total_answers == 3
    assert all(not u.startswith(BOT_PREFIX) for u, _, _ in res.correct_players)
    assert not any(u.startswith(BOT_PREFIX) for u in game.standings)


def test_crowd_round_with_under_three_real_players_is_void(game):
    crowd(game)
    alice = game.db.get_or_create_player("alice")
    alice.streak = 2
    answer_at(game, "alice", 0, 2)
    answer_at(game, "bob", 0, 2)
    answer_at(game, BOT_PREFIX + "Rookie", 0, 2)     # a bot does not make it three
    res = game._resolve_question()
    assert res.void and res.winners == [] and res.correct_players == []
    assert alice.score == 0 and alice.streak == 2


def test_bots_answer_crowd_rounds_inside_the_options(game, monkeypatch):
    monkeypatch.setattr(logic_mod, "MIN_PLAYERS", 4)
    crowd(game)
    game._last_round_real_players = set()
    picks = []
    for _ in range(25):    # 100 bot picks: a 25% "right answer" roll would hit index -1 often
        game._schedule_bots()
        picks += [c for _, c, _ in game._scheduled_bots]
    assert len(picks) == 100 and all(0 <= c < 4 for c in picks)


def test_crowd_reveal_says_what_the_crowd_picked(game):
    crowd(game)
    game.special_slots = {}
    for u, c in (("alice", 1), ("bob", 1), ("carol", 0)):
        game.current_answers[u] = (c, time.time())
    game._enter_revealing()
    assert "Cat" in game.host_line


def test_empty_deck_falls_back_to_a_classic_question(game, tmp_path):
    game.special = SpecialDecks([write_pack(tmp_path, [])])
    game.special_slots = {2: "odd_one_out"}
    q = ask(game, 2)
    assert q.kind == "classic" and q.options
