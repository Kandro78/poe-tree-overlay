"""Drag prediction of the overlay, with a simulated mouse (no game needed).

    python -m unittest tests.test_drag
"""
import math
import os
import sys
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from treeoverlay import app as A  # noqa: E402
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import PassiveTree  # noqa: E402

QAPP = QApplication.instance() or QApplication([])
TREE = PassiveTree()


class Mouse:
    x, y, down = 1000, 700, False


class FakeUser32:
    def __getattr__(self, name):
        return lambda *a: 0

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk == A.VK_LBUTTON and Mouse.down else 0


class Drag(unittest.TestCase):
    def setUp(self):
        A.user32 = FakeUser32()
        A.cursor_pos = lambda: (Mouse.x, Mouse.y)
        Mouse.x, Mouse.y, Mouse.down = 1000, 700, False
        self.ov = A.Overlay(TREE, A.load_settings(), Tracker.POE_HUD)
        self.ov.place((0, 0, 2560, 1440))
        self.t = Transform(0.144, 1280.0, 1180.0)
        self.ov.set_transform(self.t, (Mouse.x, Mouse.y, False))

    def tearDown(self):
        self.ov.close()

    def step(self, dx, tree_moves):
        """Mouse moves by dx with the button held; the tracker then reports
        the frame captured at that moment."""
        Mouse.x += dx
        self.ov._follow()
        if tree_moves:
            self.t = Transform(self.t.scale, self.t.tx + dx, self.t.ty)
        self.ov.set_transform(self.t, (Mouse.x, Mouse.y, True))

    def press(self):
        Mouse.down = True
        self.ov._follow()

    def test_drag_where_tree_doesnt_move(self):
        self.press()
        self.step(35, tree_moves=False)     # the first tracker frame: cursor moved, tree didn't
        for _ in range(10):
            self.step(15, tree_moves=False)
            Mouse.x += 10          # the cursor runs ahead between tracker frames
            self.ov._follow()
            self.assertAlmostEqual(self.ov.transform.tx, self.t.tx, delta=0.5)

    def test_pan_follows_cursor(self):
        self.press()
        Mouse.x += 12                       # predicted from the first moment of the drag
        self.ov._follow()
        self.assertAlmostEqual(self.ov.transform.tx, self.t.tx + 12, delta=0.5)
        self.step(15, tree_moves=True)
        for _ in range(5):
            self.step(15, tree_moves=True)
            Mouse.x += 12                   # between tracker frames: prediction
            self.ov._follow()
            self.assertAlmostEqual(self.ov.transform.tx, self.t.tx + 12, delta=0.5)

    def test_release_stops_prediction(self):
        self.press()
        for _ in range(3):
            self.step(15, tree_moves=True)
        Mouse.down = False
        self.ov._follow()
        Mouse.x += 40
        self.ov._follow()
        self.ov.set_transform(self.t, (Mouse.x, Mouse.y, False))
        self.assertAlmostEqual(self.ov.transform.tx, self.t.tx, delta=0.5)


class GameLatency(unittest.TestCase):
    """The game draws the tree LAG seconds behind the cursor; the tracker
    delivers a result every ~33 ms for a frame captured ~30 ms earlier."""
    LAG = 0.040

    def setUp(self):
        self.now = 0.0
        A.user32 = FakeUser32()
        A.cursor_pos = lambda: (Mouse.x, Mouse.y)
        A.clock = lambda: self.now
        Mouse.x, Mouse.y, Mouse.down = 1000, 700, False
        self.path = [(0.0, Mouse.x)]
        self.ov = A.Overlay(TREE, A.load_settings(), Tracker.POE_HUD)
        self.ov.place((0, 0, 2560, 1440))
        self.t0 = Transform(0.144, 1280.0, 1180.0)
        self.ov.set_transform(self.t0, (Mouse.x, Mouse.y, False, self.now))

    def tearDown(self):
        self.ov.close()
        A.clock = A.time.perf_counter

    def cursor_x_at(self, when):
        xs = [x for t, x in self.path if t <= when]
        return xs[-1] if xs else self.path[0][1]

    def tree_tx_at(self, when):
        """Where the game draws the tree at `when`."""
        return self.t0.tx + self.cursor_x_at(when - self.LAG) - self.path[0][1]

    def drag(self, seconds=1.0):
        """A realistic drag: speeds up, wobbles, slows down and stops, then the
        button is held still a moment. Returns overlay errors (px) against where
        the tree is on screen when each overlay paint shows up."""
        Mouse.down = True
        errors = []
        pending = []
        start = self.now
        while self.now - start < seconds + 0.2:
            self.now += 0.008
            u = (self.now - start) / seconds
            if u < 1:
                speed = 2500 * math.sin(math.pi * u) * (1 + 0.4 * math.sin(6 * math.pi * u))
                Mouse.x += speed * 0.008
            self.path.append((self.now, Mouse.x))
            # the tracker: capture every 33 ms, result 30 ms later
            if int(self.now / 0.033) != int((self.now - 0.008) / 0.033):
                pending.append((self.now + 0.030, self.now, Mouse.x))
            while pending and pending[0][0] <= self.now:
                _, tc, cx = pending.pop(0)
                t = Transform(self.t0.scale, self.tree_tx_at(tc), self.t0.ty)
                self.ov.set_transform(t, (cx, Mouse.y, True, tc))
            self.ov._follow()
            if self.now - start > 0.1 and self.ov.transform is not None:
                errors.append(abs(self.ov.transform.tx - self.tree_tx_at(self.now + A.PRESENT_DELAY)))
        Mouse.down = False
        self.now += 0.008
        self.ov._follow()
        return errors

    def test_mouse_moves_before_the_press_dont_count(self):
        # hover across the tree without the button, the tracker reports the still tree
        for _ in range(30):
            self.now += 0.008
            Mouse.x += 10
            self.path.append((self.now, Mouse.x))
            self.ov._follow()
        self.ov.set_transform(self.t0, (Mouse.x - 150, Mouse.y, False, self.now - 0.12))
        # press: until the cursor moves with the button down, the rings stay put
        Mouse.down = True
        self.ov._follow()
        self.now += 0.008
        self.ov._follow()
        self.assertAlmostEqual(self.ov.transform.tx, self.t0.tx, delta=0.5)
        Mouse.down = False
        self.ov._follow()

    def test_latency_is_learned_and_rings_stick(self):
        self.drag()                       # the first drag measures the latency
        self.assertAlmostEqual(self.ov.latency, self.LAG, delta=0.010)
        learned = self.drag()
        self.ov.latency = 0.0             # what the overlay did before: no latency model
        naive = self.drag()
        print(f"\n  latency learned {self.ov.latency_measured and 'yes'}; ring vs tree while dragging: "
              f"with latency model median {np.median(learned):.1f} px, worst {max(learned):.1f} px; "
              f"without: median {np.median(naive):.1f} px, worst {max(naive):.1f} px")
        self.assertLess(np.percentile(learned, 95), np.percentile(naive, 95) / 2)


if __name__ == "__main__":
    unittest.main()
