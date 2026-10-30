"""Overlay drawing: a pan moves the cached tree layer instead of drawing it
again, and looks the same as drawing it fresh.

    python -m unittest tests.test_paint
"""
import os
import sys
import time
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["TREEOVERLAY_NO_WHEEL"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from treeoverlay import app as A  # noqa: E402
from treeoverlay.build import Spec  # noqa: E402
from treeoverlay.tracker import Tracker, Transform  # noqa: E402
from treeoverlay.tree import PassiveTree  # noqa: E402

QAPP = QApplication.instance() or QApplication([])
TREE = PassiveTree()


class Layer(unittest.TestCase):
    def setUp(self):
        self.ov = A.Overlay(TREE, A.load_settings(), Tracker.POE_HUD)
        self.ov.place((0, 0, 2560, 1440))
        self.ov.opacity = 1.0
        self.ov.settings["show_labels"] = False
        self.ov.set_spec(self.spec())

    def tearDown(self):
        self.ov.close()

    def spec(self):
        # a real-sized build: the class start plus everything within 25 steps
        cls = 3
        start = TREE.class_start(cls).id
        seen, edge = {start}, [start]
        for _ in range(25):
            edge = [b for a in edge for b in TREE.nodes[a].neighbours
                    if b not in seen and b in TREE.nodes and not TREE.nodes[b].ascendancy]
            seen.update(edge)
        return Spec(class_id=cls, ascend_id=0, nodes=sorted(seen - {start}), masteries={}, title="test")

    def draw(self):
        img = QImage(2560, 1440, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        t0 = time.perf_counter()
        self.ov.render(img)
        ms = (time.perf_counter() - t0) * 1000
        img = img.convertToFormat(QImage.Format_RGBA8888)
        return np.frombuffer(img.constBits(), np.uint8).reshape(1440, 2560, 4).astype(np.int16), ms

    def test_pan_reuses_layer_and_matches(self):
        start = TREE.class_start(3)
        t = Transform(0.144, 1280 - 0.144 * start.x, 720 - 0.144 * start.y)
        self.ov.transform = t
        self.draw()
        layer = self.ov._layer[3]
        self.ov.transform = Transform(t.scale, t.tx + 37, t.ty - 21)
        moved, ms = self.draw()
        self.assertIs(self.ov._layer[3], layer)          # not drawn again
        self.ov._layer = None
        fresh, _ = self.draw()
        diff = np.abs(moved - fresh)
        print(f"\n  pan from the cached layer: {ms:.1f} ms; pixels differing by > 40: {(diff.max(2) > 40).mean() * 100:.2f}%")
        self.assertLess((diff.max(2) > 40).mean(), 0.002)
        self.assertGreater(fresh[..., 3].astype(bool).mean(), 0.001)   # something was drawn at all

    def test_zoom_draws_again(self):
        start = TREE.class_start(3)
        self.ov.transform = Transform(0.144, 1280 - 0.144 * start.x, 720 - 0.144 * start.y)
        self.draw()
        layer = self.ov._layer[3]
        self.ov.transform = Transform(0.234, 1280 - 0.234 * start.x, 720 - 0.234 * start.y)
        self.draw()
        self.assertIsNot(self.ov._layer[3], layer)


if __name__ == "__main__":
    unittest.main()
