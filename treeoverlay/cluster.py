"""Positions of cluster jewel nodes, following Path of Building's
PassiveSpec:BuildSubgraph (MIT licence, (c) the PoB Community contributors).

PoB gives the nodes a cluster jewel adds ids above 0xFFFF that encode where
they sit:
    bits 0-3  node index in the cluster template (0-11, 12 = the mastery)
    bits 4-5  jewel size (0 small, 1 medium, 2 large)
    bits 6-8  index of the large socket it hangs off
    bits 9-10 index of the medium socket inside a large cluster
With the tree's proxy groups and PoB's orbit offsets that is enough to place
them, without reading the jewels themselves.
"""
import json
import math
from pathlib import Path

from .tree import Node

TOTAL_INDICES = {0: 6, 1: 12, 2: 12}
# template slots the sockets of a cluster use, in socket order 0, 1, 2 (PoB's getJewels {0, 2, 1})
SOCKET_SLOT = {2: {0: 4, 2: 8, 1: 6}, 1: {0: 6}, 0: {0: 4}}
OFFSETS = {int(k): {int(s): v for s, v in d.items()}
           for k, d in json.loads((Path(__file__).with_name("cluster_offsets.json")).read_text()).items()}

_12_TO_16 = [0, 1, 3, 4, 5, 7, 8, 9, 11, 12, 13, 15]
_6_TO_16 = [0, 3, 5, 8, 11, 13]


def _translate(index, total, per_orbit):
    if total == per_orbit:
        return index
    if total == 12 and per_orbit == 16:
        return _12_TO_16[index]
    if total == 6 and per_orbit == 16:
        return _6_TO_16[index]
    return int(index * per_orbit / total)


def decode(node_id):
    return {"slot": node_id & 0xF, "size": (node_id >> 4) & 0x3,
            "large": (node_id >> 6) & 0x7, "medium": (node_id >> 9) & 0x3}


class ClusterLayout:
    def __init__(self, tree):
        self.tree = tree
        raw = tree.raw["nodes"]
        # jewel sockets that take cluster jewels: (size, index, parent id) -> node id
        self.sockets = {}
        for key, n in raw.items():
            ej = n.get("expansionJewel")
            if ej and not n.get("isProxy"):
                self.sockets[(ej["size"], ej["index"], str(ej.get("parent", "")))] = int(key)

    def _socket(self, size, index, parent=""):
        return self.sockets.get((size, index, str(parent)))

    def socket_for(self, info, all_ids):
        """The socket the cluster with these id bits is socketed in."""
        large = self._socket(2, info["large"])
        if large is None:
            return None
        if info["size"] == 2:
            return large
        # a smaller jewel either sits directly in the large socket, or in a
        # socket inside a large cluster there (then that large cluster's nodes are in the build)
        nested = any(i >= 0x10000 and (i >> 4) & 3 == 2 and (i >> 6) & 7 == info["large"] for i in all_ids)
        if not nested:
            return large
        medium = self._socket(1, info["medium"], large)
        if info["size"] == 1 or medium is None:
            return medium
        has_medium_cluster = any(i >= 0x10000 and (i >> 4) & 3 == 1 and (i >> 6) & 7 == info["large"]
                                 and (i >> 9) & 3 == info["medium"] for i in all_ids)
        return self._socket(0, 0, medium) if has_medium_cluster else medium

    def position(self, socket_id, size, slot):
        """(x, y) of template slot `slot` of a `size` cluster in this socket."""
        raw = self.tree.raw["nodes"][str(socket_id)]
        proxy_id = int(raw["expansionJewel"]["proxy"])
        group = self.tree.groups[self.tree.raw["nodes"][str(proxy_id)]["group"]]
        if slot == 12:                                 # the mastery sits in the middle
            return group["x"], group["y"]
        orbit = size + 1
        per_orbit = self.tree.raw["constants"]["skillsPerOrbit"][orbit]
        total = TOTAL_INDICES[size]
        start = OFFSETS.get(proxy_id, {}).get(size, 0)
        index = _translate((slot + start) % total, total, per_orbit)
        angle = self.tree.orbit_angles[orbit][index]
        r = self.tree.orbit_radii[orbit]
        return group["x"] + math.sin(angle) * r, group["y"] - math.cos(angle) * r

    def add_to_tree(self, node_ids):
        """Create Node objects for the build's cluster node ids in tree.nodes,
        linked like PoB links them. Returns the ids that could be placed."""
        ids = [i for i in node_ids if i >= 0x10000]
        placed = []
        by_cluster = {}
        for nid in ids:
            info = decode(nid)
            socket = self.socket_for(info, node_ids)
            if socket is None or info["slot"] > 12:
                continue
            x, y = self.position(socket, info["size"], info["slot"])
            cx, cy = self.position(socket, info["size"], 12)
            self.tree.groups[-socket] = {"x": cx, "y": cy}      # so ring connections draw as arcs
            kind = "mastery" if info["slot"] == 12 else "normal"
            self.tree.nodes[nid] = Node(id=nid, name="Cluster jewel passive", x=x, y=y, kind=kind,
                                        group=-socket, orbit=info["size"] + 1, orbit_index=info["slot"])
            by_cluster.setdefault((socket, info["size"]), []).append(nid)
            placed.append(nid)
        # links: around the ring in slot order (closed unless small), entrance (slot 0) to the socket
        for (socket, size), members in by_cluster.items():
            slot_of = {m: m & 0xF for m in members if m & 0xF != 12}
            # sockets inside this cluster are real tree nodes on the same ring
            for (s_size, s_index, s_parent), child in self.sockets.items():
                if s_parent == str(socket) and s_size == size - 1 and child in self.tree.nodes:
                    slot = SOCKET_SLOT[size].get(s_index)
                    if slot is not None and slot not in slot_of.values():
                        slot_of[child] = slot
            ring = sorted(slot_of, key=slot_of.get)
            for a, b in zip(ring, ring[1:]):
                self._link(a, b)
            if len(ring) > 2 and size != 0:
                self._link(ring[0], ring[-1])
            entrance = [m for m in ring if slot_of[m] == 0]
            if entrance and socket in self.tree.nodes:
                self._link(entrance[0], socket)
        return placed

    def _link(self, a, b):
        self.tree.nodes[a].neighbours.add(b)
        self.tree.nodes[b].neighbours.add(a)
