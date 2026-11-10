import unittest

from annalist.state import Knowledge

LADDER = {"group_type": "school", "step_type": "rank", "rank": "number"}


def knowledge():
    kb = Knowledge(LADDER, power_types={"school", "rank", "draught"})
    kb.upsert_entity({"name": "Ashwright", "type": "rank", "aliases": []}, 1)
    kb.upsert_entity({"name": "Stout man at the fair", "type": "character", "aliases": []}, 2)
    kb.upsert_entity({"name": "Sparkwater", "type": "draught", "aliases": []}, 1)
    return kb


class RankMerges(unittest.TestCase):
    def test_a_retype_cannot_turn_a_rank_into_a_person(self):
        kb = knowledge()
        kb.apply_retypes([{"name": "Ashwright", "from": "rank", "to": "character", "reason": "", "source": "llm"}])
        self.assertEqual(kb.entities["Ashwright"]["type"], "rank")

    def test_a_person_is_never_merged_into_a_power_entry(self):
        for power in ("Ashwright", "Sparkwater"):
            kb = knowledge()
            kb.apply_merges([{"a": "Stout man at the fair", "b": power, "same": True, "canonical": power,
                              "revealed": {"basis": "quote", "chapter": 3, "quote": "q"}}])
            self.assertEqual(kb.entities["Stout man at the fair"]["type"], "character")
            self.assertIn(power, kb.entities)
            self.assertNotIn("absorbed", kb.entities[power])

    def test_people_still_merge_with_each_other(self):
        kb = knowledge()
        kb.upsert_entity({"name": "Oda Brent", "type": "character", "aliases": []}, 2)
        kb.apply_merges([{"a": "Stout man at the fair", "b": "Oda Brent", "same": True, "canonical": "Oda Brent",
                          "revealed": {"basis": "quote", "chapter": 3, "quote": "q"}}])
        self.assertNotIn("Stout man at the fair", kb.entities)


if __name__ == "__main__":
    unittest.main()
