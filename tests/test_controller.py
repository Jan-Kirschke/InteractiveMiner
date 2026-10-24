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
