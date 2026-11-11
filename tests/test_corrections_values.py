import json
import re
import unittest

from tests.test_asof_leaks import visible_text
from tests.test_build import MiniBuild, build_script, site_views

KEPT = "knows the date of the wreck like a birthday"
WRONG = "learned her letters beside Bram"
INES = {
    "trivia": [{"value": KEPT, "chapter": 1, "quotes": ["Ines Varro knew the date of that night the way other girls knew their birthdays"],
                "asserted_by": "narrator"},
               {"value": WRONG, "chapter": 1, "quotes": ["they had learned their letters at the same bench and been beaten for the same broken window"],
                "asserted_by": "narrator"}],
    "personality_evidence": [{"value": "observant", "chapter": 1, "quotes": ["Ines had never seen his hands shake before."], "asserted_by": "narrator"},
                             {"value": "patient", "chapter": 3, "quotes": ["Ines waited an hour in the guest room, then went looking with a lantern."],
                              "asserted_by": "narrator"}],
}

CORRECTIONS = {"entries": [{"name": "Ines Varro", "drop": {"trivia": [{"chapter": 1, "value": "Learned her letters beside Bram"},
                                                                       {"chapter": 2, "value": KEPT}],
                                                            "personality_evidence": [{"chapter": 3, "value": "patient"}]}}]}


class DroppedValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = build_script()
        script["replies"].insert(0, {"purpose": "profile", "contains": 'about the character "Ines Varro"', "reply": INES})
        cls.book = MiniBuild(script)
        cls.book.build()
        cls.before = cls.page()
        cls.calls = len(cls.book.calls())
        (cls.book.workdir / "corrections.json").write_text(json.dumps(CORRECTIONS), encoding="utf-8")
        cls.rebuild = cls.book.build()
        cls.new_calls = cls.book.calls()[cls.calls:]
        cls.after = cls.page()

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    @classmethod
    def page(cls):
        wiki = cls.book.json("site/data/wiki.json")
        return next(e for e in wiki["entities"] if e["name"] == "Ines Varro")

    def values(self, page, key):
        return [o["value"] for o in page["profile"]["lists"].get(key, [])]

    def test_a_removed_list_value_is_gone_and_the_others_stay(self):
        self.assertEqual(self.values(self.before, "trivia"), [KEPT, WRONG])
        self.assertEqual(self.values(self.after, "trivia"), [KEPT])
        self.assertEqual(self.values(self.after, "personality_evidence"), ["observant"])
        view = f"{self.after['id']}@5"
        shown = visible_text(site_views(self.book.workdir / "site" / "data" / "wiki.json", view)[view]).lower()
        self.assertIn(KEPT, shown)
        self.assertNotIn("learned her letters", shown)
        self.assertNotIn("patient", shown)

    def test_only_the_personality_written_from_the_removed_evidence_is_asked_again(self):
        self.assertEqual(re.findall(r"^== (\w+)$", self.rebuild.stdout, re.M), ["render", "export"])
        self.assertEqual({c["purpose"] for c in self.new_calls}, {"personality"})

    def test_a_drop_that_matches_nothing_is_skipped_with_a_warning(self):
        self.assertIn(f"warning: correction Ines Varro.drop trivia ch2 {KEPT!r} matches no value, skipped", self.rebuild.stdout)


if __name__ == "__main__":
    unittest.main()
