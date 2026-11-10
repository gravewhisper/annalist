import json
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from annalist import read
from annalist.llm import LLMError


def extraction(raised=(), resolved=()):
    return {"synopsis": "s", "entities": [], "facts": [], "relations": [],
            "questions_raised": [{"question": q, "quote": "q"} for q in raised],
            "questions_resolved": [{"id": i, "answer": "a", "quote": "q"} for i in resolved]}


class ReadOverlap(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = Path(tmp.name)
        (self.workdir / "chapters").mkdir()
        (self.workdir / "state").mkdir()
        chapters = [{"index": n, "title": f"T{n}", "words": 1} for n in range(1, 5)]
        (self.workdir / "chapters.json").write_text(json.dumps(chapters), encoding="utf-8")
        (self.workdir / "book.json").write_text(json.dumps({"timeline_kind": "linear"}), encoding="utf-8")
        for c in chapters:
            (self.workdir / "chapters" / f"{c['index']:04d}.txt").write_text(f"chapter {c['index']}", encoding="utf-8")

    def run_read(self, replies, audit=lambda *a: {}, verdict="accept"):
        self.prompts = {}

        def fake_llm(workdir, purpose, prompt, chapter=None, **kw):
            self.prompts[chapter] = prompt
            reply = replies[chapter]
            if isinstance(reply, Exception):
                raise reply
            return reply

        with mock.patch.object(read, "llm", fake_llm), mock.patch.object(read, "audit_support", audit), \
                mock.patch.object(read, "reread", lambda *a: {"verdict": verdict, "payoff": "p"}):
            read.cmd_read(Namespace(workdir=str(self.workdir), start=1, end=max(replies)))

    def saved(self, n):
        return (self.workdir / "state" / f"{n:04d}.json").exists()

    def test_chapter_two_extract_begins_before_chapter_one_check_ends(self):
        second = threading.Event()
        overlapped = []
        real = read.extract_chapter

        def spy(workdir, kb, chapter, pending):
            if chapter["index"] == 2:
                second.set()
            return real(workdir, kb, chapter, pending)

        def audit(workdir, out, n):
            if n == 1:
                overlapped.append(second.wait(10))
            return {}

        with mock.patch.object(read, "extract_chapter", spy):
            self.run_read({1: extraction(), 2: extraction()}, audit)
        self.assertEqual(overlapped, [True])
        self.assertTrue(self.saved(1) and self.saved(2))

    def test_claimed_answer_stays_open_until_its_check_is_saved(self):
        replies = {1: extraction(raised=["Who cut the page?"]), 2: extraction(), 3: extraction(resolved=["Q0001-01"]), 4: extraction()}
        self.run_read(replies)
        self.assertIn("Who cut the page?", self.prompts[4])

    def test_accepted_answer_closes_the_question_one_chapter_later(self):
        chapters = json.loads((self.workdir / "chapters.json").read_text(encoding="utf-8"))
        chapters.append({"index": 5, "title": "T5", "words": 1})
        (self.workdir / "chapters.json").write_text(json.dumps(chapters), encoding="utf-8")
        (self.workdir / "chapters" / "0005.txt").write_text("chapter 5", encoding="utf-8")
        replies = {1: extraction(raised=["Who cut the page?"]), 2: extraction(), 3: extraction(resolved=["Q0001-01"]), 4: extraction(), 5: extraction()}
        self.run_read(replies)
        self.assertNotIn("Who cut the page?", self.prompts[5])

    def test_no_prompt_holds_a_later_chapter(self):
        replies = {n: extraction() for n in range(1, 5)}
        for n in replies:
            (self.workdir / "chapters" / f"{n:04d}.txt").write_text(f"marker{n}word", encoding="utf-8")
        self.run_read(replies)
        for n, prompt in self.prompts.items():
            for later in range(n + 1, 5):
                self.assertNotIn(f"marker{later}word", prompt)

    def test_failed_extract_keeps_the_chapter_before_it(self):
        with self.assertRaises(SystemExit) as stop:
            self.run_read({1: extraction(), 2: LLMError("bad reply")})
        self.assertEqual(stop.exception.code, 2)
        self.assertTrue(self.saved(1))
        self.assertFalse(self.saved(2))
        self.run_read({1: extraction(), 2: extraction()})
        self.assertTrue(self.saved(2))

    def test_failed_check_saves_nothing_after_it(self):
        def audit(workdir, out, n):
            if n == 1:
                raise LLMError("bad check")
            return {}

        with self.assertRaises(SystemExit) as stop:
            self.run_read({1: extraction(), 2: extraction()}, audit)
        self.assertEqual(stop.exception.code, 2)
        self.assertFalse(self.saved(1) or self.saved(2))


if __name__ == "__main__":
    unittest.main()
