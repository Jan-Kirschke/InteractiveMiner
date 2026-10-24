"""The rendered show audio, measured as the mixer plays it (play gains applied)."""

import pytest

import quiz.sounds as S

# Everything that sounds from "time's up" until the reveal stinger has landed:
# LOCKING plays whoosh + times_up + drumroll, REVEALING plays whoosh, then the stinger,
# and the lobby bed returns under it.
REVEAL_WINDOW = ("whoosh", "times_up", "drumroll", "correct", "wrong", "music_lobby")


@pytest.fixture(scope="module")
def heard():
    arrays = S.render_all(5.1)   # LATE_ANSWER_GRACE + REVEAL_AT on the server
    return {name: S.measure(st * (S.SoundManager.MUSIC_VOLUME if name.startswith("music_")
                                  else S.SFX_GAIN))
            for name, st in arrays.items()}


@pytest.mark.parametrize("name", REVEAL_WINDOW)
def test_reveal_window_has_no_hiss(heard, name):
    """No white-noise snare or crash: almost no energy above 3 kHz, and no loud burst there."""
    m = heard[name]
    assert m["hf_share"] <= 0.02, f"{name}: {m['hf_share']:.1%} of its energy is above 3 kHz"
    assert m["hf_peak"] <= -45, f"{name}: a {m['hf_peak']:.1f} dBFS burst above 3 kHz"


@pytest.mark.parametrize("name", [n for n in REVEAL_WINDOW if not n.startswith("music_")])
def test_reveal_window_is_never_louder_than_the_question_bed(heard, name):
    bed = heard["music_question"]["lufs"]
    assert heard[name]["lufs_max"] <= bed, f"{name} peaks at {heard[name]['lufs_max']:.1f} LUFS, bed {bed:.1f}"
