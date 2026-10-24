"""Ascendancy panel detection on synthetic frames: the rendered panel pasted
over the tree at a few sizes, plus frames without it.

    python tests/test_ascendancy.py [ascendancy name]
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay import ascendancy  # noqa: E402
from treeoverlay.ascendancy import AscendancyFinder  # noqa: E402
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import DATA_DIR, PassiveTree  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "Hierophant"
tree = PassiveTree()
render = cv2.imread(str(DATA_DIR / "render_0.2972.png"))
meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
W, H = 2560, 1440
ascendancy.SEARCH_EVERY = ascendancy.CHECK_EVERY = 0.0   # test every frame


def tree_frame(s=0.144):
    k = s / meta["zoom"]
    t = Transform(s, 1280, 900)
    return cv2.warpAffine(render, np.float32([[k, 0, t.tx + s * meta["origin_x"]], [0, k, t.ty + s * meta["origin_y"]]]), (W, H))


finder = AscendancyFinder(tree, Tracker.POE_HUD)
finder.set_ascendancy(name)
panel = cv2.imread(str(DATA_DIR / f"asc_{name}.png"))
am = finder.meta
ok = True
for diameter in (500, 800, 1100):
    k = diameter / panel.shape[1]
    big = cv2.resize(panel, None, fx=k, fy=k, interpolation=cv2.INTER_LINEAR)
    frame = tree_frame()
    x0, y0 = (W - big.shape[1]) // 2, (H - big.shape[0]) // 2 - 40
    mask = np.zeros(big.shape[:2], np.uint8)
    cv2.circle(mask, (big.shape[1] // 2, big.shape[0] // 2), int(big.shape[1] * 0.42), 255, -1)
    roi = frame[y0:y0 + big.shape[0], x0:x0 + big.shape[1]]
    roi[mask > 0] = big[mask > 0]
    # where the panel's tree coordinates land on this frame
    s = am["zoom"] * k
    truth = Transform(s, x0 - am["origin_x"] * s, y0 - am["origin_y"] * s)
    finder.transform = None
    t0 = time.perf_counter()
    t = finder.update(frame)
    ms = (time.perf_counter() - t0) * 1000
    if t is None:
        print(f"panel {diameter} px: not found ({ms:.0f} ms)")
        ok = False
        continue
    err = max(np.hypot(*(np.array(t.to_screen(n.x, n.y)) - truth.to_screen(n.x, n.y)))
              for n in tree.nodes.values() if n.ascendancy == name)
    print(f"panel {diameter} px: found, worst node off by {err:.1f} px ({ms:.0f} ms)")
    ok &= err < 6
finder.transform = None
for s in (0.144, 0.3):
    if finder.update(tree_frame(s)) is not None:
        print(f"false panel on a plain tree frame (zoom {s})")
        ok = False
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
