"""
The Lifelong Quiz - private answer page
Players open the page on their phone, link it to their YouTube name once (the page shows a
code, they type "!link CODE" in chat), then answer by tapping. Nobody else sees the answer,
and it reaches the game without YouTube's chat delay.

Runs in threads inside the game process. HTTP threads never touch the game: answers go into
the same queue as chat messages, and the game publishes a ready-made state snapshot.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from quiz.models import ChatMessage

PAGE = Path(__file__).resolve().parent / "web" / "answer.html"
CODE_TTL = 15 * 60          # an unlinked code expires after 15 minutes
MAX_PENDING = 20_000


class AnswerHub:
    """Shared state between the game (main thread) and the HTTP threads."""

    def __init__(self, conn, lock, message_queue: queue.Queue):
        self._conn, self._lock = conn, lock
        self._queue = message_queue
        self._pending: dict[str, tuple[str, float]] = {}   # code -> (token, created)
        self._names: dict[str, str] = {}                    # token -> YouTube name
        self._snapshot = b"{}"
        self._points: dict[str, dict] = {}                  # name -> {"points", "rank"} this match
        self._guard = threading.Lock()
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS web_links (token TEXT PRIMARY KEY, username TEXT, linked REAL)")
            self._conn.commit()
            for token, name in self._conn.execute("SELECT token, username FROM web_links"):
                self._names[token] = name

    # --- HTTP side -------------------------------------------------------
    def new_session(self) -> dict:
        token = secrets.token_urlsafe(18)
        with self._guard:
            now = time.time()
            if len(self._pending) > MAX_PENDING:
                self._pending = {c: v for c, v in self._pending.items() if now - v[1] < CODE_TTL}
            code = f"{secrets.randbelow(900000) + 100000}"
            while code in self._pending:
                code = f"{secrets.randbelow(900000) + 100000}"
            self._pending[code] = (token, now)
        return {"token": token, "code": code}

    def name_of(self, token: str) -> str | None:
        return self._names.get(token)

    def code_of(self, token: str) -> str | None:
        with self._guard:
            for code, (t, created) in self._pending.items():
                if t == token and time.time() - created < CODE_TTL:
                    return code
        return None

    def answer(self, token: str, choice: int) -> bool:
        name = self._names.get(token)
        if not name or choice not in (1, 2, 3, 4):
            return False
        self._queue.put(ChatMessage(name, str(choice), time.time(), raw=str(choice), source="web"))
        return True

    def me(self, token: str) -> dict:
        name = self._names.get(token)
        return {"name": name, **self._points.get(name, {})} if name else {"name": None, "code": self.code_of(token)}

    @property
    def snapshot(self) -> bytes:
        return self._snapshot

    # --- game side (main thread) -----------------------------------------
    def link(self, code: str, username: str) -> bool:
        """'!link CODE' typed in chat by username."""
        with self._guard:
            entry = self._pending.pop(code.strip(), None)
        if not entry or time.time() - entry[1] > CODE_TTL:
            return False
        token = entry[0]
        self._names[token] = username
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO web_links VALUES (?, ?, ?)", (token, username, time.time()))
            self._conn.commit()
        return True

    def publish(self, state: dict, points: dict[str, dict]):
        self._snapshot = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode()
        self._points = points


class _Handler(BaseHTTPRequestHandler):
    hub: AnswerHub = None  # set by serve()
    protocol_version = "HTTP/1.1"
    timeout = 30   # a phone that went away frees its thread

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype="application/json", cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode())

    def _body(self) -> dict:
        n = min(int(self.headers.get("Content-Length") or 0), 2048)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/play", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8", "no-cache")
        elif path == "/api/state":
            self._send(200, self.hub.snapshot)
        elif path == "/healthz":
            self._send(200, b"ok", "text/plain")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        body = self._body()
        token = str(body.get("token", ""))
        if self.path == "/api/session":
            if token and (self.hub.name_of(token) or self.hub.code_of(token)):
                self._json(200, {"token": token, **self.hub.me(token)})
            else:
                s = self.hub.new_session()
                self._json(200, {"token": s["token"], "name": None, "code": s["code"]})
        elif self.path == "/api/me":
            self._json(200, self.hub.me(token))
        elif self.path == "/api/answer":
            try:
                choice = int(body.get("choice", 0))
            except (TypeError, ValueError):
                choice = 0
            ok = self.hub.answer(token, choice)
            self._json(200 if ok else 403, {"ok": ok})
        else:
            self._json(404, {"error": "not found"})


def serve(hub: AnswerHub, port: int) -> ThreadingHTTPServer | None:
    _Handler.hub = hub
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    except OSError as e:
        print(f"[Answers] Could not open port {port}: {e}")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[Answers] Answer page on port {port}")
    return server
