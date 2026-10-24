"""The settings window: everything that used to need editing settings.json."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout)

KEYS = [f"F{i}" for i in range(1, 13)]
ACTIONS = [("next_tree", "Next tree of the build"), ("calibrate", "Calibrate"),
           ("toggle", "Show / hide the overlay"), ("reset", "Reset tracking and readings")]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings
        lay = QVBoxLayout(self)

        shown = QGroupBox("Overlay")
        f = QFormLayout(shown)
        self.labels = QCheckBox("Names for upcoming notables and mastery choices")
        self.labels.setChecked(settings["show_labels"])
        self.progress = QCheckBox("Read which passives are allocated")
        self.progress.setChecked(settings["show_progress"])
        self.route = QSpinBox()
        self.route.setRange(0, 30)
        self.route.setValue(settings["route_length"])
        self.route.setSuffix(" points")
        self.auto_next = QCheckBox("Switch to the next tree when one is complete")
        self.auto_next.setChecked(settings["auto_next_tree"])
        f.addRow(self.labels)
        f.addRow(self.progress)
        f.addRow("Number the next", self.route)
        f.addRow(self.auto_next)
        lay.addWidget(shown)

        game = QGroupBox("Game")
        g = QFormLayout(game)
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
        self.fps.setSuffix(" checks/s while idle")
        g.addRow("In-game UI scale", self.ui_scale)
        g.addRow("Account realm", self.realm)
        g.addRow("Tree still", self.fps)
        lay.addWidget(game)

        keys = QGroupBox("Hotkeys (read only, the game still gets the key)")
        k = QFormLayout(keys)
        self.keys = {}
        for action, label in ACTIONS:
            box = QComboBox()
            box.addItems(["off"] + KEYS)
            box.setCurrentText(settings["keys"].get(action) or "off")
            self.keys[action] = box
            k.addRow(label, box)
        lay.addWidget(keys)

        app = QGroupBox("Program")
        a = QHBoxLayout(app)
        self.minimized = QCheckBox("Start minimized")
        self.minimized.setChecked(settings.get("start_minimized", False))
        a.addWidget(self.minimized)
        lay.addWidget(app)

        lay.addWidget(QLabel("<span style='color:gray'>UI scale and realm apply right away; "
                             "nothing here needs a restart.</span>"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def values(self):
        """The settings as they should be after OK."""
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
            "keys": {a: (b.currentText() if b.currentText() != "off" else "") for a, b in self.keys.items()},
        })
        return out
