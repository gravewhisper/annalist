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

TEACHER_QUOTE = "Ilse was taught her letters by her teacher, Master Corin Dale, who kept a school by the quay."
ROBE_QUOTE = "Lady Veyra, wearing a long grey robe, handed a bronze key to Pell Garrow."
DOUBT_QUOTE = "How could Master Fenwick be the same man as Baron Odo, painted two hundred years ago?"

DAUGHTER_QUOTE = "Is the grey robed woman your daughter, Master Dale?"

CHAPTERS = {
    1: ("The School", f"{TEACHER_QUOTE} Corin Dale was patient and old. Edda Grey sold fish.\n"),
    2: ("The Key", "A grey-robed woman with a hoarse voice handed Pell Garrow a bronze key in the dark of the harbor. "
                   "Pell Garrow ran.\n"),
    3: ("The Letter", "Ilse opened the letter from her teacher and smiled at the careful hand. Corin Dale was away.\n"),
    4: ("The Portrait", "The portrait of Baron Odo hung in the hall. Baron Odo had a scar on his chin, in exactly the same place as "
                        "Master Fenwick's scar. Master Fenwick laughed at the likeness.\n"),
    5: ("The Doubt", f"Ilse stared at the old painting. {DOUBT_QUOTE} She did not know.\n"),
    6: ("The Robe", f"{ROBE_QUOTE} Lady Veyra smiled. Pell Garrow bowed.\n"),
    7: ("The Daughter", f"Pell Garrow found Corin Dale at the school. {DAUGHTER_QUOTE}\n"),
}


def entry(name, summary):
    return {"name": name, "type": "character", "aliases": [], "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [entry("Ilse", "A girl of the quay."), entry("Corin Dale", "A schoolmaster."), entry("Edda Grey", "A fishwife.")],
        "facts": [fact("Corin Dale", "Corin Dale teaches Ilse her letters.", TEACHER_QUOTE)]},
    2: {"entities": [entry("Grey-robed woman", "A hoarse woman who hands Pell Garrow a bronze key."), entry("Pell Garrow", "A runner.")],
        "facts": [fact("Grey-robed woman", "The grey-robed woman hands Pell Garrow a bronze key.",
                       "A grey-robed woman with a hoarse voice handed Pell Garrow a bronze key in the dark of the harbor.")]},
    3: {"entities": [entry("Ilse's teacher", "The teacher who writes to Ilse.")],
        "facts": [fact("Ilse's teacher", "Ilse's teacher writes her a letter.",
                       "Ilse opened the letter from her teacher and smiled at the careful hand.")]},
    4: {"entities": [entry("Baron Odo", "A baron in an old portrait."), entry("Master Fenwick", "A cheerful man with a scar.")],
        "facts": [fact("Baron Odo", "Baron Odo's portrait shows a scar in the same place as Master Fenwick's scar.",
                       "Baron Odo had a scar on his chin, in exactly the same place as Master Fenwick's scar.")]},
    5: {"entities": [], "facts": []},
    6: {"entities": [entry("Lady Veyra", "A lady in a grey robe.")],
        "facts": [fact("Lady Veyra", "Lady Veyra wears a long robe.", ROBE_QUOTE)]},
    7: {"entities": [], "facts": []},
}

REPLIES = [
    {"purpose": "identify", "contains": "Master Corin Dale, who kept a school", "reply": {
        "candidate": "Corin Dale", "basis": "explicit", "same_individual": True, "chapter": 1, "quote": TEACHER_QUOTE, "reason": "Named."}},
    {"purpose": "identify", "contains": "Lady Veyra, wearing a long grey robe", "reply": {
        "candidate": "Lady Veyra", "basis": "implied", "same_individual": True, "chapter": 6, "quote": ROBE_QUOTE, "reason": "Same robe."}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "same_individual": False, "chapter": None, "quote": "", "reason": "No."}},
    {"purpose": "suspect", "contains": "How could Master Fenwick be the same man", "reply": {
        "basis": "implied", "same_individual": True, "chapter": 5, "quote": DOUBT_QUOTE, "reason": "Ilse suspects it."}},
    {"purpose": "suspect", "reply": {"basis": "none", "same_individual": False, "chapter": None, "quote": "", "reason": "No."}},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "relate", "contains": "CHAPTER 7: The Daughter", "reply": {"relations": [
        {"source": "Grey-robed woman", "type": "daughter of", "target": "Corin Dale", "quote": DAUGHTER_QUOTE,
         "asserted_by": "Pell Garrow", "status": "belief"}]}},
    {"purpose": "relate", "reply": {"relations": []}},
    {"purpose": "reveal", "reply": {"chapter": None, "quote": ""}},
]


class Quay:
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
        for name, data in (("chapters.json", [{"index": n, "title": t, "words": len(x.split())} for n, (t, x) in CHAPTERS.items()]),
                           ("script.json", {"replies": REPLIES}), ("book.json", {"title": "Quay", "backend": {"name": "fake", "script": "script.json"}}),
                           ("build.json", {"stages": {}})):
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


class SuspectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quay = Quay()
        cls.quay.run("resolve", str(cls.quay.workdir), "--jobs", "1")
        cls.pairs = json.loads((cls.quay.workdir / "merges.json").read_text(encoding="utf-8"))["pairs"]

    @classmethod
    def tearDownClass(cls):
        cls.quay.close()

    def pair(self, a, b):
        return next((d for d in self.pairs if {d["a"], d["b"]} == {a, b}), None)

    def test_a_role_descriptor_merges_with_whom_an_earlier_statement_names_in_that_role(self):
        pair = self.pair("Ilse's teacher", "Corin Dale")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertTrue(pair["same"])
        entities = load_states(self.quay.workdir, until=3).entities
        self.assertNotIn("Ilse's teacher", entities)
        self.assertIn("Ilse's teacher", entities["Corin Dale"]["aliases"])

    def test_a_described_figure_gets_a_possibly_lead_to_whom_a_later_scene_shows_in_the_same_dress(self):
        pair = self.pair("Grey-robed woman", "Lady Veyra")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertFalse(pair["same"])
        self.assertEqual(pair["possibly"], {"chapter": 6, "quote": ROBE_QUOTE})

    def test_a_named_figure_said_to_look_like_another_gets_a_possibly_lead_from_the_suspicion(self):
        pair = self.pair("Baron Odo", "Master Fenwick")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertIn("resemblance", pair["rules"])
        self.assertEqual(pair["possibly"], {"chapter": 5, "quote": DOUBT_QUOTE})
        odo = load_states(self.quay.workdir).entities["Baron Odo"]
        self.assertEqual([p["name"] for p in odo.get("possibly", [])], ["Master Fenwick"])


class StatedTieTest(unittest.TestCase):
    def test_a_tie_stated_with_a_hyphenated_name_written_with_a_space_is_kept(self):
        quay = Quay()
        try:
            quay.run("relate", str(quay.workdir), "--jobs", "1")
            relate = json.loads((quay.workdir / "relate.json").read_text(encoding="utf-8"))
            kept = [(r["source"], r["type"], r["target"]) for r in relate["chapters"].get("7", {}).get("relations", [])]
            self.assertEqual(kept, [("Grey-robed woman", "daughter of", "Corin Dale")], relate["chapters"].get("7"))
        finally:
            quay.close()


if __name__ == "__main__":
    unittest.main()
