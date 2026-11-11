import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from types import SimpleNamespace

from annalist.book import load_book
from annalist.evidence import affiliations
from annalist.files import write_json
from annalist.ladders import ladder_needed
from annalist.link import fact_candidates
from annalist.resolve import candidate_pairs, decide_pair
from annalist.review import merges
from annalist.state import Knowledge
from tests.test_build import ROOT, site_views


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


class BookTypeResolveTest(unittest.TestCase):
    TYPES = {"warding item": {"parent": "artifact", "description": "a charm"}, "relic": {"parent": "artifact", "description": "an old thing"}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = Path(tmp.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "chapters" / "0001.txt").write_text(
            "Ilse hung the Salt Ward over the door. Varn kept the Bone Charm and a Bone Charm Shard in his coat.\n", encoding="utf-8")
        self.kb = Knowledge(power_types=self.TYPES)
        for name, etype in (("Salt Ward", "warding item"), ("Salt Ward of Corvel", "artifact"), ("Bone Charm", "warding item"),
                            ("Bone Charm Shard", "relic")):
            self.kb.upsert_entity({"name": name, "type": etype, "summary": f"{name}, a charm of the quay"}, 1)
        self.kb.synopses[1] = "Ilse hangs a ward."
        self.pairs = candidate_pairs(self.workdir, self.kb, {}, 1)

    def test_entries_of_a_book_type_and_its_parent_are_proposed_as_one_and_judged_as_the_parent_type(self):
        key = ("Salt Ward", "Salt Ward of Corvel")
        self.assertIn(key, self.pairs)
        prompts = []

        def reply(workdir, purpose, prompt, **kw):
            prompts.append(prompt)
            return {"same": False, "reason": "Two charms."}

        with patch("annalist.resolve.cached_llm", side_effect=reply):
            decide_pair(self.workdir, self.kb, {}, {}, *key, self.pairs[key])
        self.assertIn("may describe the same artifact.", prompts[0])

    def test_two_book_types_of_one_parent_are_never_proposed_as_one(self):
        self.assertNotIn(("Bone Charm", "Bone Charm Shard"), self.pairs)

    def test_a_merge_of_a_book_type_into_its_parent_keeps_the_book_type(self):
        self.kb.apply_merges([{"a": "Salt Ward", "b": "Salt Ward of Corvel", "same": True, "canonical": "Salt Ward of Corvel",
                               "revealed": {"basis": "quote", "chapter": 1}}])
        merged = self.kb.entities["Salt Ward of Corvel"]
        self.assertEqual((merged["type"], merged["aliases"]), ("warding item", ["Salt Ward"]))
        self.assertNotIn("Salt Ward", self.kb.entities)


def category_wiki():
    rows = [("Salt Ward", "warding item", 1), ("Bone Charm", "warding item", 3), ("Grey Lamp", "artifact", 1), ("Ilse", "character", 1)]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": c, "type": t, "first": c, "aliases": [], "blurbs": [[c, f"{n} of the quay."]]}
                for i, (n, t, c) in enumerate(rows, 1)]
    facts = [{"id": f"F{i}", "chapter": e["first"], "entity": e["id"], "claim": f"{e['name']} is on the quay.", "status": "stated",
              "by": "narrator", "quotes": []} for i, e in enumerate(entities, 1)]
    return {"book": {"title": "Quay", "max": 3, "public_domain": False, "theme": {}, "power_types": ["warding item"],
                     "parents": {"warding item": "artifact"}, "ladder": None},
            "chapters": [{"n": n, "title": f"Chapter {n}", "synopsis": ""} for n in (1, 2, 3)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": facts, "relations": [], "questions": [], "ladders": [], "volumes": []}, {e["name"]: e["id"] for e in entities}


def plain(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


class BookTypeCategoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wiki, cls.ids = category_wiki()
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
            cls.views = site_views(path, "route:cat:artifact@1", "route:cat:artifact@3", "route:cat:warding item@3",
                                   f"{cls.ids['Salt Ward']}@1", "route:cat:character@1")

    def test_the_parent_category_links_to_each_book_type_category_with_its_entries_so_far(self):
        early, later = (plain(self.views[f"route:cat:artifact@{n}"]["html"]) for n in (1, 3))
        self.assertIn("Subcategories Warding items 1", early)
        self.assertIn("Subcategories Warding items 2", later)
        self.assertIn('data-go="cat:warding item"', self.views["route:cat:artifact@3"]["html"])
        self.assertNotIn("Subcategories", plain(self.views["route:cat:character@1"]["html"]))

    def test_a_book_type_category_and_its_entries_sit_under_the_parent_in_the_crumbs(self):
        self.assertIn("Home › Artifacts Warding items 2 entries", plain(self.views["route:cat:warding item@3"]["html"]))
        self.assertIn("Home › Artifacts › Warding items Salt Ward", plain(self.views[f"{self.ids['Salt Ward']}@1"]))
        self.assertIn("Bone Charm", plain(self.views["route:cat:warding item@3"]["html"]))


class BookTypeKindTest(unittest.TestCase):
    TYPES = {"warding item": {"parent": "artifact", "description": "a charm"}, "harbour fort": {"parent": "place", "description": "a fort"},
             "sect": {"parent": "organization", "description": "a school of lamp lore"}}
    TEXT = "Ilse lived at Corvel Keep. Ilse was a member of the Ember Sect.\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = Path(tmp.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "chapters" / "0001.txt").write_text(self.TEXT, encoding="utf-8")
        self.kb = Knowledge(power_types=self.TYPES)
        for name, etype in (("Ilse", "character"), ("Corvel Keep", "harbour fort"), ("Ember Sect", "sect"), ("Salt Ward", "warding item"),
                            ("Grey Charm", "artifact"), ("Corvel Quay", "place")):
            self.kb.upsert_entity({"name": name, "type": etype, "summary": f"{name} of the quay"}, 1)
        self.kb.synopses[1] = "Ilse joins a sect."

    def test_a_fact_naming_an_entry_of_a_book_type_of_place_is_labelled_with_the_place_labels(self):
        self.kb.facts.append({"id": "F0001-001", "chapter": 1, "entity": "Ilse", "claim": "Ilse lives at Corvel Keep.",
                              "quotes": ["Ilse lived at Corvel Keep."], "asserted_by": "narrator", "status": "stated", "timeline": "main"})
        found = fact_candidates(self.workdir, self.kb)
        self.assertEqual([(c["source"], c["target"], c["type"]) for c in found], [("Ilse", "Corvel Keep", "place")])

    def test_membership_of_a_book_type_of_organization_is_an_affiliation(self):
        self.kb.relations.append({"id": "R0001-001", "chapter": 1, "source": "Ilse", "target": "Ember Sect", "type": "member of", "detail": "",
                                  "quotes": ["Ilse was a member of the Ember Sect."], "asserted_by": "narrator", "status": "stated",
                                  "timeline": "main"})
        self.assertEqual([o["value"] for o in affiliations(self.workdir, self.kb, "Ilse")], ["Ember Sect"])

    def test_review_flags_a_merge_across_unrelated_types_but_not_one_of_a_book_type_and_its_parent(self):
        write_json(self.workdir / "merges.json", {"pairs": [
            {"a": "Salt Ward", "b": "Grey Charm", "same": True, "canonical": "Grey Charm", "reason": "One charm."},
            {"a": "Salt Ward", "b": "Corvel Quay", "same": True, "canonical": "Corvel Quay", "reason": "One place."}]})
        flagged = merges(SimpleNamespace(workdir=self.workdir, extracted=self.kb))
        self.assertEqual([(f["a"], f["b"], f["reasons"]) for f in flagged], [("Salt Ward", "Corvel Quay", ["cross-type (warding item / place)"])])


if __name__ == "__main__":


    unittest.main()
