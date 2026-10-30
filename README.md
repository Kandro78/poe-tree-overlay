# PoE Tree Overlay (Path of Exile 1)

Highlights a build's passive tree directly on the in-game passive skill tree.
Paste a Path of Building code (or link / tree URL / PoB file), open the tree
with **P**, and rings and connecting lines appear over the nodes of the build,
following panning and zooming.

It also knows what your character has allocated, from the screen and
(optionally) from your public pathofexile.com profile:

* allocated passives fade out, refund candidates get a red ✕
* the next points to take are numbered (an always-connected route that heads
  for the nearest notable, keystone, jewel socket or mastery); the first one pulses
* upcoming notables are named, masteries show the effect the build picks
* a finished leveling tree switches to the build's next tree by itself
* the ascendancy panel and cluster jewel nodes are covered too

Colours: cyan = small passive, gold = notable, red = keystone,
purple = mastery, green = jewel socket / connections.

## Install and run

**Packaged app**: run `PoE Tree Overlay.exe` (built with `tools/build_exe.py`).
On first start it downloads the passive tree from GGG's export and builds its
reference images (about half a minute). Data and settings live in
`%APPDATA%\PoE Tree Overlay`.

**From source** (Python 3.10+, Windows 10 2004+ / 11):

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

Data and settings then live in the project folder (`data/`, `settings.json`).

## Use

1. Run the game in **Windowed Fullscreen** (or windowed). Exclusive fullscreen
   hides overlays.
2. Pick the build: with Path of Building Community installed, the overlay
   lists your PoB builds and, with **Follow the build open in Path of
   Building** on, switches to whatever build PoB shows (read from PoB's window
   title). Saving in PoB (Ctrl+S) updates the overlay; if you changed PoB's
   active tree, the overlay follows it. Settings → Path of Building adds more,
   by changing PoB's files:

   * **Live link**: PoB tells the overlay the build and tree it shows,
     unsaved edits included, so nothing needs saving.
   * **Tree number in the title**: " [Tree N]" in PoB's window title (follows
     tree switches without the live link).
   * **Show in-game progress**: rings on PoB's tree for passives allocated in
     game (green, red if the tree doesn't have them) and the next points
     numbered in the overlay's order.
   * **Tree hotkeys**: Ctrl+Up / Ctrl+Down switch trees on any tab (Up / Down
     already do on the Tree tab).
   * **Lower CPU use when idle**: PoB draws 20 frames a second instead of over
     100 while it's in front but unused (in the background it already slows
     down by itself).
   * **macOS-style look**: rounded controls, macOS dark greys and the Inter
     font.

   The originals are kept in `data/pob_backup` and put back when an option is
   switched off; changes show after PoB restarts. PoB's update check is taught
   to accept these files, so it no longer offers an "update" for them; a real
   PoB update still installs, and the overlay re-applies the changes
   afterwards. Or paste a PoB code, pobb.in link or
   tree URL and press **Load**. Choose the tree in the drop-down (e.g. a
   leveling stage).
3. Optional: enter your pathofexile.com account (`Name#1234`; taken from PoB
   if you imported there), press **Get characters** and pick the one you play.
   A build imported from a character in PoB picks that character by itself. The Characters tab of your profile
   must be public (Privacy Settings on pathofexile.com). Without it, the
   overlay learns what's allocated by looking at the tree as you pan.
4. Open the passive tree in game. The status line shows *Locked* once it's found.

On the tree screen, the panel at the top left shows the tree and progress
("33/120 allocated · 87 to go · 12 to refund"). Click the name to pick another
tree of the build; **Re-read** reads the allocated passives again. Clicking the
panel doesn't take focus from the game.

Closing the window keeps the overlay running in the tray; **Quit** is in the
tray icon's menu. **Settings…** covers the labels, the route length, the next
tree switch, the in-game UI scale, the account realm and the hotkeys:

| Default key | Action |
| --- | --- |
| F6 | Next tree of the build |
| F7 | Calibrate: hover the class start, press F7; hover the named notable, press F7 |
| F8 | Show / hide the overlay |
| F9 | Reset the tracking map and the allocation readings |

Hotkeys are only read, the game still gets the key press. Calibrating is
rarely needed: only if the rings sit in the wrong place.

**Update tree data** fetches the newest passive tree when a new league changes
it. Builds made for a different tree version are flagged in the build info line.

## How it works

* **Build input** (`build.py`): Path of Building codes, pobb.in and pastebin
  links, `pathofexile.com/passive-skill-tree/...` URLs and PoB `.xml` files.
* **Path of Building** (`pob.py`): reads PoB's `Settings.xml` (builds folder,
  account), its window title (the open build) and the build files (reloaded
  when saved; `<Import lastCharacterHash>` is sha1 of the character name).
* **PoB changes** (`pob_patch.py`, `pob_theme/`, `pob_extras/`): optional.
  Exact text swaps in PoB's Lua (undone by swapping back; a PoB version with
  different code is left alone), the theme module that wraps PoB's drawing
  calls (the passive tree is drawn without it, which keeps it free), Inter
  redrawn as PoB's bitmap fonts (`tools/make_pob_theme.py`), and
  `PoETreeOverlay.lua` for the rest. That one reads `pob_extras.cfg` and
  swaps files with the overlay in `%APPDATA%\PoE Tree Overlay`: it writes
  `pob_live.xml` (PoB's own `SaveDB` output) and `pob_live.txt` (file, build
  name, active tree, revision) a quarter second after each change, and reads
  `pob_marks.txt` (build, tree, allocated node ids, route) every second. The
  frame limiter sleeps through LuaJIT's FFI. `debug=1` in the cfg logs to
  `pob_extras.log`. PoB's
  `UpdateCheck.lua` reads `PoETreeOverlay.sha1` (changed file, our hash,
  release hash) and counts a listed file as the release while the release
  still has that hash.
* **Tree data** (`tree.py`, `updater.py`): GGG's
  [skilltree-export](https://github.com/grindinggear/skilltree-export); node
  positions are computed the same way as in Path of Building.
* **Finding the tree** (`tracker.py`): the game window is captured (Desktop
  Duplication via `dxcam`, ~2 ms; GDI via `mss` as fallback; screen capture
  only, no memory reading, no input sent to the game). ORB features are
  matched against the tree rendered from the game's own sprites (`render.py`)
  and against what the game showed earlier, and a scale + offset is fitted
  with RANSAC. Unchanged screens cost ~20 ms, pans ~5 ms (phase correlation,
  checked against the map every 0.3 s), zooms ~50–110 ms (the game zooms
  around the cursor in fixed steps; all known steps are tried).
* **Tree open?** The tree screen's "Skills" header is learned once and checked
  every frame; nothing heavy runs while the tree is closed.
* **Game UI** (`hud.py`): globes, flasks, skill bar, header and buttons are
  anchored to the screen edges and sized by the window height and UI scale.
  They're left out of tracking and never drawn over, nor are tooltips.
* **Allocated passives** (`progress.py`, `character.py`): allocated passives
  have a brightly lit frame; the brightness where the frame sits tells them
  apart (masteries: icon colour). Popups that darken a whole region are
  recognised and ignored. The site's data covers what hasn't been seen; the
  screen wins where it has.
* **Dragging** (`app.py`): from the press, the rings follow the cursor at
  ~250 Hz, shifted by how far the cursor moved since the last tracked frame,
  with the game's own drawing delay (measured from your drags) taken into
  account. If the tree doesn't follow the cursor, that drag isn't predicted.
* **Ascendancy panel** (`ascendancy.py`): a second tracker looks for the round
  panel, rendered from the game's art, while you're not dragging.
* **Cluster jewels** (`cluster.py`): PoB's cluster node ids encode slot, jewel
  size and socket; with PoB's orbit offsets (`cluster_offsets.json`, from PoB,
  MIT licence) they're placed exactly where PoB places them.
* **Overlay**: transparent, click-through windows excluded from screen capture
  (`WDA_EXCLUDEFROMCAPTURE`), so the tracker never sees its own drawings.

## Limits

* Ascendancy panel detection is tested on rendered frames only; the real
  panel's look may need tuning.
* Cluster jewel notables are drawn like small passives (which slots hold
  notables depends on the jewel itself).
* Tested live at 2560×1440, 16:9, UI scale 100 %. Other sizes and UI scales
  are tested on rendered frames.
* Allocation reading needs nodes drawn at least 3 px wide: at the smallest zoom
  on small screens, zoom in a step.

## Development

```
.venv\Scripts\python -m unittest tests.test_units tests.test_drag   # parsing, geometry, route, clusters, site, drag prediction
.venv\Scripts\python tests\test_tracking.py auto      # tracking a pan/zoom path on rendered frames
.venv\Scripts\python tests\test_zoom_animation.py     # zoom animations and jumps
.venv\Scripts\python tests\test_resolutions.py        # 1080p, ultrawide, 120 % UI scale
.venv\Scripts\python tests\test_ascendancy.py         # finding the ascendancy panel
.venv\Scripts\python tools\soak.py 10                 # CPU and memory over 10 minutes (needs psutil)
.venv\Scripts\python tools\build_exe.py               # dist\PoE Tree Overlay\PoE Tree Overlay.exe (needs pyinstaller)
```

Recording and replaying live sessions: `TREEOVERLAY_DUMP_DIR=<dir>` saves a
frame every 2 s (`TREEOVERLAY_DUMP_BURST=1`: every frame) plus the tracker's
result, for `tests\replay_dump.py`, `tests\replay_burst.py` and
`tests\replay_allocation.py`. `TREEOVERLAY_TRACE=<file>` logs every tracker
result and ring update for `tests\analyze_trace.py`. `TREEOVERLAY_LOG=1`
prints the status, `TREEOVERLAY_FAKE_GAME=1` makes `tools\fake_game.py`'s
window count as the game.

## Third-party tool rules

GGG allows tools that don't read game memory, don't modify the client and
don't automate gameplay. This tool only captures the screen, draws over it and
reads public profile data. Check GGG's current third-party policy before you
share it.
