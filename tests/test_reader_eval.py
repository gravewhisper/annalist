import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"


def entity(eid, name, etype, first, aliases=(), **extra):
    return {"id": eid, "name": name, "name_chapter": first, "type": etype, "first": first,
            "aliases": [{"name": n, "chapter": c} for n, c in aliases], "blurbs": [], **extra}


def question(qid, chapter, text, leads=(), **extra):
    return {"id": qid, "chapter": chapter, "question": text, "quote": "", "tier": {"arc": None, "series": None},
            "leads": [{"chapter": c, "text": t, "quote": q} for c, t, q in leads], **extra}


def resolved(chapter, answer, quote):
    return {"chapter": chapter, "shown": chapter, "answer": answer, "quote": quote, "payoff": ""}


WIKI = {
    "book": {"title": "Harbour Tales", "max": 12, "ladder": {"group_type": "school", "step_type": "rank"}, "parents": {"warding relic": "artifact"}},
    "chapters": [{"n": n, "title": f"Chapter {n}", "synopsis": ""} for n in range(1, 13)],
    "timelines": [],
    "entities": [
        entity("mara", "Mara Quill", "character", 1, aliases=[("Grey Courier", 6)]),
        entity("veil", "Veiled Rider", "character", 3, merged={"into": "mara", "chapter": 6}),
        entity("tobin", "Tobin Vale", "character", 2),
        entity("mask", "Late Mask", "character", 3, merged={"into": "tobin", "chapter": 11}),
        entity("hood", "Hooded Stranger", "character", 4,
               possibly=[{"id": "tobin", "chapter": 7, "quote": "The stranger limped exactly as Tobin did."}]),
        entity("lamp", "Brass Lantern", "artifact", 2),
        entity("bell", "Tide Bell", "warding relic", 2),
        entity("ash", "Order of Ash", "organization", 1),
        entity("ember", "Ember School", "school", 2),
        entity("tide", "Tide School", "school", 3),
        entity("spark", "Spark Adept", "rank", 2),
        entity("flame", "Flame Adept", "rank", 5),
        entity("inferno", "Inferno Adept", "rank", 11),
        entity("coral", "Coral", "rank", 3),
        entity("coralschool", "Coral School", "school", 4),
        entity("reef", "Reef", "school", 5),
        entity("sentinel", "Reef School Sentinel", "character", 5),
        entity("wraith", "Grey Wraith", "deity", 3),
        entity("tidecall", "Tidecall", "concept", 4),
        entity("dock", "Dock Seven", "uncategorized", 5),
        entity("isle", "Marow Isle", "place", 6, aliases=[("Marrow Isle", 6)]),
        entity("harbour", "Old Harbour", "place", 2, aliases=[("Harbour of Ash", 3)]),
        entity("gale", "Gale", "deity", 2, common_names=["Gale"], linked_chapters=[2, 3]),
    ],
    "facts": [
        {"id": "F1", "chapter": 8, "entity": "tobin", "claim": "Tobin felt the Gale coming for him.", "status": "stated", "by": "Tobin Vale",
         "quotes": ["I felt the Gale coming for me."]},
        {"id": "F2", "chapter": 3, "entity": "tobin", "claim": "Tobin prayed to the Gale for calm seas.", "status": "stated", "by": "narrator",
         "quotes": ["He knelt and prayed to the Gale."]},
    ],
    "relations": [
        {"chapter": 4, "source": "mara", "target": "tobin", "type": "employs", "family": "service", "status": "stated",
         "quotes": ["Mara counted out Tobin's wages."]},
        {"chapter": 11, "source": "lamp", "target": "ash", "type": "owned by", "family": "ownership", "status": "stated",
         "quotes": ["The lantern bore the Order's seal."]},
    ],
    "questions": [
        question("Q1", 2, "Who stole the brass lantern from the chapel?",
                 resolved=resolved(5, "Tobin Vale took it to pay a gambling debt.", "Tobin slipped the lantern under his coat.")),
        question("Q2", 3, "Why does the Order of Ash fear the river?",
                 resolved=resolved(8, "A flood once drowned the Order's founders.", "The water took all seven of them.")),
        question("Q3", 4, "What is written on the sealed letter?"),
        question("Q4", 5, "Where did the Hooded Stranger come from?",
                 leads=[(7, "He speaks with a northern accent.", "His vowels were flat and northern.")]),
        question("Q5", 3, "Why did the bell tower burn twice?",
                 premise={"chapter": 6, "explanation": "The tower burned only once.",
                          "quotes": [{"chapter": 6, "quote": "It had burned once, long ago, and never again."}]}),
        question("Q6", 2, "Who sends the anonymous letters?",
                 leads=[(4, "The letters smell of courier wax.", "The seal smelled of the courier's wax.")],
                 resolved=resolved(9, "Mara Quill writes and sends them.", "Mara pressed her seal into the wax.")),
        question("Q7", 9, "Who owns the silver key?", resolved=resolved(11, "The harbourmaster.", "The key hung at his belt.")),
        question("Q8", 2, "Who rang the bell at midnight?"),
        question("Q9", 7, "Who rang the bell at midnight?", resolved=resolved(8, "Tobin rang it as a signal.", "Tobin hauled the rope.")),
    ],
    "ladders": [{"group": "ember", "chapter": 2, "steps": [{"id": "spark", "rank": 1, "chapter": 2},
                                                          {"id": "flame", "rank": 2, "chapter": 5},
                                                          {"id": "inferno", "rank": 3, "chapter": 11}]},
                {"group": "coralschool", "chapter": 4, "steps": [{"id": "coral", "rank": 1, "chapter": 4}]}],
    "volumes": [{"name": "Part One", "id": "one", "from": 1, "to": 10,
                 "deaths": [{"name": "Tobin Vale", "chapter": 4}, {"name": "Tobin Vale", "chapter": 5}, {"name": "Late Mask", "chapter": 9},
                            {"name": "Mara Quill", "chapter": 9}]}],
}


def ask(text, answer, expect="resolved_in_volume", confidence="sure", raised=None, **extra):
    return {"raised": raised, "question": text, "reader_answer": answer, "expect": expect, "confidence": confidence, **extra}


KEY = {
    "source": "a made-up reader of a made-up book",
    "scope": "Part One, chapters 1-10",
    "items": [
        ask("Who stole the brass lantern from the chapel?", "Tobin, to settle what he owed at cards."),
        ask("Why does the Order of Ash fear the river?", "A river spirit cursed the Order."),
        ask("What is written on the sealed letter?", "A map of the old mines."),
        ask("Where did the Hooded Stranger come from?", "From the northern hills.", confidence="unsure"),
        ask("Why did the bell tower burn twice?", "It burned only once.", expect="false_premise"),
        ask("Who sends the anonymous letters?", "Mara sends them herself.", expect="lead_then_resolved",
            lead_chapter=4, answer_chapter=8),
        ask("Who owns the silver key?", "The harbourmaster keeps it."),
        ask("What colour is the moon above the eastern sea?", "Pale green."),
        ask("Who rang the bell at midnight?", "Tobin, as a signal to the smugglers.", raised=7),
    ],
    "expected_merges": [
        {"names": ["Veiled Rider", "Mara Quill"], "type": "character", "note": "", "confidence": "sure"},
        {"names": ["Grey Courier", "Mara Quill"], "type": "character", "note": "", "confidence": "sure"},
        {"names": ["Hooded Stranger", "Tobin Vale"], "type": "character", "note": "", "confidence": "mostly"},
        {"names": ["Hooded Stranger", "Tobin Vale"], "type": "character", "note": "", "confidence": "sure"},
        {"names": ["Late Mask", "Tobin Vale"], "type": "character", "note": "", "confidence": "sure"},
        {"names": ["Phantom Duke", "Tobin Vale"], "type": "character", "note": "", "confidence": "sure"},
        {"names": ["the Rider", "Mara Quill"], "type": "character", "note": "", "confidence": "sure"},
        {"names": ["Brass Lanterns", "Brass Lantern"], "type": "artifact", "note": "", "confidence": "sure"},
        {"names": ["Order of Ash's", "Order of Ash"], "type": "organization", "note": "", "confidence": "sure"},
    ],
    "expected_relations": [
        {"entry": "Tobin Vale", "related_to": "Mara Quill", "note": ""},
        {"entry": "Brass Lantern", "related_to": "Order of Ash", "note": ""},
        {"entry": "Phantom Duke", "related_to": "Order of Ash", "note": ""},
    ],
    "expected_structure": [
        {"what": "schools", "note": "", "min_expected": ["Ember School", "Tide School"]},
        {"what": "schools", "note": "", "min_expected": ["Ember School", "Stone School"]},
        {"what": "no duplicate deaths", "note": ""},
        {"what": "schools", "note": "", "min_expected": ["Coral", "Reef School"]},
        {"what": "kinds are not individuals", "check": "types", "expected_types": {"Grey Wraith": ["concept"], "Tidecall": ["concept"]}},
        {"what": "every entry typed", "check": "types", "expected_types": {"Brass Lantern": ["any"]}, "none_of_type": "uncategorized"},
        {"what": "title spelling", "check": "title", "entry": "Marow Isle", "expected_title": "Marrow Isle", "expected_first_chapter": 4},
        {"what": "fullest title", "check": "title", "entry": "Harbour of Ash", "expected_title": "Old Harbour", "expected_first_chapter": 2},
        {"what": "no duplicate deaths", "check": "one_death"},
        {"what": "common word", "check": "no_link", "entry": "Tobin Vale", "chapter": 8, "text": "I felt the Gale coming for me.",
         "must_not_link_to": "Gale (deity)"},
        {"what": "common word", "check": "no_link", "entry": "Tobin Vale", "chapter": 3, "text": "He knelt and prayed to the Gale.",
         "must_not_link_to": "Gale (deity)"},
        {"what": "items are items", "check": "types", "expected_types": {"Tide Bell": ["artifact"]}},
    ],
    "expected_relation_kinds": [{"pair": ["Tobin Vale", "Mara Quill"], "wording": "employs"}],
}


JUDGE = {
    "Tobin, to settle what he owed at cards.": {"verdict": "agree", "reasoning": "Both name Tobin and a debt."},
    "A river spirit cursed the Order.": {"verdict": "disagree", "reasoning": "The wiki blames a flood, the reader a curse."},
    "From the northern hills.": {"verdict": "partly", "reasoning": "The accent points north."},
    "It burned only once.": {"verdict": "agree", "reasoning": "Both say one fire."},
    "Mara sends them herself.": {"verdict": "agree", "reasoning": "Both name Mara."},
    "Tobin, as a signal to the smugglers.": {"verdict": "agree", "reasoning": "Both say Tobin signalled."},
    "A map of the old mines.": {"verdict": "agree", "reasoning": "never asked"},
    "The harbourmaster keeps it.": {"verdict": "agree", "reasoning": "never asked"},
}


class Run:
    def __init__(self, book):
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        (self.workdir / "site" / "data").mkdir(parents=True)
        (self.workdir / "site" / "data" / "wiki.json").write_text(json.dumps(WIKI), encoding="utf-8")
        script = {"replies": [{"purpose": "judge", "contains": answer, "reply": reply} for answer, reply in JUDGE.items()]}
        (self.workdir / "script.json").write_text(json.dumps(script), encoding="utf-8")
        (self.workdir / "book.json").write_text(json.dumps(book), encoding="utf-8")
        self.key = self.root / "key.json"
        self.key.write_text(json.dumps(KEY), encoding="utf-8")

    def eval(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}
        return subprocess.run([sys.executable, "-m", "annalist", "eval", str(self.workdir), *args], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=120)

    def judge_calls(self):
        path = self.workdir / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return [r for r in rows if r["purpose"] == "judge"]

    def close(self):
        self.tmp.cleanup()


FAKE = {"backend": {"name": "fake", "script": "script.json"}}


class ReaderKeyEvalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CACHE.mkdir(parents=True, exist_ok=True)
        cls.book = Run(FAKE)
        cls.proc = cls.book.eval("--reader-key", str(cls.book.key), "--judge-model", "judge-model-x")
        path = cls.book.workdir / "reader-eval.json"
        cls.report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": [], "totals": {}}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def item(self, section, n):
        return next(i for i in self.report["items"] if i["id"] == f"{section}:{n}")

    def text(self, item):
        return " ".join([item["detail"]] + item["evidence"])

    def test_eval_runs_from_a_reader_key_alone_and_writes_both_reports(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertTrue((self.book.workdir / "reader-eval.md").exists())
        self.assertFalse((self.book.workdir / "eval.json").exists())
        self.assertEqual(self.report["scope_end"], 10)

    def test_eval_with_neither_a_gold_nor_a_reader_key_is_refused(self):
        proc = self.book.eval()
        self.assertNotEqual(proc.returncode, 0)

    def test_a_resolved_question_the_judge_agrees_with_passes(self):
        item = self.item("question", 1)
        self.assertEqual(item["outcome"], "pass")
        self.assertIn("Tobin Vale took it to pay a gambling debt.", self.text(item))
        self.assertIn("Tobin slipped the lantern under his coat.", self.text(item))
        self.assertIn("ch5", self.text(item))

    def test_a_resolved_question_the_judge_disagrees_with_fails_and_keeps_the_reasoning(self):
        item = self.item("question", 2)
        self.assertEqual(item["outcome"], "fail")
        self.assertIn("The wiki blames a flood, the reader a curse.", self.text(item))

    def test_an_open_question_fails_without_a_judge_call(self):
        self.assertEqual(self.item("question", 3)["outcome"], "fail")
        self.assertIn("open", self.item("question", 3)["detail"])
        self.assertNotIn("never asked", self.text(self.item("question", 3)))
        self.assertEqual(len(self.book.judge_calls()), 6)

    def test_an_answer_shown_after_the_scope_end_leaves_the_question_open(self):
        item = self.item("question", 7)
        self.assertEqual(item["outcome"], "fail")
        self.assertIn("open", item["detail"])
        self.assertNotIn("The harbourmaster.", self.text(item))

    def test_an_unsure_reader_item_passes_on_a_quoted_lead(self):
        item = self.item("question", 4)
        self.assertEqual(item["outcome"], "pass")
        self.assertIn("His vowels were flat and northern.", self.text(item))

    def test_a_false_premise_item_passes_when_the_wiki_refutes_the_premise(self):
        item = self.item("question", 5)
        self.assertEqual(item["outcome"], "pass")
        self.assertIn("The tower burned only once.", self.text(item))

    def test_a_lead_then_resolved_item_reports_the_lead_and_answer_chapters_against_the_readers(self):
        item = self.item("question", 6)
        self.assertEqual(item["outcome"], "pass")
        text = self.text(item)
        self.assertIn("lead ch4 before the answer ch9", text)
        self.assertIn("reader lead ch4, wiki ch4", text)
        self.assertIn("reader answer ch8, wiki ch9", text)

    def test_a_question_the_wiki_never_raised_is_unmatched_with_its_best_ratio(self):
        item = self.item("question", 8)
        self.assertEqual(item["outcome"], "unmatched")
        self.assertRegex(item["detail"], r"best ratio 0\.\d\d")

    def test_the_raised_chapter_picks_between_questions_with_the_same_text(self):
        item = self.item("question", 9)
        self.assertEqual(item["outcome"], "pass")
        self.assertIn("Tobin rang it as a signal.", self.text(item))

    def test_a_merge_through_an_absorbed_page_passes_with_its_merge_chapter(self):
        self.assertEqual(self.item("merge", 1)["outcome"], "pass")
        self.assertIn("ch6", self.item("merge", 1)["detail"])

    def test_a_merge_through_an_alias_passes_with_the_alias_chapter(self):
        self.assertEqual(self.item("merge", 2)["outcome"], "pass")
        self.assertIn("ch6", self.item("merge", 2)["detail"])

    def test_a_possibly_lead_passes_a_mostly_merge_and_is_lead_only_for_a_sure_one(self):
        mostly, sure = self.item("merge", 3), self.item("merge", 4)
        self.assertEqual(mostly["outcome"], "pass")
        self.assertEqual(sure["outcome"], "lead_only")
        for item in (mostly, sure):
            self.assertIn("possibly, ch7", item["detail"])
            self.assertIn("The stranger limped exactly as Tobin did.", self.text(item))

    def test_a_merge_dated_after_the_scope_end_fails(self):
        item = self.item("merge", 5)
        self.assertEqual(item["outcome"], "fail")
        self.assertIn("ch11", item["detail"])

    def test_a_name_the_wiki_lacks_is_its_own_outcome(self):
        self.assertEqual(self.item("merge", 6)["outcome"], "name_missing")
        self.assertIn("Phantom Duke", self.item("merge", 6)["detail"])
        self.assertEqual(self.item("relation", 3)["outcome"], "name_missing")

    def test_a_plural_or_possessive_of_an_entry_name_finds_that_entry(self):
        for i in (8, 9):
            self.assertEqual(self.item("merge", i)["outcome"], "pass", self.text(self.item("merge", i)))

    def test_a_merge_name_found_by_its_words_passes(self):
        self.assertEqual(self.item("merge", 7)["outcome"], "pass")

    def test_a_relation_in_either_direction_passes_with_its_type_chapter_and_quote(self):
        item = self.item("relation", 1)
        self.assertEqual(item["outcome"], "pass")
        self.assertIn("employs", self.text(item))
        self.assertIn("ch4", self.text(item))
        self.assertIn("Mara counted out Tobin's wages.", self.text(item))

    def test_a_relation_shown_after_the_scope_end_fails(self):
        self.assertEqual(self.item("relation", 2)["outcome"], "fail")

    def test_structure_reports_the_type_count_ladder_steps_and_missing_names(self):
        whole, partial = self.item("structure", 1), self.item("structure", 2)
        self.assertEqual(whole["outcome"], "pass")
        self.assertEqual(partial["outcome"], "fail")
        self.assertIn("Stone School", partial["detail"])
        self.assertIn("4 school entries", self.text(whole))
        self.assertIn("2 ladder groups", self.text(whole))
        self.assertIn("Spark Adept", self.text(whole))
        self.assertIn("Flame Adept", self.text(whole))
        self.assertNotIn("Inferno Adept", self.text(whole))

    def test_a_structure_item_without_names_to_check_is_not_scored(self):
        self.assertEqual(self.item("structure", 3)["outcome"], "not_scored")
        self.assertIn("no duplicate deaths", self.item("structure", 3)["detail"])

    def test_a_group_named_with_or_without_its_type_word_matches_an_entry_of_that_type(self):
        item = self.item("structure", 4)
        self.assertEqual(item["outcome"], "pass", self.text(item))
        self.assertIn('Coral as "Coral School"', self.text(item))
        self.assertIn("1 Coral ch4", self.text(item))
        self.assertIn('Reef School as "Reef"', self.text(item))

    def test_a_type_check_accepts_a_book_type_whose_parent_is_the_expected_type(self):
        item = self.item("structure", 12)
        self.assertEqual(item["outcome"], "pass", self.text(item))
        self.assertIn("[warding relic]", self.text(item))

    def test_a_type_check_fails_an_entry_of_another_type_and_names_it(self):

        item = self.item("structure", 5)
        self.assertEqual(item["outcome"], "fail", self.text(item))
        self.assertIn("Grey Wraith", item["detail"])
        self.assertIn("deity", item["detail"])
        self.assertNotIn("Tidecall", item["detail"])

    def test_a_type_check_counts_the_entries_left_with_a_forbidden_type(self):
        item = self.item("structure", 6)
        self.assertEqual(item["outcome"], "fail", self.text(item))
        self.assertIn("1 uncategorized", item["detail"])
        self.assertIn("Dock Seven", self.text(item))

    def test_a_title_check_compares_the_pages_title_and_first_chapter(self):
        wrong, right = self.item("structure", 7), self.item("structure", 8)
        self.assertEqual(wrong["outcome"], "fail")
        self.assertIn('titled "Marow Isle"', wrong["detail"])
        self.assertIn("first ch6, expected ch4", wrong["detail"])
        self.assertEqual(right["outcome"], "pass", self.text(right))

    def test_a_death_check_fails_a_character_who_dies_twice_through_any_of_their_names(self):
        item = self.item("structure", 9)
        self.assertEqual(item["outcome"], "fail", self.text(item))
        self.assertIn("Tobin Vale ch4, ch5, ch9", item["detail"])
        self.assertNotIn("Mara Quill", item["detail"])

    def test_a_link_check_follows_the_chapters_a_common_word_name_is_linked_in(self):
        self.assertEqual(self.item("structure", 10)["outcome"], "pass", self.text(self.item("structure", 10)))
        linked = self.item("structure", 11)
        self.assertEqual(linked["outcome"], "fail", self.text(linked))
        self.assertIn("Tobin prayed to the Gale", self.text(linked))

    def test_totals_count_outcomes_per_section_and_the_judge_spend(self):
        totals = self.report["totals"]
        self.assertEqual(totals["questions"]["pass"], 5)
        self.assertEqual(totals["questions"]["fail"], 3)
        self.assertEqual(totals["questions"]["unmatched"], 1)
        self.assertEqual(totals["merges"]["pass"], 6)
        self.assertEqual(totals["merges"]["lead_only"], 1)
        self.assertEqual(totals["merges"]["name_missing"], 1)
        self.assertEqual(totals["structure"]["pass"], 2 + 3)
        self.assertEqual(totals["all"]["pass"], 5 + 6 + 1 + 2 + 3)
        self.assertEqual(self.report["judge_spend_usd"], 0)

    def test_the_judge_model_flag_reaches_the_backend(self):
        self.assertEqual({c["model"] for c in self.book.judge_calls()}, {"judge-model-x"})

    def test_the_judge_model_defaults_to_the_books_model_for_judging(self):
        run = Run({**FAKE, "models": {"judge": "book-judge"}})
        try:
            proc = run.eval("--reader-key", str(run.key))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual({c["model"] for c in run.judge_calls()}, {"book-judge"})
        finally:
            run.close()


if __name__ == "__main__":
    unittest.main()
