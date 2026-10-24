"""Every state of both layouts draws through a whole match without raising (headless).

The match runs in a subprocess: the layout (and the screen size the UI modules read at import)
is fixed by QUIZ_LAYOUT when quiz.config is first imported, and the other tests have imported it
already. The build-up card and every cover style run in process on both surface sizes.
"""

import os
import subprocess
import sys
from pathlib import Path

import pygame
import pytest

from quiz.transitions import STYLES, Transitions
from quiz.ui import Fonts

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
g.db.next_match_number = lambda: int(os.environ["RENDER_MATCH"])   # the match number picks the format
g._enter_lobby()
print("format", g.match_format)
ui = (VerticalUI if VERTICAL else UIManager)(screen)
def guard(paint):   # the next question is served at BUILDUP entry: its options must not show yet
    def wrapped(*a, **k):
        assert g.state != S.BUILDUP, "answer options drawn during BUILDUP"
        return paint(*a, **k)
    return wrapped
for meth in ("_btn", "_btn_lit", "_draw_option"):
    if hasattr(ui, meth):
        setattr(ui, meth, guard(getattr(ui, meth)))
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
    if g.state == S.ASKING and step % 7 == 0:   # power-ups the locked-in list tags
        g.process_message(names[1], "double", "!double")
        g.process_message(names[2], "half 1 2", "!half 1 2")
    g.update(dt)
    if before == S.PODIUM and g.state == S.LOBBY:
        laps += 1
    seen.add(g.state.name)
    ui.draw(g, {"connected": step % 200 > 20, "broadcasting": True})
print(sorted(seen))
'''


@pytest.mark.parametrize("layout,match,fmt", [
    ("vertical", 1, "classic"), ("vertical", 2, "speed"), ("vertical", 3, "survivors"), ("vertical", 4, "teams"),
    ("horizontal", 1, "classic"), ("horizontal", 4, "teams")])
def test_every_state_renders(layout, match, fmt):
    """A whole match of each format: the build-up, the format pods and the podium cards."""
    root = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if not k.startswith("QUIZ_")}
    env.update(QUIZ_LAYOUT=layout, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PYTHONPATH=str(root),
               RENDER_MATCH=str(match))
    r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    assert f"format {fmt}" in r.stdout
    for state in ("LOBBY", "INTRO", "BUILDUP", "ASKING", "LOCKING", "REVEALING", "PODIUM"):
        assert state in r.stdout


# Build-up card and cover styles run in process: Transitions takes its size from the surface it
# draws to, so both layouts are covered without re-importing quiz.config.
@pytest.fixture(scope="module")
def fonts():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    pygame.joystick.quit()   # the dummy driver's joystick subsystem leaks Windows USER objects
    return Fonts()


class _Logic:
    q_index, match_no, pips = 4, 2, [True, False, None, True]

    def __init__(self, buildup):
        self.buildup = buildup


FULL = {"q_no": 10, "of": 10, "tier": "expert", "stakes": 80, "kind": "classic", "event": "final",
        "headline": "FINAL QUESTION · DOUBLE POINTS", "subline": "QuizQueen_88 leads by 24 with one question left to play",
        "spotlight": "QuizQueen_88", "intensity": 1.0}
SPARSE = {"q_no": 5}
ODD = {"q_no": "3", "of": None, "tier": "IMPOSSIBLE", "stakes": "lots", "kind": "no_such_round", "event": None,
       "headline": "", "subline": None, "spotlight": "", "intensity": 7}


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
@pytest.mark.parametrize("style", sorted(STYLES))
@pytest.mark.parametrize("raw", [FULL, SPARSE, ODD], ids=["full", "sparse", "odd"])
def test_buildup_card_every_style(fonts, size, style, raw):
    screen = pygame.Surface(size)
    fx = Transitions(fonts)
    info = Transitions.buildup_info(_Logic(raw))
    assert 0.0 <= info["intensity"] <= 1.0
    dur = 4.0
    fx.start("buildup", 0.0, boundary=dur, lead=dur, style=style, **info)
    t = 0.0
    while t < dur + STYLES[style][1] + 0.2:   # cover, card beats, uncover after the boundary
        fx.draw(screen, t)
        t += 0.09
    assert not fx.active(t)


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080)])
@pytest.mark.parametrize("style", sorted(STYLES))
def test_standalone_cover(fonts, size, style):
    screen = pygame.Surface(size)
    fx = Transitions(fonts)
    for p in (0.0, 0.3, 0.7, 1.0):
        fx.cover(screen, style, p)
        fx.cover(screen, style, p, out=True)
