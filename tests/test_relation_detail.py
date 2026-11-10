import html as html_lib
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_connect import plain

NAMES = [("Ada", "character"), ("Bram", "character"), ("Cora", "character"), ("Dax", "character"), ("Baron Gramir", "character"),
         ("Night Watch", "organization"), ("Grey Guild", "organization")]


def detail_wiki():
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, (n, t) in enumerate(NAMES, 1)]
    for e in entities:
        if e["type"] == "character":
            e["present"] = list(range(1, 7))
    ids = {e["name"]: e["id"] for e in entities}

    def rel(c, a, t, b, fam, detail=""):
        row = {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "by": "narrator",
               "quotes": [f"{a} and {b} in chapter {c}."]}
        return {**row, "detail": detail} if detail else row

    relations = [rel(2, "Ada", "suspects", "Bram", "investigation", "of impersonating Baron Gramir"),
                 rel(3, "Ada", "Suspects", "Bram", "investigation", "Of impersonating Baron Gramir."),
                 rel(4, "Ada", "suspects", "Bram", "investigation", "of hiding the ledger"),
                 rel(1, "Ada", "friend of", "Cora", "alliance"), rel(1, "Cora", "friend of", "Bram", "alliance"),
                 rel(1, "Ada", "friend of", "Dax", "alliance"), rel(1, "Ada", "friend of", "Baron Gramir", "alliance"),
                 rel(2, "Night Watch", "allied with", "Grey Guild", "alliance", "against the harbour gangs"),
                 rel(1, "Ada", "member of", "Night Watch", "membership"), rel(1, "Bram", "member of", "Grey Guild", "membership"),
                 rel(6, "Cora", "warns", "Bram", "alliance", "about the flooded vault")]
    return {"book": {"title": "Details", "max": 6, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


class RelationDetailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = detail_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def view(self, view):
        return site_views(self.path, view)[view]

    def page(self, name, n, tab=""):
        return self.view(f"{self.id[name]}@{n}" + (f"?tab={tab}" if tab else ""))

    def test_the_relations_tab_reads_the_detail_after_the_target_and_groups_by_wording_and_detail_whatever_the_case(self):
        rows = re.findall(r'<div class="fact">(.*?)<button', self.page("Ada", 5, "relations"), re.S)
        said = [plain(r) for r in rows if "suspects" in plain(r).lower()]
        self.assertEqual(said, ["Ada suspects Bram of hiding the ledger Ch 4", "Ada suspects Bram of impersonating Baron Gramir Ch 2 Ch 3"])

    def test_a_detail_names_a_known_entry_with_a_link(self):
        page = self.page("Ada", 2, "relations")
        detail = re.search(r'<span class="rdetail">(.*?)</span>', page).group(1)
        self.assertIn(f'data-ent="{self.id["Baron Gramir"]}"', detail)

    def test_the_connections_list_shows_the_latest_tie_with_its_detail_and_counts_each_detail_as_its_own_kind(self):
        page = self.page("Ada", 5)
        row = next(r for r in re.findall(r"<li><span class=\"cwho\".*?</li>", page, re.S) if "suspects" in r)
        self.assertIn("Ada suspects Bram of hiding the ledger +1", plain(row))
        titles = html_lib.unescape(re.search(r'title="([^"]*)"', row).group(1)).split("\n")
        self.assertEqual(titles, ["Ada suspects Bram of impersonating Baron Gramir, ch 2, 3", "Ada suspects Bram of hiding the ledger, ch 4"])

    def test_the_connected_path_hops_read_the_detail(self):
        out = self.view(f"graph:path:{self.id['Ada']}~{self.id['Bram']}@3")
        self.assertIn("Ada suspects Bram of impersonating Baron Gramir", plain(out["html"]))

    def test_the_graph_line_and_its_history_carry_the_detail(self):
        out = self.view(f"graph:{self.id['Ada']}@4")
        titles = [html_lib.unescape(t) for t in re.findall(r'<path class="edge[^"]*"[^>]*><title>(.*?)</title>', out["html"], re.S)]
        line = next(t for t in titles if "suspects" in t)
        self.assertIn("Ada suspects Bram of impersonating Baron Gramir, ch 2, 3; Ada suspects Bram of hiding the ledger, ch 4", line)
        self.assertIn("ch 2 suspects of impersonating Baron Gramir · ch 4 suspects of hiding the ledger", line)

    def test_the_matrix_tooltip_reads_the_detail(self):
        labels = html_lib.unescape(" ".join(re.findall(r'aria-label="([^"]*)"', self.view("graph:matrix@6")["html"])))
        self.assertIn("Cora warns Bram about the flooded vault, ch 6", labels)

    def test_a_tie_between_groups_reads_its_detail(self):
        self.assertIn("Night Watch is allied with Grey Guild against the harbour gangs", plain(self.view("graph:factions@2")["html"]))

    def test_no_detail_shows_before_its_chapter(self):
        self.assertNotIn("flooded vault", self.page("Bram", 5))
        self.assertNotIn("ledger", self.page("Ada", 3))
        self.assertNotIn("ledger", self.view(f"graph:{self.id['Ada']}@3")["html"])


if __name__ == "__main__":
    unittest.main()
