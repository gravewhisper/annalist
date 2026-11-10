import copy
import unittest

from annalist.scorecard import Wiki
from tests.test_build import MiniBuild, build_script

REVEAL_QUOTE = "My name was Livia Hale. Tomas was my father."


def script_without_the_read_merge(reveal):
    script = build_script()
    extract = next(r for r in script["replies"] if r.get("purpose") == "extract" and r.get("chapter") == 4)
    extract["reply"] = copy.deepcopy(extract["reply"])
    livia = next(e for e in extract["reply"]["entities"] if e["name"] == "Livia Hale")
    livia["aliases"] = [{"name": "Wren", "unique": True}]
    script["replies"][:0] = [
        {"purpose": "resolve", "contains": "Name: Sister Wren", "reply": {"same": True, "canonical_name": "Livia Hale",
                                                                          "reason": "Chapter 4 says Wren is Livia."}},
        {"purpose": "reveal", "contains": "ENTRY A", "reply": reveal}]
    return script


STITCHED = ("They buried Tomas Hale in the Guild plot behind the harbour chapel on a grey, windless morning. "
            "My name was Livia Hale. Tomas was my father.")


class RevealedMergeTest(unittest.TestCase):
    def build(self, reveal, revised=None):
        script = script_without_the_read_merge(reveal)
        if revised is not None:
            script["replies"].insert(0, {"purpose": "reveal", "contains": "was rejected", "reply": revised})
        book = MiniBuild(script)
        self.addCleanup(book.close)
        book.build()
        pair = next(d for d in book.json("merges.json")["pairs"] if {d["a"], d["b"]} == {"Livia Hale", "Sister Wren"})
        return pair, book.json("site/data/wiki.json")

    def test_a_merge_resolve_accepts_is_linked_from_the_chapter_whose_quote_shows_the_identity(self):
        pair, data = self.build({"chapter": 4, "quote": REVEAL_QUOTE})
        self.assertEqual(pair["revealed"], {"chapter": 4, "quote": REVEAL_QUOTE, "basis": "quote"})
        wiki = Wiki(data)
        livia = next(e for e in data["entities"] if e["name"] == "Livia Hale")["id"]
        wren = next(e for e in data["entities"] if e["name"] == "Sister Wren")
        self.assertEqual(wren["merged"], {"into": livia, "chapter": 4})
        self.assertFalse([text for _, text in wiki.page(livia, 3) if "Wren" in text])
        self.assertIn("Sister Wren is the abbey's archivist", " ".join(text for _, text in wiki.page(livia, 4)))

    def test_an_unverified_merge_of_overlapping_names_is_linked_only_from_the_chapter_that_gave_the_overlapping_name(self):
        pair, data = self.build({"chapter": None, "quote": ""})
        self.assertEqual(pair["revealed"], {"chapter": 4, "quote": "", "basis": "variant"})
        livia = next(e for e in data["entities"] if e["name"] == "Livia Hale")["id"]
        self.assertEqual(next(e for e in data["entities"] if e["name"] == "Sister Wren")["merged"], {"into": livia, "chapter": 4})

    def test_a_reveal_quote_stitched_from_separate_sentences_is_asked_again(self):
        pair, data = self.build({"chapter": 4, "quote": STITCHED}, revised={"chapter": 4, "quote": REVEAL_QUOTE})
        self.assertEqual(pair["revealed"], {"chapter": 4, "quote": REVEAL_QUOTE, "basis": "quote"})

    def test_a_reveal_quote_that_never_matches_falls_back_without_stopping_the_build(self):
        pair, data = self.build({"chapter": 4, "quote": STITCHED}, revised={"chapter": 4, "quote": STITCHED})
        self.assertEqual(pair["revealed"], {"chapter": 4, "quote": "", "basis": "variant"})


if __name__ == "__main__":
    unittest.main()


def script_with_cross_type_names():
    script = build_script()
    replies = {(r.get("purpose"), r.get("chapter")): r for r in script["replies"]}
    for n in (1, 3, 4):
        replies[("extract", n)]["reply"] = copy.deepcopy(replies[("extract", n)]["reply"])
    replies[("extract", 1)]["reply"]["entities"].append({"name": "T. H.", "type": "concept", "aliases": [],
                                                          "summary": "Initials inked inside the Salt Ledger's cover."})
    next(e for e in replies[("extract", 3)]["reply"]["entities"] if e["name"] == "Sister Wren")["type"] = "concept"
    next(e for e in replies[("extract", 4)]["reply"]["entities"] if e["name"] == "Livia Hale")["aliases"] = [
        {"name": "Sister Wren", "unique": True}]
    script["replies"][:0] = [
        {"purpose": "resolve", "contains": "Name: T. H.", "reply": {"same": True, "canonical_name": "Tomas Hale", "reason": "His initials."}},
        {"purpose": "resolve", "contains": "Name: Sister Wren", "reply": {"same": True, "canonical_name": "Livia Hale", "reason": "Same woman."}},
        {"purpose": "reveal", "contains": "ENTRY A", "reply": {"chapter": 4, "quote": REVEAL_QUOTE}}]
    return script


class CrossTypeMergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(script_with_cross_type_names())
        cls.book.build()
        cls.pairs = {frozenset((d["a"], d["b"])): d for d in cls.book.json("merges.json")["pairs"]}
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_an_entry_whose_name_another_entry_carries_as_an_alias_is_merged_from_the_reveal(self):
        pair = self.pairs[frozenset(("Livia Hale", "Sister Wren"))]
        self.assertIn("alias-is-other-entry: 'Sister Wren'", pair["rules"])
        self.assertEqual(pair["revealed"]["chapter"], 4)
        livia = next(e for e in self.wiki["entities"] if e["name"] == "Livia Hale")["id"]
        self.assertEqual(next(e for e in self.wiki["entities"] if e["name"] == "Sister Wren")["merged"], {"into": livia, "chapter": 4})

    def test_initials_never_shown_next_to_the_name_are_compared_but_kept_apart(self):
        pair = self.pairs[frozenset(("T. H.", "Tomas Hale"))]
        self.assertIn("initials: 'T. H.'", pair["rules"])
        self.assertEqual(pair["revealed"]["basis"], "unverified")
        self.assertNotIn("merged", next(e for e in self.wiki["entities"] if e["name"] == "T. H."))
