"""The settings window: everything that used to need editing settings.json."""
from PySide6.QtWidgets import QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QPushButton, QSpinBox, QVBoxLayout

from . import theme

KEYS = [f"F{i}" for i in range(1, 13)]
ACTIONS = [("next_tree", "Next tree of the build"), ("calibrate", "Calibrate"),
           ("toggle", "Show / hide the overlay"), ("reset", "Reset tracking and readings")]
POB_OPTIONS = [
    ("pob_link", "Live link", "The overlay follows the build and tree open in Path of Building, unsaved "
                              "changes included."),
    ("pob_title_patch", "Tree number in the title", "Shows the tree number in Path of Building's window "
                                                    "title (follows tree switches without the live link)."),
    ("pob_marks", "Show in-game progress", "Rings on Path of Building's tree for passives allocated in game "
                                           "(red: not in the tree) and the next points numbered in order."),
    ("pob_keys", "Tree hotkeys", "Ctrl+Up and Ctrl+Down switch the build's tree on any tab."),
    ("pob_gems", "DPS of linked support gems", "On the Skills tab, how much DPS each linked support gem adds "
                                               "(by the DPS chosen under \"Sort gems by DPS\")."),
    ("pob_speed", "Lower CPU use when idle", "Path of Building draws 20 frames a second instead of over 100 "
                                             "while you're not using it."),
    ("pob_theme", "macOS-style look", "Rounded controls, macOS dark colours and the Inter font."),
]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(6)

        self.labels = theme.Switch()
        self.labels.setChecked(settings["show_labels"])
        self.progress = theme.Switch()
        self.progress.setChecked(settings["show_progress"])
        self.route = QSpinBox()
        self.route.setRange(0, 30)
        self.route.setValue(settings["route_length"])
        self.route.setSuffix(" points")
        self.auto_next = theme.Switch()
        self.auto_next.setChecked(settings["auto_next_tree"])
        shown = theme.Card()
        shown.add(theme.row("Names of upcoming notables and masteries", self.labels))
        shown.add(theme.row("Read which passives are allocated", self.progress))
        shown.add(theme.row("Number the next", self.route))
        shown.add(theme.row("Switch to the next tree when one is complete", self.auto_next))

        self.ui_scale = QDoubleSpinBox()
        self.ui_scale.setRange(50, 200)
        self.ui_scale.setDecimals(0)
        self.ui_scale.setSuffix(" %")
        self.ui_scale.setValue(round(settings["ui_scale"] * 100))
        self.realm = QComboBox()
        self.realm.addItems(["pc", "xbox", "sony"])
        self.realm.setCurrentText(settings["realm"])
        self.fps = QSpinBox()
        self.fps.setRange(2, 30)
        self.fps.setValue(settings["fps"])
        self.fps.setSuffix(" per second")
        game = theme.Card()
        game.add(theme.row("In-game UI scale", self.ui_scale))
        game.add(theme.row("Account realm", self.realm))
        game.add(theme.row("Checks while the tree stands still", self.fps))

        self.keys = {}
        keys = theme.Card()
        for action, label in ACTIONS:
            box = QComboBox()
            box.addItems(["Off"] + KEYS)
            box.setCurrentText(settings["keys"].get(action) or "Off")
            box.setMinimumWidth(90)
            self.keys[action] = box
            keys.add(theme.row(label, box))

        self.minimized = theme.Switch()
        self.minimized.setChecked(settings.get("start_minimized", False))
        self.appearance = QComboBox()
        for key, label in theme.MODES.items():
            self.appearance.addItem(label, key)
        self.appearance.setCurrentIndex(max(0, self.appearance.findData(settings.get("appearance", "system"))))
        program = theme.Card()
        program.add(theme.row("Appearance", self.appearance))
        program.add(theme.row("Start minimized", self.minimized))
        self.pob = {}
        pob_card = theme.Card()
        for key, label, note in POB_OPTIONS:
            box = theme.Switch()
            box.setChecked(settings.get(key, False))
            self.pob[key] = box
            pob_card.add(theme.row(label, box), theme.caption(note))

        # two columns: the overlay itself, and Path of Building plus the program
        columns = QHBoxLayout()
        columns.setSpacing(20)
        for sections in ((("Overlay", shown), ("Game", game), ("Hotkeys (the game still gets the key)", keys)),
                         (("Path of Building", pob_card), ("Program", program))):
            col = QVBoxLayout()
            col.setSpacing(6)
            for i, (name, card) in enumerate(sections):
                if i:
                    col.addSpacing(8)
                col.addWidget(theme.section(name))
                col.addWidget(card)
            col.addStretch(1)
            columns.addLayout(col, 1)
        lay.addLayout(columns)
        lay.addSpacing(6)
        lay.addWidget(theme.caption("Everything applies right away. The Path of Building options change a few of "
                                    "its files (the originals are kept and put back when switched off) and show "
                                    "after Path of Building restarts."))

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        cancel, ok = QPushButton("Cancel"), QPushButton("Done")
        ok.setObjectName("primary")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addSpacing(8)
        lay.addLayout(buttons)
        self.setMinimumWidth(960)
        theme.title_bar(self)

    def values(self):
        """The settings as they should be after Done."""
        out = dict(self.settings)
        out.update({
            "show_labels": self.labels.isChecked(),
            "show_progress": self.progress.isChecked(),
            "route_length": self.route.value(),
            "auto_next_tree": self.auto_next.isChecked(),
            "ui_scale": self.ui_scale.value() / 100,
            "realm": self.realm.currentText(),
            "fps": self.fps.value(),
            "start_minimized": self.minimized.isChecked(),
            "appearance": self.appearance.currentData(),
            **{key: box.isChecked() for key, box in self.pob.items()},
            "keys": {a: (b.currentText() if b.currentText() != "Off" else "") for a, b in self.keys.items()},
        })
        return out
