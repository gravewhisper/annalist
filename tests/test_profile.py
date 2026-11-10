import json
import tempfile
import unittest
from pathlib import Path

from annalist.files import write_json
from annalist.profile import keep_specific, quote_naming_class
from tests.test_pipeline import MiniBook, mini_script

CLASSES = ("Apprentice", "Keeper", "Master")
OPENING = ("Ines was nineteen and had been Tomas's apprentice for six years. Tomas was the keeper of the harbour lamp and a sworn "
           "member of the Lamplighters' Guild, and he was the only person in Corvel Quay who still climbed the tower stairs "
           "without stopping for breath. He was sixty-one.")
LONE_QUOTE = "he was the only person in Corvel Quay who still climbed the tower stairs without stopping for breath."
NAMING_QUOTE = ("Tomas was the keeper of the harbour lamp and a sworn member of the Lamplighters' Guild, and he was the only person "
                "in Corvel Quay who still climbed the tower stairs without stopping for breath.")


def observation(value, quote, support="supported", chapter=1):
    return {"value": value, "chapter": chapter, "quotes": [quote], "asserted_by": "narrator", "quote_ok": True,
            "quote_ratios": [1.0], "timeline": "main", "support": support}


class ClassQuoteTest(unittest.TestCase):
    def test_a_quote_that_omits_the_class_named_in_the_value_widens_to_the_sentence_that_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            (Path(tmp) / "chapters" / "0001.txt").write_text(OPENING + "\n", encoding="utf-8")
            widened = quote_naming_class(tmp, observation("Keeper (harbour lamp)", LONE_QUOTE), CLASSES)
            untouched = quote_naming_class(tmp, observation("climbs without stopping", LONE_QUOTE), CLASSES)
        self.assertEqual(widened["quotes"], [NAMING_QUOTE])
        self.assertEqual(widened["quote_widened_from"], LONE_QUOTE)
        self.assertEqual(untouched["quotes"], [LONE_QUOTE])


class KeepSpecificTest(unittest.TestCase):
    def rerun(self, old, new, classes=CLASSES):
        profile = {"fields": {}, "extra": {"guild_rank": [new]}, "lists": {}}
        previous = {"fields": {}, "extra": {"guild_rank": [old]}, "lists": {}}
        return keep_specific(profile, previous, {"guild_rank": classes})["extra"]["guild_rank"][0]

    def test_a_vaguer_rerun_value_does_not_replace_a_verified_specific_one(self):
        kept = self.rerun(observation("Keeper (harbour lamp)", NAMING_QUOTE), observation("Keeper", NAMING_QUOTE))
        self.assertEqual(kept["value"], "Keeper (harbour lamp)")
        self.assertEqual(kept["replaced"], [{"value": "Keeper", "support": "supported"}])

    def test_a_value_naming_the_class_beats_one_that_does_not(self):
        kept = self.rerun(observation("Keeper (harbour lamp)", NAMING_QUOTE), observation("climbs the stairs", LONE_QUOTE, "trim"))
        self.assertEqual(kept["value"], "Keeper (harbour lamp)")

    def test_a_more_specific_rerun_value_or_an_unverified_old_one_gives_way(self):
        self.assertEqual(self.rerun(observation("Keeper", NAMING_QUOTE), observation("Keeper (harbour lamp)", NAMING_QUOTE))["value"],
                         "Keeper (harbour lamp)")
        self.assertEqual(self.rerun(observation("Keeper (harbour lamp)", NAMING_QUOTE, "unaudited"), observation("Keeper", NAMING_QUOTE))["value"],
                         "Keeper")


def profile_reply(value, quote):
    empty = {k: [] for k in ("full_name", "sex", "age", "birthdate", "height", "marital_status", "status", "affiliation",
                             "appearance", "personality_evidence", "trivia")}
    return {**empty, "extra": {"guild_rank": [{"value": value, "chapter": 1, "quotes": [quote], "asserted_by": "narrator"}]}}


class ProfileRerunTest(unittest.TestCase):
    def test_a_forced_rerun_with_a_vaguer_reply_keeps_the_verified_class_value(self):
        book = MiniBook(mini_script())
        self.addCleanup(book.tmp.cleanup)
        book.read(5)
        settings = json.loads((book.workdir / "book.json").read_text(encoding="utf-8"))
        write_json(book.workdir / "book.json", {**settings, "extra_fields": {
            "guild_rank": {"description": "the character's rank in the Lamplighters' Guild", "values": list(CLASSES)}}})
        supported = {"verdicts": [{"id": "O1", "verdict": "supported"}]}

        def profile(value):
            write_json(book.workdir / "script.json", {"replies": [
                {"purpose": "profile", "reply": profile_reply(value, LONE_QUOTE)},
                {"purpose": "profile-support", "reply": supported},
                {"purpose": "profile-field", "reply": {"observations": []}},
                {"purpose": "death", "reply": {"died": False}}]})
            for cached in (book.workdir / "cache").glob("profile*.json"):
                cached.unlink()
            book.run("profile", str(book.workdir), "--character", "Tomas Hale")
            data = json.loads((book.workdir / "profiles.json").read_text(encoding="utf-8"))
            return data["characters"]["Tomas Hale"]["extra"]["guild_rank"]

        first = profile("Keeper (harbour lamp)")
        self.assertEqual([(o["value"], [q.replace("’", "'") for q in o["quotes"]]) for o in first],
                         [("Keeper (harbour lamp)", [NAMING_QUOTE])])
        second = profile("Keeper")
        self.assertEqual([o["value"] for o in second], ["Keeper (harbour lamp)"])
        self.assertEqual(second[0]["replaced"], [{"value": "Keeper", "support": "supported"}])


class ProfileValueShapeTest(unittest.TestCase):
    def profile(self, full_name, rank, verdicts):
        book = MiniBook(mini_script())
        self.addCleanup(book.tmp.cleanup)
        book.read(5)
        settings = json.loads((book.workdir / "book.json").read_text(encoding="utf-8"))
        write_json(book.workdir / "book.json", {**settings, "extra_fields": {
            "guild_rank": {"description": "the character's rank in the Lamplighters' Guild", "values": list(CLASSES)}}})
        reply = profile_reply(rank, NAMING_QUOTE)
        reply["full_name"] = [{"value": full_name, "chapter": 1, "quotes": [NAMING_QUOTE], "asserted_by": "narrator"}]
        write_json(book.workdir / "script.json", {"replies": [
            {"purpose": "profile", "reply": reply},
            {"purpose": "profile-support", "reply": {"verdicts": verdicts}},
            {"purpose": "profile-field", "reply": {"observations": []}},
            {"purpose": "death", "reply": {"died": False}}]})
        book.run("profile", str(book.workdir), "--character", "Tomas Hale")
        data = json.loads((book.workdir / "profiles.json").read_text(encoding="utf-8"))["characters"]["Tomas Hale"]
        return [o["value"] for o in data["fields"]["full_name"]], [o["value"] for o in data["extra"]["guild_rank"]]

    def test_a_name_field_keeps_only_the_name_and_a_value_drops_the_subjects_own_name(self):
        supported = [{"id": "O1", "verdict": "supported"}, {"id": "O2", "verdict": "supported"}]
        self.assertEqual(self.profile("Tomas Hale, keeper of the harbour lamp", "Tomas Hale: Keeper (harbour lamp)", supported),
                         (["Tomas Hale"], ["Keeper (harbour lamp)"]))

    def test_a_name_field_keeps_initials(self):
        supported = [{"id": "O1", "verdict": "supported"}, {"id": "O2", "verdict": "supported"}]
        self.assertEqual(self.profile("T. R. Hale, keeper of the harbour lamp", "Keeper", supported)[0], ["T. R. Hale"])

    def test_a_name_field_with_no_name_in_it_is_dropped(self):
        self.assertEqual(self.profile("the keeper of the lamp", "Keeper", [{"id": "O1", "verdict": "supported"}]), ([], ["Keeper"]))

    def test_a_trim_may_only_remove_words_from_a_value(self):
        grows = [{"id": "O1", "verdict": "trim", "claim": "Tomas Hale, a sworn member of the Lamplighters' Guild"},
                 {"id": "O2", "verdict": "trim", "claim": "Tomas Hale: Keeper of the harbour lamp, sixty-one, sworn member"}]
        self.assertEqual(self.profile("Tomas Hale", "Keeper (harbour lamp)", grows), (["Tomas Hale"], ["Keeper (harbour lamp)"]))
        shrinks = [{"id": "O1", "verdict": "supported"}, {"id": "O2", "verdict": "trim", "claim": "Tomas Hale: Keeper"}]
        self.assertEqual(self.profile("Tomas Hale", "Keeper (harbour lamp)", shrinks), (["Tomas Hale"], ["Keeper"]))


if __name__ == "__main__":
    unittest.main()
