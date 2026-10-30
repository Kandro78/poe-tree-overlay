"""Find the build's ascendancy panel on screen.

The game shows the ascendancy tree as a round panel with its own art. It is
found like the main tree: a second tracker whose reference is the panel
rendered from the game's sprites (render.render_ascendancy). The panel doesn't
pan or zoom, so after a full search it's only re-checked a few times a second.
A full search takes ~300-600 ms, so it runs on a low-priority thread of its
own, and only when the panel may have opened: after a click that didn't move
the tree (the panel opens with one), else every few seconds. A drag that
started during a search used to stall for its first few hundred ms.
"""
import ctypes
import json
import threading
import time

import cv2
import numpy as np

from .render import render_ascendancy
from .tracker import Tracker
from .tree import DATA_DIR

MIN_DIAMETER_PX = 250     # smaller matches are the little preview on the main tree, not the panel
SEARCH_AFTER_CLICK = 1.5  # s after a click during which the panel is searched for
SEARCH_GAP = 0.4          # s between those searches
IDLE_SEARCH_EVERY = 5.0   # s between full searches otherwise, in case a click was missed
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
        self.alert_until = 0.0
        self._job = None          # (frame, tracker, name) waiting for the search thread
        self._busy = False
        self._wake = threading.Event()
        threading.Thread(target=self._run, name="ascendancy", daemon=True).start()

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

    def clicked(self):
        """A click that didn't move the tree: it may have opened the panel."""
        self.alert_until = time.perf_counter() + SEARCH_AFTER_CLICK

    def update(self, frame):
        """Hand this frame to the search thread (rate limited, never waits for
        it). Returns the panel's Transform as last found, or None."""
        if self.tracker is None:
            return None
        now = time.perf_counter()
        if self.transform is not None:
            due = CHECK_EVERY
        else:
            due = SEARCH_GAP if now < self.alert_until else IDLE_SEARCH_EVERY
        if now - self.last_try >= due and not self._busy:
            self.last_try = now
            self._busy = True
            self._job = (frame, self.tracker, self.name)   # each capture is a new array, nothing writes to it
            self._wake.set()
        return self.transform

    def _run(self):
        try:     # tracking the main tree comes first
            ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), -2)
        except (AttributeError, OSError):
            pass
        while True:
            self._wake.wait()
            self._wake.clear()
            frame, tr, name = self._job
            try:
                t = self._find(frame, tr)
                if name == self.name:          # not a search for a build switched away from
                    self.transform = t
            finally:
                self._busy = False

    def _find(self, frame, tr):
        pts, desc = tr._features(frame)
        h, w = frame.shape[:2]
        if len(pts) < tr.MIN_INLIERS:
            return None
        found = None
        if self.transform is not None:
            found = tr._guided(pts, desc, self.transform, w, h, radius_px=12)
        if found is None:
            guess = tr._match(pts, desc, np.arange(len(tr.map_pts)), w, ratio_test=False)
            if guess is not None:
                found = tr._guided(pts, desc, guess[0], w, h, radius_px=12)
        if found is None or found[1] < 40 or found[3] < 30:
            return None
        t = found[0]
        if 2 * self.meta["radius"] * t.scale < MIN_DIAMETER_PX:
            return None
        return t
