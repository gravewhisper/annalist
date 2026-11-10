import json
import unittest

from annalist.files import read_json, write_json
from annalist.review import CHECKS, load_run, relation_rejections, review, review_markdown
from tests.test_pipeline import MiniBook, mini_script


def obs(value, chapter, quote, timeline="main"):
    return {"value": value, "chapter": chapter, "quotes": [quote], "asserted_by": "narrator", "quote_ok": True,
            "quote_ratios": [1.0], "timeline": timeline, "support": "supported"}


def profile(status=(), extra=None):
    return {"fields": {"status": list(status)}, "extra": extra or {}, "lists": {}}


class ReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBook(mini_script())
        cls.book.read(5)
        workdir = cls.book.workdir
        settings = read_json(workdir / "book.json", {})
        write_json(workdir / "book.json", {**settings, "power_types": {"relic": "an object holding old harbour magic"},
                                           "extra_fields": {"guild_rank": {"description": "rank in the Lamplighters' Guild",
                                                                           "values": ["Apprentice", "Keeper", "Master"]}}})
        write_json(workdir / "types.json", {"entities": [{"name": "Odile Marr", "from": "character", "to": "relic", "source": "llm"}]})
        write_json(workdir / "merges.json", {"pairs": [{"a": "Captain Fenn", "b": "Bram Ostrow", "type": "character", "rules": [],
                                                        "same": False, "canonical": "", "reason": "", "source": "llm"},
                                                       {"a": "Salt Ledger", "b": "lamp room key", "type": "artifact", "rules": [],
                                                        "same": True, "canonical": "Salt Ledger",
                                                        "reason": "They probably name the same Guild record.", "source": "llm"}]})
        write_json(workdir / "profiles.json", {"characters": {
            "Ines Varro": profile(extra={"guild_rank": [obs("Keeper", 5, "Ines lit the harbour lamp")]}),
            "Sabine Oake": profile([obs("dead", 3, "Sabine lay still")]),
            "Bram Ostrow": profile([obs("dead", 2, "Bram lay still", "gannet-night")],
                                   {"guild_rank": [obs("Apprentice", 1, "Bram was an apprentice of the Guild")]}),
            "Tomas Hale": profile([obs("dead", 3, "Tomas lay still")], {"guild_rank": [obs("Keeper", 1, "Tomas was the keeper")]}),
        }})
        last = workdir / "chapters" / "0005.txt"
        last.write_text(last.read_text(encoding="utf-8") + "\nThis eBook is for the use of anyone anywhere.\n", encoding="utf-8")
        cls.report = {c["key"]: c["findings"] for c in review(workdir)["checks"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.tmp.cleanup()

    def test_main_characters_without_status_or_power_are_listed(self):
        missing = {f["character"]: f["missing"] for f in self.report["empty_fields"]}
        self.assertEqual(missing["Sabine Oake"], ["guild_rank"])
        self.assertEqual(missing["Livia Hale"], ["profile"])
        self.assertNotIn("Ines Varro", missing)
        self.assertNotIn("Tomas Hale", missing)

    def test_a_death_followed_by_speech_is_explained_only_by_a_timeline(self):
        found = {f["character"]: f for f in self.report["dead_then_alive"]}
        self.assertEqual((found["Sabine Oake"]["later"], found["Sabine Oake"]["explained_by"]), ("speaks", ""))
        self.assertEqual(found["Bram Ostrow"]["explained_by"], "the death is in flashback gannet-night")
        self.assertNotIn("Tomas Hale", found)

    def test_hedged_merges_and_power_types_holding_people_are_flagged(self):
        self.assertEqual([(f["a"], f["reasons"]) for f in self.report["merges"]],
                         [("Salt Ledger", ['hedged reason ("probably")'])])
        self.assertEqual([(f["type"], f["people"]) for f in self.report["power_type_people"]], [("relic", ["Odile Marr"])])

    def test_profile_values_whose_quote_does_not_show_them(self):
        self.assertEqual([(f["character"], f["gap"]) for f in self.report["quote_gaps"]],
                         [("Ines Varro", "class Keeper not in the quote")])

    def test_license_text_in_a_chapter_is_found(self):
        self.assertEqual([(f["chapter"], f["hits"]) for f in self.report["front_matter"]], [(5, ["ebook"])])

    def test_relation_rejection_rates(self):
        self.assertEqual(self.report["relation_rejections"], [])
        run = load_run(self.book.workdir)
        run.states = [{"chapter": 7, "support": {"R1": {"verdict": "unsupported"}, "R2": {"verdict": "unsupported"},
                                                 "R3": {"verdict": "supported"}, "R4": {"verdict": "unsupported"}, "F1": {"verdict": "unsupported"}}},
                      {"chapter": 8, "support": {f"R{i}": {"verdict": "supported"} for i in range(1, 9)}}]
        self.assertEqual([f["text"] for f in relation_rejections(run)], ["ch 7: 3 of 4 relations rejected"])

    def test_the_markdown_has_a_section_per_check(self):
        report = {"workdir": str(self.book.workdir), "until": 5,
                  "checks": [{"key": c.key, "title": c.title, "findings": self.report[c.key]} for c in CHECKS]}
        markdown = review_markdown(report)
        for c in CHECKS:
            self.assertIn(f"## {c.title} ({len(self.report[c.key])})", markdown)
        self.assertEqual(json.loads(json.dumps(report))["until"], 5)


if __name__ == "__main__":
    unittest.main()
