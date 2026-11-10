import copy
import json
import re
import shutil
import subprocess
import sys
import unittest

from tests.test_build import build_script, MiniBuild, plan_rows, ROOT

MISSED_QUOTE = ("When your Tomas walked into my archive three days ago I knew his face before he said a word, "
                "and I was so frightened I could not speak.")
IMPLIED_QUOTE = ("That night, when I came up out of the water with the line in my teeth, the first thing I saw was a grey "
                 "Guild barge pulling away from the foot of the lamp tower with no light in her.")
LIGHTS = {"question": "What were the lights on the water beyond the rocks, where no lights should be?",
          "quote": "From the gallery he could see lights on the water out beyond the rocks, where no lights should be, "
                   "and then he could not see them anymore."}
SCAR = {"question": "Where does the white scar across the back of Sister Wren's left hand come from?",
        "quote": "small and quick, with a white scar across the back of her left hand."}

ENDING_REPLY = {"results": [
    {"id": "Q0003-02", "answered": True, "chapter": 4, "quote": MISSED_QUOTE,
     "answer": "She had recognised Tomas as her father and was too frightened to tell him.",
     "verdict": "answered-implicitly", "quotes": [], "reason": "Chapter 4 says it outright."},
    {"id": "Q0001-03", "answered": False, "verdict": "answered-implicitly",
     "answer": "She saw the master's grey Guild barge leaving the dark lamp tower.",
     "quotes": [{"chapter": 5, "quote": IMPLIED_QUOTE}, {"chapter": 5, "quote": "Odile kept the barge's name in a locked tin."}],
     "reason": "The ending shows what she saw."},
    {"id": "Q0002-02", "answered": False, "verdict": "left-open", "quotes": [], "reason": "The ending never says whose lights they were."},
    {"id": "Q0003-05", "answered": False, "verdict": "dropped-thread", "quotes": [], "reason": "The scar is never mentioned again."},
]}


def ending_script():
    script = build_script()
    for row in script["replies"]:
        if row["purpose"] != "extract":
            continue
        reply = row["reply"] = copy.deepcopy(row["reply"])
        if row["chapter"] == 2:
            reply["questions_raised"].append(LIGHTS)
        if row["chapter"] == 3:
            reply["questions_raised"].append(SCAR)
        reply["questions_resolved"] = [r for r in reply.get("questions_resolved") or [] if r["id"] not in ("Q0003-02", "Q0001-03")]
    script["replies"].append({"purpose": "ending", "reply": ENDING_REPLY})
    return script


COMPLETE = {"backend": {"name": "fake", "script": "script.json"}, "complete": True}
ODILE = "What has Odile Marr carried in her head about the wreck for nine years?"


def reread_says(question, reply):
    script = ending_script()
    script["replies"].insert(0, {"purpose": "reread", "contains": question, "reply": reply})
    return script


def sections(markdown):
    found, current = {}, None
    for line in markdown.splitlines():
        heading = re.match(r"## (.+?) \(\d+\)$", line)
        if heading:
            current = heading.group(1)
            found[current] = []
        elif current:
            found[current] += re.findall(r"\*\*(Q\d{4}-\d{2})\*\*", line)
    return found


class EndingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(ending_script(), book=COMPLETE)
        cls.first = cls.book.build()

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def render(self, until):
        self.book.run_annalist("render", str(self.book.workdir), "--until", str(until))
        return (self.book.workdir / f"wiki-ch{until:04d}" / "open-questions.md").read_text(encoding="utf-8")

    def site(self, *views):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        proc = subprocess.run([node, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"),
                               str(self.book.workdir / "site" / "data" / "wiki.json"), *views],
                              capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)

    def test_each_question_left_open_at_the_end_gets_its_verdict(self):
        decisions = self.book.json("ending.json")["questions"]
        self.assertEqual({k: v["verdict"] for k, v in decisions.items()},
                         {"Q0003-02": "answered", "Q0001-03": "answered-implicitly", "Q0002-02": "left-open", "Q0003-05": "dropped-thread"})
        self.assertEqual(decisions["Q0003-02"]["chapter"], 4)
        self.assertEqual(decisions["Q0001-03"]["quotes"], [{"chapter": 5, "quote": IMPLIED_QUOTE}])

    def test_the_last_chapter_page_sorts_questions_into_answered_open_and_loose_ends(self):
        page = (self.book.workdir / "wiki" / "open-questions.md").read_text(encoding="utf-8")
        found = sections(page)
        self.assertEqual(sorted(found["Answered at the end"]), ["Q0001-03", "Q0003-02"])
        self.assertEqual(found["Open mysteries"], ["Q0002-02"])
        self.assertEqual(found["Loose ends"], ["Q0003-05"])
        self.assertLess(page.index("<details>"), page.index("**Q0003-05**"))

    def test_a_missed_answer_shows_from_its_own_chapter_and_verdicts_only_at_the_last(self):
        before = sections(self.render(3))
        self.assertIn("Q0003-02", before["Open"])
        at_answer = sections(self.render(4))
        self.assertIn("Q0003-02", at_answer["Resolved"])
        self.assertNotIn("Q0003-02", at_answer["Open"])
        self.assertLessEqual({"Q0001-03", "Q0002-02", "Q0003-05"}, set(at_answer["Open"]))
        self.assertNotIn("Loose ends", at_answer)

    def test_before_the_answer_chapter_the_page_is_what_it_was_without_the_end_pass(self):
        with_ending = self.render(3)
        moved = self.book.workdir / "ending.json.away"
        (self.book.workdir / "ending.json").rename(moved)
        try:
            self.assertEqual(self.render(3), with_ending)
        finally:
            moved.rename(self.book.workdir / "ending.json")

    def test_the_site_shows_verdicts_only_at_the_last_chapter(self):
        out = self.site("states@3", "states@4", "states@5", "mysteries@4", "mysteries@5")
        mine = ("Q0003-02", "Q0001-03", "Q0002-02", "Q0003-05")
        self.assertEqual([out["states@3"][q] for q in mine], ["open", "open", "open", "open"])
        self.assertEqual([out["states@4"][q] for q in mine], ["resolved", "open", "open", "open"])
        self.assertEqual([out["states@5"][q] for q in mine], ["resolved", "resolved", "open", "dropped"])
        self.assertNotIn("End of book", out["mysteries@4"])
        self.assertNotIn("Loose ends", out["mysteries@4"])
        self.assertIn("Answered at the end (2)", out["mysteries@5"])
        self.assertIn("Open mysteries (1)", out["mysteries@5"])
        self.assertRegex(out["mysteries@5"], r'<h2><button type="button" class="disc" aria-expanded="false" aria-controls="(\w+)"><span>Loose ends \(1\)</span></button></h2><div class="discbody" id="\1" hidden>')
        self.assertIn("Sister Wren", out["mysteries@5"].split("Loose ends")[1])

    def test_the_volume_lists_only_open_mysteries_at_the_end_and_loose_ends_apart(self):
        threads = next((self.book.workdir / "wiki" / "volumes").glob("*-threads.md")).read_text(encoding="utf-8")
        still_open, loose = threads.split("## Loose ends (1)")
        self.assertIn(LIGHTS["question"], still_open)
        self.assertNotIn(SCAR["question"], still_open)
        self.assertNotIn(ODILE, threads)
        self.assertIn(SCAR["question"], loose)
        self.assertNotIn(LIGHTS["question"], loose)

    def test_a_rebuild_is_current_and_asks_again_only_for_a_missing_verdict(self):
        calls = len(self.book.calls())
        again = self.book.build()
        self.assertEqual(plan_rows(again.stdout)["ending"], "done")
        self.assertEqual(len(self.book.calls()), calls)
        path = self.book.workdir / "ending.json"
        original = path.read_text(encoding="utf-8")
        data = json.loads(original)
        del data["questions"]["Q0002-02"]
        path.write_text(json.dumps(data), encoding="utf-8")
        try:
            rebuilt = self.book.build()
            self.assertEqual(plan_rows(rebuilt.stdout)["ending"], "run: input changed")
            questions = self.book.json("ending.json")["questions"]
            self.assertEqual(questions["Q0002-02"]["verdict"], "left-open")
            self.assertEqual(len(self.book.calls("ending")), 2)
        finally:
            path.write_text(original, encoding="utf-8")
            self.book.build()


class ImpliedAnswerTest(unittest.TestCase):
    def test_an_implied_answer_the_reread_rejects_is_demoted_to_unclear(self):
        book = MiniBuild(reread_says(ODILE, {"verdict": "reject", "payoff": "The barge quote shows a barge, not what she remembered."}),
                         book=COMPLETE)
        try:
            book.build()
            decision = book.json("ending.json")["questions"]["Q0001-03"]
            self.assertEqual(decision["verdict"], "unclear")
            self.assertIn("The barge quote shows a barge", decision["reason"])
            found = sections((book.workdir / "wiki" / "open-questions.md").read_text(encoding="utf-8"))
            self.assertEqual(found["Answered at the end"], ["Q0003-02"])
            self.assertIn("Q0001-03", found["Open mysteries"])
        finally:
            book.close()


class FailedItemTest(unittest.TestCase):
    def test_a_failed_reread_reruns_only_that_question_on_the_next_build(self):
        book = MiniBuild(reread_says(ODILE, {"verdict": "maybe"}), book=COMPLETE)
        try:
            book.build()
            self.assertEqual(plan_rows(book.build("--dry-run").stdout)["ending"], "run: 1 unfinished")
            found = sections((book.workdir / "wiki" / "open-questions.md").read_text(encoding="utf-8"))
            self.assertNotIn("Q0001-03", found["Answered at the end"])
            book.script(ending_script())
            before = len(book.calls())
            retried = book.build()
            self.assertEqual(plan_rows(retried.stdout)["ending"], "run: 1 unfinished")
            asked = book.calls()[before:]
            self.assertEqual([c["purpose"] for c in asked], ["reread"])
            self.assertEqual(book.json("ending.json")["questions"]["Q0001-03"]["verdict"], "answered-implicitly")
            self.assertEqual(plan_rows(book.build("--dry-run").stdout)["ending"], "done")
        finally:
            book.close()

    def test_a_failed_ending_batch_is_asked_again_on_the_next_build(self):
        script = ending_script()
        script["replies"] = [r for r in script["replies"] if r["purpose"] != "ending"] + [{"purpose": "ending", "reply": "not json"}]
        book = MiniBuild(script, book=COMPLETE)
        try:
            book.build()
            self.assertEqual({d["verdict"] for d in book.json("ending.json")["questions"].values()}, {"error"})
            self.assertEqual(plan_rows(book.build("--dry-run").stdout)["ending"], "run: 4 unfinished")
            book.script(ending_script())
            book.build()
            self.assertEqual(book.json("ending.json")["questions"]["Q0002-02"]["verdict"], "left-open")
            self.assertEqual(plan_rows(book.build("--dry-run").stdout)["ending"], "done")
        finally:
            book.close()

    def test_a_failed_sweep_batch_keeps_the_sweep_stage_from_counting_as_current(self):
        script = ending_script()
        script["replies"] = [r for r in script["replies"] if r["purpose"] != "sweep"] + [{"purpose": "sweep", "reply": "not json"}]
        book = MiniBuild(script, book=COMPLETE)
        try:
            book.build()
            failed = [k for k, d in book.json("sweep.json")["questions"].items() if d["verdict"] == "error"]
            self.assertTrue(failed)
            self.assertEqual(plan_rows(book.build("--dry-run").stdout)["sweep"], f"run: {len(failed)} unfinished")
            book.script(ending_script())
            before = len(book.calls())
            book.build()
            self.assertEqual(len([c for c in book.calls()[before:] if c["purpose"] == "sweep"]), 1)
            self.assertEqual(book.json("sweep.json")["questions"], {})
            self.assertEqual(plan_rows(book.build("--dry-run").stdout)["sweep"], "done")
        finally:
            book.close()


class IncompleteBookTest(unittest.TestCase):
    def test_an_incomplete_book_gets_no_end_pass(self):
        book = MiniBuild(ending_script())
        try:
            built = book.build()
            self.assertTrue(plan_rows(built.stdout)["ending"].startswith("skip: book.json does not mark the book complete"))
            self.assertFalse((book.workdir / "ending.json").exists())
            self.assertEqual(book.calls("ending"), [])
            refused = book.run_annalist("ending", str(book.workdir), check=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("does not mark the book complete", refused.stderr)
            self.assertFalse((book.workdir / "ending.json").exists())
        finally:
            book.close()

    def test_a_complete_book_built_short_of_its_end_gets_no_end_pass(self):
        book = MiniBuild(ending_script(), book=COMPLETE)
        try:
            built = book.build("--to", "4")
            self.assertEqual(plan_rows(built.stdout)["ending"], "skip: chapters 5-5 are not read")
            self.assertFalse((book.workdir / "ending.json").exists())
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()
