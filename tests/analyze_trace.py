"""How well do the rings follow the tree while dragging? Reads a trace written
with TREEOVERLAY_TRACE=<file> and compares, for every frame captured during a
drag, where the tree was with where the overlay showed the rings at that moment.
It then replays the prediction with other latency / present-delay values to
see which would have fit best.

    python tests/analyze_trace.py <trace file>
"""
import bisect
import json
import sys

import numpy as np

rows = [json.loads(line) for line in open(sys.argv[1])]
tracks = [r for r in rows if r["k"] == "track"]
ticks = [r for r in rows if r["k"] == "tick"]
if not ticks:
    sys.exit("no drags in this trace")

# cursor history from every sample we have
cur = sorted([(r["t"], r["cx"], r["cy"]) for r in ticks] + [(r["tc"], r["cx"], r["cy"]) for r in tracks])
cur_t = [c[0] for c in cur]


def cursor_at(when):
    i = bisect.bisect_right(cur_t, when)
    if i == 0:
        return cur[0][1:]
    if i == len(cur):
        return cur[-1][1:]
    (t0, x0, y0), (t1, x1, y1) = cur[i - 1], cur[i]
    f = (when - t0) / (t1 - t0) if t1 > t0 else 0
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


tick_t = [r["t"] for r in ticks]
# the button went down at the first overlay update of each drag
press_starts = [r["t"] for i, r in enumerate(ticks) if i == 0 or r["t"] - ticks[i - 1]["t"] > 0.05]


def press_start(when):
    i = bisect.bisect_right(press_starts, when) - 1
    return press_starts[i] if i >= 0 else 0.0
done_sorted = sorted(tracks, key=lambda r: r["done"])
done_t = [r["done"] for r in done_sorted]
truth = [r for r in tracks if r["down"] and r["path"] in ("pan-fast", "pan-checked")]


def shown_error(present):
    """What the overlay actually showed (from the ticks) vs the tree."""
    errs = []
    for r in truth:
        i = bisect.bisect_right(tick_t, r["tc"] - present) - 1
        if i < 0 or r["tc"] - present - ticks[i]["t"] > 0.03 or not ticks[i]["pred"]:
            continue
        errs.append(np.hypot(ticks[i]["ox"] - r["tx"], ticks[i]["oy"] - r["ty"]))
    return np.array(errs)


def replay_error(latency, present, predict=True):
    """The prediction rebuilt with other values."""
    errs = []
    for r in truth:
        paint = r["tc"] - present
        j = bisect.bisect_right(done_t, paint) - 1
        if j < 0:
            continue
        base = done_sorted[j]
        if not base["down"] or abs(base["s"] / r["s"] - 1) > 0.01 or paint - base["tc"] > 0.3:
            continue
        if predict:
            pressed = press_start(paint)      # only movement with the button down drags the tree
            soon = cursor_at(max(paint + present - latency, pressed))
            then = cursor_at(max(base["tc"] - latency, pressed))
            px, py = base["tx"] + soon[0] - then[0], base["ty"] + soon[1] - then[1]
        else:
            px, py = base["tx"], base["ty"]
        errs.append(np.hypot(px - r["tx"], py - r["ty"]))
    return np.array(errs)


def describe(e):
    return f"median {np.median(e):5.1f} px, 90% {np.percentile(e, 90):5.1f} px, worst {e.max():5.1f} px (n={len(e)})"


print(f"{len(tracks)} tracker results, {len(truth)} during drags, {len(ticks)} overlay updates")
lat_used = ticks[-1]["lat"]
for present in (0.0, 0.008, 0.016):
    e = shown_error(present)
    if len(e):
        print(f"as shown, if the overlay appears {present * 1000:.0f} ms after painting: {describe(e)}")
print(f"no prediction at all:        {describe(replay_error(0, 0, predict=False))}")
best = None
for lat in np.arange(0, 0.081, 0.004):
    for present in (0.0, 0.004, 0.008, 0.012, 0.016, 0.024):
        e = replay_error(lat, present)
        if len(e) and (best is None or np.median(e) < best[0]):
            best = (np.median(e), lat, present, e)
print(f"replayed with latency {lat_used * 1000:.0f} ms / present 8 ms: {describe(replay_error(lat_used, 0.008))}")
print(f"best: latency {best[1] * 1000:.0f} ms, present {best[2] * 1000:.0f} ms: {describe(best[3])}")
