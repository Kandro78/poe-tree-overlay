# PoE Tree Overlay (Path of Exile 1)

Highlights a build's passive tree directly on the in-game passive skill tree.
Paste a Path of Building code (or link / tree URL / PoB file), open the tree
with **P**, and rings + connecting lines appear over the nodes of the build,
following panning and zooming.

The overlay also reads which passives your character has already allocated. It
fades out what's done, makes the nodes you can take *right now* pulse, labels
upcoming notables and the mastery effect the build picks, and puts a red ✕ on
allocated passives the build doesn't use (refund candidates).

## How it works

* **Build input** (`treeoverlay/build.py`): Path of Building codes, pobb.in and
  pastebin links, `pathofexile.com/passive-skill-tree/...` URLs and PoB `.xml`
  files. Every tree spec of the build is listed (leveling trees included).
* **Tree data** (`treeoverlay/tree.py`): GGG's official
  [skilltree-export](https://github.com/grindinggear/skilltree-export)
  (`data/data.json`, 3.29.1). Node positions are computed the same way as in
  Path of Building.
* **Finding the tree on screen** (`treeoverlay/tracker.py`): the game window
  is captured a few times per second (screen capture only, no memory reading,
  no input sent to the game). ORB features are matched against
  * a *reference map* built from the tree rendered with the game's own sprite
    sheets (`tools/render_tree.py`), so the tree is found without setup, and
  * a *learned map* that grows from what the game actually shows while you pan.

  The in-game tree only pans and zooms, so a scale + offset is fitted with
  RANSAC. A first guess from the whole map is only accepted after a guided
  re-match around it, which stops repeated node icons from causing false locks.
* **Is the tree open?** Once the tracker has a confident lock, it saves the
  tree screen's fixed "Skills" header (`data/gate_<width>x<height>.png`). From
  then on, the expensive search runs only while that header is on screen. It
  learns the header from the game, so it works in every client language. Delete
  the file if the game's UI changes.
* **Allocated passives** (`treeoverlay/progress.py`): allocated passives get a
  brightly lit frame (live: small passives 176+ vs at most 65 brightness,
  notables 233+ vs at most 123), so the brightness of the ring where the frame
  sits tells them apart. Masteries have no frame; their icon's colour is used
  instead. Hover tooltips darken whatever is under them. Where most nodes of a
  screen region (unallocated ones included) get much darker at once, that region
  counts as covered and keeps its old readings. Each node keeps its last reading, so the picture
  builds up as you pan. Nodes under the HUD are skipped. From that, the plan
  works out what's done, what can be taken next (a neighbour of something
  allocated), how many steps away the rest is, and what's allocated but not in
  the build.
* **Capture**: Desktop Duplication via `dxcam` (~2 ms per frame) when it
  works, GDI via `mss` (~19 ms) otherwise. Both leave out the overlay's own
  windows.
* **Dragging**: while you drag the tree, the rings follow the cursor at about
  120 Hz, from the moment you press. The game draws the tree a little behind
  the mouse (measured live: ~8–12 ms); the overlay measures that delay from
  your drags and places the rings where the tree is being drawn. The last tracker result is shifted by how far the cursor has moved
  since that frame was captured, so they don't trail the 30–150 ms a tracking
  step takes. Every tracker result re-anchors them. If the tree doesn't follow
  the cursor (e.g. you're dragging something else), the prediction switches
  off for that drag.
* **Speed**: an unchanged screen reuses the last result (~20 ms live). A pan is
  estimated with phase correlation and confirmed with a guided match (~50 ms).
  A pan is taken straight from phase correlation for up to 0.3 s between full
  checks (~5 ms). The game zooms around the mouse cursor, in fixed steps
  (at 2560x1440: 0.144, 0.234, 0.324 … 0.684, 0.09 apart, plus a few
  others), often several steps between two frames. After a zoom, every known
  step around the cursor is tried, ranked by a cheap thumbnail comparison and
  confirmed with a guided match (~50–110 ms). Small zoom changes take a
  Fourier-Mellin estimate from the thumbnails (~16 ms). Anything else falls
  back to descriptor matching (~150 ms).
* **Overlay** (`treeoverlay/app.py`): a transparent, click-through, always-on-top
  window over the game. It is excluded from screen capture
  (`WDA_EXCLUDEFROMCAPTURE`), so the tracker never sees its own drawings.

Colours: cyan = small passive, gold = notable, red = keystone,
purple = mastery, green = jewel socket / connections. Pulsing white ring = take
next. Faded ring = already allocated. Red ✕ = allocated but not in the build.

A small panel at the top left of the tree screen shows the tree's name and
progress ("33/120 allocated · 87 to go · 12 not in build"). Click the name to
pick another tree of the build (e.g. the next leveling stage). **Re-read**
reads the allocated passives again, e.g. after switching characters. Clicking
the panel doesn't take focus from the game.

The overlay leaves the game's own UI alone: globes, flasks, skill bar, the
"Skills" header and buttons, and any tooltip you're hovering are kept free.

## Setup

Python 3.10+ on Windows 10 2004+ / Windows 11.

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

The first start renders the reference tree and builds the reference map
(`data/render_0.2972.png`, `data/refmap.npz`, about 10 s). Sprites come from
`data/sprites` (downloaded from web.poecdn.com, URLs in `data.json`).

## Use

1. Run the game in **Windowed Fullscreen** (or windowed). Exclusive fullscreen
   hides overlays.
2. Paste the build into the control window and press **Load**, or pick a PoB
   file. Choose the tree in the drop-down (e.g. a leveling tree).
3. Open the passive tree in game. The status line shows *Locked* once it's found.
   Pan over the parts of the tree you've allocated once so it can read them.

Hotkeys (global and only read, so the game still gets the key press; configurable in `settings.json`):

| Key | Action |
| --- | --- |
| F6 | Next tree of the build (same as picking it in the panel) |
| F7 | Calibrate: hover the class start, press F7; hover the named notable, press F7 |
| F8 | Show / hide the overlay |
| F9 | Reset: clear the tracking map and the allocation readings (shows a note in the panel). Normally not needed; use it if the rings sit in the wrong place after a game update |

Calibrate only if the rings sit in the wrong place. It anchors the learned map
for areas where the in-game look differs too much from the rendered reference.

The control window also has **Update tree data**, which fetches the newest
passive tree from GGG's export when a new league changes it. Builds made for a
different tree version are flagged in the build info line. The *Labels* and
*Track allocated passives* boxes turn those features off.

`settings.json` also has `start_minimized` (open the control window minimized),
`fps` and `mask_rects`: screen areas the tracker ignores,
as `[x0, y0, x1, y1]` fractions of the game window. The default (`null`) masks
PoE's HUD, which stays visible over the tree: globes, flasks and skill bar, and
the "Skills" header. Learning those would make the tracker "see" the tree in
gameplay too. Adjust them for unusual aspect ratios or UI scales.

## Limits

* Ascendancy nodes aren't highlighted. The game shows them in a separate panel.
* Cluster jewel nodes aren't highlighted. Their positions depend on the jewel.
* Allocation reading needs nodes drawn at least 3 px wide. At the smallest
  zoom on small screens, zoom in a step.
* Allocation readings persist until F9, so after switching characters press F9.
* Tested live at 2560×1440, 16:9, default UI scale. The HUD masks assume that
  layout.

## Development

```
.venv\Scripts\python -m unittest tests.test_units    # build parsing, tree geometry, progress plan
.venv\Scripts\python tests\test_tracking.py auto     # no calibration
.venv\Scripts\python tests\test_tracking.py manual   # hover calibration
.venv\Scripts\python tests\test_zoom_animation.py    # zoom animations and jumps: speed and error per frame
.venv\Scripts\python tests\replay_burst.py <dump>    # replay a TREEOVERLAY_DUMP_BURST=1 recording frame by frame
.venv\Scripts\python tests\analyze_trace.py <file>   # how closely the rings followed the tree (TREEOVERLAY_TRACE)
.venv\Scripts\python -m unittest tests.test_drag      # drag prediction with a simulated mouse and game delay
.venv\Scripts\python tools\fake_game.py 60           # window titled "Path of Exile" that pans the tree
.venv\Scripts\python tests\profile_frame.py <dump>   # time the tracking steps on dumped frames
.venv\Scripts\python tests\replay_allocation.py <dump>  # allocation readings frame by frame
.venv\Scripts\python -m treeoverlay.updater           # update the tree data from the command line
```

Debug environment variables: `TREEOVERLAY_LOG=1` (print status),
`TREEOVERLAY_DUMP_DIR=<dir>` (every 2 s save the captured frame plus the tracker
result; replay with `tests\replay_dump.py <dir>`),
`TREEOVERLAY_IGNORE_FOREGROUND=1` (track even when the game isn't focused),
`TREEOVERLAY_VISIBLE_TO_CAPTURE=1` (overlay shows up in screenshots; the tracker
then sees it too, so use it only for screenshots).

## Third-party tool rules

GGG allows tools that don't read game memory, don't modify the client and
don't automate gameplay. This tool only captures the screen and draws over it.
Check GGG's current third-party policy before you share it.
