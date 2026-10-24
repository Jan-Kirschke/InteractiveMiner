"""Game loop 2 (docs/game-modes.md): difficulty that pays, level ups, the ramp fallback,
fresh categories, host-line variety, combo steps, rotating formats, the community goal and
!double. Every rule at its seam, no network."""

import time

import pytest

import quiz.logic as logic_mod
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic, BOT_PREFIX
from quiz.models import GameState, Question

BOT = BOT_PREFIX + "Rookie"


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)  # no OTDB calls
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.state = GameState.ASKING
    g.mini_event = ""
    g.is_double_points = False
    g.special_slots = {}
    g.question_start_time = time.time()
    g.question_duration = 30.0
    yield g
    db.close()


def classic(game, difficulty="easy", correct=1, kind="classic"):
    game.current_question = Question("Q?", "B", ["A", "B", "C", "D"], correct, "Test", difficulty, kind=kind)
    game.current_answers, game.lock_order, game.half_picks = {}, [], {}


def answer_at(game, user, choice, seconds=3):
    game.current_answers[user] = (choice, game.question_start_time + seconds)


def points(res):
    return {u: p for u, p, _ in res.correct_players}


def ask(game, n):
    game.q_index = n - 1
    game._transition_to(GameState.ASKING)
    return game.current_question


def served(difficulties):
    """A _pop_question stand-in: question n gets difficulties[n - 1] (or the ramp's tier)."""
    def pop(game):
        def _pop(want=""):
            d = difficulties[game.q_index - 1] if difficulties else want
            return Question(f"Q{game.q_index}?", "B", ["A", "B", "C", "D"], 1, "Test", d)
        return _pop
    return pop


# ------------------------------------------
# 1. DIFFICULTY PAYS, LEVEL UP, GRACEFUL RAMP
# ------------------------------------------
@pytest.mark.parametrize("difficulty,pts", [("easy", 20), ("medium", 25), ("hard", 30)])
def test_points_scale_with_the_shown_difficulty(game, difficulty, pts):
    classic(game, difficulty)
    answer_at(game, "alice", 1, 3)                  # 10 x 2 speed, then x difficulty
    assert points(game._resolve_question()) == {"alice": pts}


def test_crowd_rounds_ignore_the_difficulty_label(game):
    classic(game, "hard", correct=-1, kind="majority")
    for u in ("alice", "bob", "carol"):
        answer_at(game, u, 0, 3)
    assert set(points(game._resolve_question()).values()) == {20}


def level_ups(game, upto=10):
    fired = []
    for n in range(1, upto + 1):
        game.sound_queue.clear()                    # update() clears it every frame
        ask(game, n)
        if "level_up" in game.sound_queue:
            fired.append(n)
    return fired


def test_level_up_fires_once_per_ramp_step(game):
    game._enter_intro()
    game._pop_question = served(None)(game)
    assert level_ups(game) == [4, 8]
    assert any("LEVEL UP" in e.text and "HARD" in e.text for e in game.event_feed)


def test_level_up_waits_for_a_question_of_the_new_tier(game):
    game._enter_intro()
    game._pop_question = served(["easy"] * 4 + ["medium"] * 4 + ["medium", "hard"])(game)
    assert level_ups(game) == [5, 10]               # Q4 and Q8-9 served below the ramp's tier


def test_a_new_match_levels_up_again(game):
    game._pop_question = served(None)(game)
    game._enter_intro()
    level_ups(game)
    game._enter_intro()
    assert level_ups(game) == [4, 8]


def test_dry_tier_serves_the_nearest_tier(game, monkeypatch):
    # No bank, no cache: the built-in questions have no hard ones, so "hard" must get medium.
    monkeypatch.setattr(game.bank, "pick", lambda *a, **k: None)
    game._question_cache = []
    assert {game._pop_question("hard").difficulty for _ in range(5)} == {"medium"}


def test_dry_tier_in_the_cache_serves_the_nearest_tier(game, monkeypatch):
    monkeypatch.setattr(game.bank, "pick", lambda *a, **k: None)
    game._question_cache = [Question(f"{d}?", "B", ["A", "B"], 1, "T", d) for d in ("easy", "medium", "easy")]
    assert game._pop_question("hard").difficulty == "medium"


# ------------------------------------------
# BUILDUP: the tension beat before every question (brief: "Tension build-up contract", frozen)
# ------------------------------------------
BUILDUP_KEYS = {"q_no", "of", "tier", "stakes", "kind", "event", "headline", "subline", "spotlight", "intensity"}


def expire(game):
    game.state_timer = 0
    game.update(0)


def to_lobby(game):
    game.state = GameState.WAITING
    game.update(0)


def play_match(game, on_state=None):
    """Lobby -> podium. on_state(game) runs after every state change. Returns buildup dicts, states seen."""
    to_lobby(game)
    seen, builds = [game.state], []
    while game.state != GameState.PODIUM:
        expire(game)
        seen.append(game.state)
        if game.state == GameState.BUILDUP:
            builds.append(dict(game.buildup))
        if on_state:
            on_state(game)
    return builds, seen


def test_buildup_runs_before_every_question(game):
    builds, seen = play_match(game)
    asks = [i for i, s in enumerate(seen) if s == GameState.ASKING]
    assert len(asks) == 10 and all(seen[i - 1] == GameState.BUILDUP for i in asks)
    assert seen[:4] == [GameState.LOBBY, GameState.INTRO, GameState.BUILDUP, GameState.ASKING]
    assert [b["q_no"] for b in builds] == list(range(1, 11))


def test_buildup_dict_has_exactly_the_contract_keys(game):
    builds, _ = play_match(game)
    for b in builds:
        assert set(b) == BUILDUP_KEYS
        assert b["of"] == 10 and b["tier"] in ("easy", "medium", "hard", "expert")
        assert b["headline"] and b["subline"] and 0 <= b["intensity"] <= 1
        assert b["event"] in (None, "final", "lightning", "first_blood", "jackpot")
    assert builds[-1]["event"] == "final" and builds[4]["event"] == "lightning"


def test_buildup_is_none_outside_buildup(game):
    to_lobby(game)
    assert game.buildup is None
    expire(game)
    expire(game)
    assert game.state == GameState.BUILDUP and game.buildup
    expire(game)
    assert game.state == GameState.ASKING and game.buildup is None


def test_the_buildup_question_is_the_one_asked(game):
    to_lobby(game)
    expire(game)
    expire(game)
    q = game.current_question
    expire(game)
    assert game.current_question is q and game.q_index == 1


def test_answers_during_buildup_do_not_count(game):
    to_lobby(game)
    expire(game)
    expire(game)
    game.process_message("alice", "1")
    expire(game)
    assert "alice" not in game.current_answers


def test_final_and_level_up_buildups_run_longer(game):
    game._pop_question = served(None)(game)
    lengths = {}

    def note(g):
        if g.state == GameState.BUILDUP:
            lengths[g.q_index] = g.state_duration
    play_match(game, note)
    assert lengths[10] == lengths[4] == lengths[8] == logic_mod.BUILDUP_TIME_BIG
    assert lengths[2] == logic_mod.BUILDUP_TIME < logic_mod.BUILDUP_TIME_BIG


def test_intensity_rises_through_the_match_and_ends_at_full(game):
    builds, _ = play_match(game)
    curve = [b["intensity"] for b in builds]
    assert all(a <= b for a, b in zip(curve, curve[1:])) and curve[0] < 0.5 and curve[-1] == 1.0
    assert game.buildup_intensity == 1.0
    expire(game)                                           # podium -> lobby
    assert game.buildup_intensity == 0.0
    expire(game)
    expire(game)
    assert game.buildup_intensity < 0.5                    # a new match starts light again


def test_stakes_are_what_the_fastest_fresh_right_answer_scores(game):
    stakes, got = {}, {}

    def play(g):
        n, user = g.q_index, f"fresh{g.q_index}"           # a new player each time: no streak
        if g.state == GameState.BUILDUP:
            stakes[n] = g.buildup["stakes"]
        elif g.state == GameState.ASKING:
            g.current_answers[user] = (g.current_question.correct_index, g.question_start_time)
        elif g.state == GameState.REVEALING:
            got[n] = points(g.last_result)[user]
    game._pop_question = served(None)(game)
    play_match(game, play)
    assert got == stakes
    assert stakes[1] == 20 and stakes[5] == 37 and stakes[10] == 60   # 20 x1.25 x1.5 lightning; 20 x1.5 x2


def standing(game, user, pts):
    game._standing(user).points = pts


def buildup_at(game, n):
    game.q_index = n - 1
    game._transition_to(GameState.BUILDUP)
    return game.buildup


def test_bots_are_never_spotlighted_or_named(game):
    game._enter_intro()
    standing(game, BOT, 500)
    game.db.get_or_create_player(BOT).streak = 40
    standing(game, "alice", 30)
    standing(game, "bob", 18)
    game.db.get_or_create_player("bob").streak = 6
    game.perfect = {"alice", BOT}
    for n in range(2, 11):
        b = buildup_at(game, n)
        assert b["spotlight"] in ("alice", "bob"), n
        assert "Bot" not in b["subline"] + game.host_line, n


def test_buildup_facts_come_from_the_match(game):
    game._enter_intro()
    standing(game, "alice", 40)
    standing(game, "bob", 28)
    game.db.get_or_create_player("bob").streak = 6
    game.perfect = {"alice", "bob", "carol"}
    text = " | ".join(buildup_at(game, n)["subline"] for n in range(2, 10))
    assert "alice leads by 12" in text
    assert "3 players are still perfect" in text
    assert "bob's 6-answer streak" in text


def test_buildup_never_repeats_a_fact_or_a_wording_twice_in_a_row(game):
    import re
    game._enter_intro()
    standing(game, "alice", 40)
    standing(game, "bob", 28)
    game.perfect = {"alice", "bob"}
    subs, lines = [], []
    for n in range(2, 10):
        subs.append(re.sub(r"\d+", "#", buildup_at(game, n)["subline"]))
        lines.append(re.sub(r"\d+", "#", game.host_line).split(".")[0])   # the opener alone
    assert all(a != b for a, b in zip(subs, subs[1:])), subs
    assert all(a != b for a, b in zip(lines, lines[1:])), lines


def test_perfect_players_drop_out_on_a_miss_and_bots_never_count(game):
    game._enter_intro()
    classic(game)
    answer_at(game, "alice", 1)
    answer_at(game, "bob", 1)
    answer_at(game, BOT, 1)
    game._enter_revealing()
    assert game.perfect == {"alice", "bob"}
    classic(game)
    answer_at(game, "alice", 1)
    answer_at(game, "bob", 0)
    game._enter_revealing()
    assert game.perfect == {"alice"}


def test_an_event_keeps_the_headline_when_the_tier_steps_up_with_it(game):
    game._enter_intro()
    game._pop_question = served(["easy"] * 4 + ["medium"] * 6)(game)
    for n in range(1, 5):
        buildup_at(game, n)
    b = buildup_at(game, 5)                                 # the first medium question is the lightning one
    assert b["headline"] == "QUESTION 5 · LIGHTNING ROUND" and "Medium questions" in b["subline"]


def test_lonely_answer_buildup_still_looks_like_crowd_mind(game):
    game.special_slots = {4: "minority"}
    game._enter_intro()
    b = buildup_at(game, 4)
    assert game.current_question.kind == "minority" and b["kind"] == "majority"
    assert "lonely" not in (b["headline"] + b["subline"] + game.host_line).lower()


# ------------------------------------------
# 2. FRESH CATEGORIES, HOST-LINE VARIETY
# ------------------------------------------
def test_the_vote_never_offers_the_last_three_voted_categories(game, monkeypatch):
    won = []
    for _ in range(40):
        game._enter_lobby()
        offered = {cid for cid, _ in game.vote_state.options.values() if cid}
        assert not offered & set(won[-3:]), (offered, won[-3:])
        game.vote_state.votes = {"alice": 1}             # option 1 is always a real category
        game._resolve_vote()
        won.append(game.vote_state.options[1][0])


def test_mixed_bag_does_not_use_up_a_recent_slot(game):
    game._enter_lobby()
    first = game.vote_state.options[1][0]
    game.vote_state.votes = {"alice": 1}
    game._resolve_vote()
    for _ in range(3):
        game._enter_lobby()
        game.vote_state.votes = {"alice": 4}             # Mixed bag
        game._resolve_vote()
    for _ in range(60):                                  # 3 of 24 offered each time: it would show up
        game._enter_lobby()
        assert first not in {cid for cid, _ in game.vote_state.options.values()}


def reveal_line(game, right, of):
    classic(game)
    for i in range(of):
        answer_at(game, f"p{i}", 1 if i < right else 0)
    game._enter_revealing()
    return game.host_line


@pytest.mark.parametrize("right,of", [(0, 0), (0, 4), (1, 10), (3, 10), (6, 10), (9, 10)])
def test_reveal_lines_never_repeat_twice_in_a_row(game, right, of):
    lines = [reveal_line(game, right, of) for _ in range(6)]
    assert all(a != b for a, b in zip(lines, lines[1:])), lines
    if of:
        assert all(f"{round(100 * right / of)}%" in line for line in lines if right)


def test_question_lines_vary(game):
    import re
    lines = []
    for n in (1, 2, 6, 9):                                   # no event on these
        ask(game, n)
        lines.append(re.sub(r"\d+", "#", game.host_line).split(".")[0])   # the wording, not the category
    assert all(a != b for a, b in zip(lines, lines[1:])), lines
