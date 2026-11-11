import json
import tempfile
import unittest
from pathlib import Path

from annalist.book import load_book
from annalist.ladders import ladder_needed
from annalist.state import Knowledge

LADDER = {"group_type": "school", "step_type": "rank", "rank": "number", "direction": "ascending", "note": ""}


def loaded(book):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "book.json").write_text(json.dumps(book), encoding="utf-8")
        return load_book(tmp)


def entities(power_types, *rows):
    kb = Knowledge(power_types=power_types)
    for n, (name, etype) in enumerate(rows, 1):
        kb.upsert_entity({"name": name, "type": etype, "summary": f"{name} as of chapter {n}"}, n)
    return {k: e["type"] for k, e in kb.entities.items()}


class BookTypeShapeTest(unittest.TestCase):
    def test_a_book_type_without_a_parent_takes_the_general_type_its_last_word_names_or_else_concept(self):
        book = loaded({"power_types": {"warding item": "an object that keeps spirits off", "elixir": "a serum that grants powers",
                                       "harbour place": "a quay the lamps watch over"}})
        self.assertEqual(book["power_types"], {
            "warding item": {"parent": "artifact", "description": "an object that keeps spirits off"},
            "elixir": {"parent": "concept", "description": "a serum that grants powers"},
            "harbour place": {"parent": "place", "description": "a quay the lamps watch over"}})

    def test_a_book_type_keeps_the_parent_it_names_and_never_takes_an_individual_as_parent(self):
        book = loaded({"power_types": {"elixir": {"parent": "artifact", "description": "a serum"},
                                       "lamplighter": {"parent": "character", "description": "a keeper of lamps"},
                                       "saint": {"parent": "deity", "description": "a holy one"},
                                       "ward": {"parent": "spell", "description": "a charm"}}})
        self.assertEqual({t: spec["parent"] for t, spec in book["power_types"].items()},
                         {"elixir": "artifact", "lamplighter": "concept", "saint": "concept", "ward": "concept"})

    def test_an_old_book_with_a_ladder_still_loads_its_types_and_ladder(self):
        book = loaded({"power_system": "Schools of fire ranked by draughts.", "timeline_kind": "linear",
                       "power_types": {"school": "A school of fire.", "rank": "A rank within a school.", "draught": "A draught."},
                       "ladder": LADDER})
        self.assertEqual(list(book["power_types"]), ["school", "rank", "draught"])
        self.assertEqual(book["ladder"], LADDER)
        self.assertFalse(ladder_needed(book))


class BookTypeMatchTest(unittest.TestCase):
    TYPES = {"warding item": {"parent": "artifact", "description": "a charm"}, "relic": {"parent": "artifact", "description": "an old thing"}}

    def test_an_entry_of_a_book_type_and_one_of_its_parent_are_one_entry_under_the_book_type(self):
        self.assertEqual(entities(self.TYPES, ("Salt Ward", "artifact"), ("Salt Ward", "warding item")), {"Salt Ward": "warding item"})
        self.assertEqual(entities(self.TYPES, ("Salt Ward", "warding item"), ("Salt Ward", "artifact")), {"Salt Ward": "warding item"})

    def test_an_alias_joins_entries_of_a_book_type_and_its_parent(self):
        kb = Knowledge(power_types=self.TYPES)
        kb.upsert_entity({"name": "Salt Ward", "type": "artifact", "summary": "a charm of salt"}, 1)
        kb.upsert_entity({"name": "Grey Charm", "type": "warding item", "aliases": ["Salt Ward"], "summary": "the charm"}, 2)
        self.assertEqual({k: (e["type"], e["aliases"]) for k, e in kb.entities.items()},
                         {"Salt Ward": ("warding item", ["Grey Charm"])})

    def test_an_alias_never_joins_two_book_types_of_one_parent_or_unrelated_types(self):
        for other in ("relic", "place"):
            kb = Knowledge(power_types=self.TYPES)
            kb.upsert_entity({"name": "Salt Ward", "type": "warding item", "summary": "a charm of salt"}, 1)
            kb.upsert_entity({"name": "Grey Relic", "type": other, "aliases": ["Salt Ward"], "summary": "an old thing"}, 2)
            self.assertEqual({k: e["type"] for k, e in kb.entities.items()}, {"Salt Ward": "warding item", "Grey Relic": other})

    def test_an_old_book_types_entries_match_entries_of_the_parent_its_name_gives(self):
        old = {"warding item": "a charm", "elixir": "a serum"}
        self.assertEqual(entities(old, ("Salt Ward", "artifact"), ("Salt Ward", "warding item")), {"Salt Ward": "warding item"})
        self.assertEqual(entities(old, ("Moonwater", "concept"), ("Moonwater", "elixir")), {"Moonwater": "elixir"})


if __name__ == "__main__":
    unittest.main()
