import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views
from tests.test_category_table import person, table_wiki, text


def groups(markup):
    found = re.findall(r'<div class="rgroup" role="group" aria-label="([^"]*)">(.*?</div>)</div>(?=<div class="rgroup"|$)', markup, re.S)
    return [(label, [text(o) for o in re.findall(r'<div data-res="[^"]*"[^>]*>(.*?)</div>', body, re.S)]) for label, body in found]


def characters(markup):
    return dict(groups(markup)).get("Characters", [])


def options(markup):
    return [text(o) for o in re.findall(r'<div data-(?:go|sadd)="[^"]*"[^>]*>(.*?)</div>', markup, re.S)]


def fuzzy_wiki():
    wiki, ids = table_wiki()
    extra = {"Mira": 0, "Miran Toll": 1, "Old Mirabel": 2, "Milo Reyna": 3, "Mora": 4}
    people = [person(20 + i, name, 4, present=(4,)) for i, name in enumerate(extra)]
    people += [person(30, "Édouard Dantès", 4), person(33, "Kasim Rhee", 4), person(31, "Tam O'Neil", 4), person(32, "Nell Ashby", 3, aliases=[("The Gull Queen", 4)])]
    wiki["entities"] += people
    for e in people:
        for k in range(1 + extra.get(e["name"], 0)):
            wiki["facts"].append({"id": f"F{e['id']}-{k}", "chapter": e["first"], "entity": e["id"], "claim": f"{e['name']} waits on the quay.",
                                  "status": "stated", "by": "narrator", "quotes": []})
    return wiki, {**ids, **{e["name"]: e["id"] for e in people}}


class SearchGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wiki, cls.id = fuzzy_wiki()
        queries = ["mira@4", "ira@4", "toll miran@4", "ksm rh@4", "dantes@4", "DANTÈS@4", "edouard@4", "oneil@4", "dantas@4", "dentas@4",
                   "edward dantes@4", "mxra@4", "mxr@4", "gull queen@3", "gull queen@4", "queen gull@3", "queen gull@4", "gul queen@3", "gul queen@4"]
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(cls.wiki), encoding="utf-8")
            cls.out = site_views(path, "search:a@2", "search:Bo@2", "search:Bo@3", "search:Fenwick@2", "search:Stranger@3",
                                 *(f"search:{q}" for q in queries), "gsearch:ada marhs@3", "gsearch:lamp gild@3", "gsearch:marsh ada@3",
                                 f"ssearch:mxra@4?drop={cls.id['Mira']}&drop={cls.id['Mora']}")

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

    def test_matches_rank_exact_then_prefix_then_word_start_then_letters_in_order_then_typos(self):
        self.assertEqual(characters(self.out["search:mira@4"]),
                         ["Mira ch 4", "Miran Toll ch 4", "Old Mirabel ch 4", "Milo Reyna ch 4", "Mora ch 4"])
        self.assertRegex(self.out["search:mira@4"], rf'^<div class="rgroup"[^>]*>.*?<div data-res="{self.id["Mira"]}" class="sel"')

    def test_query_words_match_word_starts_in_any_order(self):
        self.assertEqual(groups(self.out["search:toll miran@4"]), [("Characters", ["Miran Toll ch 4"])])
        self.assertEqual(options(self.out["gsearch:marsh ada@3"])[0], "Ada Marsh character")

    def test_letters_in_order_match_with_gaps_after_unbroken_runs(self):
        self.assertEqual(groups(self.out["search:ksm rh@4"]), [("Characters", ["Kasim Rhee ch 4"])])
        self.assertEqual(characters(self.out["search:ira@4"]), ["Old Mirabel ch 4", "Miran Toll ch 4", "Mira ch 4", "Milo Reyna ch 4"])

    def test_case_accents_and_punctuation_are_ignored(self):
        for query in ("dantes", "DANTÈS", "edouard"):
            self.assertEqual(characters(self.out[f"search:{query}@4"])[0], "Édouard Dantès ch 4", query)
        self.assertEqual(characters(self.out["search:oneil@4"]), ["Tam O'Neil ch 4"])

    def test_small_typos_match_by_query_length(self):
        self.assertEqual(characters(self.out["search:dantas@4"]), ["Édouard Dantès ch 4"])
        self.assertNotIn("Dantès", self.out["search:dentas@4"])
        self.assertEqual(characters(self.out["search:edward dantes@4"]), ["Édouard Dantès ch 4"])
        self.assertEqual(sorted(characters(self.out["search:mxra@4"])), ["Mira ch 4", "Miran Toll ch 4", "Mora ch 4", "Old Mirabel ch 4"])
        self.assertEqual(groups(self.out["search:mxr@4"]), [])

    def test_a_later_alias_never_matches_before_its_chapter(self):
        for query in ("gull queen", "queen gull", "gul queen"):
            self.assertEqual(groups(self.out[f"search:{query}@3"]), [], query)
            self.assertEqual(characters(self.out[f"search:{query}@4"]), ["Nell Ashby (The Gull Queen) ch 3"], query)

    def test_graph_and_storyline_boxes_use_the_same_matcher(self):
        self.assertEqual(options(self.out["gsearch:ada marhs@3"]), ["Ada Marsh character"])
        self.assertEqual(options(self.out["gsearch:lamp gild@3"]), ["Lamp Guild organization"])
        self.assertEqual(sorted(options(self.out[f"ssearch:mxra@4?drop={self.id['Mira']}&drop={self.id['Mora']}"])), ["Mira", "Mora"])


if __name__ == "__main__":
    unittest.main()
