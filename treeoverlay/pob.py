"""Working alongside Path of Building Community (read only, nothing in PoB is changed).

* PoB's Settings.xml gives the builds folder, the build it had open last and the
  pathofexile.com account it imported from.
* PoB's window title is "<build name> (<class>) - Path of Building" while a
  build is open, so the overlay can follow the build you're looking at.
* A saved build file changes on disk: reload it (PoB saves on Ctrl+S).
* Each build remembers the imported character as sha1(name)
  (<Import lastCharacterHash>), which picks the character on pathofexile.com.
* Optional changes to PoB itself (tree number in the title, the macOS-style
  look) are in pob_patch.py; nothing else here writes to PoB.
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

TITLE_SUFFIX = " - Path of Building"


def documents_dir():
    buf = ctypes.create_unicode_buffer(wt.MAX_PATH)
    try:
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL
            return Path(buf.value)
    except (OSError, AttributeError):
        pass
    return Path.home() / "Documents"


def user_dirs():
    """Where PoB keeps Settings.xml: Documents, or the install folder when portable."""
    return [documents_dir() / "Path of Building",
            Path(os.environ.get("APPDATA", "")) / "Path of Building Community"]


@dataclass
class PobSettings:
    build_dir: Path
    last_build: Path | None = None
    account: str = ""
    realm: str = "pc"


def read_settings(dirs=None):
    """PoB's settings, or None if PoB isn't installed for this user."""
    for d in dirs or user_dirs():
        f = d / "Settings.xml"
        if not f.is_file():
            continue
        out = PobSettings(build_dir=d / "Builds")
        try:
            root = ET.parse(f).getroot()
        except (ET.ParseError, OSError):
            return out
        misc = root.find("Misc")
        if misc is not None and misc.get("buildPath"):
            out.build_dir = Path(misc.get("buildPath"))
        mode = root.find("Mode")
        args = [a.get("string") or "" for a in mode.findall("Arg")] if mode is not None else []
        if mode is not None and mode.get("mode") == "BUILD" and args and args[0]:
            out.last_build = Path(args[0])                       # path, name
        elif mode is not None and mode.get("mode") == "LIST" and args and args[0]:
            sub = args[1] if len(args) > 1 else ""               # selected name, sub folder
            out.last_build = out.build_dir / sub / f"{args[0]}.xml"
        acc = root.find("Accounts")
        if acc is not None:
            out.account = acc.get("lastAccountName") or ""
            realm = (acc.get("lastRealm") or "PC").lower()
            out.realm = {"xbox": "xbox", "sony": "sony", "ps4": "sony"}.get(realm, "pc")
        return out
    return None


@dataclass
class BuildFile:
    name: str          # as PoB shows it: the file name without .xml
    path: Path
    folder: str        # sub folder below the builds folder, "" at the top
    mtime: float


def list_builds(build_dir):
    """Every build file, newest first."""
    out = []
    root = Path(build_dir)
    if not root.is_dir():
        return out
    for f in root.rglob("*.xml"):
        if f.name.startswith("~~temp~~"):
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        folder = f.parent.relative_to(root).as_posix()
        out.append(BuildFile(f.stem, f, "" if folder == "." else folder, mtime))
    out.sort(key=lambda b: -b.mtime)
    return out


def parse_title(title):
    """'CRAB TOTEM (Hierophant) [Tree 2] - Path of Building' -> ('CRAB TOTEM', 2).
    (None, None) without a build; the tree number only with the patch."""
    if not title.endswith(TITLE_SUFFIX):
        return None, None
    sub = title[:-len(TITLE_SUFFIX)]
    tree = None
    m = re.match(r"^(.*) \[Tree (\d+)\]$", sub)
    if m:
        sub, tree = m.group(1), int(m.group(2))
    m = re.match(r"^(.*) \([^()]*\)$", sub)
    return (m.group(1) if m else sub), tree


def name_from_title(title):
    """'CRAB TOTEM (Hierophant) - Path of Building' -> 'CRAB TOTEM'; None without a build."""
    return parse_title(title)[0]


def find_build(name, builds, prefer=None):
    """The file of the build PoB has open: same name; if several folders have
    one, the one PoB opened last, else the newest."""
    hits = [b for b in builds if b.name == name]
    if prefer is not None:
        for b in hits:
            if os.path.normcase(str(b.path)) == os.path.normcase(str(prefer)):
                return b
    return hits[0] if hits else None


def open_build_name():
    """Name of the build open in a running PoB, or None."""
    return open_build()[0]


def open_build():
    """(build name, tree number or None) of a running PoB, or (None, None)."""
    if os.name != "nt":
        return None, None
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    found = []

    def exe_of(hwnd):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wt.DWORD(len(buf))
            ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return buf.value if ok else ""
        finally:
            kernel32.CloseHandle(h)

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.endswith(TITLE_SUFFIX) or buf.value == "Path of Building":
                if exe_of(hwnd).lower().endswith("path of building.exe"):
                    found.append(buf.value)
                    return False
        return True

    user32.EnumWindows(visit, 0)
    return parse_title(found[0]) if found else (None, None)


def character_hash(build_path):
    """sha1 of the character the build was imported from, or None."""
    try:
        text = Path(build_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'<Import\b[^>]*\blastCharacterHash="([0-9a-f]{40})"', text)
    return m.group(1) if m else None


def character_for(build_path, names):
    """Which of the account's characters the build was imported from."""
    h = character_hash(build_path)
    if not h:
        return None
    for n in names:
        if hashlib.sha1(n.encode("utf-8")).hexdigest() == h:
            return n
    return None


def install_dir():
    """PoB's program folder (where Path of Building.exe is), or None."""
    d = Path(os.environ.get("APPDATA", "")) / "Path of Building Community"
    return d if (d / "Path of Building.exe").is_file() else None
