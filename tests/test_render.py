"""Every state of both layouts draws through a whole match without raising (headless).

Runs in a subprocess: the layout (and the screen size the UI modules read at import) is fixed
by QUIZ_LAYOUT when quiz.config is first imported, and the other tests have imported it already.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = r'''
import os, sys, tempfile, time
import pygame
import quiz.logic as L
from quiz.config import SCREEN_WIDTH, SCREEN_HEIGHT, VERTICAL
from quiz.db import QuizDatabase
from quiz.models import GameState as S

L.requests = None
pygame.init()
pygame.joystick.quit()   # the dummy driver's joystick subsystem leaks Windows USER objects
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
from quiz.ui import UIManager
from quiz.ui_vertical import VerticalUI

clock = [1_800_000_000.0]
time.time = lambda: clock[0]
g = L.QuizLogic(QuizDatabase(os.path.join(tempfile.mkdtemp(), "q.db")))
push = g._push_event
def stamped(*a, **k):    # GameEvent stamps the real clock: keep toasts on the fake one
    push(*a, **k)
    g.event_feed[-1].timestamp = clock[0]
g._push_event = stamped
ui = (VerticalUI if VERTICAL else UIManager)(screen)
names = ["Deklarator", "QuizQueen_88", "maria.lopez", "Kenji"]
seen, laps, step = set(), 0, 0
while laps < 1 and clock[0] < 1_800_000_000.0 + 900:
    step += 1
    dt = (0.37, 0.11, 0.53)[step % 3]     # uneven steps land on many points of every timeline
    clock[0] += dt
    before = g.state
    if g.state == S.ASKING and step % 4 == 0:
        g.process_message(names[step % 4], str(1 + step % len(g.current_question.options)), "x")
    if g.state == S.LOBBY and step % 5 == 0:
        g.process_message(names[step % 4], str(1 + step % 4), "x")
    if g.state == S.ASKING and step % 50 == 0:
        g.process_message(names[0], "!card", "!card")
    g.update(dt)
    if before == S.PODIUM and g.state == S.LOBBY:
        laps += 1
    seen.add(g.state.name)
    ui.draw(g, {"connected": step % 200 > 20, "broadcasting": True})
print(sorted(seen))
'''


@pytest.mark.parametrize("layout", ["vertical", "horizontal"])
def test_every_state_renders(layout):
    root = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if not k.startswith("QUIZ_")}
    env.update(QUIZ_LAYOUT=layout, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONPATH=str(root))
    r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    for state in ("LOBBY", "INTRO", "ASKING", "LOCKING", "REVEALING", "PODIUM"):
        assert state in r.stdout
