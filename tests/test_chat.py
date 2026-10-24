"""Chat reader recovery: a dropped connection is found again, with one reader thread throughout."""

import queue
import threading
import time

import quiz.chat as chat_mod
from quiz.chat import ChatManager


class _Script:
    """Each LiveChat the manager opens takes the next behaviour: messages to deliver, or 'drop'."""

    def __init__(self, plan):
        self.plan, self.opened = list(plan), 0


def _fake_livechat(script):
    class FakeChat:
        def __init__(self, url, session=None):
            self.video_id = "vid"
            self.mode = script.plan.pop(0) if script.plan else "idle"
            self.alive = True

        def open(self):
            if self.mode == "offline":
                raise ConnectionError("network unreachable")
            script.opened += 1
            return True

        def poll(self):
            if self.mode == "drop":
                raise ConnectionError("connection reset")
            if self.mode == "idle":
                return [], 0.01
            out, self.mode = self.mode, "idle"
            return [(a, t, time.time()) for a, t in out], 0.01
    return FakeChat


def test_dropped_chat_is_reopened_and_messages_flow_again(monkeypatch):
    script = _Script(["drop", "offline", [("ann", "2"), ("ben", "!crew Owls")]])
    monkeypatch.setattr(chat_mod, "LiveChat", _fake_livechat(script))

    class Quick(ChatManager):
        RETRY_SECONDS, POLL_BACKOFF = 0.05, 0.01
    q = queue.Queue()
    cm = Quick(["https://www.youtube.com/watch?v=x"], q)
    threads_before = threading.active_count()
    cm.start()
    got = []
    deadline = time.monotonic() + 5
    while len(got) < 2 and time.monotonic() < deadline:
        try:
            got.append(q.get(timeout=0.05))
        except queue.Empty:
            pass
    assert [(m.username, m.message) for m in got] == [("ann", "2"), ("ben", "crew owls")]
    assert script.opened == 2                       # the dropped chat, then the one that came back
    assert threading.active_count() == threads_before + 1
    cm.stop()
    cm._thread.join(2)
    assert not cm._thread.is_alive()
