import html as html_lib
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_graph import NODE

CLIQUE_A = ("Ash", "Bex", "Cal")
CLIQUE_B = ("Dov", "Eda", "Fen")
FILLERS = [f"Filler {i:02d}" for i in range(1, 57)]


def matrix_wiki():
    present = {"Ash": range(1, 7), "Loner": range(1, 7), "Dov": range(1, 6), "Bex": range(1, 5), "Eda": range(1, 4),
               "Lux": range(4, 7), "Cal": range(1, 3), "Fen": [1], **{f: [6] for f in FILLERS}}
    first = {"Lux": 4, **{f: 6 for f in FILLERS}}
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": first.get(n, 1), "type": "character", "first": first.get(n, 1), "aliases": [],
                 "blurbs": [[first.get(n, 1), f"{n} is here."]], "present": list(present[n])} for i, n in enumerate(present, 1)]
    entities.append({"id": "000000f0", "name": "Harbour", "name_chapter": 1, "type": "place", "first": 1, "aliases": [], "blurbs": []})
    ids = {e["name"]: e["id"] for e in entities}
    rel = lambda c, a, t, b, fam: {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "quotes": []}
    relations = [rel(c, a, "ally of", b, "alliance") for c in (1, 2, 3) for a, b in (("Ash", "Bex"), ("Ash", "Cal"), ("Bex", "Cal"))]
    relations += [rel(c, a, "sibling of", b, "kin") for c in (1, 2, 3) for a, b in (("Dov", "Eda"), ("Dov", "Fen"), ("Eda", "Fen"))]
    relations += [rel(2, "Ash", "trusts", "Dov", "alliance"), rel(5, "Ash", "betrays", "Dov", "hostility")]
    relations += [rel(4, "Lux", "rescues", "Ash", "alliance"), rel(6, "Bex", "duels", "Eda", "hostility"), rel(1, "Ash", "lives in", "Harbour", "place")]
    relations += [rel(6, f, "met", "Ash", "alliance") for f in FILLERS]
    by = {e["name"]: e for e in entities}
    by["Fen"]["profile"] = {"fields": {"status": [{"chapter": 5, "value": "dead", "quotes": []}]}, "lists": {}, "spoke": [], "personality": []}
    return {"book": {"title": "Matrix", "max": 6, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


def tags(markup, cls):
    found = re.findall(rf'<(?:a|div) ([^>]*\bclass="{cls}(?: [^"]*)?"[^>]*)>', markup)
    return [{k: html_lib.unescape(v) for k, v in re.findall(r'([\w-]+)="([^"]*)"', attrs)} for attrs in found]


@unittest.skipIf(NODE is None, "node is not installed")
class MatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = matrix_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}
        cls.out = site_views(cls.path, *(f"graph:matrix@{n}" for n in range(1, 7)))

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def view(self, n):
        return self.out[f"graph:matrix@{n}"]

    def names(self, n):
        return [self.name[i] for i in self.view(n)["model"]["ids"]]

    def cells(self, n):
        pairs = {}
        for cell in tags(self.view(n)["html"], "mcell"):
            a, b = cell["data-go"].removeprefix("graph:path:").split("~")
            kind = re.search(r"\bk-(\w+)", cell["class"]).group(1)
            pairs[(self.name[a], self.name[b])] = {**cell, "kind": kind, "new": " new" in cell["class"]}
        return pairs

    def test_only_characters_known_by_the_chapter_with_a_tie_appear_up_to_sixty_in_story_order(self):
        self.assertNotIn("Lux", self.names(3))
        self.assertIn("Lux", self.names(4))
        for n in range(1, 7):
            self.assertNotIn("Loner", self.names(n), n)
            self.assertNotIn("Harbour", self.names(n), n)
            self.assertNotIn("Harbour", self.view(n)["html"], n)
        self.assertEqual(len(self.names(6)), 60)
        self.assertEqual(set(self.names(6)), {*CLIQUE_A, *CLIQUE_B, "Lux", *FILLERS[:53]})
        self.assertNotIn("Filler 54", self.view(6)["html"])

    def test_no_tie_from_a_later_chapter_is_drawn(self):
        for n in range(1, 7):
            m = self.view(n)["model"]
            self.assertTrue(all(max(r["chapters"]) <= n for c in m["links"] for r in c["rows"]), n)
        self.assertNotIn(("Bex", "Eda"), self.cells(5))
        self.assertNotIn("duels", self.view(5)["html"])
        self.assertNotIn("betrays", self.view(4)["html"])
        self.assertEqual(self.cells(6)[("Bex", "Eda")]["kind"], "conflict")

    def test_the_order_is_the_same_however_the_chapters_were_visited_and_keeps_tight_groups_together(self):
        again = site_views(self.path, "graph:matrix@3", "graph:matrix@6?limit=5", "graph:matrix@6")
        self.assertEqual([self.name[i] for i in again["graph:matrix@6"]["model"]["ids"]], self.names(6))
        self.assertEqual([self.name[i] for i in again["graph:matrix@6?limit=5"]["model"]["ids"]], self.names(6))
        for n in (3, 4, 6):
            order = self.names(n)
            self.assertEqual(order[0], "Ash", n)
            for clique in (CLIQUE_A, CLIQUE_B):
                at = sorted(order.index(x) for x in clique)
                self.assertEqual(at, list(range(at[0], at[0] + 3)), (n, clique, order))

    def test_every_cell_has_its_mirror_with_the_same_kind_and_the_diagonal_is_blank(self):
        for n in (3, 6):
            cells = self.cells(n)
            self.assertTrue(cells)
            for (a, b), cell in cells.items():
                self.assertNotEqual(a, b)
                self.assertEqual(cells[(b, a)]["kind"], cell["kind"], (n, a, b))
                self.assertEqual(cells[(b, a)]["aria-label"], cell["aria-label"], (n, a, b))
            ids = self.view(n)["model"]["ids"]
            drawn = {frozenset(k) for k in cells}
            self.assertEqual(drawn, {frozenset((self.name[c["a"]], self.name[c["b"]])) for c in self.view(n)["model"]["links"]})
            self.assertEqual(len(cells), 2 * len(drawn))
            self.assertTrue(all(self.id[a] in ids and self.id[b] in ids for a, b in cells))

    def test_a_cell_takes_the_colour_of_the_latest_kind_of_tie_by_the_chapter(self):
        self.assertNotIn(("Ash", "Dov"), self.cells(1))
        self.assertEqual([self.cells(n)[("Ash", "Dov")]["kind"] for n in (2, 3, 4, 5, 6)], ["allies", "allies", "allies", "conflict", "conflict"])
        self.assertEqual(self.cells(6)[("Dov", "Eda")]["kind"], "close")
        self.assertEqual(self.cells(6)[("Ash", "Bex")]["kind"], "allies")
        self.assertIn("var(--r-conflict)", self.cells(5)[("Ash", "Dov")]["style"])

    def test_hovering_a_cell_names_both_characters_the_kind_now_and_the_history_up_to_the_chapter(self):
        at4, at5 = self.cells(4)[("Ash", "Dov")]["aria-label"], self.cells(5)[("Ash", "Dov")]["aria-label"]
        self.assertTrue(at4.startswith("Ash and Dov, Allies"), at4)
        self.assertTrue(at5.startswith("Ash and Dov, Conflict"), at5)
        self.assertIn("ch 2 trusts · ch 5 betrays", at5)
        self.assertNotIn("betrays", at4)

    def test_only_ties_first_seen_in_the_chapter_are_marked_new(self):
        at4 = self.cells(4)
        self.assertEqual({frozenset(k) for k, c in at4.items() if c["new"]}, {frozenset(("Ash", "Lux"))})
        self.assertIn("new this chapter", self.view(4)["html"])
        self.assertFalse(any(c["new"] for c in self.cells(5).values()))
        self.assertTrue(self.cells(5)[("Ash", "Dov")]["kind"] == "conflict" and not self.cells(5)[("Ash", "Dov")]["new"])

    def test_a_dead_character_is_marked_with_a_dagger_from_the_chapter_of_their_death(self):
        fen = self.id["Fen"]
        header = lambda n: next(h for h in re.findall(r'<div class="mrow[^"]*"[^>]*>.*?</div>', self.view(n)["html"]) if f'data-go="e:{fen}"' in h)
        self.assertNotIn("†", header(4))
        self.assertIn('<span class="dagger">†</span>', header(5))
        self.assertIn('title="Died ch 5"', header(5))

    def test_cells_open_the_pair_on_connected_and_headers_open_the_character_with_real_links(self):
        links = site_views(self.path, "links:graph:matrix@6")["links:graph:matrix@6"]
        self.assertEqual(links["bare"], [])
        ash, dov = self.id["Ash"], self.id["Dov"]
        routes = {r["p"] for r in links["rows"]}
        self.assertIn(f"graph:path:{ash}~{dov}", routes)
        self.assertIn(f"graph:path:{dov}~{ash}", routes)
        self.assertIn(f"e:{ash}", routes)
        tabs = re.findall(r'data-go="(graph(?::\w+)?)"[^>]*>([^<]+)</a>', self.view(6)["html"].split('class="tabs gtabs"')[1].split("</div>")[0])
        labels = [label for _, label in tabs]
        self.assertEqual(labels.index("Matrix"), labels.index("Storyline") + 1)
        self.assertIn(("graph:matrix", "Matrix"), tabs)


if __name__ == "__main__":
    unittest.main()
