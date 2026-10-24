"""Zoom animations as the game plays them: several in-between frames per zoom
step, then the view settles. Reports time per step and error per frame.

    python tests/test_zoom_animation.py
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import DATA_DIR  # noqa: E402

render = cv2.imread(str(DATA_DIR / "render_0.2972.png"))
meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
z, ox, oy = meta["zoom"], meta["origin_x"], meta["origin_y"]
W, H = 2560, 1440


def frame(t):
    k = t.scale / z
    f = cv2.warpAffine(render, np.float32([[k, 0, t.tx + t.scale * ox], [0, k, t.ty + t.scale * oy]]), (W, H))
    # fixed UI like the game's: header, globes, flask and skill bars
    for x0, y0, x1, y1 in Tracker.POE_HUD:
        f[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)] = (40, 50, 70)
    return f


def zoomed(t, s2, anchor):
    k = s2 / t.scale
    return Transform(s2, anchor[0] - (anchor[0] - t.tx) * k, anchor[1] - (anchor[1] - t.ty) * k)


def corner_error(est, truth):
    return max(np.hypot(*(np.array(est.to_screen(*truth.to_tree(x, y))) - (x, y)))
               for x, y in ((0, 0), (W, 0), (0, H), (W, H)))


tracker = Tracker()   # the game's HUD masks
tracker.load_reference(DATA_DIR / "render_0.2972.png", meta, cache=DATA_DIR / "refmap.npz")
t = Transform(0.144, 1280 + 4 * 0.144, 720 + 3180 * 0.144)
for _ in range(3):
    tracker.update(frame(t))
anchor = (1000, 600)
rows = []
for target in (0.180, 0.234, 0.288, 0.234, 0.180, 0.144):
    start = t.scale
    for i in range(1, 7):            # the animation
        t = zoomed(t, start + (target - start) * i / 6, anchor)
        est = tracker.update(frame(t), anchor)
        rows.append(("anim", tracker.last_ms, corner_error(est, t) if est else None, tracker.last_fast))
        time.sleep(0.02)
    for _ in range(3):               # settled
        est = tracker.update(frame(t), anchor)
        rows.append(("still", tracker.last_ms, corner_error(est, t) if est else None, tracker.last_fast))
        time.sleep(0.02)

# the game also jumps several zoom levels between two frames (one wheel flick),
# around the cursor
jumps = []
for target in (0.504, 0.144, 0.414, 0.684, 0.144):
    cursor = (1180 + len(jumps) * 20, 1100)
    t = zoomed(t, target, cursor)
    est = tracker.update(frame(t), cursor)
    jumps.append((tracker.last_ms, corner_error(est, t) if est else None, tracker.last_path))
    for _ in range(2):
        tracker.update(frame(t), cursor)
        time.sleep(0.02)
print("jumps:", ", ".join(f"{p} {ms:.0f} ms {e:.1f} px" if e is not None else f"{p} lost" for ms, e, p in jumps))

anim = [r for r in rows if r[0] == "anim"]
still = [r for r in rows if r[0] == "still"]
lost = sum(r[2] is None for r in rows)
print(f"animation frames: median {np.median([r[1] for r in anim]):.0f} ms, p90 {np.percentile([r[1] for r in anim], 90):.0f} ms, "
      f"fast {sum(r[3] for r in anim)}/{len(anim)}, error median {np.median([r[2] for r in anim if r[2] is not None]):.1f} px, "
      f"max {max(r[2] for r in anim if r[2] is not None):.1f} px")
print(f"settled frames:   error max {max(r[2] for r in still if r[2] is not None):.1f} px, lost {lost}")
ok = (lost == 0 and max(r[2] for r in still) < 3 and np.median([r[1] for r in anim]) < 60
      and all(e is not None and e < 5 and ms < 150 for ms, e, _ in jumps))
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
