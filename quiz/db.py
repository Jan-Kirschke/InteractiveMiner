"""
The Lifelong Quiz - Database Layer
SQLite persistence with in-memory write-back cache.
"""

import queue
import sqlite3
import threading
import time
import os

from quiz.config import DB_PATH
from quiz.models import Player, utc_week

BOT_PREFIX = "[Bot] "
FRIENDS_MAX = 20          # friends per player
REQUESTS_OUT_MAX = 10     # pending !friend requests one player may have sent (the oldest go)
REQUESTS_IN_MAX = 20      # pending requests waiting for one player (the oldest go)


def is_bot(username: str) -> bool:
    return username.startswith(BOT_PREFIX)


class QuizDatabase:
    def __init__(self, db_path=DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._dirty = set()  # usernames that need flushing
        self._save_idle = threading.Event()
        self._save_idle.set()
        self._save_queue: queue.Queue = queue.Queue()
        self._writer = None

        # Ensure data directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

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

        self._conn.execute("PRAGMA journal_mode=WAL")      # a crash mid-write cannot corrupt the file
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._players: dict[str, Player] = {}
        self._roster = 0          # bumped when players are added or removed (ladder cache key)
        self._ladder_key = None
        self._weekly: list[Player] = []
        self._weekly_pos: dict[str, int] | None = None
        self._lifetime: list[Player] | None = None
        self._lifetime_pos: dict[str, int] | None = None
        self._names: dict[str, str] = {}   # find_player: lower-case name without "@" -> username
        self._names_key = None
        # Friends, in memory; changes reach sqlite through the writer thread (_friend_ops)
        self._friends: dict[str, dict[str, float]] = {}        # username -> {friend: since}
        self._requests_in: dict[str, dict[str, float]] = {}    # target -> {sender: at}
        self._requests_out: dict[str, dict[str, float]] = {}   # sender -> {target: at}
        self._friend_ops: list[tuple[str, tuple]] = []
        self._load_all()
        self._load_friends()

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
                wrong_streak    INTEGER DEFAULT 0,
                last_seen       REAL DEFAULT 0
            )
        """)
        # Migrate: add columns if missing (existing DBs)
        for col, typedef in [
            ("wrong_streak", "INTEGER DEFAULT 0"),
            ("participation_streak", "INTEGER DEFAULT 0"),
            ("streak_shield", "INTEGER DEFAULT 0"),
            ("weekly_score", "INTEGER DEFAULT 0"),
            ("week", "TEXT DEFAULT ''"),
            ("day_streak", "INTEGER DEFAULT 0"),
            ("last_day", "TEXT DEFAULT ''"),
            ("crew", "TEXT DEFAULT ''"),
            ("duel_wins", "INTEGER DEFAULT 0"),
            ("duel_losses", "INTEGER DEFAULT 0"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE players ADD COLUMN {col} {typedef}")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # Column already exists
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_players_score
            ON players(score DESC)
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  REAL,
                ended_at    REAL,
                category    TEXT,
                players     INTEGER,
                winner      TEXT,
                winner_points INTEGER
            )
        """)
        # Friends (additive: older databases just gain the two empty tables). A pair is stored once, a < b.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                a TEXT NOT NULL, b TEXT NOT NULL, since REAL,
                PRIMARY KEY (a, b)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS friend_requests (
                sender TEXT NOT NULL, target TEXT NOT NULL, at REAL,
                PRIMARY KEY (sender, target)
            )
        """)
        self._conn.commit()

    def _load_all(self):
        # Bots are never persisted or ranked; purge rows left by older versions.
        purged = self._conn.execute(
            "DELETE FROM players WHERE username LIKE ?", (BOT_PREFIX + "%",),
        ).rowcount
        self._conn.commit()
        if purged:
            print(f"[DB] Purged {purged} stored bot rows")
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
                wrong_streak=row["wrong_streak"] if "wrong_streak" in row.keys() else 0,
                participation_streak=row["participation_streak"] if "participation_streak" in row.keys() else 0,
                streak_shield=bool(row["streak_shield"]) if "streak_shield" in row.keys() else False,
                last_seen=row["last_seen"],
                weekly_score=row["weekly_score"] or 0,
                week=row["week"] or "",
                day_streak=row["day_streak"] or 0,
                last_day=row["last_day"] or "",
                crew=row["crew"] or "",
                duel_wins=row["duel_wins"] or 0,
                duel_losses=row["duel_losses"] or 0,
            )
            self._players[p.username] = p
        print(f"[DB] Loaded {len(self._players)} players from database")

    def get_or_create_player(self, username: str) -> Player:
        if username not in self._players:
            self._players[username] = Player(username=username)
            self._dirty.add(username)
            self._roster += 1
        return self._players[username]

    def mark_dirty(self, username: str):
        self._dirty.add(username)

    # Ladders: a full sort costs ~25 ms at 50k players, and the show reads them every frame
    # (lobby, podium, player cards, !rank). They are rebuilt only when points, the roster or the
    # ISO week changed. Points change only in Player.add_points/reset, which bump points_epoch.
    def _ladders(self) -> str:
        wk = utc_week()
        key = (wk, Player.points_epoch, self._roster)
        if key != self._ladder_key:
            weekly = [p for p in self._players.values()
                      if not is_bot(p.username) and p.current_weekly(wk) > 0]
            weekly.sort(key=lambda p: p.weekly_score, reverse=True)
            self._weekly, self._weekly_pos, self._lifetime = weekly, None, None
            self._ladder_key = key
        return wk

    def get_top_players(self, n: int = 10) -> list[Player]:
        """Lifetime ladder (lifetime points = level)."""
        self._ladders()
        if self._lifetime is None:
            self._lifetime_pos = None
            self._lifetime = sorted(
                (p for p in self._players.values() if not is_bot(p.username)),
                key=lambda p: p.score,
                reverse=True,
            )
        return self._lifetime[:n]

    def get_weekly_top(self, n: int = 10) -> list[Player]:
        """This week's ladder (resets Monday 00:00 UTC)."""
        self._ladders()
        return self._weekly[:n]

    def weekly_rank(self, username: str) -> int:
        """1-based position on this week's ladder, 0 if not on it."""
        self._ladders()
        if self._weekly_pos is None:
            self._weekly_pos = {p.username: i for i, p in enumerate(self._weekly, 1)}
        return self._weekly_pos.get(username, 0)

    def find_player(self, name: str) -> str | None:
        """Resolve a chat mention ("@Lena_K", "lena_k") to a known username."""
        want = name.strip().lstrip("@").lower()
        if self._names_key != self._roster:  # names only change with the roster
            index = {}
            for u in self._players:
                if not is_bot(u):
                    index.setdefault(u.lstrip("@").lower(), u)  # first in roster order, as the scan was
            self._names, self._names_key = index, self._roster
        return self._names.get(want)

    def crew_members(self, crew: str) -> list[str]:
        return [u for u, p in self._players.items() if p.crew == crew]

    # ------------------------------------------
    # FRIENDS: mutual. "!friend x" from both sides makes a friendship; one side is a pending request.
    def _load_friends(self):
        for row in self._conn.execute("SELECT a, b, since FROM friends ORDER BY since"):
            self._friends.setdefault(row["a"], {})[row["b"]] = row["since"] or 0.0
            self._friends.setdefault(row["b"], {})[row["a"]] = row["since"] or 0.0
        for row in self._conn.execute("SELECT sender, target, at FROM friend_requests ORDER BY at"):
            self._requests_in.setdefault(row["target"], {})[row["sender"]] = row["at"] or 0.0
            self._requests_out.setdefault(row["sender"], {})[row["target"]] = row["at"] or 0.0

    def friends_of(self, username: str) -> list[str]:
        """Friends in the order they became friends."""
        mine = self._friends.get(username, {})
        return sorted(mine, key=mine.get)

    def are_friends(self, a: str, b: str) -> bool:
        return b in self._friends.get(a, {})

    def _drop_request(self, sender: str, target: str) -> bool:
        if target not in self._requests_out.get(sender, {}):
            return False
        del self._requests_out[sender][target]
        del self._requests_in[target][sender]
        self._friend_ops.append(("DELETE FROM friend_requests WHERE sender = ? AND target = ?", (sender, target)))
        return True

    def request_friend(self, sender: str, target: str, now: float | None = None) -> str:
        """sender typed "!friend target". Returns "friends" (target had asked: now friends),
        "requested", "pending" (asked before), "already" or "full" (FRIENDS_MAX reached)."""
        now = time.time() if now is None else now
        if target in self._friends.get(sender, {}):
            return "already"
        if len(self._friends.get(sender, {})) >= FRIENDS_MAX:
            return "full"
        if sender in self._requests_out.get(target, {}):
            if len(self._friends.get(target, {})) >= FRIENDS_MAX:
                return "full"
            self._drop_request(target, sender)
            self._drop_request(sender, target)
            self._friends.setdefault(sender, {})[target] = now
            self._friends.setdefault(target, {})[sender] = now
            a, b = sorted((sender, target))
            self._friend_ops.append(("INSERT OR REPLACE INTO friends (a, b, since) VALUES (?, ?, ?)", (a, b, now)))
            return "friends"
        if target in self._requests_out.get(sender, {}):
            return "pending"
        out = self._requests_out.setdefault(sender, {})
        while len(out) >= REQUESTS_OUT_MAX:
            self._drop_request(sender, min(out, key=out.get))
        waiting = self._requests_in.setdefault(target, {})
        while len(waiting) >= REQUESTS_IN_MAX:
            self._drop_request(min(waiting, key=waiting.get), target)
        out[target] = waiting[sender] = now
        self._friend_ops.append(("INSERT OR REPLACE INTO friend_requests (sender, target, at) VALUES (?, ?, ?)",
                                 (sender, target, now)))
        return "requested"

    def unfriend(self, username: str, other: str) -> bool:
        """End a friendship or withdraw a request, either way round. True if anything changed."""
        changed = self._drop_request(username, other) | self._drop_request(other, username)
        if other in self._friends.get(username, {}):
            del self._friends[username][other]
            del self._friends[other][username]
            a, b = sorted((username, other))
            self._friend_ops.append(("DELETE FROM friends WHERE a = ? AND b = ?", (a, b)))
            changed = True
        return changed

    def lifetime_rank(self, username: str) -> int:
        """1-based place on the lifetime ladder, 0 if not on it."""
        self.get_top_players(0)
        if self._lifetime_pos is None:
            self._lifetime_pos = {p.username: i for i, p in enumerate(self._lifetime, 1)}
        return self._lifetime_pos.get(username, 0)

    def next_match_number(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM matches").fetchone()
        return row[0] + 1

    def record_match(self, started_at: float, category: str, players: int,
                     winner: str, winner_points: int):
        self._conn.execute(
            "INSERT INTO matches (started_at, ended_at, category, players, winner, winner_points) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (started_at, time.time(), category, players, winner, winner_points),
        )
        self._conn.commit()

    def get_player_count(self, exclude_bots: bool = True) -> int:
        if exclude_bots:
            return sum(1 for u in self._players if not u.startswith(BOT_PREFIX))
        return len(self._players)

    def remove_players(self, usernames: list[str]):
        """Remove specific players from cache and database (used to clean up bot data)."""
        removed = []
        for name in usernames:
            if name in self._players:
                del self._players[name]
                removed.append(name)
        self._dirty -= set(usernames)
        self._roster += 1
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

    def reset_all_players(self):
        """Reset scores/stats for all players."""
        count = 0
        for player in self._players.values():
            player.reset()
            self._dirty.add(player.username)
            count += 1
        print(f"[DB] Reset all {count} players")
        return count

    # ------------------------------------------
    # SAVING
    # The game thread only swaps the dirty set (O(1)); a writer thread with its own connection
    # builds the rows and commits, so a slow commit (WAL checkpoint, busy disk) never stalls a
    # frame or the systemd watchdog ping. The swap must stay on the game thread: it is the thread
    # that marks players dirty, so no mark can land in a set the writer has already read.
    # A row read while the game changes that player is re-marked dirty and written again next time.
    def save_in_background(self) -> bool:
        """Start writing the dirty players; returns at once. False if nothing to do or a save is
        still running (the dirty set keeps growing and goes with the next call)."""
        if not (self._dirty or self._friend_ops) or not self._save_idle.is_set():
            return False
        with self._lock:
            to_save, self._dirty = self._dirty, set()
            ops, self._friend_ops = self._friend_ops, []
        self._save_idle.clear()
        if self._writer is None:
            self._writer = threading.Thread(target=self._writer_loop, name="db-writer", daemon=True)
            self._writer.start()
        self._save_queue.put((to_save, ops))
        return True

    def wait_saved(self, timeout: float | None = None) -> bool:
        return self._save_idle.wait(timeout)

    def save_all(self):
        """Write every dirty player and wait until it is committed."""
        self.wait_saved()
        if self.save_in_background():
            self.wait_saved()

    def _writer_loop(self):
        conn = sqlite3.connect(self._db_path, timeout=30)  # its own: the game's queries never wait on it
        conn.execute("PRAGMA synchronous=NORMAL")          # per connection; WAL is a property of the file
        while True:
            item = self._save_queue.get()
            if item is None:
                break
            batch, ops = item
            try:
                rows = self._rows(batch)
                if rows:
                    self._write_rows(conn, rows)
                    print(f"[DB] Saved {len(rows)} players")
                if ops:
                    for sql, params in ops:   # in order: a request, then its acceptance
                        conn.execute(sql, params)
                    conn.commit()
                    ops = []
            except Exception as e:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                with self._lock:
                    self._dirty.update(batch)  # keep them for the next save instead of losing them
                    self._friend_ops[:0] = ops  # idempotent statements: replaying them is safe
                print(f"[DB] Save error: {e}")
            finally:
                self._save_idle.set()
        conn.close()

    def _rows(self, usernames) -> list[tuple]:
        data = []
        for uname in usernames:
            p = self._players.get(uname)
            if p and not is_bot(uname):
                data.append((
                    p.username, p.score, p.streak, p.best_streak,
                    p.rank, p.games_played, p.correct_answers,
                    p.wrong_answers, p.wrong_streak,
                    p.participation_streak, int(p.streak_shield),
                    p.last_seen, p.weekly_score, p.week,
                    p.day_streak, p.last_day,
                    p.crew, p.duel_wins, p.duel_losses,
                ))
        return data

    def _write_rows(self, conn, rows: list[tuple]):
        conn.executemany("""
            INSERT OR REPLACE INTO players
            (username, score, streak, best_streak, rank,
             games_played, correct_answers, wrong_answers,
             wrong_streak, participation_streak, streak_shield,
             last_seen, weekly_score, week, day_streak, last_day,
             crew, duel_wins, duel_losses)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()

    def close(self):
        self.save_all()
        if self._writer is not None:
            self._save_queue.put(None)
            self._writer.join(timeout=30)
            self._writer = None
        self._conn.close()
        print("[DB] Database closed")
