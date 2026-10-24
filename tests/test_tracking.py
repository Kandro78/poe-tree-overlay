"""Simulated pan/zoom session over a rendered tree (no game needed).

    python tools/render_tree.py      # once
    python tests/test_tracking.py
"""
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import PassiveTree, DATA_DIR  # noqa: E402

W, H = 2560, 1440
rng = np.random.default_rng(1)

render = cv2.imread(str(DATA_DIR / "render_0.2972.png"))
meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
z, ox, oy = meta["zoom"], meta["origin_x"], meta["origin_y"]


def view(t: Transform):
    k = t.scale / z
    M = np.float32([[k, 0, t.tx + t.scale * ox], [0, k, t.ty + t.scale * oy]])
    img = cv2.warpAffine(render, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=(10, 12, 16))
    # make it look less like the reference: other gamma/tint, slight blur and
    # glowing "allocated" nodes along the way
    img = (255 * (img / 255.0) ** 0.85 * np.array([0.95, 1.0, 1.08])).clip(0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    for n in allocated:
        x, y = t.to_screen(n.x, n.y)
        if -50 < x < W + 50 and -50 < y < H + 50:
            cv2.circle(img, (int(x), int(y)), int(n.radius * t.scale * 1.1), (90, 200, 240), max(2, int(8 * t.scale)), cv2.LINE_AA)
    # static UI that does not move with the tree: top bar and a search box
    cv2.rectangle(img, (0, 0), (W, 90), (30, 40, 50), -1)
    cv2.putText(img, "12 Passive Skill Points Left", (W // 2 - 300, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (180, 200, 220), 3)
    cv2.rectangle(img, (40, H - 110), (600, H - 40), (40, 40, 40), -1)
    cv2.putText(img, "Search", (60, H - 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (150, 150, 150), 2)
    noise = rng.normal(0, 3, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def centered(tree_x, tree_y, scale):
    return Transform(scale, W / 2 - scale * tree_x, H / 2 - scale * tree_y)


tree = PassiveTree()
witch = tree.class_start(3)
target = [n for n in tree.nodes.values() if not n.ascendancy]
allocated = [n for n in target if math.dist((n.x, n.y), (witch.x, witch.y)) < 3000 and rng.random() < 0.5]
MODE = sys.argv[1] if len(sys.argv) > 1 else "auto"   # auto | manual | noref

# A path: start at the witch, pan right/down while zooming out and in again.
path = []
cx, cy, s = witch.x, witch.y, 0.20
for i in range(200):
    a = i / 200 * 2 * math.pi
    s = 0.20 * (1.0 + 0.6 * math.sin(a * 1.5))     # 0.08 .. 0.32
    cx += 70 * math.cos(a) / s * 0.2                # ~70 px per frame on screen
    cy += 40 * math.sin(a * 2) / s * 0.2
    path.append(centered(cx, cy, s))

tracker = Tracker(mask_rects=[(0, 0, 1, 0.07)])
if MODE != "noref":
    tracker.load_reference(DATA_DIR / "render_0.2972.png", meta, cache=DATA_DIR / "refmap.npz")
    print("reference features:", tracker.n_ref)
truth0 = path[0]
# Calibration with a few px of hover error on both points
p_start = np.array(truth0.to_screen(witch.x, witch.y)) + rng.normal(0, 4, 2)
notable = min((n for n in target if n.kind == "notable" and 900 < math.dist((n.x, n.y), (witch.x, witch.y)) < 2500),
              key=lambda n: math.dist((n.x, n.y), (witch.x, witch.y)))
p_not = np.array(truth0.to_screen(notable.x, notable.y)) + rng.normal(0, 4, 2)
cal = Transform.from_points([(witch.x, witch.y), (notable.x, notable.y)], [p_start, p_not])
if MODE == "auto":
    first = tracker.update(view(truth0))
    print("found without calibration:", first is not None, f"in {tracker.last_ms:.0f}ms")
else:
    print(f"hover calibration: notable {notable.name!r}, scale err {abs(cal.scale / truth0.scale - 1) * 100:.2f}%")
    cal = tracker.calibrate(view(truth0), cal)
    print(f"after refinement: scale err {abs(cal.scale / truth0.scale - 1) * 100:.2f}%")

errs, lost, times, lost_at = [], 0, [], []
for i, truth in enumerate(path[1:], 1):
    if i == 100:  # tree closed for a few frames: random gameplay-ish image
        for _ in range(3):
            junk = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3), np.uint8), (0, 0), 3)
            r = tracker.update(junk)
            print("closed-tree frame ->", "lost (good)" if r is None else "FALSE POSITIVE")
    est = tracker.update(view(truth))
    times.append(tracker.last_ms)
    if est is None:
        lost += 1
        lost_at.append(i)
        continue
    # error measured on nodes visible on screen
    pts = [(n.x, n.y) for n in target]
    tp = np.array([truth.to_screen(x, y) for x, y in pts])
    vis = (tp[:, 0] > 0) & (tp[:, 0] < W) & (tp[:, 1] > 0) & (tp[:, 1] < H)
    ep = np.array([est.to_screen(x, y) for x, y in pts])
    errs.append(np.abs(ep[vis] - tp[vis]).max())
    if errs[-1] > 8:
        print(f"frame {i}: max err {errs[-1]:.1f}px (scale {truth.scale:.3f}, {tracker.last_ref} reference matches)")
    if i % 25 == 0:
        print(f"frame {i:3d} scale {truth.scale:.3f} inliers {tracker.last_inliers:4d} "
              f"max err {errs[-1]:5.1f}px map {len(tracker.map_pts)} {tracker.last_ms:.0f}ms")

errs = np.array(errs)
print(f"\nframes {len(path) - 1}, lost {lost}, median max-err {np.median(errs):.1f}px, "
      f"lost at {lost_at}, 95% {np.percentile(errs, 95):.1f}px, worst {errs.max():.1f}px, avg {np.mean(times):.0f}ms/frame")
ok = lost <= 5 and np.percentile(errs, 95) < 12
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
