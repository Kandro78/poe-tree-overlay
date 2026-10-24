"""Stand-in for the game during development: a window titled "Path of Exile"
that shows the rendered tree and slowly pans/zooms it.

    python tools/fake_game.py [seconds] [still]
"""
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"
W, H = 1600, 900
render = cv2.imread(str(DATA / "render_0.2972.png"))
meta = json.loads((DATA / "render_0.2972.json").read_text())
z, ox, oy = meta["zoom"], meta["origin_x"], meta["origin_y"]
duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30
still = "still" in sys.argv[2:]   # keep the view fixed
# "still_after=N": move for N seconds, then stop
still_after = next((float(a.split("=")[1]) for a in sys.argv[2:] if a.startswith("still_after=")), None)

cv2.namedWindow("Path of Exile", cv2.WINDOW_AUTOSIZE)
cx, cy = -4, -3180  # Witch start
t_start = time.time()
while time.time() - t_start < duration:
    run = time.time() - t_start
    if still_after is not None:
        run = min(run, still_after)
    a = 0.0 if still else run / 20 * 2 * math.pi
    s = 0.13 * (1 + 0.3 * math.sin(a))
    x, y = cx + 900 * math.sin(a), cy + 500 * math.sin(2 * a)
    k = s / z
    M = np.float32([[k, 0, W / 2 - s * x + s * ox], [0, k, H / 2 - s * y + s * oy]])
    img = cv2.warpAffine(render, M, (W, H), borderValue=(10, 12, 16))
    # fixed header like the game's "Skills" bar (the overlay learns it to tell
    # whether the tree is open)
    cv2.rectangle(img, (W // 3, 0), (2 * W // 3, 60), (40, 60, 80), -1)
    cv2.putText(img, "SKILLS", (W // 2 - 70, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (170, 200, 230), 2)
    cv2.imshow("Path of Exile", img)
    if cv2.waitKey(33) == 27:
        break
