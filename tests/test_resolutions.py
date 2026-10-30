"""Tracking at other window sizes and UI scales: the HUD is drawn where the
anchored layout (treeoverlay/hud.py) puts it, the tree pans underneath.

    python tests/test_resolutions.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay.hud import gate_rect, ui_rects  # noqa: E402
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import DATA_DIR  # noqa: E402

render = cv2.imread(str(DATA_DIR / "render_0.2972.png"))
meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
rng = np.random.default_rng(3)


def frame(t, w, h, ui, header=True):
    k = t.scale / meta["zoom"]
    img = cv2.warpAffine(render, np.float32([[k, 0, t.tx + t.scale * meta["origin_x"]],
                                             [0, k, t.ty + t.scale * meta["origin_y"]]]), (w, h))
    for x0, y0, x1, y1 in ui_rects(w, h, ui):           # the HUD: textured, so it has features
        patch = rng.integers(30, 120, (int((y1 - y0) * h) + 1, int((x1 - x0) * w) + 1, 3), dtype=np.uint8)
        img[int(y0 * h):int(y0 * h) + patch.shape[0], int(x0 * w):int(x0 * w) + patch.shape[1]] = \
            patch[:img[int(y0 * h):, int(x0 * w):].shape[0], :img[:, int(x0 * w):].shape[1]]
    if header:
        gx0, gy0, gx1, gy1 = gate_rect(w, h, ui)
        cv2.putText(img, "SKILLS", (int((gx0 + gx1) / 2 * w) - 60, int(gy1 * h * 0.8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0 * h / 1440 * 1.5, (200, 220, 240), 2)
        cv2.rectangle(img, (int(gx0 * w), 0), (int(gx1 * w), int(gy1 * h)), (90, 110, 130), 3)
    return img


ok = True
for w, h, ui in ((1920, 1080, 1.0), (3440, 1440, 1.0), (2560, 1440, 1.2),
                 (3840, 2160, 1.0), (2560, 1080, 1.0), (1600, 900, 1.0), (1366, 768, 1.0)):
    tr = Tracker()
    tr.load_reference(DATA_DIR / "render_0.2972.png", meta, cache=DATA_DIR / "refmap.npz")
    tr.fit_to_window(w, h, ui)
    errs, lost = [], 0
    for level, steps in ((0.144, 40), (0.234, 15)):     # min zoom, then one wheel step in
        s = level * h / 1440
        t = Transform(s, w / 2 + 4 * s, h / 2 + 3180 * s)
        for i in range(steps):
            t = Transform(s, t.tx + 18 * w / 2560, t.ty - 9 * h / 1440)
            est = tr.update(frame(t, w, h, ui))
            if est is None:
                lost += 1
                continue
            errs.append(max(np.hypot(*(np.array(est.to_screen(*t.to_tree(x, y))) - (x, y)))
                            for x, y in ((0, 0), (w, 0), (0, h), (w, h))))
    gate = tr.gate is not None
    closed = tr.gate_closed(frame(t, w, h, ui, header=False)) if gate else None
    print(f"{w}x{h} UI {int(ui * 100)}%: lost {lost}, worst {max(errs):.1f} px, header learned {gate}, "
          f"no-header frame seen as closed {closed}")
    ok &= lost <= 2 and max(errs) < 5 and gate and closed
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
