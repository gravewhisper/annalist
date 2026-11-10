import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_backends import stub_claude

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data"
DROPPED = (1, "F1")


def expected(n):
    return json.loads((DATA / "mini-expected-extractions" / f"ch{n:02d}.json").read_text(encoding="utf-8"))


def support_reply(extraction, n):
    ids = [f"F{i}" for i in range(1, len(extraction["facts"]) + 1)] + [f"R{i}" for i in range(1, len(extraction["relations"]) + 1)]
    return {"verdicts": [{"id": i, "verdict": "unsupported" if (n, i) == DROPPED else "supported"} for i in ids]}


def mini_script(skip=()):
    replies = []
    for n in range(1, 6):
        record = expected(n)
        steps = {"extract": record["extraction"], "timelines": record["timelines"],
                 "support": support_reply(record["extraction"], n),
                 "reread": {"verdict": "accept", "payoff": "The setup is paid off by the resolving passage."}}
        replies += [{"purpose": p, "chapter": n, "reply": r} for p, r in steps.items() if (p, n) not in skip]
    return {"replies": replies}


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class MiniBook:
    def __init__(self, script):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}
        self.env.update(stub_claude(self.root, "", 1))
        self.run("extract", str(DATA / "mini.epub"), str(self.workdir))
        (self.workdir / "script.json").write_text(json.dumps(script), encoding="utf-8")
        (self.workdir / "book.json").write_text(json.dumps({"backend": {"name": "fake", "script": "script.json"},
                                                            "timeline_kind": "flashback"}), encoding="utf-8")

    def run(self, *args, check=True):
        proc = subprocess.run([sys.executable, "-m", "annalist", *args], cwd=ROOT, env=self.env,
                              capture_output=True, text=True, timeout=120)
        if check and proc.returncode:
            raise AssertionError(f"annalist {' '.join(args)} exited {proc.returncode}:\n{proc.stderr}")
        return proc

    def read(self, last, **kw):
        return self.run("read", str(self.workdir), "--to", str(last), **kw)

    def entities(self):
        return {e["name"]: e for e in json.loads((self.workdir / "entities.json").read_text(encoding="utf-8"))}

    def rows(self, name):
        return read_jsonl(self.workdir / name)


class ReadMiniBookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBook(mini_script())
        cls.book.read(3)
        cls.before_reveal = cls.book.entities()
        cls.book.read(5)
        cls.verify = cls.book.run("verify", str(cls.book.workdir)).stdout

    @classmethod
    def tearDownClass(cls):
        cls.book.tmp.cleanup()

    def test_extract_finds_the_five_chapters_in_spine_order(self):
        chapters = json.loads((self.book.workdir / "chapters.json").read_text(encoding="utf-8"))
        self.assertEqual([c["title"] for c in chapters],
                         ["The Missing Page", "Nine Winters Ago", "The Abbey Stair", "Two Names", "The Salt Ledger"])

    def test_wiki_lists_the_books_entities(self):
        names = set(self.book.entities())
        for name in ("Ines Varro", "Tomas Hale", "Bram Ostrow", "Sabine Oake", "Livia Hale", "Brannoc Abbey",
                     "Salt Ledger", "lamp room key", "Captain Fenn", "Odile Marr"):
            self.assertIn(name, names)
        self.assertIn("Master Oake", self.book.entities()["Sabine Oake"]["aliases"])

    def test_every_fact_quote_verifies_against_the_chapter_text(self):
        facts = self.book.rows("facts.jsonl")
        self.assertTrue(facts)
        self.assertEqual([f["id"] for f in facts if not f["quote_ok"] or f.get("dropped_quotes")], [])

    def test_fact_the_audit_rejects_stays_out_of_the_wiki(self):
        dropped = expected(DROPPED[0])["extraction"]["facts"][0]["claim"]
        self.assertNotIn(dropped, [f["claim"] for f in self.book.rows("facts.jsonl")])

    def test_tomas_dies_in_chapter_three(self):
        deaths = [f for f in self.book.rows("facts.jsonl") if f["entity"] == "Tomas Hale" and "dead" in f["claim"]]
        self.assertEqual([f["chapter"] for f in deaths], [3])
        self.assertTrue(deaths[0]["quote_ok"])

    def test_sister_wren_is_revealed_as_livia_only_from_chapter_four(self):
        self.assertIn("Sister Wren", self.before_reveal)
        self.assertNotIn("Sister Wren", self.before_reveal["Livia Hale"]["aliases"])
        after = self.book.entities()
        self.assertNotIn("Sister Wren", after)
        self.assertIn("Sister Wren", after["Livia Hale"]["aliases"])
        self.assertEqual(after["Livia Hale"]["first_chapter"], 2)

    def test_the_captain_title_does_not_merge_odile_and_fenn(self):
        entities = self.book.entities()
        self.assertNotEqual(entities["Odile Marr"], entities["Captain Fenn"])
        for e in entities.values():
            self.assertNotIn("the captain", [a.lower() for a in e["aliases"]])

    def test_key_passes_from_ines_to_bram(self):
        holders = [(r["chapter"], r["source"]) for r in self.book.rows("relations.jsonl")
                   if r["target"] == "lamp room key" and r["type"] == "holder of"]
        self.assertEqual(holders, [(3, "Ines Varro"), (4, "Bram Ostrow")])

    def test_chapter_two_is_labelled_a_flashback(self):
        timelines = {t["id"]: t for t in json.loads((self.book.workdir / "timelines.json").read_text(encoding="utf-8"))}
        self.assertEqual((timelines["gannet-night"]["kind"], timelines["gannet-night"]["started"]), ("flashback", 2))
        by_chapter = {}
        for f in self.book.rows("facts.jsonl"):
            by_chapter.setdefault(f["chapter"], set()).add(f["timeline"])
        self.assertEqual(by_chapter[2], {"gannet-night"})
        self.assertEqual(by_chapter[1] | by_chapter[3] | by_chapter[4] | by_chapter[5], {"main"})

    def test_accepted_rereads_resolve_open_questions(self):
        questions = {q["id"]: q for q in self.book.rows("questions.jsonl")}
        self.assertEqual((questions["Q0001-01"]["status"], questions["Q0001-01"]["resolved_chapter"]), ("resolved", 5))

    def test_calls_are_logged_with_the_fake_backend(self):
        calls = self.book.rows("calls.jsonl")
        self.assertEqual({c["backend"] for c in calls}, {"fake"})
        self.assertEqual({c["purpose"] for c in calls}, {"extract", "support", "timelines", "reread"})
        self.assertFalse([c for c in calls if c["error"]])


class UnscriptedCallTest(unittest.TestCase):
    def test_read_stops_before_saving_a_chapter_the_script_does_not_cover(self):
        book = MiniBook(mini_script(skip={("extract", 2)}))
        try:
            proc = book.read(2, check=False)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("no scripted reply for purpose 'extract' chapter 2", proc.stderr)
            self.assertTrue((book.workdir / "state" / "0001.json").exists())
            self.assertFalse((book.workdir / "state" / "0002.json").exists())
        finally:
            book.tmp.cleanup()


class ConfigErrorTest(unittest.TestCase):
    def test_bad_backend_config_exits_with_the_reason(self):
        book = MiniBook(mini_script())
        try:
            book.env["ANNALIST_BACKEND"] = "gemini"
            proc = book.read(1, check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("annalist: unknown backend 'gemini'", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
        finally:
            book.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
