import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from annalist.corrections import apply_to_wiki, load_corrections, reader_notes
from annalist.state import Knowledge


VIEW = {"recent_entities": 25, "recent_questions": 40, "matched_questions": 15}


def wiki():
    return {"entities": [
        {"id": "a", "name": "Veiled Woman", "name_chapter": 2, "type": "character", "first": 2, "aliases": [{"name": "Mira Vale", "chapter": 9}],
         "profile": {"fields": {"status": [{"chapter": 4, "value": "dead", "quotes": ["She fell."]}]}, "lists": {}, "spoke": [], "personality": []}},
        {"id": "b", "name": "Northmarch", "name_chapter": 1, "type": "uncategorized", "first": 1, "aliases": []},
    ]}


def rows(corrected, name):
    return next(e for e in corrected["entities"] if e["name"] == name)["profile"]["fields"]


def merged_wiki():
    return {"relations": [{"chapter": 8, "source": "q", "target": "p", "type": "knows"}], "entities": [
        {"id": "p", "name": "Mira Vale", "first": 1, "aliases": [{"name": "The Veil", "chapter": 40}],
         "profile": {"fields": {"rank": [{"chapter": 12, "shown": 40, "value": "Baron", "quotes": ["The Baron."]}]}, "lists": {}}},
        {"id": "q", "name": "The Veil", "first": 10, "aliases": [], "merged": {"into": "p", "chapter": 40}},
    ]}


class KnownFromAndRelations(unittest.TestCase):
    def test_known_from_moves_a_merge_and_what_it_held_back(self):
        fix = [{"name": "The Veil", "known_from": {"chapter": 10, "quotes": ["q"]}}]
        corrected, missing = apply_to_wiki(merged_wiki(), fix)
        page, part = corrected["entities"]
        self.assertEqual(missing, [])
        self.assertEqual(part["merged"]["chapter"], 10)
        self.assertEqual(page["aliases"][0]["chapter"], 10)
        self.assertEqual(page["profile"]["fields"]["rank"][0]["shown"], 12)

    def test_an_added_relation_joins_the_others_in_chapter_order(self):
        row = {"source": "Mira Vale", "target": "The Veil", "type": "loves", "family": "romance", "chapter": 3, "quotes": ["q"]}
        corrected, missing = apply_to_wiki(merged_wiki(), [], [row])
        self.assertEqual(missing, [])
        added = corrected["relations"][0]
        self.assertEqual((added["source"], added["target"], added["family"], added["status"], added["by"]), ("p", "q", "romance", "stated", "narrator"))

    def test_a_dropped_relation_is_removed_and_a_wrong_drop_is_reported(self):
        good = {"source": "The Veil", "target": "Mira Vale", "type": "knows", "chapter": 8}
        bad = {"source": "The Veil", "target": "Mira Vale", "type": "hates", "chapter": 8}
        corrected, missing = apply_to_wiki(merged_wiki(), [], [], [good, bad])
        self.assertEqual(corrected["relations"], [])
        self.assertEqual(missing, ["The Veil -> Mira Vale: hates (ch 8)"])

    def test_a_relation_naming_nobody_is_reported(self):
        row = {"source": "Nobody", "target": "The Veil", "type": "loves", "chapter": 3, "quotes": ["q"]}
        corrected, missing = apply_to_wiki(merged_wiki(), [], [row])
        self.assertEqual(missing, ["Nobody"])
        self.assertEqual(len(corrected["relations"]), 1)


class ApplyToWiki(unittest.TestCase):
    def test_changes_the_type_of_an_entry(self):
        corrected, missing = apply_to_wiki(wiki(), [{"name": "Northmarch", "type": "place"}])
        self.assertEqual(corrected["entities"][1]["type"], "place")
        self.assertEqual(missing, [])

    def test_finds_an_entry_by_alias(self):
        corrected, _ = apply_to_wiki(wiki(), [{"name": "Mira Vale", "type": "deity"}])
        self.assertEqual(corrected["entities"][0]["type"], "deity")

    def test_later_status_is_hidden_until_its_chapter(self):
        row = {"chapter": 7, "value": "revived", "quotes": ["She rose."]}
        corrected, _ = apply_to_wiki(wiki(), [{"name": "Veiled Woman", "fields": {"status": [row]}}])
        self.assertEqual([(o["chapter"], o["value"]) for o in rows(corrected, "Veiled Woman")["status"]], [(4, "dead"), (7, "revived")])

    def test_row_replaces_the_value_for_the_same_chapter(self):
        row = {"chapter": 4, "value": "missing", "quotes": ["She vanished."]}
        corrected, _ = apply_to_wiki(wiki(), [{"name": "Veiled Woman", "fields": {"status": [row]}}])
        self.assertEqual([o["value"] for o in rows(corrected, "Veiled Woman")["status"]], ["missing"])

    def test_gives_an_entry_without_a_profile_one(self):
        row = {"chapter": 3, "value": "Baron", "quotes": ["The Baron."]}
        corrected, _ = apply_to_wiki(wiki(), [{"name": "Northmarch", "fields": {"rank": [row]}}])
        self.assertEqual(rows(corrected, "Northmarch")["rank"][0]["value"], "Baron")
        self.assertEqual(next(e for e in corrected["entities"] if e["id"] == "b")["profile"]["spoke"], [])

    def test_title_keeps_the_old_name_before_the_reveal(self):
        corrected, _ = apply_to_wiki(wiki(), [{"name": "Veiled Woman", "title": "Mira Vale", "title_chapter": 9}])
        page = corrected["entities"][0]
        self.assertEqual((page["name"], page["name_chapter"]), ("Mira Vale", 9))
        self.assertEqual(page["aliases"], [{"name": "Veiled Woman", "chapter": 2}])

    def test_reports_a_correction_that_matches_nothing(self):
        corrected, missing = apply_to_wiki(wiki(), [{"name": "Nobody", "type": "place"}])
        self.assertEqual(missing, ["Nobody"])
        self.assertEqual(corrected, wiki())

    def test_does_not_change_its_input(self):
        original = wiki()
        before = copy.deepcopy(original)
        apply_to_wiki(original, [{"name": "Northmarch", "type": "place"}])
        self.assertEqual(original, before)


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
        self.assertEqual(load_corrections(self.workdir), [])

    def test_keeps_a_row_whose_quote_is_in_its_chapter(self):
        row = {"chapter": 7, "value": "revived", "quotes": ["She rose from the grave and walked home."]}
        self.write([{"name": "A", "fields": {"status": [row]}}])
        self.assertEqual(load_corrections(self.workdir)[0]["fields"]["status"], [row])

    def test_drops_and_reports_a_row_whose_quote_is_not_in_its_chapter(self):
        self.write([{"name": "A", "fields": {"status": [{"chapter": 7, "value": "revived", "quotes": ["An invented sentence that never appears anywhere."]}]}}])
        out = io.StringIO()
        with redirect_stdout(out):
            loaded = load_corrections(self.workdir)
        self.assertEqual(loaded[0]["fields"]["status"], [])
        self.assertIn("A.status", out.getvalue())

    def test_refuses_a_correction_with_no_name(self):
        self.write([{"type": "place"}])
        with self.assertRaises(SystemExit):
            load_corrections(self.workdir)


class Reader(unittest.TestCase):
    def setUp(self):
        self.kb = Knowledge(None, {}, ())
        self.kb.upsert_entity({"name": "Mira Vale", "type": "uncategorized", "summary": "A traveller."}, 1)
        row = {"chapter": 7, "value": "revived", "quotes": ["She rose."]}
        self.corrections = [{"name": "Mira Vale", "type": "deity", "fields": {"status": [row]}}]

    def view(self, chapter):
        return self.kb.compact_view("Mira Vale came.", VIEW, reader_notes(self.kb, self.corrections, chapter))

    def test_reader_sees_a_correction_from_an_earlier_chapter(self):
        self.assertIn("status: revived (chapter 7)", self.view(8))

    def test_reader_is_not_told_a_correction_from_a_later_chapter(self):
        self.assertNotIn("revived", self.view(7))

    def test_reader_sees_the_corrected_type(self):
        self.assertIn("type: deity", self.view(2))

    def test_view_is_unchanged_with_no_corrections(self):
        self.assertEqual(self.kb.compact_view("Mira Vale came.", VIEW), self.kb.compact_view("Mira Vale came.", VIEW, {}))
