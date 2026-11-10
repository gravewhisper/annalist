import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from annalist.state import load_states
from tests.test_backends import stub_claude
from tests.test_build import site_views

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"
NODE = shutil.which("node")

CHAPTERS = {
    1: ("The Parcel",
        "Fog lay on the lane when a grey-cloaked courier left a sealed parcel at the door of Maren Tull's workshop. "
        "Maren Tull watched the grey-cloaked courier walk away without a word. Dovric Hallam, the ferryman, was already "
        "drinking at the inn across the lane. Pell Quarry swept the step and grumbled about the cold.\n\n"
        "A limping beggar sat by the well and asked Pell Quarry for a coin. Pell Quarry gave him nothing.\n\n"
        "That night a veiled singer sang under the bridge, and Maren Tull stopped to listen. Isolde Fane, the innkeeper's "
        "daughter, closed the shutters against the song.\n\n"
        "Maren Tull set her brass compass on the bench beside the parcel.\n"),
    2: ("The Bells",
        "The tide bell rang twice before the harbour gong answered it from the pier. Maren Tull opened the parcel and "
        "found an instrument wrapped in oilcloth. The Wayfinder was Maren Tull's heirloom, a needle in a polished case.\n\n"
        "A hooded watcher crouched on the roof above the inn. Pell Quarry did not look up.\n\n"
        "A drowned sailor lay tangled in kelp beneath the pier, a silver earring in one ear.\n"),
    3: ("The Ferryman",
        "Dovric Hallam hung a grey cloak on the peg by Maren Tull's door. \"I was the grey-cloaked courier who left the "
        "parcel,\" Dovric Hallam told her. \"Your grandmother paid me to carry it.\" The tide bell rang as he spoke, and "
        "the harbour gong answered across the water.\n\n"
        "An ashen clerk copied the ferry ledger in the corner and never looked up.\n"),
    4: ("The Song",
        "Isolde Fane hummed the tune the veiled singer had sung under the bridge, and would not say where she had "
        "learned it. Maren Tull said nothing and turned the Wayfinder in her hands.\n\n"
        "An elderly couple waited at the gate, and Pell Quarry embraced his parents before he went to sweep the step.\n"),
    5: ("The Needle",
        "Maren Tull held the brass compass beside the Wayfinder and saw at last that they were one instrument. "
        "The brass compass was the Wayfinder, its case only polished new. The limping beggar was gone from the well.\n"),
    6: ("The Notice",
        "Isolde Fane read the harbour notice aloud. The body found tangled in kelp beneath the pier was Corwin Ashby, who wore "
        "a silver earring.\n"),
}


def person(name, summary):
    return {"name": name, "type": "character", "aliases": [], "summary": summary}


def thing(name, summary):
    return {"name": name, "type": "artifact", "aliases": [], "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [person("Maren Tull", "A workshop keeper on the lane."),
                     person("Dovric Hallam", "The ferryman."),
                     person("Pell Quarry", "A sweeper who grumbles about the cold."),
                     person("Isolde Fane", "The innkeeper's daughter."),
                     person("Grey-cloaked courier", "A courier in a grey cloak who leaves a sealed parcel."),
                     person("Limping beggar", "A beggar by the well."),
                     person("Veiled singer", "A singer under the bridge at night."),
                     thing("Brass compass", "Maren Tull's brass compass, kept on her bench.")],
        "facts": [fact("Maren Tull", "Maren Tull watched the courier walk away.",
                       "Maren Tull watched the grey-cloaked courier walk away without a word."),
                  fact("Grey-cloaked courier", "The grey-cloaked courier left a sealed parcel at Maren Tull's workshop.",
                       "a grey-cloaked courier left a sealed parcel at the door of Maren Tull's workshop"),
                  fact("Limping beggar", "The limping beggar asked Pell Quarry for a coin.",
                       "A limping beggar sat by the well and asked Pell Quarry for a coin."),
                  fact("Veiled singer", "The veiled singer sang under the bridge at night.",
                       "That night a veiled singer sang under the bridge, and Maren Tull stopped to listen.")]},
    2: {"entities": [person("Maren Tull", "A workshop keeper on the lane."),
                     person("Pell Quarry", "A sweeper who grumbles about the cold."),
                     person("Hooded watcher", "A figure crouched on the roof above the inn, probably Pell Quarry."),
                     thing("Wayfinder", "Maren Tull's heirloom instrument, a needle in a polished case."),
                     thing("Tide bell", "A bell that rings with the tide."),
                     thing("Harbour gong", "A gong on the pier."),
                     person("Drowned sailor", "A drowned sailor tangled in kelp beneath the pier, with a silver earring.")],
        "facts": [fact("Hooded watcher", "A hooded watcher crouched on the roof above the inn.",
                       "A hooded watcher crouched on the roof above the inn."),
                  fact("Drowned sailor", "A drowned sailor lay tangled in kelp beneath the pier, wearing a silver earring.",
                       "A drowned sailor lay tangled in kelp beneath the pier, a silver earring in one ear.")]},
    3: {"entities": [person("Dovric Hallam", "The ferryman, who carried the parcel."),
                     person("Maren Tull", "A workshop keeper on the lane."),
                     person("Ashen clerk", "A clerk copying the ferry ledger."),
                     person("Old man", "A man who fed the gulls from the pier."),
                     thing("Tide bell", "A bell that rings with the tide."),
                     thing("Harbour gong", "A gong on the pier.")],
        "facts": [fact("Ashen clerk", "The ashen clerk copied the ferry ledger.",
                       "An ashen clerk copied the ferry ledger in the corner and never looked up."),
                  fact("Old man", "An old man fed the gulls from the pier.", "An old man fed the gulls from the pier at dawn.")]},
    4: {"entities": [person("Isolde Fane", "The innkeeper's daughter, who hums an old tune."),
                     person("Maren Tull", "A workshop keeper on the lane."),
                     person("Pell Quarry", "A sweeper who grumbles about the cold."),
                     person("Elderly couple", "An elderly couple waiting at the gate, Pell Quarry's parents."),
                     thing("Wayfinder", "Maren Tull's heirloom instrument, a needle in a polished case.")],
        "facts": [fact("Elderly couple", "An elderly couple waited at the gate for Pell Quarry.",
                       "An elderly couple waited at the gate, and Pell Quarry embraced his parents")]},
    5: {"entities": [person("Maren Tull", "A workshop keeper on the lane."),
                     thing("Brass compass", "Maren Tull's brass compass, kept on her bench."),
                     thing("Wayfinder", "Maren Tull's heirloom instrument, a needle in a polished case."),
                     person("Limping beggar", "A beggar by the well.")],
        "facts": []},
    6: {"entities": [person("Isolde Fane", "The innkeeper's daughter, who hums an old tune."),
                     person("Corwin Ashby", "A seaman lost in spring, found beneath the pier tangled in kelp, wearing a silver earring.")],
        "facts": [fact("Corwin Ashby", "Corwin Ashby's body was found beneath the pier, tangled in kelp, with his silver earring.",
                       "The body found tangled in kelp beneath the pier was Corwin Ashby, who wore a silver earring.")]},
}

COURIER_QUOTE = "\"I was the grey-cloaked courier who left the parcel,\" Dovric Hallam told her."
SINGER_QUOTE = "Isolde Fane hummed the tune the veiled singer had sung under the bridge, and would not say where she had learned it."
SAILOR_QUOTE = "The body found tangled in kelp beneath the pier was Corwin Ashby, who wore a silver earring."
COUPLE_QUOTE = "An elderly couple waited at the gate, and Pell Quarry embraced his parents before he went to sweep the step."
COMPASS_QUOTE = "The brass compass was the Wayfinder, its case only polished new."

REPLIES = [
    {"purpose": "identify", "contains": "Name: Grey-cloaked courier",
     "reply": {"candidate": "Dovric Hallam", "basis": "explicit", "same_individual": True, "chapter": 3, "quote": COURIER_QUOTE}},
    {"purpose": "identify", "contains": "Name: Veiled singer",
     "reply": {"candidate": "Isolde Fane", "basis": "implied", "same_individual": True, "chapter": 4, "quote": SINGER_QUOTE}},
    {"purpose": "identify", "contains": "Name: Ashen clerk",
     "reply": {"candidate": "Dovric Hallam", "basis": "explicit", "same_individual": True, "chapter": 3,
               "quote": "Dovric Hallam admitted that he was the ashen clerk at the ferry."}},
    {"purpose": "identify", "contains": "was Corwin Ashby, who wore a silver earring",
     "reply": {"candidate": "Corwin Ashby", "basis": "explicit", "same_individual": True, "chapter": 6, "quote": SAILOR_QUOTE}},
    {"purpose": "identify", "contains": "Name: Elderly couple",
     "reply": {"candidate": "Pell Quarry", "basis": "explicit", "same_individual": False, "chapter": 4, "quote": COUPLE_QUOTE,
               "reason": "The couple are Pell Quarry's parents."}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "chapter": None, "quote": ""}},
    {"purpose": "resolve", "contains": "Name: Wayfinder",
     "reply": {"same": True, "canonical_name": "Wayfinder", "reason": "Both are Maren Tull's heirloom instrument."}},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "reveal", "contains": "ENTRY B: Wayfinder", "reply": {"chapter": 5, "quote": COMPASS_QUOTE}},
    {"purpose": "reveal", "reply": {"chapter": None, "quote": ""}},
]


class Town:
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
        (self.workdir / "book.json").write_text(json.dumps({"title": "Town", "backend": {"name": "fake", "script": "script.json"}}),
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

    def json(self, name):
        return json.loads((self.workdir / name).read_text(encoding="utf-8"))

    def close(self):
        self.tmp.cleanup()


class IdentifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.town = Town()
        cls.town.run("resolve", str(cls.town.workdir), "--jobs", "1")
        cls.town.run("export", str(cls.town.workdir), str(cls.town.workdir / "site"))
        cls.pairs = cls.town.json("merges.json")["pairs"]
        cls.wiki = cls.town.json("site/data/wiki.json")
        cls.entry = {e["name"]: e for e in cls.wiki["entities"]}
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.town.close()

    def pair(self, a, b):
        return [d for d in self.pairs if {d["a"], d["b"]} == {a, b}]

    def entities(self, until):
        return load_states(self.town.workdir, until=until).entities

    def site(self, *views):
        return site_views(self.town.workdir / "site" / "data" / "wiki.json", *views)

    def test_a_descriptor_the_text_names_merges_into_the_named_entry_from_that_chapter(self):
        self.assertIn("Grey-cloaked courier", self.entities(2))
        self.assertNotIn("Grey-cloaked courier", self.entities(3))
        self.assertIn("Grey-cloaked courier", self.entities(3)["Dovric Hallam"]["aliases"])
        self.assertEqual(self.entry["Grey-cloaked courier"]["merged"], {"into": self.id["Dovric Hallam"], "chapter": 3})
        identified = [d for d in self.pair("Grey-cloaked courier", "Dovric Hallam") if d["same"]]
        self.assertEqual([d["revealed"] for d in identified], [{"chapter": 3, "quote": COURIER_QUOTE, "basis": "quote"}])

    def test_a_descriptor_linked_only_by_its_description_merges_into_the_named_entry_the_text_identifies(self):
        self.assertIn("Drowned sailor", self.entities(5))
        self.assertNotIn("Drowned sailor", self.entities(6))
        self.assertIn("Drowned sailor", self.entities(6)["Corwin Ashby"]["aliases"])
        self.assertEqual(self.entry["Drowned sailor"]["merged"], {"into": self.id["Corwin Ashby"], "chapter": 6})
        identified = [d for d in self.pair("Drowned sailor", "Corwin Ashby") if d["same"]]
        self.assertEqual([d["revealed"] for d in identified], [{"chapter": 6, "quote": SAILOR_QUOTE, "basis": "quote"}])

    def test_a_group_that_includes_the_named_character_is_not_merged_into_them(self):
        self.assertIn("Elderly couple", self.entities(5))
        self.assertIn("Pell Quarry", self.entities(5))
        self.assertNotIn("merged", self.entry["Elderly couple"])
        self.assertNotIn("possibly", self.entry["Elderly couple"])
        self.assertFalse([d for d in self.pairs if "Elderly couple" in (d["a"], d["b"]) and d["same"]])

    def test_an_implied_identity_stays_apart_and_is_offered_as_a_dated_lead(self):
        self.assertIn("Veiled singer", self.entities(5))
        self.assertNotIn("merged", self.entry["Veiled singer"])
        self.assertNotIn("possibly", self.entities(3)["Veiled singer"])
        self.assertEqual(self.entities(4)["Veiled singer"]["possibly"], [{"name": "Isolde Fane", "chapter": 4, "quote": SINGER_QUOTE}])
        self.assertEqual(self.entry["Veiled singer"]["possibly"], [{"id": self.id["Isolde Fane"], "chapter": 4, "quote": SINGER_QUOTE}])

    def test_a_quote_the_chapter_does_not_hold_identifies_no_one(self):
        self.assertIn("Ashen clerk", self.entities(5))
        self.assertNotIn("merged", self.entry["Ashen clerk"])
        self.assertNotIn("possibly", self.entry["Ashen clerk"])
        self.assertFalse([d for d in self.pairs if d["a"] == "Ashen clerk" and d["same"]])

    def test_a_descriptor_with_no_distinctive_words_and_no_located_quote_identifies_no_one(self):
        self.assertIn("Old man", self.entities(5))
        self.assertTrue(self.entry["Old man"].get("nameless"))
        self.assertNotIn("merged", self.entry["Old man"])
        self.assertNotIn("possibly", self.entry["Old man"])
        self.assertFalse([d for d in self.pairs if d["a"] == "Old man" and d["same"]])

    def test_descriptors_are_marked_nameless_and_named_entries_are_not(self):
        for name in ("Grey-cloaked courier", "Veiled singer", "Limping beggar", "Ashen clerk", "Hooded watcher"):
            self.assertTrue(self.entry[name].get("nameless"), name)
        for name in ("Maren Tull", "Dovric Hallam", "Isolde Fane", "Wayfinder", "Brass compass"):
            self.assertNotIn("nameless", self.entry[name])

    def test_two_things_one_owner_holds_are_compared_and_merged_from_the_revealing_chapter(self):
        [pair] = self.pair("Brass compass", "Wayfinder")
        self.assertIn("same-holder: Maren Tull", pair["rules"])
        self.assertEqual(pair["revealed"], {"chapter": 5, "quote": COMPASS_QUOTE, "basis": "quote"})
        self.assertEqual(self.entry["Brass compass"]["merged"], {"into": self.id["Wayfinder"], "chapter": 5})
        self.assertIn("Brass compass", self.entities(4))

    def test_two_things_named_in_one_sentence_in_two_chapters_are_compared(self):
        [pair] = self.pair("Harbour gong", "Tide bell")
        self.assertIn("co-mentioned", pair["rules"])
        self.assertFalse(pair["same"])

    def test_an_entry_whose_summary_says_it_is_probably_another_is_compared_with_it(self):
        self.assertTrue(any("hedged-identity" in d["rules"] for d in self.pair("Hooded watcher", "Pell Quarry")))

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_site_shows_the_lead_only_from_its_chapter(self):
        singer = self.id["Veiled singer"]
        pages = self.site(f"{singer}@3", f"{singer}@4")
        self.assertNotIn("Possibly", pages[f"{singer}@3"])
        self.assertNotIn("Isolde Fane", pages[f"{singer}@3"])
        later = pages[f"{singer}@4"]
        self.assertIn("Possibly", later)
        self.assertIn(f'data-ent="{self.id["Isolde Fane"]}"', later)
        self.assertIn("implied, ch 4", later)
        self.assertIn("would not say where she had learned it", later)

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_category_page_lists_unnamed_figures_after_the_named_entries(self):
        pages = self.site("route:cat:character@2", "route:cat:character@3")
        early, later = pages["route:cat:character@2"]["html"], pages["route:cat:character@3"]["html"]
        head = early.index("Unnamed figures")
        self.assertLess(early.index("Maren Tull"), head)
        self.assertGreater(early.index("Grey-cloaked courier"), head)
        self.assertGreater(early.index("Limping beggar"), head)
        self.assertNotIn("Grey-cloaked courier", later)
        self.assertGreater(later.index("Veiled singer"), later.index("Unnamed figures"))


if __name__ == "__main__":
    unittest.main()
