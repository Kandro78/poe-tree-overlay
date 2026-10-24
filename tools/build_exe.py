"""Build the Windows app with PyInstaller: dist/PoE Tree Overlay/PoE Tree Overlay.exe

    python tools/build_exe.py

Tree data isn't bundled; the app downloads it from GGG on first start into
%APPDATA%/PoE Tree Overlay, where its settings live too.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)

# the icon: the app draws it, PyInstaller wants an .ico
from PySide6.QtGui import QGuiApplication  # noqa: E402
app = QGuiApplication([])
sys.path.insert(0, str(ROOT))
from treeoverlay.app import app_icon  # noqa: E402
icon = BUILD / "icon.ico"
app_icon().pixmap(64, 64).save(str(icon), "ICO")

subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "PoE Tree Overlay",
    "--icon", str(icon),
    "--add-data", f"{ROOT / 'treeoverlay' / 'cluster_offsets.json'};treeoverlay",
    "--collect-submodules", "dxcam",
    "--collect-submodules", "comtypes",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(BUILD / "pyinstaller"),
    "--specpath", str(BUILD),
    str(ROOT / "run.py"),
], check=True, cwd=ROOT)
print("built", ROOT / "dist" / "PoE Tree Overlay" / "PoE Tree Overlay.exe")
