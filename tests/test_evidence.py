import json
import re
import tempfile
import unittest
from pathlib import Path

from annalist.evidence import affiliations
from annalist.state import Knowledge

from annalist.files import write_json
from tests.test_pipeline import MiniBook, mini_script

CLASSES = ["Apprentice", "Keeper", "Master"]
EMPTY = {k: [] for k in ("full_name", "sex", "age", "birthdate", "height", "marital_status", "status", "affiliation",
                         "appearance", "personality_evidence", "trivia")}
FLASHBACK_ALIVE = {"value": "alive", "chapter": 2, "timeline": "gannet-night", "asserted_by": "narrator",
                   "quotes": ["Tomas lit it himself at half past four, trimmed the wick, wrote the hour in the Salt Ledger, "
                              "and went down to the quay to watch for a red-and-white sail."]}
DEATH = {"died": True, "chapter": 3, "circumstances": "Tomas was found at the foot of the abbey stair.",
         "quotes": ["They found Tomas himself at the bottom, three hundred steps down, where the stair turned on the last "
                    "landing above the beach. He had been dead for some time."]}
FLASHBACK_DEATH = {"died": True, "chapter": 2, "timeline": "gannet-night", "circumstances": "Livia was lost in the wreck.",
                   "quotes": ["Livia Hale was not among the living or the dead."]}
APPRENTICE = {"value": "Apprentice", "chapter": 1, "asserted_by": "narrator",
              "quotes": ["Ines was nineteen and had been Tomas’s apprentice for six years."]}


MASTER = {"value": "Master (Lamplighters’ Guild)", "chapter": 1, "asserted_by": "narrator",
          "quotes": ["Sabine Oake had been master of the Lamplighters’ Guild for eleven years."]}


def evidence_script():
    script = mini_script()
    script["replies"] += [
        {"purpose": "profile", "reply": {**EMPTY, "status": [FLASHBACK_ALIVE], "extra": {"guild_rank": []}}},
        {"purpose": "profile-support", "reply": {"verdicts": [{"id": "O1", "verdict": "supported"}]}},
        {"purpose": "profile-field", "reply": {"observations": []}},
        {"purpose": "profile-field", "contains": 'character "Ines Varro"', "reply": {"observations": [APPRENTICE]}},
        {"purpose": "profile-field", "contains": 'character "Sabine Oake"', "reply": {"observations": [MASTER]}},
        {"purpose": "death", "reply": {"died": False}},
        {"purpose": "death", "contains": '"Tomas Hale" die in chapter 3', "reply": DEATH},
        {"purpose": "death", "contains": '"Livia Hale" die in chapter 4', "reply": FLASHBACK_DEATH},
        {"purpose": "summary", "reply": {"summary": "A figure of Corvel Quay."}},
        {"purpose": "personality", "reply": {"paragraph": "Careful (ch 1)."}},
        {"purpose": "arcs", "reply": {"arcs": [{"name": "The Missing Page", "start": 1}]}},
        {"purpose": "arc", "reply": {"summary": "Ines follows the cut page of the Salt Ledger."}},
        {"purpose": "volume", "reply": {"overview": "The keepers of Corvel Quay.", "character_development": []}},
        {"purpose": "events", "reply": {"events": []}},
    ]
    return script


def infobox(book, until, page):
    text = (book.workdir / f"wiki-ch{until:04d}" / "character" / f"{page}.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| \*\*(.+?)\*\* \| (.+?) \|$", text, re.M))
    return {k: re.sub(r"\[ch (\d+)\]\([^)]*\)", r"ch \1", v) for k, v in rows.items()}


class InfoboxEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBook(evidence_script())
        cls.book.read(5)
        settings = json.loads((cls.book.workdir / "book.json").read_text(encoding="utf-8"))
        write_json(cls.book.workdir / "book.json", {**settings, "extra_fields": {
            "guild_rank": {"description": "the character's rank in the Lamplighters' Guild", "values": CLASSES}}})
        cls.book.run("profile", str(cls.book.workdir), "--character", "Tomas Hale", "--character", "Ines Varro",
                     "--character", "Bram Ostrow", "--character", "Sabine Oake", "--character", "Livia Hale")
        for until in (2, 5):
            cls.book.run("render", str(cls.book.workdir), "--until", str(until))

    @classmethod
    def tearDownClass(cls):
        cls.book.tmp.cleanup()

    def test_a_verified_death_sets_the_status_though_the_profile_only_saw_him_alive_in_a_flashback(self):
        self.assertEqual(infobox(self.book, 5, "tomas-hale")["Status"], "Dead (ch 3)")

    def test_before_the_death_chapter_the_status_is_not_dead_and_the_flashback_does_not_set_it(self):
        self.assertNotIn("Dead", infobox(self.book, 2, "tomas-hale").get("Status", ""))
        self.assertNotIn("(ch 2)", infobox(self.book, 2, "tomas-hale").get("Status", ""))

    def test_a_death_the_death_reading_places_in_a_flashback_does_not_set_the_present_status(self):
        self.assertNotIn("Dead", infobox(self.book, 5, "livia-hale").get("Status", ""))

    def test_affiliation_comes_from_a_member_of_relation_when_the_profile_has_none(self):
        self.assertEqual(infobox(self.book, 5, "bram-ostrow")["Affiliation"], "Lamplighters’ Guild (ch 1)")

    def test_a_class_stated_in_a_fact_fills_the_class_field_when_the_profile_has_none(self):
        self.assertEqual(infobox(self.book, 5, "tomas-hale")["Guild rank"], "Keeper (ch 1)")

    def test_a_focused_field_reading_fills_a_class_no_fact_states(self):
        self.assertEqual(infobox(self.book, 5, "ines-varro")["Guild rank"], "Apprentice (ch 1)")

    def test_a_more_specific_reading_of_the_same_chapter_replaces_the_bare_class(self):
        self.assertEqual(infobox(self.book, 5, "sabine-oake")["Guild rank"], "Master (Lamplighters’ Guild) (ch 1)")

    def test_the_volume_lists_the_verified_death(self):
        self.book.run("volume", str(self.book.workdir), "--name", "The Salt Ledger", "--from", "1", "--to", "5")
        volume = json.loads((self.book.workdir / "volumes" / "the-salt-ledger.json").read_text(encoding="utf-8"))
        self.assertEqual([(d["name"], d["chapter"]) for d in volume["deaths"]], [("Tomas Hale", 3)])


class RelationAffiliationTest(unittest.TestCase):
    def test_a_member_of_relation_whose_quote_never_names_the_group_is_not_an_affiliation(self):
        kb = Knowledge()
        for name, etype in (("Corvin Ash", "character"), ("Wren Tally", "character"), ("Ironvein Crew", "organization"),
                            ("Seventh Bell", "organization")):
            kb.upsert_entity({"name": name, "type": etype}, 1)
        kb.relations += [
            {"chapter": 1, "source": "Corvin Ash", "target": "Ironvein Crew", "type": "member of", "status": "stated",
             "quotes": ["Only his lieutenants might know: Corvin Ash, Pell, and the twins."]},
            {"chapter": 1, "source": "Wren Tally", "target": "Seventh Bell", "type": "member of", "status": "stated",
             "quotes": ["Her brother blamed her for joining the Seventh Bell."]}]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            (Path(tmp) / "chapters" / "0001.txt").write_text(
                "Only his lieutenants might know: Corvin Ash, Pell, and the twins. "
                "Her brother blamed her for joining the Seventh Bell.\n", encoding="utf-8")
            self.assertEqual(affiliations(tmp, kb, "Corvin Ash"), [])
            self.assertEqual([o["value"] for o in affiliations(tmp, kb, "Wren Tally")], ["Seventh Bell"])


if __name__ == "__main__":
    unittest.main()
