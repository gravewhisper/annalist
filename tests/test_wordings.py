import re
import unittest

from tests.test_build import MiniBuild, build_script, read_jsonl
from tests.test_pipeline import expected, support_reply

ARREST = ("Captain Fenn arrested Sabine Oake for the wreck of the Gannet and the deaths of twenty-two people, "
          "and Bram Ostrow for the death of Tomas Hale.")
HALL = "They found Sabine Oake in the Guild hall, at the long table, with Bram Ostrow standing at her shoulder."

RELATE_CH5 = {"relations": [
    {"source": "Captain Fenn", "type": "charged", "detail": "with the wreck of the Gannet", "target": "Sabine Oake",
     "quote": ARREST, "asserted_by": "narrator", "status": "stated"},
    {"source": "Sabine Oake", "type": "Member of", "target": "Lamplighters’ Guild", "quote": HALL,
     "asserted_by": "narrator", "status": "stated"},
    {"source": "Bram Ostrow", "type": "attends", "detail": "his place is there", "target": "Lamplighters’ Guild", "quote": HALL,
     "asserted_by": "narrator", "status": "stated"},
]}

TOOK = "took from ines varro on the orders of sabine oake"
ONCE_KEPT = "father once kept"
HID = "hid the salt ledger from"
LEGACY_CH4 = [
    {"source": "Bram Ostrow", "target": "lamp room key", "type": TOOK, "quotes": ["Give me the key, Ines."],
     "asserted_by": "narrator", "status": "stated"},
    {"source": "Livia Hale", "target": "harbour lamp", "type": ONCE_KEPT, "quotes": ["Give me the key, Ines."],
     "asserted_by": "narrator", "status": "stated"},
    {"source": "Sabine Oake", "target": "Bram Ostrow", "type": HID, "quotes": ["Give me the key, Ines."],
     "asserted_by": "narrator", "status": "stated"},
]
SPLITS = {"wordings": [{"wording": TOOK, "type": "took", "detail": "from ines varro on the orders of sabine oake"},
                       {"wording": ONCE_KEPT, "type": "", "detail": ""}]}


def wordings_script():
    script = build_script()
    record = expected(4)
    extraction = {**record["extraction"], "relations": record["extraction"]["relations"] + LEGACY_CH4}
    chapter4 = {"extract": extraction, "support": support_reply(extraction, 4)}
    for reply in script["replies"]:
        if reply.get("chapter") == 4 and reply["purpose"] in chapter4:
            reply["reply"] = chapter4[reply["purpose"]]
    script["replies"].insert(0, {"purpose": "relate", "contains": "CHAPTER 5: The Salt Ledger", "reply": RELATE_CH5})
    script["replies"].insert(0, {"purpose": "wordings", "contains": TOOK, "reply": SPLITS})
    return script


def infobox(book, page):
    text = (book.workdir / "wiki" / "character" / f"{page}.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| \*\*(.+?)\*\* \| (.+?) \|$", text, re.M))
    return {k: re.sub(r"\[ch (\d+)\]\([^)]*\)", r"ch \1", v) for k, v in rows.items()}


class WordingsMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(wordings_script())
        cls.book.build()
        cls.rows = read_jsonl(cls.book.workdir / "relations.jsonl")
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.names = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def shown(self, source, target):
        return [r for r in self.wiki["relations"] if (self.names[r["source"]], self.names[r["target"]]) == (source, target)]

    def page(self, slug):
        return (self.book.workdir / "wiki" / "character" / f"{slug}.md").read_text(encoding="utf-8")

    def test_a_filled_in_relation_keeps_its_casing_and_its_detail_reads_after_the_target(self):
        self.assertIn(("charged", "with the wreck of the Gannet"),
                      {(r["type"], r["detail"]) for r in self.rows if (r["source"], r["target"]) == ("Captain Fenn", "Sabine Oake")})
        self.assertIn(("charged", "with the wreck of the Gannet"), {(r["type"], r.get("detail")) for r in self.shown("Captain Fenn", "Sabine Oake")})
        self.assertIn(("Member of", ""), {(r["type"], r["detail"]) for r in self.rows if (r["source"], r["target"]) == ("Sabine Oake", "Lamplighters’ Guild")})
        self.assertRegex(self.page("captain-fenn"), r"\*charged\* \[Sabine Oake\]\([^)]*\) with the wreck of the Gannet \(")

    def test_a_read_detail_that_cannot_follow_the_target_reaches_neither_the_page_nor_the_site(self):
        self.assertIn(("attends", ""), {(r["type"], r["detail"]) for r in self.rows if r["source"] == "Bram Ostrow"})
        self.assertNotIn("detail", next(r for r in self.shown("Bram Ostrow", "Lamplighters’ Guild") if r["type"] == "attends"))
        self.assertNotIn("his place is there", self.page("bram-ostrow"))

    def test_a_relation_without_detail_exports_none(self):
        self.assertTrue(all(r.get("detail") for r in self.wiki["relations"] if "detail" in r))
        self.assertNotIn("detail", next(r for r in self.shown("Sabine Oake", "Lamplighters’ Guild") if r["type"] == "Member of"))

    def test_a_legacy_wording_is_split_into_predicate_and_detail_with_the_names_cased_as_the_book_does(self):
        want = ("took", "from Ines Varro on the orders of Sabine Oake")
        self.assertIn(want, {(r["type"], r["detail"]) for r in self.rows if (r["source"], r["target"]) == ("Bram Ostrow", "lamp room key")})
        self.assertIn(want, {(r["type"], r.get("detail")) for r in self.shown("Bram Ostrow", "lamp room key")})
        self.assertNotIn(TOOK, {r["type"].lower() for r in self.rows})

    def test_a_name_of_common_words_the_book_never_writes_in_lowercase_is_cased_in_a_wording_the_reading_left_whole(self):
        self.assertIn("hid the Salt Ledger from", {r["type"] for r in self.rows if (r["source"], r["target"]) == ("Sabine Oake", "Bram Ostrow")})

    def test_a_legacy_wording_that_cannot_be_said_of_its_source_is_dropped(self):
        self.assertEqual([r for r in self.rows if (r["source"], r["target"], r["chapter"]) == ("Livia Hale", "harbour lamp", 4)], [])

    def test_rerunning_the_wordings_stage_reads_nothing_new(self):
        asked = len(self.book.calls("wordings"))
        self.assertGreater(asked, 0)
        self.book.run_annalist("wordings", str(self.book.workdir))
        self.assertEqual(len(self.book.calls("wordings")), asked)

    def test_a_capitalised_member_of_is_still_an_affiliation(self):
        self.assertEqual(infobox(self.book, "sabine-oake")["Affiliation"], "Lamplighters’ Guild (ch 5)")


if __name__ == "__main__":
    unittest.main()
