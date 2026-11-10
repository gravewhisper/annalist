import unittest

from annalist.state import Knowledge


def person(name, aliases=()):
    return {"name": name, "type": "character", "aliases": [{"name": a, "unique": True} for a in aliases], "summary": ""}


class NameVariantMergeTest(unittest.TestCase):
    def test_a_name_that_is_part_of_the_other_is_no_reveal(self):
        kb = Knowledge()
        kb.upsert_entity(person("Admiral Mira Vale", ["Captain Mira Vale"]), 2)
        kb.upsert_entity(person("Mira Vale"), 5)
        kb.upsert_entity(person("Mira Vale", ["Captain Mira Vale"]), 9)
        self.assertEqual(len(kb.entities), 1)
        self.assertEqual(next(iter(kb.entities.values())).get("absorbed", []), [])

    def test_a_different_name_stays_apart_until_the_chapter_that_links_it(self):
        kb = Knowledge()
        kb.upsert_entity(person("Sister Wren"), 2)
        kb.upsert_entity(person("Livia Hale"), 3)
        kb.upsert_entity(person("Livia Hale", ["Sister Wren"]), 9)
        self.assertEqual([(a["name"], a["chapter"]) for a in kb.entities["Livia Hale"]["absorbed"]], [("Sister Wren", 9)])

    def test_shared_letters_are_not_a_shared_name(self):
        kb = Knowledge()
        kb.upsert_entity(person("Ann"), 2)
        kb.upsert_entity(person("Joanna Reed"), 3)
        kb.upsert_entity(person("Joanna Reed", ["Ann"]), 9)
        self.assertEqual([a["chapter"] for a in kb.entities["Joanna Reed"]["absorbed"]], [9])


if __name__ == "__main__":
    unittest.main()
