import json
import unittest

from annalist.export import entity_id
from tests.test_build import MiniBuild, build_script, plan_rows, ran

VOLUMES = ("--volumes", "1-3,4-5")
FENN = "Their commander was Captain Fenn, a thin, careful man with ink on his cuffs who had been a clerk before he was a soldier."
LAMP = "The harbour lamp of Corvel Quay had burned every night for two hundred years, except one."
KEEPER = "Tomas was the keeper of the harbour lamp and a sworn member of the Lamplighters' Guild"
SLIPPED = "“He slipped in the fog,” the Captain said."
PROBE = "the prompt held chapter 4"

CHARACTERS = {
    "entries": [
        {"name": "Captain Fenn", "same_as": "Odile Marr", "chapter": 3, "quotes": [FENN], "why": "The text calls her the Captain."},
        {"name": "Sabine Oake", "title": "Master Sabine Oake", "title_chapter": 1,
         "quotes": ["Sabine Oake had been master of the Lamplighters' Guild for eleven years."]},
        {"name": "Tomas Hale", "fields": {"occupation": [{"chapter": 1, "value": "keeper of the harbour lamp", "quotes": [KEEPER]}]}},
        {"name": "Ines Varro", "drop": {"age": [{"chapter": 1, "value": "nineteen"}]}},
        {"name": "Harbourmaster Quill", "type": "place", "chapter": 1, "quotes": [LAMP]},
    ],
    "relations": [
        {"source": "Tomas Hale", "target": "Salt Ledger", "type": "wrote in", "status": "stated", "chapter": 2,
         "quotes": ["He wrote the hour of lighting in the Salt Ledger every night, in his square careful hand"]},
        {"source": "Bram Ostrow", "target": "Ines Varro", "type": "oldest friend of", "chapter": 1,
         "quotes": ["Bram had loved her since the day they met."]},
    ],
    "drop_relations": [{"source": "Brannoc Abbey", "target": "Corvel Quay", "type": "located near", "chapter": 3}],
    "questions": [],
}
WORLD = {"entries": [{"name": "harbour lamp", "type": "place", "chapter": 1, "quotes": [LAMP], "why": "A lamp tower is a place."}]}
MYSTERIES = {"questions": [
    {"id": "Q0003-01", "chapter": 3, "answer": "Captain Fenn said he slipped in the fog.", "quotes": [SLIPPED]},
    {"id": "Q0003-04", "dismiss": True, "why": "Bram says why at once."},
    {"id": "Q0002-01", "chapter": 4, "answer": "She lived and became Sister Wren.", "quotes": ["My name was Livia Hale."]},
    {"id": "Q0003-02", "chapter": 3, "answer": "She was going to tell him about the rosemary.", "quotes": ["Sister Wren looked at him for a long moment."]},
]}
CHAPTER_FOUR = {"relations": [{"source": "Ines Varro", "target": "Tomas Hale", "type": "mourns", "chapter": 4, "quotes": ["no such line"], "why": PROBE}]}


def proofread_script():
    script = build_script()
    script["replies"][:0] = [{"purpose": "proofread", "contains": "They buried Tomas Hale in the Guild plot", "reply": CHAPTER_FOUR}] + [
        {"purpose": "proofread", "contains": f"as it stands after chapter 3: the {title}.", "reply": reply}
        for title, reply in (("characters", CHARACTERS), ("places, organizations, and other entries", WORLD), ("questions a reader noted", MYSTERIES))]
    return script


def entity(wiki, name):
    return next(e for e in wiki["entities"] if e["name"] == name)


def ties(wiki):
    names = {e["id"]: e["name"] for e in wiki["entities"]}
    return {(names[r["source"]], r["type"], names[r["target"]], r["chapter"]) for r in wiki["relations"]}


class ProofreadBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(proofread_script())
        cls.first = cls.book.build(*VOLUMES)
        cls.asked = len(cls.book.calls("proofread"))
        cls.second = cls.book.build(*VOLUMES)
        cls.review = cls.book.json("proofread.json")
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_the_review_runs_after_the_stages_it_reviews_and_before_render(self):
        stages = ran(self.first.stdout)
        self.assertEqual(stages[stages.index("volumes"):stages.index("volumes") + 3], ["volumes", "proofread", "render"])

    def test_a_join_and_a_type_change_rewrite_the_pages(self):
        self.assertNotIn("Captain Fenn", {e["name"] for e in self.wiki["entities"]})
        self.assertIn({"name": "Captain Fenn", "chapter": 3}, entity(self.wiki, "Odile Marr")["aliases"])
        self.assertEqual(entity(self.wiki, "harbour lamp")["type"], "place")

    def test_a_title_and_infobox_values_reach_the_pages(self):
        oake = entity(self.wiki, "Master Sabine Oake")
        self.assertEqual((oake["id"], oake["name_chapter"]), (entity_id("Sabine Oake"), 1))
        tomas = entity(self.wiki, "Tomas Hale")["profile"]["fields"]
        self.assertIn(("keeper of the harbour lamp", 1), [(o["value"], o["chapter"]) for o in tomas["occupation"]])
        ines = entity(self.wiki, "Ines Varro").get("profile", {}).get("fields", {})
        self.assertNotIn("nineteen", [o["value"] for o in ines.get("age", [])])

    def test_ties_are_added_and_removed(self):
        self.assertIn(("Tomas Hale", "wrote in", "Salt Ledger", 2), ties(self.wiki))
        self.assertNotIn(("Brannoc Abbey", "located near", "Corvel Quay", 3), ties(self.wiki))

    def test_questions_are_answered_from_their_chapter_or_dismissed(self):
        questions = {q["id"]: q for q in self.wiki["questions"]}
        self.assertEqual((questions["Q0003-01"]["resolved"]["shown"], questions["Q0003-01"]["resolved"]["answer"]),
                         (3, "Captain Fenn said he slipped in the fog."))
        self.assertNotIn("Q0003-04", questions)

    def test_a_bad_quote_a_chapter_outside_the_volume_a_later_word_or_an_unknown_name_is_rejected_and_logged(self):
        rejected = {(r["list"], r["reason"]) for r in self.review["rejected"] if r["volume"] == "Volume 1"}
        self.assertEqual(rejected, {("relations", "no quote found in chapter 1"),
                                    ("questions", "chapter 4 is outside chapters 1-3"),
                                    ("questions", "uses rosemary, which the book first uses after chapter 3"),
                                    ("entries", "names no entry 'Harbourmaster Quill'")})
        self.assertNotIn("oldest friend of", {t[1] for t in ties(self.wiki)})
        answers = " ".join((q.get("resolved") or {}).get("answer", "") for q in self.wiki["questions"])
        self.assertNotIn("rosemary", answers)
        self.assertNotIn("became Sister Wren", answers)
        self.assertNotIn("Harbourmaster Quill", {e["name"] for e in self.wiki["entities"]})

    def test_the_accepted_rows_are_kept_in_their_own_file_in_the_corrections_format(self):
        self.assertEqual(sorted(r["name"] for r in self.review["entries"]),
                         ["Captain Fenn", "Ines Varro", "Sabine Oake", "Tomas Hale", "harbour lamp"])
        self.assertEqual([(r["source"], r["type"], r["target"], r["chapter"]) for r in self.review["relations"]],
                         [("Tomas Hale", "wrote in", "Salt Ledger", 2)])
        self.assertEqual([r["id"] for r in self.review["questions"]], ["Q0003-01", "Q0003-04"])
        self.assertFalse((self.book.workdir / "corrections.json").exists())

    def test_no_session_sees_a_chapter_past_its_volume(self):
        probed = {r["volume"] for r in self.review["rejected"] if r["row"].get("why") == PROBE}
        self.assertEqual(probed, {"Volume 2"})

    def test_the_review_asks_at_high_effort_by_default(self):
        self.assertEqual({c.get("effort") for c in self.book.calls("proofread")}, {"high"})

    def test_a_rerun_with_the_same_wiki_and_text_calls_nothing(self):
        self.assertEqual(plan_rows(self.second.stdout)["proofread"], "done")
        self.assertEqual(ran(self.second.stdout), [])
        self.assertEqual(len(self.book.calls("proofread")), self.asked)

    def test_a_rerun_of_the_stage_reuses_every_session(self):
        book = MiniBuild(proofread_script())
        try:
            book.build(*VOLUMES)
            asked = len(book.calls("proofread"))
            book.edit_code("proofread.py", 'PURPOSE = "proofread"', 'PURPOSE = "proofread"\nRULES = 2')
            rebuilt = book.build(*VOLUMES)
            self.assertEqual(plan_rows(rebuilt.stdout)["proofread"], "run: code changed")
            self.assertIn("proofread", ran(rebuilt.stdout))
            self.assertEqual(len(book.calls("proofread")), asked)
        finally:
            book.close()

    def test_a_budget_stops_before_a_session_the_cache_cannot_answer(self):
        book = MiniBuild(proofread_script())
        try:
            book.build(*VOLUMES)
            for path in (book.workdir / "cache").glob("proofread-*.json"):
                path.unlink()
            asked = len(book.calls("proofread"))
            stopped = book.run_annalist("proofread", str(book.workdir), "--budget", "0", check=False)
            self.assertEqual(stopped.returncode, 1)
            self.assertIn("spent $0.00 of the $0.00 budget; stopping before the proofread of Volume 1", stopped.stderr)
            self.assertEqual(len(book.calls("proofread")), asked)
            book.run_annalist("proofread", str(book.workdir))
            asked = len(book.calls("proofread"))
            book.run_annalist("proofread", str(book.workdir), "--budget", "0")
            self.assertEqual(len(book.calls("proofread")), asked)
        finally:
            book.close()


class UserWinsTest(unittest.TestCase):
    def test_the_users_corrections_win_over_a_conflicting_proposal(self):
        book = MiniBuild(proofread_script())
        try:
            mine = {"entries": [{"name": "harbour lamp", "type": "concept"}],
                    "questions": [{"id": "Q0003-04", "chapter": 3, "answer": "He was looking for them.",
                                   "quotes": ["“Looking for you,” said Bram."]}]}
            (book.workdir / "corrections.json").write_text(json.dumps(mine), encoding="utf-8")
            book.build(*VOLUMES)
            review = book.json("proofread.json")
            self.assertIn(("harbour lamp", "place"), [(r["name"], r.get("type")) for r in review["entries"]])
            self.assertIn(("Q0003-04", True), [(r["id"], r.get("dismiss")) for r in review["questions"]])
            wiki = book.json("site/data/wiki.json")
            self.assertEqual(entity(wiki, "harbour lamp")["type"], "concept")
            answered = next(q for q in wiki["questions"] if q["id"] == "Q0003-04")["resolved"]
            self.assertEqual((answered["shown"], answered["answer"]), (3, "He was looking for them."))
            self.assertEqual(json.loads((book.workdir / "corrections.json").read_text(encoding="utf-8")), mine)
        finally:
            book.close()

    def test_an_edit_to_corrections_json_asks_no_proofread_session(self):
        book = MiniBuild(proofread_script())
        try:
            book.build(*VOLUMES)
            asked = len(book.calls("proofread"))
            (book.workdir / "corrections.json").write_text(json.dumps({"entries": [{"name": "Kestrel", "type": "place"}]}), encoding="utf-8")
            rebuilt = book.build(*VOLUMES)
            self.assertEqual(ran(rebuilt.stdout), ["render", "export"])
            self.assertEqual(len(book.calls("proofread")), asked)
        finally:
            book.close()


class PartsTest(unittest.TestCase):
    def test_a_volume_too_large_for_one_window_is_read_in_consecutive_parts_against_each_slice(self):
        script = proofread_script()
        script["replies"].insert(0, {"purpose": "proofread", "contains": "full text of chapters 2 to 2 of a novel", "reply": {"relations": [
            {"source": "Tomas Hale", "target": "Salt Ledger", "type": "wrote in", "chapter": 2,
             "quotes": ["He wrote the hour of lighting in the Salt Ledger every night, in his square careful hand"]},
            {"source": "Tomas Hale", "target": "Corvel Quay", "type": "lives in", "chapter": 3, "quotes": [FENN]}]}})
        book = MiniBuild(script)
        try:
            book.edit_code("proofread.py", "PART_TOKENS = WINDOW_TOKENS - REPLY_TOKENS - SLICE_TOKENS", "PART_TOKENS = 2000")
            book.build(*VOLUMES)
            review = book.json("proofread.json")
            parts = {(s["volume"], tuple(s["chapters"])) for s in review["sessions"]}
            self.assertEqual(parts, {("Volume 1", (1, 1)), ("Volume 1", (2, 2)), ("Volume 1", (3, 3)), ("Volume 2", (4, 4)), ("Volume 2", (5, 5))})
            slices = {}
            for s in review["sessions"]:
                slices.setdefault(s["slice"], set()).add(tuple(s["chapters"]))
            self.assertEqual(slices["mysteries-1"], {(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)})
            self.assertEqual(len(book.calls("proofread")), len(review["sessions"]))
            self.assertIn(("Tomas Hale", "wrote in", "Salt Ledger", 2), [(r["source"], r["type"], r["target"], r["chapter"]) for r in review["relations"]])
            self.assertIn("chapter 3 is outside chapters 2-2", {r["reason"] for r in review["rejected"]})
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()
