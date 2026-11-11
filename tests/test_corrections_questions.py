import json
import re
import unittest

from tests.test_asof_leaks import visible_text
from tests.test_build import MiniBuild, build_script, site_views

OPEN = "Why was Bram on the beach below the stair the night Tomas died?"
DISMISSED = "What was Sister Wren about to say to Tomas in the archive?"
ANSWER = "Bram followed Tomas out on the master's orders."


def open_script():
    script = build_script()
    for r in script["replies"]:
        if r["purpose"] == "extract" and r["chapter"] == 5:
            r["reply"]["questions_resolved"] = [q for q in r["reply"]["questions_resolved"] if q["id"] != "Q0003-04"]
    return script


CORRECTIONS = {"questions": [
    {"id": "Q0003-04", "chapter": 5, "answer": ANSWER, "quotes": ["It was Bram who broke."]},
    {"question": DISMISSED, "dismiss": True},
    {"id": "Q0003-01", "chapter": 5, "answer": "Pushed.", "quotes": ["A line the book never has."]},
    {"id": "Q0009-01", "dismiss": True},
]}


class QuestionCorrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(open_script())
        cls.book.build()
        cls.sweeps = len(cls.book.calls("sweep"))
        cls.calls = len(cls.book.calls())
        (cls.book.workdir / "corrections.json").write_text(json.dumps(CORRECTIONS), encoding="utf-8")
        cls.rebuild = cls.book.build()
        cls.new_calls = cls.book.calls()[cls.calls:]
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def views(self, *names):
        out = site_views(self.book.workdir / "site" / "data" / "wiki.json", *names)
        return {v: visible_text(html) for v, html in out.items()}

    def test_the_question_stages_rerun_and_ask_nothing_about_a_settled_question(self):
        self.assertGreater(self.sweeps, 0)
        self.assertEqual(re.findall(r"^== (\w+)$", self.rebuild.stdout, re.M), ["sweep", "answers", "proofread", "render", "export"])
        self.assertEqual(self.new_calls, [])

    def test_an_answered_question_shows_resolved_from_its_chapter_and_not_before(self):
        q = next(q for q in self.wiki["questions"] if q["id"] == "Q0003-04")
        self.assertEqual((q["resolved"]["chapter"], q["resolved"]["shown"], q["resolved"]["answer"]), (5, 5, ANSWER))
        shown = self.views("mysteries@4", "mysteries@5", "chapter:5@5")
        self.assertIn(OPEN, shown["mysteries@4"])
        self.assertNotIn(ANSWER, shown["mysteries@4"])
        self.assertNotIn(OPEN, shown["mysteries@5"])
        self.assertIn(ANSWER, shown["chapter:5@5"])

    def test_a_dismissed_question_is_gone(self):
        self.assertNotIn(DISMISSED, json.dumps(self.wiki, ensure_ascii=False))
        shown = self.views(*(f"mysteries@{n}" for n in range(3, 6)), "chapter:3@5", "chapter:4@5")
        self.assertEqual([v for v, text in shown.items() if "about to say to Tomas" in text], [])

    def test_a_bad_quote_or_an_unknown_id_is_skipped_with_a_warning(self):
        self.assertIn("warning: correction Q0003-01 ch5 has no quote found in that chapter, skipped", self.rebuild.stdout)
        self.assertIn("warning: corrections.json names question 'Q0009-01', which matches no question, skipped", self.rebuild.stdout)
        self.assertNotEqual(next(q for q in self.wiki["questions"] if q["id"] == "Q0003-01")["resolved"]["answer"], "Pushed.")


if __name__ == "__main__":
    unittest.main()
