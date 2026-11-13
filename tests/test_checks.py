import json
import tempfile
import unittest
from pathlib import Path

from annalist.checks import site_checks


def page(id, name, type="character", first=1, aliases=(), **extra):
    return {"id": id, "name": name, "type": type, "first": first, "aliases": [{"name": n, "chapter": c} for n, c in aliases], **extra}


class SiteChecksTest(unittest.TestCase):
    def checks(self, entities, facts=(), review=None):
        with tempfile.TemporaryDirectory() as tmp:
            if review is not None:
                Path(tmp, "review.json").write_text(json.dumps({"checks": review}), encoding="utf-8")
            return site_checks(Path(tmp), entities, list(facts))

    def test_a_name_two_character_pages_claim_flags_the_smaller_page_from_the_chapter_it_took_the_name(self):
        ada = page("a", "Ada Marsh", aliases=[("The Lantern", 3)])
        tor = page("t", "Tor Vell", first=5, aliases=[("The Lantern", 9)])
        facts = [{"entity": "a"}] * 4 + [{"entity": "t"}]
        found = self.checks([ada, tor], facts)
        self.assertEqual([(c["kind"], c["entity"], c["chapter"]) for c in found], [("shared_name", "t", 9)])
        self.assertEqual(found[0]["reason"], "shares \u201cThe Lantern\u201d with the page \u201cAda Marsh\u201d")

    def test_places_sharing_a_name_and_a_page_merged_into_its_namesake_are_not_flagged(self):
        found = self.checks([page("a", "Ada Marsh", aliases=[("Harbour", 2)]), page("h", "Harbour", type="place"),
                             page("old", "Old Ada", aliases=[("Ada Marsh", 1)], merged={"into": "a", "chapter": 4})])
        self.assertEqual(found, [])

    def test_two_pages_later_merged_into_a_third_are_flagged_for_the_chapters_they_stand_apart(self):
        merged = {"into": "z", "chapter": 50}
        found = self.checks([page("k", "Kai Roan", aliases=[("The Gull", 3)], merged=merged),
                             page("j", "Jarl Venn", first=20, aliases=[("The Gull", 30)], merged=merged), page("z", "Zed")],
                            [{"entity": "k"}] * 3 + [{"entity": "j"}])
        self.assertEqual([(c["kind"], c["entity"], c["chapter"]) for c in found], [("shared_name", "j", 30)])

    def test_many_names_and_a_described_page_with_many_facts_are_flagged(self):
        many = page("m", "Wren", aliases=[(f"Name {k}", k) for k in range(1, 7)])
        clerk = page("c", "Gray-coated clerk", nameless=True)
        found = self.checks([many, clerk], [{"entity": "c"}] * 5)
        self.assertEqual(sorted((c["kind"], c["chapter"]) for c in found), [("description_title", 1), ("many_names", 6)])

    def test_hedged_merges_and_unexplained_returns_come_from_the_review(self):
        review = [{"key": "merges", "findings": [{"a": "Gull", "b": "Wren", "canonical": "Wren", "reasons": ['hedged reason ("likely")']}]},
                  {"key": "dead_then_alive", "findings": [
                      {"character": "Wren", "died": 4, "later": "speaks", "later_chapter": 6, "explained_by": ""},
                      {"character": "Wren", "died": 2, "later": "revived", "later_chapter": 3, "explained_by": "a revival is recorded in ch 3"}]}]
        found = self.checks([page("w", "Wren", first=2)], review=review)
        self.assertEqual([(c["kind"], c["chapter"]) for c in found], [("merge", 2), ("dead_alive", 6)])
        self.assertEqual(len({c["id"] for c in found}), 2)


class PlainReasonTest(unittest.TestCase):
    def test_review_reasons_read_as_plain_words(self):
        from annalist.checks import plain_reason
        self.assertEqual(plain_reason('hedged reason ("likely")'), "the judge only said \u201clikely\u201d")
        self.assertEqual(plain_reason("cross-type (church / place)"), "one was filed as church, the other as place")


class CheckScopeTest(unittest.TestCase):
    def checks(self, entities, facts=(), review=None, last=None):
        with tempfile.TemporaryDirectory() as tmp:
            if review is not None:
                Path(tmp, "review.json").write_text(json.dumps({"checks": review}), encoding="utf-8")
            return site_checks(Path(tmp), entities, list(facts), last)

    def test_a_described_page_whose_name_the_book_reveals_is_not_flagged(self):
        named = page("n", "Ada Marsh", nameless=True, named_from=4)
        self.assertEqual(self.checks([named], [{"entity": "n"}] * 6), [])

    def test_nothing_past_the_wikis_last_chapter_is_listed(self):
        review = [{"key": "dead_then_alive", "findings": [
            {"character": "Wren", "died": 4, "later": "speaks", "later_chapter": 30, "explained_by": ""}]}]
        self.assertEqual(self.checks([page("w", "Wren")], review=review, last=20), [])
        self.assertEqual(len(self.checks([page("w", "Wren")], review=review, last=40)), 1)
