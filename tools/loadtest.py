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
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
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
                 profile: str = "", sample: bool = False, mem_every: float = 60.0) -> dict:
    os.environ.update({"QUIZ_LAYOUT": "vertical", "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
                       "QUIZ_FPS": "30", "QUIZ_STREAM_HEIGHT": "720"})
    sys.path.insert(0, str(ROOT))
    rng = random.Random(seed)
    random.seed(seed)

    real_time = time.time
    clock = [real_time()]
    time.time = lambda: clock[0]          # every quiz module reads time.time(): one fake clock for all

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

    saves = []
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
    phases = ("chat", "logic", "save", "sounds", "render", "convert", "total")
    times = {p: [] for p in phases}
    msgs_done, owed, chat_us = 0, 0.0, []
    mem, next_mem = [], 0.0
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
    pc = time.perf_counter
    for f in range(frames):
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
            ctrl._render()
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
        times["render"].append((t5 - t4) * 1000)
        times["convert"].append((t6 - t5) * 1000)
        times["total"].append((t7 - t0) * 1000)
        if queued:
            msgs_done += queued
            chat_us.append((t1 - t0) * 1e6 / queued)
        sim = f / fps
        if sim >= next_mem:
            mem.append((round(sim, 1), round(_rss_mb(), 1)))
            next_mem += mem_every
    wall = real_time() - began_wall
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
    sizes = {
        "players_in_memory": len(db._players), "dirty_left": len(db._dirty),
        "text_cache": len(getattr(ui, "_text_cache", {})), "surf_cache": len(getattr(ui, "_surf_cache", {})),
        "event_feed": len(logic.event_feed), "seen_questions": len(logic._seen_questions),
        "command_cooldowns": len(logic._command_cooldowns), "known_players": len(logic._known_players),
        "duels": len(logic.duels), "msg_queue_left": ctrl.msg_queue.qsize(),
    }
    result = {
        "players": players, "rate": rate, "seconds": seconds, "render_every": render_every,
        "frames": frames, "wall_s": round(wall, 1), "messages": msgs_done,
        "frame_ms": {p: {k: round(v, 3) for k, v in _pct(times[p], 50, 95, 99).items()} for p in phases},
        "over_budget_frames": sum(1 for t in times["total"] if t > BUDGET_MS),
        "msg_us": {k: round(v, 2) for k, v in _pct(chat_us, 50, 95, 99).items()},
        "saves": {"count": len(saves), "rows": sum(r for _, r in saves),
                  "ms": {k: round(v, 2) for k, v in _pct([s for s, _ in saves], 50, 95).items()},
                  "worst_rows": max((r for _, r in saves), default=0)},
        "ranking_ms": ranking,
        "rss_mb": {"start": mem[0][1] if mem else 0, "end": round(_rss_mb(), 1),
                   "slope_mb_per_h": round(slope, 2), "samples": mem if len(mem) <= 40 else mem[::max(1, len(mem) // 40)]},
        "threads": {"start": threads_start, "end": threading.active_count()},
        "sizes": sizes,
        "rounds": logic.round_count, "match_no": logic.match_no,
    }
    if sampler:
        result["sample"] = sampler.top()
    ctrl.shutdown()
    time.time = real_time
    tmp.cleanup()
    return result


def _row(r: dict) -> str:
    fm = r["frame_ms"]["total"]
    return (f"| {r['players']:>6} | {r['rate']:>5} | {fm['p50']:6.2f} | {fm['p95']:6.2f} | {fm['p99']:7.2f} | "
            f"{fm['max']:7.1f} | {r['over_budget_frames']:>5} | {r['msg_us']['p50']:6.1f} | "
            f"{r['saves']['ms']['max']:7.1f} ({r['saves']['worst_rows']}) | "
            f"{r['ranking_ms']['weekly_top10_ms']:6.2f} | {r['ranking_ms']['weekly_rank_ms']:6.2f} | "
            f"{r['rss_mb']['end']:6.0f} |")


HEADER = ("| N | msg/s | p50 ms | p95 ms | p99 ms | max ms | >33ms | us/msg | worst save ms (rows) | "
          "top10 ms | rank ms | RSS MB |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def run_matrix(seconds: float, jobs: int, out: str, players=PLAYERS, rates=RATES):
    cells = [(n, m) for n in players for m in rates]
    tmp = tempfile.TemporaryDirectory()
    results, running = [], []
    pending = list(cells)
    while pending or running:
        while pending and len(running) < jobs:
            n, m = pending.pop(0)
            path = os.path.join(tmp.name, f"{n}_{m}.json")
            cmd = [sys.executable, __file__, "--players", str(n), "--rate", str(m),
                   "--seconds", str(seconds), "--json", path]
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
                print(f"| {n} | {m} | FAILED rc={proc.returncode}: {err.strip().splitlines()[-1:] } |", flush=True)
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
    print("| N | msg/s | p50 ms | p95 ms | p99 ms | max ms | >33ms frames | worst save ms | us/msg p50 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for key in sorted(before.keys() & after.keys()):
        b, a = before[key], after[key]
        bf, af = b["frame_ms"]["total"], a["frame_ms"]["total"]
        cell = lambda x, y, fmt="{:.2f}": f"{fmt.format(x)} -> {fmt.format(y)}"
        print(f"| {key[0]} | {key[1]} | {cell(bf['p50'], af['p50'])} | {cell(bf['p95'], af['p95'])} | "
              f"{cell(bf['p99'], af['p99'])} | {cell(bf['max'], af['max'], '{:.0f}')} | "
              f"{b['over_budget_frames']} -> {a['over_budget_frames']} | "
              f"{cell(b['saves']['ms']['max'], a['saves']['ms']['max'], '{:.0f}')} | "
              f"{cell(b['msg_us']['p50'], a['msg_us']['p50'], '{:.1f}')} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", type=int, default=1000)
    ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--seconds", type=float, default=360, help="simulated seconds (one match is about 340)")
    ap.add_argument("--render-every", type=int, default=1, help="render 1 frame in K (long soaks)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--profile", default="", help="write cProfile stats here")
    ap.add_argument("--sample", action="store_true", help="add a stack-sampling profile to the result")
    ap.add_argument("--json", default="", help="write the result here (matrix workers)")
    ap.add_argument("--matrix", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default="")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare)
        return
    if a.matrix:
        print(HEADER, flush=True)
        run_matrix(a.seconds, a.jobs, a.out)
        return
    if a.json:  # worker: keep the game's own log lines out of the way
        sys.stdout = open(os.devnull, "w")
    r = run_scenario(a.players, a.rate, a.seconds, a.render_every, a.seed, a.profile, a.sample)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(r, f, indent=1)
    else:
        print(json.dumps(r, indent=1))
        print(HEADER)
        print(_row(r))


if __name__ == "__main__":
    main()
