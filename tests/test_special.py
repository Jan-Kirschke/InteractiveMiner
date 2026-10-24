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


def test_empty_deck_falls_back_to_a_classic_question(game, tmp_path):
    game.special = SpecialDecks([write_pack(tmp_path, [])])
    game.special_slots = {2: "odd_one_out"}
    q = ask(game, 2)
    assert q.kind == "classic" and q.options
