import json
import tempfile
import unittest
from pathlib import Path

from annalist.book import load_book
from annalist.read import EXTRACT_PROMPT
from annalist.survey import stable_fields
from annalist.template import base_field, ENTITY_TYPES, RELATION_TYPES


def book_in(tmp, book):
    Path(tmp, "book.json").write_text(json.dumps(book), encoding="utf-8")
    return load_book(tmp)


class TemplateTest(unittest.TestCase):
    def test_book_adds_but_cannot_redefine_base_types_or_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = book_in(tmp, {
                "power_types": {"character": "a hero", "place": "x", "elixir": "a serum that grants powers"},
                "extra_fields": {"gender": "male or female", "Status": "alive or not", "nicknames": "other names",
                                 "power_class": {"description": "class, e.g. 'Psycho (cryokinesis)'", "values": ["Genome", "Psycho"]},
                                 "elixir_color": "the colors"}})
        self.assertEqual(book["power_types"], {"elixir": {"parent": "concept", "description": "a serum that grants powers"}})
        self.assertEqual(book["extra_fields"], {"power_class": "class, e.g. 'Psycho (cryokinesis)'", "elixir_color": "the colors"})
        self.assertEqual(book["field_values"], {"power_class": ["Genome", "Psycho"], "elixir_color": []})

    def test_defaults_without_a_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = load_book(tmp)
        self.assertEqual(book["power_types"], {"ability": {"parent": "concept", "description": "a specific power or technique"}})
        self.assertIs(book["complete"], False)

    def test_base_field_matches_names_labels_and_aliases(self):
        self.assertEqual(base_field("Gender").key, "sex")
        self.assertEqual(base_field("Marital status").key, "marital_status")
        self.assertEqual(base_field("alive-or-dead").key, "status")
        self.assertEqual(base_field("personality").key, "personality_evidence")
        self.assertIsNone(base_field("power_class"))
        self.assertIsNone(base_field("pathway_sequence"))
        self.assertEqual(base_field("Profession").key, "occupation")
        self.assertEqual(base_field("title of office").key, "occupation")
        self.assertEqual(base_field("Lives in").key, "residence")
        self.assertEqual(base_field("abode").key, "residence")
        self.assertIsNone(base_field("title"))

    def test_a_book_field_for_occupation_or_residence_folds_into_the_general_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = book_in(tmp, {"extra_fields": {"occupation": "their job", "home": "where they live", "title": "their sequence title"}})
        self.assertEqual(book["extra_fields"], {"title": "their sequence title"})
        self.assertEqual(stable_fields({"job": "their job", "power_class": "class"}, {}), {"power_class": "class"})

    def test_extract_prompt_lists_the_registry(self):
        prompt = EXTRACT_PROMPT.format(knowledge="", n=1, title="", text="", power_names="", power_types="",
                                       power_relation="advances to", base_types=", ".join(ENTITY_TYPES),
                                       relation_types=", ".join(f'"{r}"' for r in RELATION_TYPES))
        self.assertIn("Use these exact types where they fit: character, place, organization, artifact, event, deity, concept.", prompt)
        self.assertIn('("sister of", "member of", "mentor of", "enemy of", "located in", "advances to")', prompt)


if __name__ == "__main__":
    unittest.main()
