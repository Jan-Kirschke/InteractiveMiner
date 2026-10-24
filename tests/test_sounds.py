"""The rendered show audio, measured as the mixer plays it, and the cues derived from the show."""

from types import SimpleNamespace

import pytest

import quiz.sounds as S
from quiz.models import GameState

# Everything that sounds from "time's up" until the reveal stinger has landed:
# LOCKING plays whoosh + times_up + drumroll, REVEALING plays whoosh, then the stinger,
# and the results bed comes in under it.
REVEAL_WINDOW = ("whoosh", "times_up", "drumroll", "correct", "wrong", "music_reveal")
# The shared cue contract (brief_common.md) plus the cues the logic already queues
CONTRACT = ("round_sting", "power_up", "combo", "jackpot", "crowd", "halftime", "level_up", "tick_soft",
            "team_win", "buildup", "stakes", "correct", "wrong", "countdown", "final_countdown", "times_up",
            "fanfare", "whoosh", "streak", "vote", "double_points", "new_question", "show_open", "rank_up",
            "answer_lock", "drumroll")


@pytest.fixture(scope="module")
def heard():
    arrays = S.render_all(5.1)   # LATE_ANSWER_GRACE + REVEAL_AT on the server
    return {name: S.measure(st * (S.SoundManager.MUSIC_VOLUME if name.startswith("music_") else 1.0))
            for name, st in arrays.items()}


def test_every_contract_cue_is_rendered(heard):
    base = {k.split("~")[0] for k in heard}
    assert not set(CONTRACT) - base


@pytest.mark.parametrize("name", REVEAL_WINDOW)
def test_reveal_window_has_no_hiss(heard, name):
    """No white-noise snare or crash: almost no energy above 3 kHz, and no loud burst there."""
    for key in [k for k in heard if k.split("~")[0] == name]:
        m = heard[key]
        assert m["hf_share"] <= 0.02, f"{key}: {m['hf_share']:.1%} of its energy is above 3 kHz"
        assert m["hf_peak"] <= -45, f"{key}: a {m['hf_peak']:.1f} dBFS burst above 3 kHz"


def test_no_cue_hisses_or_tops_the_question_bed(heard):
    bed = heard["music_question"]["lufs"]
    bad = [f"{k}: {m['hf_share']:.1%} >3k, burst {m['hf_peak']:.1f}, max {m['lufs_max']:.1f} LUFS (bed {bed:.1f})"
           for k, m in heard.items() if not k.startswith("music_")
           and (m["hf_share"] > 0.03 or m["hf_peak"] > -42 or m["lufs_max"] > bed + 0.05)]
    assert not bad, "\n".join(bad)


def test_cues_sit_on_their_loudness_targets(heard):
    """The mix is levelled per cue: each lands on its target unless its peak cap pulled it down."""
    for name, (_fn, variants, target) in S._SFX.items():
        for v in range(variants):
            m = heard[S.variant_key(name, v)]
            want = S._buildup_level(v) if target is None else target
            capped = m["peak"] >= 20 * __import__("math").log10(S.PEAK_CAP) - 0.05
            assert m["lufs_max"] <= want + 0.3 and (capped or m["lufs_max"] >= want - 0.3), (name, v, m)


# ------------------------------------------
# ShowCues: cue names derived from the state clock
# ------------------------------------------
def _logic(state, duration, **kw):
    fields = dict(q_index=3, last_result=None, standings={}, podium=[], special_slots={})
    return SimpleNamespace(state=state, state_start_time=1.0, state_duration=duration, state_timer=duration,
                           **{**fields, **kw})


def _run(cues, logic, step=1 / 30):
    """Step the state clock to its end; return (age, cue) pairs."""
    out = []
    while logic.state_timer > 0:
        logic.state_timer -= step
        out += [(round(logic.state_duration - logic.state_timer, 2), n) for n in cues.update(logic)]
    return out


def test_reveal_cues_follow_the_choreography():
    res = SimpleNamespace(correct_players=[("a", 20, 1.0), ("b", 15, 2.0)])
    fired = _run(S.ShowCues(), _logic(GameState.REVEALING, 8.0, last_result=res, standings={"a": 1}))
    names = [n for _, n in fired]
    assert names[:3] == ["reveal_sweep", "points_fly", "points_fly_2"]   # 2 right players: 2 flights
    assert "standings_move" in names and "halftime" not in names
    t = dict((n, a) for a, n in fired)
    assert abs(t["reveal_sweep"] - 0.3) < 0.05 and abs(t["standings_move"] - 4.85) < 0.05
    assert len(names) == len(set(names))   # each once per visit
    tail = "question_sweep" if not hasattr(GameState, "BUILDUP") else None
    assert (tail in names) if tail else not {"question_sweep", "event_sweep"} & set(names)


def test_halftime_replaces_the_standings_and_final_reveal_drops_the_curtain():
    half = [n for _, n in _run(S.ShowCues(), _logic(GameState.REVEALING, 8.0, q_index=5, standings={"a": 1}))]
    assert "halftime" in half and "standings_move" not in half
    final = _run(S.ShowCues(), _logic(GameState.REVEALING, 8.0, q_index=10))
    assert [n for _, n in final if n == "final_curtain"] and dict((n, a) for a, n in final)["final_curtain"] >= 6.39


def test_podium_places_play_only_for_filled_places_in_order():
    fired = _run(S.ShowCues(), _logic(GameState.PODIUM, 14.0, podium=["x", "y"]))
    assert [n for _, n in fired] == ["podium_2", "podium_1", "next_match"]


def test_buildup_plays_the_riser_on_entry_and_the_stakes_at_1_2_s():
    state = getattr(GameState, "BUILDUP", SimpleNamespace(name="BUILDUP"))
    fired = _run(S.ShowCues(), _logic(state, 4.0))
    assert fired[0][1] == "buildup" and fired[0][0] < 0.05
    assert [n for _, n in fired] == ["buildup", "stakes"] and abs(fired[1][0] - S.STAKES_AT) < 0.05


# ------------------------------------------
# SoundManager.play: the seam to the logic's sound_queue
# ------------------------------------------
class _Snd:
    def __init__(self, length=2.0):
        self.plays, self.volume, self.length = 0, 1.0, length

    def play(self):
        self.plays += 1

    def get_length(self):
        return self.length

    def set_volume(self, v):
        self.volume = v


class _Ch:
    def __getattr__(self, _):
        return lambda *a, **k: None


@pytest.fixture
def manager():
    m = S.SoundManager.__new__(S.SoundManager)
    m.__dict__.update(_enabled=True, _sounds={"correct": [_Snd()], "vote": [_Snd(0.2), _Snd(0.2)]},
                      _last_play_time={}, _last_variant={}, _music={"question": _Snd(), "question_tension": _Snd(), "reveal": _Snd()},
                      _scene_bed=None, _wanted_bed=None, _duck_until=0.0, _duck_depth=1.0, _duck=1.0,
                      _tension=0.0, _intensity=0.0, _applied=None, _bed_channels=[_Ch(), _Ch()],
                      _roll_channel=_Ch(), _layer_channel=_Ch(), _riser_channel=_Ch())
    return m


def test_play_ignores_unknown_names(manager):
    manager.play("no_such_cue")
    manager.play("halftime")   # a contract name with no sound loaded yet
    assert manager._last_play_time == {}


def test_music_ducks_under_a_stinger_and_comes_back(manager, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(S.time, "monotonic", lambda: clock[0])
    manager.play("correct")
    for _ in range(10):
        manager.update()
    assert manager._music["question"].volume == pytest.approx(S.DUCK["correct"], abs=0.01)
    clock[0] += 3.0
    manager.set_tension(0.4)   # logic.buildup_intensity
    for _ in range(120):
        manager.update()
    assert manager._music["question"].volume == pytest.approx(1.0, abs=0.01)
    assert manager._music["question_tension"].volume == pytest.approx(0.4, abs=0.01)


def test_repeated_cues_vary_and_respect_their_cooldown(manager, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(S.time, "monotonic", lambda: clock[0])
    for _ in range(6):
        manager.play("vote")
        clock[0] += 0.35
    a, b = manager._sounds["vote"]
    assert (a.plays, b.plays) == (3, 3)   # alternates, never the same voicing twice in a row
    manager.play("vote")
    manager.play("vote")                  # inside the 0.3 s cooldown: dropped
    assert a.plays + b.plays == 7


def test_controller_times_buildup_and_stakes_and_feeds_the_tension():
    from quiz.controller import MainGameController
    calls = []
    sounds = SimpleNamespace(play=lambda n, variant=None: calls.append(n),
                             play_buildup=lambda i, s: calls.append(("buildup", i, s)),
                             play_stakes=lambda: calls.append("stakes"),
                             set_tension=lambda i: calls.append(("tension", i)), update=lambda: None)
    state = getattr(GameState, "BUILDUP", SimpleNamespace(name="BUILDUP"))
    logic = _logic(state, 6.0, sound_queue=["whoosh", "buildup", "stakes"], buildup={"intensity": 0.8},
                   buildup_intensity=0.8)
    g = MainGameController.__new__(MainGameController)
    g.logic, g.sounds, g._cues = logic, sounds, S.ShowCues()
    g._play_sounds()
    assert calls == ["whoosh", ("buildup", 0.8, 6.0), ("tension", 0.8)]   # queued copies are not doubled
    logic.sound_queue, logic.state_timer = [], 6.0 - S.STAKES_AT
    g._play_sounds()
    assert calls[-2:] == ["stakes", ("tension", 0.8)]
