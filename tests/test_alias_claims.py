import unittest

from annalist.resolve import claimed_pairs, CLAIMED, RESOLVE_PROMPT
from annalist.state import Knowledge


def person(name, *aliases, summary=""):
    return {"name": name, "type": "character", "aliases": [{"name": a, "unique": True} for a in aliases], "summary": summary}


def fact(entity, claim):
    return {"entity": entity, "claim": claim, "quotes": [claim], "asserted_by": "narrator", "status": "stated"}


def chapter(n, entities, facts=()):
    return {"chapter": n, "title": f"Chapter {n}", "extraction": {"entities": entities, "facts": list(facts)}}


class AliasClaimTest(unittest.TestCase):
    def read(self, *chapters):
        kb = Knowledge()
        for c in chapters:
            kb.apply(c)
        return kb

    def opening(self):
        return [chapter(1, [person("Serrin Vale")], [fact("Serrin Vale", f"Serrin Vale did thing {i}.") for i in range(6)]),
                chapter(2, [person("Serrin Vale", "Grey Lantern", summary="Serrin's masked persona.")],
                        [fact("Serrin Vale", "Serrin Vale wore the mask.")]),
                chapter(3, [person("Count Orvell")], [fact("Count Orvell", "Count Orvell rules the harbour.")])]

    def test_another_characters_persona_does_not_pull_them_into_a_page(self):
        kb = self.read(*self.opening(), chapter(4, [person("Count Orvell", "Grey Lantern", summary="Harbour lord.")],
                                                [fact("Count Orvell", "Count Orvell recognized him.")]))
        self.assertIn("Serrin Vale", kb.entities)
        self.assertEqual(kb.resolve("Grey Lantern"), "Serrin Vale")
        self.assertEqual(kb.entities["Count Orvell"]["aliases"], [])
        self.assertEqual(kb.entities["Count Orvell"]["claims"], [{"name": "Grey Lantern", "chapter": 4}])
        view = kb.compact_view("Count Orvell met Serrin Vale.", {"recent_entities": 5, "recent_questions": 0, "matched_questions": 0})
        line = next(x for x in view.splitlines() if x.startswith("- Count Orvell"))
        self.assertNotIn("Serrin", line)
        self.assertNotIn("Lantern", line)

    def test_a_smaller_page_does_not_absorb_a_bigger_one_by_its_name(self):
        kb = self.read(*self.opening(), chapter(4, [person("Count Orvell", "Serrin Vale")]))
        self.assertEqual(kb.resolve("Serrin Vale"), "Serrin Vale")
        self.assertEqual(sum(f["entity"] == "Serrin Vale" for f in kb.facts), 7)

    def test_a_page_named_by_its_alias_does_not_absorb_another_page(self):
        kb = self.read(*self.opening(), chapter(4, [person("Grey Lantern", "Count Orvell")]))
        self.assertIn("Count Orvell", kb.entities)
        self.assertEqual(kb.resolve("Count Orvell"), "Count Orvell")
        self.assertEqual(kb.entities["Serrin Vale"]["claims"], [{"name": "Count Orvell", "chapter": 4}])

    def test_a_persona_page_still_joins_its_bigger_owner(self):
        kb = self.read(chapter(1, [person("Serrin Vale")], [fact("Serrin Vale", f"Serrin Vale did thing {i}.") for i in range(6)]),
                       chapter(2, [person("Grey Lantern")], [fact("Grey Lantern", "Grey Lantern robbed a coach.")]),
                       chapter(3, [person("Serrin Vale", "Grey Lantern")]))
        self.assertEqual(kb.resolve("Grey Lantern"), "Serrin Vale")
        self.assertNotIn("Grey Lantern", kb.entities)

    def test_resolve_judges_a_claim_with_the_possession_rule(self):
        kb = self.read(*self.opening(), chapter(4, [person("Count Orvell", "Grey Lantern")]))
        self.assertEqual(list(claimed_pairs(kb)), [("Count Orvell", "Serrin Vale", "alias-claimed: 'Grey Lantern' in ch4")])
        self.assertIn("{listing}", RESOLVE_PROMPT)
        self.assertIn("marionette", CLAIMED)

    def test_a_name_listed_as_its_own_entity_does_not_join_another_entry_by_alias(self):
        father = person("Aubric", summary="Calls himself Aubric.")
        for before in ([chapter(1, [person("Halvane")], [fact("Halvane", "Halvane is a magistrate.")])], []):
            for entities in ([person("Halvane", "Aubric"), father], [father, person("Halvane", "Aubric")]):
                kb = self.read(*before, chapter(2, entities, [fact("Aubric", "Aubric is a conspirator."),
                                                               fact("Halvane", "Halvane is a royalist.")]))
                self.assertEqual(kb.resolve("Halvane"), "Halvane")
                self.assertEqual(kb.resolve("Aubric"), "Aubric")
                self.assertEqual(kb.entities["Halvane"]["aliases"], [])
                self.assertEqual({f["claim"]: f["entity"] for f in kb.facts}["Aubric is a conspirator."], "Aubric")

    def test_an_alias_no_entity_of_the_chapter_bears_still_joins(self):
        kb = self.read(chapter(1, [person("Halvane")]),
                       chapter(2, [person("Halvane", "the Magistrate"), person("Aubric")], [fact("the Magistrate", "The Magistrate frowned.")]))
        self.assertEqual(kb.resolve("the Magistrate"), "Halvane")
        self.assertEqual(kb.facts[0]["entity"], "Halvane")
        self.assertEqual(kb.resolve("Aubric"), "Aubric")


if __name__ == "__main__":
    unittest.main()
