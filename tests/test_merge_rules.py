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

GREY = "Grey Shepherd of River and Reed for Mercy"
PALE = "Pale Shepherd of River and Reed for Mercy"
LISTING = ("To open the sluice by night, Corin had to set four loaves of rye bread at the four corners of the mill loft, on the beams "
           "or on the grain chests, wherever the damp could not reach them and the rats would leave them be until morning. "
           "He had to sweep the loft floor first and leave the broom by the ladder with its bristles turned up toward the roof. "
           "Then, standing in the middle of the loft with his back to the millstones, he had to walk a slow square against the "
           f"turn of the wheel. On the first step he whispered 'The {GREY}.' On the second step he held his breath. "
           f"On the last step he whispered 'The {PALE}.' Then he waited with his eyes shut until the wheel creaked twice.")
ONE_PATRON = f"Bessa said the {PALE} answers every miller who whispers the words, for the prayer is meant for one patron alone."
EQUATED = "An old Wickbearer was about the same as a modern Candlewright."

CHAPTERS = {
    1: ("The Mill",
        f"Corin Hale came to the mill at Wexbridge. Old Bessa prayed to the {GREY} at the door.\n"
        f"Later the miller muttered the {PALE} under his breath.\n"
        "Corin joined the Tallow Club, the chandlers who kept the mill lamps.\n"
        "The Candlewright Odo lit the lamps. Corin read of the Wickbearer in a torn ledger.\n"),
    2: ("The Loft", f"{LISTING}\nThe Tallow Gathering began at dusk in the loft.\n{EQUATED}\n"),
    3: ("The Answer",
        f"Corin asked Bessa again about the {GREY}, and she only smiled at the wheel.\n{ONE_PATRON}\n"),
}


def entry(name, etype, summary):
    return {"name": name, "type": etype, "aliases": [], "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [entry("Corin Hale", "character", "A young man at the mill."),
                     entry("Bessa", "character", "An old woman of the mill."),
                     entry(GREY, "deity", "A patron Bessa prays to."),
                     entry(PALE, "deity", "A name the miller mutters."),
                     entry("Tallow Club", "organization", "The chandlers who keep the mill lamps."),
                     entry("Candlewright", "rank", "The rank of the lamp keepers."),
                     entry("Wickbearer", "rank", "A rank named in an old ledger.")],
        "facts": [fact("Corin Hale", "Corin came to the mill.", "Corin Hale came to the mill at Wexbridge.")]},
    2: {"entities": [entry("Tallow Gathering", "event", "A meeting held at dusk in the loft.")],
        "facts": [fact("Corin Hale", "Corin set loaves at the corners of the loft.", "Corin had to set four loaves of rye bread")]},
    3: {"entities": [], "facts": []},
}


def same(canonical):
    return {"same": True, "canonical_name": canonical, "reason": "One and the same."}


REPLIES = [
    {"purpose": "resolve", "contains": "for the prayer is meant for one patron alone", "reply": same(GREY)},
    {"purpose": "resolve", "contains": "Name: Tallow Gathering", "reply": same("Tallow Gathering")},
    {"purpose": "resolve", "contains": "Name: Wickbearer", "reply": same("Candlewright")},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "reveal", "contains": "ENTRY A: Candlewright", "reply": {"chapter": 2, "quote": EQUATED}},
    {"purpose": "reveal", "reply": {"chapter": None, "quote": ""}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "chapter": None, "quote": ""}},
]

KIND_CHAPTERS = {
    1: ("The Chapel",
        "Ilse lit a candle for the Hollow Saint. A hollow saint is said to walk the marsh at night, "
        "and the old women claim hollow saints cannot cross running water.\n"),
    2: ("The Marsh",
        "Varn swore he had seen a hollow saint by the reeds. Two hollow saints stood there, said Ilse, and an hollow saint "
        "never walks alone. The Grey Abbot rang the chapel bell.\n"),
    3: ("The Bell",
        "Some hollow saint had left wet prints on the chapel steps. The Grey Abbot said a grey abbot keeps the bell, "
        "and the Grey Abbot kept it still. Ilse asked the Grey Abbot about grey abbots.\n"),
}

KIND_EXTRACTIONS = {
    1: {"entities": [entry("Ilse", "character", "A girl of the marsh."), entry("Hollow Saint", "deity", "A saint Ilse lights candles for.")],
        "facts": [fact("Hollow Saint", "Ilse lit a candle for the Hollow Saint.", "Ilse lit a candle for the Hollow Saint.")]},
    2: {"entities": [entry("Grey Abbot", "deity", "The keeper of the chapel bell.")],
        "facts": [fact("Grey Abbot", "The Grey Abbot rang the chapel bell.", "The Grey Abbot rang the chapel bell.")]},
    3: {"entities": [], "facts": []},
}

KIND_BOOK = {"title": "Marsh", "backend": {"name": "fake", "script": "script.json"}, "power_system": "Saints walk the marsh.",
             "timeline_kind": "linear", "power_types": {}}

KIND_REPLIES = [
    {"purpose": "retype", "contains": "Name: Hollow Saint",
     "reply": {"items": [{"id": str(i), "type": "character", "reason": "A person."} for i in range(1, 4)]}},
    {"purpose": "retype", "reply": {"items": [{"id": str(i), "type": "character", "reason": "A person."} for i in range(1, 4)]}},
    {"purpose": "link", "reply": {"labels": []}},
]


class Run:
    def __init__(self, chapters, extractions, book, replies):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        (self.workdir / "chapters").mkdir(parents=True)
        (self.workdir / "state").mkdir()
        for n, (title, text) in chapters.items():
            (self.workdir / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")
            extraction = {"synopsis": text.split(".")[0] + ".", **extractions[n], "relations": []}
            (self.workdir / "state" / f"{n:04d}.json").write_text(
                json.dumps({"chapter": n, "title": title, "extraction": extraction}), encoding="utf-8")
        for name, data in (("chapters.json", [{"index": n, "title": t, "words": len(x.split())} for n, (t, x) in chapters.items()]),
                           ("script.json", {"replies": replies}), ("book.json", book), ("build.json", {"stages": {}})):
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


class MergeRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mill = Run(CHAPTERS, EXTRACTIONS, {"title": "Mill", "backend": {"name": "fake", "script": "script.json"}}, REPLIES)
        cls.mill.run("resolve", str(cls.mill.workdir), "--jobs", "1")
        cls.pairs = json.loads((cls.mill.workdir / "merges.json").read_text(encoding="utf-8"))["pairs"]

    @classmethod
    def tearDownClass(cls):
        cls.mill.close()

    def pair(self, a, b):
        return next((d for d in self.pairs if {d["a"], d["b"]} == {a, b}), None)

    def entities(self, until):
        return load_states(self.mill.workdir, until=until).entities

    def test_the_listing_passage_is_long_enough_that_a_fixed_cut_loses_the_second_title(self):
        self.assertGreater(LISTING.index(PALE), 600)

    def test_two_titles_listed_in_one_invocation_become_one_entry_from_the_listing_chapter(self):
        pair = self.pair(GREY, PALE)
        self.assertIsNotNone(pair)
        self.assertTrue(pair["same"], pair)
        self.assertIn(GREY, self.entities(1))
        self.assertIn(PALE, self.entities(1))
        merged = self.entities(2)
        self.assertIn(GREY, merged)
        self.assertNotIn(PALE, merged)
        self.assertIn(PALE, merged[GREY]["aliases"])

    def test_a_group_and_its_meeting_named_alike_merge_into_the_group_at_the_meetings_chapter(self):
        pair = self.pair("Tallow Club", "Tallow Gathering")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertTrue(pair["same"], pair)
        self.assertNotIn("Tallow Gathering", self.entities(1))
        merged = self.entities(2)
        self.assertNotIn("Tallow Gathering", merged)
        self.assertEqual(merged["Tallow Club"]["type"], "organization")
        self.assertIn("Tallow Gathering", merged["Tallow Club"]["aliases"])

    def test_two_ranks_one_sentence_equates_are_compared_and_merge_from_that_sentence(self):
        pair = self.pair("Candlewright", "Wickbearer")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertTrue(pair["same"], pair)
        self.assertEqual(pair["revealed"]["chapter"], 2)
        self.assertIn("Wickbearer", self.entities(1))
        self.assertNotIn("Wickbearer", self.entities(2))


FAKE_NAME = '"Tobias Quill. Call me Tobias." Hadrin had long thought of a fake name.'
UNMASKED = '"I was never Ebon Marsh," Selene Thorn said. Ebon Marsh was only a false name she had worn at the docks.'

ALIAS_CHAPTERS = {
    1: ("The Inn", f"Hadrin Voss reached the inn at dusk.\n{FAKE_NAME}\nHadrin paid the baker Wren Ashby.\n"
                   "The courier Ebon Marsh met Selene Thorn on the docks.\n"),
    2: ("The Docks", "Ebon Marsh carried a sealed letter past Selene Thorn.\n"),
    3: ("The Mask", f"{UNMASKED}\n"),
}

ALIAS_EXTRACTIONS = {
    1: {"entities": [entry("Hadrin Voss", "character", "A traveller who reaches the inn."),
                     entry("Tobias Quill", "character", "Fake name Hadrin gives the innkeeper."),
                     entry("Wren Ashby", "character", "A baker Hadrin pays."),
                     entry("Selene Thorn", "character", "A woman of the docks."),
                     entry("Ebon Marsh", "character", "A courier of the docks."),
                     entry("Dorian Pike", "character", "A trader at the market."),
                     entry("Ulric Fenn", "character", "Alias Dorian uses at the market."),
                     entry("Orla Keane", "character", "Pseudonym written in a market ledger.")],
        "facts": [fact("Hadrin Voss", "Hadrin reached the inn.", "Hadrin Voss reached the inn at dusk.")]},
    2: {"entities": [], "facts": []},
    3: {"entities": [entry("Ebon Marsh", "character", "False name Selene wore as a courier at the docks."),
                     entry("Ulric Fenn", "character", "A market regular who sells eels."),
                     entry("Orla Keane", "character", "A debtor Dorian found in the ledger.")], "facts": []},
}

ALIAS_REPLIES = [
    {"purpose": "resolve", "contains": "Name: Tobias Quill", "reply": same("Hadrin Voss")},
    {"purpose": "resolve", "contains": "Name: Ebon Marsh", "reply": same("Selene Thorn")},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "reveal", "contains": "ENTRY A: Hadrin Voss", "reply": {"chapter": 1, "quote": FAKE_NAME}},
    {"purpose": "reveal", "contains": "ENTRY A: Ebon Marsh", "reply": {"chapter": 3, "quote": UNMASKED}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "chapter": None, "quote": ""}},
]


class FalseNameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inn = Run(ALIAS_CHAPTERS, ALIAS_EXTRACTIONS, {"title": "Inn", "backend": {"name": "fake", "script": "script.json"}},
                      ALIAS_REPLIES)
        cls.inn.run("resolve", str(cls.inn.workdir), "--jobs", "1")
        cls.pairs = json.loads((cls.inn.workdir / "merges.json").read_text(encoding="utf-8"))["pairs"]

    @classmethod
    def tearDownClass(cls):
        cls.inn.close()

    def pair(self, a, b):
        return next((d for d in self.pairs if {d["a"], d["b"]} == {a, b}), None)

    def entities(self, until):
        return load_states(self.inn.workdir, until=until).entities

    def test_a_false_name_sharing_no_words_with_its_owner_is_merged_from_the_chapter_that_says_so(self):
        pair = self.pair("Hadrin Voss", "Tobias Quill")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertTrue(pair["same"], pair)
        self.assertEqual(pair["revealed"], {"chapter": 1, "quote": FAKE_NAME, "basis": "quote"})
        merged = self.entities(1)
        self.assertNotIn("Tobias Quill", merged)
        self.assertIn("Tobias Quill", merged["Hadrin Voss"]["aliases"])

    def test_a_secret_identity_stays_two_entries_until_the_chapter_that_reveals_it(self):
        pair = self.pair("Ebon Marsh", "Selene Thorn")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertTrue(pair["same"], pair)
        self.assertEqual(pair["revealed"]["chapter"], 3)
        before = self.entities(2)
        self.assertIn("Ebon Marsh", before)
        self.assertNotIn("Ebon Marsh", before["Selene Thorn"]["aliases"])
        after = self.entities(3)
        self.assertNotIn("Ebon Marsh", after)
        self.assertIn("Ebon Marsh", after["Selene Thorn"]["aliases"])

    def test_a_summary_that_names_someone_without_calling_it_a_false_name_proposes_nothing(self):
        self.assertIsNone(self.pair("Hadrin Voss", "Wren Ashby"))

    def test_a_false_name_cue_in_an_earlier_summary_is_still_proposed_after_a_later_summary_drops_it(self):
        self.assertEqual(self.entities(3)["Ulric Fenn"]["summary"], "A market regular who sells eels.")
        pair = self.pair("Dorian Pike", "Ulric Fenn")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertIn("false-name: 'Alias'", pair["rules"])

    def test_a_cue_and_an_owner_named_only_in_different_summaries_propose_nothing(self):
        self.assertIsNone(self.pair("Dorian Pike", "Orla Keane"))


class KindNameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.marsh = Run(KIND_CHAPTERS, KIND_EXTRACTIONS, KIND_BOOK, KIND_REPLIES)
        cls.marsh.run("retype", str(cls.marsh.workdir), "--jobs", "1")
        cls.decisions = {d["name"]: d for d in json.loads((cls.marsh.workdir / "types.json").read_text(encoding="utf-8"))["entities"]}
        cls.kb = load_states(cls.marsh.workdir)

    @classmethod
    def tearDownClass(cls):
        cls.marsh.close()

    def test_a_name_the_text_mostly_uses_as_a_kind_is_a_concept_without_asking_the_model(self):
        self.assertEqual(self.kb.entities["Hollow Saint"]["type"], "concept")
        self.assertNotEqual(self.decisions["Hollow Saint"]["source"], "llm")

    def test_a_name_the_text_mostly_uses_as_a_name_is_still_typed_by_the_model(self):
        self.assertEqual(self.decisions["Grey Abbot"]["source"], "llm")
        self.assertEqual(self.kb.entities["Grey Abbot"]["type"], "character")


if __name__ == "__main__":
    unittest.main()
