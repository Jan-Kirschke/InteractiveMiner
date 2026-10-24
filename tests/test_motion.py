import pytest

from quiz import motion


@pytest.mark.parametrize("ease", motion.EASINGS, ids=lambda f: f.__name__)
def test_every_curve_starts_at_0_and_lands_on_1(ease):
    # Animations are written as lerp(a, b, ease(p)): a curve that misses an endpoint leaves
    # an element a few pixels off its layout slot for the rest of the state.
    assert ease(0.0) == pytest.approx(0.0, abs=1e-9)
    assert ease(1.0) == pytest.approx(1.0, abs=1e-9)
    assert ease(-3.0) == pytest.approx(0.0, abs=1e-9)    # before the window: clamped
    assert ease(7.0) == pytest.approx(1.0, abs=1e-9)     # long after it: clamped


def test_progress_maps_a_window_to_0_1():
    assert motion.progress(0.0, 0.5, 1.0) == 0.0
    assert motion.progress(1.0, 0.5, 1.0) == 0.5
    assert motion.progress(9.0, 0.5, 1.0) == 1.0
    assert motion.progress(0.5, 0.5, 0.0) == 1.0      # zero-length window is a step, not a crash


def test_spring_is_continuous_where_its_tail_is_snapped():
    assert abs(motion.spring(0.999) - 1.0) < 0.01
    assert max(motion.spring(i / 100) for i in range(101)) > 1.0   # it does overshoot


def test_shake_dies_out():
    dx, dy = motion.shake(2.0, amp=12)
    assert abs(dx) < 0.01 and abs(dy) < 0.01
