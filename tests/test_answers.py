import copy
import json
import re
import unittest

from tests.test_build import MiniBuild, plan_rows, site_views
from tests.test_ending import ending_script, IMPLIED_QUOTE, MISSED_QUOTE, sections

KEEPER = {"question": "Who shares the keeping of the harbour lamp with Tomas?",
          "quote": "Tomas was the keeper of the harbour lamp and a sworn member of the Lamplighters’ Guild, and he was the only "
                   "person in Corvel Quay who still climbed the tower stairs without stopping for breath."}
KEEPER_QUOTE = "He kept the lamp for nine more years."
LEAD_QUOTE = ("Tomas had spoken with Odile Marr for an hour that morning in the back room of the harbour inn, and had come out grey "
              "in the face and would not say what she had told him.")
LEAD_TEXT = "Odile Marr told Tomas something about that night that shook him."
LIGHTS_ANSWER = "The lights were the master's grey Guild barge pulling away from the dark lamp tower."
PREMISE_WHY = "Tomas keeps the lamp alone; the book shows no second keeper."
VOLUMES = ("--volumes", "First=1-3,Second=4-5")


def answers_script(premise_quotes=None):
    script = ending_script()
    script["replies"] = [r for r in script["replies"] if r["purpose"] not in ("ending", "answers", "premise")]
    for row in script["replies"]:
        if row["purpose"] == "extract" and row["chapter"] == 1:
            row["reply"] = copy.deepcopy(row["reply"])
            row["reply"]["questions_raised"].append(KEEPER)
    script["replies"] += [
        {"purpose": "answers", "reply": {"results": [
            {"id": "Q0003-02", "answer": {"chapter": 4, "quote": MISSED_QUOTE,
                                          "answer": "She had recognised Tomas as her father and was too frightened to tell him."},
             "verdict": "left-open"},
            {"id": "Q0002-02", "lead": {"chapter": 3, "quote": LEAD_QUOTE, "text": LEAD_TEXT},
             "answer": {"chapter": 5, "quote": IMPLIED_QUOTE, "answer": LIGHTS_ANSWER}},
            {"id": "Q0001-04", "premise": {"explanation": PREMISE_WHY,
                                           "quotes": premise_quotes or [{"chapter": 2, "quote": KEEPER_QUOTE}]}},
            {"id": "Q0003-05", "verdict": "dropped-thread"},
            {"id": "Q0001-03"},
        ]}},
        {"purpose": "premise", "reply": {"verdict": "accept", "reason": "Chapter 2 shows Tomas keeping the lamp alone."}},
    ]
    return script


def site(book, *views):
    return site_views(book.workdir / "site" / "data" / "wiki.json", *views)


def questions(book):
    return {q["id"]: q for q in (json.loads(line) for line in (book.workdir / "questions.jsonl").read_text(encoding="utf-8").splitlines())}


def render(book, until):
    book.run_annalist("render", str(book.workdir), "--until", str(until))
    return (book.workdir / f"wiki-ch{until:04d}" / "open-questions.md").read_text(encoding="utf-8")


class VolumeAnswersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(answers_script())
        cls.first = cls.book.build(*VOLUMES)

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_an_unfinished_book_gets_an_answer_pass_at_each_volume_end(self):
        self.assertTrue(plan_rows(self.first.stdout)["ending"].startswith("skip: book.json does not mark the book complete"))
        self.assertEqual(plan_rows(self.first.stdout)["answers"], "run")
        self.assertEqual(sorted(self.book.json("answers.json")["boundaries"]), ["3", "5"])

    def test_a_missed_answer_is_resolved_from_its_own_chapter(self):
        q = questions(self.book)["Q0003-02"]
        self.assertEqual((q["status"], q["resolved_chapter"]), ("resolved", 4))
        self.assertIn("Q0003-02", sections(render(self.book, 3))["Open"])
        self.assertIn("Q0003-02", sections(render(self.book, 4))["Resolved"])
        out = site(self.book, "states@3", "states@4")
        self.assertEqual((out["states@3"]["Q0003-02"], out["states@4"]["Q0003-02"]), ("open", "resolved"))

    def test_a_volume_pass_never_looks_past_its_own_boundary(self):
        first = self.book.json("answers.json")["boundaries"]["3"]["questions"]
        self.assertTrue(first)
        self.assertTrue(all(n <= 3 for d in first.values() for n in d["candidates"]))
        self.assertNotEqual(first.get("Q0003-02", {}).get("verdict"), "answered")

    def test_a_volume_pass_never_judges_a_thread_left_open_or_dropped(self):
        self.assertFalse((self.book.workdir / "ending.json").exists())
        self.assertFalse([q["id"] for q in questions(self.book).values() if q.get("ending")])
        wiki = json.loads((self.book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        self.assertFalse([q["id"] for q in wiki["questions"] if q.get("ending")])
        self.assertEqual(questions(self.book)["Q0003-05"]["status"], "open")
        mysteries = site(self.book, "mysteries@5")["mysteries@5"]
        self.assertNotIn("Loose ends", mysteries)
        self.assertNotIn("End of book", mysteries)

    def test_a_lead_shows_from_its_chapter_and_the_answer_from_a_later_one(self):
        out = site(self.book, "states@2", "states@3", "states@4", "states@5", "mysteries@3?m=partial", "mysteries@5?m=resolved")
        self.assertEqual([out[f"states@{n}"]["Q0002-02"] for n in (2, 3, 4, 5)], ["open", "partial", "partial", "resolved"])
        self.assertIn("told Tomas something about that night that shook him", out["mysteries@3?m=partial"])
        self.assertIn("Tomas had spoken with Odile Marr", out["mysteries@3?m=partial"])
        self.assertNotIn("grey Guild barge pulling away from the dark lamp tower", out["mysteries@3?m=partial"])
        self.assertIn("grey Guild barge pulling away from the dark lamp tower", out["mysteries@5?m=resolved"])
        wiki = json.loads((self.book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        lights = next(q for q in wiki["questions"] if q["id"] == "Q0002-02")
        self.assertEqual(lights["leads"], [{"chapter": 3, "text": LEAD_TEXT, "quote": LEAD_QUOTE}])
        self.assertEqual((lights["resolved"]["chapter"], lights["resolved"]["shown"]), (5, 5))
        threads = (self.book.workdir / "wiki" / "volumes" / "first-threads.md").read_text(encoding="utf-8")
        self.assertIn(f"*Lead from ch [3](../../chapters/0003.txt):* {LEAD_TEXT}", threads)

    def test_a_false_premise_shows_only_from_its_chapter_with_its_quotes(self):
        out = site(self.book, "states@1", "states@2", "mysteries@1", "mysteries@2?m=resolved", "home@2")
        self.assertEqual((out["states@1"]["Q0001-04"], out["states@2"]["Q0001-04"]), ("open", "premise-false"))
        self.assertNotIn("Premise does not hold", out["mysteries@1"])
        self.assertNotIn(PREMISE_WHY, out["mysteries@1"])
        self.assertIn("Premise does not hold", out["mysteries@2?m=resolved"])
        self.assertIn(PREMISE_WHY, out["mysteries@2?m=resolved"])
        self.assertIn(KEEPER_QUOTE, out["mysteries@2?m=resolved"])
        stat = lambda html, label: int(re.search(rf"<b>(\d+)</b>{label}", html).group(1))
        states = list(site(self.book, "states@2")["states@2"].values())
        self.assertEqual(stat(out["home@2"], "open mysteries"), states.count("open"))
        self.assertEqual(stat(out["home@2"], "solved"), states.count("resolved") + states.count("premise-false"))
        self.assertIn("Q0001-04", sections(render(self.book, 1))["Open"])
        at_two = sections(render(self.book, 2))
        self.assertEqual(at_two["Premise does not hold"], ["Q0001-04"])
        self.assertNotIn("Q0001-04", at_two["Open"])
        self.assertNotIn("Q0001-04", [q["id"] for q in questions(self.book).values() if q["status"] in ("open", "partial")])

    def test_a_rebuild_asks_nothing_again(self):
        calls = len(self.book.calls())
        self.book.edit_code("answers.py", "\ndef cmd_answers(", "\nRULES = 2\n\n\ndef cmd_answers(")
        rebuilt = self.book.build(*VOLUMES)
        self.assertEqual(plan_rows(rebuilt.stdout)["answers"], "run: code changed")
        self.assertEqual(len(self.book.calls()), calls)
        self.assertEqual(questions(self.book)["Q0003-02"]["status"], "resolved")


class UnverifiedPremiseTest(unittest.TestCase):
    def test_a_premise_whose_quote_is_not_in_the_text_is_dropped(self):
        book = MiniBuild(answers_script([{"chapter": 2, "quote": "Tomas had no partner at the lamp and never wanted one."}]))
        try:
            book.build()
            self.assertEqual(questions(book)["Q0001-04"]["status"], "open")
            self.assertEqual(book.calls("premise"), [])
            self.assertEqual(site(book, "states@5")["states@5"]["Q0001-04"], "open")
        finally:
            book.close()


class RejectedPremiseTest(unittest.TestCase):
    def test_a_premise_the_confirmation_rejects_leaves_the_question_open(self):
        script = answers_script()
        script["replies"] = [r for r in script["replies"] if r["purpose"] != "premise"]
        script["replies"].append({"purpose": "premise", "reply": {"verdict": "reject", "reason": "Nine years alone does not rule out a partner."}})
        book = MiniBuild(script)
        try:
            book.build()
            self.assertEqual(len(book.calls("premise")), 1)
            self.assertEqual(questions(book)["Q0001-04"]["status"], "open")
            self.assertEqual(site(book, "states@5")["states@5"]["Q0001-04"], "open")
        finally:
            book.close()


KEY = {"question": "What did the Guild record in the Salt Ledger about the key to the lamp room on the night of the wreck?",
       "quote": "The Guild wants it back, and Master Oake has promised me the keepership of the lamp if I bring it to her."}
KEY_QUOTE = "And in the narrow column at the edge of the page: Master's key drawn at six o'clock, S. Oake."


class LaterPassageTest(unittest.TestCase):
    def test_a_volume_pass_shows_the_chapters_after_a_question_and_not_the_ones_before_it(self):
        script = answers_script()
        for row in script["replies"]:
            if row["purpose"] == "extract" and row["chapter"] == 4:
                row["reply"] = copy.deepcopy(row["reply"])
                row["reply"]["questions_raised"].append(KEY)
        script["replies"].insert(0, {"purpose": "answers", "contains": f'{KEY["quote"]}"\nPassages:\n[chapter 4]', "reply": {"results": [
            {"id": "Q0004-01", "answer": {"chapter": 5, "quote": KEY_QUOTE, "answer": "The master's key was drawn at six o'clock by S. Oake."}}]}})
        book = MiniBuild(script)
        try:
            book.build()
            q = questions(book)["Q0004-01"]
            self.assertEqual(q["question"], KEY["question"])
            self.assertEqual((q["status"], q.get("resolved_chapter")), ("resolved", 5))
            self.assertEqual(book.json("answers.json")["boundaries"]["5"]["questions"]["Q0004-01"]["candidates"], [4, 5])
        finally:
            book.close()

    def test_a_volume_pass_shows_the_rest_of_the_chapter_that_raised_a_question(self):
        script = answers_script()
        for row in script["replies"]:
            if row["purpose"] == "extract" and row["chapter"] == 4:
                row["reply"] = copy.deepcopy(row["reply"])
                row["reply"]["questions_raised"].append(BRAM)
        script["replies"].insert(0, {"purpose": "answers", "contains": BRAM_QUOTE, "reply": {"results": [
            {"id": "Q0004-01", "answer": {"chapter": 4, "quote": BRAM_QUOTE, "answer": "Bram took the brass key from Ines by force."}}]}})
        book = MiniBuild(script)
        try:
            book.build()
            q = questions(book)["Q0004-01"]
            self.assertEqual((q["status"], q.get("resolved_chapter")), ("resolved", 4))
        finally:
            book.close()


BRAM = {"question": "Will Bram get the key from Ines, as he demands?",
        "quote": "Give it to me and nobody needs to get hurt."}
BRAM_QUOTE = "He stood for a moment with the brass key in his hand, breathing hard."


class NotAMysteryTest(unittest.TestCase):
    def test_a_question_only_about_what_a_character_will_do_next_is_not_a_mystery(self):
        script = answers_script()
        for row in script["replies"]:
            if row["purpose"] == "extract" and row["chapter"] == 4:
                row["reply"] = copy.deepcopy(row["reply"])
                row["reply"]["questions_raised"].append(BRAM)
        script["replies"].insert(0, {"purpose": "mystery", "contains": BRAM["question"], "reply": {"questions": [
            {"id": "Q0004-01", "mystery": False}, {"id": "Q0002-02", "mystery": True}]}})
        book = MiniBuild(script)
        try:
            book.build(*VOLUMES)
            self.assertIs(book.json("tiers.json")["questions"]["Q0004-01"]["mystery"], False)
            self.assertNotIn("Q0004-01", book.json("answers.json")["boundaries"]["5"]["questions"])
            wiki = json.loads((book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
            self.assertNotIn("Q0004-01", [q["id"] for q in wiki["questions"]])
            self.assertIn("Q0002-02", [q["id"] for q in wiki["questions"]])
            self.assertNotIn(BRAM["question"], render(book, 5))
        finally:
            book.close()


RECOGNISED = "Livia knew Tomas for her father the moment he walked into her archive."


def rescripted(answers):
    script = answers_script()
    for row in script["replies"]:
        if row["purpose"] == "answers":
            row["reply"] = {"results": [r for r in row["reply"]["results"] if r["id"] not in answers] + list(answers.values())}
    return script


class StaleVerdictTest(unittest.TestCase):
    def test_a_settled_verdict_is_asked_again_once_the_rules_it_was_judged_under_change(self):
        book = MiniBuild(answers_script())
        try:
            book.build(*VOLUMES)
            self.assertEqual(book.json("answers.json")["boundaries"]["5"]["questions"]["Q0003-02"]["verdict"], "answered")
            book.edit_code("answers.py", "some left for later.", "some left for later, and a few rest on a false premise.")
            book.script(rescripted({"Q0003-02": {"id": "Q0003-02", "answer": {"chapter": 4, "quote": MISSED_QUOTE, "answer": RECOGNISED}}}))
            book.build(*VOLUMES)
            self.assertEqual(book.json("answers.json")["boundaries"]["5"]["questions"]["Q0003-02"]["answer"]["answer"], RECOGNISED)
            self.assertEqual(questions(book)["Q0003-02"]["status"], "resolved")
        finally:
            book.close()


class KeptLeadTest(unittest.TestCase):
    def test_a_checked_lead_survives_a_new_ask_that_gives_none(self):
        lead = {"id": "Q0002-02", "lead": {"chapter": 3, "quote": LEAD_QUOTE, "text": LEAD_TEXT}}
        book = MiniBuild(rescripted({"Q0002-02": lead}))
        try:
            book.build(*VOLUMES)
            book.edit_code("answers.py", "some left for later.", "some left for later, and a few rest on a false premise.")
            book.script(rescripted({"Q0002-02": {"id": "Q0002-02"}}))
            book.build(*VOLUMES)
            leads = [d.get("lead", {}).get("text") for b in book.json("answers.json")["boundaries"].values()
                     for k, d in b["questions"].items() if k == "Q0002-02"]
            self.assertIn(LEAD_TEXT, leads)
            wiki = json.loads((book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
            self.assertEqual(next(q for q in wiki["questions"] if q["id"] == "Q0002-02")["leads"],
                             [{"chapter": 3, "text": LEAD_TEXT, "quote": LEAD_QUOTE}])
        finally:
            book.close()


class PremiseOverAnswerTest(unittest.TestCase):
    def test_a_reply_with_both_an_answer_and_a_false_premise_records_the_premise(self):
        book = MiniBuild(rescripted({"Q0001-04": {
            "id": "Q0001-04", "answer": {"chapter": 2, "quote": KEEPER_QUOTE, "answer": "Nobody; Tomas keeps the lamp alone."},
            "premise": {"explanation": PREMISE_WHY, "quotes": [{"chapter": 2, "quote": KEEPER_QUOTE}]}}}))
        try:
            book.build(*VOLUMES)
            decision = book.json("answers.json")["boundaries"]["3"]["questions"]["Q0001-04"]
            self.assertEqual((decision["verdict"], decision.get("premise", {}).get("explanation")), ("premise-false", PREMISE_WHY))
            self.assertEqual(questions(book)["Q0001-04"]["status"], "premise-false")
            self.assertEqual(site(book, "states@2")["states@2"]["Q0001-04"], "premise-false")
        finally:
            book.close()


def sweep_script(answers):
    script = ending_script()
    script["replies"] = [r for r in script["replies"] if r["purpose"] != "sweep"]
    script["replies"].append({"purpose": "sweep", "reply": {"answers": answers}})
    return script


UNANSWERED = [{"id": q, "answered": False} for q in ("Q0001-03", "Q0002-02", "Q0003-02", "Q0003-05")]


class SweepFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.book = MiniBuild(sweep_script(UNANSWERED))
        self.book.build()
        self.decisions = self.book.json("sweep.json")["questions"]
        self.calls = len(self.book.calls("sweep"))

    def tearDown(self):
        self.book.close()

    def test_an_unanswered_question_is_not_asked_again_when_nothing_it_was_shown_changed(self):
        self.assertEqual({k: d["verdict"] for k, d in self.decisions.items()},
                         {"Q0001-03": "unanswered", "Q0002-02": "unanswered", "Q0003-02": "unanswered", "Q0003-05": "unanswered"})
        self.book.edit_code("sweep.py", "\ndef sweep_item(", "\nRULES = 2\n\n\ndef sweep_item(")
        rebuilt = self.book.build()
        self.assertEqual(plan_rows(rebuilt.stdout)["sweep"], "run: code changed")
        self.assertEqual(len(self.book.calls("sweep")), self.calls)
        self.assertEqual(self.book.json("sweep.json")["questions"], self.decisions)

    def test_an_unanswered_question_is_asked_again_when_its_passages_change(self):
        path = self.book.workdir / "state" / "0003.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["extraction"]["synopsis"] += " Ines keeps the brass key on a cord at her neck."
        path.write_text(json.dumps(state), encoding="utf-8")
        self.book.script(sweep_script([
            {"id": "Q0001-03", "answered": True, "chapter": 5, "quote": IMPLIED_QUOTE,
             "answer": "She saw the master's grey Guild barge leaving the dark lamp tower."},
            {"id": "Q0003-02", "answered": True, "chapter": 4, "quote": MISSED_QUOTE,
             "answer": "She had recognised Tomas as her father."}]))
        self.book.build()
        self.assertEqual(len(self.book.calls("sweep")), self.calls + 1)
        decisions = self.book.json("sweep.json")["questions"]
        self.assertEqual(decisions["Q0001-03"]["verdict"], "accept")
        self.assertEqual(decisions["Q0003-02"], self.decisions["Q0003-02"])
        self.assertEqual(questions(self.book)["Q0003-02"]["status"], "open")


if __name__ == "__main__":
    unittest.main()
