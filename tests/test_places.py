import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_connect import connect_wiki, plain
from tests.test_factions import factions_wiki

NAMES = [("Loen", "place", 1), ("Backlund", "place", 1), ("Cherwood", "place", 2), ("Minsk Street", "place", 1), ("Tingen", "place", 1),
         ("Daffodil Street", "place", 1), ("Khoy University", "place", 1), ("Harbour", "place", 1), ("Klein", "character", 1),
         ("Benson", "character", 1), ("Melissa", "character", 1), ("Audrey", "character", 5), ("Leonard", "character", 1),
         ("Old Neil", "character", 1), ("Night Watch", "organization", 1), ("Sonia Sea", "place", 1), ("Rorsted Isles", "place", 1)]


def places_wiki():
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": t, "first": c, "aliases": [], "blurbs": [[c, f"{n} is here."]]}
                for i, (n, t, c) in enumerate(NAMES, 1)]
    ids = {e["name"]: e["id"] for e in entities}

    def rel(c, a, t, b, fam="place", detail="", status="stated"):
        row = {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": status, "by": "narrator", "quotes": []}
        return {**row, "detail": detail} if detail else row

    relations = [rel(1, "Backlund", "located in", "Loen"), rel(1, "Tingen", "located in", "Loen"), rel(2, "Cherwood", "a district of", "Backlund"),
                 rel(1, "Minsk Street", "located in", "Backlund"), rel(3, "Minsk Street", "Located in", "Cherwood"),
                 rel(1, "Daffodil Street", "located in", "Tingen"), rel(1, "Khoy University", "located in", "Tingen"),
                 rel(1, "Harbour", "located near", "Tingen"), rel(1, "Klein", "lives at", "Daffodil Street"), rel(1, "Klein", "lives in", "Tingen"),
                 rel(4, "Klein", "lives on", "Minsk Street"), rel(2, "Benson", "works in", "Backlund", "service", "as a clerk"),
                 rel(1, "Melissa", "studies at", "Khoy University", "teaching"), rel(5, "Audrey", "lives in", "Cherwood"),
                 rel(1, "Leonard", "visited", "Tingen"), rel(1, "Old Neil", "lives at", "Harbour"),
                 rel(1, "Leonard", "lives in", "Backlund", status="belief"), rel(1, "Night Watch", "based in", "Tingen", "membership"),
                 rel(1, "Rorsted Isles", "located in", "Sonia Sea"), rel(1, "Benson", "worked in", "Backlund", "service")]
    return {"book": {"title": "Places", "max": 6, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


class PlacesTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = places_wiki()
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def views(self, *views, wiki=None):
        path = Path(self.dir.name) / "wiki.json"
        path.write_text(json.dumps(wiki or self.wiki), encoding="utf-8")
        return site_views(path, *views)

    def places(self, n):
        return self.views(f"graph:places@{n}")[f"graph:places@{n}"]

    def tree(self, nodes):
        return {self.name[p["id"]]: self.tree(p["children"]) for p in nodes}

    def find(self, nodes, name):
        for p in nodes:
            if self.name[p["id"]] == name:
                return p
            found = self.find(p["children"], name)
            if found:
                return found
        return None

    def test_places_nest_under_the_most_specific_place_they_are_said_to_lie_in(self):
        self.assertEqual(self.tree(self.places(3)["model"]["roots"]),
                         {"Loen": {"Tingen": {"Daffodil Street": {}, "Khoy University": {}}, "Backlund": {"Cherwood": {"Minsk Street": {}}}}, "Harbour": {},
                          "Sonia Sea": {"Rorsted Isles": {}}})

    def test_a_place_moves_under_a_narrower_place_only_once_the_book_says_so(self):
        self.assertEqual(self.tree(self.places(2)["model"]["roots"])["Loen"]["Backlund"], {"Minsk Street": {}, "Cherwood": {}})

    def test_a_person_is_listed_only_under_the_most_specific_place_and_counted_in_every_place_around_it(self):
        roots = self.places(3)["model"]["roots"]
        residents = lambda name: [self.name[x["id"]] for x in self.find(roots, name)["residents"]]
        counts = lambda name: sorted(self.name[i] for i in self.find(roots, name)["people"])
        self.assertEqual(residents("Daffodil Street"), ["Klein"])
        self.assertEqual(residents("Tingen"), [])
        self.assertEqual(counts("Tingen"), ["Klein", "Melissa"])
        self.assertEqual(counts("Loen"), ["Benson", "Klein", "Melissa"])
        self.assertEqual(residents("Backlund"), ["Benson"])
        self.assertIn("Loen 3 people", plain(self.places(3)["html"]))

    def test_a_resident_reads_the_book_s_words_for_the_tie(self):
        html = self.places(3)["html"]
        self.assertIn("Benson works in Backlund as a clerk", plain(html))
        self.assertIn("Melissa studies at Khoy University", plain(html))
        self.assertIn('title="worked in Backlund\nworks in Backlund as a clerk"', html)

    def test_places_where_no_one_is_known_to_be_fold_after_the_rest(self):
        html = self.places(3)["html"]
        hidden = re.findall(r'<div class="discbody" id="[^"]+" hidden>(.*?)</div>', html, re.S)
        self.assertIn("Sonia Sea", plain(hidden[-1]))
        self.assertIn("Show the place where no one is known to be", plain(html))

    def test_no_resident_or_place_from_a_later_chapter_is_shown(self):
        early, later = self.places(4), self.places(5)
        self.assertNotIn("Audrey", early["html"])
        self.assertEqual([self.name[x["id"]] for x in self.find(later["model"]["roots"], "Cherwood")["residents"]], ["Audrey"])
        self.assertNotIn("Cherwood", self.places(1)["html"])
        self.assertEqual([self.name[x["id"]] for x in self.find(early["model"]["roots"], "Minsk Street")["residents"]], ["Klein"])

    def test_near_a_visit_a_suspicion_and_a_group_s_base_place_nobody(self):
        html = plain(self.places(6)["html"])
        self.assertNotIn("Leonard", html)
        self.assertNotIn("Night Watch", html)
        self.assertNotIn("Harbour", str(self.tree([self.find(self.places(6)["model"]["roots"], "Tingen")])))

    def test_a_deep_branch_folds_behind_a_show_all_button(self):
        html = self.places(3)["html"]
        hidden = re.search(r'<div class="discbody" id="[^"]+" hidden><ul class="ptree">(.*?)</ul></div>', html, re.S)
        self.assertIn("Minsk Street", plain(hidden.group(1)))
        self.assertIn("Show the place inside", plain(html))

    def test_every_place_and_person_is_a_real_link(self):
        out = self.views("links:graph:places@3")["links:graph:places@3"]
        self.assertEqual(out["bare"], [])
        pages = {r["p"] for r in out["rows"] if r["ent"]}
        self.assertLessEqual({f"e:{self.id[n]}" for n in ("Loen", "Minsk Street", "Klein", "Melissa")}, pages)

    def test_the_places_tab_shows_only_when_a_place_holds_someone_or_another_place(self):
        tabs = lambda wiki: self.views("graph:matrix@6", wiki=wiki)["graph:matrix@6"]["html"]
        self.assertIn('data-go="graph:places"', tabs(self.wiki))
        self.assertIn('data-go="graph:places"', tabs(connect_wiki()))
        self.assertNotIn('data-go="graph:places"', tabs(factions_wiki()))


if __name__ == "__main__":
    unittest.main()
