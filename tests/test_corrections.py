import json
import tempfile
import unittest
from pathlib import Path

from annalist.corrections import correct_profiles, Corrections, EVERY_CORRECTION, load_corrections, reader_notes
from annalist.export import build
from annalist.state import Knowledge, load_states


VIEW = {"recent_entities": 25, "recent_questions": 40, "matched_questions": 15}


def entity(name, etype="character", aliases=()):
    return {"name": name, "type": etype, "aliases": list(aliases)}


def fact(who, quote):
    return {"entity": who, "claim": quote, "quotes": [quote]}


def tie(source, target, kind, quote):
    return {"source": source, "target": target, "type": kind, "detail": "", "quotes": [quote]}


TEXT = {
    1: "Mira Vale walked into Northmarch at dawn. A hooded figure followed her.",
    2: "A grey stranger watched Mira Vale from the bridge. The Veil kept her face hidden.",
    3: "Old Grey said nothing. The Veil spoke of the old king, and the hood fell back.",
    4: "He pushed his spectacles up, the way Mira's brother always did.",
    5: "Mira Vale lit a candle for her brother. The Veil was Mira all along.",
    6: "The grey stranger returned to Northmarch. She rose from the grave and walked home.",
}

STORY = {
    1: {"entities": [entity("Mira Vale"), entity("Northmarch", "uncategorized"), entity("Hood")],
        "facts": [fact("Mira Vale", "Mira Vale walked into Northmarch at dawn."), fact("Hood", "A hooded figure followed her.")]},
    2: {"entities": [entity("Grey Stranger"), entity("The Veil")],
        "facts": [fact("Grey Stranger", "A grey stranger watched Mira Vale from the bridge."), fact("The Veil", "The Veil kept her face hidden.")],
        "relations": [tie("Grey Stranger", "Mira Vale", "watches", "A grey stranger watched Mira Vale from the bridge.")]},
    3: {"entities": [entity("Grey Stranger", aliases=["Old Grey"]), entity("The Veil")],
        "facts": [fact("Grey Stranger", "Old Grey said nothing."), fact("The Veil", "The Veil spoke of the old king, and the hood fell back.")]},
    4: {"entities": [entity("Mira Vale")], "facts": [fact("Mira Vale", "He pushed his spectacles up, the way Mira's brother always did.")]},
    5: {"entities": [entity("Mira Vale")], "facts": [fact("Mira Vale", "Mira Vale lit a candle for her brother.")]},
    6: {"entities": [entity("Grey Stranger"), entity("Mira Vale")], "facts": [fact("Grey Stranger", "The grey stranger returned to Northmarch.")],
        "relations": [tie("Grey Stranger", "Mira Vale", "watches", "The grey stranger returned to Northmarch.")]},
}

MERGES = [{"a": "Mira Vale", "b": "The Veil", "canonical": "Mira Vale", "same": True, "revealed": {"basis": "text", "chapter": 5}},
          {"a": "Grey Stranger", "b": "Hood", "canonical": "Grey Stranger", "same": True, "revealed": {"basis": "text", "chapter": 3}}]

SAME = {"name": "Grey Stranger", "same_as": "Mira Vale", "chapter": 4, "quotes": ["He pushed his spectacles up"]}


class Story:
    def __init__(self, test, corrections, merges=MERGES):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.workdir = Path(folder.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "state").mkdir()
        for n, text in TEXT.items():
            (self.workdir / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
            (self.workdir / "state" / f"{n:04d}.json").write_text(json.dumps({"chapter": n, "extraction": {"synopsis": text, **STORY[n]}}),
                                                                  encoding="utf-8")
        (self.workdir / "chapters.json").write_text(json.dumps([{"index": n, "title": str(n)} for n in TEXT]), encoding="utf-8")
        (self.workdir / "merges.json").write_text(json.dumps({"pairs": merges}), encoding="utf-8")
        (self.workdir / "corrections.json").write_text(json.dumps({"entries": [], **corrections}), encoding="utf-8")

    def kb(self, until=None):
        return load_states(self.workdir, until=until, corrections=EVERY_CORRECTION)

    def site(self):
        return build(self.workdir, {})


def page(kb, name):
    return kb.entities[kb.resolve(name)]


def where(kb, quote):
    f = next(f for f in kb.facts if f["quotes"] == [quote])
    return f["entity"], f.get("filed")


class SameAs(unittest.TestCase):
    def test_the_description_page_joins_the_named_page_from_the_chapter_of_the_clue(self):
        kb = Story(self, {"entries": [SAME]}).kb()
        self.assertNotIn("Grey Stranger", kb.entities)
        joined = next(a for a in kb.entities["Mira Vale"]["absorbed"] if a["name"] == "Grey Stranger")
        self.assertEqual((joined["chapter"], joined["by"], joined["type"]), (4, "reader", "character"))
        self.assertEqual(where(kb, "Old Grey said nothing."), ("Mira Vale", "Grey Stranger"))
        self.assertEqual(where(kb, "The grey stranger returned to Northmarch."), ("Mira Vale", "Grey Stranger"))
        self.assertEqual(kb.problems, [])

    def test_before_the_chapter_the_two_pages_stay_apart(self):
        kb = Story(self, {"entries": [SAME]}).kb(until=3)
        self.assertIn("Grey Stranger", kb.entities)
        self.assertEqual(where(kb, "Old Grey said nothing.")[0], "Grey Stranger")

    def test_a_tie_between_the_two_before_the_chapter_stays_and_a_later_one_becomes_no_tie(self):
        kb = Story(self, {"entries": [SAME]}).kb()
        watches = [(r["chapter"], r["source"], r["target"], r.get("filed")) for r in kb.relations if r["type"] == "watches"]
        self.assertEqual(watches, [(2, "Mira Vale", "Mira Vale", {"source": "Grey Stranger"})])

    def test_a_page_already_merged_into_the_description_joins_no_earlier_than_the_correction(self):
        kb = Story(self, {"entries": [SAME]}).kb()
        self.assertEqual(next(a["chapter"] for a in kb.entities["Mira Vale"]["absorbed"] if a["name"] == "Hood"), 4)

    def test_a_chapter_before_either_page_appears_is_skipped_with_a_warning(self):
        kb = Story(self, {"entries": [{**SAME, "chapter": 1, "quotes": ["A hooded figure followed her."]}]}, merges=[]).kb()
        self.assertIn("Grey Stranger", kb.entities)
        self.assertEqual(kb.problems, ["correction Grey Stranger same_as Mira Vale: chapter 1 is before one of them first appears, skipped"])

    def test_an_unknown_name_on_either_side_is_reported(self):
        for fix in ({**SAME, "name": "Nobody"}, {**SAME, "same_as": "Nobody"}):
            kb = Story(self, {"entries": [fix]}).kb()
            self.assertIn("Grey Stranger", kb.entities)
            self.assertEqual(kb.problems, ["corrections.json names 'Nobody', which matches no entry, skipped"])

    def test_two_names_of_one_page_are_left_alone(self):
        kb = Story(self, {"entries": [{**SAME, "name": "Old Grey", "same_as": "Grey Stranger"}]}).kb()
        self.assertIn("Grey Stranger", kb.entities)
        self.assertIn("already the same page", kb.problems[0])

    def test_a_link_whose_quote_is_not_in_its_chapter_is_skipped_with_a_warning(self):
        kb = Story(self, {"entries": [{**SAME, "quotes": ["He took off his hat."]}]}).kb()
        self.assertIn("Grey Stranger", kb.entities)
        self.assertEqual(kb.problems, ["correction Grey Stranger.same_as ch4 has no quote found in that chapter, skipped"])


class KnownFrom(unittest.TestCase):
    def test_known_from_moves_a_merge_earlier_in_every_view(self):
        story = Story(self, {"entries": [{"name": "The Veil", "known_from": {"chapter": 3, "quotes": ["The Veil spoke of the old king"]}}]})
        self.assertEqual(next(a["chapter"] for a in story.kb().entities["Mira Vale"]["absorbed"] if a["name"] == "The Veil"), 3)
        self.assertNotIn("The Veil", story.kb(until=3).entities)
        self.assertIn("The Veil", story.kb(until=2).entities)


class TypesTitlesAndTies(unittest.TestCase):
    def test_changes_the_type_of_an_entry_found_by_any_name(self):
        kb = Story(self, {"entries": [{"name": "Northmarch", "type": "place"}, {"name": "Old Grey", "type": "deity"}]}).kb()
        self.assertEqual((page(kb, "Northmarch")["type"], page(kb, "Grey Stranger")["type"]), ("place", "deity"))

    def test_a_title_keeps_the_old_name_before_the_reveal(self):
        problems, wiki = Story(self, {"entries": [{"name": "Northmarch", "title": "Free City of Northmarch", "title_chapter": 6}]}).site()
        shown = next(e for e in wiki["entities"] if e["name"] == "Free City of Northmarch")
        self.assertEqual((shown["name_chapter"], shown["aliases"]), (6, [{"name": "Northmarch", "chapter": 1}]))
        self.assertEqual(problems, [])

    def test_an_added_relation_takes_the_defaults_and_its_named_family(self):
        row = {"source": "Mira Vale", "target": "Northmarch", "type": "rules", "family": "service", "chapter": 5,
               "quotes": ["Mira Vale lit a candle for her brother."]}
        problems, wiki = Story(self, {"relations": [row]}).site()
        names = {e["id"]: e["name"] for e in wiki["entities"]}
        added = [(names[r["source"]], names[r["target"]], r["family"], r["status"], r["by"]) for r in wiki["relations"] if r["type"] == "rules"]
        self.assertEqual(added, [("Mira Vale", "Northmarch", "service", "stated", "narrator")])
        self.assertEqual(problems, [])

    def test_an_added_relation_waits_for_its_chapter(self):
        row = {"source": "Mira Vale", "target": "Northmarch", "type": "rules", "chapter": 5, "quotes": ["Mira Vale lit a candle for her brother."]}
        story = Story(self, {"relations": [row]})
        self.assertEqual([r for r in story.kb(until=4).relations if r["type"] == "rules"], [])

    def test_a_relation_naming_the_merged_page_before_its_merge_stays_on_that_page(self):
        row = {"source": "The Veil", "target": "Northmarch", "type": "rules", "chapter": 3, "quotes": ["The Veil spoke of the old king"]}
        added = next(r for r in Story(self, {"relations": [row]}).kb().relations if r["type"] == "rules")
        self.assertEqual((added["source"], added["filed"]), ("Mira Vale", {"source": "The Veil"}))

    def test_a_dropped_relation_is_removed_and_a_wrong_drop_is_reported(self):
        good = {"source": "Grey Stranger", "target": "Mira Vale", "type": "watches", "chapter": 2}
        bad = {"source": "Grey Stranger", "target": "Mira Vale", "type": "hates", "chapter": 2}
        kb = Story(self, {"drop_relations": [good, bad]}).kb()
        self.assertEqual([r["chapter"] for r in kb.relations if r["type"] == "watches"], [6])
        self.assertEqual(kb.problems, ["corrections.json names 'Grey Stranger -> Mira Vale: hates (ch 2)', which matches no entry, skipped"])

    def test_a_relation_naming_nobody_is_reported(self):
        row = {"source": "Nobody", "target": "Mira Vale", "type": "loves", "chapter": 5, "quotes": ["Mira Vale lit a candle"]}
        kb = Story(self, {"relations": [row]}).kb()
        self.assertEqual(kb.problems, ["corrections.json names 'Nobody', which matches no entry, skipped"])
        self.assertEqual([r for r in kb.relations if r["type"] == "loves"], [])

    def test_no_corrections_leave_the_knowledge_as_the_pipeline_built_it(self):
        story = Story(self, {})
        plain = load_states(story.workdir)
        kb = story.kb()
        self.assertEqual((kb.entities, kb.facts, kb.relations, kb.questions), (plain.entities, plain.facts, plain.relations, plain.questions))


STATUS = {"chapter": 6, "value": "revived", "quotes": ["She rose from the grave and walked home."]}


def profiles(story, entries, pages):
    kb = Story(story, {"entries": entries}).kb()
    return correct_profiles(kb, pages, kb.corrections)


class Fields(unittest.TestCase):
    def dead(self):
        return {"Mira Vale": {"fields": {"status": [{"chapter": 4, "value": "dead", "quotes": ["q"], "quote_ok": True}]}, "extra": {}, "lists": {}}}

    def test_a_later_value_joins_the_history_from_its_chapter(self):
        pages = profiles(self, [{"name": "Mira Vale", "fields": {"status": [STATUS]}}], self.dead())
        self.assertEqual([(o["chapter"], o["value"]) for o in pages["Mira Vale"]["fields"]["status"]], [(4, "dead"), (6, "revived")])

    def test_a_value_replaces_the_value_for_the_same_chapter(self):
        row = {"chapter": 4, "value": "missing", "quotes": ["He pushed his spectacles up"]}
        pages = profiles(self, [{"name": "Mira Vale", "fields": {"status": [row]}}], self.dead())
        self.assertEqual([o["value"] for o in pages["Mira Vale"]["fields"]["status"]], ["missing"])

    def test_gives_an_entry_without_a_profile_one(self):
        row = {"chapter": 6, "value": "Free city", "quotes": ["The grey stranger returned to Northmarch."]}
        pages = profiles(self, [{"name": "Northmarch", "fields": {"rank": [row]}}], {})
        self.assertEqual(pages["Northmarch"]["extra"]["rank"][0]["value"], "Free city")

    def test_a_value_named_for_a_merged_page_before_its_merge_shows_there_and_waits_on_the_whole_page(self):
        row = {"chapter": 3, "value": "veiled", "quotes": ["The Veil spoke of the old king"]}
        pages = profiles(self, [{"name": "The Veil", "fields": {"appearance": [row]}}], {})
        self.assertEqual([o.get("shown") for o in pages["The Veil"]["lists"]["appearance"]], [None])
        self.assertEqual([o["shown"] for o in pages["Mira Vale"]["lists"]["appearance"]], [5])


class LoadCorrections(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.workdir = Path(folder.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "chapters" / "0007.txt").write_text("The sun came up. She rose from the grave and walked home.", encoding="utf-8")

    def write(self, entries):
        (self.workdir / "corrections.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")

    def test_no_file_means_no_corrections(self):
        self.assertEqual(load_corrections(self.workdir).entries, [])

    def test_keeps_a_row_whose_quote_is_in_its_chapter(self):
        row = {"chapter": 7, "value": "revived", "quotes": ["She rose from the grave and walked home."]}
        self.write([{"name": "A", "fields": {"status": [row]}}])
        self.assertEqual([r["value"] for r in load_corrections(self.workdir).entries[0]["fields"]["status"]], ["revived"])

    def test_drops_and_reports_a_row_whose_quote_is_not_in_its_chapter(self):
        self.write([{"name": "A", "fields": {"status": [{"chapter": 7, "value": "revived", "quotes": ["An invented sentence that never appears anywhere."]}]}}])
        loaded = load_corrections(self.workdir)
        self.assertEqual(loaded.entries[0]["fields"]["status"], [])
        self.assertEqual(loaded.problems, ["correction A.status ch7 has no quote found in that chapter, skipped"])

    def test_refuses_a_correction_with_no_name(self):
        self.write([{"type": "place"}])
        with self.assertRaises(SystemExit):
            load_corrections(self.workdir)

    def test_refuses_a_link_with_no_chapter(self):
        self.write([{"name": "Bespectacled man", "same_as": "Arlen", "quotes": ["She rose from the grave"]}])
        with self.assertRaises(SystemExit):
            load_corrections(self.workdir)


class Reader(unittest.TestCase):
    def setUp(self):
        self.kb = Knowledge(None, {}, ())
        self.kb.upsert_entity({"name": "Mira Vale", "type": "uncategorized", "summary": "A traveller."}, 1)
        self.kb.upsert_entity({"name": "Grey Stranger", "type": "character", "summary": "A man in grey."}, 2)
        row = {"chapter": 7, "value": "revived", "quotes": ["She rose."]}
        self.corrections = Corrections(entries=[{"name": "Mira Vale", "type": "deity", "fields": {"status": [row]}},
                                                {"name": "Grey Stranger", "same_as": "Mira Vale", "chapter": 4, "quotes": ["q"]}],
                                       relations=[], dropped=[], problems=[])

    def notes(self, chapter):
        return reader_notes(self.kb, self.corrections, chapter)

    def test_reader_sees_a_correction_from_an_earlier_chapter(self):
        self.assertIn("status: revived (chapter 7)", self.notes(8)["Mira Vale"])

    def test_reader_is_not_told_a_correction_from_a_later_chapter(self):
        self.assertNotIn("revived", self.notes(7)["Mira Vale"])

    def test_reader_sees_the_corrected_type(self):
        self.assertIn("type: deity", self.kb.compact_view("Mira Vale came.", VIEW, self.notes(2)))

    def test_the_reader_learns_a_link_only_in_chapters_after_it(self):
        self.assertNotIn("Grey Stranger", self.notes(4))
        self.assertEqual(self.notes(5)["Grey Stranger"], "same as Mira Vale from chapter 4")

    def test_view_is_unchanged_with_no_corrections(self):
        self.assertEqual(self.kb.compact_view("Mira Vale came.", VIEW), self.kb.compact_view("Mira Vale came.", VIEW, {}))


if __name__ == "__main__":
    unittest.main()
