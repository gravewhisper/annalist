import unittest

from annalist.wordings import casing, worded

DROPPED = [
    ("resident of", "Brindle", "she came to Brindle with her husband long ago"),
    ("resident of", "Brindle", "his cottage is there"),
    ("resident of", "Brindle", "her cottage is located there"),
    ("son of", "Tide Guild", "his father was a clerk in it"),
    ("works at", "Quay Gate", "stays on duty there"),
    ("colleague of", "Oskar", "greeted him at the market"),
    ("colleague of", "Oskar", "calls him Captain"),
    ("teacher of", "Oskar", "taught him the knots"),
    ("client of", "Oskar", "plans to hire him again"),
    ("works at", "Quay Gate", "Ledger Office is his address"),
    ("acquaintance of", "Oskar", "Mara believes he lied"),
    ("colleague of", "Oskar", "teammate; he helped her once"),
    ("employee of", "Oskar", "Mara's wife found him there"),
    ("employee of", "Brindle Bank", "as senior employee of Brindle Bank's north branch"),
    ("member of", "Tide Guild", "as one of the Tide Guild"),
    ("located on", "Quay Street", "at 18 Quay Street"),
    ("creator of", "Tide Guild", "the modern Tide Guild"),
    ("owner of", "Brass Lantern", "her brass lantern, which she trims nightly"),
]

KEPT = [
    ("resident of", "Brindle", "with his brother and sister"),
    ("formerly resided on", "Quay Street", "in the Lower Ward"),
    ("resident of", "Brindle", "living at No. 12, first floor"),
    ("works in", "Brindle", "as a clerk"),
    ("suspects", "Oskar", "of impersonating the baron"),
    ("gave", "Oskar", "a silver ring to the innkeeper"),
    ("promised", "Oskar", "the third share of the salvage"),
    ("gave", "Oskar", "his coat"),
    ("owns", "Brass Lantern", "kept under his pillow"),
    ("member of", "Tide Guild", "recruited by Mara"),
    ("rank of path", "Salt path", "as Rank 4"),
    ("examined", "Oskar", "and concluded he lied"),
    ("suspects", "Black Mirror", "was used in a forbidden rite"),
    ("practices", "Dowsing", "using a moonstone on a chain"),
    ("warned", "Oskar", "that the tide would turn"),
    ("hunts", "Oskar", "who fled the harbour"),
    ("fears", "Oskar", "because of the debt"),
    ("suspects", "Black Mirror", "was used in a forbidden rite with a black mirror"),
    ("trade partner of", "Oskar", "Mara's notes in exchange for the map"),
    ("cooperated with", "Oskar", "numerous times"),
]


class DetailReadsAfterTargetTest(unittest.TestCase):
    def read(self, rtype, target, detail):
        return worded({"type": rtype, "target": target, "detail": detail}, {})

    def test_a_detail_that_cannot_follow_the_target_is_not_kept(self):
        for rtype, target, detail in DROPPED:
            with self.subTest(detail=detail):
                self.assertEqual(self.read(rtype, target, detail), {"type": rtype, "detail": ""})

    def test_a_detail_that_reads_after_the_target_is_kept_word_for_word(self):
        for rtype, target, detail in KEPT:
            with self.subTest(detail=detail):
                self.assertEqual(self.read(rtype, target, detail), {"type": rtype, "detail": detail})

    def test_an_older_wording_split_earlier_is_held_to_the_same_rule(self):
        wordings = {"resident of brindle": {"type": "resident of", "detail": "his cottage is there"},
                    "works in as a clerk": {"type": "works in", "detail": "as a clerk"}}
        self.assertEqual(worded({"type": "resident of brindle", "target": "Brindle"}, wordings), {"type": "resident of", "detail": ""})
        self.assertEqual(worded({"type": "works in as a clerk", "target": "Brindle"}, wordings), {"type": "works in", "detail": "as a clerk"})


class FirstNameCasingTest(unittest.TestCase):
    ENTITIES = [{"name": "Ines Varro", "aliases": []}, {"name": "Old Harl", "aliases": []}]
    BOOK = "Ines Varro met Old Harl, an old friend, at the quay."

    def test_a_single_word_of_a_name_the_book_never_writes_in_lowercase_is_cased(self):
        self.assertEqual(casing(self.ENTITIES, self.BOOK)("recommended ines to"), "recommended Ines to")

    def test_a_word_of_a_name_the_book_also_uses_as_a_common_word_stays_lowercase(self):
        self.assertEqual(casing(self.ENTITIES, self.BOOK)("trusts an old friend of"), "trusts an old friend of")


if __name__ == "__main__":
    unittest.main()
