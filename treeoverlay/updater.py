"""Keep data/data.json and the sprite sheets in step with GGG's skilltree-export,
and tell whether a newer release of the overlay itself is out.

    python -m treeoverlay.updater          # update if a newer tree is out
"""
import json
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

from .tree import DATA_DIR

API = "https://api.github.com/repos/grindinggear/skilltree-export/commits?per_page=1"
RAW = "https://raw.githubusercontent.com/grindinggear/skilltree-export/master/data.json"
VERSION_FILE = DATA_DIR / "version.txt"
RELEASES = "https://api.github.com/repos/Kandro78/poe-tree-overlay/releases/latest"
RELEASES_PAGE = "https://github.com/Kandro78/poe-tree-overlay/releases/latest"
SPRITE_ZOOM = "0.2972"
# generated from the old tree; rebuilt on the next start
DERIVED = ["render_0.2972.png", "render_0.2972.json", "refmap.npz"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PoE-TreeOverlay/0.2"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def installed_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def latest_version():
    """Version of the newest export, from its commit message (e.g. "3.29.1")."""
    commit = json.loads(_get(API))[0]["commit"]["message"]
    return commit.splitlines()[0].strip()


def matches(spec_version, version):
    """PoB stores "3_29", the export is called "3.29.1": compare major.minor."""
    if not spec_version or not (version or "")[:1].isdigit():   # some export commits aren't named by version
        return True
    return spec_version.replace("_", ".").split(".")[:2] == version.split(".")[:2]


def _version_tuple(text):
    """"v0.9.2" or "0.9.2" -> (0, 9, 2); None for anything else."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def newer_release(current):
    """(version, page) of the overlay's newest release if it is newer than
    `current`, else None. Drafts and pre-releases don't count (GitHub's "latest")."""
    release = json.loads(_get(RELEASES))
    tag, cur = _version_tuple(release.get("tag_name")), _version_tuple(current)
    if tag and cur and tag > cur:
        return release["tag_name"].lstrip("v"), release.get("html_url") or RELEASES_PAGE
    return None


def update(log=print):
    """Download the newest tree if it differs. Returns the new version or None."""
    latest = latest_version()
    if latest == installed_version():
        log(f"Tree data is up to date ({latest}).")
        return None
    log(f"Downloading passive tree {latest}…")
    tmp = Path(tempfile.mkdtemp(prefix="treeoverlay_"))
    try:
        (tmp / "data.json").write_bytes(_get(RAW))
        data = json.loads((tmp / "data.json").read_text(encoding="utf-8"))
        (tmp / "sprites").mkdir()
        urls = {v[SPRITE_ZOOM]["filename"] for v in data["sprites"].values() if SPRITE_ZOOM in v}
        for url in sorted(urls):
            name = url.split("/")[-1].split("?")[0]
            log(f"  {name}")
            (tmp / "sprites" / name).write_bytes(_get(url))
        # swap in only after everything arrived
        shutil.copy2(tmp / "data.json", DATA_DIR / "data.json")
        for f in (tmp / "sprites").iterdir():
            shutil.copy2(f, DATA_DIR / "sprites" / f.name)
        for name in DERIVED:
            (DATA_DIR / name).unlink(missing_ok=True)
        VERSION_FILE.write_text(latest, encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"Updated to {latest}. Restart the overlay to rebuild the reference tree.")
    return latest


if __name__ == "__main__":
    update()
