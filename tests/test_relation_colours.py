import json
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_graph import NODE
from tests.test_matrix import matrix_wiki, tags


def colour_wiki():
    wiki = matrix_wiki()
    ids = {e["name"]: e["id"] for e in wiki["entities"]}
    rel = lambda a, t, b, fam: {"chapter": 6, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "quotes": []}
    wiki["relations"] += [rel("Filler 01", "mentor of", "Filler 02", "teaching"),
                          rel("Filler 03", "employs", "Filler 04", "service"),
                          rel("Filler 05", "investigates", "Filler 06", "investigation"),
                          rel("Filler 07", "rival of", "Filler 08", "hostility")]
    return wiki


@unittest.skipIf(NODE is None, "node is not installed")
class RelationColourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        path = Path(cls.dir.name) / "wiki.json"
        wiki = colour_wiki()
        path.write_text(json.dumps(wiki), encoding="utf-8")
        name = {e["id"]: e["name"] for e in wiki["entities"]}
        view = site_views(path, "graph:matrix@6")["graph:matrix@6"]
        cls.html = view["html"]
        cls.cells = {}
        for cell in tags(view["html"], "mcell"):
            a, b = cell["data-go"].removeprefix("graph:path:").split("~")
            cls.cells[(name[a], name[b])] = cell

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def colour(self, a, b):
        return self.cells[(a, b)]["style"].split("var(--r-")[1].split(")")[0]

    def test_teaching_shares_the_work_colour_and_investigation_is_drawn_grey(self):
        self.assertEqual(self.colour("Filler 01", "Filler 02"), self.colour("Filler 03", "Filler 04"))
        self.assertEqual(self.colour("Filler 05", "Filler 06"), "other")
        self.assertEqual(self.colour("Filler 07", "Filler 08"), "hostility")

    def test_the_kinds_are_named_by_their_colour_group(self):
        self.assertTrue(self.cells[("Filler 01", "Filler 02")]["aria-label"].startswith("Filler 01 and Filler 02, Work and hierarchy"))
        self.assertTrue(self.cells[("Filler 07", "Filler 08")]["aria-label"].startswith("Filler 07 and Filler 08, Conflict"))
        self.assertTrue(self.cells[("Ash", "Bex")]["aria-label"].startswith("Ash and Bex, Friends and allies"))


if __name__ == "__main__":
    unittest.main()
