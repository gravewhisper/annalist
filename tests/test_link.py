import unittest

from annalist.families import relation_family
from annalist.link import POSSESSION, VOCABULARY
from annalist.state import load_states
from tests.test_build import MiniBuild, build_script
from tests.test_pipeline import support_reply

QUAY_QUOTE = "She put the key on its ring around her neck, under her shirt."
ABBEY_QUOTE = "At half past four Ines lit the harbour lamp and wrote the hour in the Salt Ledger"
SHIRT_SENTENCE = "Then he reached into the neck of Ines’s shirt, closed his fist round the iron ring, and pulled until the cord broke."

LIVES_QUAY = {"entity": "Ines Varro", "claim": "Ines Varro lives at Corvel Quay.", "quotes": [QUAY_QUOTE],
              "asserted_by": "narrator", "status": "stated"}
WREN_ABBEY = {"entity": "Sister Wren", "claim": "Sister Wren lives at Brannoc Abbey.", "quotes": ["The sisters called her Sister Wren."],
              "asserted_by": "narrator", "status": "stated"}
LIVES_ABBEY = {"entity": "Ines Varro", "claim": "Ines Varro lives at Brannoc Abbey.", "quotes": [ABBEY_QUOTE],
               "asserted_by": "narrator", "status": "stated"}

LABELS = {"labels": [
    {"fact": "F0001-003", "target": "Lamplighters’ Guild", "type": "member of"},
    {"fact": "F0001-010", "target": "Kestrel", "type": "none"},
    {"fact": "F0003-001", "target": "Corvel Quay", "type": "lives at"},
    {"fact": "F0003-002", "target": "Brannoc Abbey", "type": "lives at"},
    {"fact": "F0005-001", "target": "Brannoc Abbey", "type": "lives at"},
]}


def link_script():
    script = build_script()

    def reply(purpose, n):
        return next(r for r in script["replies"] if r["purpose"] == purpose and r.get("chapter") == n)

    for n, facts in ((3, [LIVES_QUAY, WREN_ABBEY]), (5, [LIVES_ABBEY])):
        extraction = reply("extract", n)["reply"]
        extraction["facts"][:0] = facts
        reply("support", n)["reply"] = support_reply(extraction, n)
    reply("extract", 5)["reply"]["entities"] += [
        {"name": "Ines's shirt", "type": "artifact", "aliases": [], "summary": "The shirt Ines wore the night Bram took the key."},
        {"name": "Abbess's seal", "type": "artifact", "aliases": [], "summary": "The seal on the abbey's ledgers."}]
    reply("extract", 4)["reply"]["entities"].append(
        {"name": "Ines's iron ring", "type": "artifact", "aliases": [], "summary": "The ring Ines wore the lamp room key on."})
    script["replies"].insert(0, {"purpose": "link", "contains": LIVES_QUAY["claim"], "reply": LABELS})
    return script


class LinkMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(link_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def shown(self, source, target):
        names = {e["id"]: e["name"] for e in self.wiki["entities"]}
        return [r for r in self.wiki["relations"] if (names[r["source"]], names[r["target"]]) == (source, target)]

    def known_at(self, until, source, rtype, target):
        kb = load_states(self.book.workdir, until=until)
        return [r for r in kb.relations if (r["source"], r["type"], r["target"]) == (source, rtype, target)]

    def test_a_possessive_name_links_the_entry_to_its_owner_from_the_first_chapter_naming_it(self):
        rows = self.shown("Ines's shirt", "Ines Varro")
        self.assertEqual([(r["type"], r["chapter"], r["quotes"]) for r in rows], [("owned by", 4, [SHIRT_SENTENCE])])
        self.assertEqual(rows[0]["family"], "ownership")
        self.assertNotIn("unverified", rows[0])

    def test_a_possessive_name_the_text_never_spells_out_is_dated_by_the_entrys_chapter_sentence_naming_owner_and_thing(self):
        rows = self.shown("Ines's iron ring", "Ines Varro")
        self.assertEqual([(r["type"], r["chapter"], r["quotes"]) for r in rows], [("owned by", 4, [SHIRT_SENTENCE])])

    def test_a_possessive_name_whose_owner_is_no_entry_adds_nothing(self):
        ids = {e["name"]: e["id"] for e in self.wiki["entities"]}
        self.assertEqual([r for r in self.wiki["relations"] if ids["Abbess's seal"] in (r["source"], r["target"])], [])

    def test_a_fact_that_a_character_lives_at_a_place_becomes_a_relation_from_its_chapter(self):
        rows = self.shown("Ines Varro", "Corvel Quay")
        self.assertEqual([(r["type"], r["chapter"], r["quotes"], r["status"]) for r in rows],
                         [("lives at", 3, [QUAY_QUOTE], "stated")])
        self.assertEqual(rows[0]["family"], "place")
        self.assertEqual(self.known_at(2, "Ines Varro", "lives at", "Corvel Quay"), [])
        self.assertEqual(len(self.known_at(3, "Ines Varro", "lives at", "Corvel Quay")), 1)

    def test_a_later_move_adds_a_second_home_and_keeps_the_first(self):
        self.assertEqual([(r["type"], r["chapter"]) for r in self.shown("Ines Varro", "Brannoc Abbey")], [("lives at", 5)])
        self.assertEqual([(r["type"], r["chapter"]) for r in self.shown("Ines Varro", "Corvel Quay")], [("lives at", 3)])
        self.assertEqual(self.known_at(4, "Ines Varro", "lives at", "Brannoc Abbey"), [])
        self.assertEqual(len(self.known_at(5, "Ines Varro", "lives at", "Corvel Quay")), 1)

    def test_a_fact_filed_under_a_name_later_revealed_as_another_character_stays_on_that_name_until_the_reveal(self):
        self.assertEqual([r["chapter"] for r in self.shown("Sister Wren", "Brannoc Abbey") if r["type"] == "lives at"], [3])
        self.assertEqual([r for r in self.shown("Livia Hale", "Brannoc Abbey") if r["type"] == "lives at"], [])
        self.assertEqual(len(self.known_at(3, "Sister Wren", "lives at", "Brannoc Abbey")), 1)
        self.assertEqual(self.known_at(3, "Livia Hale", "lives at", "Brannoc Abbey"), [])
        later = self.known_at(5, "Livia Hale", "lives at", "Brannoc Abbey")
        self.assertEqual([r["filed"] for r in later], [{"source": "Sister Wren"}])

    def test_a_fact_labelled_none_adds_nothing(self):
        self.assertEqual([r["type"] for r in self.shown("Odile Marr", "Kestrel")], ["master of"])

    def test_a_label_matching_a_relation_already_known_in_that_chapter_is_not_added_twice(self):
        rows = self.shown("Tomas Hale", "Lamplighters’ Guild")
        self.assertEqual([(r["type"], r["chapter"]) for r in rows], [("member of", 1)])

    def test_the_mini_books_candidates_go_to_the_classifier_in_one_call(self):
        self.assertEqual(len(self.book.calls("link")), 1)


class LinkFamilyTest(unittest.TestCase):
    def test_every_type_the_link_stage_writes_has_a_family(self):
        types = {POSSESSION} | {t for labels in VOCABULARY.values() for t in labels}
        self.assertEqual({t: relation_family(t) for t in types if relation_family(t) == "other"}, {})


if __name__ == "__main__":
    unittest.main()
