"""Changes PoE Tree Overlay can make to Path of Building, and undo.

* "title": Classes/PassiveSpec.lua adds " [Tree N]" to PoB's window title, so
  the overlay follows tree switches without saving.
* "theme": a macOS-style look: Modules/PoETreeOverlayTheme.lua (rounded boxes,
  macOS dark greys), loaded from Modules/Main.lua, and the UI font redrawn
  with Inter (SimpleGraphic/Fonts/Liberation Sans*).
* "quiet": goes with either. PoB checks its files against the release at each
  start and offers to "update" changed ones, which would undo the changes.
  PoETreeOverlay.sha1 lists each changed file with its original hash, and
  UpdateCheck.lua counts a listed file as the original while PoB's release
  still has that original. A real PoB update still updates everything.

Text changes swap one exact piece of PoB's code for another and back; a PoB
version where that piece differs is left alone ("unknown"). Replaced files are
backed up first and put back on undo.
"""
import hashlib
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

if getattr(sys, "frozen", False):
    THEME_DIR = Path(sys._MEIPASS) / "treeoverlay" / "pob_theme"
else:
    THEME_DIR = Path(__file__).resolve().parent / "pob_theme"
HASH_LIST = "PoETreeOverlay.sha1"


@dataclass
class TextPatch:
    file: str
    original: str
    new: str


TITLE_ORIGINAL = '\tmain:SetWindowTitleSubtext(string.format("%s (%s)", self.build.buildName, classText))'
TITLE_NEW = '''\t-- PoE Tree Overlay: the active tree's number in the title, so the overlay can follow it
\tlocal treeTab, treeText = self.build.treeTab, ""
\tif treeTab and treeTab.specList and treeTab.specList[treeTab.activeSpec] == self then
\t\ttreeText = " [Tree " .. treeTab.activeSpec .. "]"
\tend
\tmain:SetWindowTitleSubtext(string.format("%s (%s)%s", self.build.buildName, classText, treeText))
\t-- PoE Tree Overlay end'''

MAIN_ORIGINAL = 'ToastNotification = LoadModule("Modules/ToastNotification")\n'
MAIN_NEW = MAIN_ORIGINAL + '''-- PoE Tree Overlay: macOS-style look (Modules/PoETreeOverlayTheme.lua)
pcall(LoadModule, "Modules/PoETreeOverlayTheme")
'''

QUIET_LIST_ORIGINAL = '-- Build lists of files to be updated or deleted\n'
QUIET_LIST_NEW = r'''-- PoE Tree Overlay: files it changed on purpose, with the hash of the original
local overlayFiles = { }
do
	local listFile = io.open(scriptPath.."/PoETreeOverlay.sha1", "r")
	if listFile then
		for line in listFile:lines() do
			local listName, patched, original = line:match("^(.-)\t(%x+)\t(%x+)")
			if listName then
				overlayFiles[listName] = { patched = patched, original = original }
			end
		end
		listFile:close()
	end
end
-- PoE Tree Overlay end
''' + QUIET_LIST_ORIGINAL
QUIET_CHECK_ORIGINAL = ('\t\t\tif data.sha1 ~= sha1(content) and data.sha1 ~= sha1(content:gsub("\\n", "\\r\\n")) then\n'
                        '\t\t\t\tConPrintf("Warning: Integrity check on \'%s\' failed, it will be replaced", data.name)\n')
QUIET_CHECK_NEW = r'''			-- PoE Tree Overlay: a file it changed counts as the original while that is still current
			local contentSha = sha1(content)
			local changed = overlayFiles[name] or overlayFiles[(name:gsub("{space}", " "))]
			if changed and changed.patched == contentSha and changed.original == data.sha1 then
				contentSha = data.sha1
			end
			if data.sha1 ~= contentSha and data.sha1 ~= sha1(content:gsub("\n", "\r\n")) then
				ConPrintf("Warning: Integrity check on '%s' failed, it will be replaced", data.name)
'''

TEXT = {
    "title": [TextPatch("Classes/PassiveSpec.lua", TITLE_ORIGINAL, TITLE_NEW)],
    "theme": [TextPatch("Modules/Main.lua", MAIN_ORIGINAL, MAIN_NEW)],
    "quiet": [TextPatch("UpdateCheck.lua", QUIET_LIST_ORIGINAL, QUIET_LIST_NEW),
              TextPatch("UpdateCheck.lua", QUIET_CHECK_ORIGINAL, QUIET_CHECK_NEW)],
}


def theme_files():
    """(path in PoB, file of ours) for every file the theme adds or replaces."""
    out = []
    for f in sorted(THEME_DIR.rglob("*")):
        if f.is_file():
            out.append((f.relative_to(THEME_DIR).as_posix(), f))
    return out


def sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def is_release(path, released_sha):
    """PoB's own test: its manifest hashes text files with CRLF line ends,
    they're installed with LF, and either counts."""
    data = Path(path).read_bytes()
    return released_sha in (hashlib.sha1(data).hexdigest(), hashlib.sha1(data.replace(b"\n", b"\r\n")).hexdigest())


def manifest_hashes(pob_dir):
    """name -> sha1 from PoB's own manifest (what its release has)."""
    try:
        text = (Path(pob_dir) / "manifest.xml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {m.group(1).replace("{space}", " "): m.group(2)
            for m in re.finditer(r'<File [^>]*name="([^"]+)"[^>]*sha1="([0-9a-f]{40})"', text)}


# -- one feature ---------------------------------------------------------------------
def _text_state(pob_dir, p):
    try:
        text = (Path(pob_dir) / p.file).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return "unknown"
    if p.new in text:
        return "on"
    return "off" if text.count(p.original) == 1 else "unknown"


def _backup(pob_dir, rel, backup_dir):
    """Keep PoB's file as it is now (once per version of it)."""
    src = Path(pob_dir) / rel
    dst = Path(backup_dir) / rel
    dst = dst.with_name(f"{dst.stem}.{sha1(src)[:12]}{dst.suffix}")
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def state(pob_dir, feature):
    """"on", "off", "partial" or "unknown" (this PoB version's code differs)."""
    states = [_text_state(pob_dir, p) for p in TEXT.get(feature, [])]
    if feature == "theme":
        states += ["on" if (Path(pob_dir) / rel).is_file() and sha1(Path(pob_dir) / rel) == sha1(ours) else "off"
                   for rel, ours in theme_files()]
    if "unknown" in states:
        return "unknown"
    if all(s == "on" for s in states):
        return "on"
    return "off" if all(s == "off" for s in states) else "partial"


def apply(pob_dir, feature, backup_dir):
    if state(pob_dir, feature) == "unknown":
        return False
    for p in TEXT.get(feature, []):
        f = Path(pob_dir) / p.file
        text = f.read_bytes().decode("utf-8")
        if p.new not in text:
            _backup(pob_dir, p.file, Path(backup_dir) / "original")
            f.write_bytes(text.replace(p.original, p.new).encode("utf-8"))
    if feature == "theme":
        for rel, ours in theme_files():
            dst = Path(pob_dir) / rel
            if dst.is_file() and sha1(dst) == sha1(ours):
                continue
            if dst.is_file():
                _backup(pob_dir, rel, Path(backup_dir) / "original")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ours, dst)
    return True


def remove(pob_dir, feature, backup_dir):
    for p in TEXT.get(feature, []):
        f = Path(pob_dir) / p.file
        try:
            text = f.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if p.new in text:
            f.write_bytes(text.replace(p.new, p.original).encode("utf-8"))
    if feature == "theme":
        released = manifest_hashes(pob_dir)
        for rel, ours in theme_files():
            dst = Path(pob_dir) / rel
            if not dst.is_file() or sha1(dst) != sha1(ours):
                continue                       # not ours (any more): PoB's own
            if rel not in released:
                dst.unlink()                   # a file the theme added
                continue
            # the file as it was before the theme: the released one, else the latest kept
            backups = sorted((Path(backup_dir) / "original" / rel).parent.glob(f"{Path(rel).stem}.*{Path(rel).suffix}"),
                             key=lambda b: b.stat().st_mtime, reverse=True)
            match = [b for b in backups if is_release(b, released[rel])] or backups
            if match:
                shutil.copyfile(match[0], dst)


# -- all of it --------------------------------------------------------------------------
def sync(pob_dir, wanted, backup_dir):
    """Make PoB match `wanted` (a set of "title" / "theme"), with the quiet
    update check whenever anything is changed. Returns each feature's state."""
    wanted = set(wanted)
    if wanted:
        wanted.add("quiet")
    for feature in ("title", "theme"):
        if feature not in wanted:
            remove(pob_dir, feature, backup_dir)
    if "quiet" not in wanted:
        remove(pob_dir, "quiet", backup_dir)
    for feature in ("quiet", "title", "theme"):
        if feature in wanted:
            apply(pob_dir, feature, backup_dir)
    write_hash_list(pob_dir)
    return {f: state(pob_dir, f) for f in ("title", "theme", "quiet")}


def write_hash_list(pob_dir):
    """PoETreeOverlay.sha1: every released file that differs from the release
    because of us, with the release's hash (read by the patched UpdateCheck)."""
    released = manifest_hashes(pob_dir)
    changed = {p.file for ps in TEXT.values() for p in ps if _text_state(pob_dir, p) == "on"}
    changed |= {rel for rel, ours in theme_files()
                if (Path(pob_dir) / rel).is_file() and sha1(Path(pob_dir) / rel) == sha1(ours)}
    lines = [f"{rel}\t{sha1(Path(pob_dir) / rel)}\t{released[rel]}" for rel in sorted(changed) if rel in released]
    target = Path(pob_dir) / HASH_LIST
    if lines:
        target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    elif target.exists():
        target.unlink()
