"""Small clickable panel over the game: shows the build's tree and progress and
lets the player switch trees without leaving the game.

The window never takes focus (WS_EX_NOACTIVATE), so clicking it leaves the game
in front, and it is excluded from screen capture like the overlay.
"""
import ctypes
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .theme import font_family

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x11

# a macOS HUD panel: dark translucent glass, white text, the system blue for
# the current choice
STYLE = """
QWidget#panel { background: rgba(28, 28, 30, 225); border: 1px solid rgba(255, 255, 255, 30); border-radius: 14px; }
QWidget { font-family: "%(font)s"; }
QPushButton { color: #f5f5f7; background: transparent; border: none; text-align: left; padding: 4px 8px;
              border-radius: 8px; font-size: 15pt; font-weight: 600; }
QPushButton:hover { background: rgba(255, 255, 255, 22); }
QPushButton:disabled { color: #f5f5f7; }
QPushButton#item { font-size: 13pt; font-weight: 400; padding: 6px 10px; }
QPushButton#item[current="true"] { color: #0a84ff; font-weight: 600; }
QPushButton#small { color: #f5f5f7; font-size: 11pt; font-weight: 500; padding: 3px 12px;
                    background: rgba(255, 255, 255, 30); border-radius: 12px; }
QPushButton#small:hover { background: rgba(255, 255, 255, 48); }
QLabel { color: rgba(235, 235, 245, 165); font-size: 12pt; padding: 0 8px; background: transparent; }
QLabel#toast { color: #30d158; font-weight: 600; }
QFrame#sep { background: rgba(255, 255, 255, 26); max-height: 1px; min-height: 1px; border: none; margin: 4px 8px; }
"""


class TreePicker(QWidget):
    chosen = Signal(int)
    reread = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE % {"font": font_family()})
        panel = QWidget(self)
        panel.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 10)
        lay.setSpacing(2)

        top = QHBoxLayout()
        self.title = QPushButton("No build loaded")
        self.title.setFocusPolicy(Qt.NoFocus)
        self.title.clicked.connect(self.toggle)
        self.reread_btn = QPushButton("Re-read")
        self.reread_btn.setObjectName("small")
        self.reread_btn.setToolTip("Read the allocated passives again (after switching characters)")
        self.reread_btn.setFocusPolicy(Qt.NoFocus)
        self.reread_btn.clicked.connect(self.reread.emit)
        top.addWidget(self.title, 1)
        top.addWidget(self.reread_btn)
        lay.addLayout(top)

        self.progress = QLabel("")
        lay.addWidget(self.progress)
        self.toast = QLabel("")
        self.toast.setObjectName("toast")
        self.toast.hide()
        lay.addWidget(self.toast)
        self.list = QWidget()
        outer_list = QVBoxLayout(self.list)
        outer_list.setContentsMargins(0, 0, 0, 0)
        sep = QFrame()
        sep.setObjectName("sep")
        outer_list.addWidget(sep)
        self.list_lay = QVBoxLayout()
        outer_list.addLayout(self.list_lay)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(0)
        self.list.hide()
        lay.addWidget(self.list)

        self.specs, self.current = [], -1
        self.toast_timer = QTimer(self, singleShot=True, timeout=self._hide_toast)
        self.anchor = None
        self.made_noactivate = False

    # -- content -------------------------------------------------------------
    def set_specs(self, specs, current):
        self.specs, self.current = specs, current
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            w.deleteLater()
        for i, spec in enumerate(specs):
            b = QPushButton(f"{'✓' if i == current else '   '}  {spec.title}")
            b.setObjectName("item")
            b.setProperty("current", i == current)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            self.list_lay.addWidget(b)
        arrow = "  ▾" if len(specs) > 1 else ""
        self.title.setText(f"{specs[current].title}{arrow}" if specs else "No build loaded")
        self.title.setToolTip(f"Tree {current + 1} of {len(specs)}" if specs else "")
        self.title.setEnabled(len(specs) > 1)
        self._fit()

    def set_progress(self, text):
        if text != self.progress.text():
            self.progress.setText(text)
            self._fit()

    def show_toast(self, text, seconds=3.0):
        self.toast.setText(text)
        self.toast.show()
        self.toast_timer.start(int(seconds * 1000))
        self._fit()

    def _hide_toast(self):
        self.toast.hide()
        self._fit()

    def toggle(self):
        self.list.setVisible(not self.list.isVisible())
        self._fit()

    def _pick(self, i):
        self.list.hide()
        self.chosen.emit(i)

    # -- placement -----------------------------------------------------------
    def place(self, rect, visible):
        """rect: game client area in physical pixels; the panel sits in the free
        area at the left of the tree screen."""
        if rect is None or not visible:
            if self.isVisible():
                self.list.hide()
                self.hide()
            return
        screen = QApplication.primaryScreen()
        cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
        for sc in QApplication.screens():
            g, d = sc.geometry(), sc.devicePixelRatio()
            if g.x() <= cx < g.x() + g.width() * d and g.y() <= cy < g.y() + g.height() * d:
                screen = sc
        dpr, geo = screen.devicePixelRatio(), screen.geometry()
        anchor = (round(geo.x() + (rect[0] + 0.012 * rect[2] - geo.x()) / dpr),
                  round(geo.y() + (rect[1] + 0.18 * rect[3] - geo.y()) / dpr))
        if anchor != self.anchor:
            self.anchor = anchor
            self.move(*anchor)
        if not self.isVisible():
            self.show()
            self._native_setup()

    def _native_setup(self):
        if self.made_noactivate:
            return
        hwnd = int(self.winId())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        if not os.environ.get("TREEOVERLAY_VISIBLE_TO_CAPTURE"):
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        self.made_noactivate = True

    def _fit(self):
        self.adjustSize()
        self.resize(max(self.sizeHint().width(), 320), self.sizeHint().height())

    def contains_cursor(self, x, y):
        """True if the physical screen point is on the panel (the overlay uses it
        to tell a click on the panel from a drag of the tree)."""
        if not self.isVisible():
            return False
        dpr = self.devicePixelRatioF()
        g = self.frameGeometry()
        return g.x() * dpr <= x <= (g.x() + g.width()) * dpr and g.y() * dpr <= y <= (g.y() + g.height()) * dpr

