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
