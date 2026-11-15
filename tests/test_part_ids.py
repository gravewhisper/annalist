import json
import tempfile
import unittest
from pathlib import Path

from annalist.export import build
from tests.test_build import site_views

TEXT = "Ivo Marsh rowed the ferry. The Heron watched from the bank. Ivo Marsh was The Heron all along. The Heron is an inn by the ferry. The Heron watched Nell Brook from the bank. Ivo Marsh rowed Nell Brook across. "


def heron_run(root):
    named = {1: [{"name": "Ivo Marsh", "type": "character", "aliases": []}, {"name": "The Heron", "type": "character", "aliases": [], "summary": "A watcher on the bank."},
                 {"name": "Nell Brook", "type": "character", "aliases": []}],
             3: [{"name": "Ivo Marsh", "type": "character", "aliases": ["The Heron"]}],
             4: [{"name": "The Heron", "type": "place", "aliases": [], "summary": "An inn by the ferry."}]}
    ties = {1: [{"source": "The Heron", "target": "Nell Brook", "type": "watches", "quotes": ["The Heron watched Nell Brook from the bank."]}],
            3: [{"source": "Ivo Marsh", "target": "Nell Brook", "type": "rows", "quotes": ["Ivo Marsh rowed Nell Brook across."]}]}
    (root / "state").mkdir()
    (root / "chapters").mkdir()
    for n in range(1, 6):
        (root / "chapters" / f"{n:04d}.txt").write_text(TEXT, encoding="utf-8")
        (root / "state" / f"{n:04d}.json").write_text(json.dumps({"chapter": n, "extraction": {"synopsis": "", "entities": named.get(n, []), "relations": ties.get(n, [])}}),
                                                      encoding="utf-8")
    (root / "chapters.json").write_text(json.dumps([{"index": n, "title": str(n)} for n in range(1, 6)]), encoding="utf-8")
    (root / "book.json").write_text(json.dumps({"title": "T"}), encoding="utf-8")
    profile = {"fields": {}, "extra": {}, "lists": {}}
    (root / "profiles.json").write_text(json.dumps({"characters": {"Ivo Marsh": profile}}), encoding="utf-8")


class PartIds(unittest.TestCase):
    """A page absorbs a part named like a later page of another type: "The Heron" is a name of Ivo Marsh from chapter 3 and an inn from 4."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        heron_run(root)
        cls.data = build(root, {})[1]
        cls.wiki = root / "wiki.json"
        cls.wiki.write_text(json.dumps(cls.data), encoding="utf-8")
        cls.records = {(e["name"], e["type"]): e for e in cls.data["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_part_and_the_page_named_alike_get_their_own_ids_and_records(self):
        ids = [e["id"] for e in self.data["entities"]]
        self.assertEqual(len(ids), len(set(ids)))
        part, inn, ivo = self.records[("The Heron", "character")], self.records[("The Heron", "place")], self.records[("Ivo Marsh", "character")]
        self.assertEqual(part["merged"], {"into": ivo["id"], "chapter": 3})
        self.assertNotIn("merged", inn)
        self.assertNotIn("profile", inn)
        self.assertEqual([b[1] for b in part["blurbs"]], ["A watcher on the bank."])
        self.assertEqual([b[1] for b in inn["blurbs"]], ["An inn by the ferry."])

    def test_the_graph_draws_the_page_that_absorbed_the_part(self):
        ivo = self.records[("Ivo Marsh", "character")]["id"]
        views = site_views(self.wiki, f"graph:characters:{ivo}@3", f"graph:all:{ivo}@5")
        self.assertEqual(views[f"graph:characters:{ivo}@3"]["model"]["focus"], ivo)


if __name__ == "__main__":
    unittest.main()
