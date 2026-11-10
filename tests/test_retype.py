import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from annalist.state import load_states
from tests.test_backends import stub_claude

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"

CHAPTERS = {
    1: ("The Draught",
        "Ilse drank the Spark draught and became a Spark of the Ember School. An evil spirit watched from the well.\n"),
    2: ("The Well",
        "Evil spirits gathered in the well. Ilse whispered that the Evil Spirit would take her, and Varn died in Harbor Row.\n"),
    3: ("The Rank",
        "As a Spark she could light any lamp. Old tales say an evil spirit fears a Spark.\n"),
}


def entry(name, etype, summary=""):
    return {"name": name, "type": etype, "aliases": [], "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [entry("Ilse", "character", "A lamp girl."), entry("Spark", "rank", "The first rank of the Ember School."),
                     entry("Spark draught", "draught", "The draught that makes a Spark."),
                     entry("Ember School", "school", "A school of fire.")],
        "facts": [fact("Spark", "The Spark rank is reached by drinking the Spark draught, brewed from ash and oil.",
                       "Ilse drank the Spark draught and became a Spark of the Ember School.")],
        "relations": []},
    2: {"entities": [entry("Evil Spirit", "deity", "A spirit Ilse fears.")],
        "facts": [fact("Evil Spirit", "Ilse fears the Evil Spirit would take her.",
                       "Ilse whispered that the Evil Spirit would take her")],
        "relations": [{"source": "Varn", "target": "Harbor Row", "type": "died in", "quotes": ["Varn died in Harbor Row."],
                       "asserted_by": "narrator", "status": "stated"}]},
    3: {"entities": [], "facts": [], "relations": []},
}

BOOK = {"title": "Ember", "backend": {"name": "fake", "script": "script.json"},
        "power_system": "Schools of fire ranked by draughts.", "timeline_kind": "linear",
        "power_types": {"school": "A school of fire.", "rank": "A rank within a school.", "draught": "A draught that grants a rank."},
        "ladder": {"group_type": "school", "step_type": "rank", "rank": "number", "direction": "ascending", "note": ""}}


def retype_reply(types):
    return {"items": [{"id": str(i), "type": t, "reason": "From the facts."} for i, t in enumerate(types, 1)]}


REPLIES = [
    {"purpose": "retype", "contains": "Name: Varn", "reply": retype_reply(["school", "concept", "place", "draught", "draught", "character"])},
    {"purpose": "retype", "reply": {"items": []}},
    {"purpose": "link", "reply": {"labels": []}},
]


class Ember:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        (self.workdir / "chapters").mkdir(parents=True)
        (self.workdir / "state").mkdir()
        for n, (title, text) in CHAPTERS.items():
            (self.workdir / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
            extraction = {"synopsis": text.split(".")[0] + ".", **EXTRACTIONS[n]}
            (self.workdir / "state" / f"{n:04d}.json").write_text(
                json.dumps({"chapter": n, "title": title, "extraction": extraction}), encoding="utf-8")
        for name, data in (("chapters.json", [{"index": n, "title": t, "words": len(x.split())} for n, (t, x) in CHAPTERS.items()]),
                           ("script.json", {"replies": REPLIES}), ("book.json", BOOK), ("build.json", {"stages": {}})):
            (self.workdir / name).write_text(json.dumps(data), encoding="utf-8")
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


class RetypeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ember = Ember()
        cls.ember.run("retype", str(cls.ember.workdir), "--jobs", "1")
        cls.ember.run("link", str(cls.ember.workdir), "--jobs", "1")
        cls.kb = load_states(cls.ember.workdir)

    @classmethod
    def tearDownClass(cls):
        cls.ember.close()

    def test_a_name_the_text_uses_as_a_kind_is_checked_and_typed_as_one(self):
        self.assertEqual(self.kb.entities["Evil Spirit"]["type"], "concept")

    def test_a_ladder_step_keeps_its_type_when_its_facts_describe_its_draught(self):
        self.assertEqual(self.kb.entities["Spark"]["type"], "rank")

    def test_an_untyped_stub_gets_a_type(self):
        self.assertEqual(self.kb.entities["Varn"]["type"], "character")
        self.assertEqual(self.kb.entities["Harbor Row"]["type"], "place")

    def test_an_entry_named_for_another_with_its_own_type_word_is_linked_to_it(self):
        rows = [(r["source"], r["type"], r["target"]) for r in self.kb.relations]
        self.assertIn(("Spark draught", "draught of", "Spark"), rows)


class LeftoverTest(unittest.TestCase):
    def test_the_review_lists_entries_still_without_a_type(self):
        ember = Ember()
        try:
            ember.run("review", str(ember.workdir))
            report = json.loads((ember.workdir / "review.json").read_text(encoding="utf-8"))
            left = next(c for c in report["checks"] if c["key"] == "uncategorized")
            self.assertEqual(sorted(f["name"] for f in left["findings"]), ["Harbor Row", "Varn"])
        finally:
            ember.close()


if __name__ == "__main__":
    unittest.main()
