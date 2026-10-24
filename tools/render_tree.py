"""Render the passive tree from the official sprite sheets (see treeoverlay/render.py).

    python tools/render_tree.py
"""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from treeoverlay.render import ZOOM, render  # noqa: E402
from treeoverlay.tree import DATA_DIR, PassiveTree  # noqa: E402

if __name__ == "__main__":
    img, meta = render(PassiveTree())
    out = DATA_DIR / f"render_{ZOOM}.png"
    cv2.imwrite(str(out), img)
    (DATA_DIR / f"render_{ZOOM}.json").write_text(json.dumps(meta))
    print(out, img.shape)
