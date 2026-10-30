"""Wheel zoom prediction: the zoom ladder, the overlay jumping ahead and the
tracker checking the predicted view first (no game needed).

    python -m unittest tests.test_wheel
"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["TREEOVERLAY_NO_WHEEL"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from treeoverlay import app as A  # noqa: E402
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import DATA_DIR, PassiveTree  # noqa: E402
from treeoverlay.wheel import ZoomPredictor  # noqa: E402

QAPP = QApplication.instance() or QApplication([])


class Ladder(unittest.TestCase):
    def test_steps(self):
        z = ZoomPredictor(1440)
        self.assertAlmostEqual(z.target(0.144, 1), 0.234)
        self.assertAlmostEqual(z.target(0.144, 3), 0.414)
        self.assertAlmostEqual(z.target(0.594, -1), 0.504)
        self.assertAlmostEqual(z.target(0.594, 1), 0.720)      # the last step is a bigger one
        self.assertAlmostEqual(z.target(0.720, 2), 0.720)      # the end of the range
        self.assertAlmostEqual(z.target(0.130, -1), 0.144)
        self.assertAlmostEqual(ZoomPredictor(1080).target(0.108, 1), 0.234 * 1080 / 1440)

    def test_learns_steps_per_notch(self):
        z = ZoomPredictor(1440)
        for _ in range(3):
            z.learn(0.234, 1, 0.414)       # one notch went two steps
        self.assertAlmostEqual(z.per_notch, 2.0)
        self.assertAlmostEqual(z.target(0.234, 1), 0.414)

    def test_learns_direction_at_the_ends(self):
        z = ZoomPredictor(1440)
        z.learn(0.234, 1, 0.144)           # wheel away from the user zoomed out
        self.assertLess(z.per_notch, 0)

    def test_zoom_keeps_anchor(self):
        t = Transform(0.144, 1280.0, 1180.0)
        t2 = ZoomPredictor.zoomed(t, 0.414, (900, 500), Transform)
        tree_pt = t.to_tree(900, 500)
        self.assertTrue(np.allclose(t2.to_screen(*tree_pt), (900, 500)))


class FakeWheel:
    def __init__(self):
        self.events = []

    def take(self):
        out, self.events = self.events, []
        return out

    def set_active(self, on):
        self.active = on


class FakeUser32:
    def __getattr__(self, name):
        return lambda *a: 0


class OverlayWheel(unittest.TestCase):
    def setUp(self):
        A.user32 = FakeUser32()
        A.cursor_pos = lambda: (900, 500)
        self.ov = A.Overlay(PassiveTree(), A.load_settings(), Tracker.POE_HUD)
        self.ov.place((0, 0, 2560, 1440))
        self.ov.wheel = FakeWheel()
        self.ov.tracker = Tracker.__new__(Tracker)
        self.ov.tracker.wheel_hint = None
        self.woken = []
        self.ov.wake_worker = lambda: self.woken.append(1)
        self.t = Transform(0.144, 1280.0, 1180.0)
        self.ov.set_transform(self.t, (900, 500, False, A.clock()), "still")

    def tearDown(self):
        self.ov.close()

    def test_jumps_ahead_then_confirms(self):
        notch = A.clock()
        self.ov.wheel.events.append((notch, 1.0))
        self.ov._follow()
        shown = self.ov.transform
        self.assertAlmostEqual(shown.scale, 0.234)
        self.assertTrue(np.allclose(shown.to_screen(*self.t.to_tree(900, 500)), (900, 500)))
        self.assertIsNotNone(self.ov.tracker.wheel_hint)
        self.assertEqual(self.woken, [1])
        # a frame captured before the game zoomed must not pull the rings back
        self.ov.set_transform(self.t, (900, 500, False, notch + 0.01), "still")
        self.assertAlmostEqual(self.ov.transform.scale, 0.234)
        # the tracker finds the zoomed view: prediction done
        found = Transform(0.2342, shown.tx + 1, shown.ty)
        self.ov.set_transform(found, (900, 500, False, notch + 0.05), "wheel")
        self.assertIsNone(self.ov.wheel_pred)
        self.assertEqual(self.ov.transform, found)

    def test_wrong_guess_gives_way(self):
        notch = A.clock()
        self.ov.wheel.events.append((notch, 1.0))
        self.ov._follow()
        other = Transform(0.414, 100.0, 100.0)
        self.ov.set_transform(other, (900, 500, False, notch + A.WHEEL_SETTLE + 0.05), "zoom-step")
        self.assertEqual(self.ov.transform, other)
        self.assertIsNone(self.ov.wheel_pred)
        self.assertGreater(self.ov.zoom.per_notch, 1.5)    # it learned one notch is more than one step

    def test_old_turns_ignored(self):
        self.ov.wheel.events.append((A.clock() - 1.0, 1.0))   # made while the tree was closed
        self.ov._follow()
        self.assertIsNone(self.ov.wheel_pred)
        self.assertAlmostEqual(self.ov.transform.scale, 0.144)


class TrackerHint(unittest.TestCase):
    """A big wheel jump: with the hint the tracker checks one view instead of searching."""
    W, H = 2560, 1440

    @classmethod
    def setUpClass(cls):
        cls.render = cv2.imread(str(DATA_DIR / "render_0.2972.png"))
        cls.meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())

    def frame(self, t):
        m = self.meta
        k = t.scale / m["zoom"]
        f = cv2.warpAffine(self.render, np.float32([[k, 0, t.tx + t.scale * m["origin_x"]],
                                                    [0, k, t.ty + t.scale * m["origin_y"]]]), (self.W, self.H))
        for x0, y0, x1, y1 in Tracker.POE_HUD:
            f[int(y0 * self.H):int(y1 * self.H), int(x0 * self.W):int(x1 * self.W)] = (40, 50, 70)
        return f

    def run_jump(self, hint):
        tracker = Tracker()
        tracker.load_reference(DATA_DIR / "render_0.2972.png", self.meta, cache=DATA_DIR / "refmap.npz")
        t = Transform(0.144, 1280 + 4 * 0.144, 720 + 3180 * 0.144)
        for _ in range(3):
            tracker.update(self.frame(t))
        cursor = (1180, 1000)
        target = ZoomPredictor.zoomed(t, 0.504, cursor, Transform)
        if hint:
            # the cursor is a few px off where the game zooms around
            tracker.wheel_hint = (ZoomPredictor.zoomed(t, 0.504, (cursor[0] + 4, cursor[1] - 3), Transform),
                                  time.perf_counter())
        est = tracker.update(self.frame(target), cursor)
        err = max(np.hypot(*(np.array(est.to_screen(*target.to_tree(x, y))) - (x, y)))
                  for x, y in ((0, 0), (self.W, 0), (0, self.H), (self.W, self.H)))
        return tracker.last_path, tracker.last_ms, err

    def test_hint_is_checked_first(self):
        path, ms, err = self.run_jump(hint=True)
        base_path, base_ms, base_err = self.run_jump(hint=False)
        print(f"\n  wheel jump 0.144 -> 0.504: with hint {path} {ms:.0f} ms {err:.1f} px; "
              f"without {base_path} {base_ms:.0f} ms {base_err:.1f} px")
        self.assertEqual(path, "wheel")
        self.assertLess(err, 4)


if __name__ == "__main__":
    unittest.main()
