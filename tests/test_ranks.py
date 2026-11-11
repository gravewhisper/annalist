import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from annalist.ladders import ladder_needed
from annalist.ranks import rank_mentions, stated_steps
from annalist.review import ranks_off_ladder
from annalist.state import Knowledge
from annalist.survey import book_problems
from tests.test_build import LATER_REPLIES, MiniBuild, ROOT, site_views

DATA = ROOT / "tests" / "data"
EPUB = DATA / "circles.epub"
NODE = shutil.which("node")

SURVEY = {"power_system": "Students of each school climb its own named circles, one at a time, by drinking the elixir of the next circle.",
          "power_types": [{"type": "school", "parent": "organization", "description": "a school that trains students through its own circles"},
                          {"type": "circle", "parent": "concept", "description": "a named rank within a school, such as Tidewatcher"},
                          {"type": "elixir", "parent": "artifact", "description": "a drink that opens the next circle to a student"}],
          "rank_word": "Circle",
          "relation_example": "first circle of",
          "extra_fields": [{"name": "current circle", "description": "the circle the character stands at, written as its name",
                            "values": ["Tidewatcher", "Brine Warden"]}],
          "power_keywords": ["circle", "elixir", "school", "tide"],
          "timeline_kind": "linear", "timeline_note": "The story runs in order over one year at the school."}
NO_RANK_TYPE = {**SURVEY, "power_types": [t for t in SURVEY["power_types"] if t["type"] != "circle"]}

SPEC = {"group_type": "school", "step_type": "circle", "rank": "number", "direction": "ascending",
        "note": "Each school ranks its own circles, the lowest first."}


def step(entry, rank, chapter, quote):
    return {"entry": entry, "rank": rank, "chapter": chapter, "quote": quote}


LADDERS = {"ladders": [
    {"group": "Saltmere School", "steps": [step("Tidewatcher", 1, 1, "Ours begins at Circle 1: Tidewatcher."),
                                           step("Brine Warden", 2, 2, "Brine Warden is Circle 2 of the Saltmere School."),
                                           step("Iselde Varn", 1, 5, "Iselde Varn, Circle 1, sat very still")]},
    {"group": "Gloam", "steps": [step("Gloam", 1, 3, "Gloam is the name of our school and the name of its first circle"),
                                 step("Storm Abbot", 4, 4, "Circle 4: Ember Abbot.")]},
]}

LISTED_CIRCLES = "names Circle 1: Gloam; Circle 2: Wickbearer; Circle 3: Night Cantor; Circle 4: Ember Abbot"
SCANNED = {"ladders": [LADDERS["ladders"][0],
                       {"group": "Gloam", "steps": LADDERS["ladders"][1]["steps"] + [
                           step("Wickbearer", 2, 4, "Circle 2: Wickbearer."), step("Night Cantor", 3, 4, "Circle 3: Night Cantor."),
                           step("Ember Abbot", 4, 4, "Circle 4: Ember Abbot.")]}]}


def circles_script():
    extractions = json.loads((DATA / "circles-extractions.json").read_text(encoding="utf-8"))
    replies = []
    for key, ext in extractions.items():
        ids = [f"F{i}" for i in range(1, len(ext["facts"]) + 1)] + [f"R{i}" for i in range(1, len(ext["relations"]) + 1)]
        replies += [{"purpose": "extract", "chapter": int(key), "reply": ext},
                    {"purpose": "support", "chapter": int(key), "reply": {"verdicts": [{"id": i, "verdict": "supported"} for i in ids]}}]
    replies += [{"purpose": "book", "reply": NO_RANK_TYPE}, {"purpose": "book", "reply": SURVEY},
                {"purpose": "ladder-spec", "reply": {"ladder": {**SPEC, "step_type": "elixir"}}},
                {"purpose": "ladder-spec", "reply": {"ladder": SPEC}},
                {"purpose": "ladders", "contains": LISTED_CIRCLES, "reply": SCANNED},
                {"purpose": "ladders", "reply": LADDERS}]
    replies += [{"purpose": p, "reply": r} for p, r in LATER_REPLIES.items() if p != "book"]
    return {"replies": replies}


class CirclesBuild(MiniBuild):
    def build(self, *extra, check=True):
        proc = subprocess.run([sys.executable, "-m", "annalist", "build", str(EPUB), str(self.workdir), "--yes", *extra],
                              cwd=self.code, env=self.env, capture_output=True, text=True, timeout=300)
        if check and proc.returncode:
            raise AssertionError(f"build exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc


class NamedRanksBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = CirclesBuild(circles_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.entries = {(e["name"], e["type"]): e for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_a_survey_that_names_ranks_without_a_type_for_them_is_asked_again(self):
        calls = self.book.calls("book")
        self.assertEqual(len(calls), 2)
        self.assertIn('rank_word is "circle", so the novel names its ranks, but no power type holds them', calls[0]["error"])
        self.assertIsNone(calls[1]["error"])
        book = self.book.json("book.json")
        self.assertEqual(book["rank_word"], "circle")
        self.assertEqual(book["power_types"]["circle"], {"parent": "concept", "description": "a named rank within a school, such as Tidewatcher"})
        self.assertEqual(list(book["extra_fields"]), ["current_circle"])

    def test_a_ladder_whose_steps_are_an_item_kind_instead_of_the_rank_type_is_asked_again(self):
        calls = self.book.calls("ladder-spec")
        self.assertEqual(len(calls), 2)
        self.assertIn('step_type must be "circle", the type of the ranks themselves', calls[0]["error"])
        self.assertIsNone(calls[1]["error"])
        self.assertEqual(self.book.json("book.json")["ladder"], SPEC)

    def test_a_rank_the_read_filed_under_the_group_type_moves_to_the_rank_type_and_onto_its_ladder(self):
        self.assertIn(("Brine Warden", "circle"), self.entries)
        self.assertNotIn(("Brine Warden", "school"), self.entries)
        self.assertIn({"name": "Brine Warden", "from": "school", "to": "circle", "source": "rank",
                       "reason": 'The wiki records "Brine Warden is Circle 2 of the Saltmere School."'}, self.book.json("types.json")["entities"])
        saltmere = next(l for l in self.book.json("ladders.json") if l["group"] == "Saltmere School")
        self.assertEqual([(s["entry"], s["rank"]) for s in saltmere["steps"]][:2], [("Tidewatcher", 1), ("Brine Warden", 2)])

    def test_a_school_named_after_its_first_circle_gets_that_circle_as_its_own_entry_and_first_step(self):
        school = next(e for e in self.wiki["entities"] if e["type"] == "school" and e["name"] in ("Gloam", "Gloam School"))
        circle = self.entries[("Gloam", "circle")]
        self.assertNotEqual(school["id"], circle["id"])
        self.assertEqual(circle["first"], 3)
        gloam = next(l for l in self.book.json("ladders.json") if l["group"] == "Gloam")
        self.assertEqual(gloam["steps"][0], {"entry": "Gloam", "rank": 1, "chapter": 3, "new": True,
                                             "quote": "Gloam is the name of our school and the name of its first circle"})
        ladder = next(l for l in self.wiki["ladders"] if l["group"] == school["id"])
        self.assertEqual(ladder["steps"][0], {"id": circle["id"], "rank": 1, "chapter": 3})

    def test_an_unlisted_step_needs_a_quote_that_names_it_and_a_name_no_other_entry_holds(self):
        steps = {s["entry"] for l in self.book.json("ladders.json") for s in l["steps"]}
        self.assertNotIn("Storm Abbot", steps)
        self.assertNotIn("Iselde Varn", steps)
        self.assertNotIn(("Storm Abbot", "circle"), self.entries)
        self.assertEqual(self.entries[("Iselde Varn", "character")]["type"], "character")

    def test_ranks_a_passage_lists_at_once_reach_the_ladder_as_entries_dated_to_that_chapter(self):
        gloam = next(l for l in self.book.json("ladders.json") if l["group"] == "Gloam")
        self.assertEqual([(s["entry"], s["rank"], s["chapter"]) for s in gloam["steps"]],
                         [("Gloam", 1, 3), ("Wickbearer", 2, 4), ("Night Cantor", 3, 4), ("Ember Abbot", 4, 4)])
        made = {e["name"]: e["first_chapter"] for e in self.book.json("entities.json") if e["type"] == "circle"}
        self.assertEqual([made[n] for n in ("Wickbearer", "Night Cantor", "Ember Abbot")], [4, 4, 4])

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_a_rank_the_ladder_adds_is_not_ranked_before_its_chapter(self):
        wick, cantor = (self.entries[(n, "circle")]["id"] for n in ("Wickbearer", "Night Cantor"))
        pages = site_views(self.book.workdir / "site" / "data" / "wiki.json", f"{wick}@3", f"{wick}@4", f"{cantor}@3")
        self.assertNotRegex(re.sub(r"<[^>]+>", " ", pages[f"{wick}@3"]), r"circle 2 of")
        self.assertRegex(re.sub(r"<[^>]+>", " ", pages[f"{wick}@4"]), r"circle 2 of")
        self.assertIn("Not yet introduced", pages[f"{cantor}@3"])

    def test_the_review_lists_ranks_the_text_names_that_no_ladder_holds(self):
        check = next(c for c in self.book.json("review.json")["checks"] if c["key"] == "ranks_off_ladder")
        self.assertEqual(check["title"], "Ranks the text names that are not on a ladder")
        self.assertEqual(check["findings"], [{"name": "Gale Reader", "chapter": 5, "form": "Circle 3: Gale Reader", "entry": None,
                                              "text": "**Gale Reader** (Circle 3: Gale Reader, ch 5): no entry"}])

    def test_an_item_named_after_a_rank_links_to_the_rank(self):
        name = {e["id"]: (e["name"], e["type"]) for e in self.wiki["entities"]}
        links = {(name[r["source"]], r["type"], name[r["target"]]) for r in self.wiki["relations"]}
        self.assertIn((("Tidewatcher elixir", "elixir"), "elixir of", ("Tidewatcher", "circle")), links)


class RankWordTest(unittest.TestCase):
    NOVEL = "Ours begins at Circle 1: Tidewatcher."

    def test_a_rank_word_the_material_never_shows_is_sent_back(self):
        self.assertIn('rank_word "tier" never appears in the material', book_problems({**SURVEY, "rank_word": "Tier"}, Knowledge(), None, self.NOVEL))

    def test_a_rank_word_with_a_type_named_by_it_passes(self):
        self.assertIsNone(book_problems(SURVEY, Knowledge(), None, self.NOVEL))
        self.assertIsNone(book_problems({**NO_RANK_TYPE, "power_types": NO_RANK_TYPE["power_types"]
                                         + [{"type": "school circle", "parent": "concept", "description": "a named rank"}]},
                                        Knowledge(), None, self.NOVEL))

    def test_a_book_without_named_ranks_needs_no_rank_type(self):
        self.assertIsNone(book_problems({**NO_RANK_TYPE, "rank_word": ""}, Knowledge(), None, self.NOVEL))


class StatedStepsTest(unittest.TestCase):
    def kb(self, claims, relations=()):
        kb = Knowledge(SPEC, power_types={"school": {"parent": "organization", "description": ""}, "circle": {"parent": "concept", "description": ""}})
        for name in ("Saltmere School", "Brine Warden", "Gloam", "Night Cantor", "Lantern", "Wick"):
            kb.upsert_entity({"name": name, "type": "school"}, 1)
        kb.facts += [{"entity": entity, "claim": claim} for entity, claim in claims]
        kb.relations += [{"source": s, "type": t, "target": o} for s, t, o in relations]
        return kb

    def test_an_entry_of_the_group_type_stated_to_be_a_numbered_or_ordered_rank_is_a_step(self):
        kb = self.kb([("Brine Warden", "Brine Warden is Circle 2 of the Saltmere School."),
                      ("Gloam", "Gloam is the name of the school and of its first circle."),
                      ("Night Cantor", "Night Cantor is the third circle of Gloam.")],
                     [("Wick", "is the second circle of", "Lantern")])
        self.assertEqual(stated_steps(kb, SPEC, "circle"), {"Brine Warden": "Brine Warden is Circle 2 of the Saltmere School.",
                                                            "Night Cantor": "Night Cantor is the third circle of Gloam.",
                                                            "Wick": "Wick is the second circle of Lantern"})

    def test_an_entry_the_text_also_gives_ranks_of_its_own_stays_a_group(self):
        kb = self.kb([("Lantern", "Circle 1: Lantern is where every student begins."), ("Lantern", "Circle 2 of Lantern is Wick."),
                      ("Wick", "Corrow asked for the circle 3 Wick school formula.")],
                     [("Gloam", "is the first circle of", "Saltmere School"), ("Night Cantor", "is Circle 3 of", "Gloam")])
        self.assertEqual(stated_steps(kb, SPEC, "circle"), {"Night Cantor": "Night Cantor is Circle 3 of Gloam"})


class RankMentionTest(unittest.TestCase):
    def test_the_scan_finds_the_rank_word_and_a_number_next_to_a_capitalized_name(self):
        text = ("They keep three circles. Circle 1: Lamp Wick. Then Circle Two, the Lantern Bearer.\n"
                "If Circle 3 opens, Maren Holt, Circle 3, will know. This circle 4 is closed. Circle 2, Circles of the Deep.\n"
                "Circle 5, I've heard, is worse.\n")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            (Path(tmp) / "chapters" / "0001.txt").write_text(text, encoding="utf-8")
            found = rank_mentions(tmp, [1], "circle")
        self.assertEqual([(m["name"], m["form"]) for m in found], [("Lamp Wick", "Circle 1: Lamp Wick"),
                                                                  ("Lantern Bearer", "Circle Two, the Lantern Bearer"),
                                                                  ("Maren Holt", "Maren Holt, Circle 3")])
        self.assertEqual(found[0]["quote"], "They keep three circles. Circle 1: Lamp Wick. Then Circle Two, the Lantern Bearer.")


class RanksOffLadderTest(unittest.TestCase):
    def test_people_and_organizations_holding_a_rank_are_not_listed_as_ranks(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            (Path(tmp) / "chapters" / "0001.txt").write_text(
                "The Lamp Guild, Circle 2, kept watch. Maren Holt, Circle 3, slept. Circle 4: Ember Abbot.\n", encoding="utf-8")
            kb = Knowledge(SPEC)
            kb.upsert_entity({"name": "Lamp Guild", "type": "organization"}, 1)
            kb.upsert_entity({"name": "Maren Holt", "type": "character"}, 1)
            kb.synopses[1] = "The watch is kept."
            run = SimpleNamespace(workdir=Path(tmp), kb=kb, until=1, book={"rank_word": "circle", "power_types": {}, "ladder": SPEC})
            found = ranks_off_ladder(run)
        self.assertEqual([(f["name"], f["form"]) for f in found], [("Ember Abbot", "Circle 4: Ember Abbot")])


class RankLadderSpecTest(unittest.TestCase):
    TYPES = {"school": {"parent": "organization", "description": "a school"}, "circle": {"parent": "concept", "description": "a named rank"},
             "elixir": {"parent": "artifact", "description": "a drink"}}

    def test_a_stored_ladder_stepping_through_an_item_kind_is_regenerated_once_the_book_has_a_rank_type(self):
        on_items = {"rank_word": "circle", "power_types": self.TYPES, "ladder": {**SPEC, "step_type": "elixir"}}
        self.assertTrue(ladder_needed(on_items))
        self.assertFalse(ladder_needed({**on_items, "ladder": SPEC}))

    def test_a_book_without_a_rank_word_keeps_any_valid_ladder(self):
        self.assertFalse(ladder_needed({"power_types": self.TYPES, "ladder": {**SPEC, "step_type": "elixir"}}))


if __name__ == "__main__":
    unittest.main()
