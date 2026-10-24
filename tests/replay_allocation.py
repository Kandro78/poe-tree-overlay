"""Replay dumped frames through the allocation reader and show how the reading
changes from frame to frame (uses the transforms stored in the dump).

    python tests/replay_allocation.py <dump dir>
"""
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay.progress import AllocationReader  # noqa: E402
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import PassiveTree  # noqa: E402

dump = Path(sys.argv[1])
tree = PassiveTree()
reader = AllocationReader(tree, Tracker.POE_HUD)
latest = {}
for r in map(json.loads, open(dump / "dump.jsonl")):
    latest[r["file"]] = r          # frames are a ring buffer
prev = None
for r in sorted(latest.values(), key=lambda r: r["n"]):
    if not r["transform"]:
        print(f"{r['n']:3d} tree closed")
        continue
    reader.update(cv2.imread(str(dump / r["file"])), Transform(*r["transform"]))
    a = reader.allocated
    change = "" if prev is None else f"  +{len(a - prev)} -{len(prev - a)}"
    print(f"{r['n']:3d} allocated {len(a):3d}  covered {reader.covered:3d}{change}")
    prev = a
