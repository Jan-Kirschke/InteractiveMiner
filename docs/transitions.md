# Transitions, build-up and brand moments

`quiz/transitions.py` draws every cut-away of the show: the match open, the build-up before
each question, the halftime ribbon, the final curtain and the next-match sweep. It depends
only on `quiz.config`, `quiz.models`, `quiz.special`, `quiz.motion` and `quiz.gfx`, works at
any size (9:16 Shorts and 16:9 TV), and takes its geometry from the surface it draws to.

Rule for every cut-away: **cover in the dead tail of the outgoing state, uncover in the
first few hundred ms of the incoming state.** No state duration, timer or answer window
changes.

## 1. The flow of a match

```
LOBBY --(match open: LQ ring iris)--> INTRO --> BUILDUP Q1 --> ASKING --> LOCKING --> REVEALING
  --> BUILDUP Qn+1 --> ASKING ... REVEALING Q10 --(final curtain)--> PODIUM --(next-match ribbon)--> LOBBY
```

`GameState.BUILDUP` (game loop, `docs/game-modes.md`) opens every question: 4 s
(`BUILDUP_TIME`), 6 s before the final and a difficulty step-up. **The build-up IS the
question transition.** Its cover closes over the previous screen when BUILDUP starts, the
build-up card plays on the cover, and the cover opens onto the question when ASKING starts.
There is no separate question bumper, so there is never a double transition.

The question is already served at BUILDUP entry, and answers count only from ASKING. So both
layouts freeze the last frame of the state before (one `screen.copy()` per question) and
the cover closes over that frame. The new options are never drawn during BUILDUP.
`tests/test_render.py` guards the button painters during BUILDUP, and a planted mutant fails
the test.

## 2. Cover styles (rotated by context)

`STYLES` = style -> (seconds to cover, seconds to uncover). `pick_style(n, event, match_no, last)`:

| Context | Style | Look |
|---|---|---|
| Q1, and Q6 out of halftime | `iris` | the LQ logo ring closes like a camera iris, then winds up and the camera pushes through it |
| Lightning (alternates in a Speed match) | `slash` | a sky-blue diagonal cut, then a bolt strike across the card |
| Final (Q10) | `spotlight` | lights out to night, a searching spotlight finds the numeral, then opens as a gold-rimmed circle |
| Others | `bands`, `doors`, `slats`, `tiles` | in rotation by question and match number, never the same style twice in a row |
| Halftime, next match | `ribbon` | the four answer colours sweep the screen as one ribbon |

The four-colour vocabulary is the brand's answer order: pink, blue, orange, teal.

## 3. The build-up card (from `logic.buildup` alone)

Keys: `q_no, of, tier, stakes, kind, event, headline, subline, spotlight, intensity`.
`Transitions.buildup_info` fills every gap, so a sparse or odd dict still draws (tested with
full, sparse and malformed dicts in every style, at both sizes).

Beats, in seconds into BUILDUP:

| t | |
|---|---|
| 0 to 0.5 | cover closes; the headline (event colour) and the previous numeral ride in |
| ~0.6 | the numeral rolls like an odometer to this question; the match pips light the new one |
| 1.2 (`T_STAKES`, on the "stakes" sound hit) | FOR N POINTS slams in (shake and ring in proportion to intensity) |
| then | the tier ladder lights rung by rung to this tier (easy, medium, hard, expert), the subline types in, the spotlight finds its player's name plate, and a four-colour fuse burns to the question |
| ASKING 0 | uncover |

**Intensity** (0.15 at Q1, 1.0 at the final) scales the drama: the background darkens from
violet to night, a light pool and heartbeat rings grow behind the numeral, floating shapes
thin out above 0.3 and stop above 0.55. `logic.buildup_intensity` also makes the ASKING
timer glow breathe harder.

Portrait stacks everything in one column inside the Shorts safe zone (y 190 to 1500).
Landscape puts the numeral on the left and the rest on the right.

## 4. Signature brand moments

- **Match open (LOBBY to INTRO):** the LQ ring closes over the lobby as an iris, the logo,
  wordmark and the tag "LIVE · MATCH N · <FORMAT>" (format label in its `special.FORMATS`
  colour, rule underneath) rise, then the ring winds up and the camera pushes through it with
  a burst of the answer shapes. The INTRO repeats the format as a chip beside the category,
  with its rule under the ring, for 4 s.
- **Halftime (REVEALING Q5):** the ribbon sweeps the reveal from 3.9 s, then the gold
  HALFTIME over a quiet ring watermark and the top 5 standings bars.
- **Final question:** the spotlight style (above).
- **Winner (REVEALING Q10 to PODIUM):** violet panels drop centre-out with a gold fringe and
  a searching spotlight pool over "AND THE WINNER IS...", then lift in a stepped podium shape.

## 5. Announcements (toasts)

Every `logic._push_event(text, color, badge)` toast uses one broadcast tab: a badge block
in the event colour (a glyph for known codes in `BADGE_GLYPHS`, else the code), a dark panel
that unrolls out of it, a light sweep, and a fuse that burns down its 3.6 s life. A new toast
rolls the old one up first. **Text written as "KICKER: rest" or "KICKER! rest" with an
all-caps kicker prints the kicker in the event colour.** New features get a headline just by
how they word the event.

## 6. Feature kit (game loop 2)

One look for every mode. Each element is a glass pod with a tracked caps label, a display
value and a segment meter, or a pill tag. Each is composed once per value and blitted once
per frame.

| Feature | Where | Reads |
|---|---|---|
| Format chip | chip row (non-classic), intro, match open | `match_format`, `special.FORMATS` |
| Stakes and tier ladder | right pod beside the timer | `question_stakes()`, `q.difficulty` (expert adds a 4th rung) |
| Survivor counter | left pod (survivors) | `perfect` |
| Gold vs Teal bar | left pod (teams) | `team_scores()`, `special.TEAMS` |
| Community goal | left pod (classic, speed) | `community_goal`, `community_correct`, `community_jackpot` |
| Combo step meter | fastest-right rows in the reveal | `Player.streak`, `config.COMBO_STEPS` |
| x2 and 50:50 tags | locked-in list | `double_picks`, `half_picks` |
| Payout card, team-win card | podium, 4.4 to 8.2 s (the ladder follows) | `match_stats["survivors"]`, `match_stats["team"]` |

The pods sit under the timer and the TIME'S UP band, and are skipped when a long question
leaves less than 112 px beside the ring. The TV layout (`quiz/ui.py`) has none of the kit
yet. It draws every state without crashing.

## 7. CPU

Rules: no per-frame `set_alpha` on per-pixel-alpha surfaces (pygame's slow path, about 4x).
Fades use `gfx.faded` (alpha baked, quantised, cached). Glows are opaque light added with
`BLEND_RGB_ADD`. Nothing smoothscales or blurs a large surface per frame. While a cut-away
fully covers the screen, the UI skips drawing the state underneath.

- `gfx.edge_glow` (the urgency and LOCKING edge light): ADD blits of three cached strip sets
  chosen by bit. 0.24 ms, against 1.6 ms for the alpha strips it replaces.
- Podium sunburst: opaque polygons on a black scratch surface, ADDed. 0.8 ms, against 3.2 ms
  for 24 gfxdraw alpha polygons.
- Option shadows composed with their faces; timer, flare, lobby and intro glows faded and
  cached.

`ui.draw`, Shorts layout, one whole match (15,273 frames, 30 fps fake clock, harness
`render.py`). Runs alternated back to back on this shared PC. Before = 31da909
(feature/matches), after = this branch:

| ms | before p50 / p95 | after p50 / p95 |
|---|---|---|
| all frames | 4.64-4.93 / 8.67-8.98 | 3.72-4.34 / 6.00-7.47 |
| LOBBY | 3.29-3.66 / 6.10-6.80 | 2.52-2.67 / 4.74-6.08 |
| INTRO | 4.91-5.40 / 5.92-7.72 | 3.41-3.52 / 5.84-6.62 |
| BUILDUP | 1.87-2.12 / 2.82-4.36 (placeholder) | 1.92-2.10 / 3.83-4.11 (full card) |
| ASKING | 4.53-4.79 / 7.48-8.02 | 3.78-4.32 / 5.27-6.15 |
| LOCKING | 7.43-7.46 / 8.98-9.49 | 4.28-5.27 / 6.22-7.43 |
| REVEALING | 7.13-7.23 / 9.87-9.96 | 4.77-5.50 / 6.75-8.40 |
| PODIUM | 8.48-8.54 / 10.50-10.51 | 4.93-8.04 / 8.78-11.39 |

## 8. Wiring

`UIManager.__init__` creates `self.fx = Transitions(self.fonts)`. Both `draw` methods call
`self.fx.cue(logic, now)` each frame, skip the state underneath while `self.fx.covered(now)`,
and call `self.fx.draw(self.screen, now)` before the confetti. `cue()` starts the build-up
when BUILDUP starts. It pre-rolls the match open (last 1.5 s of LOBBY), the final curtain
(last 1.6 s of REVEALING Q10) and the next-match ribbon (end of PODIUM). It anchors each
uncover to the next state's `state_start_time`. If the state is left any other way (the skip
key), nothing uncovers and the cut stays hard. `fx.cover(screen, style, p)` draws one style
on its own; the halftime card uses it.

## 9. Follow-ups

- The TV layout has no feature kit and keeps its rail; port the pods if TV goes live.
- Closest Call (number) and Double Down need their own reveal (number line, stake chips).
