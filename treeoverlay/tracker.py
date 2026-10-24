"""Find where the passive tree is on screen.

The in-game tree only pans and zooms, so the screen position of a tree point
is   screen = scale * tree + (tx, ty).

Workflow:
  1. Calibration: the player hovers two known nodes and presses the hotkey.
     That gives the first transform.
  2. Every captured frame's ORB features are converted to tree coordinates
     with the current transform and stored in a "map" (descriptor + tree
     position). The map grows as the player pans around.
  3. Later frames are localised by matching their features against the map
     and fitting scale + translation with RANSAC. No chaining from frame to
     frame, so errors don't add up.
When too few features match (tree closed, unmapped area) the tracker reports
"lost" and the overlay hides.
"""
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


# two threads are plenty for these image sizes; all cores would make the game share its CPU
cv2.setNumThreads(2)

_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], np.uint8)
_KEY = 1 << 24   # packs a 2D grid cell into one int64


@dataclass
class Transform:
    scale: float
    tx: float
    ty: float

    def to_screen(self, x, y):
        return self.scale * x + self.tx, self.scale * y + self.ty

    def to_tree(self, sx, sy):
        return (sx - self.tx) / self.scale, (sy - self.ty) / self.scale

    @staticmethod
    def from_points(tree_pts, screen_pts):
        """Least squares scale + translation from >= 2 point pairs."""
        t = np.asarray(tree_pts, np.float64)
        s = np.asarray(screen_pts, np.float64)
        tc, sc = t - t.mean(0), s - s.mean(0)
        scale = float((tc * sc).sum() / (tc * tc).sum())
        tx, ty = s.mean(0) - scale * t.mean(0)
        return Transform(scale, float(tx), float(ty))


class Tracker:
    WORK_WIDTH = 1280          # frames are downscaled to this width for ORB
    MIN_INLIERS = 18
    MAP_INLIERS = 35           # only grow the map from confident frames
    MAX_MAP = 60000
    CONFIRM_REF = 25           # reference matches needed to trust a tracked view
    STATIC_DIFF = 0.6          # mean grey change (0-255) below which a frame counts as unchanged
    PHASE_TRUST = 0.5          # phase-correlation confidence for a pan taken without checking
    VERIFY_EVERY = 0.3         # s; a full check at least this often while panning

    MIN_REF = 10               # without calibration a lock needs this much reference support

    # Parts of the screen that stay put while the tree pans (fractions of the
    # game window: x0, y0, x1, y1). PoE keeps the HUD visible over the tree, and
    # learning the globes or the skill bar would make the tracker "see" the
    # tree in gameplay too.
    POE_HUD = [(0.0, 0.742, 0.117, 1.0),     # life globe
               (0.117, 0.865, 0.29, 1.0),    # flasks
               (0.706, 0.865, 0.883, 1.0),   # skill bar
               (0.882, 0.756, 1.0, 1.0),     # mana globe
               (0.0, 0.975, 1.0, 1.0),       # experience bar
               (0.331, 0.0, 0.667, 0.083),   # "Skills" header with search box
               (0.39, 0.083, 0.61, 0.17),    # refund / apply / cancel buttons
               (0.0, 0.67, 0.012, 0.72)]     # small buttons at the left edge

    def __init__(self, mask_rects=None):
        self.orb = cv2.ORB_create(nfeatures=2500, scaleFactor=1.2, nlevels=8, fastThreshold=12)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        # a list of its own: the worker updates it in place when the window size changes,
        # and the allocation reader and ascendancy finder share it
        self.mask_rects = list(self.POE_HUD) if mask_rects is None else mask_rects
        self.auto_masks = mask_rects is None
        self.gate, self.gate_shape, self.gate_path = None, None, None
        self.gate_candidate, self.gate_off = None, False
        self.reset()

    def reset(self):
        """Forget the learned map (the reference map from the rendered tree stays)."""
        self.transform = None
        self.map_desc = np.zeros((0, 32), np.uint8)
        self.map_pts = np.zeros((0, 2), np.float32)   # tree coords
        self.map_scale = np.zeros((0,), np.float32)    # work-image px per tree unit when seen
        self.lost_frames = 0
        self.last_inliers = 0
        self.last_ref = 0
        self.last_ms = 0.0
        self.keyframes = []   # (centre x, centre y, scale) of views already added to the map
        self.prev_thumb = None
        self._hann = None
        self.last_static = False
        self.last_fast = False
        self.last_verified = 0.0
        self.unverified = False
        self._lp_win = None
        self.last_path, self.last_zoom_info, self.last_phase = "", None, None
        self.checked = None
        self.zoom_levels, self.last_scale, self.cursor = [], None, None
        self.user_calibrated = False
        if getattr(self, "ref_pts", None) is not None:
            self.map_pts, self.map_desc = self.ref_pts.copy(), self.ref_desc.copy()
            self.map_scale = self.ref_scale.copy()
        self.n_ref = len(self.map_pts)

    @property
    def calibrated(self):
        return self.transform is not None or len(self.map_pts) > 0

    # -- reference map from the rendered tree -----------------------------
    REFERENCE_LEVELS = (0.54, 0.40, 0.30, 0.225, 0.17, 0.125)

    def load_reference(self, render_png, meta, cache=None, levels=None):
        """Seed the map with features of the tree rendered from the game's own
        sprites, so the tree can be found without manual calibration."""
        if cache and Path(cache).exists():
            d = np.load(cache)
            self.ref_pts, self.ref_desc, self.ref_scale = d["pts"], d["desc"], d["scale"]
        else:
            img = cv2.imread(str(render_png), cv2.IMREAD_GRAYSCALE)
            z, ox, oy = meta["zoom"], meta["origin_x"], meta["origin_y"]
            orb = cv2.ORB_create(nfeatures=2500, scaleFactor=1.2, nlevels=8, fastThreshold=12)
            all_pts, all_desc, all_scale = [], [], []
            # feature scale = pixels per tree unit in the downscaled work image
            for k in levels or self.REFERENCE_LEVELS:
                level = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k != 1 else img
                tile, step = 1280, 1024
                for y in range(0, level.shape[0], step):
                    for x in range(0, level.shape[1], step):
                        part = level[y:y + tile, x:x + tile]
                        if part.shape[0] < 64 or part.shape[1] < 64:
                            continue
                        kps, desc = orb.detectAndCompute(part, None)
                        if desc is None:
                            continue
                        p = np.array([kp.pt for kp in kps], np.float32) + (x, y)
                        all_pts.append(p / (z * k) + (ox, oy))
                        all_desc.append(desc)
                        all_scale.append(np.full(len(desc), z * k, np.float32))
            self.ref_pts = np.vstack(all_pts).astype(np.float32)
            self.ref_desc = np.vstack(all_desc)
            self.ref_scale = np.concatenate(all_scale)
            if cache:
                np.savez_compressed(cache, pts=self.ref_pts, desc=self.ref_desc, scale=self.ref_scale)
        self.reset()

    # -- features -------------------------------------------------------
    def _features(self, frame, work_width=None):
        """ORB features of a frame downscaled to work_width (default WORK_WIDTH),
        as full-resolution screen positions."""
        h, w = frame.shape[:2]
        ww = work_width or self.WORK_WIDTH
        f = ww / w if w > ww else 1.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        if f != 1.0:
            gray = cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        mask = np.full(gray.shape, 255, np.uint8)
        gh, gw = gray.shape
        for x0, y0, x1, y1 in self.mask_rects:
            mask[int(gh * y0):int(gh * y1), int(gw * x0):int(gw * x1)] = 0
        kps, desc = self.orb.detectAndCompute(gray, mask)
        if work_width is None:
            self.work_f = f
        if desc is None:
            return np.zeros((0, 2), np.float32), np.zeros((0, 32), np.uint8)
        pts = np.array([k.pt for k in kps], np.float32) / f   # back to full-res screen px
        return pts, desc

    # -- map ------------------------------------------------------------
    def _add_to_map(self, pts, desc, transform, inlier_idx=None):
        tree = np.column_stack(transform.to_tree(pts[:, 0], pts[:, 1])).astype(np.float32)
        keep = np.ones(len(pts), bool)
        if inlier_idx is not None:
            keep[inlier_idx] = False  # already in the map
        if len(self.map_pts):
            # skip features that sit right on top of an existing map point in view
            lo, hi = tree.min(0), tree.max(0)
            near = self.map_pts[((self.map_pts >= lo) & (self.map_pts <= hi)).all(1)]
            cell = 6.0 / transform.scale
            existing = set(map(tuple, np.floor(near / cell).astype(np.int64)))
            keys = np.floor(tree / cell).astype(np.int64)
            keep &= np.array([tuple(k) not in existing for k in keys], bool)
        self.map_pts = np.vstack([self.map_pts, tree[keep]])
        self.map_desc = np.vstack([self.map_desc, desc[keep]])
        self.map_scale = np.concatenate([self.map_scale, np.full(keep.sum(), transform.scale * self.work_f, np.float32)])
        extra = len(self.map_pts) - self.n_ref - self.MAX_MAP
        if extra > 0:  # drop the oldest learned points, never the reference ones
            cut = np.r_[0:self.n_ref, self.n_ref + extra:len(self.map_pts)]
            self.map_pts, self.map_desc, self.map_scale = self.map_pts[cut], self.map_desc[cut], self.map_scale[cut]

    # -- public ---------------------------------------------------------
    def calibrate(self, frame, transform):
        """Start a new learned map from a frame whose transform is roughly known
        (from the hovered nodes). With a reference map the guess is refined by
        matching first; the hover points are only a few pixels accurate."""
        self.reset()
        h, w = frame.shape[:2]
        pts, desc = self._features(frame)
        if self.n_ref:
            refined = self._guided(pts, desc, transform, w, h, radius_px=40)
            if refined is not None and refined[3] >= 30:
                self.transform = refined[0]
                return self.transform
        self.transform = transform
        self.user_calibrated = True
        self._new_view(transform, w, h)
        self._add_to_map(pts, desc, transform)
        return transform

    def update(self, frame, cursor=None):
        """Localise a frame. Returns the Transform or None when lost. cursor:
        mouse position inside the frame, used as the likely zoom centre."""
        t0 = time.perf_counter()
        self.cursor = cursor
        if self.gate_closed(frame):
            # Tree not open: skip the expensive search and keep the last view,
            # the game usually reopens the tree where it was.
            self.last_inliers = self.last_ref = 0
            result = None
        else:
            result = self._localise(frame)
            if result is not None and self.gate is None and not self.gate_off and self.last_ref >= self.GATE_LEARN_REF:
                self._learn_gate(frame, result)
        self.last_ms = (time.perf_counter() - t0) * 1000
        return result

    # -- "is the tree open?" ----------------------------------------------
    # The tree screen has a fixed "Skills" header. Once a confident lock shows
    # the tree is open, that patch is kept as a template (so it works in any
    # game language and UI theme) and the tracker only runs while it's there.
    GATE_RECT = (0.42, 0.0, 0.56, 0.055)
    GATE_LEARN_REF = 150
    GATE_MIN_SCORE = 0.7

    def fit_to_window(self, w, h, ui_scale=1.0):
        """HUD masks and header patch for this window size (unless masks were given)."""
        from .hud import gate_rect, ui_rects
        if self.auto_masks:
            self.mask_rects[:] = ui_rects(w, h, ui_scale)
        self.GATE_RECT = gate_rect(w, h, ui_scale)

    def _gate_patch(self, frame, pad=0.0):
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self.GATE_RECT
        x0, x1 = max(0.0, x0 - pad), min(1.0, x1 + pad)
        y0, y1 = max(0.0, y0 - pad), min(1.0, y1 + pad)
        patch = frame[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.ndim == 3 else patch
        return cv2.resize(patch, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)

    def _learn_gate(self, frame, t):
        """Take the header patch as the gate only once it has stayed the same
        while the tree moved underneath; otherwise that spot isn't fixed UI
        (other layout or aspect ratio) and the gate stays off."""
        patch = self._gate_patch(frame)
        if self.gate_candidate is None:
            self.gate_candidate = (patch, t)
            return
        cand, ct = self.gate_candidate
        if abs(t.tx - ct.tx) + abs(t.ty - ct.ty) < 50 and abs(t.scale / ct.scale - 1) < 0.1:
            return   # the view hasn't moved enough to tell
        same = cand.shape == patch.shape and float(cv2.matchTemplate(patch, cand, cv2.TM_CCOEFF_NORMED).max()) > 0.9
        self.gate_candidate = None
        if not same:
            self.gate_off = True
            return
        self.gate = cand
        self.gate_shape = frame.shape[:2]
        if self.gate_path:
            cv2.imwrite(str(self.gate_path), self.gate)

    def gate_score(self, frame):
        region = self._gate_patch(frame, pad=0.01)
        if region.shape[0] < self.gate.shape[0] or region.shape[1] < self.gate.shape[1]:
            return 0.0
        return float(cv2.matchTemplate(region, self.gate, cv2.TM_CCOEFF_NORMED).max())

    def gate_closed(self, frame):
        if self.gate is None:
            return False
        if frame.shape[:2] != self.gate_shape:   # window resized: learn it again
            self.gate, self.gate_candidate, self.gate_off = None, None, False
            return False
        return self.gate_score(frame) < self.GATE_MIN_SCORE

    def use_gate_file(self, path, shape):
        """Keep the learned header in path; shape is the (height, width) of the
        game window it belongs to."""
        self.gate_path, self.gate_shape = Path(path), tuple(shape)
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if self.gate_path.exists() else None
        self.gate, self.gate_candidate, self.gate_off = img, None, False

    def _thumb(self, frame):
        """Small grey copy with the HUD flattened, for cheap frame-to-frame checks."""
        h, w = frame.shape[:2]
        f = self.THUMB_HEIGHT / h     # by height: wide screens get a wider thumbnail, not a coarser one
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        g = cv2.resize(g, (int(w * f), self.THUMB_HEIGHT), interpolation=cv2.INTER_AREA).astype(np.float32)
        th, tw = g.shape
        for x0, y0, x1, y1 in self.mask_rects:
            g[int(th * y0):int(th * y1), int(tw * x0):int(tw * x1)] = 0
        return g, f

    def _pan_window(self, shape):
        """Weights for phase correlation: a Hann window that also fades to zero
        over the HUD, with soft edges. HUD that never moves (and a hard mask
        border) would otherwise pull every pan estimate towards zero."""
        key = (shape, tuple(map(tuple, self.mask_rects)))
        if self._hann is None or self._hann[0] != key:
            th, tw = shape
            valid = np.ones(shape, np.float32)
            for x0, y0, x1, y1 in self.mask_rects:
                valid[int(th * y0):int(th * y1) + 1, int(tw * x0):int(tw * x1) + 1] = 0
            valid = cv2.erode(valid, np.ones((7, 7), np.uint8))
            valid = cv2.GaussianBlur(valid, (0, 0), 3)
            self._hann = (key, cv2.createHanningWindow((tw, th), cv2.CV_32F) * valid)
        return self._hann[1]

    THUMB_HEIGHT = 270

    def _localise(self, frame):
        self.last_path = "?"
        self.last_static = False
        self.last_fast = False
        self.last_diff = None
        if not len(self.map_pts):
            return None
        h, w = frame.shape[:2]
        thumb, tf = self._thumb(frame)
        prev, self.prev_thumb = self.prev_thumb, thumb
        shift = None
        zoom_guess = None
        if prev is not None and prev.shape == thumb.shape and self.transform is not None and self.lost_frames == 0:
            self.last_diff = float(np.abs(thumb - prev).mean())
            if self.last_diff < self.STATIC_DIFF and not self.unverified:
                self.last_static = True
                self.last_path = "still"
                self.last_verified = time.perf_counter()   # same picture as the checked one
                return self.transform          # nothing moved: keep the last result
            # Fast results are only taken while a full check happened moments
            # ago, and never for the first still frame after them, which gets
            # the full check instead.
            may_trust = (self.last_diff >= self.STATIC_DIFF and
                         time.perf_counter() - self.last_verified < self.VERIFY_EVERY)
            # phaseCorrelate applies the window to its inputs in place: give it copies
            (dx, dy), resp = cv2.phaseCorrelate(prev.copy(), thumb.copy(), self._pan_window(thumb.shape).copy())
            if resp > 0.15:
                shift = (dx / tf, dy / tf)
            t0 = self.transform
            if resp > self.PHASE_TRUST and may_trust:
                # A clean pan: take the shift as it is (a few ms instead of 50-100).
                self.last_path = "pan-fast"
                return self._fast(Transform(t0.scale, t0.tx + dx / tf, t0.ty + dy / tf))
            else:
                # Not a clean pan: most likely the zoom animation. Estimate zoom and
                # shift from the thumbnails (Fourier-Mellin, ~12 ms).
                # measured against the last checked frame, so errors don't add up
                # over the animation's frames
                base_thumb, base_t = self.checked if self.checked and self.checked[0].shape == thumb.shape else (prev, t0)
                zoom_guess = self._zoom_estimate(base_thumb, thumb, tf, w, h, base_t)
                # trusted unchecked only for small zoom changes; near the
                # estimate's 1.6x limit it can be 10+ px off
                if zoom_guess is not None and may_trust and 0.77 < zoom_guess.scale / base_t.scale < 1.3:
                    self.last_path = "zoom-fast"
                    return self._fast(zoom_guess)
            self.last_phase = (round(float(resp), 2), may_trust)

        pts, desc = self._features(frame)
        if len(pts) < self.MIN_INLIERS:
            return self._lost()

        found = None
        if zoom_guess is not None:
            found = self._guided(pts, desc, zoom_guess, w, h, radius_px=12)
            if found is not None and found[3] < 2 * self.CONFIRM_REF:
                found = None
            self.last_path = "zoom-checked" if found else "zoom-failed"
        if found is None and shift is not None:
            # A pan: phase correlation gives the move in a few ms, the guided
            # match confirms it against the map.
            t0 = self.transform
            guess = Transform(t0.scale, t0.tx + shift[0], t0.ty + shift[1])
            found = self._guided(pts, desc, guess, w, h, radius_px=12)
            if found is not None and found[3] < 150:
                # weakly supported: a second pass from the refined view picks up the edges too
                found = self._guided(pts, desc, found[0], w, h, radius_px=8) or found
            if found is not None and (found[3] < 2 * self.CONFIRM_REF or abs(found[0].scale / t0.scale - 1) > 0.03):
                found = None
            if found is not None:
                self.last_path = "pan-checked"
        if (found is None and shift is None and self.transform is not None and self.lost_frames == 0
                and prev is not None and prev.shape == thumb.shape):
            found = self._try_zoom(pts, desc, w, h, prev, thumb, tf)
            if found:
                self.last_path = "zoom-step"
        if found is None and self.transform is not None and self.lost_frames < 5:
            # Tracking: a descriptor match around the last view gives the motion
            # (zoom included), a guided match at that position then pins it down
            # and counts how much of the rendered reference agrees.
            moved = self._windowed(pts, desc, self.transform, w, h)
            if moved is not None:
                found = self._guided(pts, desc, moved[0], w, h, radius_px=12) or moved
                self.last_path = "windowed"
        if found is None or found[3] < self.CONFIRM_REF:
            # Lost, never found, or the reference doesn't back the tracked view
            # (a fast pan can slide onto a look-alike part of the tree): search
            # the whole map. Node icons repeat all over the tree, so take every
            # best match, let RANSAC sort it out and confirm with a guided match.
            # When zoomed in further than the reference covers, the same search
            # on a half-size copy of the frame still finds it.
            for coarse in (False, True):
                gp, gd = (self._features(frame, self.WORK_WIDTH // 2) if coarse else (pts, desc))
                if len(gp) < self.MIN_INLIERS:
                    continue
                guess = self._match(gp, gd, np.arange(len(self.map_pts)), w, ratio_test=False)
                if guess is None:
                    continue
                cand = self._guided(pts, desc, guess[0], w, h, radius_px=12)
                if (cand is not None and cand[1] >= 30 and abs(cand[0].scale / guess[0].scale - 1) < 0.05
                        and (found is None or cand[3] > 1.5 * found[3] + 10)):
                    found = cand
                    self.last_path = "search"
                    break
        if found is None or (found[3] < self.MIN_REF and not self.user_calibrated):
            return self._lost()

        t, n_in, inlier_q, n_ref = found
        self._note_zoom(t.scale, h)
        self.transform = t
        self.last_verified = time.perf_counter()
        self.unverified = False
        self.checked = (thumb, t)   # the last frame checked against the map
        self.lost_frames = 0
        self.last_inliers = n_in
        self.last_ref = n_ref
        # Learn only while the rendered reference clearly agrees (or the player
        # calibrated), otherwise a wrong lock would teach itself and never let go.
        anchored = n_ref >= 2 * self.CONFIRM_REF or self.user_calibrated
        if n_in >= self.MAP_INLIERS and anchored and self._new_view(t, w, h):
            self._add_to_map(pts, desc, t, inlier_idx=inlier_q)
        return t

    def _fast(self, t):
        """Take a result without checking it against the map (yet)."""
        self.transform = t
        self.last_fast = True
        self.unverified = True
        return t

    LP_SIZE = (1024, 128)   # log-polar grid: radius x angle; finer radius = finer zoom steps

    def _zoom_estimate(self, prev, thumb, tf, w, h, base):
        """Zoom factor and shift between two thumbnails, from the log-polar
        magnitude spectra (Fourier-Mellin). Measured on zoom animations: about
        2 px median, 4 px worst at the screen corners."""
        th, tw = thumb.shape
        if self._lp_win is None or self._lp_win.shape != thumb.shape:
            self._lp_win = cv2.createHanningWindow((tw, th), cv2.CV_32F)
        win = self._lp_win
        centre, max_r = (tw / 2, th / 2), min(tw, th) / 2
        flags = cv2.WARP_POLAR_LOG | cv2.INTER_LINEAR | cv2.WARP_FILL_OUTLIERS

        def logpolar(img):
            spectrum = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(img * win)))).astype(np.float32)
            return cv2.warpPolar(spectrum, self.LP_SIZE, centre, max_r, flags)

        (dr, da), resp = cv2.phaseCorrelate(logpolar(prev), logpolar(thumb))
        angle = (da * 360.0 / self.LP_SIZE[1]) % 180.0      # the spectrum repeats every 180 degrees
        k = float(np.exp(-dr * np.log(max_r) / self.LP_SIZE[0]))
        self.last_zoom_info = {"resp": round(float(resp), 3), "angle": round(min(angle, 180 - angle), 2), "k": round(k, 4)}
        if resp < 0.1 or min(angle, 180.0 - angle) > 3.0 or not (0.6 < k < 1.67) or abs(k - 1) < 0.003:
            return None   # not a clean zoom (the tree never rotates)
        M = np.float32([[k, 0, centre[0] * (1 - k)], [0, k, centre[1] * (1 - k)]])
        (dx, dy), resp2 = cv2.phaseCorrelate(cv2.warpAffine(prev, M, (tw, th)), thumb.copy(), win.copy())
        self.last_zoom_info["resp2"] = round(float(resp2), 3)
        if resp2 < self.PHASE_TRUST:
            return None
        t = base
        cx, cy = w / 2, h / 2
        return Transform(t.scale * k, k * (t.tx - cx) + cx + dx / tf, k * (t.ty - cy) + cy + dy / tf)

    # -- zoom ----------------------------------------------------------------
    # The game zooms in fixed steps (seen at 2560x1440: 0.130 0.144 0.180 0.234
    # 0.288 0.324 0.414 0.684, with an animation in between). After a zoom,
    # trying the neighbouring steps around the likely centre and confirming with
    # a guided match is much quicker than the general search.
    # Zoom levels seen at 2560x1440. The game zooms around the mouse cursor and
    # one wheel flick can jump several levels between two captured frames.
    SEED_ZOOM_1440 = (0.130, 0.144, 0.180, 0.234, 0.288, 0.324, 0.414, 0.504, 0.594, 0.684, 0.720)

    def _note_zoom(self, scale, h):
        """Remember zoom steps the view settles on (same scale twice running)."""
        if not self.zoom_levels:
            self.zoom_levels = [z * h / 1440 for z in self.SEED_ZOOM_1440]
        last, self.last_scale = self.last_scale, scale
        if last and abs(scale / last - 1) < 0.005 and all(abs(scale / z - 1) > 0.015 for z in self.zoom_levels):
            self.zoom_levels = sorted(self.zoom_levels + [scale])

    @staticmethod
    def _overlap_ncc(warped, valid, thumb):
        """Correlation of two thumbnails over the area both actually show."""
        m = valid > 0.5
        if m.sum() < 2000:
            return -1.0
        a, b = warped[m], thumb[m]
        a = a - a.mean(); b = b - b.mean()
        d = float(np.sqrt((a * a).sum() * (b * b).sum()))
        return float((a * b).sum() / d) if d > 0 else -1.0

    def _try_zoom(self, pts, desc, w, h, prev_thumb, thumb, tf):
        """After a zoom: try every known zoom level around the cursor (the
        game's zoom centre; the screen centre if the cursor is unknown), rank
        them by how well the zoomed previous thumbnail matches, and confirm the
        best with a guided match."""
        t = self.transform
        cur = t.scale
        levels = [z for z in self.zoom_levels if abs(z / cur - 1) > 0.02]
        if self.cursor and 0 <= self.cursor[0] < w and 0 <= self.cursor[1] < h:
            anchors = [tuple(self.cursor)]
        else:
            anchors = [(w / 2, h / 2)]
        ones = np.ones_like(prev_thumb)
        ranked = []
        for anchor in anchors:
            for z in levels:
                k = z / cur
                M = np.float32([[k, 0, anchor[0] * tf * (1 - k)], [0, k, anchor[1] * tf * (1 - k)]])
                size = thumb.shape[::-1]
                warped = cv2.warpAffine(prev_thumb, M, size)
                valid = cv2.warpAffine(ones, M, size)
                ranked.append((self._overlap_ncc(warped, valid, thumb), anchor, z))
        ranked.sort(reverse=True)
        for score, (ax, ay), z in ranked[:2]:
            k = z / cur
            guess = Transform(z, ax - (ax - t.tx) * k, ay - (ay - t.ty) * k)
            # the cursor is a few px off the true zoom centre; that grows with the jump
            radius = 12 if 0.7 < k < 1.4 else 20
            g = self._guided(pts, desc, guess, w, h, radius_px=radius)
            if g is not None and g[3] >= 2 * self.CONFIRM_REF and abs(g[0].scale / z - 1) < 0.03:
                return g
        return None

    def _guided(self, pts, desc, t, w, h, radius_px):
        """Check a guess: for each frame feature look only at map points within
        radius_px of where the guess puts it. Repeated icons elsewhere in the
        tree can't interfere, which a plain descriptor match can't avoid."""
        x0, y0 = t.to_tree(-radius_px, -radius_px)
        x1, y1 = t.to_tree(w + radius_px, h + radius_px)
        ratio = self.map_scale / (t.scale * self.work_f)
        cand = np.nonzero((self.map_pts[:, 0] > x0) & (self.map_pts[:, 0] < x1) &
                          (self.map_pts[:, 1] > y0) & (self.map_pts[:, 1] < y1) &
                          (ratio > 0.4) & (ratio < 2.5))[0]
        if len(cand) < self.MIN_INLIERS:
            return None
        cell = radius_px / t.scale
        cp = self.map_pts[cand]
        ck = np.floor(cp / cell).astype(np.int64)
        ckey = ck[:, 0] * _KEY + ck[:, 1]
        order = np.argsort(ckey, kind="stable")
        skey = ckey[order]
        proj = np.column_stack(t.to_tree(pts[:, 0], pts[:, 1]))
        qk = np.floor(proj / cell).astype(np.int64)
        qs, cs = [], []
        for dx in (-1, 0, 1):          # all map points in the 3x3 cells around each feature
            for dy in (-1, 0, 1):
                k = (qk[:, 0] + dx) * _KEY + (qk[:, 1] + dy)
                lo = np.searchsorted(skey, k, "left")
                cnt = np.searchsorted(skey, k, "right") - lo
                if not cnt.any():
                    continue
                q = np.repeat(np.arange(len(pts)), cnt)
                offs = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
                qs.append(q)
                cs.append(order[np.repeat(lo, cnt) + offs])
        if not qs:
            return None
        q, c = np.concatenate(qs), np.concatenate(cs)
        near = ((cp[c] - proj[q]) ** 2).sum(1) < cell * cell
        q, c = q[near], c[near]
        ham = _POPCOUNT[np.bitwise_xor(self.map_desc[cand[c]], desc[q])].sum(1, dtype=np.int32)
        o = np.lexsort((ham, q))                     # best descriptor per feature
        q, c, ham = q[o], c[o], ham[o]
        best = np.r_[True, q[1:] != q[:-1]] & (ham < 50)
        q, c = q[best], c[best]
        src, dst, qidx, is_ref = cp[c], pts[q], q, cand[c] < self.n_ref
        if len(src) < self.MIN_INLIERS:
            return None
        src, dst = np.float32(src), np.float32(dst)
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=max(3.0, w / 500),
                                             maxIters=2000, confidence=0.999)
        if M is None:
            return None
        inl = inl.ravel().astype(bool)
        n_in = int(inl.sum())
        if n_in < self.MIN_INLIERS:
            return None
        return Transform.from_points(src[inl], dst[inl]), n_in, qidx[inl], int(is_ref[inl].sum())

    def _windowed(self, pts, desc, t, w, h):
        """Match against map points around view t, seen at a similar zoom."""
        x0, y0 = t.to_tree(-w * 0.3, -h * 0.3)
        x1, y1 = t.to_tree(w * 1.3, h * 1.3)
        ratio = self.map_scale / (t.scale * self.work_f)
        sel = ((self.map_pts[:, 0] > x0) & (self.map_pts[:, 0] < x1) &
               (self.map_pts[:, 1] > y0) & (self.map_pts[:, 1] < y1) &
               (ratio > 0.4) & (ratio < 2.5))
        cand = np.nonzero(sel)[0]
        if len(cand) < self.MIN_INLIERS:
            return None
        return self._match(pts, desc, cand, w, ratio_test=True)

    def _new_view(self, t, w, h):
        """Only learn from views that differ from earlier keyframes (moved by a
        quarter screen or zoomed by 25 %), so the map doesn't fill with copies."""
        cx, cy = t.to_tree(w / 2, h / 2)
        reach = 0.25 * min(w, h) / t.scale
        for kx, ky, ks in self.keyframes:
            if 0.8 < ks / t.scale < 1.25 and abs(kx - cx) < reach and abs(ky - cy) < reach:
                return False
        self.keyframes.append((cx, cy, t.scale))
        return True

    def _match(self, pts, desc, cand, width, ratio_test):
        if ratio_test:
            matches = self.matcher.knnMatch(desc, self.map_desc[cand], k=2)
            good = [m[0] for m in matches
                    if len(m) == 2 and m[0].distance < 0.8 * m[1].distance and m[0].distance < 64]
            iters, min_in = 3000, self.MIN_INLIERS
        else:
            # the three nearest descriptors each; the windowed check afterwards
            # throws out wrong guesses, so a weak guess here is fine
            good = [m for ms in self.matcher.knnMatch(desc, self.map_desc[cand], k=3) for m in ms if m.distance < 50]
            iters, min_in = 30000, 12
        if len(good) < min_in:
            return None
        src = np.float32([self.map_pts[cand[m.trainIdx]] for m in good])
        dst = np.float32([pts[m.queryIdx] for m in good])
        qidx = np.array([m.queryIdx for m in good])
        is_ref = np.array([cand[m.trainIdx] < self.n_ref for m in good])

        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=max(3.0, width / 500),
                                             maxIters=iters, confidence=0.999)
        if M is None:
            return None
        inl = inl.ravel().astype(bool)
        n_in = int(inl.sum())
        scale = float(np.hypot(M[0, 0], M[1, 0]))
        angle = abs(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
        if n_in < min_in or angle > 2.0 or not (0.02 < scale < 2.0):
            return None
        # The tree never rotates: refit scale + translation only on the inliers.
        return Transform.from_points(src[inl], dst[inl]), n_in, qidx[inl], int(is_ref[inl].sum())

    def _lost(self):
        self.prev_thumb = None
        self.lost_frames += 1
        self.last_inliers = 0
        return None
