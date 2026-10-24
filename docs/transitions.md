# Transitions and cutscenes

Goal: make the show move like HQ Trivia (flat violet stage, bold white type, flat circles,
rings, crosses and hex nuts in the answer colours) without hiding anything players need.
Prototype: `quiz/transitions.py`. It does not depend on `quiz/ui.py`, works at any size
(16:9 TV and 9:16 Shorts), and has not been wired in yet.

## 1. Audit of the current motion (quiz/ui.py, quiz/ui_vertical.py)

**Always moving (ambient):** the background is pre-rendered. Two 820 px spotlights drift
across it (additive blits), with 16 flat floaters and 45 dust motes. Small pulses: the live
dot and the current match pip. The host caption types out with "voice" bars.

**Moves on entry, then static:**

| State | What animates | Then |
|---|---|---|
| LOBBY | countdown pop in the last 10 s, vote cards ease-out-back, vote bars ease toward their share, social panels slide up | static apart from the bars |
| INTRO (4 s) | shine sweep, "MATCH N" scales 2.4x to 1x (smoothscale every frame), category slides, 3-2-1 pops | it is the only real sting |
| ASKING | question lines fade up (staggered), options pop (scale 0.85 to 1, 0.25 to 0.9 s), lock-ins slide into the rail | ring timer; heartbeat ring and red vignette in the last 5 s |
| LOCKING | "TIME'S UP" stamp slams in (rotozoom every frame), jitter, yellow vignette, lock bar | options snap to dimmed in one frame |
| REVEALING | answer split counts up, the correct card lifts, outline and ring burst at 1.1 s, confetti, the "knew it" panel slides in at 1.5 s, fastest-right rows pop | **nothing moves from about 2 s to 8 s** |
| PODIUM | title fades, bars rise (staggered ease-out-back), avatars drop, crown, confetti, stat cards slide | static after about 2.6 s |

**Hard cuts (one frame, whole layout swapped):**

1. **LOBBY to INTRO.** The header, vote cards and rail vanish together. This is the show
   opening, and it has no open.
2. **REVEALING to ASKING.** It happens 9 times per match. The whole screen swaps to the next
   question with no announcement of the question number. Lightning and bonus rounds only get
   a toast and a pill.
3. **LOCKING to REVEALING.** The worst jump. The question block shrinks, the options jump up
   about 100 px and shrink from 190 to 160 px, and the rail swaps panels.
4. **REVEALING to PODIUM.** The climax arrives as a plain cut.
5. **PODIUM to LOBBY.** A cut, but a low-attention moment.

Budget observations (not fixed here): the stamp rotozoom and the intro smoothscale allocate
a surface every frame, and `_draw_option` with scale makes a new cache entry per size while
it pops in. On this PC `ui.draw` itself costs 3 to 9 ms per frame on average, with spikes of
15 to 30 ms on the first frame of a new state (text cache misses).

## 2. Concepts (ranked)

Every concept follows one rule: **cover in the dead tail of the outgoing state, uncover in
the first few hundred ms of the incoming state**, while that state's own entry animation plays
underneath. No state duration, timer or answer window changes. The logic's `"whoosh"` (queued
on every state change) lands on the uncover.

### 1. Question bumper "QUESTION 3 -> 4" (REVEALING to ASKING). BUILT

Four answer-colour bands (pink, blue, orange, teal, in answer order) lead a flat violet curtain
across the screen. On TV it moves left to right, slanted like the stage stripes. On Shorts it
moves bottom to top, the "swipe up to next" gesture. On the curtain, "QUESTION" sits over a
huge numeral that rolls like an odometer from the last number to this one. The match pips
(green and red history) light the new one, and "OF 10 · EASY" rises from a mask. Event
variants: LIGHTNING ROUND (sky blue, bolt badge, "12 SECONDS · 1.5x POINTS"), FINAL QUESTION
(gold, x2 badge), BONUS ROUND (purple). The curtain then leaves the same way, uncovering the
new question.

| t (ms, 0 = state change) | |
|---|---|
| -1100 (-1500 for event rounds) | bands enter, curtain follows (460 ms, in-out cubic, bands lead by 22 ms each) |
| -640 | screen covered; the old numeral arrives printed on the curtain, and riders bob |
| -620 to -320 | numeral rolls to the new number (out-back), pip lights; event rounds hold 400 ms longer first |
| -520 to -240 | sub line rises; event badge pops |
| 0 to +400 | the curtain leaves, card and riders riding it, bands trailing (they clear by +490) |

- **Reuses:** answer colours, pips and their done/miss data, the floater shape vocabulary,
  and the stage-stripe slant.
- **Fit:** it covers the last 1.1 s (1.5 s) of an 8 s reveal. The fact panel has been up for
  4.6 s or more by then. In ASKING, the TV slant uncovers the question text (top left) first,
  by about 250 ms. On Shorts the bottom clears first and the question by about 400 ms. Both are
  inside the existing 0.9 s option pop-in.
- **Trade-off:** stream viewers see the question up to 0.25 to 0.4 s after phone-page players.
  That is small next to stream latency, and it is the same for everyone in chat.
- **Cost:** 5 polygons, 8 shape riders, 4 or 5 cached text blits.

### 2. Match open: colour iris, logo flash, shape burst (LOBBY to INTRO). BUILT

Pink, blue, orange, teal, then violet discs swell from the centre and swallow the lobby. On
violet, the four answer shapes pop in a row and the justified lockup "THE LIFELONG / QUIZ"
rises. "• LIVE · MATCH N" follows, and a dotted orbit draws on (the HQ intro's dotted circle).
The logo sinks. At the state change the colours open again as rings, and the answer shapes
plus 30 HQ shapes burst outward over the existing "MATCH N" sting.

| t (ms) | |
|---|---|
| -1500 to -940 | five discs, 50 ms stagger, 360 ms in-cubic each |
| -1010 to -600 | orbit draws, shapes pop (60 ms stagger), lockup rises line by line |
| -200 to 0 | logo sinks into its baseline mask |
| 0 to +730 | violet, teal, orange, blue and pink open in turn (out-quad, 45 ms lag), then the hole; the burst flies (exponential drag) and shrinks away by +1000 |

- **Fit:** the cover holds the lobby's last 1.5 s of 30 s, while the countdown reads 0:02 to
  0:00. Votes still count until expiry, since the logic is untouched. The INTRO's 3-2-1 starts
  at 1.0 s, after the burst has left the centre.
- **Cost:** while the iris is still growing, each colour is drawn as a ring rather than a full
  disc, and once it covers the screen it is a single `fill`; plus about 34 small shapes.

### 3. Final curtain "AND THE WINNER IS..." (REVEALING Q10 to PODIUM). BUILT

Violet stage panels (9 on TV, 5 on Shorts) drop from the centre outward. Each has a gold
fringe and a small bounce. "MATCH N · CATEGORY" sits over "AND THE WINNER IS", on one line on
TV and stacked three lines on Shorts. Three gold dots tick in like a drumroll. At the state
change the panels fly up from the centre outward. The stepped lift forms a podium silhouette
that frames the real podium rising underneath, and the text rides the first panels so it never
sits over the podium.

| t (ms) | |
|---|---|
| -1600 to -1010 | panels drop (440 ms, out-back 1.1, 50 ms stagger centre-out) |
| -1110 to -720 | big line rises, then the match line |
| -810 to -260 | three dots pop (out-back 2.4) |
| 0 to +450 | panels lift (340 ms in-cubic, 35 ms stagger) |

- **Fit:** it covers the last 1.6 s of the final reveal. The answer, split and fastest-right
  rows have been up for more than 4 s. The podium's own bars start at 0.3 s.
- **Suspense:** the podium is not computed until the state change, so the card cannot spoil it.
- **Cost:** about 20 rects, 6 riders, 3 dots, and 3 or 4 cached text blits.

### 4. Reveal shutter (LOCKING to REVEALING). Not built

Four answer-colour bars slam closed in the last 180 ms of LOCKING and open over the first
260 ms of REVEALING, hiding the layout jump (cut 3). Cost is under 0.5 ms. Ranked below the
top three: the moment of truth wants immediacy, and two cut-aways per question risks
fatigue. A cheaper fix for the same cut is to animate the layout change in ui.py: tween the
option rects from the ASKING positions to the REVEALING ones over 300 ms.

### 5. Halftime standings (end of REVEALING Q5, about 2.4 s). Not built

A cutscene with information: the top 5 match standings slide in as bars, with overtakes
marked. It uses 2.4 s of the reveal's dead time. Ranked lower because it duplicates the rail
standings on TV and needs its own data design. It is the most useful idea for Shorts, which
has no rail.

### 6. Next-match sweep (PODIUM to LOBBY). Not built

Reuse concept 1's wipe with a "NEXT MATCH · VOTE NOW" card. Almost free to add, but the lobby
is a low-attention moment.

**Top 3 = 1, 2 and 3. They run 11 times per match: 9 question bumpers, 1 open, 1 final.**

## 3. CPU

All drawing is flat polygons, circles and rects straight onto the screen, plus pre-rendered,
tight-cropped text. There is no per-frame full-screen alpha, no smoothscale and no rotozoom.
Text is built once per transition on its first frame, for the size of the target surface, and
cached.

Measured by `fx.draw` alone on this PC (Windows, pygame 2.6.1, 30 fps fake clock, real
QuizLogic, with the real UI underneath):

| | 1920x1080 mean / p95 | 1080x1920 mean / p95 | first frame incl. build |
|---|---|---|---|
| question | 1.35 / 2.15 ms | 1.43 / 2.21 ms | 2.4 to 5.1 ms |
| match_open | 0.64 / 1.09 ms | 0.59 / 1.03 ms | 3.3 to 3.6 ms |
| final | 1.58 / 2.19 ms | 1.55 / 2.15 ms | 1.8 to 3.0 ms |
| reference: one full-screen opaque blit | 0.58 ms | 0.85 ms | |

Single-frame maxima of 4 to 9 ms appeared now and then. They did not repeat across passes, and
this PC was busy with other sessions. Assume a 2 vCPU cloud core is about 2x slower: about
3 ms per frame on average and under 5 ms at p95, against the 20 ms budget.

`covered(now)` reports when the screen is fully covered. The UI can then skip drawing the
state underneath for those frames (0.5 to 1.0 s per transition), which saves its 3 to 9 ms
per frame.

## 4. Wiring (exact)

`quiz/transitions.py` imports only `quiz.config` and `quiz.models`, so `quiz/ui.py` can import
it with no cycle. `VerticalUI` subclasses `UIManager`, so both get it.

```python
# quiz/ui.py, imports
from quiz.transitions import Transitions

# UIManager.__init__, after self.fonts = Fonts()
self.fx = Transitions(self.fonts)

# UIManager.draw AND VerticalUI.draw, right after `age = now - self._state_enter`
self.fx.cue(logic, now)
# optional saving while the cut-away fully covers the screen:
# if self.fx.covered(now): skip _draw_stage / the state branch / header / footer

# both draw methods, immediately before `self._draw_confetti(dt)`
self.fx.draw(self.screen, now)
```

`cue()` does the triggering itself:

| Outgoing state | Starts when | Plays | Anchors to |
|---|---|---|---|
| LOBBY | `time_remaining <= 1.5` | `match_open` | INTRO's `state_start_time` |
| REVEALING, `q_index < 10` | `time_remaining <= 1.1` (1.5 if the next question is 5, 3, 7 or 10) | `question` with n, event, difficulty, pips | ASKING's `state_start_time` |
| REVEALING, `q_index == 10` | `time_remaining <= 1.6` | `final` with match no and category | PODIUM's `state_start_time` |

If the pre-roll never happened (the F1 skip key), nothing plays and the cut stays hard, as
today. Confetti draws over the curtains on purpose. Manual use:
`fx.start("question", now, n=4, event="", difficulty="medium", pips=[...])` plays a full
cut-away from `now`.

## 5. Shorts (9:16) specifics

- Geometry comes from `screen.get_size()` on every draw and is laid out once per size. There
  are no `SCREEN_WIDTH`/`SCREEN_HEIGHT` constants. Tested at 1920x1080, 1080x1920, 1280x720
  and 720x1280.
- Cards centre on the Shorts safe zone. They stay below the top 180 px and above the bottom
  320 px, and also clear `ui_vertical.SAFE_BOTTOM = 1500`: the lowest element, the question
  pips, ends at about y = 1300. Decorative shapes may sit in the overlay zones.
- The type is bigger and stacked: the numeral is 620 px, "AND THE / WINNER / IS..." runs on
  three lines, and the lockup is a justified block. Lines that might overflow are fitted to the
  width.

## 6. Follow-ups

- Move the `"whoosh"` to the cover start, or add a short pre-roll riser, so the sound follows
  the picture into each cut-away.
- Fix cut 3 inside ui.py by tweening the option rects (see concept 4).
- Build concept 5 (halftime standings) for Shorts.
