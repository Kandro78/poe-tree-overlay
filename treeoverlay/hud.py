"""Where the game's own UI sits on the passive tree screen, for any window size.

PoE pins its HUD to the screen edges and sizes it by the screen height (and
the in-game UI scale). Measured at 2560x1440 with UI scale 100 %:
each area is (x anchor, x from, x to, y anchor, y from, y to), distances in
units of the window height, measured from the anchor.
"""

AREAS = [
    ("left",   0.000, 0.208, "bottom", 0.000, 0.258),   # life globe
    ("left",   0.208, 0.516, "bottom", 0.000, 0.135),   # flasks
    ("right",  0.208, 0.523, "bottom", 0.000, 0.135),   # skill bar
    ("right",  0.000, 0.210, "bottom", 0.000, 0.244),   # mana globe
    ("full",   0.000, 0.000, "bottom", 0.000, 0.025),   # experience bar
    ("centre", -0.299, 0.299, "top",   0.000, 0.083),   # "Skills" header with search box
    ("centre", -0.196, 0.196, "top",   0.083, 0.170),   # refund / apply / cancel buttons
    ("left",   0.000, 0.021, "top",    0.670, 0.720),   # small buttons at the left edge
]

# the fixed patch of the "Skills" header that tells whether the tree is open
GATE = ("centre", -0.142, 0.107, "top", 0.000, 0.055)


def _to_fractions(area, w, h, ui_scale):
    xa, x0, x1, ya, y0, y1 = area
    k = h * ui_scale
    if xa == "full":
        fx0, fx1 = 0.0, 1.0
    elif xa == "left":
        fx0, fx1 = x0 * k / w, x1 * k / w
    elif xa == "right":
        fx0, fx1 = 1 - x1 * k / w, 1 - x0 * k / w
    else:
        fx0, fx1 = 0.5 + x0 * k / w, 0.5 + x1 * k / w
    if ya == "top":
        fy0, fy1 = y0 * k / h, y1 * k / h
    else:
        fy0, fy1 = 1 - y1 * k / h, 1 - y0 * k / h
    clamp = lambda v: min(1.0, max(0.0, v))
    return clamp(fx0), clamp(fy0), clamp(fx1), clamp(fy1)


def ui_rects(w, h, ui_scale=1.0):
    """The HUD areas as (x0, y0, x1, y1) fractions of a w x h window."""
    return [_to_fractions(a, w, h, ui_scale) for a in AREAS]


def gate_rect(w, h, ui_scale=1.0):
    return _to_fractions(GATE, w, h, ui_scale)
