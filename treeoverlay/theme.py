"""The look of the app's own windows: macOS-style grouped cards, pill buttons,
toggle switches and the system accent blue, in light and dark (following the
Windows setting).

SF Pro may only be used on Apple platforms, so the closest Windows font is
used: Segoe UI Variable (Windows 11), else Segoe UI.
"""
import ctypes
import sys

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontDatabase, QPainter
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .tree import DATA_DIR

LIGHT = {
    "window": "#f2f2f7", "card": "#ffffff", "card_line": "#e3e3e8", "sep": "#e5e5ea",
    "text": "#1d1d1f", "muted": "#6e6e73", "accent": "#007aff", "accent_hover": "#0068d9",
    "accent_soft": "rgba(0, 122, 255, 0.28)", "control": "#e9e9eb", "control_hover": "#dcdce0",
    "control_down": "#cfcfd4", "field": "#ffffff", "field_line": "#d1d1d6", "track_off": "#e3e3e8",
    "ok": "#248a3d", "ok_bg": "rgba(52, 199, 89, 0.16)", "warn": "#c93400", "warn_bg": "rgba(255, 149, 0, 0.18)",
    "bad": "#d70015", "bad_bg": "rgba(255, 59, 48, 0.14)", "idle_bg": "rgba(120, 120, 128, 0.14)",
}
DARK = {
    "window": "#1c1c1e", "card": "#2c2c2e", "card_line": "#38383a", "sep": "#3a3a3c",
    "text": "#f5f5f7", "muted": "#98989d", "accent": "#0a84ff", "accent_hover": "#3395ff",
    "accent_soft": "rgba(10, 132, 255, 0.40)", "control": "#3a3a3c", "control_hover": "#464649",
    "control_down": "#505054", "field": "#1c1c1e", "field_line": "#48484a", "track_off": "#48484a",
    "ok": "#30d158", "ok_bg": "rgba(48, 209, 88, 0.18)", "warn": "#ff9f0a", "warn_bg": "rgba(255, 159, 10, 0.18)",
    "bad": "#ff453a", "bad_bg": "rgba(255, 69, 58, 0.18)", "idle_bg": "rgba(152, 152, 157, 0.18)",
}

_dark = False


def font_family(display=False):
    families = set(QFontDatabase.families())
    for name in (("Segoe UI Variable Display", "Segoe UI Variable Text") if display else ("Segoe UI Variable Text",)):
        if name in families:
            return name
    return "Segoe UI"


def colors():
    return DARK if _dark else LIGHT


def _chevron(name, path, color):
    """QSS can only load arrows from files; write them next to the data."""
    folder = DATA_DIR / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{name}.svg"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
           f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" '
           f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    if not f.exists() or f.read_text() != svg:
        f.write_text(svg)
    return f.as_posix()


def stylesheet():
    c = colors()
    mode = "dark" if _dark else "light"
    down = _chevron(f"down_{mode}", "M3 4.5 L6 7.5 L9 4.5", c["muted"])
    up = _chevron(f"up_{mode}", "M3 7.5 L6 4.5 L9 7.5", c["muted"])
    text, display = font_family(), font_family(display=True)
    return f"""
* {{ font-family: "{text}"; font-size: 10pt; color: {c['text']}; }}
QWidget#root, QDialog {{ background: {c['window']}; }}
QFrame#card {{ background: {c['card']}; border: 1px solid {c['card_line']}; border-radius: 12px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#sep {{ background: {c['sep']}; border: none; min-height: 1px; max-height: 1px; }}
QLabel#title {{ font-family: "{display}"; font-size: 17pt; font-weight: 700; }}
QLabel#section {{ color: {c['muted']}; font-size: 9pt; font-weight: 600; padding: 0 0 0 12px; }}
QLabel#caption {{ color: {c['muted']}; font-size: 9pt; }}
QLabel#key {{ color: {c['muted']}; font-size: 8pt; font-weight: 600; background: {c['control']};
             border-radius: 5px; padding: 1px 6px; }}
QLabel#pill {{ font-size: 9pt; font-weight: 600; border-radius: 12px; padding: 0 12px;
              min-height: 24px; max-height: 24px;
              color: {c['muted']}; background: {c['idle_bg']}; }}
QLabel#pill[state="ok"] {{ color: {c['ok']}; background: {c['ok_bg']}; }}
QLabel#pill[state="warn"] {{ color: {c['warn']}; background: {c['warn_bg']}; }}
QLabel#pill[state="bad"] {{ color: {c['bad']}; background: {c['bad_bg']}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {c['field']}; border: 1px solid {c['field_line']}; border-radius: 7px;
    padding: 5px 9px; min-height: 18px; selection-background-color: {c['accent']}; selection-color: white; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['accent']}; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['card_line']}; border-radius: 8px;
    padding: 4px; outline: 0; selection-background-color: {c['accent']}; selection-color: white; }}
QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 0 8px; border-radius: 5px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    border: none; width: 20px; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}

QPushButton {{ background: {c['control']}; border: none; border-radius: 7px; padding: 6px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {c['control_hover']}; }}
QPushButton:pressed {{ background: {c['control_down']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#primary {{ background: {c['accent']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#plain {{ background: transparent; color: {c['accent']}; padding: 6px 6px; }}
QPushButton#plain:hover {{ color: {c['accent_hover']}; }}

QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['card_line']};
           border-radius: 6px; padding: 4px 8px; }}
QMenu {{ background: {c['card']}; border: 1px solid {c['card_line']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 5px 22px 5px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['accent']}; color: white; }}
QMenu::separator {{ height: 1px; background: {c['sep']}; margin: 4px 8px; }}
QProgressDialog QLabel {{ padding: 6px; }}
"""


MODES = {"system": "Like Windows", "light": "Light", "dark": "Dark"}
_mode = "system"


def apply(app, mode="system"):
    """Style the whole app. mode: "light", "dark", or "system" to follow the
    light/dark setting of Windows as it changes."""
    global _mode
    _mode = mode if mode in MODES else "system"
    app.setStyle("Fusion")
    app.styleHints().colorSchemeChanged.connect(lambda *_: _refresh(app))
    _refresh(app)


def set_mode(app, mode):
    global _mode
    _mode = mode if mode in MODES else "system"
    _refresh(app)


def _refresh(app):
    global _dark
    if _mode == "system":
        _dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    else:
        _dark = _mode == "dark"
    app.setStyleSheet(stylesheet())
    for w in app.topLevelWidgets():
        if w.isWindow():
            title_bar(w)
        for s in w.findChildren(Switch):
            s.update()


def title_bar(widget):
    """Dark or light native title bar to match (Windows 10 20H1+)."""
    if sys.platform != "win32" or not widget.isWindow():
        return
    try:
        value = ctypes.c_int(1 if _dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20, ctypes.byref(value), 4)
    except (OSError, AttributeError):
        pass


# -- building blocks ---------------------------------------------------------------
class Switch(QCheckBox):
    """A macOS-style toggle; a QCheckBox underneath, so toggled/setChecked work."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(38, 32)     # as tall as a text field, so rows line up

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def _animate(self, on):
        self._anim.stop()
        if not self.isVisible():
            self._set_pos(1.0 if on else 0.0)
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _set_pos(self, v):
        self._pos = float(v)
        self.update()

    def showEvent(self, e):
        self._anim.stop()
        self._pos = 1.0 if self.isChecked() else 0.0
        super().showEvent(e)

    def paintEvent(self, _):
        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, 38, 22).translated(0, (self.height() - 22) / 2)
        off, on = QColor(c["track_off"]), QColor(c["accent"])
        t = self._pos
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 11, 11)
        knob = QPointF(r.left() + 11 + t * 16, r.center().y())
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob + QPointF(0, 0.8), 9.2, 9.2)
        p.setBrush(QColor("white"))
        p.drawEllipse(knob, 9, 9)


def separator():
    line = QFrame()
    line.setObjectName("sep")
    return line


class Card(QFrame):
    """A rounded group of rows with hairlines between them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 6, 14, 6)
        self.lay.setSpacing(0)
        self._rows = 0

    def add(self, item, caption=None):
        """item: a widget or a layout, put on its own row."""
        if self._rows:
            self.lay.addWidget(separator())
        box = QVBoxLayout()
        box.setContentsMargins(0, 7, 0, 7)
        box.setSpacing(4)
        if isinstance(item, QWidget):
            box.addWidget(item)
        else:
            box.addLayout(item)
        if caption is not None:
            box.addWidget(caption)
        self.lay.addLayout(box)
        self._rows += 1
        return item


def row(label, *widgets, key=None):
    """A settings row: the name on the left, controls on the right."""
    h = QHBoxLayout()
    h.setSpacing(8)
    name = QLabel(label) if isinstance(label, str) else label
    h.addWidget(name)
    if key:
        k = QLabel(key)
        k.setObjectName("key")
        h.addWidget(k)
    h.addStretch(1)
    for w in widgets:
        h.addWidget(w)
    return h


def section(text):
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


def caption(text=""):
    lab = QLabel(text)
    lab.setObjectName("caption")
    lab.setWordWrap(True)
    return lab
