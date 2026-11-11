import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from annalist.backends import load_settings
from annalist.book import load_book
from annalist.files import read_jsonl, write_json
from annalist.state import Knowledge
from annalist.survey import book_problems, generate_book

BAD = {"power_system": "Lamplighters keep the harbour lamps.",
       "power_types": [{"type": "lamplighter", "description": "a keeper of the harbour lamps"},
                       {"type": "relic", "description": "an object holding old harbour magic"}],
       "extra_fields": [{"name": "gender", "description": "male or female"}],
       "power_keywords": ["lamp"]}

GOOD = {"power_system": "Lamplighters keep the harbour lamps.",
        "power_types": [{"type": "relic", "description": "an object holding old harbour magic"}],
        "extra_fields": [{"name": "guild rank", "description": "the character's rank in the Lamplighters' Guild",
                          "values": ["Apprentice", "Keeper", "Master"]}],
        "power_keywords": ["lamp"], "timeline_kind": "flashback", "timeline_note": "Chapter two is set nine winters ago."}


def harbour_kb():
    kb = Knowledge()
    for name, etype in (("Tomas Hale", "lamplighter"), ("Odile Marr", "lamplighter"), ("Bram Ostrow", "lamplighter"),
                        ("Salt Ledger", "relic"), ("Ines Varro", "character")):
        kb.upsert_entity({"name": name, "type": etype, "summary": f"{name} of Corvel Quay"}, 1)
    for i, (entity, speaker) in enumerate((("Salt Ledger", "Tomas Hale"), ("Salt Ledger", "Odile Marr"),
                                           ("Ines Varro", "Bram Ostrow")), 1):
        kb.facts.append({"id": f"F{i}", "entity": entity, "chapter": 1, "claim": "a claim", "quotes": [],
                         "asserted_by": speaker, "status": "stated", "timeline": "main"})
    kb.synopses[1] = "The harbour lamp goes dark."
    return kb


class BookGenerationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = Path(tmp.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "chapters" / "0001.txt").write_text("The harbour lamp went dark.\n", encoding="utf-8")
        write_json(self.workdir / "chapters.json", [{"index": 1, "title": "The Missing Page"}])
        write_json(self.workdir / "source.json", {"complete": True, "complete_evidence": "THE END"})
        write_json(self.workdir / "book.json", {"backend": {"name": "fake", "script": "script.json"}})
        patcher = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def script(self, *replies):
        write_json(self.workdir / "script.json", {"replies": [{"purpose": "book", "reply": r} for r in replies]})

    def calls(self):
        return read_jsonl(self.workdir / "calls.jsonl")

    def test_a_power_type_of_people_is_rejected_and_the_retry_gives_a_valid_book(self):
        self.script(BAD, GOOD)
        kb = harbour_kb()
        generate_book(self.workdir, kb, kb)
        calls = self.calls()
        self.assertEqual([c["mode"] for c in calls], ["original", "revise"])
        self.assertIn('power type "lamplighter" holds people: 3 of its 3 entries so far speak', calls[0]["error"])
        self.assertIn('extra field "gender" repeats the general field "sex"', calls[0]["error"])
        self.assertIn("timeline_kind must be one of loop, flashback, linear", calls[0]["error"])
        self.assertIsNone(calls[1]["error"])
        book = load_book(self.workdir)
        self.assertEqual(book["power_types"], {"relic": "an object holding old harbour magic"})
        self.assertEqual(book["field_values"], {"guild_rank": ["Apprentice", "Keeper", "Master"]})
        self.assertEqual((book["timeline_kind"], book["complete"]), ("flashback", True))
        self.assertEqual(load_settings(self.workdir).backend, "fake")

    def test_a_cached_reply_that_fails_validation_is_revised_not_reused(self):
        self.script(GOOD)
        kb = harbour_kb()
        generate_book(self.workdir, kb, kb)
        cached = next((self.workdir / "cache").glob("book-*.json"))
        write_json(cached, {"purpose": "book", "backend": "fake", "model": "fake", "reply": BAD})
        generate_book(self.workdir, kb, kb)
        self.assertEqual([c["mode"] for c in self.calls()], ["original", "revise"])
        self.assertEqual(json.loads(cached.read_text(encoding="utf-8"))["reply"], GOOD)

    def test_a_regenerated_book_keeps_the_extra_fields_the_workdir_already_had(self):
        self.script(GOOD)
        kb = harbour_kb()
        generate_book(self.workdir, kb, kb)
        kb.synopses[2] = "Tomas is buried."
        renamed = {**GOOD, "extra_fields": [
            {"name": "keeper class", "description": "the class of keeper", "values": ["Keeper", "Master"]},
            {"name": "lamp colour", "description": "the colour of the lamp the character keeps"}]}
        self.script(renamed)
        generate_book(self.workdir, kb, kb)
        book = load_book(self.workdir)
        self.assertEqual(book["extra_fields"], {"guild_rank": "the character's rank in the Lamplighters' Guild",
                                                "lamp_colour": "the colour of the lamp the character keeps"})
        self.assertEqual(book["field_values"]["guild_rank"], ["Apprentice", "Keeper", "Master"])

    def test_a_kept_field_that_repeats_a_general_field_is_dropped(self):
        write_json(self.workdir / "book.json", {"backend": {"name": "fake", "script": "script.json"},
                                                "extra_fields": {"gender": "male or female"}})
        self.script(GOOD)
        kb = harbour_kb()
        generate_book(self.workdir, kb, kb)
        self.assertEqual(list(load_book(self.workdir)["extra_fields"]), ["guild_rank"])

    def test_extra_fields_that_track_the_same_thing_are_rejected(self):
        reply = {**GOOD, "extra_fields": GOOD["extra_fields"] + [
            {"name": "rank", "description": "the character's rank, such as Keeper (Lamp)", "values": []}]}
        self.assertIn('extra fields "guild_rank" and "rank" track the same thing', book_problems(reply, Knowledge()))

    def test_a_workdir_book_with_overlapping_fields_keeps_the_first_and_its_class_names(self):
        write_json(self.workdir / "book.json", {"backend": {"name": "fake", "script": "script.json"}, "extra_fields": {
            "guild_rank": "the character's rank and lamp, written as 'Rank, Lamp'",
            "rank": {"description": "the rank", "values": ["Apprentice", "Keeper"]}}})
        loaded = load_book(self.workdir)
        self.assertEqual(list(loaded["extra_fields"]), ["guild_rank"])
        self.assertEqual(loaded["field_values"]["guild_rank"], ["Apprentice", "Keeper"])
        self.script({**GOOD, "extra_fields": [{"name": "rank", "description": "the rank", "values": ["Apprentice", "Keeper"]}]})
        kb = harbour_kb()
        generate_book(self.workdir, kb, kb)
        stored = json.loads((self.workdir / "book.json").read_text(encoding="utf-8"))["extra_fields"]
        self.assertEqual(stored, {"guild_rank": {"description": "the character's rank and lamp, written as 'Rank, Lamp'",
                                                 "values": ["Apprentice", "Keeper"]}})

    def test_a_type_described_as_a_kind_of_person_is_rejected_before_any_entries_exist(self):
        reply = {**GOOD, "power_types": [{"type": "mutant", "description": "A person whose body was warped by an elixir"}]}
        self.assertIn('power type "mutant" is described as a kind of person', book_problems(reply, Knowledge()))
        self.assertIsNone(book_problems(GOOD, Knowledge()))


    def test_a_novel_without_powers_is_asked_what_its_fan_wiki_tracks_and_keeps_that_field(self):
        ordinary = {"power_system": "Characters are ranked by the titles of the harbour gentry.", "power_types": [],
                    "extra_fields": [{"name": "title", "description": "the character's title as the text gives it",
                                      "values": ["Harbourmaster", "Lady of the Quay"]}],
                    "power_keywords": ["harbourmaster", "lady", "title"], "timeline_kind": "linear", "timeline_note": "In order."}
        write_json(self.workdir / "script.json", {"replies": [
            {"purpose": "book", "contains": "never the only one: a fan wiki may track a character's cultivation stage or power class, "
                                            "but also a noble title or social rank", "reply": ordinary}]})
        generate_book(self.workdir, Knowledge(), Knowledge())
        book = load_book(self.workdir)
        self.assertEqual((book["power_types"], book["field_values"]), ({}, {"title": ["Harbourmaster", "Lady of the Quay"]}))
        self.assertEqual(book["power_keywords"], ["harbourmaster", "lady", "title"])

    def test_an_extra_field_with_no_keywords_to_find_it_is_rejected(self):
        reply = {**GOOD, "power_keywords": []}
        self.assertIn("power_keywords is empty", book_problems(reply, Knowledge()))
        self.assertIsNone(book_problems({**reply, "extra_fields": []}, Knowledge()))

    def test_an_extra_field_that_joins_a_general_field_to_another_fact_is_rejected(self):
        reply = {**GOOD, "extra_fields": [{"name": "guild rank or affiliation", "description": "the rank, or else the guild"}]}
        self.assertIn('extra field "guild rank or affiliation" joins the general field "affiliation"', book_problems(reply, Knowledge()))
    def test_an_extra_field_whose_values_are_forms_of_address_is_rejected(self):
        address = {**GOOD, "extra_fields": [{"name": "social title", "description": "how the character is addressed",
                                             "values": ["Mr.", "Mrs.", "Miss", "Dr.", "Sir"]}]}
        self.assertIn('extra field "social title" lists forms of address', book_problems(address, Knowledge()))
        ranks = {**GOOD, "extra_fields": [{"name": "title", "description": "the noble title", "values": ["Sir", "Baron", "Count"]}]}
        self.assertIsNone(book_problems(ranks, Knowledge()))


if __name__ == "__main__":
    unittest.main()
