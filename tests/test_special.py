"""Special rounds: the pack loader, the slot map and each round's scoring (no network)."""

import json
import time

import pytest

import quiz.logic as logic_mod
from quiz.db import QuizDatabase
from quiz.logic import QuizLogic, BOT_PREFIX
from quiz.models import GameState
from quiz.special import SpecialDecks, PACK_DIR


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setattr(logic_mod, "requests", None)  # no OTDB calls
    db = QuizDatabase(str(tmp_path / "quiz.db"))
    g = QuizLogic(db)
    g.state = GameState.ASKING
    g.mini_event = ""
    g.is_double_points = False
    g.question_start_time = time.time()
    g.question_duration = 30.0
    yield g
    db.close()


def write_pack(tmp_path, items, name="special_test.json"):
    path = tmp_path / name
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


# ------------------------------------------
# LOADER
# ------------------------------------------
def test_bundled_packs_load_into_decks_by_type():
    decks = SpecialDecks()
    items = [it for p in PACK_DIR.glob("special_*.json") for it in json.loads(p.read_text(encoding="utf-8"))]
    for kind in ("majority", "higher_lower", "odd_one_out"):
        bundled = sum(it.get("type") == kind for it in items)
        assert bundled >= 150 and decks.count(kind) == bundled, kind   # every bundled item plays
    assert decks.count("number") == 0          # Closest Call is not built: its pack stays inert


def test_loader_skips_items_a_round_cannot_play(tmp_path):
    path = write_pack(tmp_path, [
        {"type": "higher_lower", "question": "Higher or lower: x?", "options": ["More", "Less"], "answer": 0},
        {"type": "higher_lower", "question": "No answer?", "options": ["More", "Less"]},
        {"type": "higher_lower", "question": "Answer out of range?", "options": ["More", "Less"], "answer": 2},
        {"type": "higher_lower", "question": "Four options?", "options": ["A", "B", "C", "D"], "answer": 0},
        {"type": "odd_one_out", "question": "Two options?", "options": ["A", "B"], "answer": 0},
        {"type": "majority", "question": "Duplicate options?", "options": ["A", "A", "B"]},
        {"type": "number", "question": "Year?", "answer": 1889},
        "not an item",
    ])
    decks = SpecialDecks([path])
    assert decks.count("higher_lower") == 1
    assert decks.count("odd_one_out") == decks.count("majority") == 0


def test_mode_name_prefix_is_dropped_from_the_text(tmp_path):
    # The round chip already says "HIGHER OR LOWER": the text should not say it again.
    path = write_pack(tmp_path, [{"type": "higher_lower", "question": "Higher or lower: is it tall?",
                                  "options": ["Taller", "Shorter"], "answer": 1}])
    q = SpecialDecks([path]).draw("higher_lower")
    assert q.text == "Is it tall?"
    assert (q.kind, q.correct_index, q.correct_answer) == ("higher_lower", 1, "Shorter")


def test_deck_serves_every_item_before_repeating(tmp_path):
    items = [{"type": "odd_one_out", "question": f"Odd one out: set {i}. Which?", "options": ["A", "B", "C", "D"],
              "answer": 2} for i in range(5)]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    first = [decks.draw("odd_one_out").text for _ in range(5)]
    assert len(set(first)) == 5


def test_deck_refill_never_repeats_the_last_question(tmp_path):
    items = [{"type": "odd_one_out", "question": f"Odd one out: set {i}. Which?", "options": ["A", "B", "C", "D"],
              "answer": 2} for i in range(2)]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    drawn = [decks.draw("odd_one_out").text for _ in range(60)]   # 30 refills
    assert all(a != b for a, b in zip(drawn, drawn[1:]))


def test_shuffled_options_keep_the_right_answer(tmp_path):
    items = [{"type": "odd_one_out", "question": "Odd one out: gases. Which?",
              "options": ["Neon", "Argon", "Helium", "Nitrogen"], "answer": 3}]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    for _ in range(20):
        q = decks.draw("odd_one_out")
        assert q.options[q.correct_index] == "Nitrogen" == q.correct_answer


def test_drawn_question_is_a_copy(tmp_path):
    items = [{"type": "majority", "question": "Crowd Mind: pet?", "options": ["Dog", "Cat"]}]
    decks = SpecialDecks([write_pack(tmp_path, items)])
    q = decks.draw("majority")
    q.kind = "minority"
    assert decks.draw("majority").kind == "majority"


def test_special_packs_stay_out_of_the_bank(game):
    texts = {json.loads(p.read_text(encoding="utf-8"))[0]["question"] for p in PACK_DIR.glob("special_*.json")}
    rows = game.bank._conn.execute("SELECT text FROM questions").fetchall()
    assert not texts & {r["text"] for r in rows}


# ------------------------------------------
# SLOT MAP
# ------------------------------------------
def ask(game, n):
    game.q_index = n - 1
    game._transition_to(GameState.ASKING)
    return game.current_question


def test_slot_map_puts_a_special_round_on_its_question(game):
    game.special_slots = {2: "odd_one_out"}
    assert ask(game, 1).kind == "classic"
    assert ask(game, 2).kind == "odd_one_out"
    assert ask(game, 3).kind == "classic"


def test_default_slots_give_every_match_its_special_rounds(game):
    kinds = {n: ask(game, n).kind for n in range(1, 11)}
    assert kinds[4] in ("majority", "minority")
    assert [n for n, k in kinds.items() if k != "classic"] == sorted(game.special_slots)


# ------------------------------------------
# CROWD MIND (majority)
# ------------------------------------------
def crowd(game, kind="majority"):
    from quiz.models import Question
    game.current_question = Question("Which pet?", "", ["Dog", "Cat", "Fish", "Parrot"], -1, "Animals", "easy",
                                     kind=kind)
    game.current_answers = {}


def answer_at(game, user, choice, seconds):
    game.current_answers[user] = (choice, game.question_start_time + seconds)


def test_crowd_mind_most_picked_option_scores_like_a_right_answer(game):
    crowd(game)
    answer_at(game, "alice", 1, 3)     # Cat, fast: 10 x 2 speed
    answer_at(game, "bob", 1, 20)      # Cat, slow: 10
    answer_at(game, "carol", 0, 3)     # Dog: the crowd did not pick it
    res = game._resolve_question()
    assert res.winners == [1] and not res.void
    assert {u: p for u, p, _ in res.correct_players} == {"alice": 20, "bob": 10}
    assert [u for u, _ in res.wrong_players] == ["carol"]
    assert game.standings["alice"].points == 20


def test_crowd_mind_losers_keep_their_streak(game):
    crowd(game)
    carol = game.db.get_or_create_player("carol")
    carol.streak = 4
    game._standing("carol").streak = 4
    for u, c in (("alice", 1), ("bob", 1), ("carol", 0)):
        answer_at(game, u, c, 5)
    game._resolve_question()
    assert carol.streak == 4 and carol.wrong_answers == 0
    assert game.standings["carol"].streak == 4


def test_crowd_mind_tie_lets_every_tied_option_win(game):
    crowd(game)
    for u, c in (("a", 0), ("b", 0), ("c", 2), ("d", 2), ("e", 3)):
        answer_at(game, u, c, 5)
    res = game._resolve_question()
    assert res.winners == [0, 2]
    assert {u for u, _, _ in res.correct_players} == {"a", "b", "c", "d"}


def test_bots_never_decide_or_score_a_crowd_round(game):
    crowd(game)
    for u, c in (("alice", 0), ("bob", 1), ("carol", 1)):
        answer_at(game, u, c, 5)
    for i in range(4):
        answer_at(game, f"{BOT_PREFIX}{i}", 0, 1)   # four bots on Dog would outvote the humans
    res = game._resolve_question()
    assert res.winners == [1]
    assert res.option_counts == [1, 2, 0, 0] and res.total_answers == 3
    assert all(not u.startswith(BOT_PREFIX) for u, _, _ in res.correct_players)
    assert not any(u.startswith(BOT_PREFIX) for u in game.standings)


def test_crowd_round_with_under_three_real_players_is_void(game):
    crowd(game)
    alice = game.db.get_or_create_player("alice")
    alice.streak = 2
    answer_at(game, "alice", 0, 2)
    answer_at(game, "bob", 0, 2)
    answer_at(game, BOT_PREFIX + "Rookie", 0, 2)     # a bot does not make it three
    res = game._resolve_question()
    assert res.void and res.winners == [] and res.correct_players == []
    assert alice.score == 0 and alice.streak == 2


def test_bots_answer_crowd_rounds_inside_the_options(game, monkeypatch):
    monkeypatch.setattr(logic_mod, "MIN_PLAYERS", 4)
    crowd(game)
    game._last_round_real_players = set()
    picks = []
    for _ in range(25):    # 100 bot picks: a 25% "right answer" roll would hit index -1 often
        game._schedule_bots()
        picks += [c for _, c, _ in game._scheduled_bots]
    assert len(picks) == 100 and all(0 <= c < 4 for c in picks)


def test_crowd_reveal_says_what_the_crowd_picked(game):
    crowd(game)
    game.special_slots = {}
    for u, c in (("alice", 1), ("bob", 1), ("carol", 0)):
        game.current_answers[u] = (c, time.time())
    game._enter_revealing()
    assert "Cat" in game.host_line


# ------------------------------------------
# LONELY ANSWER (minority): the Crowd Mind pack, scoring flipped, twist shown only after lock
# ------------------------------------------
def test_lonely_answer_least_picked_option_wins(game):
    crowd(game, "minority")
    for u, c in (("a", 0), ("b", 0), ("c", 0), ("d", 1), ("e", 1), ("f", 2)):
        answer_at(game, u, c, 5)
    res = game._resolve_question()
    assert res.winners == [2]                       # Parrot (option 4) had no picks: it cannot win
    assert [u for u, _, _ in res.correct_players] == ["f"]
    assert game.db.get_or_create_player("a").streak == 0 and game.db.get_or_create_player("a").wrong_answers == 0


def test_lonely_answer_tie_and_bots_never_decide(game):
    crowd(game, "minority")
    for u, c in (("a", 0), ("b", 0), ("c", 1), ("d", 3)):
        answer_at(game, u, c, 5)
    answer_at(game, BOT_PREFIX + "Rookie", 2, 1)    # a lone bot pick would be the loneliest
    res = game._resolve_question()
    assert res.winners == [1, 3]
    assert {u for u, _, _ in res.correct_players} == {"c", "d"}


def test_crowd_slot_turns_lonely_by_chance(game, monkeypatch):
    game.special_slots = {4: "majority"}
    monkeypatch.setattr(logic_mod, "LONELY_CHANCE", 1.0)
    assert ask(game, 4).kind == "minority"
    monkeypatch.setattr(logic_mod, "LONELY_CHANCE", 0.0)
    assert ask(game, 4).kind == "majority"
    game.special_slots = {4: "minority"}            # a slot can also force the twist
    assert ask(game, 4).kind == "minority"


def test_lonely_twist_stays_hidden_until_the_reveal(game, monkeypatch):
    from quiz.ui import round_style
    game.special_slots = {4: "minority"}
    q = ask(game, 4)
    assert round_style(q)[0] == "CROWD MIND"                  # asking: looks like any Crowd Mind
    assert "lonely" not in (game.host_line + " ".join(e.text for e in game.event_feed)).lower()
    game._transition_to(GameState.LOCKING)
    assert "lonely" not in (game.host_line + " ".join(e.text for e in game.event_feed)).lower()
    assert "LONELY" in round_style(q, revealed=True)[0]
    for u, c in (("a", 0), ("b", 0), ("c", 1)):
        game.current_answers[u] = (c, time.time())
    game._transition_to(GameState.REVEALING)
    assert "lonely" in game.host_line.lower()


# ------------------------------------------
# HIGHER OR LOWER: two options, classic scoring
# ------------------------------------------
def test_higher_lower_takes_only_1_or_2_and_scores_like_classic(game, monkeypatch):
    monkeypatch.setattr(logic_mod, "MIN_PLAYERS", 4)
    game._last_round_real_players = set()
    q = ask(game, 2)
    assert q.kind == "higher_lower" and len(q.options) == 2
    assert "type 1 or 2" in game.host_line.lower()
    assert all(0 <= c < 2 for _, c, _ in game._scheduled_bots)
    game.process_message("bob", "3")
    assert "bob" not in game.current_answers
    q.difficulty = "easy"                                   # x1: difficulty pays is in test_loop.py
    right, wrong = q.correct_index, 1 - q.correct_index
    answer_at(game, "alice", right, 1)
    answer_at(game, "bob", wrong, 1)
    res = game._resolve_question()
    assert [(u, p) for u, p, _ in res.correct_players] == [("alice", 20)]
    assert res.winners == [right] and game.db.get_or_create_player("bob").wrong_answers == 1


# ------------------------------------------
# ODD ONE OUT: four items, the one that does not belong is right
# ------------------------------------------
def test_odd_one_out_scores_the_item_that_does_not_belong(game):
    q = ask(game, 6)
    assert q.kind == "odd_one_out" and len(q.options) == 4
    assert "odd one out" in game.host_line.lower()
    answer_at(game, "alice", q.correct_index, 1)
    answer_at(game, "bob", (q.correct_index + 1) % 4, 1)
    res = game._resolve_question()
    assert [u for u, _, _ in res.correct_players] == ["alice"] and res.winners == [q.correct_index]


def expire(game):
    game.state_timer = 0
    game.update(0)


def test_a_full_match_plays_every_special_slot(game, monkeypatch):
    monkeypatch.setattr(logic_mod, "MIN_PLAYERS", 0)        # no bots: the crowd is the three of us
    game.state = GameState.WAITING
    game.update(0)
    expire(game)                                            # lobby -> intro
    kinds = {}
    for n in range(1, 11):
        expire(game)                                        # build-up
        expire(game)
        q = game.current_question
        kinds[n] = q.kind
        crowd_round = q.kind in ("majority", "minority")
        pick = 0 if crowd_round else q.correct_index
        game.process_message("alice", str(pick + 1))
        game.process_message("bob", str(pick + 1))
        game.process_message("carol", str((pick + 1) % len(q.options) + 1))
        expire(game)
        expire(game)
        res = game.last_result
        assert not res.void
        alice_won = "alice" in [u for u, _, _ in res.correct_players]
        assert alice_won == (q.kind != "minority"), n      # Lonely Answer: carol's lone pick wins
    expire(game)
    assert game.state == GameState.PODIUM and game.podium[0].username in ("alice", "bob")
    assert {n: k for n, k in kinds.items() if k != "classic"}.keys() == game.special_slots.keys()
    assert kinds[2] == "higher_lower" and kinds[4] in ("majority", "minority") and kinds[6] == "odd_one_out"


# ------------------------------------------
# 50:50 JOKER (chat): "!half 1 3" names two options once per match on a 3+ streak; pays half
# ------------------------------------------
def classic(game, correct=1, options=("A", "B", "C", "D")):
    from quiz.models import Question
    game.current_question = Question("Q?", options[correct], list(options), correct, "Test", "easy")
    game.current_answers, game.lock_order, game.half_picks = {}, [], {}


def on_streak(game, user, n=3):
    game._standing(user).streak = n


def test_half_pays_half_when_the_right_answer_is_one_of_the_two(game):
    classic(game, correct=1)
    on_streak(game, "alice")
    game.process_message("alice", "half 1 2", "!half 1 2", at=game.question_start_time + 1)
    answer_at(game, "bob", 1, 1)
    res = game._resolve_question()
    pts = {u: p for u, p, _ in res.correct_players}
    assert pts == {"alice": 10, "bob": 20}                  # 10 x 2 speed, halved
    assert res.option_counts == [0.5, 1.5, 0, 0]            # the split still adds up to the players
    assert game.standings["alice"].streak == 4               # a hit keeps the streak going


def test_half_misses_when_neither_pick_is_right(game):
    classic(game, correct=1)
    on_streak(game, "alice")
    game.process_message("alice", "half 13", "!half 1,3")   # chat strips the comma
    res = game._resolve_question()
    assert res.correct_players == [] and game.standings["alice"].streak == 0


@pytest.mark.parametrize("msg", ["half", "half 1", "half 1 1", "half 1 2 3", "half 1 5", "half 12 3"])
def test_half_needs_exactly_two_different_options(game, msg):
    classic(game)
    on_streak(game, "alice")
    game.process_message("alice", msg, "!" + msg)
    assert "alice" not in game.current_answers and "alice" not in game.halves_used


def test_half_needs_a_streak_and_works_once_per_match(game):
    classic(game)
    on_streak(game, "alice", 2)
    game.process_message("alice", "half 1 2")
    assert "alice" not in game.current_answers               # streak 2: still locked
    on_streak(game, "alice", 3)
    game.process_message("alice", "half 1 2")
    assert game.half_picks == {"alice": (0, 1)}
    classic(game)                                            # next question, same match
    game.process_message("alice", "half 1 2")
    assert "alice" not in game.current_answers
    game._enter_intro()                                      # a new match hands it back
    assert not game.halves_used


def test_half_is_not_offered_on_crowd_or_two_option_rounds_or_to_bots(game):
    crowd(game)
    game.half_picks = {}
    on_streak(game, "alice")
    game.process_message("alice", "half 1 2")
    classic(game, correct=0, options=("More", "Less"))
    game.process_message("alice", "half 1 2")                # would cover both answers
    classic(game)
    on_streak(game, BOT_PREFIX + "Rookie")
    game.process_message(BOT_PREFIX + "Rookie", "half 1 2")
    assert game.half_picks == {} and game.halves_used == set()


def test_plain_answer_after_half_replaces_it_but_the_joker_is_spent(game):
    classic(game, correct=1)
    on_streak(game, "alice")
    game.process_message("alice", "half 1 2")
    game.process_message("alice", "1")                       # changed her mind: just A
    assert "alice" not in game.half_picks and "alice" in game.halves_used
    res = game._resolve_question()
    assert res.correct_players == []


def test_half_after_time_is_up_only_as_a_first_answer(game):
    classic(game)
    on_streak(game, "alice")
    on_streak(game, "bob")
    game.process_message("alice", "3")
    game.state = GameState.LOCKING
    game.process_message("alice", "half 1 2")                # answers are locked
    game.process_message("bob", "half 1 2")                  # a late first answer still counts
    assert game.half_picks == {"bob": (0, 1)} and game.current_answers["alice"][0] == 2


def test_reaching_the_streak_announces_the_joker(game):
    classic(game, correct=1)
    on_streak(game, "alice", 2)
    answer_at(game, "alice", 1, 3)
    game._resolve_question()
    assert any("50:50" in e.text and "alice" in e.text for e in game.event_feed)


def test_empty_deck_falls_back_to_a_classic_question(game, tmp_path):
    game.special = SpecialDecks([write_pack(tmp_path, [])])
    game.special_slots = {2: "odd_one_out"}
    q = ask(game, 2)
    assert q.kind == "classic" and q.options
