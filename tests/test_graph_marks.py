import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_graph import NODE, hub_wiki


def dead(chapter):
    return {"fields": {"status": [{"chapter": chapter, "value": "dead", "quotes": []}]}, "lists": {}, "spoke": [], "personality": []}


def marks_wiki():
    wiki = hub_wiki()
    by_name = {e["name"]: e for e in wiki["entities"]}
    by_name["Person 01"]["profile"] = dead(4)
    by_name["Person 02"]["profile"] = dead(6)
    late = {"id": "000000ff", "name": "Late Comer", "name_chapter": 4, "type": "character", "first": 4, "aliases": [], "blurbs": [[4, "Late Comer arrives."]]}
    wiki["entities"].append(late)
    wiki["relations"].append({"chapter": 4, "source": by_name["Ada Hub"]["id"], "target": late["id"], "type": "friend of", "family": "alliance",
                              "status": "stated", "quotes": []})
    return wiki


def node_tag(markup, id_):
    return re.search(rf'<g class="[^"]*" data-gn="{id_}"[^>]*>.*?</g>', markup).group(0)


@unittest.skipIf(NODE is None, "node is not installed")
class GraphMarksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = marks_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}
        hub = cls.id["Ada Hub"]
        cls.views = {(kind, n): f"graph:{arg}@{n}?limit=40" for n in range(3, 7) for kind, arg in (("orbit", hub), ("whole", "all"))}
        cls.out = site_views(cls.path, *cls.views.values())

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def view(self, kind, n):
        return self.out[self.views[(kind, n)]]

    def died(self, kind, n):
        return {self.name[nd["id"]]: nd["died"] for nd in self.view(kind, n)["model"]["nodes"] if nd["died"] is not None}

    def test_a_character_is_faded_with_a_cross_from_the_chapter_of_their_death_and_not_before(self):
        p1 = self.id["Person 01"]
        for kind in ("orbit", "whole"):
            self.assertEqual(self.died(kind, 3), {}, kind)
            self.assertEqual(self.died(kind, 4), {"Person 01": 4}, kind)
            before, after = self.view(kind, 3)["html"], self.view(kind, 4)["html"]
            self.assertNotIn(" dead", node_tag(before, p1))
            self.assertIn(" dead", node_tag(after, p1))
            self.assertIn("Person 01 died ch 4", node_tag(after, p1))
            self.assertIn('Person 01<tspan class="dagger"> †</tspan></text>', after)
            self.assertNotIn("†", before)

    def test_no_dead_marker_uses_a_glyph_that_has_an_emoji_form(self):
        cross = re.compile(r"\u271d|&#x0*271d;|&#0*10013;", re.I)
        for f in ("app.js", "app.css", "index.html"):
            self.assertIsNone(cross.search((ROOT / "annalist" / "site" / f).read_text(encoding="utf-8")), f)
        pages = site_views(self.path, f"{self.id['Person 01']}@5", "graph:factions@5", "graph:story@5")
        for view, out in [*self.out.items(), *pages.items()]:
            self.assertIsNone(cross.search(json.dumps(out, ensure_ascii=False)), view)
        self.assertIn("†", self.view("whole", 5)["html"])
        self.assertIn('<span class="dagger">†</span>', pages["graph:factions@5"]["html"])

    def test_a_death_later_in_the_book_is_not_shown_before_its_chapter(self):
        for kind in ("orbit", "whole"):
            for n in (3, 4, 5):
                self.assertNotIn("Person 02", self.died(kind, n), (kind, n))
                self.assertNotIn("ch 6", self.view(kind, n)["html"], (kind, n))
            self.assertEqual(self.died(kind, 6)["Person 02"], 6, kind)

    def panel(self, kind, n):
        return re.search(r'<aside class="gpanel".*?</aside>', self.view(kind, n)["html"], re.S).group(0)

    def test_network_views_offer_full_screen_and_others_do_not(self):
        hub = self.id["Ada Hub"]
        out = site_views(self.path, f"graph:{hub}@4", "graph:all@4", f"graph:path:{hub}~{self.id['Late Comer']}@4", "graph:factions@4", "graph:story@4", "graph:matrix@4")
        for view, html in ((v, o["html"]) for v, o in out.items()):
            shown = 'data-gfull' in html
            self.assertEqual(shown, not view.split("@")[0].endswith(("factions", "story", "matrix")), view)
            if shown:
                self.assertIn('aria-label="Full screen"', html, view)

    def test_the_side_panel_holds_the_filters_and_legend_next_to_the_drawing(self):
        html = self.view("orbit", 4)["html"]
        stage = html.index('class="gstage drawn"')
        self.assertLess(stage, html.index('<aside class="gpanel"'))
        self.assertLess(html.index("</aside>"), html.index('<div class="gdraw">'))
        panel = self.panel("orbit", 4)
        for part in ('data-ggt="people"', "data-ggr=", "More filters", 'data-gt="character"', 'class="muted glegend"', 'id="gq"'):
            self.assertIn(part, panel)

    def test_the_side_panel_knows_nothing_a_later_chapter_adds(self):
        for kind in ("orbit", "whole"):
            early, later = self.panel(kind, 3), self.panel(kind, 4)
            counts = [int(m) for m in re.findall(r'data-ggt="people".*?<small>(\d+)</small>', early)], [int(m) for m in re.findall(r'data-ggt="people".*?<small>(\d+)</small>', later)]
            self.assertEqual(counts[1][0] - counts[0][0], 1, kind)
            self.assertNotIn("Late Comer", early, kind)

    def test_full_screen_toggles_and_ends_when_the_page_leaves_the_network_views(self):
        hub = self.id["Ada Hub"]
        out = site_views(self.path, f"route:graph:{hub}@4", "click:gfull=@4", "key:graph:Escape@4", "click:gfull=@5", "route:home@5", f"route:graph:{hub}@6")
        states = list(out.values())
        self.assertEqual([s["full"] for s in states], [False, True, False, True, False, False])
        self.assertIn('aria-label="Leave full screen"', states[1]["html"])
        self.assertIn('aria-label="Full screen"', states[2]["html"])

    def test_only_entries_and_ties_first_seen_in_the_chapter_are_marked_new(self):
        late, hub = self.id["Late Comer"], self.id["Ada Hub"]
        for kind in ("orbit", "whole"):
            at4 = self.view(kind, 4)
            self.assertEqual([nd["id"] for nd in at4["model"]["nodes"] if nd["fresh"]], [late], kind)
            self.assertEqual([{l["a"], l["b"]} for l in at4["model"]["links"] if l["fresh"]], [{hub, late}], kind)
            self.assertIn('class="ring"', node_tag(at4["html"], late))
            self.assertIn("2 new this chapter", at4["html"])
            at5 = self.view(kind, 5)
            self.assertFalse(any(nd["fresh"] for nd in at5["model"]["nodes"]), kind)
            self.assertFalse(any(l["fresh"] for l in at5["model"]["links"]), kind)
            self.assertNotIn("new this chapter", at5["html"])
            self.assertEqual([{self.name[l["a"]], self.name[l["b"]]} for l in self.view(kind, 6)["model"]["links"] if l["fresh"]], [{"Person 01", "Person 02"}], kind)


if __name__ == "__main__":
    unittest.main()
