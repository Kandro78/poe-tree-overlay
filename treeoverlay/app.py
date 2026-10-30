"""Control window + click-through overlay over the Path of Exile window."""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import queue
import threading
import sys
import time
import traceback
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtCore import QRect
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QProgressDialog, QPushButton, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from . import build, character, pob, theme, updater
from .ascendancy import AscendancyFinder
from .capture import Capture
from .cluster import ClusterLayout
from .picker import TreePicker
from .progress import AllocationReader, Plan, merge_allocations
from .settings_dialog import SettingsDialog
from .tracker import Tracker, Transform
from .tree import CLASS_NAMES, DATA_DIR, PassiveTree

ROOT = DATA_DIR.parent
SETTINGS = ROOT / "settings.json"
DEFAULTS = {"last_input": "", "spec": -1, "mask_rects": None, "ui_scale": 1.0, "fps": 8, "show_progress": True,
            "start_minimized": False, "follow_pob": True,
            "account": "", "character": "", "realm": "pc",
            "show_labels": True, "route_length": 8, "auto_next_tree": True, "keys": {"next_tree": "F6", "calibrate": "F7", "toggle": "F8", "reset": "F9"}}

user32 = ctypes.windll.user32
VK = {f"F{i}": 0x6F + i for i in range(1, 13)}
VK_LBUTTON = 0x01
WDA_EXCLUDEFROMCAPTURE = 0x11
DEFAULT_LATENCY = 0.03   # s the game shows the tree behind the cursor, until measured
PRESENT_DELAY = 0.004    # s from painting the overlay to it being on screen (best fit over 4 live traces)
LABEL_ZOOM = 0.3   # from this zoom on, all remaining notables/masteries get a label

COLORS = {"normal": QColor(80, 220, 255), "notable": QColor(255, 200, 60), "keystone": QColor(255, 90, 60),
          "mastery": QColor(200, 120, 255), "jewel": QColor(120, 255, 140), "start": QColor(80, 220, 255)}


def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 200, 60), 9))
    p.drawEllipse(10, 10, 44, 44)
    p.setPen(QPen(QColor(80, 220, 255), 5))
    p.drawEllipse(24, 24, 16, 16)
    p.end()
    return QIcon(pix)


def load_settings():
    s = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    keys = {**s["keys"], **saved.pop("keys", {})}   # new hotkeys appear in old settings files too
    s.update(saved)
    s["keys"] = keys
    return s


def save_settings(s):
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


def find_game():
    """Returns (hwnd, (left, top, width, height)) of the game's client area in
    physical pixels, or (None, None)."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(h, _):
        if user32.IsWindowVisible(h) and not user32.IsIconic(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, buf, 256)
            if buf.value == "POEWindowClass" and not os.environ.get("TREEOVERLAY_FAKE_GAME"):
                found.insert(0, h)
            else:
                user32.GetWindowTextW(h, buf, 256)
                if buf.value == "Path of Exile":
                    found.append(h)
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return None, None
    hwnd = found[0]
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    if rc.right < 100 or rc.bottom < 100:
        return None, None
    return hwnd, (pt.x, pt.y, rc.right, rc.bottom)


clock = time.perf_counter   # one clock for capture times and cursor samples (tests replace it)

_trace_file = None


def trace(**rec):
    """TREEOVERLAY_TRACE=<file>: one JSON line per tracker result and per
    overlay update during drags, to measure how well the rings follow."""
    global _trace_file
    path = os.environ.get("TREEOVERLAY_TRACE")
    if not path:
        return
    if _trace_file is None:
        _trace_file = open(path, "a", buffering=1)
    _trace_file.write(json.dumps(rec) + "\n")


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class Worker(QThread):
    """Captures the game window and runs the tracker."""
    # Transform or None, game rect, (allocated, seen, covered rects) or None,
    # (cursor x, cursor y, left button down) at the moment of the capture
    located = Signal(object, object, object, object)
    # ascendancy panel: (Transform, (x, y, radius)) while it's open, else None
    asc_located = Signal(object)
    status = Signal(str)

    def __init__(self, settings, tree):
        super().__init__()
        self.settings = settings
        self.requests = queue.Queue()
        self.enabled = True
        self.tracker = Tracker(settings["mask_rects"])
        self.reader = AllocationReader(tree, self.tracker.mask_rects)
        self.asc = AscendancyFinder(tree, self.tracker.mask_rects)
        self._asc_open = False
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        render = DATA_DIR / "render_0.2972.png"
        if not render.exists():
            self.status.emit("Rendering the reference tree (first start only)…")
            from . import render as render_tree
            img, meta = render_tree.render(PassiveTree())
            import cv2
            cv2.imwrite(str(render), img)
            (DATA_DIR / "render_0.2972.json").write_text(json.dumps(meta))
        self.status.emit("Building the reference map (first start only)…")
        meta = json.loads((DATA_DIR / "render_0.2972.json").read_text())
        self.tracker.load_reference(render, meta, cache=DATA_DIR / "refmap.npz")
        sct = Capture()
        self.status.emit(f"Ready (capture: {sct.backend})")
        try:
            while not self._stop:
                try:
                    self._step(sct)
                except Exception as exc:  # keep tracking alive, but say what went wrong
                    traceback.print_exc()
                    self.status.emit(f"Error: {exc}")
                    time.sleep(1.0)
        finally:
            sct.close()

    def _dump(self, frame, t):
        """TREEOVERLAY_DUMP_DIR: every 2 s keep a frame plus what the tracker made
        of it (the overlay itself is invisible to screenshots)."""
        out = os.environ.get("TREEOVERLAY_DUMP_DIR")
        burst = bool(os.environ.get("TREEOVERLAY_DUMP_BURST"))   # every frame, for replaying motion
        if not out or (not burst and time.time() - getattr(self, "_last_dump", 0) < 2.0):
            return
        self._last_dump = time.time()
        n = getattr(self, "_dump_n", 0)
        self._dump_n = n + 1
        import cv2
        cv2.imwrite(os.path.join(out, f"frame_{n % 300:03d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        rec = {"n": n, "file": f"frame_{n % 300:03d}.jpg", "time": time.strftime("%H:%M:%S"),
               "transform": t and [t.scale, t.tx, t.ty], "inliers": self.tracker.last_inliers,
               "ms": round(self.tracker.last_ms), "lost_frames": self.tracker.lost_frames,
               "learned": len(self.tracker.map_pts) - self.tracker.n_ref,
               "allocated": sorted(self.reader.allocated), "seen": len(self.reader.seen),
               "static": self.tracker.last_static, "diff": getattr(self.tracker, "last_diff", None),
               "path": self.tracker.last_path, "zoom_info": self.tracker.last_zoom_info,
               "phase": self.tracker.last_phase, "t_capture": self._t_capture,
               "cursor": self.tracker.cursor and [int(c) for c in self.tracker.cursor]}
        with open(os.path.join(out, "dump.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def _step(self, sct):
        t0 = time.perf_counter()
        hwnd, rect = find_game()
        try:
            req = self.requests.get_nowait()
        except queue.Empty:
            req = None
        if rect is None:
            self.located.emit(None, None, None, None)
            self.status.emit("Path of Exile window not found")
            time.sleep(1.0)
            return
        if isinstance(req, tuple) and req[0] == "ascendancy":
            self.asc.set_ascendancy(req[1])
            self.reader.refresh_nodes()       # a new build may have brought cluster jewel nodes
            req = None
        if req == "refit":
            self._gate_size = None
            req = None
        if req == "reset":
            self.tracker.reset()
            self.reader.reset()
            self.status.emit("Learned map and allocations cleared")
        elif req == "reset_alloc":
            self.reader.reset()
            self.status.emit("Allocations cleared, reading them again")
        in_front = user32.GetForegroundWindow() == hwnd or os.environ.get("TREEOVERLAY_IGNORE_FOREGROUND")
        if not self.enabled or not in_front:
            if req not in (None, "reset", "reset_alloc"):
                self.requests.put(req)  # keep a calibration for when the game is in front
            self.located.emit(None, rect, None, None)
            time.sleep(0.2)
            return
        if rect[2:] != getattr(self, "_gate_size", None):
            # a new window size: HUD areas follow it (and the in-game UI scale)
            self._gate_size = rect[2:]
            ui = float(self.settings.get("ui_scale", 1.0))
            self.tracker.fit_to_window(rect[2], rect[3], ui)
            suffix = "" if ui == 1.0 else f"_ui{int(round(ui * 100))}"
            self.tracker.use_gate_file(DATA_DIR / f"gate_{rect[2]}x{rect[3]}{suffix}.png", (rect[3], rect[2]))
        cursor = (*cursor_pos(), bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000), clock())
        self._t_capture = time.time()
        frame, fresh = sct.grab(rect)
        grabbed = clock()
        if not fresh and req is None and getattr(self, "_had_frame", False):
            # The screen hasn't been redrawn since the last frame: nothing new to
            # track, and the old image must not be passed off as taken now.
            time.sleep(0.002 if cursor[2] else 1.0 / self.settings["fps"])
            return
        self._had_frame = True
        if isinstance(req, Transform):
            t = self.tracker.calibrate(frame, req)
            self.status.emit(f"Calibrated (scale {t.scale:.3f})")
        else:
            t = self.tracker.update(frame, (cursor[0] - rect[0], cursor[1] - rect[1]))
        progress = None
        if (t is not None and self.settings["show_progress"]
                and not self.tracker.last_static and not self.tracker.last_fast):
            self.reader.update(frame, t)
            progress = (frozenset(self.reader.allocated), frozenset(self.reader.seen), list(self.reader.covered_rects))
        # the ascendancy panel: not while dragging (the search takes ~80 ms)
        if t is not None and not cursor[2] and not self.tracker.last_fast:
            asc_t = self.asc.update(frame)
            if asc_t is not None or self._asc_open:
                self._asc_open = asc_t is not None
                self.asc_located.emit((asc_t, self.asc.circle) if asc_t is not None else None)
        elif t is None and self._asc_open:
            self._asc_open = False
            self.asc_located.emit(None)
        self._dump(frame, t)
        if t is not None:
            trace(k="track", tc=cursor[3], tg=grabbed, done=clock(), cx=cursor[0], cy=cursor[1], down=cursor[2],
                  tx=t.tx, ty=t.ty, s=t.scale, path=self.tracker.last_path)
        self.located.emit(t, rect, progress, cursor)
        state = "Locked" if t else "Tree closed" if self.tracker.last_path == "closed" else "Searching"
        self.status.emit(f"{state} · {self.tracker.last_path} · {self.tracker.last_inliers} matches · "
                         f"{self.tracker.last_ms:.0f} ms · map {len(self.tracker.map_pts) - self.tracker.n_ref}"
                         f"{'' if self.tracker.gate is not None else ' · learning tree screen'}")
        # while the picture changes, go again right away; when it stands still, idle
        moving = t is not None and (not self.tracker.last_static or cursor[2])   # button down: a drag may start
        pause = 1.0 / 60 if moving else 1.0 / self.settings["fps"]   # at most 60 updates/s while moving
        if t is None and self.tracker.gate is None and self.tracker.lost_frames > 3:
            pause = 0.5   # nothing learned yet to tell if the tree is open: search less often
        time.sleep(max(0.0, pause - (time.perf_counter() - t0)))


class SiteFetcher(QObject):
    """Fetches from pathofexile.com off the UI thread."""
    characters_ready = Signal(object, object)   # list or None, error text
    passives_ready = Signal(object, object, object)   # character, (hashes, masteries) or None, error text

    def fetch_characters(self, account, realm):
        def run():
            try:
                self.characters_ready.emit(character.characters(account, realm), None)
            except character.SiteError as exc:
                self.characters_ready.emit(None, str(exc))
        threading.Thread(target=run, daemon=True).start()

    def fetch_passives(self, account, name, realm):
        def run():
            try:
                self.passives_ready.emit(name, character.passives(account, name, realm), None)
            except character.SiteError as exc:
                self.passives_ready.emit(name, None, str(exc))
        threading.Thread(target=run, daemon=True).start()


class Overlay(QWidget):
    def __init__(self, tree, settings, ui_rects):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.tree = tree
        self.settings = settings
        self.ui_rects = ui_rects
        self.plan = None
        self.nodes, self.edges = [], []
        self.status = None           # Plan.status() result, None until something was read
        self.covered_rects = []      # screen areas a game tooltip covers right now
        self.route = []              # the next points to take, in order
        self.allocated = frozenset()
        self.asc = None              # (Transform, (x, y, radius)) of the open ascendancy panel
        self.asc_nodes = []
        self.transform = None
        self.rect_px = None
        self.message = ""            # calibration prompts
        self.pulse = QTimer(self, interval=60, timeout=self._tick)   # animates the "next" rings
        # drag prediction: base = last tracker result, press = where the left button went down
        self.base, self.base_cursor, self.press, self.drag_follows = None, None, None, True
        self.drag_start = None   # first tracker result and cursor of the current drag
        self.tree_moving = False # the tracker has seen the tree move with the cursor in this drag
        # The game draws the tree a little behind the mouse. The tree on screen
        # follows where the cursor was `latency` seconds ago; measured from drags.
        self.trail = deque(maxlen=800)   # (time, x, y) cursor samples, ~3 s
        self.latency = DEFAULT_LATENCY
        self.latency_measured = False
        self.drag_samples = []           # (capture time, tree tx, tree ty) during the current drag
        self.press_ref = None
        self.press_time = 0.0
        self.follow_timer = QTimer(self, interval=4, timeout=self._follow)   # ring updates while dragging
        self.picker = None   # clicks on the tree picker aren't drags of the tree
        self.show()
        # keep our own drawings out of the screenshots the tracker looks at
        if not os.environ.get("TREEOVERLAY_VISIBLE_TO_CAPTURE"):
            user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)

    def set_spec(self, spec):
        ClusterLayout(self.tree).add_to_tree(spec.nodes)      # the build's cluster jewel nodes
        self.plan = Plan(self.tree, spec)
        name = self.tree.ascendancy_name(spec.class_id, spec.ascend_id)
        self.asc_nodes = [self.tree.nodes[n] for n in spec.nodes
                          if n in self.tree.nodes and name and self.tree.nodes[n].ascendancy == name]
        self.nodes = [self.tree.nodes[n] for n in self.plan.target]
        self.edges = self.tree.edges(list(self.plan.target) + [self.plan.start])
        self.status = None
        self.route = []
        self.update()

    def set_progress(self, progress):
        if self.plan is None or progress is None:
            return
        allocated, seen, self.covered_rects = progress
        self.allocated = allocated
        self.status = self.plan.status(allocated, seen) if seen else None
        self.route = self.plan.route(self.status["done"], self.settings["route_length"]) if self.status else []

    def _tick(self):
        if self.transform is None:
            self.pulse.stop()
        self.update()

    def place(self, rect):
        if rect == self.rect_px:
            return
        self.rect_px = rect
        if rect is None:
            self.hide()
            return
        # Qt keeps each screen's top-left at its native position and scales
        # the inside by the screen's DPI factor.
        cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
        screen = QApplication.primaryScreen()
        for sc in QApplication.screens():
            g, d = sc.geometry(), sc.devicePixelRatio()
            if g.x() <= cx < g.x() + g.width() * d and g.y() <= cy < g.y() + g.height() * d:
                screen = sc
        dpr, geo = screen.devicePixelRatio(), screen.geometry()
        self.setGeometry(round(geo.x() + (rect[0] - geo.x()) / dpr), round(geo.y() + (rect[1] - geo.y()) / dpr),
                         math.ceil(rect[2] / dpr), math.ceil(rect[3] / dpr))
        self.show()

    def set_transform(self, t, cursor=None):
        """t: where the tracker found the tree in the frame captured while the
        cursor was at `cursor`."""
        prev, prev_cursor = self.base, self.base_cursor
        self.base, self.base_cursor = t, cursor
        if (t is not None and prev is not None and cursor and prev_cursor and cursor[2]
                and self.press is not None and abs(t.scale / prev.scale - 1) < 0.01):
            # Predicting starts with the press (quick flicks are over in a few
            # frames); as soon as the tracker sees the cursor travel while the
            # tree stays put (its edge, a button), the rings stop following.
            dcx, dcy = cursor[0] - prev_cursor[0], cursor[1] - prev_cursor[1]
            dtx, dty = t.tx - prev.tx, t.ty - prev.ty
            if math.hypot(dtx, dty) > 3 and dtx * dcx + dty * dcy > 0:
                self.tree_moving = True
            elif math.hypot(dcx, dcy) > 30 and math.hypot(dtx, dty) < 1:
                self.tree_moving = False
        if t is not None and cursor and len(cursor) > 3:
            if cursor[2] and self.press is not None and self.drag_follows:
                self.drag_samples.append((cursor[3], t.tx, t.ty))
        if t is not None and cursor and cursor[2] and self.press is not None:
            # Does the tree really move with the cursor in this drag? Judged on
            # the whole drag so far: the game shows a move a frame or so after
            # the cursor makes it, so single steps can look like "no movement".
            if self.drag_start is None:
                self.drag_start = (t, cursor)
            else:
                t0, c0 = self.drag_start
                dcx, dcy = cursor[0] - c0[0], cursor[1] - c0[1]
                if math.hypot(dcx, dcy) > 60:
                    follow = ((t.tx - t0.tx) * dcx + (t.ty - t0.ty) * dcy) / (dcx * dcx + dcy * dcy)
                    if os.environ.get("TREEOVERLAY_LOG"):
                        print(f"drag: tree moved {follow:.2f}x the cursor", flush=True)
                    self.drag_follows = follow > 0.3
        self.transform = self._predicted() if t is not None else None
        if self.press is not None and self.transform is not None:
            # every ring move counts: tracker results land between the cursor ticks
            cx, cy = cursor_pos()
            trace(k="tick", t=clock(), cx=cx, cy=cy, ox=self.transform.tx, oy=self.transform.ty,
                  pred=bool(self.drag_follows and self.tree_moving), lat=self.latency, src="track")
        if t is not None:
            if not self.pulse.isActive():
                self.pulse.start()
            if not self.follow_timer.isActive():
                self.follow_timer.start()
        self.update()

    def _predicted(self):
        """The tracker result moved on by how far the cursor has dragged the tree
        since that frame was captured: the tracker needs 30-150 ms per frame, the
        cursor is read right now."""
        t, c = self.base, self.base_cursor
        if t is None or c is None or self.press is None or not self.drag_follows or not self.tree_moving:
            return t
        if len(c) > 3:
            # the cursor right now, so the history reaches the present (the 8 ms
            # samples alone can be one tick old: 36 px at 4500 px/s)
            now = clock()
            x, y = cursor_pos()
            if not self.trail or now > self.trail[-1][0]:
                self.trail.append((now, x, y))
            # the captured frame showed the cursor of (capture - latency); the
            # screen, by the time this paint is shown, the cursor of (now + present - latency).
            # Only movement with the button down drags the tree: moving the
            # mouse before pressing must not count.
            then = self._cursor_at(max(c[3] - self.latency, self.press_time))
            soon = self._cursor_at(max(now + PRESENT_DELAY - self.latency, self.press_time))
            return Transform(t.scale, t.tx + soon[0] - then[0], t.ty + soon[1] - then[1])
        x, y = cursor_pos()
        return Transform(t.scale, t.tx + x - c[0], t.ty + y - c[1])

    def _cursor_at(self, when):
        """Cursor position at a past moment, interpolated from the samples."""
        trail = self.trail
        if when >= trail[-1][0]:
            return trail[-1][1], trail[-1][2]
        if when <= trail[0][0]:
            return trail[0][1], trail[0][2]
        lo, hi = 0, len(trail) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if trail[mid][0] <= when:
                lo = mid
            else:
                hi = mid
        (t0, x0, y0), (t1, x1, y1) = trail[lo], trail[hi]
        f = (when - t0) / (t1 - t0) if t1 > t0 else 0.0
        return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f

    def _measure_latency(self):
        """After a drag: which delay makes the cursor path best explain where
        the tracker saw the tree? Kept as a running average over drags."""
        samples = [s for s in self.drag_samples if s[0] - 0.2 > self.trail[0][0]] if self.trail else []
        self.drag_samples = []
        ref = self.press_ref
        log = os.environ.get("TREEOVERLAY_LOG")
        if len(samples) < 6 or ref is None:
            if log and samples:
                print(f"drag: latency not measured ({len(samples)} tracker frames, {'no' if ref is None else 'a'} start point)", flush=True)
            return
        moved = math.hypot(samples[-1][1] - ref[0], samples[-1][2] - ref[1])
        if moved < 150:
            if log:
                print(f"drag: latency not measured (tree moved only {moved:.0f} px)", flush=True)
            return
        best, best_err = None, None
        for ms in range(0, 152, 4):
            lat = ms / 1000
            err = 0.0
            for tc, tx, ty in samples:
                c = self._cursor_at(tc - lat)
                ex = (tx - ref[0]) - (c[0] - ref[2])
                ey = (ty - ref[1]) - (c[1] - ref[3])
                err += ex * ex + ey * ey
            if best_err is None or err < best_err:
                best, best_err = lat, err
        rms = math.sqrt(best_err / len(samples))
        if rms > 25:     # the tree didn't follow the cursor cleanly (edge of the tree?)
            if log:
                print(f"drag: latency not measured (best fit {best * 1000:.0f} ms still {rms:.0f} px off)", flush=True)
            return
        self.latency = best if not self.latency_measured else 0.6 * self.latency + 0.4 * best
        self.latency_measured = True
        if log:
            print(f"drag: game latency {best * 1000:.0f} ms (rms {rms:.1f} px), using {self.latency * 1000:.0f} ms", flush=True)

    def _follow(self):
        if self.base is None:
            self.follow_timer.stop()
            return
        down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        cx, cy = cursor_pos()
        now = clock()
        if not self.trail or now > self.trail[-1][0]:
            self.trail.append((now, cx, cy))
        if down and self.press is None:
            x, y = cursor_pos()
            rect = self.rect_px
            on_ui = rect is None or (self.picker is not None and self.picker.contains_cursor(x, y)) or any(
                rect[0] + x0 * rect[2] <= x <= rect[0] + x1 * rect[2] and rect[1] + y0 * rect[3] <= y <= rect[1] + y1 * rect[3]
                for x0, y0, x1, y1 in self.ui_rects)
            self.press, self.drag_follows = (x, y), not on_ui
            self.press_time = clock()
            self.tree_moving = not on_ui
            # where tree and cursor were when the button went down (the tree stands
            # still then); the latency is measured from this point
            self.press_ref = (self.base.tx, self.base.ty, cx, cy) if self.base is not None else None
        elif not down and self.press is not None:
            self.press, self.drag_start, self.tree_moving = None, None, False
            self._measure_latency()
        if self.press is not None and self.drag_follows and self.tree_moving:
            t = self._predicted()
            cur = self.transform
            if cur is None or abs(t.tx - cur.tx) + abs(t.ty - cur.ty) > 0.3:
                self.transform = t
                self.update()
        if self.press is not None and self.transform is not None:
            trace(k="tick", t=clock(), cx=cx, cy=cy, ox=self.transform.tx, oy=self.transform.ty,
                  pred=bool(self.drag_follows and self.tree_moving), lat=self.latency)

    # -- drawing -------------------------------------------------------------
    def _edge_path(self, t, a, b):
        arc = self.tree.arc(a, b)
        path = QPainterPath()
        if arc:
            cx, cy, r, t1, sweep = arc
            x, y = t.to_screen(cx, cy)
            rr = r * t.scale
            rect = QRectF(x - rr, y - rr, 2 * rr, 2 * rr)
            # Qt angles: degrees, counter-clockwise; ours are clockwise (y down)
            path.arcMoveTo(rect, -math.degrees(t1))
            path.arcTo(rect, -math.degrees(t1), -math.degrees(sweep))
        else:
            na, nb = self.tree.nodes[a], self.tree.nodes[b]
            path.moveTo(*t.to_screen(na.x, na.y))
            path.lineTo(*t.to_screen(nb.x, nb.y))
        return path

    def _label(self, p, x, y, text, color, size):
        p.setFont(QFont(theme.font_family(), size, QFont.DemiBold))
        rect = p.fontMetrics().boundingRect(text)
        box = QRectF(x, y - rect.height() / 2 - 4, rect.width() + 18, rect.height() + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 30, 200))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(color)
        p.drawText(box, Qt.AlignCenter, text)

    def _mastery_text(self, node_id):
        effect = self.plan.spec.masteries.get(node_id)
        for e in self.tree.raw["nodes"][str(node_id)].get("masteryEffects", []):
            if e["effect"] == effect:
                text = " / ".join(e["stats"])
                return text if len(text) <= 70 else text[:67] + "…"
        return None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dpr = self.devicePixelRatioF()
        p.scale(1 / dpr, 1 / dpr)  # draw in physical pixels
        w, h = self.width() * dpr, self.height() * dpr
        if self.message:
            p.setFont(QFont(theme.font_family(), 16, QFont.DemiBold))
            box = QRectF(w / 2 - 520, 0.2 * h, 1040, 64)
            p.setPen(QPen(QColor(255, 255, 255, 30), 1.5))
            p.setBrush(QColor(28, 28, 30, 225))
            p.drawRoundedRect(box, 18, 18)
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(245, 245, 247))
            p.drawText(box, Qt.AlignCenter, self.message)
        t = self.transform
        if t is None or self.plan is None:
            return
        # never draw over the game's own UI or an open tooltip
        p.save()
        clip = QRegion(0, 0, int(w), int(h))
        for x0, y0, x1, y1 in self.ui_rects:
            clip -= QRegion(int(x0 * w), int(y0 * h), int((x1 - x0) * w) + 1, int((y1 - y0) * h) + 1)
        for x, y, rw, rh in self.covered_rects:
            clip -= QRegion(QRect(int(x), int(y), int(rw), int(rh)))
        if self.asc is not None:      # the ascendancy panel covers the tree there
            cx, cy, r = self.asc[1]
            clip -= QRegion(int(cx - r), int(cy - r), int(2 * r), int(2 * r), QRegion.Ellipse)
        p.setClipRegion(clip)
        s = t.scale
        st = self.status
        done = st["done"] if st else set()
        nxt = st["next"] if st else set()
        pulse = 0.5 + 0.5 * math.sin(time.time() * 5)

        # connections: walked ones faint, the rest bright
        for a, b in self.edges:
            walked = (a in done or a == self.plan.start) and (b in done or b == self.plan.start)
            pen = QPen(QColor(90, 255, 140, 60 if walked else 170), max(2.0, (8 if walked else 14) * s))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawPath(self._edge_path(t, a, b))

        p.setBrush(Qt.NoBrush)
        labels = []
        step_of = {n: i + 1 for i, n in enumerate(self.route)}
        badges = []
        for n in self.nodes:
            x, y = t.to_screen(n.x, n.y)
            if not (-50 < x < w + 50 and -50 < y < h + 50):
                continue
            r = n.radius * s * 1.15
            color = QColor(COLORS.get(n.kind, COLORS["normal"]))
            if n.id in done:
                color.setAlpha(80)
                p.setPen(QPen(color, max(1.5, 5 * s)))
                p.drawEllipse(QPointF(x, y), r * 0.9, r * 0.9)
                continue
            if step_of.get(n.id) == 1:
                grow = 1.25 + 0.15 * pulse
                p.setPen(QPen(QColor(255, 255, 255, int(90 + 120 * pulse)), max(3.0, 8 * s)))
                p.drawEllipse(QPointF(x, y), r * grow, r * grow)
                p.setPen(QPen(color, max(3.5, 14 * s)))
            elif n.id in nxt:
                p.setPen(QPen(color, max(3.0, 13 * s)))
            else:
                p.setPen(QPen(color, max(2.5, 10 * s)))
            p.drawEllipse(QPointF(x, y), r, r)
            if n.id in step_of:
                badges.append((x + r * 0.75, y - r * 0.75, step_of[n.id]))
            # names for what to take next; zoomed in, for every notable/mastery left
            if self.settings["show_labels"] and (n.id in step_of or s >= LABEL_ZOOM):
                if n.kind == "mastery":
                    text = self._mastery_text(n.id)
                    if text:
                        labels.append((x + r + 6, y, text, QColor(220, 180, 255)))
                elif n.kind in ("notable", "keystone"):
                    labels.append((x + r + 6, y, n.name, QColor(255, 225, 140)))
        # nodes the character took that the build doesn't use
        if st:
            p.setPen(QPen(QColor(255, 60, 60, 220), max(2.5, 9 * s)))
            for nid in st["wrong"]:
                n = self.tree.nodes[nid]
                x, y = t.to_screen(n.x, n.y)
                d = n.radius * s * 0.8
                p.drawLine(QPointF(x - d, y - d), QPointF(x + d, y + d))
                p.drawLine(QPointF(x - d, y + d), QPointF(x + d, y - d))
        size = 10 if s < 0.2 else 12
        for x, y, text, color in labels:
            self._label(p, x, y, text, color, size)
        # the order to take the next points in
        br = max(12.0, 34 * s)
        p.setFont(QFont(theme.font_family(), max(7, int(br * 0.75)), QFont.Bold))
        for x, y, number in badges:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 230) if number == 1 else QColor(20, 20, 20, 220))
            p.drawEllipse(QPointF(x, y), br, br)
            p.setPen(QColor(0, 0, 0) if number == 1 else QColor(255, 225, 140))
            p.drawText(QRectF(x - br, y - br, 2 * br, 2 * br), Qt.AlignCenter, str(number))
        p.setBrush(Qt.NoBrush)
        p.restore()
        self._draw_ascendancy(p)

    def _draw_ascendancy(self, p):
        if self.asc is None or not self.asc_nodes:
            return
        t = self.asc[0]
        s = t.scale
        for n in self.asc_nodes:
            x, y = t.to_screen(n.x, n.y)
            r = n.radius * s * 1.2
            color = QColor(255, 200, 60) if n.kind == "notable" else QColor(80, 220, 255)
            if n.id in self.allocated:
                color.setAlpha(80)
                p.setPen(QPen(color, max(1.5, 5 * s)))
            else:
                p.setPen(QPen(color, max(3.0, 12 * s)))
            p.drawEllipse(QPointF(x, y), r, r)
            if n.kind == "notable" and n.id not in self.allocated and self.settings["show_labels"]:
                self._label(p, x + r + 6, y, n.name, QColor(255, 225, 140), 11)

    def set_ascendancy_panel(self, found):
        self.asc = found
        self.update()

    def progress_text(self):
        """One line for the picker: how far the character is with this tree."""
        st = self.status
        if self.plan is None:
            return ""
        if not st:
            return "Reading allocated passives…"
        line = f"{len(st['done'])}/{len(self.plan.target)} allocated"
        if st["todo"]:
            line += f" · {len(st['todo'])} to go"
        else:
            line += " · tree complete"
        if st["wrong"]:
            line += f" · {len(st['wrong'])} to refund"
        return line


class PopupCombo(QComboBox):
    def __init__(self, before_popup):
        super().__init__()
        self.before_popup = before_popup

    def showPopup(self):
        self.before_popup()
        super().showPopup()


class ControlWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PoE Tree Overlay")
        self.settings = load_settings()
        self.tree = PassiveTree()
        self.specs = []
        self.spec = None
        self.calib_points = []

        keys = self.settings["keys"]
        self.setObjectName("root")
        self.input = QLineEdit(self.settings["last_input"])
        self.input.setPlaceholderText("Or paste a PoB code, pobb.in link or tree URL")
        load_btn = QPushButton("Load")
        load_btn.setObjectName("primary")
        file_btn = QPushButton("Open PoB File…")
        self.spec_box = QComboBox()
        self.spec_box.setMinimumWidth(260)
        self.info = theme.caption("Load a build to start.")
        self.status = QLabel("Starting")
        self.status.setObjectName("pill")
        self.show_box = theme.Switch()
        self.show_box.setChecked(True)
        cal_btn = QPushButton("Calibrate")
        cal_btn.setToolTip(f"Hover the class start, press {keys['calibrate']}; hover the named notable, "
                           f"press {keys['calibrate']}. Only needed if the rings sit in the wrong place.")
        reset_btn = QPushButton("Clear Learned Map")
        reset_btn.setToolTip(f"Forget the learned map and the allocation readings ({keys['reset']})")
        update_btn = QPushButton("Update Tree Data")
        update_btn.setToolTip("Fetch the newest passive tree from GGG (after a new league)")
        settings_btn = QPushButton("Settings…")
        self.labels_box = theme.Switch()
        self.labels_box.setChecked(self.settings["show_labels"])
        self.progress_box = theme.Switch()
        self.progress_box.setChecked(self.settings["show_progress"])
        self.account = QLineEdit(self.settings["account"])
        self.account.setPlaceholderText("pathofexile.com account, e.g. Name#1234")
        chars_btn = QPushButton("Get Characters")
        self.char_box = QComboBox()
        self.char_box.setMinimumWidth(260)
        if self.settings["character"]:
            self.char_box.addItem(self.settings["character"])
        self.site_status = theme.caption("Optional. The Characters tab of the profile must be public.")

        # Path of Building: its builds, the one it has open, reload on save
        self.pob = pob.read_settings()
        self.pob_box = PopupCombo(self.refresh_pob_builds)
        self.pob_box.setMinimumWidth(260)
        self.pob_box.setPlaceholderText("Choose a build")
        self.pob_builds = []
        self.follow_box = theme.Switch()
        self.follow_box.setChecked(self.settings["follow_pob"])
        self.pob_status = theme.caption("")
        self._pob_open = None          # build name in PoB's title at the last look
        self._watch = None             # (path, mtime) of the loaded build file
        self._file_active = None       # the file's active tree at the last load

        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(34, 34))
        title = QLabel("PoE Tree Overlay")
        title.setObjectName("title")
        header.addWidget(icon); header.addSpacing(4); header.addWidget(title); header.addStretch(1)
        header.addWidget(self.status)

        build = theme.Card()
        if self.pob is not None:
            build.add(theme.row("Path of Building", self.pob_box))
            build.add(theme.row("Follow the build open in Path of Building", self.follow_box), self.pob_status)
        source = QHBoxLayout(); source.setSpacing(8)
        source.addWidget(self.input, 1); source.addWidget(file_btn); source.addWidget(load_btn)
        build.add(source)
        build.add(theme.row("Tree", self.spec_box), self.info)

        char = theme.Card()
        acc = QHBoxLayout(); acc.setSpacing(8)
        acc.addWidget(self.account, 1); acc.addWidget(chars_btn)
        char.add(acc)
        char.add(theme.row("Character", self.char_box), self.site_status)

        shown = theme.Card()
        shown.add(theme.row("Show overlay", self.show_box, key=keys["toggle"] or None))
        shown.add(theme.row("Track allocated passives", self.progress_box))
        shown.add(theme.row("Names of upcoming notables and masteries", self.labels_box))

        tools = QHBoxLayout(); tools.setSpacing(8)
        for b in (cal_btn, reset_btn, update_btn):
            tools.addWidget(b)
        tools.addStretch(1); tools.addWidget(settings_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 18)
        lay.setSpacing(6)
        lay.addLayout(header)
        for name, card in (("Build", build), ("pathofexile.com", char), ("Overlay", shown)):
            lay.addSpacing(10)
            lay.addWidget(theme.section(name))
            lay.addWidget(card)
        lay.addSpacing(12)
        lay.addLayout(tools)
        help_text = theme.caption(
            "Run the game in Windowed Fullscreen and open the passive tree (P): the overlay finds it by itself. "
            "{n} switches between the build's trees.".format(n=keys["next_tree"] or "The panel on the tree screen"))
        lay.addSpacing(4)
        lay.addWidget(help_text)
        self.setMinimumWidth(640)
        self.resize(700, 0)

        # allocated passives from pathofexile.com (all of the tree, not only what was seen)
        self.site = SiteFetcher()
        self.site_alloc, self.site_masteries, self.site_time = None, {}, 0.0
        self.site.characters_ready.connect(self.on_characters)
        self.site.passives_ready.connect(self.on_site_passives)
        self._auto_from = None        # tree index already auto-advanced from
        self.last_reading = None      # last (allocated, seen, covered) from the screen
        self.tree_open = False

        self.worker = Worker(self.settings, self.tree)
        self.overlay = Overlay(self.tree, self.settings, self.worker.tracker.mask_rects)
        self.picker = TreePicker()
        self.overlay.picker = self.picker
        self.picker.chosen.connect(self.spec_box.setCurrentIndex)
        self.picker.reread.connect(self.reread)
        self.worker.located.connect(self.on_located)
        self.worker.asc_located.connect(self.overlay.set_ascendancy_panel)
        self.worker.status.connect(self.set_status)
        if os.environ.get("TREEOVERLAY_LOG"):
            self.worker.status.connect(lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
        self.worker.start()

        load_btn.clicked.connect(lambda: self.load(self.input.text()))
        self.input.returnPressed.connect(lambda: self.load(self.input.text()))
        file_btn.clicked.connect(self.pick_file)
        self.spec_box.currentIndexChanged.connect(self.choose_spec)
        self.show_box.toggled.connect(self.set_enabled)
        cal_btn.clicked.connect(self.start_calibration)
        reset_btn.clicked.connect(lambda: self.worker.requests.put("reset"))
        update_btn.clicked.connect(self.update_tree_data)
        settings_btn.clicked.connect(self.open_settings)
        self.setWindowIcon(app_icon())
        self._make_tray()
        self.labels_box.toggled.connect(lambda on: self._setting("show_labels", on))
        chars_btn.clicked.connect(self.get_characters)
        self.account.returnPressed.connect(self.get_characters)
        self.char_box.activated.connect(lambda _: self.choose_character(self.char_box.currentText()))
        self.progress_box.toggled.connect(lambda on: self._setting("show_progress", on))

        self.key_state = {}
        self.hotkeys = QTimer(self, interval=30, timeout=self.poll_keys)
        self.hotkeys.start()
        self.pob_box.activated.connect(self.choose_pob_build)
        self.follow_box.toggled.connect(self.set_follow_pob)
        last = self.settings["last_input"]
        if last:
            QTimer.singleShot(0, lambda: self.load(last, mode="startup"))
        if self.settings["account"] and self.settings["character"]:
            QTimer.singleShot(0, self.refresh_site)
        if self.pob is not None:
            self.refresh_pob_builds()
            if not self.settings["account"] and self.pob.account:
                # the account PoB imports from is the one to read passives from
                self.account.setText(self.pob.account)
                self.settings["realm"] = self.pob.realm
                QTimer.singleShot(0, self.get_characters)
            self.pob_timer = QTimer(self, interval=1000, timeout=self.poll_pob)
            self.pob_timer.start()
            QTimer.singleShot(0, self.poll_pob)

    def set_status(self, text):
        """The pill at the top right: the short state, the details on hover."""
        short = text.split(" · ")[0]
        if short.startswith("Ready"):
            short = "Ready"
        elif short == "Path of Exile window not found":
            short = "Game not running"
        state = ("ok" if short == "Locked" else "warn" if short == "Searching"
                 else "bad" if short.startswith("Error") else "")
        if len(short) > 40:
            short = short[:39] + "…"
        self.status.setText(short)
        self.status.setToolTip(text)
        if self.status.property("state") != state:
            self.status.setProperty("state", state)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

    # -- Path of Building ---------------------------------------------------------
    def refresh_pob_builds(self):
        """The builds list, newest first; read again whenever it's opened."""
        self.pob_builds = pob.list_builds(self.pob.build_dir)
        self.pob_box.blockSignals(True)
        self.pob_box.clear()
        for b in self.pob_builds:
            self.pob_box.addItem(b.name.strip())
            self.pob_box.setItemData(self.pob_box.count() - 1, b.folder or "Builds", Qt.ToolTipRole)
        self._show_loaded_build()
        self.pob_box.blockSignals(False)

    def _loaded_file(self):
        return self._watch[0] if self._watch else None

    def _show_loaded_build(self):
        loaded = self._loaded_file()
        idx = next((i for i, b in enumerate(self.pob_builds) if loaded is not None and b.path == loaded), -1)
        self.pob_box.setCurrentIndex(idx)

    def choose_pob_build(self, idx):
        if 0 <= idx < len(self.pob_builds):
            self.load(str(self.pob_builds[idx].path), mode="pob")

    def set_follow_pob(self, on):
        self._setting("follow_pob", on)
        self._pob_open = None          # look again right away
        self.poll_pob()

    def poll_pob(self):
        """Every second: follow the build PoB shows, reload the file when it's saved."""
        name = pob.open_build_name() if self.settings["follow_pob"] else None
        if name is not None and name != self._pob_open:
            builds = pob.list_builds(self.pob.build_dir)
            hit = pob.find_build(name, builds, prefer=self._loaded_file() or self.pob.last_build)
            if hit is None:
                self.pob_status.setText(f"“{name.strip()}” is open in Path of Building but not saved yet.")
            else:
                self._pob_open = name
                if hit.path != self._loaded_file():
                    self.load(str(hit.path), mode="pob")
        elif name is None:
            self._pob_open = None
        if self._watch:
            path, mtime = self._watch
            try:
                now = path.stat().st_mtime
            except OSError:
                now = mtime
            if now != mtime:
                self.load(str(path), mode="reload")
        self._pob_caption(name)

    def _pob_caption(self, open_name):
        loaded = self._loaded_file()
        if not self.settings["follow_pob"]:
            text = "Pick a build above; it reloads whenever you save it in Path of Building."
        elif open_name is None:
            text = "Path of Building isn't showing a build. Open one there, or pick one above."
        elif loaded is not None and loaded.stem == open_name:
            text = f"Following “{open_name.strip()}”. Saving in Path of Building (Ctrl+S) updates the overlay."
        else:
            return      # the not-saved-yet note stays
        self.pob_status.setText(text)

    def _match_character(self):
        """Pick the character the loaded build was imported from in PoB."""
        loaded = self._loaded_file()
        if loaded is None or not self.char_box.count():
            return
        names = [self.char_box.itemText(i) for i in range(self.char_box.count())]
        name = pob.character_for(loaded, names)
        if name and name != self.settings["character"]:
            self.char_box.setCurrentText(name)
            self.choose_character(name)
            self.site_status.setText(f"{name}: the character this build was imported from in Path of Building.")

    # -- pathofexile.com --------------------------------------------------------
    def get_characters(self):
        account = self.account.text().strip()
        if not account:
            return
        self.settings["account"] = character.normalise_account(account)
        save_settings(self.settings)
        self.site_status.setText("Getting characters…")
        self.site.fetch_characters(self.settings["account"], self.settings["realm"])

    def on_characters(self, chars, error):
        if error:
            self.site_status.setText(error)
            return
        chars = sorted(chars, key=lambda c: -c["level"])
        self.char_box.clear()
        for c in chars:
            self.char_box.addItem(c["name"])
            self.char_box.setItemData(self.char_box.count() - 1, f"{c['class']} {c['level']}, {c['league']}",
                                      Qt.ToolTipRole)
        current = self.settings["character"]
        if current in [c["name"] for c in chars]:
            self.char_box.setCurrentText(current)
        self.site_status.setText(f"{len(chars)} characters. Pick the one you're playing.")
        self.choose_character(self.char_box.currentText())
        self._match_character()

    def choose_character(self, name):
        if not name:
            return
        if name != self.settings["character"]:
            self.settings["character"] = name
            save_settings(self.settings)
            self.worker.requests.put("reset_alloc")    # the screen readings were another character's
        self.refresh_site(force=True)

    def refresh_site(self, force=False):
        """Fetch the character's passives; when opening the tree at most every 20 s."""
        if not (self.settings["account"] and self.settings["character"]):
            return
        if not force and time.time() - self.site_time < 20:
            return
        self.site_time = time.time()
        self.site.fetch_passives(self.settings["account"], self.settings["character"], self.settings["realm"])

    def on_site_passives(self, name, result, error):
        if name != self.settings["character"]:
            return
        if error:
            self.site_status.setText(error)
            return
        self.site_alloc, self.site_masteries = result
        self.site_status.setText(f"{name}: {len(self.site_alloc)} passives allocated on pathofexile.com "
                                 f"(updated {time.strftime('%H:%M:%S')}).")
        self._update_progress()

    def _merged_progress(self):
        """What is allocated: what the screen shows for nodes it has read, the
        site's state for everything else."""
        reading = self.last_reading
        allocated, seen, covered = reading if reading else (frozenset(), frozenset(), [])
        if self.site_alloc is None:
            return reading
        site = {n for n in self.site_alloc if n in self.tree.nodes}
        merged = merge_allocations(allocated, seen, site)
        everything = frozenset(n.id for n in self.tree.nodes.values() if not n.ascendancy and n.kind != "start")
        return frozenset(merged), everything, covered

    def _maybe_next_tree(self):
        """When the current tree is complete, move on to the build's next one."""
        st = self.overlay.status
        idx = self.spec_box.currentIndex()
        if (self.settings["auto_next_tree"] and st and not st["todo"] and idx + 1 < len(self.specs)
                and self._auto_from != idx):
            self._auto_from = idx
            QTimer.singleShot(1500, lambda: self.spec_box.setCurrentIndex(idx + 1)
                              if self.spec_box.currentIndex() == idx else None)
            self.picker.show_toast(f"Tree complete: switching to {self.specs[idx + 1].title}", 4)

    def _update_progress(self):
        progress = self._merged_progress()
        if progress is not None and self.settings["show_progress"]:
            self.overlay.set_progress(progress)
            self.picker.set_progress(self.overlay.progress_text())
            self.overlay.update()
            self._maybe_next_tree()

    # -- tray and settings ----------------------------------------------------------
    def _make_tray(self):
        self.quitting = False
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("PoE Tree Overlay")
        menu = QMenu()
        for text, slot in (("Show window", self.show_window), ("Re-read allocated passives", self.reread),
                           ("Settings…", self.open_settings)):
            act = QAction(text, menu)
            act.triggered.connect(slot)
            menu.addAction(act)
        self.tray_overlay = QAction("Show overlay", menu, checkable=True, checked=self.show_box.isChecked())
        self.tray_overlay.toggled.connect(self.show_box.setChecked)
        self.show_box.toggled.connect(self.tray_overlay.setChecked)
        menu.addAction(self.tray_overlay)
        menu.addSeparator()
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.quit)
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_window()
                                    if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self._tray_hint_shown = False

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if not dlg.exec():
            return
        new = dlg.values()
        ui_changed = new["ui_scale"] != self.settings["ui_scale"]
        realm_changed = new["realm"] != self.settings["realm"]
        self.settings.update(new)
        save_settings(self.settings)
        self.labels_box.setChecked(new["show_labels"])
        self.progress_box.setChecked(new["show_progress"])
        if ui_changed:
            self.worker.requests.put("refit")
        if realm_changed:
            self.refresh_site(force=True)
        if self.spec is not None:
            self.overlay.set_spec(self.spec)
        self.overlay.update()

    def quit(self):
        self.quitting = True
        self.close()

    def _setting(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)
        if key == "show_progress" and not value:
            self.overlay.status = None
        self.overlay.update()

    def update_tree_data(self):
        lines = []
        try:
            new = updater.update(log=lines.append)
        except Exception as exc:
            QMessageBox.warning(self, "Update failed", str(exc))
            return
        QMessageBox.information(self, "Tree data", "\n".join(lines[-3:]) if new else lines[-1])

    # -- build -----------------------------------------------------------
    def pick_file(self):
        start = str(self.pob.build_dir if self.pob else pob.documents_dir() / "Path of Building" / "Builds")
        path, _ = QFileDialog.getOpenFileName(self, "Path of Building build", start, "PoB builds (*.xml)")
        if path:
            self.load(path)

    def load(self, text, mode="user"):
        """mode: "user" (typed or picked), "startup" (the last build, on the tree
        used last), "pob" (followed from Path of Building, on its active tree) or
        "reload" (the file was saved: same tree, unless PoB's active one changed)."""
        try:
            specs, active = build.load(text)
        except Exception as exc:
            if mode == "user":
                QMessageBox.warning(self, "Could not load build", str(exc))
            return    # a reload may have caught PoB mid-save: the next look tries again
        text = text.strip().strip('"')
        path = Path(text)
        is_file = len(text) < 260 and path.is_file()
        if mode == "reload":
            idx = active if active != self._file_active else self.spec_box.currentIndex()
        elif mode == "startup" and 0 <= self.settings.get("spec", -1) < len(specs):
            idx = self.settings["spec"]
        else:
            idx = active
        idx = max(0, min(idx, len(specs) - 1))
        self._file_active = active
        self._watch = (path, path.stat().st_mtime) if is_file else None
        self.specs = specs
        self.settings["last_input"] = text
        save_settings(self.settings)
        # the paste field is for codes and links; files show in the builds list
        if is_file and self.pob is not None:
            self.input.clear()
        else:
            self.input.setText(text)
        self.spec_box.blockSignals(True)
        self.spec_box.clear()
        for s in specs:
            self.spec_box.addItem(f"{s.title}  ({len(s.nodes)} nodes)")
        self.spec_box.setCurrentIndex(idx)
        self.spec_box.blockSignals(False)
        self.choose_spec(idx)
        if self.pob is not None:
            self._show_loaded_build()
        if is_file:
            if mode == "reload":
                self.picker.show_toast("Updated from Path of Building")
            elif mode == "pob":
                self.picker.show_toast(f"Path of Building: {path.stem.strip()}")
            self._match_character()

    def choose_spec(self, idx):
        if not 0 <= idx < len(self.specs):
            return
        self.spec = self.specs[idx]
        self.settings["spec"] = idx
        save_settings(self.settings)
        self.overlay.set_spec(self.spec)
        self.picker.set_specs(self.specs, idx)
        self.worker.requests.put(("ascendancy", self.tree.ascendancy_name(self.spec.class_id, self.spec.ascend_id)))
        self.picker.show_toast(f"Switched to tree {idx + 1}/{len(self.specs)}")
        known = [n for n in self.spec.nodes if n in self.tree.nodes]
        kinds = [self.tree.nodes[n].kind for n in known if not self.tree.nodes[n].ascendancy]
        skipped = len(self.spec.nodes) - len(known)
        self.info.setText(
            f"{CLASS_NAMES[self.spec.class_id]} · {kinds.count('normal')} small, {kinds.count('notable')} notables, "
            f"{kinds.count('keystone')} keystones, {kinds.count('mastery')} masteries"
            + (f" · {skipped} nodes not placed" if skipped else "")
            + (f" · tree {self.spec.tree_version}" if self.spec.tree_version else "")
            + ("" if updater.matches(self.spec.tree_version, updater.installed_version()) else
               f" · <b>this build is for tree {self.spec.tree_version}, the overlay has {updater.installed_version()}</b>"))

    # -- tracking ------------------------------------------------------------
    def on_located(self, t, rect, progress, cursor):
        self.overlay.place(rect)
        opened = t is not None and not self.tree_open
        self.tree_open = t is not None
        if opened:
            self.refresh_site()
        if progress is not None:
            self.last_reading = progress
        if self.settings["show_progress"] and (progress is not None or opened):
            self.overlay.set_progress(self._merged_progress())
            self._maybe_next_tree()
        self.overlay.set_transform(t if self.show_box.isChecked() else None, cursor)
        self.picker.place(rect, t is not None and self.show_box.isChecked())
        self.picker.set_progress(self.overlay.progress_text())

    def reread(self):
        self.worker.requests.put("reset_alloc")
        self.last_reading = None
        self.refresh_site(force=True)
        self.picker.show_toast("Reading allocated passives again.\nPan over your tree once.", 4)

    def next_tree(self):
        if len(self.specs) > 1:
            self.spec_box.setCurrentIndex((self.spec_box.currentIndex() + 1) % len(self.specs))

    def set_enabled(self, on):
        self.worker.enabled = on
        if not on:
            self.overlay.set_transform(None)

    # -- calibration ---------------------------------------------------------
    def calibration_targets(self):
        start = self.tree.class_start(self.spec.class_id if self.spec else 3)
        pool = [n for n in self.tree.nodes.values() if n.kind == "notable" and not n.ascendancy]
        in_build = [n for n in pool if self.spec and n.id in self.spec.nodes]
        dist = lambda n: math.dist((n.x, n.y), (start.x, start.y))
        for group in (in_build, pool):
            ok = [n for n in group if 900 < dist(n) < 2500]
            if ok:
                return start, min(ok, key=dist)
        return start, min(pool, key=dist)

    def start_calibration(self):
        start, notable = self.calibration_targets()
        self.calib_points = []
        self.calib = (start, notable)
        key = self.settings["keys"]["calibrate"]
        self.overlay.message = f"Calibration 1/2: hover the centre of the {CLASS_NAMES[start.class_start]} start and press {key}"
        self.overlay.update()

    def calibration_click(self):
        if not self.calib_points and not self.overlay.message:
            self.start_calibration()
            return
        rect = self.overlay.rect_px
        if rect is None:
            return
        x, y = cursor_pos()
        self.calib_points.append((x - rect[0], y - rect[1]))
        start, notable = self.calib
        key = self.settings["keys"]["calibrate"]
        if len(self.calib_points) == 1:
            self.overlay.message = f"Calibration 2/2: hover the notable “{notable.name}” (search it with Ctrl+F) and press {key}"
        else:
            t = Transform.from_points([(start.x, start.y), (notable.x, notable.y)], self.calib_points)
            self.worker.requests.put(t)
            self.overlay.message = ""
            self.calib_points = []
        self.overlay.update()

    def poll_keys(self):
        keys = self.settings["keys"]
        for action, name in keys.items():
            if not name:
                continue
            down = bool(user32.GetAsyncKeyState(VK.get(name, 0)) & 0x8000)
            if down and not self.key_state.get(action):
                if action == "calibrate":
                    self.calibration_click()
                elif action == "toggle":
                    self.show_box.setChecked(not self.show_box.isChecked())
                elif action == "reset":
                    self.worker.requests.put("reset")
                    self.picker.show_toast("Cleared: tracking map and allocation readings.\nPan over your tree to read it again.", 5)
                elif action == "next_tree":
                    self.next_tree()
            self.key_state[action] = down

    def closeEvent(self, e):
        if not self.quitting and self.tray.isVisible():
            # keep running in the tray; Quit is in the tray icon's menu
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("PoE Tree Overlay", "Still running here. Right-click for Quit.",
                                      app_icon(), 4000)
            return
        self.tray.hide()
        self.worker.stop()
        self.worker.wait(2000)
        self.overlay.close()
        self.picker.close()
        super().closeEvent(e)


def ensure_tree_data(app):
    """A fresh install has no tree data: fetch it once, with a progress window."""
    if (DATA_DIR / "data.json").exists():
        return True
    (DATA_DIR / "sprites").mkdir(parents=True, exist_ok=True)
    dlg = QProgressDialog("Downloading the passive tree from GGG (first start only)…", None, 0, 0)
    dlg.setWindowTitle("PoE Tree Overlay")
    dlg.setWindowIcon(app_icon())
    dlg.show()
    result = {}

    def run():
        try:
            updater.update(log=lambda line: result.__setitem__("line", line))
        except Exception as exc:          # no network, GitHub down, ...
            result["error"] = str(exc)
        result["done"] = True

    threading.Thread(target=run, daemon=True).start()
    while "done" not in result:
        if "line" in result:
            dlg.setLabelText(result["line"])
        app.processEvents()
        time.sleep(0.03)
    dlg.close()
    if "error" in result:
        QMessageBox.critical(None, "PoE Tree Overlay", f"Couldn't download the passive tree data:\n{result['error']}")
        return False
    return True


def main():
    # 1 ms timer resolution: the cursor sampling and repaint timers (8 ms)
    # otherwise tick at Windows' default 15.6 ms
    winmm = ctypes.windll.winmm
    winmm.timeBeginPeriod(1)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)    # it lives on in the tray
    app.setWindowIcon(app_icon())
    app.aboutToQuit.connect(lambda: winmm.timeEndPeriod(1))
    theme.apply(app)
    if not ensure_tree_data(app):
        sys.exit(1)
    w = ControlWindow()
    w.destroyed.connect(app.quit)
    w.setAttribute(Qt.WA_DeleteOnClose)
    theme.title_bar(w)
    if w.settings.get("start_minimized") or os.environ.get("TREEOVERLAY_MINIMIZED"):
        w.showMinimized()   # stay out of the game's way
    else:
        w.show()
    sys.exit(app.exec())
