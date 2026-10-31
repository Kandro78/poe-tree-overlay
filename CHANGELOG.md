# Changelog

## 0.9.2 (2026-10-31)

* The download window (Update Tree Data, pobb.in / pastebin links) no longer
  takes the focus from the game.
* A build Path of Building has open is no longer replaced by a pobb.in /
  pastebin link that was still downloading at startup.
* A second Update Tree Data click during a download is ignored instead of
  starting another download.
* After a damaged data file, restarting the overlay downloads the tree data
  again (Update Tree Data couldn't repair it).

## 0.9.1 (2026-10-31)

* Clear Learned Map (F9) now also relearns the tree screen's header, so the
  overlay no longer stays hidden for good after a game language or UI change.
* Update Tree Data and pobb.in / pastebin links load in the background
  instead of freezing the app and the overlay.
* No false "this build is for another tree" warning when GGG's tree export
  has a commit that isn't named by version.
* A damaged data file shows an error and is rebuilt on the next start; an
  interrupted first download is fetched again.
* Unexpected answers from pathofexile.com show an error instead of hanging.
* Errors the overlay recovers from are now written to `log.txt` too.
* Settings are saved safely (a crash mid-save can't wipe them).

## 0.9.0 (2026-10-30) — first public release

* Build overlay on the in-game passive tree: rings, connections, refund marks,
  numbered next points, mastery effects and the build's jewels per socket.
* Tracks panning, zooming (wheel prediction), dragging and flicks; ascendancy
  panel and cluster jewels included.
* Reads allocated passives from the screen and, optionally, from the public
  pathofexile.com profile; finished leveling trees switch to the next tree.
* Path of Building integration (all optional, each reversible): live link,
  tree number in the title, in-game progress marks on PoB's tree, tree
  hotkeys, idle frame limiter, support gem DPS, macOS-style look in dark or
  light.
* Crash log in `%APPDATA%\PoE Tree Overlay\log.txt`.
