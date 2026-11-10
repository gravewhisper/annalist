import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_connect import connect_wiki, plain
from tests.test_factions import factions_wiki

PEOPLE = ["Arno Vale", "Bea Vale", "Cal Vale", "Dora Vale", "Eli Vale", "Finn Rowe", "Gus Rowe", "Hana Pell", "Ivo Marsh", "Jun Marsh",
          "Kip", "Lena Vale"]
DEAD = {"fields": {"status": [{"chapter": 5, "value": "dead", "quotes": []}]}, "lists": {}, "spoke": [], "personality": []}


def family_wiki():
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": "character", "first": 6 if n == "Lena Vale" else 1, "aliases": [],
                 "blurbs": [[1, f"{n} is here."]]} for i, n in enumerate(PEOPLE, 1)]
    entities.append({"id": "000000ff", "name": "Vale House", "name_chapter": 1, "type": "place", "first": 1, "aliases": [], "blurbs": [[1, "A house."]]})
    entities[0]["profile"] = DEAD
    ids = {e["name"]: e["id"] for e in entities}

    def rel(c, a, t, b, fam, status="stated"):
        return {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": status, "by": "narrator", "quotes": []}

    relations = [rel(1, "Bea Vale", "wife of", "Arno Vale", "romance"), rel(1, "Cal Vale", "son of", "Arno Vale", "kin"),
                 rel(2, "Cal Vale", "son of", "Bea Vale", "kin"), rel(2, "Bea Vale", "mother of", "Dora Vale", "kin"),
                 rel(2, "Arno Vale", "father of", "Dora Vale", "kin"), rel(1, "Eli Vale", "elder brother of", "Cal Vale", "kin"),
                 rel(3, "Finn Rowe", "husband of", "Dora Vale", "romance"), rel(4, "Gus Rowe", "son of", "Finn Rowe", "kin"),
                 rel(4, "Dora Vale", "mother of", "Gus Rowe", "kin"), rel(2, "Hana Pell", "cousin of", "Cal Vale", "kin", "implied"),
                 rel(1, "Ivo Marsh", "sister of", "Jun Marsh", "kin"), rel(1, "Kip", "lover of", "Jun Marsh", "romance"),
                 rel(1, "Kip", "friend of", "Arno Vale", "alliance"), rel(6, "Lena Vale", "daughter of", "Arno Vale", "kin"),
                 rel(1, "Arno Vale", "father of", "Vale House", "kin"), rel(3, "Kip", "father figure to", "Jun Marsh", "kin"),
                 rel(3, "Kip", "sold the Vale family ledger to", "Ivo Marsh", "kin"), rel(3, "Kip", "distant relative of", "Lena Vale", "kin")]
    return {"book": {"title": "Family", "max": 6, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


class FamilyTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = family_wiki()
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def views(self, *views, wiki=None):
        path = Path(self.dir.name) / "wiki.json"
        path.write_text(json.dumps(wiki or self.wiki), encoding="utf-8")
        return site_views(path, *views)

    def family(self, n):
        return self.views(f"graph:family@{n}")[f"graph:family@{n}"]

    def rows(self, f):
        return [[self.name[i] for i in row] for row in f["rows"]]

    def test_each_family_is_one_group_of_kin_largest_first_and_no_one_is_in_a_family_of_one(self):
        fams = self.family(4)["model"]["families"]
        self.assertEqual([sorted(self.name[m["id"]] for m in f["members"]) for f in fams],
                         [["Arno Vale", "Bea Vale", "Cal Vale", "Dora Vale", "Eli Vale", "Finn Rowe", "Gus Rowe", "Hana Pell"], ["Ivo Marsh", "Jun Marsh"]])

    def test_parents_sit_a_generation_above_their_children_and_siblings_spouses_and_cousins_share_a_row(self):
        rows = self.rows(self.family(4)["model"]["families"][0])
        self.assertEqual([sorted(r) for r in rows], [["Arno Vale", "Bea Vale"], ["Cal Vale", "Dora Vale", "Eli Vale", "Finn Rowe", "Hana Pell"], ["Gus Rowe"]])

    def test_spouses_sit_side_by_side_and_siblings_sit_together(self):
        rows = self.rows(self.family(4)["model"]["families"][0])
        self.assertEqual(abs(rows[0].index("Arno Vale") - rows[0].index("Bea Vale")), 1)
        self.assertEqual(abs(rows[1].index("Dora Vale") - rows[1].index("Finn Rowe")), 1)
        at = sorted(rows[1].index(n) for n in ("Cal Vale", "Dora Vale", "Eli Vale"))
        self.assertEqual(at, list(range(at[0], at[0] + 3)))

    def test_a_child_sits_under_its_parents(self):
        f = self.family(4)["model"]["families"][0]
        x = {self.name[m["id"]]: m["x"] for m in f["members"]}
        lo, hi = sorted([x["Dora Vale"], x["Finn Rowe"]])
        self.assertTrue(lo <= x["Gus Rowe"] <= hi, x)

    def test_kin_from_a_later_chapter_is_not_shown(self):
        early = self.family(1)
        self.assertEqual(self.rows(early["model"]["families"][0]), [["Arno Vale", "Bea Vale"], ["Cal Vale", "Eli Vale"]])
        self.assertNotIn("Dora", early["html"])
        self.assertNotIn("Gus", self.family(3)["html"])
        self.assertNotIn("Lena", self.family(5)["html"])
        self.assertIn("Lena Vale", plain(self.family(6)["html"]))

    def test_a_dead_relative_is_faded_with_a_dagger_only_from_the_death(self):
        alive, dead = self.family(4)["html"], self.family(5)["html"]
        node = lambda html: re.search(rf'<a class="ent fnode([^"]*)" data-ent="{self.id["Arno Vale"]}".*?</a>', html, re.S)
        self.assertNotIn("dead", node(alive).group(1))
        self.assertNotIn("†", node(alive).group(0))
        self.assertIn("dead", node(dead).group(1).split())
        self.assertIn("†", node(dead).group(0))

    def test_implied_and_unplaced_kin_are_dashed_and_parent_lines_are_not(self):
        html = self.family(4)["html"]
        ties = {html_title: cls for cls, html_title in re.findall(r'<path class="ftie ([^"]*)"[^>]*><title>(.*?)</title>', html)}
        cousin = next(cls for t, cls in ties.items() if "cousin" in t)
        self.assertTrue({"kin", "implied"} <= set(cousin.split()))
        self.assertEqual(set(next(cls for t, cls in ties.items() if "son of Finn" in t).split()) & {"parent", "kin", "implied"}, {"parent"})
        self.assertEqual(set(next(cls for t, cls in ties.items() if "husband of" in t).split()) & {"spouse", "kin", "implied"}, {"spouse"})

    def test_a_romance_that_is_not_a_marriage_a_father_figure_a_wording_that_only_names_a_family_and_kin_to_a_place_make_no_family(self):
        names = {self.name[m["id"]] for f in self.family(5)["model"]["families"] for m in f["members"]}
        self.assertNotIn("Kip", names)
        self.assertNotIn("Vale House", names)

    def test_a_relative_of_unknown_degree_joins_the_family_with_a_dashed_line(self):
        f = self.family(6)["model"]["families"][0]
        self.assertIn("Kip", {self.name[m["id"]] for m in f["members"]})
        self.assertIn("kin", re.search(r'<path class="ftie ([^"]*)"[^>]*><title>Kip is a distant relative of', self.family(6)["html"]).group(1).split())

    def test_every_name_is_a_real_link_to_its_page(self):
        out = self.views("links:graph:family@4")["links:graph:family@4"]
        self.assertEqual(out["bare"], [])
        pages = {r["p"] for r in out["rows"] if r["ent"]}
        self.assertLessEqual({f"e:{self.id[n]}" for n in ("Arno Vale", "Gus Rowe", "Jun Marsh")}, pages)

    def test_the_family_tab_shows_only_when_kin_is_known(self):
        out = self.views("graph:matrix@1")
        self.assertIn('data-go="graph:family"', out["graph:matrix@1"]["html"])
        tabs = lambda wiki: self.views("graph:matrix@6", wiki=wiki)["graph:matrix@6"]["html"]
        self.assertNotIn('data-go="graph:family"', tabs(factions_wiki()))
        self.assertNotIn('data-go="graph:family"', tabs(connect_wiki()))


if __name__ == "__main__":
    unittest.main()
