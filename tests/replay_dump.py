"""Replay frames dumped with TREEOVERLAY_DUMP_DIR through a tracker in order and
compare every result with an independent fresh solve of that frame alone.

    python tests/replay_dump.py <dump dir>
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay.tracker import Tracker  # noqa: E402
from treeoverlay.tree import DATA_DIR  # noqa: E402

dump = Path(sys.argv[1])
meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
# frames are a ring buffer: only the newest record of each file matches its image
latest = {}
for r in map(json.loads, open(dump / "dump.jsonl")):
    latest[r["file"]] = r
recs = sorted(latest.values(), key=lambda r: r["n"])


def tracker():
    t = Tracker()
    t.load_reference(DATA_DIR / "render_0.2972.png", meta, cache=DATA_DIR / "refmap.npz")
    return t


seq = tracker()
bad = 0
for r in recs:
    frame = cv2.imread(str(dump / r["file"]))
    gate = f"gate {seq.gate_score(frame):.2f}" if seq.gate is not None else "gate -   "
    est = seq.update(frame)
    ref = tracker().update(frame)
    if est is None or ref is None:
        print(f"{r['n']:3d} {gate} seq", est and round(est.scale, 4), "fresh", ref and round(ref.scale, 4),
              f"{seq.last_ms:.0f}ms")
        continue
    h, w = frame.shape[:2]
    corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], float)
    err = max(np.hypot(*(np.array(est.to_screen(*ref.to_tree(x, y))) - (x, y))) for x, y in corners)
    live = r["transform"]
    print(f"{r['n']:3d} {gate} scale {est.scale:.4f} ref-matches {seq.last_ref:4d} diff-vs-fresh {err:6.1f}px {seq.last_ms:4.0f}ms"
          f"   (live run: {'%.4f %.0f %.0f' % tuple(live) if live else None})")
    bad += err > 10
print("frames disagreeing with a fresh solve:", bad)
