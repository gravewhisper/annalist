import json
import tempfile
import unittest
from pathlib import Path

from annalist.export import build
from annalist.pages import Absorbed

TEXTS = {1: "Edda Moor woke in a strange body by the sea. The grey-eyed harbor inspector watched the docks, "
            "and the grey-eyed harbor inspector said nothing.",
         2: "Lisbet Crane walked to the market. Lisbet Crane bought bread, and Lisbet smiled. The grey-eyed harbor inspector "
            "nodded. Tomas Wexley, the inspector, spoke to her. Then Tomas Wexley left.",
         3: "Lisbet Crane slept and Lisbet Crane dreamed. Tomas Wexley returned. Warden Tomas Wexley bowed, and Tomas waved.",
         4: "Lisbet Crane laughed, Lisbet Crane sang, and Lisbet Crane ran. Tomas Wexley followed. Edda Moor had been her name in her first life."}

STATES = {1: [{"name": "Edda Moor", "type": "character", "aliases": [], "summary": "A woman who woke in a strange body."},
              {"name": "Grey-eyed inspector", "type": "character", "aliases": [{"name": "grey-eyed harbor inspector", "unique": True}]}],
          2: [{"name": "Lisbet Crane", "type": "character", "aliases": [], "summary": "A woman at the market."},
              {"name": "Grey-eyed inspector", "type": "character", "aliases": ["Tomas Wexley", "Tomas"]}],
          3: [{"name": "Lisbet Crane", "type": "character", "aliases": ["Lisbet"]},
              {"name": "Grey-eyed inspector", "type": "character", "aliases": ["Warden Tomas Wexley"]}],
          4: [{"name": "Lisbet Crane", "type": "character", "aliases": []}]}


def seed(root):
    (root / "state").mkdir()
    (root / "chapters").mkdir()
    for n, text in TEXTS.items():
        (root / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
        (root / "state" / f"{n:04d}.json").write_text(json.dumps({"chapter": n, "extraction": {"synopsis": "", "entities": STATES[n]}}),
                                                      encoding="utf-8")
    merge = {"a": "Edda Moor", "b": "Lisbet Crane", "canonical": "Edda Moor", "same": True,
             "revealed": {"basis": "quote", "chapter": 4, "quote": "Edda Moor had been her name in her first life."}}
    (root / "merges.json").write_text(json.dumps({"pairs": [merge]}), encoding="utf-8")
    (root / "chapters.json").write_text(json.dumps([{"index": n, "title": str(n)} for n in TEXTS]), encoding="utf-8")
    (root / "book.json").write_text(json.dumps({"title": "T"}), encoding="utf-8")


class CommonTitles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed(root)
            cls.records = build(root, {})[1]["entities"]
        cls.pages = {r["name"]: r for r in cls.records}

    def test_a_described_page_takes_its_regular_name_over_a_fuller_description(self):
        page = self.pages["Tomas Wexley"]
        self.assertEqual(page["name_chapter"], 2)
        self.assertIn("grey-eyed harbor inspector", [a["name"] for a in page["aliases"]])

    def test_a_merged_page_takes_the_name_the_book_uses_most(self):
        page = next(r for r in self.records if "merged" not in r and "Edda Moor" in [r["name"]] + [a["name"] for a in r["aliases"]])
        self.assertEqual(page["name"], "Lisbet Crane")
        self.assertIn("Edda Moor", [a["name"] for a in page["aliases"]])

    def test_a_merged_part_keeps_its_own_summaries(self):
        part = next(r for r in self.records if r.get("merged") and r["name"] == "Lisbet Crane")
        self.assertEqual([b[1] for b in part["blurbs"]], ["A woman at the market."])


class NestedParts(unittest.TestCase):
    def test_a_name_belongs_to_the_part_it_names_over_a_part_that_took_it_as_an_alias(self):
        page = {"name": "Orrin Vale", "aliases": [], "absorbed": [{"name": "Lisbet Crane", "aliases": [], "chapter": 9},
                                                                  {"name": "Edda Moor", "aliases": ["Lisbet Crane"], "chapter": 9}]}
        self.assertEqual(Absorbed([page]).page_for_name("Orrin Vale", "Lisbet Crane", 3), "Lisbet Crane")


if __name__ == "__main__":
    unittest.main()
