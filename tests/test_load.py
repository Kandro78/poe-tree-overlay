"""Background downloads: a build loaded while a pobb.in / pastebin link downloads
(PoB's, followed at startup) stays and the link's result is dropped; a second
Update Tree Data click during a download does nothing.

    python tests/test_load.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit  # noqa: E402

from treeoverlay import app as A  # noqa: E402
from treeoverlay.build import Spec  # noqa: E402

QAPP = QApplication.instance() or QApplication([])
POB_XML = '<PathOfBuilding><Tree activeSpec="1"><Spec title="PoB build" classId="3" nodes="1,2"/></Tree></PathOfBuilding>'


class Window:
    """The parts of ControlWindow that load() uses."""
    load = A.ControlWindow.load

    def __init__(self):
        self.settings = {"spec": -1}
        self.spec_box, self.input = QComboBox(), QLineEdit()
        self.pob, self._file_active, self.specs = None, None, []
        self.picker = SimpleNamespace(show_toast=lambda *a, **k: None)
        self.chosen = []

    def choose_spec(self, idx, toast=True):
        self.chosen.append(self.specs[idx].title)

    def _match_character(self):
        pass


class LoadOrder(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.saved = A.SETTINGS, A.in_background
        A.SETTINGS = d / "settings.json"          # not the real settings
        self.pob_file = d / "PoB build.xml"
        self.pob_file.write_text(POB_XML, encoding="utf-8")

    def tearDown(self):
        A.SETTINGS, A.in_background = self.saved

    def test_build_loaded_during_a_link_download_stays(self):
        w = Window()

        def downloading(text, job):
            w.load(str(self.pob_file), mode="pob")      # PoB's build, followed meanwhile
            return ([Spec("Link build", 3, [1])], 0), None

        A.in_background = downloading
        w.load("https://pobb.in/abc", mode="startup")
        self.assertEqual([s.title for s in w.specs], ["PoB build"])
        self.assertEqual(w.chosen, ["PoB build"])
        self.assertEqual(w.settings["last_input"], str(self.pob_file))

    def test_link_still_loads_when_the_build_in_between_failed(self):
        w = Window()

        def downloading(text, job):
            w.load(str(self.pob_file.with_name("half saved.xml")), mode="pob")   # can't be read: nothing applied
            return ([Spec("Link build", 3, [1])], 0), None

        A.in_background = downloading
        w.load("https://pobb.in/abc", mode="startup")
        self.assertEqual(w.chosen, ["Link build"])

    def test_link_alone_loads(self):
        w = Window()
        A.in_background = lambda text, job: (([Spec("Link build", 3, [1])], 0), None)
        w.load("https://pobb.in/abc")
        self.assertEqual(w.chosen, ["Link build"])

    def test_second_update_click_while_downloading_is_ignored(self):
        w = SimpleNamespace(update_tree_data=lambda: A.ControlWindow.update_tree_data(w))
        calls = []

        def downloading(text, job):
            calls.append(text)
            w.update_tree_data()          # clicked again before the first one finished
            return None, "offline"

        A.in_background = downloading
        saved = A.QMessageBox.warning
        A.QMessageBox.warning = lambda *a: None
        try:
            w.update_tree_data()
            w.update_tree_data()          # and once it's done, it works again
        finally:
            A.QMessageBox.warning = saved
        self.assertEqual(len(calls), 2)       # one download per finished click, none for the nested clicks


if __name__ == "__main__":
    unittest.main()
