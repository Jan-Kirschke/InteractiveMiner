"""Load harness for The Lifelong Quiz: the real controller loop, headless, on a fake clock.

One scenario = N players in the database, M chat messages per second from them, S simulated
seconds of show. Every frame runs the same steps in the same order as MainGameController.run()
(chat -> logic -> saves -> sounds -> render -> frame conversion for FFmpeg), each step timed.

    python tools/loadtest.py --players 1000 --rate 50 --seconds 360
    python tools/loadtest.py --matrix --out before.json            # the N x M grid, one process each
    python tools/loadtest.py --compare before.json after.json      # before/after table
    python tools/loadtest.py --players 1000 --rate 50 --seconds 10800 --render-every 10   # 3 h soak
    python tools/loadtest.py --players 10000 --rate 500 --seconds 120 --profile out.prof --sample

Offline by construction: SDL dummy drivers, no OTDB (quiz.logic.requests = None), no FFmpeg
process (only the in-loop frame conversion is measured), a throwaway SQLite file.
"""

from __future__ import annotations

import argparse
import array
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYERS = (10, 1_000, 10_000, 50_000)
RATES = (1, 50, 500, 2_000)
BUDGET_MS = 1000 / 30


def _rss_mb() -> float:
    """Resident set size of this process in MB (Linux /proc, Windows psapi)."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except OSError:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return pmc.WorkingSetSize / 1e6
    except Exception:
        return 0.0


def _user_objects() -> int:
    """Windows USER handles held by this process (GetGuiResources flag 1); -1 elsewhere."""
    try:
        import ctypes
        from ctypes import wintypes
        k32, u32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        u32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        return u32.GetGuiResources(k32.GetCurrentProcess(), 1)
    except Exception:
        return -1


def _init_without_joystick():
    """Every pygame.init() in this process starts only display and font, whatever the code
    under test does (older trees call pygame.init()): the joystick subsystem leaks ~100 USER
    objects per second under the dummy driver on Windows, and quitting it after init leaves
    device events that make pygame.event.get() raise KeyError."""
    import pygame

    def init():
        pygame.display.init()
        pygame.font.init()
        return (2, 0)
    pygame.init = init


def _pct(values, *ps):
    if not values:
        return {f"p{p}": 0.0 for p in ps} | {"max": 0.0}
    s = sorted(values)
    out = {f"p{p}": s[min(len(s) - 1, int(len(s) * p / 100))] for p in ps}
    out["max"] = s[-1]
    return out


def _seed_players(db_path: str, n: int, week: str, day: str, rng: random.Random):
    """N existing players with this week's points, a few crews, a day streak."""
    import sqlite3
    from quiz.db import QuizDatabase
    QuizDatabase(db_path).close()  # creates the schema exactly as the game does
    conn = sqlite3.connect(db_path)
    crews = [f"Crew {i}" for i in range(max(1, n // 250))]
    rows = []
    for i in range(n):
        score = rng.randint(0, 50_000)
        rows.append((f"viewer_{i:05d}", score, 0, rng.randint(0, 20), "Bronze", rng.randint(0, 500),
                     rng.randint(0, 300), rng.randint(0, 200), 0, rng.randint(0, 5), 0, time.time(),
                     rng.randint(0, 5_000), week, rng.randint(0, 9), day,
                     rng.choice(crews) if rng.random() < 0.3 else "", 0, 0))
    conn.executemany(
        "INSERT OR REPLACE INTO players (username, score, streak, best_streak, rank, games_played,"
        " correct_answers, wrong_answers, wrong_streak, participation_streak, streak_shield, last_seen,"
        " weekly_score, week, day_streak, last_day, crew, duel_wins, duel_losses)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _message_text(rng: random.Random, n_players: int) -> str:
    r = rng.random()
    if r < 0.80:
        return str(rng.randint(1, 4))
    if r < 0.86:
        return rng.choice(["lol", "this is hard", "gg", "hi from berlin", "2nd place again"])
    if r < 0.90:
        return rng.choice(["!ready", "!join"])
    if r < 0.93:
        return rng.choice(["!rank", "!score", "!me"])
    if r < 0.95:
        return "!card"
    if r < 0.97:
        return "!crew " + rng.choice(["Night Owls", "Kaffee Klatsch", "Brainrot Busters"])
    if r < 0.98:
        return f"!duel @viewer_{rng.randrange(n_players):05d}"
    return "!accept"


class Sampler(threading.Thread):
    """Statistical profiler: samples the main thread's stack every `interval` seconds."""

    def __init__(self, interval=0.001):
        super().__init__(daemon=True)
        self.interval, self.main = interval, threading.main_thread().ident
        self.self_counts, self.incl_counts, self.n = {}, {}, 0
        self.on = True

    def run(self):
        while self.on:
            frame = sys._current_frames().get(self.main)
            if frame is not None:
                self.n += 1
                seen, leaf = set(), True
                while frame is not None:
                    code = frame.f_code
                    key = f"{Path(code.co_filename).name}:{code.co_name}"
                    if leaf:
                        self.self_counts[key] = self.self_counts.get(key, 0) + 1
                        leaf = False
                    if key not in seen:
                        seen.add(key)
                        self.incl_counts[key] = self.incl_counts.get(key, 0) + 1
                    frame = frame.f_back
            time.sleep(self.interval)

    def top(self, k=25):
        n = max(1, self.n)
        fmt = lambda d: [(name, round(100 * c / n, 1)) for name, c in sorted(d.items(), key=lambda x: -x[1])[:k]]
        return {"samples": self.n, "self_pct": fmt(self.self_counts), "inclusive_pct": fmt(self.incl_counts)}


def run_scenario(players: int, rate: float, seconds: float, render_every: int = 1, seed: int = 1,
                 profile: str = "", sample: bool = False, mem_every: float = 60.0,
                 pace_real_time: bool = False, trace: bool = False) -> dict:
    os.environ.update({"QUIZ_LAYOUT": "vertical", "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
                       "QUIZ_FPS": "30", "QUIZ_STREAM_HEIGHT": "720"})
    sys.path.insert(0, str(ROOT))
    rng = random.Random(seed)
    random.seed(seed)

    real_time = time.time
    clock = [real_time()]
    time.time = lambda: clock[0]          # every quiz module reads time.time(): one fake clock for all
    _init_without_joystick()              # also for older trees whose controller lacks the fix

    from quiz.models import utc_day, utc_week, ChatMessage
    tmp = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp.name, "load.db")
    _seed_players(db_path, players, utc_week(), utc_day(), rng)

    import quiz.logic as L
    L.requests = None
    import quiz.controller as C
    from quiz.chat import _PUNCTUATION_RE
    C.DB_PATH_OFFLINE = db_path
    ctrl = C.MainGameController(offline=True)
    ctrl.broadcaster._active = True       # send_frame converts as when streaming; no FFmpeg, no writer thread

    # DB saves: the commit itself, wherever it runs (writer thread now, the game thread before);
    # the game thread's share shows in the "save" phase.
    saves = []
    if hasattr(ctrl.db, "_write_rows"):
        _write_rows = ctrl.db._write_rows

        def timed_write(conn, rows):
            t0 = time.perf_counter()
            _write_rows(conn, rows)
            saves.append(((time.perf_counter() - t0) * 1000, len(rows)))
        ctrl.db._write_rows = timed_write
    else:
        _save_all = ctrl.db.save_all

        def timed_save():
            rows = len(ctrl.db._dirty)
            t0 = time.perf_counter()
            _save_all()
            if rows:
                saves.append(((time.perf_counter() - t0) * 1000, rows))
        ctrl.db.save_all = timed_save

    # Steady state only: the sounds render on a background thread at start-up (numpy, holds the GIL
    # in bursts), so wait for them; the clock stays frozen meanwhile, the game has not started yet.
    deadline = real_time() + 120
    while not ctrl.sounds.music_ready and ctrl.sounds._enabled and real_time() < deadline:
        time.sleep(0.2)

    names = [f"viewer_{i:05d}" for i in range(players)]
    fps = 30
    frames = int(seconds * fps)
    phases = ("chat", "logic", "save", "sounds", "wait", "render", "convert", "busy", "total")
    wait_frame = getattr(ctrl.broadcaster, "wait_frame", lambda *a: True)  # older code converts in-loop
    pace = 1 / fps if pace_real_time else 0.0
    times = {p: array.array("f") for p in phases}   # 4 bytes a frame: a 3 h soak must not grow from its own log
    msgs_done, owed, chat_us = 0, 0.0, array.array("f")
    snap0 = None
    mem, next_mem, user_obj = [], 0.0, [_user_objects()]
    threads_start = threading.active_count()
    sampler = Sampler() if sample else None
    prof = None
    if profile:
        import cProfile
        prof = cProfile.Profile()
    if sampler:
        sampler.start()
    if prof:
        prof.enable()
    began_wall = real_time()
    cpu0, main_cpu0 = time.process_time(), time.thread_time()
    pc = time.perf_counter
    next_tick = pc()
    for f in range(frames):
        if pace:  # like clock.tick(30): the converter and writer threads get the idle time
            next_tick += pace
            delay = next_tick - pc()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = pc()
        clock[0] += 1 / fps
        owed += rate / fps
        while owed >= 1:
            owed -= 1
            raw = _message_text(rng, players)
            ctrl.msg_queue.put(ChatMessage(names[rng.randrange(players)],
                                           _PUNCTUATION_RE.sub("", raw).strip().lower(), clock[0], raw=raw))
        queued = ctrl.msg_queue.qsize()
        t0 = pc()
        ctrl._handle_events()
        ctrl._process_chat()
        t1 = pc()
        ctrl.logic.update(1 / fps)
        t2 = pc()
        ctrl._save_on_state_change()
        t3 = pc()
        ctrl._play_sounds()
        ctrl._start_music_when_ready()
        t4 = pc()
        if f % render_every == 0:
            wait_frame()  # _render() does this first; timed apart so render is drawing only
            tw = pc()
            ctrl._render()
        else:
            tw = pc()
        t5 = pc()
        ctrl._broadcast_frame() if f % render_every == 0 else None
        t6 = pc()
        ctrl._periodic_save()
        ctrl._watchdog_ping()
        t7 = pc()
        times["chat"].append((t1 - t0) * 1000)
        times["logic"].append((t2 - t1) * 1000)
        times["save"].append((t3 - t2 + t7 - t6) * 1000)
        times["sounds"].append((t4 - t3) * 1000)
        times["wait"].append((tw - t4) * 1000)
        times["render"].append((t5 - tw) * 1000)
        times["convert"].append((t6 - t5) * 1000)
        times["total"].append((t7 - t0) * 1000)
        times["busy"].append((t7 - t0 - (tw - t4)) * 1000)  # the game thread working, not waiting
        if queued:
            msgs_done += queued
            chat_us.append((t1 - t0) * 1e6 / queued)
        sim = f / fps
        if sim >= next_mem:
            mem.append((round(sim, 1), round(_rss_mb(), 1)))
            user_obj.append(_user_objects())
            next_mem += mem_every
        if trace and snap0 is None and sim >= min(600.0, seconds / 4):  # after warm-up
            tracemalloc.start(8)
            snap0 = tracemalloc.take_snapshot()
    wall = real_time() - began_wall
    growth = []
    if snap0 is not None:
        diff = tracemalloc.take_snapshot().compare_to(snap0, "traceback")
        growth = [(round(d.size_diff / 1e6, 2), d.count_diff, [f"{Path(fr.filename).name}:{fr.lineno}" for fr in d.traceback][-4:])
                  for d in diff[:15]]
        tracemalloc.stop()
    wait_frame(5.0)
    cpu_ms = (time.process_time() - cpu0) * 1000 / frames
    main_cpu_ms = (time.thread_time() - main_cpu0) * 1000 / frames
    if prof:
        prof.disable()
        prof.dump_stats(profile)
    if sampler:
        sampler.on = False

    # Ranking / leaderboard cost at this N (each call timed alone, median of 5)
    logic, db = ctrl.logic, ctrl.db

    def bench(fn, reps=5):
        out = []
        for _ in range(reps):
            t0 = pc()
            fn()
            out.append((pc() - t0) * 1000)
        return round(statistics.median(out), 3)
    who = names[rng.randrange(players)]
    ranking = {
        "weekly_top10_ms": bench(lambda: db.get_weekly_top()),
        "weekly_rank_ms": bench(lambda: db.weekly_rank(who)),
        "lifetime_top10_ms": bench(lambda: db.get_top_players(10)),
        "crew_ladder_ms": bench(lambda: logic.crew_ladder(3)),
        "find_player_ms": bench(lambda: db.find_player("@" + who)),
        "match_ranking_ms": bench(lambda: logic.match_ranking(5)),
        "participation_streaks_ms": bench(logic._update_participation_streaks, reps=1),
    }

    # Memory trend after warm-up (first sample excluded): least-squares slope in MB per hour
    pts = mem[1:] if len(mem) > 3 else mem
    slope = 0.0
    if len(pts) >= 2:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den * 3600 if den else 0.0

    ui = ctrl.ui

    def surf_mb(cache):
        total = 0
        for v in cache.values():
            for s in (v if isinstance(v, tuple) else (v,)):
                if hasattr(s, "get_bytesize"):
                    total += s.get_width() * s.get_height() * s.get_bytesize()
        return round(total / 1e6, 1)
    sizes = {
        "text_cache_mb": surf_mb(getattr(ui, "_text_cache", {})),
        "surf_cache_mb": surf_mb(getattr(ui, "_surf_cache", {})),
        "fx_cache_mb": surf_mb(getattr(getattr(ui, "fx", None), "_cache", {})),
        "players_in_memory": len(db._players), "dirty_left": len(db._dirty),
        "text_cache": len(getattr(ui, "_text_cache", {})), "surf_cache": len(getattr(ui, "_surf_cache", {})),
        "event_feed": len(logic.event_feed), "seen_questions": len(logic._seen_questions),
        "command_cooldowns": len(logic._command_cooldowns), "known_players": len(logic._known_players),
        "duels": len(logic.duels), "msg_queue_left": ctrl.msg_queue.qsize(),
    }
    result = {
        "players": players, "rate": rate, "seconds": seconds, "render_every": render_every,
        "frames": frames, "wall_s": round(wall, 1), "messages": msgs_done, "paced": bool(pace),
        # CPU per frame: x 30 = percent of one core at 30 fps. Main = the game thread alone.
        "cpu_ms_per_frame": round(cpu_ms, 2), "main_cpu_ms_per_frame": round(main_cpu_ms, 2),
        "frame_ms": {p: {k: round(v, 3) for k, v in _pct(times[p], 50, 95, 99).items()} for p in phases},
        "over_budget_frames": sum(1 for t in times["busy"] if t > BUDGET_MS),
        "msg_us": {k: round(v, 2) for k, v in _pct(chat_us, 50, 95, 99).items()},
        "saves": {"count": len(saves), "rows": sum(r for _, r in saves),
                  "ms": {k: round(v, 2) for k, v in _pct([s for s, _ in saves], 50, 95).items()},
                  "worst_rows": max((r for _, r in saves), default=0)},
        "ranking_ms": ranking,
        "rss_mb": {"start": mem[0][1] if mem else 0, "end": round(_rss_mb(), 1),
                   "slope_mb_per_h": round(slope, 2), "samples": mem if len(mem) <= 40 else mem[::max(1, len(mem) // 40)]},
        "threads": {"start": threads_start, "end": threading.active_count()},
        "user_objects": {"max": max(user_obj), "end": _user_objects()},
        "sizes": sizes,
        "rounds": logic.round_count, "match_no": logic.match_no,
    }
    if sampler:
        result["sample"] = sampler.top()
    if trace:
        result["heap_growth_mb"] = growth   # Python allocations after warm-up, largest first
    ctrl.shutdown()
    time.time = real_time
    tmp.cleanup()
    return result


def _row(r: dict) -> str:
    fm = r["frame_ms"]["busy"]
    return (f"| {r['players']:>6} | {r['rate']:>5} | {fm['p50']:6.2f} | {fm['p95']:6.2f} | {fm['p99']:7.2f} | "
            f"{fm['max']:7.1f} | {r['over_budget_frames']:>5} | {r['cpu_ms_per_frame']:6.2f} | "
            f"{r['main_cpu_ms_per_frame']:6.2f} | {r['msg_us']['p50']:6.1f} | "
            f"{r['saves']['ms']['max']:7.1f} ({r['saves']['worst_rows']}) | "
            f"{r['ranking_ms']['weekly_top10_ms']:6.2f} | {r['ranking_ms']['weekly_rank_ms']:6.2f} | "
            f"{r['rss_mb']['end']:6.0f} |")


HEADER = ("| N | msg/s | busy p50 ms | p95 | p99 | max | >33ms | CPU ms/frame | main CPU ms/frame | us/msg | "
          "worst save ms (rows) | top10 ms | rank ms | RSS MB |\n" + "|---" * 14 + "|")


def run_matrix(seconds: float, jobs: int, out: str, players=PLAYERS, rates=RATES, pace=False):
    cells = [(n, m) for n in players for m in rates]
    tmp = tempfile.TemporaryDirectory()
    results, running = [], []
    pending = list(cells)
    while pending or running:
        while pending and len(running) < jobs:
            n, m = pending.pop(0)
            path = os.path.join(tmp.name, f"{n}_{m}.json")
            cmd = [sys.executable, __file__, "--players", str(n), "--rate", str(m),
                   "--seconds", str(seconds), "--json", path] + (["--pace"] if pace else [])
            running.append((subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE), path, n, m))
        for item in list(running):
            proc, path, n, m = item
            if proc.poll() is None:
                continue
            running.remove(item)
            err = proc.stderr.read().decode(errors="replace")
            if proc.returncode == 0 and os.path.exists(path):
                with open(path) as f:
                    results.append(json.load(f))
                print(_row(results[-1]), flush=True)
            else:
                print(f"| {n} | {m} | FAILED rc={proc.returncode}: {err.strip().splitlines()[-1:]} |", flush=True)
        time.sleep(0.2)
    results.sort(key=lambda r: (r["players"], r["rate"]))
    if out:
        with open(out, "w") as f:
            json.dump(results, f, indent=1)
    tmp.cleanup()
    return results


def compare(before_path: str, after_path: str):
    with open(before_path) as f:
        before = {(r["players"], r["rate"]): r for r in json.load(f)}
    with open(after_path) as f:
        after = {(r["players"], r["rate"]): r for r in json.load(f)}
    print("| N | msg/s | busy p50 ms | busy p95 ms | busy p99 ms | busy max ms | >33ms frames | "
          "CPU ms/frame | worst save ms | us/msg p50 |")
    print("|---" * 10 + "|")
    for key in sorted(before.keys() & after.keys()):
        b, a = before[key], after[key]
        bf, af = b["frame_ms"]["busy"], a["frame_ms"]["busy"]
        cell = lambda x, y, fmt="{:.1f}": f"{fmt.format(x)} -> {fmt.format(y)}"
        print(f"| {key[0]} | {key[1]} | {cell(bf['p50'], af['p50'])} | {cell(bf['p95'], af['p95'])} | "
              f"{cell(bf['p99'], af['p99'])} | {cell(bf['max'], af['max'], '{:.0f}')} | "
              f"{b['over_budget_frames']} -> {a['over_budget_frames']} | "
              f"{cell(b['cpu_ms_per_frame'], a['cpu_ms_per_frame'])} | "
              f"{cell(b['saves']['ms']['max'], a['saves']['ms']['max'], '{:.0f}')} | "
              f"{cell(b['msg_us']['p50'], a['msg_us']['p50'])} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", type=int, default=1000)
    ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--seconds", type=float, default=360, help="simulated seconds (one match is about 340)")
    ap.add_argument("--render-every", type=int, default=1, help="render 1 frame in K (long soaks)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--profile", default="", help="write cProfile stats here")
    ap.add_argument("--sample", action="store_true", help="add a stack-sampling profile to the result")
    ap.add_argument("--trace", action="store_true", help="tracemalloc after warm-up: where the Python heap grows")
    ap.add_argument("--json", default="", help="write the result here (matrix workers)")
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="parallel workers (keep at most 2 Python processes)")
    ap.add_argument("--out", default="")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--pace", action="store_true", help="real-time 30 fps like clock.tick (CPU %% like production)")
    ap.add_argument("--grid-players", default=",".join(map(str, PLAYERS)))
    ap.add_argument("--grid-rates", default=",".join(map(str, RATES)))
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare)
        return
    if a.matrix:
        print(HEADER, flush=True)
        run_matrix(a.seconds, a.jobs, a.out, [int(x) for x in a.grid_players.split(",")],
                   [float(x) for x in a.grid_rates.split(",")], a.pace)
        return
    if a.json:  # worker: keep the game's own log lines out of the way
        sys.stdout = open(os.devnull, "w")
    r = run_scenario(a.players, a.rate, a.seconds, a.render_every, a.seed, a.profile, a.sample,
                     pace_real_time=a.pace, trace=a.trace)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(r, f, indent=1)
    else:
        print(json.dumps(r, indent=1))
        print(HEADER)
        print(_row(r))


if __name__ == "__main__":
    main()
