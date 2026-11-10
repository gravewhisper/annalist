import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_graph import NODE
from tests.test_graph_marks import dead, node_tag

PEOPLE = 60
ALL_TYPES = "allTypes=1"


def whole_wiki():
    names = ["Ada Hub"] + [f"Person {i:02d}" for i in range(1, PEOPLE + 1)] + ["Far One", "Far Two", "Late Comer"]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]} for i, n in enumerate(names, 1)]
    entities[-1].update(first=3, name_chapter=3)
    entities += [{"id": f"{0xa0 + i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": []}
                 for i, (n, t) in enumerate([("Harbour Guild", "organization"), ("Harbour Town", "place"), ("Old Blade", "artifact"), ("The Rite", "concept")])]
    ids = {e["name"]: e["id"] for e in entities}
    by_name = {e["name"]: e for e in entities}
    by_name["Person 02"]["profile"] = dead(3)
    rel = lambda c, a, t, b, fam: {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "quotes": []}
    person = lambda i: f"Person {i:02d}"
    relations = [rel(c, "Ada Hub", "friend of", person(i), "alliance") for i in range(1, PEOPLE + 1) for c in (1, 2)]
    relations += [rel(1, person(i), "knows", person(i + 1), "alliance") for i in range(1, PEOPLE)]
    relations += [rel(1, person(i), "member of", "Harbour Guild", "membership") for i in (1, 2, 3, 4)]
    relations += [rel(1, "Far One", "rival of", "Far Two", "hostility")]
    relations += [rel(1, "Ada Hub", "lives in", "Harbour Town", "place"), rel(1, "Ada Hub", "carries", "Old Blade", "object"), rel(1, "Ada Hub", "studies", "The Rite", "other")]
    relations += [rel(3, "Ada Hub", "friend of", "Late Comer", "alliance")]
    chapters = [{"n": n, "title": str(n), "synopsis": "Ada Hub walks." if n == 1 else ""} for n in range(1, 5)]
    return {"book": {"title": "Whole", "max": 4, "public_domain": False, "theme": {}, "power_types": [], "ladder": None}, "chapters": chapters,
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class WholeBookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(whole_wiki()), encoding="utf-8")
        cls.wiki = whole_wiki()
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def graph(self, n, query=""):
        view = f"graph:all@{n}" + (f"?{query}" if query else "")
        return site_views(self.path, view)[view]

    def nodes(self, g):
        return {nd["label"]: nd for nd in g["model"]["nodes"]}

    def text(self, html):
        return re.sub(r"<[^>]+>", "", html)

    def test_it_opens_on_people_only_and_the_other_groups_are_one_chip_away(self):
        g = self.graph(4)
        self.assertEqual({nd["type"] for nd in g["model"]["nodes"]}, {"character"})
        self.assertIn('data-ggt="lore" class=""', g["html"])
        everyone = self.graph(4, ALL_TYPES)
        self.assertEqual({nd["type"] for nd in everyone["model"]["nodes"]}, {"character", "organization", "place", "artifact", "concept"})

    def test_it_centres_on_the_top_ranked_character_unless_the_reader_centred_elsewhere(self):
        g = self.graph(4)
        self.assertEqual(g["model"]["focus"], self.id["Ada Hub"])
        self.assertEqual((self.nodes(g)["Ada Hub"]["x"], self.nodes(g)["Ada Hub"]["y"]), (0, 0))
        person = self.id["Person 07"]
        view = f"graph:all:{person}@4"
        self.assertEqual(site_views(self.path, view)[view]["model"]["focus"], person)
        remembered = site_views(self.path, f"graph:{person}@4", "graph:all@4")["graph:all@4"]
        self.assertEqual(remembered["model"]["focus"], person)

    def test_rings_grow_with_steps_from_the_centre_and_strays_sit_outside_them_all(self):
        centre_on = self.id["Person 01"]
        view = f"graph:all:{centre_on}@4"
        nodes = {nd["label"]: nd for nd in site_views(self.path, view)[view]["model"]["nodes"]}
        radius = lambda name: (nodes[name]["x"] ** 2 + nodes[name]["y"] ** 2) ** .5
        near, next_out, far = radius("Ada Hub"), radius("Person 30"), radius("Far One")
        self.assertLess(near, next_out)
        self.assertLess(max(radius(n) for n in nodes if n not in ("Far One", "Far Two")), far)

    def test_every_connected_entry_is_drawn_with_no_leftover_bubble(self):
        g = self.graph(4, ALL_TYPES)
        self.assertEqual(g["model"]["bubbles"], [])
        self.assertNotIn("data-gb=", g["html"])
        for name in ("Person 60", "Far Two", "The Rite"):
            self.assertIn(name, self.nodes(g))

    def test_only_the_longest_running_ties_are_drawn_until_show_all_ties_is_on(self):
        g = self.graph(4)
        total, drawn = g["model"]["ties"], g["model"]["links"]
        self.assertGreater(total, len(drawn))
        self.assertEqual(len(drawn), len(g["model"]["nodes"]))
        self.assertEqual({l["weight"] for l in drawn} - {1}, {2})
        self.assertIn('data-gopt="allTies"', g["html"])
        everything = self.graph(4, "allTies=1")
        self.assertEqual(len(everything["model"]["links"]), total)
        self.assertEqual([nd["x"] for nd in everything["model"]["nodes"]], [nd["x"] for nd in g["model"]["nodes"]])

    def test_the_subtitle_says_how_many_of_how_many_ties_are_drawn(self):
        g = self.graph(4)
        text = self.text(g["html"])
        self.assertIn(f'{len(g["model"]["links"])} longest-running of {g["model"]["ties"]} ties', text)
        every = self.text(self.graph(4, "allTies=1")["html"])
        self.assertIn(f'all {g["model"]["ties"]} ties', every)

    def test_dots_carry_no_initials_and_only_main_entries_are_named_at_first(self):
        g = self.graph(4)
        self.assertNotIn('class="ini"', g["html"])
        named = [nd for nd in g["model"]["nodes"] if nd.get("named")]
        self.assertEqual(len(named), 24)
        quiet = next(nd for nd in g["model"]["nodes"] if not nd.get("named"))
        self.assertRegex(g["html"], rf'class="lbl[^"]*\bhide\b[^"]*" data-for="{quiet["id"]}"')
        self.assertNotRegex(g["html"], rf'class="lbl[^"]*\bhide\b[^"]*" data-for="{self.id["Ada Hub"]}"')

    def names(self, *args):
        view = "names:" + json.dumps(args) + "@1"
        return set(site_views(self.path, view)[view])

    def test_names_show_for_mains_on_zoom_and_always_for_the_hovered_dot_without_overlapping(self):
        items = [{"id": "main", "x": 0, "y": 0, "w": 40, "main": True}, {"id": "clash", "x": 5, "y": 0, "w": 40, "main": True},
                 {"id": "minor", "x": 300, "y": 0, "w": 40, "main": False}, {"id": "under", "x": 2, "y": 0, "w": 40, "main": False}]
        self.assertEqual(self.names(items, 1, False, None, None), {"main"})
        self.assertEqual(self.names(items, 1, True, None, None), {"main", "minor"})
        self.assertEqual(self.names(items, 1, False, "under", None), {"under"})
        self.assertEqual(self.names(items, 1, False, "minor", None), {"minor", "main"})

    def test_a_death_and_new_marks_appear_only_from_their_chapter(self):
        person = self.id["Person 02"]
        before, after = self.nodes(self.graph(2))["Person 02"], self.nodes(self.graph(3))["Person 02"]
        self.assertIsNone(before["died"])
        self.assertEqual(after["died"], 3)
        html = self.graph(3)["html"]
        self.assertRegex(node_tag(html, person), r'class="gnode[^"]*dead')
        late = self.id["Late Comer"]
        at3, at4 = self.graph(3), self.graph(4)
        self.assertIn('class="ring"', node_tag(at3["html"], late))
        self.assertTrue(any(l["fresh"] and late in (l["a"], l["b"]) for l in at3["model"]["links"]))
        self.assertNotIn('class="ring"', node_tag(at4["html"], late))
        self.assertNotIn("Late Comer", {nd["label"] for nd in self.graph(2)["model"]["nodes"]})

    def test_a_centre_from_a_later_chapter_is_ignored_and_never_named(self):
        view = f'graph:all:{self.id["Late Comer"]}@2'
        g = site_views(self.path, view)[view]
        self.assertEqual(g["model"]["focus"], self.id["Ada Hub"])
        self.assertNotIn("Late Comer", g["html"])

    def test_the_entry_card_sits_in_the_side_panel_clear_of_the_drawing(self):
        html = self.graph(4)["html"]
        self.assertLess(html.index('<aside class="gpanel"'), html.index('id="gcard"'))
        self.assertLess(html.index('id="gcard"'), html.index("</aside>"))

    def test_a_group_band_joins_members_on_a_ring_and_the_biggest_is_named(self):
        g = self.graph(4)
        self.assertIn('class="band"', g["html"])
        self.assertTrue(any(b["name"] == "Harbour Guild" for b in g["model"]["bands"]))
        self.assertIn(">Harbour Guild</text>", g["html"])


if __name__ == "__main__":
    unittest.main()
