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

RENAME = "After the flood, the Lantern Saint was renamed the Tide Mother."
FORMERLY = "Odile walked the Salt Road, formerly the Old Track, to the hall."

CHAPTERS = {
    1: ("The Shrine",
        "Pilgrims climbed to the shrine of the Lantern Saint. The Hall of the Lantern Saint kept the candles. "
        "Odile walked the Old Track to the shrine. The wind changed to the east.\n"),
    2: ("The Storm",
        "A storm came over the hills. The Tide Mother sent rain on the fields. "
        "The bells of the Hall of the Tide Mother rang all night. Odile came home by the Salt Road.\n"),
    3: ("The Decree", f"{RENAME} {FORMERLY}\n"),
}


def entry(name, etype, summary):
    return {"name": name, "type": etype, "aliases": [], "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [entry("Odile", "character", "A pilgrim."),
                     entry("Lantern Saint", "deity", "The god of the hill shrine."),
                     entry("Hall of the Lantern Saint", "organization", "The order that keeps the shrine's candles."),
                     entry("Old Track", "place", "The path to the shrine.")],
        "facts": [fact("Hall of the Lantern Saint", "The Hall of the Lantern Saint kept the candles.",
                       "The Hall of the Lantern Saint kept the candles.")]},
    2: {"entities": [entry("Tide Mother", "deity", "A god who sends rain."),
                     entry("Hall of the Tide Mother", "organization", "An order whose bells ring in storms."),
                     entry("Salt Road", "place", "The road home from the hills.")],
        "facts": [fact("Tide Mother", "The Tide Mother sent rain on the fields.", "The Tide Mother sent rain on the fields.")]},
    3: {"entities": [entry("Lantern Saint", "deity", "The god of the hill shrine, renamed.")],
        "facts": [fact("Tide Mother", "The Lantern Saint was renamed the Tide Mother.", RENAME)]},
}


def same(canonical):
    return {"same": True, "canonical_name": canonical, "reason": "The text says the name changed."}


REPLIES = [
    {"purpose": "resolve", "contains": "Name: Lantern Saint\n", "reply": same("Tide Mother")},
    {"purpose": "resolve", "contains": "Name: Hall of the Lantern Saint\n", "reply": same("Hall of the Tide Mother")},
    {"purpose": "resolve", "contains": "Name: Old Track\n", "reply": same("Salt Road")},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "reveal", "reply": {"chapter": None, "quote": ""}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "chapter": None, "quote": ""}},
]


class Shrine:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        (self.workdir / "chapters").mkdir(parents=True)
        (self.workdir / "state").mkdir()
        for n, (title, text) in CHAPTERS.items():
            (self.workdir / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
            extraction = {"synopsis": text.split(".")[0] + ".", **EXTRACTIONS[n], "relations": []}
            (self.workdir / "state" / f"{n:04d}.json").write_text(
                json.dumps({"chapter": n, "title": title, "extraction": extraction}), encoding="utf-8")
        (self.workdir / "chapters.json").write_text(json.dumps(
            [{"index": n, "title": title, "words": len(text.split())} for n, (title, text) in CHAPTERS.items()]), encoding="utf-8")
        (self.workdir / "script.json").write_text(json.dumps({"replies": REPLIES}), encoding="utf-8")
        (self.workdir / "book.json").write_text(json.dumps({"title": "Shrine", "backend": {"name": "fake", "script": "script.json"}}),
                                                encoding="utf-8")
        (self.workdir / "build.json").write_text(json.dumps({"stages": {}}), encoding="utf-8")
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


class StatedRenameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shrine = Shrine()
        cls.shrine.run("resolve", str(cls.shrine.workdir), "--jobs", "1")
        cls.pairs = json.loads((cls.shrine.workdir / "merges.json").read_text(encoding="utf-8"))["pairs"]

    @classmethod
    def tearDownClass(cls):
        cls.shrine.close()

    def pair(self, a, b):
        found = [d for d in self.pairs if {d["a"], d["b"]} == {a, b}]
        self.assertTrue(found, f"no candidate pair for {a} and {b}")
        return found[0]

    def holder(self, name, until):
        return next(k for k, e in load_states(self.shrine.workdir, until=until).entities.items() if name in [k] + e["aliases"])

    def assert_merged_from(self, a, b, chapter, quote):
        pair = self.pair(a, b)
        self.assertTrue(pair["same"])
        self.assertEqual(pair["revealed"], {"chapter": chapter, "quote": quote, "basis": "quote"})
        self.assertNotEqual(self.holder(a, chapter - 1), self.holder(b, chapter - 1))
        self.assertEqual(self.holder(a, chapter), self.holder(b, chapter))

    def test_a_rename_the_text_states_merges_the_two_entries_from_the_stating_chapter(self):
        self.assertTrue(any(r.startswith("stated-rename") for r in self.pair("Lantern Saint", "Tide Mother")["rules"]))
        self.assertEqual(self.pair("Lantern Saint", "Tide Mother")["canonical"], "Tide Mother")
        self.assert_merged_from("Lantern Saint", "Tide Mother", 3, RENAME)

    def test_a_formerly_clause_states_a_rename_too(self):
        self.assert_merged_from("Old Track", "Salt Road", 3, FORMERLY)

    def test_a_name_built_on_the_renamed_name_pairs_with_the_one_built_on_the_new_name(self):
        self.assertTrue(any(r.startswith("renamed-within") for r in self.pair("Hall of the Lantern Saint", "Hall of the Tide Mother")["rules"]))
        self.assert_merged_from("Hall of the Lantern Saint", "Hall of the Tide Mother", 3, RENAME)

    def test_a_change_that_names_no_entry_pairs_nothing(self):
        self.assertFalse([d for d in self.pairs if any("east" in r.lower() for r in d["rules"])])


if __name__ == "__main__":
    unittest.main()
