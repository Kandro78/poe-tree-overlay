"""Unit tests that need neither the game nor a screen.

    python -m unittest tests.test_units
"""
import base64
import hashlib
import os
import tempfile
import time
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from treeoverlay import build, character, pob, updater  # noqa: E402
from treeoverlay.progress import Plan, merge_allocations  # noqa: E402
from treeoverlay.tree import PassiveTree  # noqa: E402

TREE = PassiveTree()
XML = """<PathOfBuilding><Tree activeSpec="2">
  <Spec title="Act 1" classId="3" treeVersion="3_29" nodes="54447,36774,17579" masteryEffects=""/>
  <Spec title="Maps" classId="3" ascendClassId="2" treeVersion="3_29" nodes="54447,36774,17579,33296" masteryEffects="{28680,61071}"/>
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
        self.assertEqual(TREE.ascendancy_name(specs[1].class_id, specs[1].ascend_id), "Elementalist")
        self.assertIsNone(TREE.ascendancy_name(specs[0].class_id, specs[0].ascend_id))

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


class Route(unittest.TestCase):
    def setUp(self):
        builds = list(Path.home().glob("Documents/Path of Building/Builds/**/*.xml"))
        if not builds:
            self.skipTest("no Path of Building builds on this machine")
        specs, active = build.load(str(builds[0]))
        self.plan = Plan(TREE, specs[active])

    def test_route_is_connected_and_in_the_build(self):
        route = self.plan.route(set(), 40)
        reached = {self.plan.start}
        for n in route:
            node = TREE.nodes[n]
            self.assertIn(n, self.plan.target)
            ok = bool(node.neighbours & reached) or (
                node.kind == "mastery" and any(TREE.nodes[m].group == node.group and TREE.nodes[m].kind == "notable"
                                               for m in reached))
            self.assertTrue(ok, f"step {node.name} isn't connected to what's taken")
            reached.add(n)
        self.assertEqual(len(route), len(set(route)))

    def test_route_continues_from_allocated(self):
        first = self.plan.route(set(), 10)
        later = self.plan.route(set(first[:5]), 5)
        self.assertTrue(set(later).isdisjoint(first[:5]))


class Clusters(unittest.TestCase):
    def setUp(self):
        from treeoverlay.cluster import ClusterLayout
        self.layout = ClusterLayout
        builds = [b for b in Path.home().glob("Documents/Path of Building/Builds/**/*.xml")
                  if any(n >= 0x10000 for s in build.load(str(b))[0] for n in s.nodes)]
        if not builds:
            self.skipTest("no build with cluster jewels on this machine")
        specs, active = build.load(str(builds[0]))
        self.spec = specs[active]
        self.tree = PassiveTree()

    def test_sockets_inside_clusters_match_the_tree(self):
        import math
        from treeoverlay.cluster import SOCKET_SLOT
        layout = self.layout(self.tree)
        for (size, index, parent), sid in layout.sockets.items():
            if size in (1, 0) and parent and sid in self.tree.nodes:
                parent_size = 2 if size == 1 else 1
                x, y = layout.position(int(parent), parent_size, SOCKET_SLOT[parent_size][index])
                self.assertLess(math.dist((x, y), (self.tree.nodes[sid].x, self.tree.nodes[sid].y)), 1.0)

    def test_build_cluster_nodes_are_placed_and_connected(self):
        ids = [n for n in self.spec.nodes if n >= 0x10000]
        placed = self.layout(self.tree).add_to_tree(self.spec.nodes)
        self.assertEqual(sorted(placed), sorted(ids))
        plan = Plan(self.tree, self.spec)
        for n in ids:
            self.assertIn(n, plan.target)
            if n & 0xF != 12:      # masteries hang off notables, not links
                self.assertTrue(self.tree.nodes[n].neighbours, f"cluster node {n} has no links")
        route = plan.route(set(), len(plan.target))
        self.assertTrue(set(ids) - {n for n in ids if n & 0xF == 12} <= set(route),
                        "the route doesn't reach every cluster node")


class Site(unittest.TestCase):
    def test_account_names(self):
        self.assertEqual(character.normalise_account("Some Name-1234"), "SomeName#1234")
        self.assertEqual(character.normalise_account("Name#1234"), "Name#1234")
        self.assertEqual(character.normalise_account("plain"), "plain")

    def test_parse_site_and_pob_shapes(self):
        site = {"hashes": [54447, 36774], "hashes_ex": [], "mastery_effects": {"28680": 61071}, "items": []}
        self.assertEqual(character.parse_passives(site), ({54447, 36774}, {28680: 61071}))
        self.assertEqual(character.parse_passives({"passives": site})[0], {54447, 36774})
        with self.assertRaises(character.SiteError):
            character.parse_passives({"error": {"code": 1, "message": "Resource not found"}})

    def test_merge(self):
        site = {1, 2, 3}
        # screen read 2 as unallocated (refunded since), and 4 as allocated (taken since)
        self.assertEqual(merge_allocations({4}, {2, 4}, site), {1, 3, 4})
        self.assertEqual(merge_allocations({4}, {2, 4}, None), {4})


class PathOfBuilding(unittest.TestCase):
    def test_title(self):
        self.assertEqual(pob.name_from_title("CRAB TOTEM (Hierophant) - Path of Building"), "CRAB TOTEM")
        self.assertEqual(pob.name_from_title("Worb leveling  (Witch) - Path of Building"), "Worb leveling ")
        self.assertEqual(pob.name_from_title("Flicker (2.0) (Raider) - Path of Building"), "Flicker (2.0)")
        self.assertIsNone(pob.name_from_title("Path of Building"))
        self.assertIsNone(pob.name_from_title("pobb.in - Path of Building - Google Chrome"))
        self.assertEqual(pob.parse_title("Worb leveling  (Elementalist) [Tree 4] - Path of Building"),
                         ("Worb leveling ", 4))
        self.assertEqual(pob.parse_title("CRAB TOTEM (Hierophant) - Path of Building"), ("CRAB TOTEM", None))

    def test_title_patch(self):
        d = Path(tempfile.mkdtemp())
        (d / "Classes").mkdir()
        original = ("function PassiveSpecClass:SetWindowTitleWithBuildClass()\n\tlocal classText = 'x'\n"
                    + pob.PATCH_ORIGINAL + "\nend\n").encode()
        (d / pob.PATCH_FILE).write_bytes(original)
        self.assertEqual(pob.patch_state(d), "original")
        self.assertTrue(pob.apply_patch(d, d / "backup"))
        self.assertEqual(pob.patch_state(d), "patched")
        self.assertTrue(pob.apply_patch(d, d / "backup"))            # twice changes nothing
        self.assertEqual((d / pob.PATCH_FILE).read_text().count("[Tree "), 1)
        self.assertEqual(next((d / "backup").iterdir()).read_bytes(), original)
        pob.remove_patch(d)
        self.assertEqual((d / pob.PATCH_FILE).read_bytes(), original)
        (d / pob.PATCH_FILE).write_text("-- another PoB version")
        self.assertEqual(pob.patch_state(d), "unknown")
        self.assertFalse(pob.apply_patch(d, d / "backup"))

    def _user_dir(self, mode):
        d = Path(tempfile.mkdtemp())
        (d / "Builds" / "League").mkdir(parents=True)
        (d / "Settings.xml").write_text(
            f'<PathOfBuilding>{mode}<Accounts lastAccountName="Someone#1234" lastRealm="PC"/>'
            '<Misc showTitlebarName="true"/></PathOfBuilding>', encoding="utf-8")
        return d

    def test_settings(self):
        d = self._user_dir('<Mode mode="LIST"><Arg string="Crab"/><Arg string="League/"/></Mode>')
        st = pob.read_settings([d])
        self.assertEqual(st.build_dir, d / "Builds")
        self.assertEqual(st.last_build, d / "Builds" / "League" / "Crab.xml")
        self.assertEqual((st.account, st.realm), ("Someone#1234", "pc"))
        d = self._user_dir('<Mode mode="BUILD"><Arg string="C:/x/Crab.xml"/><Arg string="Crab"/></Mode>')
        self.assertEqual(pob.read_settings([d]).last_build, Path("C:/x/Crab.xml"))
        self.assertIsNone(pob.read_settings([Path(tempfile.mkdtemp())]))

    def test_builds_and_character(self):
        d = self._user_dir("")
        old, new = d / "Builds" / "Crab.xml", d / "Builds" / "League" / "Crab.xml"
        old.write_text(XML, encoding="utf-8")
        h = hashlib.sha1("CrabGuy".encode()).hexdigest()
        new.write_text(XML.replace("<Tree", f'<Import lastCharacterHash="{h}"/><Tree'), encoding="utf-8")
        os.utime(old, (time.time() - 100, time.time() - 100))
        builds = pob.list_builds(d / "Builds")
        self.assertEqual([(b.name, b.folder) for b in builds], [("Crab", "League"), ("Crab", "")])
        self.assertEqual(pob.find_build("Crab", builds).path, new)                 # newest
        self.assertEqual(pob.find_build("Crab", builds, prefer=old).path, old)     # the one PoB opened
        self.assertIsNone(pob.find_build("Other", builds))
        self.assertEqual(pob.character_for(new, ["Someone", "CrabGuy"]), "CrabGuy")
        self.assertIsNone(pob.character_for(old, ["CrabGuy"]))


if __name__ == "__main__":
    unittest.main()
