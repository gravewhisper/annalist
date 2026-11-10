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
from tests.test_build import site_views

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"

CHAPTERS = {
    1: ("The Shrine",
        "Neve Strand climbed to the shrine above Kessandra. She swore by the God of Brine and Salt that she would come back.\n"
        "She chanted the Warden of Sea and Sky for Mercy on the first step and the Keeper of Sea and Sky for Mercy on the last, "
        "both names of the one old god of the shrine.\nHard frost covered the steps, and the frost bit her hands.\n"),
    2: ("The Bells",
        "At the Church of Ashlight the candles burned low. Neve walked past the Church of the Veil on her way down. "
        "The God of Brine and Salt was silent. The bells of Kessandra rang. They sang 'The Hollow Crown of Dusk' twice. The frost was thick. A Tide Warden stood by the door while the Tide Wardens kept watch.\n"),
    3: ("The Storm",
        "\"By Brine!\" Neve cried as the wave broke. The Ashlight Veil watched over her. Pilgrims came from Kesendra, "
        "or perhaps from Kessandra, she was never sure. "
        "At dusk she praised the Warden of Sea and Sky for Mercy and the Keeper of Sea and Sky for Mercy again. "
        "Neve prayed to Frost, the cold god of the peaks.\n"),
    4: ("The Quiet",
        "\"By Brine, I am done,\" Neve said. The Church of the Veil rang its bells, and the Church of Ashlight answered. "
        "Kessandra lay quiet under the snow. She sensed the approach of Frost on the hill, though it was only the frost of evening. A Tide Warden nodded, another Tide Warden laughed, and the Tide Wardens left Neve's lantern by the gate.\n\"The Hollow Crown of Dusk,\" she whispered.\n"),
}


def entry(name, etype, summary, aliases=()):
    return {"name": name, "type": etype, "aliases": list(aliases), "summary": summary}


def fact(entity, claim, quote):
    return {"entity": entity, "claim": claim, "quotes": [quote], "asserted_by": "narrator", "status": "stated"}


EXTRACTIONS = {
    1: {"entities": [entry("Neve Strand", "character", "A pilgrim."),
                     entry("God of Brine", "deity", "The God of Brine and Salt, by whom Neve swears."),
                     entry("Sky", "place", "The sky over the shrine.")],
        "facts": [fact("Neve Strand", "Neve swore by the God of Brine and Salt.",
                       "She swore by the God of Brine and Salt that she would come back."),
                  fact("Neve Strand", "Neve climbed to the shrine.", "Neve Strand climbed to the shrine above Kessandra.")]},
    2: {"entities": [entry("Church of Ashlight", "organization", "A church where candles burn."),
                     entry("Tide Wardens", "organization", "Guards of the shore.", aliases=["Tide Warden"]),
                     entry("Lantern", "artifact", "Neve's lantern.", aliases=["Neve's lantern"])],
        "facts": [fact("Church of Ashlight", "Candles burned at the Church of Ashlight.",
                       "At the Church of Ashlight the candles burned low."),
                  fact("Neve Strand", "Neve walked past the Church of the Veil.", "Neve walked past the Church of the Veil on her way down.")]},
    3: {"entities": [entry("Ashlight Veil", "deity", "A goddess who watches over Neve."),
                     entry("Kesendra", "place", "A town pilgrims come from.", aliases=["Kessandra"]),
                     entry("Frost", "deity", "The cold god of the peaks.")],
        "facts": [fact("Kesendra", "Pilgrims came from Kesendra.", "Pilgrims came from Kesendra, or perhaps from Kessandra"),
                  fact("Neve Strand", "Neve prayed to Frost.", "Neve prayed to Frost, the cold god of the peaks."),
                  fact("Frost", "Frost is the cold god of the peaks.", "Frost, the cold god of the peaks.")]},
    4: {"entities": [], "facts": [fact("Neve Strand", "Neve sensed the approach of Frost on the hill.",
                                       "She sensed the approach of Frost on the hill")]},
}

DISCOVERED = [
    {"name": "Warden of Sea and Sky for Mercy", "type": "deity", "summary": "A title chanted on the first step.", "chapter": 1},
    {"name": "Keeper of Sea and Sky for Mercy", "type": "deity", "summary": "A title chanted on the last step.", "chapter": 1},
    {"name": "Church of the Veil", "type": "organization", "summary": "A church whose bells ring.", "chapter": 2},
    {"name": "Brine", "type": "deity", "summary": "Invoked in the oath 'By Brine'.", "chapter": 3},
]


def same(canonical):
    return {"same": True, "canonical_name": canonical, "reason": "One and the same."}


REPLIES = [
    {"purpose": "resolve", "contains": "Name: Brine\n", "reply": same("God of Brine")},
    {"purpose": "resolve", "contains": "Name: Keeper of Sea and Sky for Mercy", "reply": same("Warden of Sea and Sky for Mercy")},
    {"purpose": "resolve", "contains": "Name: Church of the Veil", "reply": same("Church of Ashlight")},
    {"purpose": "resolve", "reply": {"same": False, "canonical_name": "", "reason": "Different."}},
    {"purpose": "reveal", "contains": "ENTRY A: Keeper of Sea and Sky for Mercy",
     "reply": {"chapter": 1, "quote": "both names of the one old god of the shrine."}},
    {"purpose": "reveal", "contains": "ENTRY A: Church of Ashlight",
     "reply": {"chapter": 4, "quote": "The Church of the Veil rang its bells, and the Church of Ashlight answered."}},
    {"purpose": "reveal", "reply": {"chapter": None, "quote": ""}},
    {"purpose": "identify", "reply": {"candidate": "", "basis": "none", "chapter": None, "quote": ""}},
    {"purpose": "summary", "contains": "Neve sensed the approach of Frost", "reply": {"summary": "Neve, at the end."}},
    {"purpose": "summary", "contains": "Neve walked past", "reply": {"summary": "Neve, a pilgrim so far."}},
    {"purpose": "summary", "reply": {"summary": "Another entry."}},
    {"purpose": "personality", "reply": {"paragraph": "Calm (ch 1)."}},
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
        self.write("chapters.json", [{"index": n, "title": title, "words": len(text.split())} for n, (title, text) in CHAPTERS.items()])
        self.write("discover.json", {"entities": DISCOVERED, "rejected": []})
        self.write("script.json", {"replies": REPLIES})
        self.write("book.json", {"title": "Shrine", "backend": {"name": "fake", "script": "script.json"}})
        self.write("build.json", {"stages": {}})
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}
        self.env.update(stub_claude(self.root, "", 1))

    def write(self, name, data):
        (self.workdir / name).write_text(json.dumps(data), encoding="utf-8")

    def run(self, *args):
        proc = subprocess.run([sys.executable, "-m", "annalist", *args], cwd=ROOT, env=self.env, capture_output=True, text=True,
                              timeout=120)
        if proc.returncode:
            raise AssertionError(f"annalist {args[0]} exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc

    def close(self):
        self.tmp.cleanup()


class TitleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shrine = Shrine()
        cls.shrine.run("resolve", str(cls.shrine.workdir), "--jobs", "1")
        cls.pairs = json.loads((cls.shrine.workdir / "merges.json").read_text(encoding="utf-8"))["pairs"]
        cls.shrine.run("render", str(cls.shrine.workdir))
        cls.shrine.run("export", str(cls.shrine.workdir), str(cls.shrine.workdir / "site"))
        wiki = json.loads((cls.shrine.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        cls.pages = {e["name"]: e for e in wiki["entities"] if not e.get("merged")}
        cls.wiki_path = cls.shrine.workdir / "site" / "data" / "wiki.json"

    @classmethod
    def tearDownClass(cls):
        cls.shrine.close()

    def pair(self, a, b):
        return next((d for d in self.pairs if {d["a"], d["b"]} == {a, b}), None)

    def test_a_discovered_name_is_compared_with_the_entries_it_shares_words_with(self):
        pair = self.pair("Brine", "God of Brine")
        self.assertIsNotNone(pair, [(d["a"], d["b"]) for d in self.pairs])
        self.assertTrue(any(r.startswith("name-containment") for r in pair["rules"]), pair["rules"])

    def test_titles_listed_together_for_one_being_are_compared(self):
        pair = self.pair("Keeper of Sea and Sky for Mercy", "Warden of Sea and Sky for Mercy")
        self.assertIsNotNone(pair)
        self.assertTrue(any(r.startswith("listed-together") for r in pair["rules"]), pair["rules"])

    def test_two_names_built_on_two_names_of_one_other_entry_are_compared(self):
        pair = self.pair("Church of Ashlight", "Church of the Veil")
        self.assertIsNotNone(pair)
        self.assertIn("same-frame: Ashlight Veil", pair["rules"])

    def test_names_of_one_kind_listed_together_with_one_shared_word_are_not_compared(self):
        self.assertIsNone(self.pair("Neve Strand", "God of Brine"))

    def test_the_title_is_the_fullest_form_the_text_uses_and_the_shorter_forms_stay_aliases(self):
        page = self.pages.get("God of Brine and Salt")
        self.assertIsNotNone(page, sorted(self.pages))
        self.assertEqual(page["name_chapter"], 1)
        self.assertIn("God of Brine", [a["name"] for a in page["aliases"]])
        self.assertIn("Brine", [a["name"] for a in page["aliases"]])

    def test_a_plural_name_and_a_possessive_form_never_replace_the_title(self):
        self.assertIn("Tide Wardens", self.pages)
        self.assertIn("Lantern", self.pages)

    def test_spelling_variants_take_the_most_used_spelling_and_the_earliest_chapter_of_any(self):
        page = self.pages.get("Kessandra")
        self.assertIsNotNone(page, sorted(self.pages))
        self.assertEqual(page["first"], 1)
        self.assertEqual(page["name_chapter"], 1)
        self.assertEqual([a["name"] for a in page["aliases"]], ["Kesendra"])


    def test_a_name_the_text_mostly_writes_as_a_common_word_links_only_where_the_chapter_names_its_entry(self):
        frost, neve = self.pages["Frost"], self.pages["Neve Strand"]
        self.assertEqual(frost["common_names"], ["Frost"])
        self.assertEqual(frost["linked_chapters"], [3])
        self.assertEqual(self.pages["Kessandra"].get("common_names", []), [])
        html = site_views(self.wiki_path, f"{neve['id']}@4")[f"{neve['id']}@4"]
        prayed = html[html.index("Neve prayed to"):][:300]
        sensed = html[html.index("Neve sensed the approach of"):][:300]
        self.assertIn(f'data-ent="{frost["id"]}"', prayed)
        self.assertNotIn(f'data-ent="{frost["id"]}"', sensed)


    def test_the_lede_is_a_summary_written_from_the_facts_known_by_the_chapter(self):
        neve = self.pages["Neve Strand"]
        self.assertEqual(neve["summaries"], [{"chapter": 2, "text": "Neve, a pilgrim so far."}])
        self.assertEqual(neve["summary"]["text"], "Neve, at the end.")
        pages = site_views(self.wiki_path, *(f"{neve['id']}@{n}" for n in (1, 3)))
        self.assertIn("A pilgrim.", pages[f"{neve['id']}@1"])
        self.assertIn("Neve, a pilgrim so far.", pages[f"{neve['id']}@3"])
        self.assertIn("As understood at chapter 2", pages[f"{neve['id']}@3"])


class FullTitleDiscoverTest(unittest.TestCase):
    def test_a_title_joined_by_and_or_for_is_found_whole(self):
        shrine = Shrine()
        try:
            (shrine.workdir / "discover.json").unlink()
            found = {c["name"] for c in candidates(shrine.workdir, load_states(shrine.workdir, discovered=False))}
            self.assertIn("Warden of Sea and Sky for Mercy", found)
            self.assertNotIn("Warden of Sea", found)
            self.assertIn("Hollow Crown of Dusk", found)
        finally:
            shrine.close()


if __name__ == "__main__":
    unittest.main()
