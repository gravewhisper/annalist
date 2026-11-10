import unittest

from annalist.names import written_summary
from annalist.state import Knowledge


class PlaceholderSummaryTest(unittest.TestCase):
    def test_a_placeholder_is_not_a_summary(self):
        self.assertEqual(written_summary({"summary": " Placeholder "}), "")
        self.assertEqual(written_summary({"summary": "A pirate."}), "A pirate.")
        self.assertEqual(written_summary({}), "")

    def test_a_placeholder_keeps_the_last_real_summary(self):
        kb = Knowledge()
        kb.upsert_entity({"name": "Mira", "type": "character", "aliases": [], "summary": "A pirate."}, 1)
        kb.upsert_entity({"name": "Mira", "type": "character", "aliases": [], "summary": "placeholder"}, 2)
        self.assertEqual(kb.entities["Mira"]["summary"], "A pirate.")


if __name__ == "__main__":
    unittest.main()
