"""Unit tests that need neither the game nor a screen.

    python -m unittest tests.test_units
"""
import base64
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay import build, updater  # noqa: E402
from treeoverlay.progress import Plan  # noqa: E402
from treeoverlay.tree import PassiveTree  # noqa: E402

TREE = PassiveTree()
XML = """<PathOfBuilding><Tree activeSpec="2">
  <Spec title="Act 1" classId="3" treeVersion="3_29" nodes="54447,36774,17579" masteryEffects=""/>
  <Spec title="Maps" classId="3" treeVersion="3_29" nodes="54447,36774,17579,33296" masteryEffects="{28680,61071}"/>
</Tree></PathOfBuilding>"""


def tree_url(class_id, nodes, masteries=()):
    data = struct.pack(">IBBB", 6, class_id, 0, len(nodes)) + struct.pack(f">{len(nodes)}H", *nodes)
    data += struct.pack(">B", 0)                                   # cluster nodes
    data += struct.pack(">B", len(masteries))
    for node, effect in masteries:
        data += struct.pack(">HH", effect, node)
    return "https://www.pathofexile.com/passive-skill-tree/" + base64.urlsafe_b64encode(data).decode()


class BuildInput(unittest.TestCase):
    def test_xml_specs_and_active(self):
        specs, active = build.specs_from_xml(XML)
        self.assertEqual([s.title for s in specs], ["Act 1", "Maps"])
        self.assertEqual(active, 1)
        self.assertEqual(specs[1].masteries, {28680: 61071})

    def test_pob_code(self):
        code = base64.urlsafe_b64encode(zlib.compress(XML.encode())).decode()
        specs, active = build.load(code)
        self.assertEqual(specs[1].nodes, [54447, 36774, 17579, 33296])

    def test_tree_url_v6(self):
        specs, _ = build.load(tree_url(3, [36774, 17579], [(28680, 61071)]))
        self.assertEqual(specs[0].class_id, 3)
        self.assertEqual(specs[0].nodes, [36774, 17579])
        self.assertEqual(specs[0].masteries, {28680: 61071})

    def test_garbage(self):
        with self.assertRaises(ValueError):
            build.load("definitely not a build")

    def test_version_match(self):
        self.assertTrue(updater.matches("3_29", "3.29.1"))
        self.assertFalse(updater.matches("3_28", "3.29.1"))
        self.assertTrue(updater.matches("", "3.29.1"))


class TreeGeometry(unittest.TestCase):
    def test_witch_start(self):
        w = TREE.class_start(3)
        self.assertEqual(w.id, 54447)
        self.assertAlmostEqual(w.x, -4, delta=2)
        self.assertAlmostEqual(w.y, -3180, delta=2)

    def test_neighbours_symmetric(self):
        for n in TREE.nodes.values():
            for m in n.neighbours:
                self.assertIn(n.id, TREE.nodes[m].neighbours)


class Progress(unittest.TestCase):
    def setUp(self):
        start = TREE.class_start(3)
        # a short path out of the Witch start
        path = [start.id]
        while len(path) < 6:
            nxt = min((m for m in TREE.nodes[path[-1]].neighbours
                       if m not in path and not TREE.nodes[m].ascendancy and TREE.nodes[m].kind != "start"),
                      default=None)
            if nxt is None:
                break
            path.append(nxt)
        self.path = path[1:]
        self.plan = Plan(TREE, build.Spec("t", 3, path))

    def test_nothing_allocated(self):
        st = self.plan.status(set(), set(self.path))
        self.assertEqual(st["next"], {self.path[0]})
        self.assertEqual(st["step"][self.path[-1]], len(self.path))

    def test_partly_allocated(self):
        st = self.plan.status(set(self.path[:2]), set(self.path))
        self.assertEqual(st["done"], set(self.path[:2]))
        self.assertIn(self.path[2], st["next"])
        self.assertEqual(st["wrong"], set())

    def test_wrong_node(self):
        other = next(n.id for n in TREE.nodes.values()
                     if n.kind == "normal" and not n.ascendancy and n.id not in self.path)
        st = self.plan.status({other}, {other})
        self.assertEqual(st["wrong"], {other})

    def test_complete(self):
        st = self.plan.status(set(self.path), set(self.path))
        self.assertFalse(st["todo"])


if __name__ == "__main__":
    unittest.main()
