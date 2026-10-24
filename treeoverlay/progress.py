"""Which passives the character has allocated, read from the screen, and what
that means for the target build.

Allocated passives get a brightly lit frame. On live 2560x1440 frames, the ring
where the frame sits measured (75th percentile of HSV value):
    small passives: allocated 176-232, unallocated 46-65
    notables:       allocated 233-248, unallocated 95-123
Masteries have no such frame; their icon turns from grey to colour instead, so
for them the colour saturation at the centre is used.

Tooltips: hovering a node opens a semi-transparent popup that darkens everything
under it, which would read as "unallocated". Every node remembers how bright it
looked at its last reading. Where most nodes of a screen region, unallocated
ones included, get much darker at once, the region counts as covered and keeps
its old readings. A refund darkens only the refunded nodes, so it still registers.
"""
from collections import deque

import cv2
import numpy as np

# brightness of the frame ring above which a node counts as allocated
RING_THRESHOLD = {"normal": 120.0, "notable": 175.0, "keystone": 175.0, "jewel": 175.0}
MASTERY_SATURATION = 56.0
SMOOTHING = 0.5        # weight of the newest reading
MIN_RADIUS_PX = 3.0    # nodes drawn smaller than this can't be read reliably
COVER_DARKER = 0.6     # a node this much darker than last time may be covered
COVER_SHARE = 0.5      # ... and its region is, when this share of its nodes are
COVER_CELL_PX = 200

_ANGLES = np.linspace(0, 2 * np.pi, 24, endpoint=False)
_RING = np.array([(rr * np.cos(a), rr * np.sin(a)) for a in _ANGLES for rr in (0.75, 0.85, 0.95)])
_g = np.linspace(-0.45, 0.45, 7)
_CORE = np.array([(x, y) for x in _g for y in _g])


class AllocationReader:
    def __init__(self, tree, mask_rects):
        self.tree = tree
        self.mask_rects = mask_rects
        self.score = {}    # node id -> smoothed reading / threshold (> 1 = allocated)
        self.nodes = [n for n in tree.nodes.values() if not n.ascendancy and n.kind != "start"]
        self.xy = np.array([(n.x, n.y) for n in self.nodes])
        self.radius = np.array([n.radius for n in self.nodes])
        self.is_mastery = np.array([n.kind == "mastery" for n in self.nodes])
        self.threshold = np.array([MASTERY_SATURATION if n.kind == "mastery" else RING_THRESHOLD.get(n.kind, 175.0)
                                   for n in self.nodes])
        self.look = np.full(len(self.nodes), np.nan)   # overall brightness at the last reading
        self.covered = 0   # nodes skipped in the last update because something covered them
        self.covered_rects = []

    def reset(self):
        self.score.clear()
        self.look[:] = np.nan

    @staticmethod
    def _sample(img, sx, sy, r, offsets, x_lo, y_lo):
        px = (sx[:, None] + offsets[None, :, 0] * r[:, None]).round().astype(int) - x_lo
        py = (sy[:, None] + offsets[None, :, 1] * r[:, None]).round().astype(int) - y_lo
        return np.percentile(img[py.clip(0, img.shape[0] - 1), px.clip(0, img.shape[1] - 1)], 75, axis=1)

    def update(self, frame, t):
        """Read every node that is fully on screen and not under the HUD."""
        h, w = frame.shape[:2]
        sx, sy = t.to_screen(self.xy[:, 0], self.xy[:, 1])
        r = self.radius * t.scale
        ok = (r >= MIN_RADIUS_PX) & (sx > r) & (sx < w - r) & (sy > r) & (sy < h - r)
        for x0, y0, x1, y1 in self.mask_rects:
            ok &= ~((sx > w * x0 - r) & (sx < w * x1 + r) & (sy > h * y0 - r) & (sy < h * y1 + r))
        idx = np.nonzero(ok)[0]
        self.covered_rects = []
        if not len(idx):
            return
        # convert only the bounding box of all visible nodes
        x_lo = int(max(0, (sx[idx] - r[idx]).min())); x_hi = int(min(w, (sx[idx] + r[idx]).max() + 1))
        y_lo = int(max(0, (sy[idx] - r[idx]).min())); y_hi = int(min(h, (sy[idx] + r[idx]).max() + 1))
        hsv = cv2.cvtColor(frame[y_lo:y_hi, x_lo:x_hi], cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2]
        values = np.empty(len(idx))
        ring = ~self.is_mastery[idx]
        if ring.any():
            i = idx[ring]
            values[ring] = self._sample(value, sx[i], sy[i], r[i], _RING, x_lo, y_lo)
        if (~ring).any():
            i = idx[~ring]
            sat = hsv[:, :, 1].astype(np.float32) * (value.astype(np.float32) / 255.0)
            values[~ring] = self._sample(sat, sx[i], sy[i], r[i], _CORE, x_lo, y_lo)
        values /= self.threshold[idx]

        # how bright each node looks overall, to notice popups covering it
        look = self._sample(value, sx[idx], sy[idx], r[idx], np.vstack([_CORE, _RING]), x_lo, y_lo)
        prev = self.look[idx]
        known = ~np.isnan(prev)
        darker = known & (look < COVER_DARKER * prev)
        cell = (sx[idx] // COVER_CELL_PX).astype(int) * 1000 + (sy[idx] // COVER_CELL_PX).astype(int)
        cells, inv = np.unique(cell, return_inverse=True)
        n_known = np.bincount(inv, weights=known, minlength=len(cells))
        n_dark = np.bincount(inv, weights=darker, minlength=len(cells))
        covered_cell = (n_known >= 3) & (n_dark >= COVER_SHARE * n_known)
        covered = covered_cell[inv]
        self.covered = int(covered.sum())
        # screen areas the overlay shouldn't draw over (the popup sits there)
        pad = COVER_CELL_PX // 4
        self.covered_rects = [((c // 1000) * COVER_CELL_PX - pad, (c % 1000) * COVER_CELL_PX - pad,
                               COVER_CELL_PX + 2 * pad, COVER_CELL_PX + 2 * pad) for c in cells[covered_cell]]
        idx, values, look = idx[~covered], values[~covered], look[~covered]
        self.look[idx] = look
        for i, v in zip(idx, values):
            nid = self.nodes[i].id
            old = self.score.get(nid)
            self.score[nid] = float(v) if old is None else old + SMOOTHING * (float(v) - old)

    @property
    def allocated(self):
        return {nid for nid, s in self.score.items() if s > 1.0}

    @property
    def seen(self):
        return set(self.score)


class Plan:
    """Target build compared with what is allocated."""

    def __init__(self, tree, spec):
        self.tree = tree
        self.spec = spec
        self.start = tree.class_start(spec.class_id).id
        self.target = {n for n in spec.nodes
                       if n in tree.nodes and not tree.nodes[n].ascendancy and tree.nodes[n].kind != "start"}

    def status(self, allocated, seen):
        """Returns dict with done / next / todo / wrong node sets and the order
        in which the remaining target nodes can be taken."""
        done = self.target & allocated
        todo = self.target - allocated
        wrong = {n for n in allocated - self.target if not self.tree.nodes[n].ascendancy}
        # Breadth-first from what's allocated (and the class start) through the
        # target nodes: step 1 can be taken now, step 2 after that, ...
        reached = done | {self.start}
        step = {}
        frontier = deque()
        for n in todo:
            if self.tree.nodes[n].neighbours & reached:
                step[n] = 1
                frontier.append(n)
        while frontier:
            n = frontier.popleft()
            for m in self.tree.nodes[n].neighbours:
                if m in todo and m not in step:
                    step[m] = step[n] + 1
                    frontier.append(m)
        nxt = {n for n, s in step.items() if s == 1}
        # masteries hang off notables and are only allocatable once one of their group's notables is
        nxt |= {n for n in todo if self.tree.nodes[n].kind == "mastery"
                and any(self.tree.nodes[m].group == self.tree.nodes[n].group for m in done)}
        return {"done": done, "next": nxt, "todo": todo, "wrong": wrong & seen, "step": step}
