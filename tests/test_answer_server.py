"""Private answer page: link a phone to a YouTube name, answers reach the game queue stamped on arrival."""

import json
import queue
import sqlite3
import threading
import time
import urllib.request

from quiz.answer_server import AnswerHub, serve


def make_hub():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    q = queue.Queue()
    return AnswerHub(conn, threading.Lock(), q), q, conn


def test_link_then_answer_reaches_the_queue():
    hub, q, _ = make_hub()
    s = hub.new_session()
    assert not hub.answer(s["token"], 2)          # not linked yet
    assert hub.link(s["code"], "Deklarator")
    assert not hub.link(s["code"], "Someone")     # a code links once
    before = time.time()
    assert hub.answer(s["token"], 2)
    msg = q.get_nowait()
    assert (msg.username, msg.message, msg.source) == ("Deklarator", "2", "web")
    assert msg.timestamp >= before
    assert not hub.answer(s["token"], 7)


def test_links_survive_a_restart():
    hub, q, conn = make_hub()
    s = hub.new_session()
    hub.link(s["code"], "Deklarator")
    again = AnswerHub(conn, threading.Lock(), q)
    assert again.name_of(s["token"]) == "Deklarator"


def test_http_round_trip():
    hub, q, _ = make_hub()
    server = serve(hub, 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        status, s = post("/api/session", {})
        assert status == 200 and s["code"] and s["name"] is None
        hub.link(s["code"], "LifelongQuiz")
        assert post("/api/session", {"token": s["token"]})[1]["name"] == "LifelongQuiz"
        hub.publish({"phase": "ASKING", "options": ["A", "B"]}, {"LifelongQuiz": {"points": 120, "rank": 1}})
        with urllib.request.urlopen(base + "/api/state", timeout=5) as r:
            assert json.loads(r.read())["phase"] == "ASKING"
        assert post("/api/me", {"token": s["token"]})[1]["points"] == 120
        assert post("/api/answer", {"token": s["token"], "choice": 1}) == (200, {"ok": True})
        assert q.get_nowait().message == "1"
        assert post("/api/answer", {"token": "nope", "choice": 1})[0] == 403
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            assert b"!link" in r.read()
    finally:
        server.shutdown()
