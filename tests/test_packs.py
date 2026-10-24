"""Bundled question packs (quiz/packs/*.json): what QuizLogic imports into the bank at start-up.

The bank silently drops what it cannot use (INSERT OR IGNORE on the text, wrong options equal to the
correct one, a difficulty the match ramp never asks for), so a broken pack shows up only as missing
questions on stream. These checks make that loud.
"""

import json
from collections import Counter

from quiz.config import DIFFICULTY_RAMP
from quiz.import_questions import load_items
from quiz.special import PACK_DIR

# Packs that predate the vertical-screen limits; they keep only the base rules.
LEGACY = {
    "animals", "art_myth", "books_comics_anime", "film_tv", "food_culture", "games_tech", "geography_world",
    "h_anime_manga", "h_art", "h_board_games", "h_books", "h_comics", "h_computers", "h_film", "h_mathematics",
    "h_music", "h_mythology", "h_television", "h_video_games", "history_world", "math_vehicles_politics", "music",
    "science_nature", "sports_global", "true_false_mix", "world_starter",
}
MAX_QUESTION, MAX_OPTION = 110, 28          # what the 1080-wide vertical layout fits without shrinking
SERVED = set(DIFFICULTY_RAMP.values())      # bank.pick only ever asks for these labels


def bank_packs():
    return sorted(p for p in PACK_DIR.glob("*.json") if not p.name.startswith("special_"))


def problems(items: list[dict], strict: bool, other_texts: set[str]) -> list[str]:
    out = []
    for it in items:
        text, correct, wrong = it["text"].strip(), it["correct"].strip(), [w.strip() for w in it["wrong"]]
        tag = text[:60]
        if not text or not correct or not it["category"]:
            out.append(f"empty field: {tag}")
        if not 1 <= len(wrong) <= 3 or correct in wrong or len(set(wrong)) != len(wrong):
            out.append(f"options: {tag}")
        if str(it["difficulty"]).lower() not in SERVED:
            out.append(f"difficulty {it['difficulty']!r} is never served: {tag}")
        if not strict:
            continue
        if len(wrong) not in (1, 3) or (len(wrong) == 1 and {correct, *wrong} != {"True", "False"}):
            out.append(f"needs 3 wrong options (or True/False): {tag}")
        if len(text) > MAX_QUESTION or any(len(o) > MAX_OPTION for o in [correct, *wrong]):
            out.append(f"too long for the vertical screen: {tag}")
        if not str(it.get("fact") or "").strip():
            out.append(f"no fact: {tag}")
        if text.lower() in other_texts:
            out.append(f"text already in another pack: {tag}")
    return out


def test_every_bundled_pack_imports_cleanly():
    packs = {p.stem: load_items(str(p)) for p in bank_packs()}
    assert packs, "no bundled packs found"
    found = []
    for name, items in packs.items():
        assert items, f"{name}: empty pack"
        others = {it["text"].strip().lower() for n, its in packs.items() if n != name for it in its}
        found += [f"{name}: {p}" for p in problems(items, name not in LEGACY, others)]
        if name not in LEGACY:
            dupes = [t for t, c in Counter(it["text"].strip().lower() for it in items).items() if c > 1]
            found += [f"{name}: duplicate text in pack: {t[:60]}" for t in dupes]
    assert not found, "\n".join(found)
