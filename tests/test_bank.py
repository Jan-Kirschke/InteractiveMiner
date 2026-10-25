"""Question bank: no repeats inside a week, measured difficulty, imports."""

import json
import sqlite3
import time

from quiz.bank import QuestionBank, MEASURE_AFTER, measured_difficulty
from quiz.import_questions import load_items


def make_bank(n=5, cat_id=22):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    bank = QuestionBank(conn)
    bank.add([{"text": f"Q{i}?", "correct": "A", "wrong": ["B", "C", "D"], "category": "Geography",
               "cat_id": cat_id, "difficulty": "easy"} for i in range(n)], "test")
    return bank


def test_no_question_repeats_until_bank_is_exhausted():
    bank = make_bank(5)
    seen = [bank.pick(22, "easy").text for _ in range(5)]
    assert len(set(seen)) == 5
    assert bank.pick(22, "easy") is None          # all asked in the last 4 h: caller falls back


def test_pick_filters_by_category_and_shuffles_correct_index():
    bank = make_bank(3, cat_id=22)
    assert bank.pick(9, "easy") is None
    q = bank.pick(None, "easy")
    assert q.options[q.correct_index] == "A" and sorted(q.options) == ["A", "B", "C", "D"]


def test_measured_difficulty_overrides_label_after_enough_answers():
    assert measured_difficulty("easy", MEASURE_AFTER - 1, 0) == "easy"
    assert measured_difficulty("easy", 20, 3) == "hard"
    assert measured_difficulty("hard", 20, 15) == "easy"
    bank = make_bank(1)
    bank.record_result("Q0?", 20, 2)
    assert bank.pick(22, "hard").difficulty == "hard"


def test_count_is_cached_between_frames_but_follows_every_change():
    # logic.update() asks for the count every frame; the table changes only on add/pick.
    bank = make_bank(5)
    queries = []
    bank._conn.set_trace_callback(lambda sql: queries.append(sql) if "COUNT" in sql else None)
    for _ in range(90):  # three seconds of frames inside one TTL window
        assert bank.count(22, unseen_for=3600) == 5
    assert len(queries) == 1
    assert bank.count(9, unseen_for=3600) == 0                   # another category, same window
    bank.pick(22, "easy")                                        # marks one asked
    assert bank.count(22, unseen_for=3600) == 4
    bank.add([{"text": "Q9?", "correct": "A", "wrong": ["B"], "cat_id": 22}], "test")
    assert bank.count(22, unseen_for=3600) == 5
    assert bank.count(None) == 6


def test_duplicate_text_is_ignored():
    bank = make_bank(2)
    assert bank.add([{"text": "Q0?", "correct": "X", "wrong": ["Y"]}], "test") == 0


def test_import_json_and_csv(tmp_path):
    j = tmp_path / "pack.json"
    j.write_text(json.dumps([{"question": "Capital of Kenya?", "correct": "Nairobi",
                              "incorrect": ["Mombasa", "Kisumu", "Nakuru"], "category": "Geography",
                              "difficulty": "easy", "fact": "Nairobi means 'cool water' in Maasai."}]),
                 encoding="utf-8")
    c = tmp_path / "pack.csv"
    c.write_text("question,correct,wrong1,wrong2,wrong3,category,difficulty,fact\n"
                 "Is the sun a star?,True,False,,,Science,easy,\n", encoding="utf-8")
    items = load_items(str(j)) + load_items(str(c))
    assert items[0]["wrong"] == ["Mombasa", "Kisumu", "Nakuru"] and items[0]["fact"]
    assert items[1]["wrong"] == ["False"]
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    bank = QuestionBank(conn)
    assert bank.add(items, "pack") == 2
    tf = bank.pick(None, "easy")
    assert len(tf.options) in (2, 4)

def test_retired_question_is_never_asked_or_counted_and_stays_retired_on_reimport():
    # 2026-10-25: questions only one country's residents can answer are retired, not deleted
    bank = make_bank(3)
    assert bank.retire(["Q0?", "Q1?", "not in the bank?"]) == 2
    assert bank.count(22) == 1
    assert bank.pick(22, "easy").text == "Q2?"
    assert bank.pick(22, "easy") is None
    bank.add([{"text": "Q0?", "correct": "A", "wrong": ["B"], "category": "Geography", "cat_id": 22}], "pack")
    assert bank.count(22) == 1 and bank.retire(["Q0?"]) == 0   # only Q2 left


def test_bank_made_before_retirement_gains_the_column():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE questions (text TEXT PRIMARY KEY, correct TEXT NOT NULL, wrong TEXT NOT NULL,"
                 " category TEXT DEFAULT '', cat_id INTEGER, difficulty TEXT DEFAULT 'medium', fact TEXT DEFAULT '',"
                 " source TEXT DEFAULT '', asked INTEGER DEFAULT 0, correct_n INTEGER DEFAULT 0, last_asked REAL DEFAULT 0)")
    conn.execute("INSERT INTO questions (text, correct, wrong, cat_id) VALUES ('Old?', 'A', '[\"B\"]', 22)")
    bank = QuestionBank(conn)
    assert bank.pick(22).text == "Old?"

def test_a_fixed_pack_answer_reaches_the_bank_but_not_another_packs_row():
    bank = make_bank(1)                      # "Q0?" from source "test", correct "A"
    bank.add([{"text": "Q0?", "correct": "B", "wrong": ["A", "C", "D"], "category": "Geography"}], "pack", update=True)
    assert bank.pick(22).correct_answer == "A"
    bank = make_bank(0)
    bank.add([{"text": "Feed?", "correct": "A", "wrong": ["B"], "cat_id": 22}], "otdb")
    bank.add([{"text": "Feed?", "correct": "B", "wrong": ["A"], "cat_id": 22}], "reviewed.json", update=True)
    assert bank.pick(22).correct_answer == "B"   # a reviewed pack takes over the unreviewed feed's row
    bank = make_bank(1)
    assert bank.add([{"text": "Q0?", "correct": "B", "wrong": ["A", "C", "D"], "category": "Geography",
                      "cat_id": 22, "difficulty": "hard", "fact": "Fixed."}], "test", update=True) == 0
    q = bank.pick(22)
    assert (q.correct_answer, q.difficulty, q.fact) == ("B", "hard", "Fixed.")
