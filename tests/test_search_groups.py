import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_category_table import table_wiki, text


def groups(markup):
    found = re.findall(r'<div class="rgroup" role="group" aria-label="([^"]*)">(.*?</div>)</div>(?=<div class="rgroup"|$)', markup, re.S)
    return [(label, [text(o) for o in re.findall(r'<div data-res="[^"]*"[^>]*>(.*?)</div>', body, re.S)]) for label, body in found]


class SearchGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wiki, cls.id = table_wiki()
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(cls.wiki), encoding="utf-8")
            cls.out = site_views(path, "search:a@2", "search:Bo@2", "search:Bo@3", "search:Fenwick@2", "search:Stranger@3")

    def test_results_are_grouped_by_type_with_the_best_match_first(self):
        found = groups(self.out["search:a@2"])
        self.assertEqual([label for label, _ in found], ["Characters", "Organizations", "Places", "Paths", "Rungs"])
        self.assertEqual(found[0][1][0], "Ada Marsh ch 1")
        self.assertEqual(found[1][1], ["Lamp Guild ch 1", "Tide Watch ch 2"])
        self.assertRegex(self.out["search:a@2"], rf'^<div class="rgroup"[^>]*>.*?<div data-res="{self.id["Ada Marsh"]}" class="sel"')

    def test_grouped_results_only_name_entries_and_names_known_by_the_chapter(self):
        self.assertNotIn("Fenwick", self.out["search:Bo@2"])
        self.assertEqual(groups(self.out["search:Bo@2"]), [("Places", ["Harbour ch 1"])])
        self.assertEqual(groups(self.out["search:Bo@3"])[0], ("Characters", ["Bo Fenwick ch 1"]))
        self.assertEqual(groups(self.out["search:Fenwick@2"]), [])
        self.assertEqual(groups(self.out["search:Stranger@3"]), [("Characters", ["Bo Fenwick (The Stranger) ch 1"])])


if __name__ == "__main__":
    unittest.main()
