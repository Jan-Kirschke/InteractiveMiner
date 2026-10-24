# Game modes for The Lifelong Quiz

Special question types and rounds that fit "answer 1-4 in chat or on the phone page". Ranked by fun per effort. **Top 4 = BUILD FIRST.** Effort: S = under a day, M = one to two days, L = more.

**The code today (2026-10-24):**

- `logic.py process_message` accepts only a bare `1`-`4`, and `answer_server.py AnswerHub.answer` rejects anything else.
- `_enter_asking` fixes the event slots: lightning on Q5, first blood or jackpot on Q3/Q7, double points on Q10.
- `_resolve_question` scores `choice == q.correct_index`. `Question` has no type field.
- Bots answer from `correct_index`.

**Built (2026-10-24, branch feature/matches):** the shared plumbing, Crowd Mind, Lonely Answer, Higher or Lower, Odd One Out and the 50:50 joker. `config.SPECIAL_SLOTS = {2: "higher_lower", 4: "majority", 6: "odd_one_out"}` gives every 10-question match 3 special rounds. 30% of the Crowd Mind slots secretly play as Lonely Answer (`LONELY_CHANCE`). Closest Call is not built, so `special_number.json` stays inert. Tests: `tests/test_special.py`.

## Game loop 2: less repetition across a 24-match show (design, 2026-10-24 evening)

A 3-hour show plays about 24 matches, 240 questions. Before this, each match had the same shape, the same host lines and the same scoring. The aim: match N+1 feels different from match N, chat plays together as well as alone, and the questions visibly get harder. Everything works through chat only, uses no per-message or per-frame work over all players, and is shown through toasts, host lines and logic fields (the visual pass comes later).

Each feature has a one-line rule. Built in this order, one commit each:

| # | Feature | One-line rule |
|---|---|---|
| 1 | Difficulty pays | Easy x1, medium x1.25, hard x1.5 on the question's shown difficulty (crowd rounds x1). |
| 1 | Level up | When the ramp steps up (Q4 medium, Q8 hard) and a question of that tier is served, a LEVEL UP toast and `level_up` play once. |
| 1 | Graceful ramp | When a tier runs dry, the nearest tier is served (lower first), and the label and points follow the question actually served. |
| 2 | Fresh categories | The vote never offers the last 3 voted categories. |
| 2 | Host-line variety | Every reveal and question line has several wordings that rotate, so the same wording never plays twice in a row. |
| 3 | Combo steps | Your streak multiplier steps up: x1.3 from 3 right in a row, x1.5 from 5, x2 from 10, x2.5 from 15, x3 from 25. |
| 4 | Rotating formats | Matches rotate Classic, Speed, Survivors, Teams by match number, so no two matches in a row share a format. |
| 4 | Speed Match | Every question is a 22 s lightning question at 1.5x. |
| 4 | Survivors | Answer every question right (crowd rounds: just answer); the survivors split 200 points, at least 20 each. |
| 4 | Teams | Your name puts you in Team Gold or Team Teal for good; the team with the higher average match points gets +15 for every member who played. |
| 4 | Halftime | After Q5, a halftime toast names the leader and the format's state. |
| 5 | Community goal | Chat's right answers on Q1-Q9 reach 5 per player of the last match (at least 10), and Q10 becomes a jackpot: every right answer +25. |
| 6 | `!double` | Once per match, after 5 answers in it: this question's answer pays x2 if right, or costs up to 20 match points if wrong. |

### Tension build-up (BUILT, operator request, top priority)

Every question now opens with `GameState.BUILDUP`: `... REVEALING -> BUILDUP -> ASKING ...`, and `INTRO -> BUILDUP` for Q1.

- **Length:** `BUILDUP_TIME`, 4 s (`QUIZ_BUILDUP_SECONDS`). `BUILDUP_TIME_BIG`, 6 s, before the final and a difficulty step-up.
- **Serving:** the question and its event are served at BUILDUP entry, so the build-up can talk about them. Answers still count only from ASKING, so the UI should not show the options during BUILDUP.
- **`logic.buildup`:** set during BUILDUP and None otherwise. Its keys are exactly the brief's contract: `q_no`, `of`, `tier`, `stakes`, `kind`, `event`, `headline`, `subline`, `spotlight`, `intensity`.
  - `stakes` = `question_stakes()`: the fastest right answer from a player with no streak. It uses the same `question_mult()` as scoring: difficulty, lightning, final.
  - `kind` shows a Lonely Answer as `majority`, so the twist stays hidden.
  - `event` is `final`, `lightning`, `first_blood`, `jackpot` or None.
- **`headline`:** "QUESTION n · ...". The event wins (FOR DOUBLE POINTS, LIGHTNING ROUND, ...), then a step-up (THE HARD ROUND), then the special round, then THE WARM-UP (Q1) or THE LAST HURDLE (Q9), then a rotating line.
- **`subline`:** one fact from the match. A step-up says so. The final prefers the lead. Otherwise it rotates through these, never the same kind twice in a row:
  - "Only 3 players are still perfect" (`logic.perfect`: every answer right, while a crowd round only needs an answer);
  - "alice leads by 12";
  - "bob's 6-answer streak is on the line";
  - "The hardest question so far: only 18% ever got it right" (`bank.stats`, from 15 real answers);
  - "Last match, only 31% got the hard ones right";
  - "Only 2 of 9 got the last one right".

  With no fact, a rotating tip is used.
- **`spotlight`:** the player the fact names, else the match leader, else None. Bots are never named, spotlighted, perfect or counted.
- **`intensity`:** 0.15 at Q1, rising about 0.08 per question. Step-ups add 0.1, events 0.05 and a race closer than the stakes 0.05. The value is capped at 0.95, never falls within a match, and is 1.0 for the final. `logic.buildup_intensity` keeps the last value and resets to 0 in the lobby.
- **Host line:** a rotating opener, the fact and "Up to N points". The opener never repeats twice in a row.
- **Cost:** everything is computed once per question at BUILDUP entry. The scans cover this match's standings (two top scorers, the best streak) and one bank lookup, never per frame or per message.

**Not built, and why:**
- Category Gauntlet: the lobby vote already makes every non-mixed match one category.
- `!shield`: `Player.streak_shield` already halves the streak once, earned at a 5-streak.
- Expert tier: the bank knows only easy, medium and hard (`bank.measured_difficulty`) and no pack labels "expert". It needs a bank change first.
- Harder late-show matches: the question bumper (`transitions.py`) reads the static `DIFFICULTY_RAMP`, so a shifted ramp would show the wrong tier. It waits for the visual pass.
- A hype meter per question: the community goal covers the group moment, and two meters would compete for the screen.

**Bots** never survive, never join a team, never count for the community goal and cannot use `!double`.

**Sound cues:** `level_up`, `combo`, `round_sting` (format at match open), `halftime`, `jackpot` (survivor and community payouts), `team_win`, `crowd` (goal half-way, team lead change) and `power_up` (goal reached, `!double` earned or used).

## Shared plumbing (once, for all top 4)

1. `Question` gains `kind: str = "classic"` and `value: float | None = None`.
2. A loader, `quiz/special.py`, reads `quiz/packs/special_*.json` into decks by `type`. Do not use `bank.add`: it keys on text and needs `correct` + `wrong`.
3. A config map, e.g. `SPECIAL_SLOTS = {2: "higher_lower", 4: "majority", 6: "odd_one_out", 8: "number"}`. `_enter_asking` takes the slot's deck question instead of calling `_pop_question`. `mini_event` stays independent, so one slot can be both "number" and "jackpot".
4. `_resolve_question` branches on `q.kind`. `ui.py` draws a type banner, like LIGHTNING.

**The packs are inert today.** `logic.py` feeds every `packs/*.json` through `load_items` and then `bank.add`. Special items have no `correct`/`incorrect`, so `bank.add` skips them. Verified on an in-memory bank: 0 rows added per special file. **The current loader ignores them until the main session implements each type.**

## 1. Crowd Mind (majority): BUILD FIRST, S

- **Play:** an opinion question with no right answer ("Which superpower would most of chat pick?"). You score by matching the crowd. Chat lobbies while the timer runs.
- **Scoring:** after lock, the option with the most real-player picks wins; ties all win. Winners get `_calculate_points` (speed and streak apply). Losers keep their streak. Fewer than 3 real answers voids the question.
- **Screen:** banner "CROWD MIND: pick what most people pick" with no live percentages. The reveal animates the bars into percentages.
- **Input:** 1-4.
- **Code:** a `_resolve_question` branch. Bots pick at random and are excluded from the count. The bars already exist (`RoundResult.option_counts`).

```json
{"type": "majority", "question": "Crowd Mind: which pet would most of chat rather have?",
 "options": ["Dog", "Cat", "Fish", "Parrot"], "category": "Animals", "difficulty": "easy", "fact": ""}
```

## 2. Higher or Lower: BUILD FIRST, S

- **Play:** a two-button call against a reference value ("Is the Nile longer or shorter than 5,000 km?"). Ideal for the 12 s lightning slot.
- **Scoring:** classic; `answer` is the correct index.
- **Screen:** the existing true/false layout; the reveal shows the real value from `fact`.
- **Input:** 1-2.
- **Code:** the loader maps it to a 2-option `Question`, plus the banner.

```json
{"type": "higher_lower", "question": "Higher or lower: is the Nile longer or shorter than 5,000 km?",
 "options": ["Longer", "Shorter"], "answer": 0, "category": "Geography", "difficulty": "medium",
 "fact": "The Nile is roughly 6,650 km long."}
```

## 3. Odd One Out: BUILD FIRST, S

- **Play:** four items with a hidden rule; one doesn't belong. The payoff is the "aha" when `fact` explains the rule.
- **Scoring:** classic.
- **Screen:** big tiles; the reveal crosses out the three that belong.
- **Input:** 1-4.
- **Code:** loader, banner and reveal styling. Each text has a unique theme hint, so it stays keyable.

```json
{"type": "odd_one_out", "question": "Odd one out: gases. Which one does not belong?",
 "options": ["Neon", "Argon", "Helium", "Nitrogen"], "answer": 3, "category": "Science & Nature",
 "difficulty": "hard", "fact": "Nitrogen is not a noble gas; neon, argon and helium are."}
```

## 4. Closest Call (number): BUILD FIRST, M

- **Play:** type a number ("In what year was the Eiffel Tower completed?"). Near misses still score, and the reveal sweeps along a number line.
- **Scoring:** the last answer before lock counts.
  - Exact: 3 x `BASE_POINTS`.
  - Within `close`: 2 x.
  - Otherwise, the closest 10% (at least 1; earlier answer wins ties): 1 x.
  - No speed multiplier; Q10 double points still apply. Exact or within `close` keeps the streak.
- **Screen:** "TYPE A NUMBER" plus the unit. The reveal draws a number line with the guesses as dots, drops the true value in, and names the top 3.
- **Input:**
  - Chat: a bare integer between `min` and `max`, with separators stripped, parsed before the 1-4 check.
  - Phone: a numeric keypad in `web/answer.html`, and `/api/answer` accepting `{"number": n}`.
- **Code:** `current_answers` stores the value; `_resolve_question` gets a branch; bots guess `answer` plus noise.

```json
{"type": "number", "question": "Closest Call: in what year was the Eiffel Tower completed?",
 "answer": 1889, "close": 10, "min": 1000, "max": 2100, "unit": "", "category": "History",
 "difficulty": "medium", "fact": "It was built as the entrance arch for the 1889 World's Fair."}
```

## 5. Lonely Answer (minority): S after Crowd Mind

Crowd Mind's pack with the scoring flipped: the least-picked option with at least one real pick wins. Chat coordination backfires, which makes for good banter. Reveal the twist only after lock. Input is 1-4. Code: one flag on the Crowd Mind branch.

## 6. Double Down (bet before the final): M

A 6 s betting window before Q10:

- `1` = x1
- `2` = x2
- `3` = x3, and a wrong answer loses 3 x `BASE_POINTS` of match points (floor 0).

The screen shows stake chips beside the names. Code: a new `GameState.BETTING` plus a stake dict read by `_resolve_question`. This replaces the flat Q10 double.

## 7. Sudden Death final: M

Q10 becomes up to five 8 s questions for the match top 5. Wrong or no answer means you're out; the last one standing gets +50, and everyone else still scores normally. The screen shows five portraits greying out. Input is 1-4. Code: a sub-loop in `_on_state_expired`, eligibility from `standings`.

## 8. Crew Clash: M

One question per match where a crew scores (20 points to each member playing) if most of its members pick right. The screen shows crew bars per option. Input is 1-4. Code: a `_resolve_question` branch reusing the `crew_race` grouping.

## 9. 50:50 Lifeline (streak reward): BUILT, chat only

The phone page is gone and the stream screen is shared, so nothing can disappear for one player. Instead, once per match, a player on a 3-answer streak in that match (`HALF_STREAK`) names two options: `!half 1 3` (also `!5050 1 3`, `!half 1,3`). If the right answer is one of them, it pays half; otherwise it is a normal wrong answer. Not on crowd rounds or two-option questions. The screen shows "plays the 50:50 joker" and a 50:50 tag in the locked-in list, never the two options. Each pick counts as half a vote in the answer split. A plain `1`-`4` while the question runs replaces it, and the joker stays spent. Reaching the streak announces "50:50 joker unlocked". Code: `QuizLogic._cmd_half`, `half_picks`, `halves_used`.

## 10. Poll Then Truth: M

Live percentages appear after 5 s, like "ask the audience" for everyone. Answers sent before the poll appears earn +5 for confidence. Input is 1-4. Code: a UI timer plus a timestamp check.

## 11. Emoji Rebus: M

"🦁👑" -> The Lion King: a classic question with an `emoji` field drawn large. minecraft.ttf has no emoji, so it needs a colour emoji font on the cloud host. Check pygame freetype colour support there first.

## 12. Order Up (sequence): L

"Oldest first", played as chained sub-picks (FIRST?, then NEXT? from the remaining three). Hard to explain on stream and needs multi-step state.

**Example packs:** `quiz/packs/special_majority.json`, `special_higher_lower.json`, `special_odd_one_out.json` and `special_number.json`, with 15 each.
