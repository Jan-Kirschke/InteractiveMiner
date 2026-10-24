"""
The Lifelong Quiz - question bank
Every question we ever get (Open Trivia DB batches, imported packs) is kept in SQLite with
how often it was asked and answered right. Picking prefers questions nobody has seen for a
long time, and once enough real players answered a question its *measured* difficulty
replaces the label it came with.
"""

import json
import random
import sqlite3
import threading
import time

from quiz.models import Question

# Open Trivia DB's fixed category list, so stored questions can be filtered by the voted id
OTDB_CATEGORY_IDS = {
    "General Knowledge": 9, "Entertainment: Books": 10, "Entertainment: Film": 11,
    "Entertainment: Music": 12, "Entertainment: Musicals & Theatres": 13,
    "Entertainment: Television": 14, "Entertainment: Video Games": 15,
    "Entertainment: Board Games": 16, "Science & Nature": 17, "Science: Computers": 18,
    "Science: Mathematics": 19, "Mythology": 20, "Sports": 21, "Geography": 22, "History": 23,
    "Politics": 24, "Art": 25, "Celebrities": 26, "Animals": 27, "Vehicles": 28,
    "Entertainment: Comics": 29, "Science: Gadgets": 30,
    "Entertainment: Japanese Anime & Manga": 31, "Entertainment: Cartoon & Animations": 32,
}

MEASURE_AFTER = 15                       # real answers before measured difficulty takes over
REPEAT_WINDOWS = (7 * 86400, 86400, 4 * 3600)   # try a week without repeats, then relax


def measured_difficulty(label: str, asked: int, correct: int) -> str:
    if asked < MEASURE_AFTER:
        return label
    rate = correct / asked
    return "easy" if rate >= 0.6 else "medium" if rate >= 0.35 else "hard"


class QuestionBank:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock | None = None):
        self._conn = conn
        self._lock = lock or threading.Lock()
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    text        TEXT PRIMARY KEY,
                    correct     TEXT NOT NULL,
                    wrong       TEXT NOT NULL,          -- JSON list of 1-3 wrong options
                    category    TEXT DEFAULT '',
                    cat_id      INTEGER,
                    difficulty  TEXT DEFAULT 'medium',
                    fact        TEXT DEFAULT '',
                    source      TEXT DEFAULT '',
                    asked       INTEGER DEFAULT 0,      -- real players who answered
                    correct_n   INTEGER DEFAULT 0,
                    last_asked  REAL DEFAULT 0
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_cat ON questions(cat_id, last_asked)")
            self._conn.commit()

    def add(self, items: list[dict], source: str) -> int:
        """items: {text, correct, wrong: [..], category, difficulty, fact?, cat_id?}. Returns rows added."""
        rows = []
        for it in items:
            wrong = [w for w in it["wrong"] if w and w != it["correct"]][:3]
            if not it.get("text") or not it.get("correct") or not wrong:
                continue
            cat = it.get("category", "")
            rows.append((
                it["text"].strip(), it["correct"].strip(), json.dumps(wrong, ensure_ascii=False), cat,
                it.get("cat_id") or OTDB_CATEGORY_IDS.get(cat), (it.get("difficulty") or "medium").lower(),
                it.get("fact", "") or "", source,
            ))
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(
                "INSERT OR IGNORE INTO questions (text, correct, wrong, category, cat_id, difficulty, fact, source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            self._conn.commit()
            return self._conn.total_changes - before

    def count(self, cat_id=None, unseen_for: float = 0) -> int:
        q = "SELECT COUNT(*) FROM questions WHERE last_asked <= ?"
        args = [time.time() - unseen_for]
        if cat_id:
            q += " AND cat_id = ?"
            args.append(cat_id)
        with self._lock:
            return self._conn.execute(q, args).fetchone()[0]

    def pick(self, cat_id=None, difficulty: str = "") -> Question | None:
        """A question for this category (None = any) not asked for as long as possible, shuffled options."""
        for window in REPEAT_WINDOWS:
            q = "SELECT * FROM questions WHERE last_asked <= ?"
            args: list = [time.time() - window]
            if cat_id:
                q += " AND cat_id = ?"
                args.append(cat_id)
            with self._lock:
                rows = self._conn.execute(q + " ORDER BY RANDOM() LIMIT 60", args).fetchall()
            if not rows:
                continue
            want = [r for r in rows if measured_difficulty(r["difficulty"], r["asked"], r["correct_n"]) == difficulty]
            r = (want or rows)[0]
            self.mark_asked(r["text"])
            options = json.loads(r["wrong"]) + [r["correct"]]
            random.shuffle(options)
            return Question(
                text=r["text"], correct_answer=r["correct"], options=options,
                correct_index=options.index(r["correct"]), category=r["category"],
                difficulty=measured_difficulty(r["difficulty"], r["asked"], r["correct_n"]),
                fact=r["fact"] or "",
            )
        return None

    def mark_asked(self, text: str):
        with self._lock:
            self._conn.execute("UPDATE questions SET last_asked = ? WHERE text = ?", (time.time(), text))
            self._conn.commit()

    def record_result(self, text: str, answered: int, correct: int):
        if answered <= 0:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE questions SET asked = asked + ?, correct_n = correct_n + ? WHERE text = ?",
                (answered, correct, text))
            self._conn.commit()

    def stats(self, text: str) -> tuple[int, int]:
        with self._lock:
            r = self._conn.execute("SELECT asked, correct_n FROM questions WHERE text = ?", (text,)).fetchone()
        return (r["asked"], r["correct_n"]) if r else (0, 0)
