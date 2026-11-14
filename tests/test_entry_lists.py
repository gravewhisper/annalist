import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_asof_leaks import visible_text
from tests.test_build import ROOT, site_views
from tests.test_graph import NODE

HERO = "000000a1"
ALIASES = [f"Alias {n}" for n in range(1, 11)]
HISTORY = ["Lamp Guild", "Harbour Office", "Tide Court", "Mill Crew", "Bell Tower", "Night Watch", "Salt Office", "Ferry Crew"]
GROUPS = {"Lamp Guild": 1, "Night Watch": 1, "Tide Court": 11}


def lists_wiki():
    hero = {"id": HERO, "name": "Hero", "name_chapter": 1, "type": "character", "first": 1, "blurbs": [[1, "Hero is here."]],
            "aliases": [{"name": a, "chapter": 1} for a in ALIASES] + [{"name": "Late Alias", "chapter": 12}],
            "profile": {"fields": {"affiliation": [{"value": v, "chapter": c, "quotes": []} for c, v in enumerate(HISTORY, 1)]},
                        "lists": {}, "spoke": [], "personality": []}}
    groups = [{"id": f"000000b{i}", "name": n, "name_chapter": c, "type": "organization", "first": c, "aliases": [], "blurbs": [[c, f"{n} is here."]]}
              for i, (n, c) in enumerate(GROUPS.items())]
    relations = [{"chapter": g["first"], "source": HERO, "target": g["id"], "type": "member of", "family": "membership", "status": "stated", "quotes": []} for g in groups]
    return {"book": {"title": "Lists", "max": 12, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 13)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": [hero, *groups], "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


def row(page, label):
    return re.search(rf"<tr><th>{label}</th><td>(.*?)</td></tr>", page, re.S).group(1)


def shown_and_folded(cell):
    head, _, folded = cell.partition('<div class="discbody"')
    return visible_text(head), visible_text("<" + folded), bool(re.match(r'[^>]*\bhidden>', folded))


@unittest.skipIf(NODE is None, "node is not installed")
class EntryListsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(lists_wiki()), encoding="utf-8")
        cls.ids = {g["name"]: g["id"] for g in lists_wiki()["entities"]}
        cls.out = site_views(cls.path, f"{HERO}@10", f"{HERO}@12", f"hover:{HERO}@10", f"toggle:e:{HERO}@10?label=7 more", f"toggle:e:{HERO}@10?label=4 more")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_the_other_names_show_the_first_few_and_fold_the_rest(self):
        shown, folded, hidden = shown_and_folded(row(self.out[f"{HERO}@10"], "Also known as"))
        self.assertEqual(shown, "Alias 1 Alias 2 Alias 3 Show Hide 7 more")
        self.assertEqual(folded, " ".join(ALIASES[3:]))
        self.assertTrue(hidden)

    def test_a_name_from_a_later_chapter_stays_out_of_the_folded_names(self):
        self.assertNotIn("Late Alias", self.out[f"{HERO}@10"])

    def test_the_history_shows_the_most_recent_few_and_folds_the_rest(self):
        shown, folded, hidden = shown_and_folded(row(self.out[f"{HERO}@10"], "Affiliation"))
        self.assertEqual(shown, "Ferry Crew (ch 8) previously Salt Office (ch 7), Night Watch (ch 6), Bell Tower (ch 5) Show Hide 4 more")
        self.assertEqual(folded, "Mill Crew (ch 4), Tide Court (ch 3), Harbour Office (ch 2), Lamp Guild (ch 1)")
        self.assertTrue(hidden)

    def test_the_fold_buttons_open_and_close_their_lists(self):
        opened = [{"expanded": "false", "hidden": True}, {"expanded": "true", "hidden": False}, {"expanded": "false", "hidden": True}]
        self.assertEqual(self.out[f"toggle:e:{HERO}@10?label=7 more"], opened)
        self.assertEqual(self.out[f"toggle:e:{HERO}@10?label=4 more"], opened)

    def test_earlier_values_link_to_entries_visible_at_the_chapter(self):
        cell = row(self.out[f"{HERO}@10"], "Affiliation")
        self.assertIn(f'data-ent="{self.ids["Night Watch"]}"', cell)
        self.assertIn(f'data-ent="{self.ids["Lamp Guild"]}"', cell)

    def test_an_earlier_value_never_links_to_an_entry_from_a_later_chapter(self):
        self.assertNotIn(self.ids["Tide Court"], self.out[f"{HERO}@10"])
        self.assertIn(f'data-ent="{self.ids["Tide Court"]}"', row(self.out[f"{HERO}@12"], "Affiliation"))

    def test_the_hover_card_lists_a_few_names_and_counts_the_rest(self):
        card = visible_text(self.out[f"hover:{HERO}@10"])
        self.assertIn("aka Alias 1, Alias 2, Alias 3 and 7 more", card)
        self.assertNotIn("Alias 4", card)


if __name__ == "__main__":
    unittest.main()
