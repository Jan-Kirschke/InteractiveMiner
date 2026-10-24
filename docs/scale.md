# Scale: what the quiz carries today, and what comes next

Measured with `tools/loadtest.py` (the real controller loop, headless, fake clock, vertical
layout) on the development PC, not on the CPX22. The server numbers are the operator's: python
64% of one core, ffmpeg 55%, pulseaudio 9%, 29-30 fps out, python RSS 237 MB. The PC is faster:
the same show there costs 38% of a core before these changes.

## Real time, 1,000 players, 50 msgs/s (`--pace`, 120 s)

| | Before | After |
|---|---|---|
| Whole process CPU | 38% of a core | 34% |
| Game thread CPU per frame | 12.6 ms | 5.8 ms |
| Game thread busy p50 / p95 / p99 | 12.9 / 20.1 / 38.3 ms | 5.6 / 10.8 / 16.2 ms |
| Frames over 33 ms | 52 of 3,600 | 8 |

The total barely drops; the game thread halves, because the stream frame conversion moved to
the second core. That is headroom for the loop, not a cheaper show.

With the visual overhaul merged (`feature/matches` 40556ff), the same run costs 41% of a core.
The game thread uses 6.8 ms CPU per frame, and render is 5.5 ms p50, 9.3 ms p95 (one full
match, 60 players answering). The server went from 64% to 71% with that deploy, the same
direction.

## UI hot paths (new UI, per frame, measured; not changed here)

| Where | Cost | What |
|---|---|---|
| `quiz/ui_vertical.py:246` `_v_stage` | 1.9 ms, 37 blits | background, light and particles, every frame |
| `quiz/ui_vertical.py:451` `_v_question` | 2.6 ms incl. children | question card, options |
| `quiz/ui_vertical.py:443` `_btn_shadow` | 0.7 ms, 3.3 blits | option shadows, redrawn every frame |
| `quiz/ui.py:902` `_draw_vignette` | 0.5 ms, one full-screen blit | edge vignette |
| `quiz/ui_vertical.py:514` `_v_timer` | 0.8 ms | ring timer |
| `quiz/ui_vertical.py:614` `_v_reveal` | 0.85 ms | while the reveal is shown |

Blits are 4.9 of the 6.1 ms. The cheapest wins would be one pre-composited static stage layer
and cached option shadows.

## Where the game thread's time went, and where it goes now

| Step | Before | After |
|---|---|---|
| smoothscale 1080x1920 to 720x1280 for FFmpeg | 7.3 ms per frame | converter thread (releases the GIL) |
| Repack to RGB for the pipe | 3.2 ms, holds the GIL | 0.9 ms buffer copy, `-pix_fmt bgr0` |
| Question-bank COUNT (OTDB top-up check) | 0.25-0.5 ms every frame | once per second |
| DB save | on the game thread: 10 ms at 1k players, 154 ms at 10k, 1.7 s at 50k | db-writer thread |
| Weekly ladder (lobby, podium, cards, `!rank`) | 0.4 ms at 1k, 5.3 ms at 10k, 79 ms at 50k per call | rebuilt only when points change |
| `@name` lookup (`!duel`) | 3 ms average at 50k | dict lookup |
| UI render | 5.5 ms p50, 9.6 ms p95 | unchanged (not in this change) |

FFmpeg's CPU is the same for `bgr0` and `rgb24` input (libx264 veryfast, 450 frames), and the
YUV it encodes is byte-identical.

## Where it breaks (`--matrix`, 120 s per cell; busy = game thread working)

| Players | msgs/s | Busy p95 before -> after | Frames over 33 ms | Game thread CPU/frame |
|---|---|---|---|---|
| 1,000 | 50 | 27.4 -> 8.3 ms | 81 -> 1 | 17.1 -> 4.4 ms |
| 1,000 | 2,000 | 40.1 -> 12.5 ms | 377 -> 2 | 19.9 -> 6.6 ms |
| 10,000 | 500 | 78.6 -> 11.2 ms | 1,209 -> 2 | 25.3 -> 6.0 ms |
| 50,000 | 50 | 90.4 -> 9.0 ms | 1,472 -> 5 | 32.2 -> 5.0 ms |
| 50,000 | 500 | 148.8 -> 17.7 ms | 2,172 -> 20 | 50.8 -> 8.6 ms |
| 50,000 | 2,000 | 200.0 -> 44.9 ms | 3,216 -> 703 | 90.2 -> 21.5 ms |

Before, the show broke at 10k players (lobby and podium frames, every `!rank`). Now it holds
50k players at 500 msgs/s, and breaks at 50k with 2,000 msgs/s. The cause there is `!crew`
(2% of the synthetic chat): 2-4 ms each, O(players).

## Per message at 50k players (game thread)

| Message | Before | After |
|---|---|---|
| answer `1`-`4` | 2.3 us | 2.6 us |
| `!rank` | 25.8 ms | 0.09 ms |
| `!crew <name>` | 4.0-4.5 ms | 2.1-2.2 ms (still scans all players) |
| chat thread: JSON parse + normalise | 16-36 us | same |

Once per question start, `_update_participation_streaks` walks every player: 0.4 ms at 1k,
1.5 ms at 10k, 5-7 ms at 50k.

## Ceilings, in the order they will be hit

1. **The CPX22's two cores.** FFmpeg (~55%), pulseaudio (~9%) and every Python thread share
   them. The game loop now has room; the box saturates first. Watch the `[Broadcast] Health`
   line: "fps from the game" below 29, or stalls above 0.
2. **Commands that scan all players.** `!crew` at 50k players: 3-5 in one frame overrun it.
3. **SQLite writes.** Off the game thread. One save of 42k rows took 1.9 s on the writer. It
   becomes a limit when a save takes longer than the 10 s save interval.
4. **Memory.** The UI caches are capped by entry count, not bytes. Measured: the text cache
   up to 370 MB (2,923 entries), the surface cache up to 150 MB (724 entries). RSS rises with
   chat volume to about 770 MB at 2,000 msgs/s. That is bounded, not a leak.
   Soak on the merged new UI (1k players, 50 msgs/s, 2.9 h of show time, 24 matches, fake
   clock): RSS 743 MB after 4 min, then +145 MB in hour 1, +33 MB in hour 2, +23 MB in hour 3
   (944 MB at the end). The Python heap grew 3.7 MB after warm-up (tracemalloc; the converter's
   frame buffer), threads stayed at 3, USER objects at 3. The growth is native surface memory
   in the UI caches filling towards their entry caps, and it is flattening. In a 200 s run the
   new `quiz/gfx.py` cache already held 145 MB and the text cache 115 MB. The server should
   level out near 900 MB to 1 GB over a 3 h show, so watch it against the 1 GB trigger below.
5. **One YouTube chat's message rate.** Not measured (no source read). The chat reader logs
   `[Chat] Status: connected, N messages received total` every 60 s. The difference per minute
   is the real rate. At 2,000 msgs/s the reader costs 3-7% of a core and the game thread 1-3%.

## Next steps and their triggers

Line numbers are those of `feature/matches` at 40556ff (merged).

| Trigger (measure on the server) | Step |
|---|---|
| Players in the DB > 10k, or `!crew` bursts in the log | Crew index in `quiz/db.py` plus two lines in `_cmd_crew` (`quiz/logic.py:1065`, the scan at `:1083`) |
| Players > 30k | Track the players who have a participation streak instead of walking all of them (`quiz/logic.py:773`) |
| python RSS > 1 GB | Byte-bounded UI caches: text cache cap at `quiz/ui.py:302` and `:318`, surface cache at `:289`, the new `quiz/gfx.py:31` cache (900 entries) |
| Health line under 29 fps from the game | Profile the UI (`tools/loadtest.py --profile`): it is now the largest game-thread cost |
| One save takes longer than 8 s | Write only changed columns, or save the players of one question at its reveal |
| Sustained > 5,000 msgs/s (several chats merged) | Chat intake (poll, parse, keep `1`-`4` and commands) in its own process |

Not built now, because no measurement needs it today: a separate intake process, a second
database, byte budgets for the UI caches.

## Measure it yourself

```
python tools/loadtest.py --players 1000 --rate 50 --seconds 120 --pace   # real time, CPU like production
python tools/loadtest.py --matrix --out after.json                       # the N x M grid, one worker
python tools/loadtest.py --compare before.json after.json
```
`cpu_ms_per_frame` x 3 is the percent of one core at 30 fps.
