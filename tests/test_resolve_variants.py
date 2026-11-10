import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from annalist.discover import candidates
from annalist.state import load_states
from tests.test_backends import stub_claude

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"

CHAPTERS = {
    1: ("The Wharf",
        "Odra Vell pulled on her grey mitten and walked to the wharf. The Ash Witches met under the crane. "
        "Mr. Pellam counted crates for the Harbor Guild near the Copper Lane's end. Tamsin Rook kept a bone whistle on a cord. "
        "Odra Vell owned a tin flute. The Lamp Keepers lit the pier.\n"),
    2: ("The Relic",
        "The Hollow Grip was an old relic that fed on its bearer's hunger, and Odra Vell had paid dearly for it. "
        "An Ash Witch watched the water. Pellam shouted at the dockhands. A clerk of the Harbor Guild's council laughed. "
        "Odra played Odra's tin flute by the crane. Tamsin Rook spoke of the Night Reed, a relic that sang by itself. "
        "Odra Vell waved to a Lamp Keeper.\n"),
    3: ("The Dusk",
        "The Hollow Grip had shrunk into a plain mitten on Odra Vell's hand, and no one could tell she wore it. "
        "The Night Reed sounded like a whistle when Tamsin Rook blew it at dusk. An Ash Witch walked on Copper Lane past a Lamp Keeper.\n"),
}

GRIP_QUOTE = "The Hollow Grip had shrunk into a plain mitten on Odra Vell's hand, and no one could tell she wore it."
FALSE_REED_QUOTE = "Tamsin Rook's bone whistle was the Night Reed all along."


def entry(name, etype, summary):
    return {"name": name, "type": etype, "aliases": [], "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [entry("Odra Vell", "character", "A wharf worker."),
                     entry("Tamsin Rook", "character", "A woman with a bone whistle."),
                     entry("Mr. Pellam", "character", "A man who counts crates."),
                     entry("Grey mitten", "artifact", "Odra Vell's grey mitten."),
                     entry("Bone whistle", "artifact", "Tamsin Rook's bone whistle, worn on a cord."),
                     entry("Tin flute", "artifact", "A tin flute."),
                     entry("Ash Witches", "organization", "A coven that meets under the crane."),
                     entry("Harbor Guild", "organization", "The guild that runs the wharf."),
                     entry("Lamp Keepers", "organization", "The keepers who light the pier.")],
        "facts": [fact("Grey mitten", "Odra Vell wore the grey mitten to the wharf.",
                       "Odra Vell pulled on her grey mitten and walked to the wharf."),
                  fact("Bone whistle", "Tamsin Rook kept the bone whistle on a cord.",
                       "Tamsin Rook kept a bone whistle on a cord."),
                  fact("Mr. Pellam", "Mr. Pellam counted crates.", "Mr. Pellam counted crates for the Harbor Guild")]},
    2: {"entities": [entry("Odra Vell", "character", "A wharf worker."),
                     entry("Hollow Grip", "artifact", "Odra Vell's relic that feeds on its bearer's hunger."),
                     entry("Night Reed", "artifact", "Tamsin Rook's relic that sings by itself."),
                     entry("Ash Witch", "organization", "A coven member watching the water."),
                     entry("Harbor Guild's", "organization", "The guild whose council laughs.")],
        "facts": [fact("Hollow Grip", "The Hollow Grip feeds on its bearer's hunger.",
                       "The Hollow Grip was an old relic that fed on its bearer's hunger"),
                  fact("Night Reed", "Tamsin Rook spoke of the Night Reed.",
                       "Tamsin Rook spoke of the Night Reed, a relic that sang by itself."),
                  fact("Pellam", "Pellam shouted at the dockhands.", "Pellam shouted at the dockhands."),
                  fact("Odra's tin flute", "Odra played her tin flute by the crane.", "Odra played Odra's tin flute by the crane.")]},
    3: {"entities": [entry("Hollow Grip", "artifact", "Odra Vell's relic that feeds on its bearer's hunger."),
                     entry("Night Reed", "artifact", "Tamsin Rook's relic that sings by itself.")],
        "facts": [fact("Hollow Grip", "The Hollow Grip looked like a plain mitten on Odra Vell's hand.", GRIP_QUOTE),
                  fact("Night Reed", "The Night Reed sounded like a whistle.",
                       "The Night Reed sounded like a whistle when Tamsin Rook blew it at dusk.")]},
}


def same(canonical):
    return {"same": True, "canonical_name": canonical, "reason": "One and the same."}


REPLIES = [
    {"purpose": "resolve", "contains": "Name: Ash Witches", "reply": same("Ash Witch")},
    {"purpose": "resolve", "contains": "Name: Harbor Guild's", "reply": same("Harbor Guild's")},
    {"purpose": "resolve", "contains": "Name: Pellam\n", "reply": same("Pellam")},
    {"purpose": "resolve", "contains": "Name: Odra's tin flute", "reply": same("Odra's tin flute")},
    {"purpose": "resolve", "contains": "Name: Grey mitten", "reply": same("Hollow Grip")},
    {"purpose": "resolve", "contains": "Name: Bone whistle", "reply": same("Night Reed")},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "reveal", "contains": "ENTRY A: Grey mitten", "reply": {"chapter": 3, "quote": GRIP_QUOTE}},
    {"purpose": "reveal", "contains": "ENTRY A: Bone whistle", "reply": {"chapter": 3, "quote": FALSE_REED_QUOTE}},
    {"purpose": "reveal", "reply": {"chapter": None, "quote": ""}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "chapter": None, "quote": ""}},
]


class Wharf:
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
        (self.workdir / "book.json").write_text(json.dumps({"title": "Wharf", "backend": {"name": "fake", "script": "script.json"}}),
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


class VariantMergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wharf = Wharf()
        cls.wharf.run("resolve", str(cls.wharf.workdir), "--jobs", "1")
        cls.pairs = json.loads((cls.wharf.workdir / "merges.json").read_text(encoding="utf-8"))["pairs"]

    @classmethod
    def tearDownClass(cls):
        cls.wharf.close()

    def pair(self, a, b):
        return next(d for d in self.pairs if {d["a"], d["b"]} == {a, b})

    def entities(self, until=None):
        return load_states(self.wharf.workdir, until=until).entities

    def holder(self, name, until=None):
        return next(k for k, e in self.entities(until).items() if name in [k] + e["aliases"])

    def test_a_singular_and_plural_of_one_name_are_compared_and_merged(self):
        self.assertTrue(self.pair("Ash Witch", "Ash Witches")["same"])
        self.assertEqual(self.holder("Ash Witch"), self.holder("Ash Witches"))

    def test_a_name_with_a_trailing_possessive_merges_under_the_plain_name(self):
        pair = self.pair("Harbor Guild", "Harbor Guild's")
        self.assertEqual(pair["canonical"], "Harbor Guild")
        self.assertIn("Harbor Guild", self.entities())
        self.assertNotIn("Harbor Guild's", self.entities())

    def test_an_untyped_stub_merges_into_the_typed_entry_with_its_name_and_keeps_the_type(self):
        for stub, typed, etype in (("Pellam", "Mr. Pellam", "character"), ("Odra's tin flute", "Tin flute", "artifact")):
            pair = self.pair(stub, typed)
            self.assertTrue(any(r.startswith("name-containment") for r in pair["rules"]), pair["rules"])
            self.assertEqual(pair["canonical"], typed)
            merged = self.entities()
            self.assertNotIn(stub, merged)
            self.assertEqual(merged[typed]["type"], etype)
            self.assertIn(stub, merged[typed]["aliases"])

    def test_things_one_owner_holds_merge_from_the_chapter_whose_fact_quote_shows_the_identity(self):
        pair = self.pair("Grey mitten", "Hollow Grip")
        self.assertIn("same-holder: Odra Vell", pair["rules"])
        self.assertEqual(pair["revealed"], {"chapter": 3, "quote": GRIP_QUOTE, "basis": "quote"})
        self.assertIn("Grey mitten", self.entities(2))
        self.assertIn("Hollow Grip", self.entities(2))
        self.assertNotIn("Grey mitten", self.entities(3))
        self.assertIn("Grey mitten", self.entities(3)["Hollow Grip"]["aliases"])

    def test_a_reveal_quote_the_chapter_does_not_hold_leaves_the_things_apart(self):
        pair = self.pair("Bone whistle", "Night Reed")
        self.assertTrue(pair["same"])
        self.assertEqual(pair["revealed"]["basis"], "unverified")
        self.assertIn("Bone whistle", self.entities())
        self.assertIn("Night Reed", self.entities())


class VariantDiscoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wharf = Wharf()
        cls.found = {c["name"] for c in candidates(cls.wharf.workdir, load_states(cls.wharf.workdir, discovered=False))}

    @classmethod
    def tearDownClass(cls):
        cls.wharf.close()

    def test_the_singular_of_an_entry_name_is_not_a_new_candidate(self):
        self.assertNotIn("Lamp Keeper", self.found)

    def test_a_possessive_counts_toward_the_plain_name_and_is_never_a_candidate_itself(self):
        self.assertIn("Copper Lane", self.found)
        self.assertNotIn("Copper Lane's", self.found)


if __name__ == "__main__":
    unittest.main()
