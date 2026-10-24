"""Replay a burst dump (TREEOVERLAY_DUMP_BURST=1: every frame saved) through
one tracker in order, with the cursor positions from the dump, and compare the
frames where the zoom changed with a fresh solve.

    python tests/replay_burst.py <dump dir>
"""
import collections
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
recs = [json.loads(l) for l in open(dump / "dump.jsonl")]
latest = {}
for r in recs:
    latest[r["file"]] = r
recs = sorted(latest.values(), key=lambda r: r["n"])

# Older dumps have no cursor: use the zoom centre implied by the live results.
for a, b in zip(recs, recs[1:]):
    if b.get("cursor") is None and a["transform"] and b["transform"] and abs(b["transform"][0] / a["transform"][0] - 1) > 0.02:
        k = b["transform"][0] / a["transform"][0]
        b["cursor"] = [(k * a["transform"][i] - b["transform"][i]) / (k - 1) for i in (1, 2)]


def tracker():
    t = Tracker()
    t.load_reference(DATA_DIR / "render_0.2972.png", meta, cache=DATA_DIR / "refmap.npz")
    return t


seq = tracker()
paths = collections.defaultdict(list)
bad = 0
prev_scale = None
for r in recs:
    frame = cv2.imread(str(dump / r["file"]))
    est = seq.update(frame, r.get("cursor"))
    paths[seq.last_path].append(seq.last_ms)
    if est is not None and prev_scale and abs(est.scale / prev_scale - 1) > 0.02:
        ref = tracker().update(frame)
        h, w = frame.shape[:2]
        err = None if ref is None else max(
            np.hypot(*(np.array(est.to_screen(*ref.to_tree(x, y))) - (x, y))) for x, y in ((0, 0), (w, 0), (0, h), (w, h)))
        print(f"{r['n']:4d} zoom {prev_scale:.3f}->{est.scale:.3f} via {seq.last_path:12s} {seq.last_ms:4.0f} ms  "
              f"vs fresh: {'-' if err is None else f'{err:.1f} px'}")
        bad += err is not None and err > 10
    if est is not None:
        prev_scale = est.scale
    time.sleep(0.03)
print()
for k, v in sorted(paths.items(), key=lambda kv: -len(kv[1])):
    print(f"{k:13s} n={len(v):3d} median {np.median(v):5.0f} ms")
print("zoom frames off by more than 10 px:", bad)
