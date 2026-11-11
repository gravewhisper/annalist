import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from annalist.answers import answers_item
from annalist.state import load_states
from tests.test_backends import stub_claude

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"

CUT = "Someone had cut the page for the night of the wreck from the harbour ledger."
AGAIN = "The stub of the missing page was stained with lamp oil."
LIMP = "The ferryman limped past the harbour ledger office."
ANSWER = "Rook admitted that he cut the page to hide his own name."

CHAPTERS = {
    1: ("The Ledger", f"{CUT} Nobody would say who had done it.\n"),
    2: ("The Oil", f"{AGAIN} {LIMP}\n"),
    3: ("The Confession", f"{ANSWER}\n"),
}

FIRST = "Who cut the missing page from the harbour ledger?"
REPEAT = "Why was the missing page cut from the harbour ledger, and why is its stub stained with oil?"
OTHER = "Is the ferryman's limp connected to the missing ledger page?"

EXTRACTIONS = {
    1: {"questions_raised": [{"question": FIRST, "quote": CUT}]},
    2: {"questions_raised": [{"question": REPEAT, "quote": AGAIN}, {"question": OTHER, "quote": LIMP}]},
    3: {"questions_resolved": [{"id": "Q0002-01", "answer": "Rook cut the page to hide his name.", "quote": ANSWER}]},
}

REPLIES = [
    {"purpose": "repeats", "reply": {"pairs": [
        {"id": "Q0001-01/Q0002-01", "same": True, "reason": "Both ask who cut the page and why."},
        {"id": "Q0001-01/Q0002-02", "same": False, "reason": "The limp is a different mystery."}]}},
    {"purpose": "leads", "reply": {"items": []}},
]


class Harbour:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        (self.workdir / "chapters").mkdir(parents=True)
        (self.workdir / "state").mkdir()
        for n, (title, text) in CHAPTERS.items():
            (self.workdir / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
            extraction = {"synopsis": text.split(".")[0] + ".", "entities": [], "facts": [], "relations": [], **EXTRACTIONS[n]}
            rereads = {"Q0002-01": {"verdict": "accept", "payoff": "The confession names who cut the page."}} if n == 3 else {}
            (self.workdir / "state" / f"{n:04d}.json").write_text(
                json.dumps({"chapter": n, "title": title, "extraction": extraction, "rereads": rereads}), encoding="utf-8")
        (self.workdir / "chapters.json").write_text(json.dumps(
            [{"index": n, "title": title, "words": len(text.split())} for n, (title, text) in CHAPTERS.items()]), encoding="utf-8")
        (self.workdir / "script.json").write_text(json.dumps({"replies": REPLIES}), encoding="utf-8")
        (self.workdir / "book.json").write_text(json.dumps({"title": "Harbour", "backend": {"name": "fake", "script": "script.json"}}),
                                                encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}
        self.env.update(stub_claude(self.root, "", 1))

    def run(self, *args):
        proc = subprocess.run([sys.executable, "-m", "annalist", *args], cwd=ROOT, env=self.env, capture_output=True, text=True,
                              timeout=120)
        if proc.returncode:
            raise AssertionError(f"annalist {args[0]} exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc

    def close(self):
        self.tmp.cleanup()


class RepeatedQuestionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harbour = Harbour()
        cls.harbour.run("leads", str(cls.harbour.workdir), "--jobs", "1")

    @classmethod
    def tearDownClass(cls):
        cls.harbour.close()

    def questions(self, until=None):
        return load_states(self.harbour.workdir, until=until).questions

    def test_a_question_asked_again_a_chapter_later_folds_into_the_open_one(self):
        questions = self.questions(2)
        self.assertEqual(sorted(questions), ["Q0001-01", "Q0002-02"])
        self.assertEqual(questions["Q0001-01"]["question"], FIRST)
        self.assertEqual([(a["chapter"], a["question"]) for a in questions["Q0001-01"]["again"]], [(2, REPEAT)])

    def test_the_earlier_question_shows_nothing_of_the_later_chapter_before_it(self):
        self.assertNotIn("again", self.questions(1)["Q0001-01"])

    def test_a_related_question_the_judge_calls_different_stays(self):
        self.assertEqual(self.questions()["Q0002-02"]["question"], OTHER)

    def test_an_answer_claimed_for_the_folded_question_settles_the_kept_one(self):
        kept = self.questions()["Q0001-01"]
        self.assertEqual((kept["status"], kept["resolved_chapter"], kept["resolve_quote"]), ("resolved", 3, ANSWER))

    def test_the_answers_judge_sees_the_later_wording(self):
        self.assertIn(REPEAT, answers_item(self.questions(2)["Q0001-01"], [], {}))

    def test_the_questions_file_lists_one_question_per_mystery(self):
        rows = [json.loads(line) for line in (self.harbour.workdir / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["id"] for r in rows], ["Q0001-01", "Q0002-02"])


if __name__ == "__main__":
    unittest.main()
