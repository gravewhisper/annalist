import json
import subprocess
import sys
import unittest

from annalist.state import Knowledge
from annalist.survey import book_problems
from tests.test_build import LATER_REPLIES, MiniBuild, ROOT

DATA = ROOT / "tests" / "data"
EPUB = DATA / "circles.epub"

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


if __name__ == "__main__":
    unittest.main()
