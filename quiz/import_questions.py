"""
Import a question pack into the quiz database.

    python -m quiz.import_questions pack.json [more.csv ...] [--db data/quiz_data.db]

JSON: a list of {"question", "correct", "incorrect": [1-3], "category", "difficulty", "fact"}
CSV:  columns question, correct, wrong1, wrong2, wrong3, category, difficulty, fact
Two options (one wrong answer) make a true/false question. Existing texts are skipped.
"""

import argparse
import csv
import json
import sqlite3

from quiz.bank import QuestionBank
from quiz.config import DB_PATH


def load_items(path: str) -> list[dict]:
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return [{
            "text": r.get("question", ""), "correct": r.get("correct", ""),
            "wrong": [r.get(k, "") for k in ("wrong1", "wrong2", "wrong3") if r.get(k)],
            "category": r.get("category", ""), "difficulty": r.get("difficulty", "medium"),
            "fact": r.get("fact", ""),
        } for r in rows]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [{
        "text": d.get("question") or d.get("text", ""),
        "correct": d.get("correct") or d.get("correct_answer", ""),
        "wrong": d.get("incorrect") or d.get("wrong") or d.get("incorrect_answers", []),
        "category": d.get("category", ""), "difficulty": d.get("difficulty", "medium"),
        "fact": d.get("fact", ""),
    } for d in data]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    bank = QuestionBank(conn)
    for path in args.files:
        items = load_items(path)
        added = bank.add(items, source=path.replace("\\", "/").rsplit("/", 1)[-1])
        print(f"{path}: {added} added, {len(items) - added} skipped")
    print(f"Bank now holds {bank.count()} questions")
    conn.close()


if __name__ == "__main__":
    main()
