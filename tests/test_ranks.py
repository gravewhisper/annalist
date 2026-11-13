import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from annalist.export import ladder_records
from annalist.ladders import ladder_needed, same_rank_pairs
from annalist.pages import Registry
from annalist.ranks import (common_words, group_key, rank_mentions, rank_names, ranked_decisions, stated_items, stated_steps,
                            text_ladders)
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
                           step("Wickbearer", 2, 4, "Circle 2: Wickbearer."), step("Candlebearer", 2, 4, "Circle 2 was once called Candlebearer"),
                           step("Night Cantor", 3, 4, "Circle 3: Night Cantor."),
                           step("Ember Abbot", 4, 4, "Circle 4: Ember Abbot.")]}]}
NEXT_SENTENCE = "Circle 3 came back to her"
SCANNED_WIDER = {"ladders": SCANNED["ladders"] + [
    {"group": "Lantern School", "steps": [step("Ashen Bell", 3, 4, f'the Lantern School\'s {NEXT_SENTENCE}. "Ashen Bell.'),
                                          step("Marsh Lantern", 4, 4, "The Lantern School's Circle 4 is called Marsh Lantern"),
                                          step("Corrow", 4, 4, 'reached a Circle 4, and Hennet only shrugged. "Corrow.')]}]}
PROOFREAD = {"entries": [{"name": "Lampwright", "type": "circle", "chapter": 4, "quotes": ["Lampwright is the first circle of the Lantern School"],
                          "why": "Lampwright is a circle of the Lantern School."}],
             "relations": [], "drop_relations": [], "questions": []}
CORRECTIONS = {"entries": [{"name": "Drowned Choir", "type": "circle"}]}


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
                {"purpose": "ladders", "contains": NEXT_SENTENCE, "reply": SCANNED_WIDER},
                {"purpose": "ladders", "contains": LISTED_CIRCLES, "reply": SCANNED},
                {"purpose": "proofread", "contains": "Lampwright", "reply": PROOFREAD},
                {"purpose": "resolve", "contains": "Candlebearer", "reply": {"same": True, "canonical_name": "Wickbearer",
                                                                           "reason": "One circle under its old and new name."}},
                {"purpose": "reveal", "contains": "Candlebearer", "reply": {"chapter": 4, "quote": "Candlebearer, Wickbearer, they are about the same",
                                                                          "reason": "Hennet says the two names are the same circle."}},
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
        (cls.book.workdir / "corrections.json").write_text(json.dumps(CORRECTIONS), encoding="utf-8")
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

    def test_a_school_named_after_its_first_circle_is_titled_with_the_group_word_as_the_book_writes_it(self):
        schools = sorted(e["name"] for e in self.wiki["entities"] if e["type"] == "school")
        self.assertIn("Gloam School", schools)
        self.assertFalse([n for n in schools if "(" in n])

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_a_page_title_never_repeats_its_type_and_same_type_namesakes_show_their_first_chapter(self):
        wiki = json.loads(json.dumps(self.wiki))
        school = next(e for e in wiki["entities"] if e["name"] == "Saltmere School")
        wiki["entities"].append({**school, "id": "twin0001", "first": 4, "name_chapter": 4, "aliases": []})
        circle = next(e for e in wiki["entities"] if e["name"] == "Tidewatcher")
        wiki["entities"].append({**circle, "id": "twin0002", "type": "elixir", "aliases": []})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
            pages = {k: re.sub(r"<[^>]+>", " ", v) for k, v in site_views(path, f"{school['id']}@5", f"{circle['id']}@5").items()}
        self.assertIn(f"Saltmere School (ch {school['first']})", pages[f"{school['id']}@5"])
        self.assertNotIn("Saltmere School (school)", pages[f"{school['id']}@5"])
        self.assertIn("Tidewatcher (circle)", pages[f"{circle['id']}@5"])

    def test_an_unlisted_step_needs_a_quote_that_names_it_and_a_name_no_other_entry_holds(self):
        steps = {s["entry"] for l in self.book.json("ladders.json") for s in l["steps"]}
        self.assertNotIn("Storm Abbot", steps)
        self.assertNotIn("Iselde Varn", steps)
        self.assertNotIn(("Storm Abbot", "circle"), self.entries)
        self.assertEqual(self.entries[("Iselde Varn", "character")]["type"], "character")

    def test_ranks_a_passage_lists_at_once_reach_the_ladder_as_entries_dated_to_that_chapter(self):
        gloam = next(l for l in self.book.json("ladders.json") if l["group"] == "Gloam")
        self.assertEqual([(s["entry"], s["rank"], s["chapter"]) for s in gloam["steps"]],
                         [("Gloam", 1, 3), ("Candlebearer", 2, 4), ("Wickbearer", 2, 4), ("Night Cantor", 3, 4), ("Ember Abbot", 4, 4)])
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

    def test_an_elixir_named_exactly_after_a_rank_moves_to_the_rank_type_and_joins_its_ladder(self):
        self.assertIn({"name": "Lamplighter", "from": "elixir", "to": "circle", "source": "rank",
                       "reason": 'The wiki records "The Circle 2 elixir of the Lantern School is Lamplighter."'}, self.book.json("types.json")["entities"])
        self.assertNotIn(("Lamplighter", "elixir"), self.entries)
        self.assertEqual(self.ladder("Lantern School")[1], ("Lamplighter", 2, 4))
        self.assertIn(("Tidewatcher elixir", "elixir"), self.entries)

    def ladder(self, group):
        name = {e["id"]: e["name"] for e in self.wiki["entities"]}
        called = {e["id"]: {e["name"]} | {a["name"] for a in e["aliases"]} for e in self.wiki["entities"]}
        ladder = next(l for l in self.wiki["ladders"] if l["group"] and group in called[l["group"]])
        return [(name[s["id"]], s["rank"], s["chapter"]) for s in ladder["steps"]]

    def test_a_rank_that_corrections_or_proofread_file_under_the_rank_type_joins_its_ladder_at_its_chapter(self):
        self.assertEqual([e["name"] for e in self.book.json("proofread.json")["entries"]], ["Lampwright"])
        self.assertEqual(self.ladder("Lantern School")[0], ("Lampwright", 1, 4))
        self.assertEqual(self.ladder("Saltmere School")[-1], ("Drowned Choir", 4, 5))

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_a_corrected_rank_is_not_on_its_ladder_before_its_chapter(self):
        saltmere = next(e["id"] for e in self.wiki["entities"] if e["name"] == "Saltmere School")
        pages = {k: re.sub(r"<[^>]+>", " ", v) for k, v in site_views(self.book.workdir / "site" / "data" / "wiki.json",
                                                                         f"{saltmere}@4", f"{saltmere}@5").items()}
        self.assertNotIn("Drowned Choir", pages[f"{saltmere}@4"])
        self.assertIn("Drowned Choir", pages[f"{saltmere}@5"])

    def test_a_rank_named_in_the_next_sentence_or_after_a_linking_verb_reaches_the_ladder(self):
        lantern = next(l for l in self.book.json("ladders.json") if l["group"] == "Lantern School")
        self.assertEqual([(s["entry"], s["rank"], s["chapter"]) for s in lantern["steps"]], [("Ashen Bell", 3, 4), ("Marsh Lantern", 4, 4)])
        self.assertEqual(self.ladder("Lantern School"), [("Lampwright", 1, 4), ("Lamplighter", 2, 4), ("Ashen Bell", 3, 4), ("Marsh Lantern", 4, 4)])
        self.assertNotIn("Corrow", {e["name"] for e in self.wiki["entities"]})

    def test_one_rank_under_two_names_in_one_group_is_one_step_once_the_text_equates_them(self):
        gloam = next(l for l in self.book.json("ladders.json") if l["group"] == "Gloam")
        self.assertEqual([(d["a"], d["b"], d["same"], d["revealed"]) for d in gloam["same"]],
                         [("Candlebearer", "Wickbearer", True, {"chapter": 4, "quote": "Candlebearer, Wickbearer, they are about the same", "basis": "quote"})])
        self.assertEqual(self.ladder("Gloam"), [("Gloam", 1, 3), ("Wickbearer", 2, 4), ("Night Cantor", 3, 4), ("Ember Abbot", 4, 4)])
        self.assertIn("Candlebearer", [a["name"] for a in self.entries[("Wickbearer", "circle")]["aliases"]])

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


class SameRankPairsTest(unittest.TestCase):
    def test_only_two_entries_at_one_rank_of_one_group_are_paired(self):
        kb = Knowledge(SPEC, power_types=RankLadderSpecTest.TYPES)
        for name in ("Candlebearer", "Wickbearer", "Night Cantor", "Tidewatcher"):
            kb.upsert_entity({"name": name, "type": "circle"}, 1)
        ladders = [{"group": "Gloam", "steps": [step("Wickbearer", 2, 4, "q"), step("Candlebearer", 2, 6, "q"), step("Night Cantor", 3, 4, "q")]},
                   {"group": "Saltmere School", "steps": [step("Tidewatcher", 2, 1, "q")]}]
        self.assertEqual(same_rank_pairs(kb, ladders), {("Candlebearer", "Wickbearer"): {"group": "Gloam", "rank": 2, "chapter": 6}})


class StatedItemsTest(unittest.TestCase):
    def test_an_item_stated_to_be_a_groups_rank_moves_unless_its_name_carries_the_item_word(self):
        kb = Knowledge(SPEC, power_types=RankLadderSpecTest.TYPES)
        for name, etype in (("Lantern School", "school"), ("Tidewatcher", "circle"), ("Tidewatcher elixir", "elixir"),
                            ("Lamplighter", "elixir"), ("Wick elixir", "elixir"), ("Ember Draught", "elixir")):
            kb.upsert_entity({"name": name, "type": etype}, 1)
        kb.facts += [{"entity": "Lamplighter", "claim": "The Circle 2 elixir of the Lantern School is Lamplighter.", "quotes": ["q"], "chapter": 1},
                     {"entity": "Ember Draught", "claim": "Ember Draught is drunk before Circle 3.", "quotes": ["q"], "chapter": 1}]
        kb.relations += [{"id": "R1", "source": "Wick elixir", "type": "is the Circle 3 elixir of", "target": "Lantern School", "quotes": ["q"], "chapter": 1}]
        self.assertEqual(stated_items(kb, "circle"), {"Lamplighter": "The Circle 2 elixir of the Lantern School is Lamplighter."})


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

    def test_the_scan_finds_a_name_after_a_linking_verb_or_standing_alone_in_the_next_sentence(self):
        text = ("At last the hill school's Circle 2 came to mind.\n\n\"Ash Reader. They read the ashes.\" Its Circle 3 was called Ember Sage.\n"
                "Nobody spoke of Circle 4 again. \"Enough. Go to bed.\"\n")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chapters").mkdir()
            (Path(tmp) / "chapters" / "0001.txt").write_text(text, encoding="utf-8")
            found = rank_mentions(tmp, [1], "circle")
        self.assertEqual([(m["name"], m["form"]) for m in found], [("Ash Reader", 'Circle 2 came to mind. "Ash Reader.'),
                                                                  ("Ember Sage", "Circle 3 was called Ember Sage")])
        self.assertEqual(found[0]["quote"], 'At last the hill school\'s Circle 2 came to mind. "Ash Reader. They read the ashes." Its Circle 3 was called Ember Sage.')


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


class JoinedGroupLaddersTest(unittest.TestCase):
    def test_ladders_whose_groups_one_page_holds_are_one_ladder(self):
        entities = [{"name": "Lantern School", "type": "school", "aliases": ["Marsh School"]},
                    *({"name": n, "type": "circle", "aliases": []} for n in ("Lampwright", "Lamplighter", "Ashen Bell", "Bell Ringer"))]
        ids = {e["name"]: e["name"] for e in entities}
        ladders = [{"group": "Lantern School", "group_type": "school", "chapter": 2,
                    "steps": [step("Lampwright", 1, 2, "q"), step("Ashen Bell", 3, 4, "q")]},
                   {"group": "Marsh School", "group_type": "school", "chapter": 3,
                    "steps": [step("Lamplighter", 2, 3, "q"), step("Bell Ringer", 3, 5, "q"), step("Lampwright", 1, 6, "q")]}]
        records = ladder_records(ladders, Registry(entities), ids, "circle")
        self.assertEqual(records, [{"group": "Lantern School", "chapter": 2, "steps": [
            {"id": "Lampwright", "rank": 1, "chapter": 2}, {"id": "Lamplighter", "rank": 2, "chapter": 3},
            {"id": "Ashen Bell", "rank": 3, "chapter": 4}, {"id": "Bell Ringer", "rank": 3, "chapter": 5}]}])


TYPES = {"school": {"parent": "organization", "description": "a school"}, "circle": {"parent": "concept", "description": "a named rank"},
         "elixir": {"parent": "artifact", "description": "a drink"}}


def chapters(tmp, *texts):
    (Path(tmp) / "chapters").mkdir()
    for n, text in enumerate(texts, 1):
        (Path(tmp) / "chapters" / f"{n:04d}.txt").write_text(text, encoding="utf-8")


def circles_kb(entries, chapter_count=1):
    kb = Knowledge(SPEC, power_types=TYPES)
    for name, etype in entries:
        kb.upsert_entity({"name": name, "type": etype}, 1)
    kb.synopses = {n: "s" for n in range(1, chapter_count + 1)}
    return kb


class RankNamesTest(unittest.TestCase):
    def names(self, text, entries=()):
        with tempfile.TemporaryDirectory() as tmp:
            chapters(tmp, text)
            kb = circles_kb(entries)
            return [(m["name"], m["form"]) for m in rank_names(kb, rank_mentions(tmp, [1], "circle"), "circle", common_words(tmp, [1]))]

    def test_openers_holders_and_kinds_of_people_are_not_ranks(self):
        text = ("Oh, Circle 2 again. However, Circle 3 is far. Maren Holt, a Circle 3, slept. Circle 4, a Mid-Circle, waits.\n"
                "The High Circles, Circle 5, rule. Nobody spoke of Circle 6. \"Indeed! They never do.\" It was indeed so.\n"
                "He was a Circle 1 Mage, she a Circle 2 Mage, and the abbot a Circle 4 Mage. Circle 3: Night Cantor.\n")
        self.assertEqual(self.names(text), [("Night Cantor", "Circle 3: Night Cantor")])

    def test_a_name_that_runs_on_past_a_known_rank_is_cut_to_it(self):
        text = ("Circle 2 Wickbearer Holt came first. Circle 2 Wickbearers are rare. Circle 3 Night Cantor's elixir burns.\n"
                "Circle 4 Ember Abbot of Hollow sang.\n")
        self.assertEqual(self.names(text, [("Wickbearer", "circle"), ("Night Cantor", "circle"), ("Ember Abbot", "circle")]),
                         [("Wickbearer", "Circle 2 Wickbearer Holt"), ("Wickbearer", "Circle 2 Wickbearers"),
                          ("Night Cantor", "Circle 3 Night Cantor's"), ("Ember Abbot of Hollow", "Circle 4 Ember Abbot of Hollow")])

    def test_a_mention_that_overlaps_the_one_before_is_dropped(self):
        self.assertEqual(self.names("Circle 1 Gloam, Circle 2 Wickbearer.\n"), [("Gloam", "Circle 1 Gloam"), ("Wickbearer", "Circle 2 Wickbearer")])


class TextLaddersTest(unittest.TestCase):
    LADDERS = [{"group": "Lantern School", "group_type": "school", "chapter": 1,
                "steps": [step("Lampwright", 1, 1, "q"), step("Lamplighter", 2, 1, "q")]},
               {"group": "Gloam (school)", "group_type": "school", "chapter": 1,
                "steps": [step("Gloam", 1, 1, "q"), step("Wickbearer", 2, 2, "q"), step("Night Cantor", 3, 1, "q")]}]
    ENTRIES = [("Lantern School", "school"), ("Lampwright", "circle"), ("Lamplighter", "circle"), ("Gloam", "circle"), ("Gloam", "school"),
               ("Wickbearer", "circle"), ("Night Cantor", "circle"), ("Candlebearer", "circle"), ("Bell Ringer", "concept"),
               ("Mira", "character"), ("Saltmere School", "school"), ("Tidewatcher", "circle")]

    def placed(self, *texts):
        with tempfile.TemporaryDirectory() as tmp:
            chapters(tmp, *texts)
            kb = circles_kb(self.ENTRIES, len(texts))
            ladders = text_ladders(tmp, kb, self.LADDERS, "circle")
        before = {(l["group"], s["entry"]) for l in self.LADDERS for s in l["steps"]}
        return [(l["group"], s["entry"], s["rank"], s["chapter"], s.get("new", False)) for l in ladders for s in l["steps"]
                if (l["group"], s["entry"]) not in before]

    def test_a_rank_whose_sentence_names_its_group_with_the_group_word_joins_that_group(self):
        self.assertEqual(self.placed("They say Circle 3 Ashen Bell belongs to the Lantern School alone. Circle 4 Marsh Lantern is far.\n"
                                     "Circle 4: Ember Abbot crowns the Gloam school.\n"),
                         [("Lantern School", "Ashen Bell", 3, 1, True), ("Gloam (school)", "Ember Abbot", 4, 1, True)])

    def test_a_rank_listed_next_to_ranks_of_one_group_at_their_numbers_joins_it(self):
        self.assertEqual(self.placed("Hennet counted. Circle 3: Night Cantor. Circle 4: Ember Abbot. Circle 5: Bell Ringer.\n"),
                         [("Gloam (school)", "Ember Abbot", 4, 1, True), ("Gloam (school)", "Bell Ringer", 5, 1, True)])

    def test_a_list_mixing_groups_or_numbers_the_ladder_does_not_give_places_nothing(self):
        self.assertEqual(self.placed("Circle 1 Lampwright, Circle 3 Night Cantor, and Circle 4 Ember Abbot.\n"
                                     "Circle 3 Lamplighter, Circle 4 Marsh Lantern.\n"
                                     "Circle 3 Night Cantor. Then, much later, after a long and windy night, came Circle 4 Ember Abbot.\n"), [])

    def test_a_list_places_nothing_before_the_ladder_holds_its_ranks(self):
        self.assertEqual(self.placed("Circle 2 Wickbearer, Circle 3 Ember Abbot.\n", "Circle 2 Wickbearer, Circle 4 Ember Abbot.\n"),
                         [("Gloam (school)", "Ember Abbot", 4, 2, True)])

    def test_another_name_for_a_listed_rank_joins_at_its_number(self):
        self.assertEqual(self.placed("Circle 1 Gloam, Circle 2 Wickbearer with the old name Candlebearer, Circle 3 Night Cantor.\n"),
                         [("Gloam (school)", "Candlebearer", 2, 1, False)])

    def test_people_and_other_kinds_of_entry_are_never_placed(self):
        self.assertEqual(self.placed("Circle 1 Gloam, Circle 2 Mira, Circle 3 Saltmere School.\n"), [])

    def test_a_group_name_written_with_its_type_in_brackets_finds_the_group_written_with_the_group_word(self):
        kb = circles_kb([("Gloam", "circle"), ("Gloam school", "school"), ("Lantern School", "school")])
        self.assertEqual([group_key(kb, n) for n in ("Gloam (school)", "Gloam", "Lantern", "Lantern (school)")],
                         ["Gloam school", "Gloam school", "Lantern School", "Lantern School"])


class RankedDecisionsTest(unittest.TestCase):
    def test_items_named_as_ranks_become_ranks_and_ranks_named_as_groups_become_groups(self):
        kb = circles_kb([("Lantern School", "school"), ("Tidewatcher", "circle"), ("Tidewatcher elixir", "elixir"), ("Lamplighter", "elixir"),
                         ("Ember Draught", "elixir"), ("Gloam", "elixir"), ("Hill school", "circle"), ("Marsh School", "school")])
        kb.facts += [{"entity": "Marsh School", "claim": "Mira is a Circle 2 Marsh School student.", "quotes": ["q"], "chapter": 1}]
        mentions = [{"chapter": 1, "name": n, "form": f"Circle 2 {n}"} for n in ("Lamplighter", "Gloam", "Tidewatcher elixir")]
        llm = [{"name": "Gloam", "from": "elixir", "to": "school", "source": "llm", "reason": "a school"},
               {"name": "Lamplighter", "from": "elixir", "to": "elixir", "source": "llm", "reason": "a brew"}]
        self.assertEqual(ranked_decisions(kb, SPEC, "circle", mentions, llm), [
            llm[0],
            {"name": "Lamplighter", "from": "elixir", "to": "circle", "source": "rank", "reason": 'The text names "Circle 2 Lamplighter" in chapter 1'},
            {"name": "Hill school", "from": "circle", "to": "school", "source": "rank", "reason": 'The name ends in "school"'}])


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
