"""Time the parts of one tracking step on dumped live frames.

    python tests/profile_frame.py <dump dir>
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay.tracker import Tracker  # noqa: E402
from treeoverlay.tree import DATA_DIR  # noqa: E402

dump = Path(sys.argv[1])
meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
tr = Tracker()
tr.load_reference(DATA_DIR / "render_0.2972.png", meta, cache=DATA_DIR / "refmap.npz")
frames = [cv2.imread(str(p)) for p in sorted(dump.glob("frame_*.jpg"))]
frames = [f for f in frames if tr.update(f) is not None][:8]
timing = {}


def timed(name, fn, *a, **k):
    t0 = time.perf_counter(); r = fn(*a, **k)
    timing.setdefault(name, []).append((time.perf_counter() - t0) * 1000)
    return r


for f in frames:
    h, w = f.shape[:2]
    pts, desc = timed("features", tr._features, f)
    moved = timed("windowed", tr._windowed, pts, desc, tr.transform, w, h)
    timed("guided", tr._guided, pts, desc, moved[0], w, h, 12)
    timed("global", tr._match, pts, desc, np.arange(len(tr.map_pts)), w, False)
    timed("update total", tr.update, f)
for k, v in timing.items():
    print(f"{k:14s} {np.median(v):6.1f} ms")
