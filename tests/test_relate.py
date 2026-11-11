import json
import unittest

from tests.test_build import MiniBuild, build_script, ran

TOMAS_ODILE = "Tomas had spoken with Odile Marr for an hour that morning in the back room of the harbour inn"

RELATE_CH3 = {"relations": [
    {"source": "Tomas Hale", "type": "confided in by", "target": "Odile Marr", "quote": TOMAS_ODILE,
     "asserted_by": "narrator", "status": "stated"},
    {"source": "Tomas Hale", "type": "father of", "target": "Sister Wren", "quote": "Sister Wren is Tomas's lost daughter.",
     "asserted_by": "narrator", "status": "stated"},
    {"source": "Sabine Oake", "type": "enemy of", "target": "Sister Wren", "quote": "The sisters called her Sister Wren.",
     "asserted_by": "narrator", "status": "stated"},
    {"source": "Tomas Hale", "type": "acting on news from", "target": "Odile Marr",
     "quote": "Then I will wait until the end of the month", "asserted_by": "Tomas Hale", "status": "implied"},
    {"source": "Tomas Hale", "type": "member of", "target": "Lamplighters’ Guild", "quote": TOMAS_ODILE,
     "asserted_by": "narrator", "status": "stated"},
]}

RELATE_CH4 = {"relations": [
    {"source": "Ines's lantern", "type": "carried past", "target": "Sabine Oake", "quote": '"Master Oake," said Ines.',
     "asserted_by": "narrator", "status": "stated"},
]}

WATCH_HOUSE = ("They went to the watch house on the quay, and they found Odile Marr already there, sitting on a bench in her blue coat "
               "with her arms folded.")

RELATE_WATCH_HOUSE = {"relations": [
    {"source": "Odile Marr", "type": "waited at", "target": "watch house", "quote": WATCH_HOUSE, "asserted_by": "narrator", "status": "stated"},
]}


def relate_script():
    script = build_script()
    script["replies"].insert(0, {"purpose": "relate", "contains": "CHAPTER 3: The Abbey Stair", "reply": RELATE_CH3})
    script["replies"].insert(1, {"purpose": "relate", "contains": "CHAPTER 4: Two Names", "reply": RELATE_CH4})
    script["replies"].insert(2, {"purpose": "relate", "contains": "- watch house [place]", "reply": RELATE_WATCH_HOUSE})

    def extract(n):
        return next(r for r in script["replies"] if r["purpose"] == "extract" and r.get("chapter") == n)["reply"]

    extract(4)["entities"].append({"name": "Ines's lantern", "type": "artifact", "aliases": [], "summary": "The lantern Ines carries on the harbour wall."})
    extract(5)["entities"].append({"name": "watch house", "type": "place", "aliases": [], "summary": "Where the quay watch keeps its bench."})
    return script


class RelateMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(relate_script())
        cls.book.build()
        cls.relate = cls.book.json("relate.json")
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def shown(self, chapter):
        names = {e["id"]: e["name"] for e in self.wiki["entities"]}
        return {(names[r["source"]], r["type"], names[r["target"]]) for r in self.wiki["relations"] if r["chapter"] == chapter}

    def test_a_relation_whose_quote_is_in_the_chapter_and_names_both_entries_is_added_at_that_chapter(self):
        self.assertIn(("Tomas Hale", "confided in by", "Odile Marr"), self.shown(3))
        self.assertEqual([r["type"] for r in self.relate["chapters"]["3"]["relations"]], ["confided in by", "acting on news from"])

    def test_a_line_whose_other_entry_is_named_a_paragraph_away_is_kept(self):
        self.assertIn(("Tomas Hale", "acting on news from", "Odile Marr"), self.shown(3))

    def test_a_quote_missing_from_the_chapter_a_quote_naming_one_side_and_a_known_relation_are_rejected(self):
        reasons = {r["relation"]["type"]: r["reason"] for r in self.relate["chapters"]["3"]["rejected"]}
        self.assertEqual(reasons, {"father of": "quote not found in the chapter",
                                   "enemy of": "the quote and the text around it do not name both entries",
                                   "member of": "already known"})
        self.assertFalse({r for r in self.shown(3) if r[1] in ("father of", "enemy of")})

    def test_an_entry_named_for_its_owners_possession_is_not_named_by_the_owners_name_alone(self):
        rejected = [(r["relation"]["source"], r["reason"]) for r in self.relate["chapters"]["4"]["rejected"]]
        self.assertEqual(rejected, [("Ines's lantern", "the quote and the text around it do not name both entries")])
        self.assertFalse([r for r in self.shown(4) if r[0] == "Ines's lantern"])

    def test_an_entry_the_chapter_names_outside_its_most_frequent_pairs_can_still_be_related(self):
        self.assertIn(("Odile Marr", "waited at", "watch house"), self.shown(5))

    def test_every_chapter_with_entries_named_together_is_asked_once(self):
        self.assertEqual(sorted(c["chapter"] for c in self.book.calls("relate")), [1, 2, 3, 4, 5])


class RewordedSummaryTest(unittest.TestCase):
    def test_rewording_an_entry_summary_does_not_reask_relate(self):
        book = MiniBuild(relate_script())
        try:
            book.build()
            relate, asked = book.json("relate.json"), len(book.calls("relate"))
            path = book.workdir / "state" / "0001.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            sabine = next(e for e in state["extraction"]["entities"] if e["name"] == "Sabine Oake")
            sabine["summary"] = "Head of the Lamplighters' Guild, who would not reopen the wreck inquiry."
            path.write_text(json.dumps(state), encoding="utf-8")
            rebuilt = book.build()
            self.assertIn("relate", ran(rebuilt.stdout))
            self.assertEqual(len(book.calls("relate")), asked)
            self.assertEqual(book.json("relate.json"), relate)
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()


class _Registry:
    timelines = {"main": {}}

    def __init__(self, names):
        self.names = set(names)

    def resolve(self, name):
        return name if name in self.names else None


class PresentEndTest(unittest.TestCase):
    TEXT = "I sat with her mother until dawn, and told her everything. Wren Hollis wept at the window."

    def check(self, present):
        from annalist.names import name_pattern
        from annalist.relate import check_relation
        req = {"kb": _Registry({"Ada Quill", "Wren Hollis", "Mara Hollis"}), "text": self.TEXT, "known": set(), "present": present,
               "patterns": {n: name_pattern([n]) for n in ("Ada Quill", "Wren Hollis", "Mara Hollis")}}
        raw = {"source": "Mara Hollis", "target": "Wren Hollis", "type": "mother of", "quote": "I sat with her mother until dawn, and told her everything."}
        return check_relation(req, raw, 3, 120)

    def test_an_end_the_chapter_shows_only_as_her_mother_counts_when_the_read_found_it_present(self):
        row, reason = self.check({"Mara Hollis", "Wren Hollis"})
        self.assertIsNotNone(row, reason)

    def test_an_end_neither_named_nor_present_is_still_rejected(self):
        row, reason = self.check({"Wren Hollis"})
        self.assertIsNone(row)
