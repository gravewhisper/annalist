import json
import tempfile
import unittest
from pathlib import Path

from annalist.export import category_labels
from annalist.state import Knowledge
from annalist.book import load_book
from annalist.survey import book_problems, generate_book
from annalist.template import category_problems
import tests.test_book as book_tests
from tests.test_book import GOOD, harbour_kb
from tests.test_book_types import category_wiki, plain
from tests.test_build import ROOT, site_views

HIDDEN = {"parent": "organization", "description": "a hidden society that meets at night, such as a cellar club"}
CHAPEL = {"parent": "organization", "description": "a sworn order of the harbour chapel"}


class CategoryCheckTest(unittest.TestCase):
    def test_subcategories_of_one_parent_overlap_when_one_name_holds_the_other_or_one_is_described_as_a_kind_of_the_other(self):
        named = category_problems({"order": HIDDEN, "silent order": CHAPEL}, {})
        described = category_problems({"secret order": HIDDEN, "chapel": CHAPEL}, {})
        self.assertIn('the organization subcategories "order" and "silent order" overlap', " ".join(named))
        self.assertIn('"chapel" is described as a kind of order', " ".join(described))

    def test_subcategories_of_different_parents_or_of_one_head_word_do_not_overlap(self):
        self.assertEqual(category_problems({"secret order": HIDDEN, "chapel": {**CHAPEL, "parent": "place"}}, {}), [])
        spells = {"fire spell": {"parent": "concept", "description": "a spell of flame"},
                  "tide spell": {"parent": "concept", "description": "a spell of the sea"}}
        self.assertEqual(category_problems(spells, {}), [])

    def test_a_subcategory_named_like_one_entry_of_another_type_is_rejected(self):
        names = {"The Secret Order": "organization", "Secret Orders": "concept", "Ines": "character"}
        found = category_problems({"cellar club": {**HIDDEN, "label": "Secret Orders"}}, names)
        self.assertEqual(len(found), 1)
        self.assertIn('the subcategory "Secret Orders" is named like the organization "The Secret Order"', found[0])

    def test_a_concept_or_an_entry_of_the_category_itself_may_share_its_name(self):
        names = {"Secret Orders": "concept", "Secret Order": "secret order"}
        self.assertEqual(category_problems({"secret order": HIDDEN}, names), [])


MATERIAL = "The Lamplighters' Guild names an Apprentice, a Keeper and a Master. The harbour relics burn."


class SurveyCategoryTest(unittest.TestCase):
    def reply(self, *types):
        return {**GOOD, "power_types": list(types)}

    def test_a_label_in_the_books_words_passes_and_one_the_material_never_writes_is_rejected(self):
        relic = {"type": "relic", "parent": "artifact", "description": "an object holding old harbour magic"}
        self.assertIsNone(book_problems(self.reply({**relic, "label": "Harbour Relics"}), Knowledge(), MATERIAL, MATERIAL))
        found = book_problems(self.reply({**relic, "label": "Sea Treasures"}), Knowledge(), MATERIAL, MATERIAL)
        self.assertIn('power type "relic" has the label "Sea Treasures", which the material never writes', found)

    def test_overlapping_power_types_and_one_named_like_an_entry_are_rejected(self):
        kb = Knowledge()
        kb.upsert_entity({"name": "Secret Order", "type": "organization", "summary": "a society of the quay"}, 1)
        found = book_problems(self.reply({"type": "secret order", **HIDDEN}, {"type": "chapel", **CHAPEL}), kb)
        self.assertIn('"chapel" is described as a kind of order', found)
        self.assertIn('the subcategory "secret order" is named like the organization "Secret Order"', found)


class SurveyLabelStoredTest(unittest.TestCase):
    setUp = book_tests.BookGenerationTest.setUp
    script = book_tests.BookGenerationTest.script

    def test_the_survey_keeps_the_label_in_the_books_words_with_its_type(self):
        relic = {"type": "relic", "parent": "artifact", "label": "harbour lamps", "description": "an object holding old harbour magic"}
        self.script({**GOOD, "power_types": [relic]})
        kb = harbour_kb()
        generate_book(self.workdir, kb, kb)
        self.assertEqual(load_book(self.workdir)["power_types"], {"relic": {"parent": "artifact", "description": "an object holding old harbour magic",
                                                                            "label": "harbour lamps"}})


class CategoryLabelTest(unittest.TestCase):
    def test_a_label_shows_from_the_first_chapter_that_writes_it_and_not_before_its_type_exists(self):
        texts = {1: "A ward hung on the door.", 2: "Two bound relics.", 3: "Ships came in."}
        categories = {"warding item": {"parent": "artifact", "description": "", "label": "Wards"},
                      "relic": {"parent": "artifact", "description": "", "label": "Bound Relics"},
                      "ship": {"parent": "artifact", "description": "", "label": "Ships", "chapter": 2},
                      "boat": {"parent": "artifact", "description": "", "label": "Skiffs"},
                      "oar": {"parent": "artifact", "description": ""}}
        self.assertEqual(category_labels(categories, texts), {"warding item": {"text": "Wards", "chapter": 1},
                                                              "relic": {"text": "Bound Relics", "chapter": 2},
                                                              "ship": {"text": "Ships", "chapter": 3}})

    def test_the_site_names_a_category_by_its_label_from_its_chapter_and_by_its_type_before(self):
        wiki, ids = category_wiki()
        wiki["book"]["labels"] = {"warding item": {"text": "Salt Wards", "chapter": 3}}
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
            views = site_views(path, "route:cat:artifact@1", "route:cat:artifact@3", f"{ids['Salt Ward']}@3")
        self.assertIn("Subcategories Warding items 1", plain(views["route:cat:artifact@1"]["html"]))
        self.assertIn("Subcategories Salt Wards 2", plain(views["route:cat:artifact@3"]["html"]))
        self.assertIn("Home › Artifacts › Salt Wards Salt Ward", plain(views[f"{ids['Salt Ward']}@3"]))


if __name__ == "__main__":
    unittest.main()
