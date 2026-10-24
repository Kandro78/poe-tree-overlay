"""Render the passive tree from the official sprite sheets (unallocated look).

The tracker's reference images come from here; also used to generate test
frames without the game running. Output: data/render_<zoom>.png and a JSON
sidecar with the tree->pixel mapping.

    python tools/render_tree.py
"""
import math

import cv2
import numpy as np

from .tree import DATA_DIR

ZOOM = "0.2972"
MARGIN = 600  # tree units around the bounds


def load_sheet(url, cache={}):
    name = url.split("/")[-1].split("?")[0]
    if name not in cache:
        img = cv2.imread(str(DATA_DIR / "sprites" / name), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise FileNotFoundError(name)
        if img.shape[2] == 3:
            img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
        cache[name] = img
    return cache[name]


def sprite(tree, kind, key):
    entry = tree.raw["sprites"][kind][ZOOM]
    c = entry["coords"].get(key)
    if c is None:
        return None
    if isinstance(c["x"], list):  # some entries hold several variants
        c = {k: v[0] for k, v in c.items()}
    sheet = load_sheet(entry["filename"])
    return sheet[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]]


def first(*imgs):
    return next((i for i in imgs if i is not None), None)


def blit(canvas, img, cx, cy):
    h, w = img.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    x1, y1 = max(x0, 0), max(y0, 0)
    x2, y2 = min(x0 + w, canvas.shape[1]), min(y0 + h, canvas.shape[0])
    if x1 >= x2 or y1 >= y2:
        return
    src = img[y1 - y0:y2 - y0, x1 - x0:x2 - x0].astype(np.float32)
    a = src[:, :, 3:4] / 255.0
    dst = canvas[y1:y2, x1:x2].astype(np.float32)
    canvas[y1:y2, x1:x2] = (src[:, :, :3] * a + dst * (1 - a)).astype(np.uint8)


def render(tree):
    z = float(ZOOM)
    min_x, min_y, max_x, max_y = tree.bounds
    ox, oy = min_x - MARGIN, min_y - MARGIN
    w = int((max_x - min_x + 2 * MARGIN) * z)
    h = int((max_y - min_y + 2 * MARGIN) * z)
    to_px = lambda x, y: ((x - ox) * z, (y - oy) * z)

    bg = sprite(tree, "background", "Background2")[:, :, :3]
    canvas = np.tile(bg, (h // bg.shape[0] + 1, w // bg.shape[1] + 1, 1))[:h, :w].copy()

    visible = {i: n for i, n in tree.nodes.items() if not n.ascendancy and tree.raw["nodes"][str(i)].get("isBloodline") is None}
    groups_used = {n.group for n in visible.values()}

    for gid in groups_used:
        g = tree.groups[gid]
        b = g.get("background")
        if not b:
            continue
        img = sprite(tree, "groupBackground", b["image"])
        if img is None:
            continue
        px, py = to_px(g["x"], g["y"])
        if b.get("isHalfImage"):
            img = np.vstack([img, img[::-1]])
        blit(canvas, img, px, py)

    line_col = (40, 60, 75)
    for a, b in tree.edges(visible.keys()):
        arc = tree.arc(a, b)
        if arc:
            cx, cy, r, t1, sweep = arc
            px, py = to_px(cx, cy)
            start = math.degrees(t1)
            cv2.ellipse(canvas, (int(px * 16), int(py * 16)), (int(r * z * 16), int(r * z * 16)), 0,
                        start, start + math.degrees(sweep), line_col, 3, cv2.LINE_AA, shift=4)
        else:
            p1 = to_px(visible[a].x, visible[a].y)
            p2 = to_px(visible[b].x, visible[b].y)
            cv2.line(canvas, (int(p1[0] * 16), int(p1[1] * 16)), (int(p2[0] * 16), int(p2[1] * 16)),
                     line_col, 3, cv2.LINE_AA, shift=4)

    class_keys = ["centerscion", "centermarauder", "centerranger", "centerwitch", "centerduelist", "centertemplar", "centershadow"]
    for n in visible.values():
        raw = tree.raw["nodes"][str(n.id)]
        px, py = to_px(n.x, n.y)
        if n.kind == "start":
            img = first(sprite(tree, "startNode", class_keys[n.class_start]), sprite(tree, "startNode", "PSStartNodeBackgroundInactive"))
            if img is not None:
                blit(canvas, img, px, py)
            continue
        if n.kind == "mastery":
            img = first(sprite(tree, "masteryInactive", raw.get("inactiveIcon", "")), sprite(tree, "mastery", raw.get("icon", "")))
            if img is not None:
                blit(canvas, img, px, py)
            continue
        icon_kind = {"notable": "notableInactive", "keystone": "keystoneInactive"}.get(n.kind, "normalInactive")
        frame_key = {"notable": "NotableFrameUnallocated", "keystone": "KeystoneFrameUnallocated",
                     "jewel": "JewelFrameUnallocated"}.get(n.kind, "PSSkillFrame")
        if n.kind != "jewel":
            icon = sprite(tree, icon_kind, raw.get("icon", ""))
            if icon is not None:
                blit(canvas, icon, px, py)
        frame = sprite(tree, "frame", frame_key)
        if frame is not None:
            blit(canvas, frame, px, py)
    return canvas, {"zoom": z, "origin_x": ox, "origin_y": oy}


def render_ascendancy(tree, name):
    """One ascendancy as the game's popup shows it: its round background art
    centred on the start node's group, with the ascendancy's nodes on top.
    Returns the image and the same tree->pixel mapping as render()."""
    z = float(ZOOM)
    nodes = {i: n for i, n in tree.nodes.items() if n.ascendancy == name}
    start = next(n for n in nodes.values() if tree.raw["nodes"][str(n.id)].get("isAscendancyStart"))
    g = tree.groups[start.group]
    bg = sprite(tree, "ascendancy", "Classes" + name)
    half = max(bg.shape[:2]) / 2 / z + 150          # tree units from the centre to the edge, with a margin
    ox, oy = g["x"] - half, g["y"] - half
    size = int(2 * half * z)
    to_px = lambda x, y: ((x - ox) * z, (y - oy) * z)
    canvas = np.full((size, size, 3), (12, 14, 18), np.uint8)
    blit(canvas, bg, *to_px(g["x"], g["y"]))
    line_col = (40, 60, 75)
    for a, b in tree.edges_ascendancy(nodes.keys()):
        p1, p2 = to_px(nodes[a].x, nodes[a].y), to_px(nodes[b].x, nodes[b].y)
        cv2.line(canvas, (int(p1[0] * 16), int(p1[1] * 16)), (int(p2[0] * 16), int(p2[1] * 16)), line_col, 3, cv2.LINE_AA, shift=4)
    for n in nodes.values():
        raw = tree.raw["nodes"][str(n.id)]
        px, py = to_px(n.x, n.y)
        if raw.get("isAscendancyStart"):
            img = sprite(tree, "ascendancy", "AscendancyMiddle")
            if img is not None:
                blit(canvas, img, px, py)
            continue
        icon = sprite(tree, "notableInactive" if n.kind == "notable" else "normalInactive", raw.get("icon", ""))
        if icon is not None:
            blit(canvas, icon, px, py)
        frame = sprite(tree, "ascendancy", "AscendancyFrameLargeNormal" if n.kind == "notable" else "AscendancyFrameSmallNormal")
        if frame is not None:
            blit(canvas, frame, px, py)
    return canvas, {"zoom": z, "origin_x": ox, "origin_y": oy, "centre": [g["x"], g["y"]], "radius": half - 150}
