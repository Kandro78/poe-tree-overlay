"""Passive tree data from GGG's skilltree-export (data/data.json).

Coordinates are "tree units" as used by the export and Path of Building:
x grows to the right, y grows downwards, origin roughly at the Scion start.
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Orbits with 16 / 40 slots are not evenly spaced (skilltree-export README, 3.17+).
_SPECIAL_ANGLES = {
    16: [0, 30, 45, 60, 90, 120, 135, 150, 180, 210, 225, 240, 270, 300, 315, 330],
    40: [0, 10, 20, 30, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 135, 140, 150, 160, 170,
         180, 190, 200, 210, 220, 225, 230, 240, 250, 260, 270, 280, 290, 300, 310, 315, 320, 330, 340, 350],
}

CLASS_NAMES = ["Scion", "Marauder", "Ranger", "Witch", "Duelist", "Templar", "Shadow"]


def _orbit_angles(count):
    degrees = _SPECIAL_ANGLES.get(count) or [360 * i / count for i in range(count)]
    return [math.radians(a) for a in degrees]


@dataclass
class Node:
    id: int
    name: str
    x: float
    y: float
    kind: str  # normal, notable, keystone, mastery, jewel, start
    group: int
    orbit: int
    orbit_index: int
    neighbours: set = field(default_factory=set)
    ascendancy: str = ""
    class_start: int = -1  # class index for the seven class start nodes

    @property
    def radius(self):
        """Approximate radius of the node frame in tree units."""
        return {"normal": 52, "notable": 76, "keystone": 108, "mastery": 95,
                "jewel": 76, "start": 160}.get(self.kind, 52)


class PassiveTree:
    def __init__(self, path=DATA_DIR / "data.json"):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        self.raw = raw
        consts = raw["constants"]
        radii = consts["orbitRadii"]
        angles = [_orbit_angles(n) for n in consts["skillsPerOrbit"]]
        self.groups = {int(k): v for k, v in raw["groups"].items()}
        self.nodes: dict[int, Node] = {}
        for key, n in raw["nodes"].items():
            if key == "root" or "group" not in n:
                continue
            g = self.groups[n["group"]]
            a = angles[n["orbit"]][n["orbitIndex"]]
            r = radii[n["orbit"]]
            if n.get("classStartIndex") is not None:
                kind = "start"
            elif n.get("isKeystone"):
                kind = "keystone"
            elif n.get("isMastery"):
                kind = "mastery"
            elif n.get("isJewelSocket"):
                kind = "jewel"
            elif n.get("isNotable"):
                kind = "notable"
            else:
                kind = "normal"
            self.nodes[n["skill"]] = Node(
                id=n["skill"], name=n.get("name", ""),
                x=g["x"] + math.sin(a) * r, y=g["y"] - math.cos(a) * r,
                kind=kind, group=n["group"], orbit=n["orbit"], orbit_index=n["orbitIndex"],
                ascendancy=n.get("ascendancyName", ""),
                class_start=n.get("classStartIndex", -1) if n.get("classStartIndex") is not None else -1,
            )
        for key, n in raw["nodes"].items():
            nid = n.get("skill")
            if nid not in self.nodes:
                continue
            for other in n.get("out", []) + n.get("in", []):
                o = int(other)
                if o in self.nodes:
                    self.nodes[nid].neighbours.add(o)
                    self.nodes[o].neighbours.add(nid)
        self.orbit_radii = radii
        self.orbit_angles = angles
        self.bounds = (raw["min_x"], raw["min_y"], raw["max_x"], raw["max_y"])

    def class_start(self, class_id):
        for n in self.nodes.values():
            if n.class_start == class_id:
                return n
        raise KeyError(f"no start node for class {class_id}")

    def edges(self, node_ids):
        """Connections between nodes that are both in node_ids, as (a, b) pairs.

        Ascendancy nodes and connections from the class start (drawn by the
        game as part of the portrait) are skipped."""
        ids = set(node_ids)
        out = []
        for a in ids:
            na = self.nodes.get(a)
            if na is None or na.ascendancy or na.kind == "mastery":
                continue
            for b in na.neighbours:
                if b > a and b in ids:
                    nb = self.nodes[b]
                    if nb.ascendancy or nb.kind == "mastery":
                        continue
                    out.append((a, b))
        return out

    def edges_ascendancy(self, node_ids):
        """Connections between ascendancy nodes in node_ids."""
        ids = set(node_ids)
        return [(a, b) for a in ids for b in self.nodes[a].neighbours if b > a and b in ids]

    def ascendancy_name(self, class_id, ascend_id):
        """PoB's ascendClassId (1-based) to the ascendancy's name, or None."""
        ascs = self.raw["classes"][class_id].get("ascendancies", [])
        return ascs[ascend_id - 1]["id"] if 0 < ascend_id <= len(ascs) else None

    def arc(self, a, b):
        """For two nodes on the same orbit of the same group the game draws an
        arc instead of a straight line. Returns (cx, cy, r, start, sweep) in
        radians (screen angle convention, 0 = +x, clockwise positive), or None."""
        na, nb = self.nodes[a], self.nodes[b]
        if na.group != nb.group or na.orbit != nb.orbit or na.orbit == 0:
            return None
        g = self.groups[na.group]
        cx, cy = g["x"], g["y"]
        t1 = math.atan2(na.y - cy, na.x - cx)
        t2 = math.atan2(nb.y - cy, nb.x - cx)
        sweep = (t2 - t1 + math.pi) % (2 * math.pi) - math.pi  # shortest way round
        return cx, cy, self.orbit_radii[na.orbit], t1, sweep
