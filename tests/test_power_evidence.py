import tempfile
import unittest
from pathlib import Path

from annalist.evidence import add_evidence
from annalist.state import Knowledge

BOOK = {"extra_fields": {"school_rank": "rank"}, "field_values": {"school_rank": ["Ashwright"]},
        "ladder": {"group_type": "school", "step_type": "rank", "rank": "number"}}
TEXT = ("Ilse drank the Glassreader draught at dawn. Oda was the Tidecaller of the harbor. The storm slowed Bram, a Second Reckoner. "
        "As a Glassreader, Ilse read the room. Finn guessed Tova was a Tidecaller, and Finn was just a baker.")


def fact(entity, claim, quote, status="stated", n=1):
    return {"id": f"F{entity}{len(claim)}", "chapter": n, "entity": entity, "claim": claim, "quotes": [quote], "status": status,
            "asserted_by": "narrator", "timeline": "main"}


class PowerEvidence(unittest.TestCase):
    def evidence(self, name, facts):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "chapters").mkdir()
            (root / "chapters" / "0001.txt").write_text(TEXT, encoding="utf-8")
            kb = Knowledge(BOOK["ladder"])
            for rank in ("Glassreader", "Tidecaller", "Reckoner"):
                kb.upsert_entity({"name": rank, "type": "rank", "aliases": []}, 1)
            for person in ("Ilse", "Oda", "Bram", "Tova", "Finn"):
                kb.upsert_entity({"name": person, "type": "character", "aliases": []}, 1)
            kb.facts = facts
            profile = add_evidence(root, kb, name, {"fields": {}, "extra": {}, "lists": {}}, {}, [], BOOK)
            return [(o["value"], o["chapter"]) for o in profile["extra"]["school_rank"]]

    def test_a_ladder_rank_outside_the_survey_list_counts(self):
        self.assertEqual(self.evidence("Oda", [fact("Oda", "Oda was the Tidecaller of the harbor.", "Oda was the Tidecaller")]), [("Tidecaller", 1)])

    def test_drinking_a_rank_draught_counts(self):
        self.assertEqual(self.evidence("Ilse", [fact("Ilse", "Ilse drank the Glassreader draught at dawn.", "Ilse drank the Glassreader draught")]), [("Glassreader", 1)])

    def test_apposition_and_as_a_rank_count(self):
        self.assertEqual(self.evidence("Bram", [fact("Bram", "The storm slowed Bram, a Second Reckoner.", "slowed Bram, a Second Reckoner")]), [("Reckoner", 1)])
        self.assertEqual(self.evidence("Ilse", [fact("Ilse", "As a Glassreader, Ilse read the room.", "As a Glassreader, Ilse read the room")]), [("Glassreader", 1)])

    def test_a_suspicion_or_a_plain_character_stays_blank(self):
        self.assertEqual(self.evidence("Tova", [fact("Tova", "Finn guessed Tova was a Tidecaller.", "Tova was a Tidecaller", status="belief")]), [])
        self.assertEqual(self.evidence("Finn", [fact("Finn", "Finn was just a baker.", "Finn was just a baker")]), [])


if __name__ == "__main__":
    unittest.main()
