"""The game loop around the broadcaster: the frame being converted is never drawn over."""

import time

import pygame

import quiz.broadcaster as B
from quiz.broadcaster import YouTubeBroadcaster
from quiz.controller import MainGameController
from tests.test_broadcaster import _as_rgb


class _Chat:
    is_connected = True


class _FillUI:
    """Stands in for the UI: every draw paints the whole screen a new colour."""

    def __init__(self, screen):
        self.screen, self.n = screen, 0

    def draw(self, logic, status):
        self.n += 1
        self.screen.fill((self.n * 40 % 256, 0, 0))


def test_pygame_starts_without_the_joystick_subsystem():
    from quiz.controller import init_pygame
    init_pygame()
    assert pygame.display.get_init() and pygame.font.get_init() and not pygame.joystick.get_init()
    pygame.display.set_mode((64, 64))
    pygame.event.get()   # the game loop's event pump works (joystick quit-after-init broke it)


def test_saves_never_block_the_game_loop(tmp_path):
    # A commit that takes a second (WAL checkpoint on a busy disk) must not stall a frame or
    # the systemd watchdog ping that follows it in the same loop.
    from quiz.db import QuizDatabase
    from quiz.models import GameState

    class SlowDisk(QuizDatabase):
        def _write_rows(self, conn, rows):
            time.sleep(1.0)
            super()._write_rows(conn, rows)

    class _Logic:
        state = GameState.REVEALING

    class _Sounds:
        def set_scene(self, name):
            pass

    g = MainGameController.__new__(MainGameController)
    g.db, g.logic, g.sounds = SlowDisk(str(tmp_path / "q.db")), _Logic(), _Sounds()
    g._prev_logic_state, g._last_save_time = None, 0.0
    for i in range(500):
        g.db.get_or_create_player(f"u{i}").add_points(i)
    t0 = time.perf_counter()
    g._save_on_state_change()      # scores were just updated: save
    g._periodic_save()
    assert time.perf_counter() - t0 < 0.1
    g.db.close()
    again = QuizDatabase(str(tmp_path / "q.db"))
    assert len(again._players) == 500
    again.close()


def test_render_waits_until_the_last_frame_was_converted(monkeypatch):
    real = pygame.transform.smoothscale

    def slow(*a):
        time.sleep(0.2)  # conversion still running when the next frame starts
        return real(*a)
    monkeypatch.setattr(B.pygame.transform, "smoothscale", slow)
    g = MainGameController.__new__(MainGameController)
    g.screen = pygame.Surface((216, 384))
    g.ui, g.logic, g.chat, g._frame_count = _FillUI(g.screen), None, _Chat(), 0
    g.broadcaster = YouTubeBroadcaster(stream_key="k", width=216, height=384, fps=30, game_fps=30, out_height=256)
    g.broadcaster._active = True

    g._render()
    want = pygame.image.tobytes(real(g.screen, (144, 256)), "RGB")
    g._broadcast_frame()
    g._render()  # the next frame
    assert g.broadcaster.wait_frame(2.0)
    assert _as_rgb(g.broadcaster._latest, g.broadcaster.pix_fmt) == want
