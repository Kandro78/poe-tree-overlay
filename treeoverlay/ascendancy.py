"""Find the build's ascendancy panel on screen.

The game shows the ascendancy tree as a round panel with its own art. It is
found like the main tree: a second tracker whose reference is the panel
rendered from the game's sprites (render.render_ascendancy). The panel doesn't
pan or zoom, so after a full search it's only re-checked a few times a second.
"""
import json
import time

import cv2
import numpy as np

from .render import render_ascendancy
from .tracker import Tracker
from .tree import DATA_DIR

MIN_DIAMETER_PX = 250     # smaller matches are the little preview on the main tree, not the panel
SEARCH_EVERY = 0.5        # s between full searches while the panel isn't open
CHECK_EVERY = 0.25        # s between re-checks while it is


class AscendancyFinder:
    def __init__(self, tree, mask_rects):
        self.tree = tree
        self.mask_rects = mask_rects
        self.name = None
        self.tracker = None
        self.meta = None
        self.transform = None
        self.last_try = 0.0

    def set_ascendancy(self, name):
        if name == self.name:
            return
        self.name, self.transform, self.tracker = name, None, None
        if not name:
            return
        png = DATA_DIR / f"asc_{name}.png"
        meta_file = DATA_DIR / f"asc_{name}.json"
        if not png.exists() or not meta_file.exists():
            img, meta = render_ascendancy(self.tree, name)
            cv2.imwrite(str(png), img)
            meta_file.write_text(json.dumps(meta))
        self.meta = json.loads(meta_file.read_text())
        self.tracker = Tracker(self.mask_rects)
        # the panel can be shown larger than the render: include upscaled levels
        self.tracker.load_reference(png, self.meta, cache=DATA_DIR / f"asc_{name}_refmap.npz",
                                    levels=(2.0, 1.5, 1.1, 0.8, 0.6, 0.45, 0.33))

    @property
    def circle(self):
        """(x, y, radius) of the panel on screen, or None."""
        t = self.transform
        if t is None or self.meta is None:
            return None
        x, y = t.to_screen(*self.meta["centre"])
        return x, y, self.meta["radius"] * t.scale

    def update(self, frame):
        """Look for the panel in this frame (rate limited). Returns its Transform or None."""
        if self.tracker is None:
            return None
        now = time.perf_counter()
        due = CHECK_EVERY if self.transform is not None else SEARCH_EVERY
        if now - self.last_try < due:
            return self.transform
        self.last_try = now
        tr = self.tracker
        pts, desc = tr._features(frame)
        h, w = frame.shape[:2]
        if len(pts) < tr.MIN_INLIERS:
            self.transform = None
            return None
        found = None
        if self.transform is not None:
            found = tr._guided(pts, desc, self.transform, w, h, radius_px=12)
        if found is None:
            guess = tr._match(pts, desc, np.arange(len(tr.map_pts)), w, ratio_test=False)
            if guess is not None:
                found = tr._guided(pts, desc, guess[0], w, h, radius_px=12)
        if found is None or found[1] < 40 or found[3] < 30:
            self.transform = None
            return None
        t = found[0]
        if 2 * self.meta["radius"] * t.scale < MIN_DIAMETER_PX:
            self.transform = None
            return None
        self.transform = t
        return t
