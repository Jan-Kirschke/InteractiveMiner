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
    assert level_ups(game) == [4, 8, 10]                   # Q10 asks for expert (EXPERT_FINAL)
    assert any("LEVEL UP" in e.text and "HARD" in e.text for e in game.event_feed)


def test_level_up_waits_for_a_question_of_the_new_tier(game):
    game._enter_intro()
    game._pop_question = served(["easy"] * 4 + ["medium"] * 4 + ["medium", "hard"])(game)
    assert level_ups(game) == [5, 10]               # Q4 and Q8-9 served below the ramp's tier


def test_a_question_above_the_ramp_does_not_level_up_early(game):
    game._enter_intro()
    game._pop_question = served(["easy", "hard", "easy", "medium"] + ["medium"] * 6)(game)
    assert level_ups(game, upto=4) == [4]                  # Q2 measured hard: still the easy part of the ramp


def test_a_new_match_levels_up_again(game):
    game._pop_question = served(None)(game)
    game._enter_intro()
    level_ups(game)
    game._enter_intro()
    assert level_ups(game) == [4, 8, 10]


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
    assert stakes[1] == 20 and stakes[5] == 37 and stakes[10] == 80   # 20 x1.25 x1.5 lightning; 20 x2 expert x2


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


@pytest.mark.parametrize("streak,mult", [(0, 1.0), (2, 1.0), (3, 1.3), (4, 1.3), (5, 1.5), (9, 1.5),
                                         (10, 2.0), (15, 2.5), (24, 2.5), (25, 3.0), (80, 3.0)])
def test_combo_multiplier_steps(streak, mult):
    assert logic_mod.combo_mult(streak) == mult


def test_a_combo_pays_from_the_streak_before_the_answer(game):
    classic(game)
    game.db.get_or_create_player("alice").streak = 4
    game.db.get_or_create_player("bob").streak = 2
    answer_at(game, "alice", 1)
    answer_at(game, "bob", 1)
    assert points(game._resolve_question()) == {"alice": 26, "bob": 20}   # 20 x1.3; 20 x1.0


def test_combo_steps_share_one_toast_and_one_sound(game):
    classic(game)
    for u in ("alice", "bob", "carol", BOT):
        game.db.get_or_create_player(u).streak = 4
        answer_at(game, u, 1)
    game.db.get_or_create_player("dave").streak = 1
    answer_at(game, "dave", 1)
    game.sound_queue.clear()
    game._resolve_question()
    combos = [e.text for e in game.event_feed if "COMBO" in e.text]
    assert len(combos) == 1 and "x1.5" in combos[0] and "+2" in combos[0] and "Bot" not in combos[0]
    assert game.sound_queue.count("combo") == 1 and "streak" not in game.sound_queue


# ------------------------------------------
# 4. ROTATING FORMATS: classic, speed, survivors, teams; halftime
# ------------------------------------------
def lobby_for(game, fmt):
    """Enter a lobby whose match number plays this format."""
    n = next(n for n in range(1, 9) if logic_mod.format_for(n) == fmt)
    game.db.next_match_number = lambda: n
    game.sound_queue.clear()
    game._enter_lobby()
    game._enter_intro()


def test_no_two_matches_in_a_row_share_a_format():
    fmts = [logic_mod.format_for(n) for n in range(1, 50)]
    assert all(a != b for a, b in zip(fmts, fmts[1:]))
    assert set(fmts[:4]) == {"classic", "speed", "survivors", "teams"}


def test_the_format_is_announced_at_match_open(game):
    from quiz.special import FORMATS
    lobby_for(game, "survivors")
    assert game.match_format == "survivors"
    assert "SURVIVORS" in game.host_line.upper() and "round_sting" in game.sound_queue
    assert any(FORMATS["survivors"][0] in e.text for e in game.event_feed)
    lobby_for(game, "classic")
    assert "round_sting" not in game.sound_queue


def test_speed_match_makes_every_question_a_lightning_question(game):
    lobby_for(game, "speed")
    game._pop_question = served(["easy"] * 10)(game)
    for n in (1, 2, 6):
        assert buildup_at(game, n)["stakes"] == 30           # 20 x1.5
        game._transition_to(GameState.ASKING)
        assert game.question_duration == logic_mod.LIGHTNING_TIME
        answer_at(game, "alice", 1, 1)
        assert points(game._resolve_question())["alice"] == 30


def test_classic_match_keeps_the_normal_clock(game):
    lobby_for(game, "classic")
    ask(game, 2)
    assert game.question_duration == logic_mod.QUESTION_DISPLAY_TIME


def reveal(game, right=(), wrong=()):
    classic(game)
    for u in right:
        answer_at(game, u, 1)
    for u in wrong:
        answer_at(game, u, 0)
    game._enter_revealing()


def test_survivors_split_the_pot(game):
    lobby_for(game, "survivors")
    reveal(game, right=("alice", "bob", "carol", "dave", BOT))
    reveal(game, right=("alice", "bob", "carol", BOT), wrong=("dave",))
    assert game.perfect == {"alice", "bob", "carol"}
    assert any("3 SURVIVORS" in e.text for e in game.event_feed)
    before = game.standings["alice"].points
    game._enter_podium()
    assert game.standings["alice"].points == before + 66      # 200 // 3
    assert game.standings["dave"].points == 20 and game.match_stats["survivors"] == (3, 66)   # out: no share
    assert "jackpot" in game.sound_queue


def test_many_survivors_get_at_least_the_minimum(game):
    lobby_for(game, "survivors")
    reveal(game, right=[f"p{i}" for i in range(25)])
    game._enter_podium()
    assert game.match_stats["survivors"] == (25, 20)


def test_survivors_wiped_out_pays_nobody(game):
    lobby_for(game, "survivors")
    reveal(game, right=("alice",))
    reveal(game, wrong=("alice",))
    assert any("wiped out" in e.text.lower() for e in game.event_feed)
    game._enter_podium()
    assert game.match_stats["survivors"] == (0, 0) and "jackpot" not in game.sound_queue


def test_no_survivor_pot_outside_survivors(game):
    lobby_for(game, "classic")
    reveal(game, right=("alice",))
    game._enter_podium()
    assert game.standings["alice"].points == 20 and "survivors" not in game.match_stats


def names_on(team, n=2):
    out, i = [], 0
    while len(out) < n:
        if logic_mod.team_of(f"u{i}") == team:
            out.append(f"u{i}")
        i += 1
    return out


def test_teams_come_from_the_name_and_never_change():
    assert logic_mod.team_of("Alice") == logic_mod.team_of("alice") in ("gold", "teal")
    assert {logic_mod.team_of(f"u{i}") for i in range(20)} == {"gold", "teal"}
    # recorded 2026-10-24: a player keeps the team across restarts (Python's hash() would not)
    assert [logic_mod.team_of(n) for n in ("alice", "bob", "Deklarator")] == ["teal", "gold", "teal"]


def test_the_team_with_the_higher_average_wins_a_bonus_for_every_member(game):
    lobby_for(game, "teams")
    g1, g2, g3 = names_on("gold", 3)
    t1, = names_on("teal", 1)
    reveal(game, right=(g1, t1), wrong=(g2, g3))           # gold 20 / 3 players, teal 20 / 1
    reveal(game, right=(BOT,) * 1, wrong=())               # a bot scores, but for no team
    assert game.team_scores() == {"gold": 7, "teal": 20}
    game._enter_podium()
    assert game.standings[t1].points == 20 + logic_mod.TEAM_WIN_BONUS
    assert game.standings[g1].points == 20
    assert game.match_stats["team"] == ("teal", 7, 20) and "team_win" in game.sound_queue


def test_a_team_tie_pays_nobody(game):
    lobby_for(game, "teams")
    g1, = names_on("gold", 1)
    t1, = names_on("teal", 1)
    reveal(game, right=(g1, t1))
    game._enter_podium()
    assert game.standings[g1].points == 20 and game.match_stats["team"] == ("", 20, 20)


def test_team_command_names_your_team_with_a_cooldown(game):
    game.process_message("alice", "team")
    game.process_message("alice", "team")
    game.process_message(BOT, "team")
    said = [e.text for e in game.event_feed if "Team" in e.text]
    assert said == [f"alice plays for Team {logic_mod.team_of('alice').capitalize()}"]


def test_halftime_after_question_five(game):
    lobby_for(game, "teams")
    for n in range(1, 6):
        game.q_index = n - 1
        game.sound_queue.clear()
        game._prepare_question()
        game.current_answers = {"alice": (game.current_question.correct_index, game.question_start_time)}
        game._enter_revealing()
        assert ("halftime" in game.sound_queue) == (n == 5)
    assert any(e.text.startswith("HALFTIME") and "alice" in e.text for e in game.event_feed)


# ------------------------------------------
# 5. COMMUNITY GOAL: chat's right answers on Q1-Q9 unlock a jackpot final
# ------------------------------------------
def at_question(game, n, right=(), wrong=()):
    game.q_index = n
    game.is_double_points = n == 10
    reveal(game, right, wrong)


@pytest.mark.parametrize("last_players,goal", [(0, 10), (1, 10), (6, 30)])
def test_the_goal_scales_with_the_last_match(game, last_players, goal):
    game.match_player_count = last_players
    game._enter_intro()
    assert game.community_goal == goal and game.community_correct == 0 and not game.community_jackpot


def test_real_right_answers_on_q1_to_q9_count(game):
    game._enter_intro()
    at_question(game, 1, right=("alice", "bob", BOT), wrong=("carol",))
    at_question(game, 10, right=("alice",))
    assert game.community_correct == 2


def test_reaching_the_goal_unlocks_the_jackpot_once(game):
    game._enter_intro()
    goal = game.community_goal
    players = [f"p{i}" for i in range(goal // 2)]
    game.sound_queue.clear()
    at_question(game, 1, right=players)
    assert not game.community_jackpot and "crowd" in game.sound_queue          # half-way
    game.sound_queue.clear()
    at_question(game, 2, right=players + [f"q{i}" for i in range(goal)])
    assert game.community_jackpot and game.sound_queue.count("power_up") == 1
    game.sound_queue.clear()
    at_question(game, 3, right=players)
    assert "power_up" not in game.sound_queue
    assert len([e for e in game.event_feed if "COMMUNITY GOAL" in e.text]) == 1


def test_the_jackpot_final_pays_every_real_right_answer(game):
    game._enter_intro()
    game.community_jackpot = True
    game.q_index, game.is_double_points = 10, True
    classic(game)
    answer_at(game, "alice", 1)
    answer_at(game, BOT, 1)
    answer_at(game, "bob", 0)
    pts = points(game._resolve_question())
    assert pts["alice"] == 40 + logic_mod.JACKPOT_BONUS and pts[BOT] == 40 and "bob" not in pts


def test_no_jackpot_final_without_the_goal(game):
    game._enter_intro()
    game.q_index, game.is_double_points = 10, True
    classic(game)
    answer_at(game, "alice", 1)
    assert points(game._resolve_question())["alice"] == 40


def test_buildup_tells_chat_how_far_the_goal_is(game):
    game._enter_intro()
    game.community_correct = game.community_goal - 4
    texts = [buildup_at(game, n)["subline"] for n in range(2, 10)]
    assert any("4 more right answers" in t for t in texts)
    game.community_jackpot = True
    assert "jackpot" in buildup_at(game, 10)["subline"].lower()


# ------------------------------------------
# 6. !double: once per match after 5 answers; x2 if right, up to -20 match points if wrong
# ------------------------------------------
def can_double(game, user, answered=5, pts=0):
    st = game._standing(user)
    st.answered, st.points = answered, pts


def test_double_needs_five_answers_this_match(game):
    classic(game)
    can_double(game, "alice", answered=4)
    game.process_message("alice", "double")
    assert "alice" not in game.double_picks
    can_double(game, "alice", answered=5)
    game.process_message("alice", "double")
    assert "alice" in game.double_picks and "alice" in game.doubles_used


def test_double_pays_twice_when_right(game):
    classic(game)
    can_double(game, "alice")
    game.process_message("alice", "double")
    answer_at(game, "alice", 1)
    answer_at(game, "bob", 1)
    assert points(game._resolve_question()) == {"alice": 40, "bob": 20}


def test_double_costs_match_points_when_wrong_but_never_below_zero(game):
    classic(game)
    can_double(game, "alice", pts=50)
    can_double(game, "bob", pts=8)
    for u in ("alice", "bob"):
        game.process_message(u, "double")
        answer_at(game, u, 0)
    lifetime = game.db.get_or_create_player("alice").score
    game._resolve_question()
    assert game.standings["alice"].points == 50 - logic_mod.DOUBLE_STAKE and game.standings["bob"].points == 0
    assert game.db.get_or_create_player("alice").score == lifetime          # only match points


def test_double_is_once_per_match(game):
    classic(game)
    can_double(game, "alice")
    game.process_message("alice", "double")
    classic(game)
    game.double_picks = {}
    game.process_message("alice", "double")
    assert "alice" not in game.double_picks
    game._enter_intro()
    assert not game.doubles_used


def test_double_is_not_for_crowd_rounds_late_answers_bots_or_with_half(game):
    classic(game, correct=-1, kind="majority")
    can_double(game, "alice")
    game.process_message("alice", "double")
    classic(game)
    game.state = GameState.LOCKING
    game.process_message("alice", "double")
    game.state = GameState.ASKING
    can_double(game, BOT)
    game.process_message(BOT, "double")
    game._standing("carol").streak = 3
    can_double(game, "carol")
    game.process_message("carol", "half 1 2")
    game.process_message("carol", "double")
    assert game.double_picks == set() and "carol" in game.half_picks
    can_double(game, "dave")
    game._standing("dave").streak = 3
    game.process_message("dave", "double")
    game.process_message("dave", "half 1 2")
    assert "dave" not in game.half_picks


def test_reaching_five_answers_announces_double_once_per_reveal(game):
    classic(game)
    for u in ("alice", "bob", BOT):
        can_double(game, u, answered=4)
        answer_at(game, u, 1)
    game.sound_queue.clear()
    game._resolve_question()
    said = [e.text for e in game.event_feed if "!double" in e.text]
    assert len(said) == 1 and "Bot" not in said[0] and game.sound_queue.count("power_up") == 1


def test_using_double_plays_power_up_on_the_next_frame(game):
    classic(game)
    can_double(game, "alice")
    game.state_timer = 20
    game.process_message("alice", "double")
    game.update(0.01)
    assert "power_up" in game.sound_queue
    game.update(0.01)
    assert "power_up" not in game.sound_queue


def test_a_burst_of_doubles_plays_one_sound(game):
    classic(game)
    game.state_timer = 20
    for i in range(300):
        can_double(game, f"p{i}")
        game.process_message(f"p{i}", "double")
    game.update(0.01)
    assert game.sound_queue.count("power_up") == 1


def test_one_survivor_is_singular(game):
    lobby_for(game, "survivors")
    reveal(game, right=("alice",))
    assert any(e.text.startswith("1 SURVIVOR left") for e in game.event_feed)


def test_question_lines_vary(game):
    import re
    lines = []
    for n in (1, 2, 6, 9):                                   # no event on these
        ask(game, n)
        lines.append(re.sub(r"\d+", "#", game.host_line).split(".")[0])   # the wording, not the category
    assert all(a != b for a, b in zip(lines, lines[1:])), lines
