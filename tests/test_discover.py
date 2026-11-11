import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from annalist.discover import candidates, judge
from annalist.state import load_states
from tests.test_build import MiniBuild, build_script


def discover_script(kind="concept"):
    script = build_script()
    script["replies"].insert(0, {"purpose": "discover", "contains": "\"Frostmonth\"", "reply": {"entries": [
        {"id": "C1", "type": kind, "summary": "The month of the Gannet wreck."},
        {"id": "C9", "type": "place", "summary": "Not a candidate."}]}})
    return script


class DiscoverMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(discover_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_a_recurring_name_the_read_never_listed_gets_a_page_from_its_first_chapter(self):
        page = next(e for e in self.wiki["entities"] if e["name"] == "Frostmonth")
        self.assertEqual((page["type"], page["first"]), ("concept", 1))
        self.assertEqual(page["blurbs"], [[1, "The month of the Gannet wreck."]])

    def test_words_that_only_open_sentences_and_names_with_entries_are_not_candidates(self):
        found = {c["name"] for c in candidates(self.book.workdir, load_states(self.book.workdir, discovered=False))}
        self.assertIn("Frostmonth", found)
        self.assertFalse(found & {"They", "She", "Tomas", "Ines Varro", "Corvel Quay"})

    def test_a_reply_naming_an_unknown_candidate_adds_nothing(self):
        self.assertEqual([e["name"] for e in self.book.json("discover.json")["entities"]], ["Frostmonth"])


class DiscoverBookTypeTest(unittest.TestCase):
    def test_a_recurring_name_can_be_filed_under_one_of_the_books_own_power_types(self):
        book = MiniBuild(discover_script("ward"))
        self.addCleanup(book.close)
        book.build()
        page = next(e for e in book.json("site/data/wiki.json")["entities"] if e["name"] == "Frostmonth")
        self.assertEqual((page["type"], page["first"]), ("ward", 1))

    def test_the_judge_is_offered_the_books_power_types_by_name_and_never_the_books_description_of_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "book.json").write_text(json.dumps({"power_types": {"elixir": "a drink brewed from moonpetal"}}), encoding="utf-8")
            prompts = []

            def reply(workdir, purpose, prompt, check=None):
                prompts.append(prompt)
                return {"entries": [{"id": "C1", "type": "elixir", "summary": "An older name for the elixir."}]}

            with patch("annalist.discover.cached_llm", side_effect=reply):
                kept = judge(tmp, [{"name": "Tideglass", "chapters": [2, 3], "passage": "The elixir was once called Tideglass."}])
        self.assertEqual([(e["name"], e["type"]) for e in kept], [("Tideglass", "elixir")])
        self.assertIn("- elixir:", prompts[0])
        self.assertNotIn("moonpetal", prompts[0])


class DiscoverGodsTest(unittest.TestCase):
    def test_a_recurring_name_for_a_class_of_gods_is_filed_as_a_concept_not_a_creature(self):
        replies = [{"purpose": "discover", "contains": "one god is a deity, and a kind or class of gods is a concept",
                    "reply": {"entries": [{"id": "C1", "type": "concept", "summary": "A class of malevolent gods."}]}},
                   {"purpose": "discover", "reply": {"entries": [{"id": "C1", "type": "creature", "summary": "Beings under the shoals."}]}}]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                                                           if not k.startswith("ANNALIST_")}, clear=True):
            (Path(tmp) / "book.json").write_text(json.dumps({"title": "Reef", "backend": {"name": "fake", "script": "script.json"}}),
                                                 encoding="utf-8")
            (Path(tmp) / "script.json").write_text(json.dumps({"replies": replies}), encoding="utf-8")
            kept = judge(tmp, [{"name": "Hollow Gods", "chapters": [1, 2], "passage": "the Hollow Gods hunger beneath the shoals"}])
        self.assertEqual([(e["name"], e["type"]) for e in kept], [("Hollow Gods", "concept")])


if __name__ == "__main__":
    unittest.main()
