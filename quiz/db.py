"""
The Lifelong Quiz - Database Layer
SQLite persistence with in-memory write-back cache.
"""

import sqlite3
import threading
import time
import os

from quiz.config import DB_PATH
from quiz.models import Player


class QuizDatabase:
    def __init__(self, db_path=DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._dirty = set()  # usernames that need flushing

        # Handle corrupted DB
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
        except sqlite3.DatabaseError:
            backup = db_path + ".bak"
            print(f"[DB] Database corrupted, backing up to {backup}")
            if os.path.exists(db_path):
                os.rename(db_path, backup)
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()

        self._players: dict[str, Player] = {}
        self._load_all()

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                username        TEXT PRIMARY KEY,
                score           INTEGER DEFAULT 0,
                streak          INTEGER DEFAULT 0,
                best_streak     INTEGER DEFAULT 0,
                rank            TEXT DEFAULT 'Bronze',
                games_played    INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0,
                wrong_answers   INTEGER DEFAULT 0,
                last_seen       REAL DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_players_score
            ON players(score DESC)
        """)
        self._conn.commit()

    def _load_all(self):
        cursor = self._conn.execute("SELECT * FROM players")
        for row in cursor:
            p = Player(
                username=row["username"],
                score=row["score"],
                streak=row["streak"],
                best_streak=row["best_streak"],
                rank=row["rank"],
                games_played=row["games_played"],
                correct_answers=row["correct_answers"],
                wrong_answers=row["wrong_answers"],
                last_seen=row["last_seen"],
            )
            self._players[p.username] = p
        print(f"[DB] Loaded {len(self._players)} players from database")

    def get_or_create_player(self, username: str) -> Player:
        if username not in self._players:
            self._players[username] = Player(username=username)
            self._dirty.add(username)
        return self._players[username]

    def mark_dirty(self, username: str):
        self._dirty.add(username)

    def get_top_players(self, n: int = 10) -> list[Player]:
        sorted_players = sorted(
            self._players.values(),
            key=lambda p: p.score,
            reverse=True,
        )
        return sorted_players[:n]

    def get_player_count(self) -> int:
        return len(self._players)

    def remove_players(self, usernames: list[str]):
        """Remove specific players from cache and database (used to clean up bot data)."""
        removed = []
        for name in usernames:
            if name in self._players:
                del self._players[name]
                removed.append(name)
        self._dirty -= set(usernames)
        if removed:
            placeholders = ",".join("?" * len(removed))
            self._conn.execute(
                f"DELETE FROM players WHERE username IN ({placeholders})",
                removed,
            )
            self._conn.commit()
            print(f"[DB] Removed {len(removed)} bot players from database")

    def reset_player(self, username: str):
        if username in self._players:
            self._players[username].reset()
            self._dirty.add(username)

    def save_all(self):
        if not self._dirty:
            return
        with self._lock:
            to_save = list(self._dirty)
            self._dirty.clear()
        try:
            data = []
            for uname in to_save:
                p = self._players.get(uname)
                if p:
                    data.append((
                        p.username, p.score, p.streak, p.best_streak,
                        p.rank, p.games_played, p.correct_answers,
                        p.wrong_answers, p.last_seen,
                    ))
            if data:
                self._conn.executemany("""
                    INSERT OR REPLACE INTO players
                    (username, score, streak, best_streak, rank,
                     games_played, correct_answers, wrong_answers, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, data)
                self._conn.commit()
                print(f"[DB] Saved {len(data)} players")
        except Exception as e:
            print(f"[DB] Save error: {e}")

    def close(self):
        self.save_all()
        self._conn.close()
        print("[DB] Database closed")
