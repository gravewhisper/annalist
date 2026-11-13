import json
import tempfile
import unittest
from pathlib import Path

from annalist.state import load_states


def person(name, *aliases):
    return {"name": name, "type": "character", "aliases": [{"name": a, "unique": True} for a in aliases]}


def fact(entity, claim):
    return {"entity": entity, "claim": claim, "quotes": [claim], "asserted_by": "narrator", "status": "stated"}


STATES = {1: ([person("Serrin Vale")], [fact("Serrin Vale", f"Serrin Vale did thing {i}.") for i in range(4)]),
          2: ([person("Count Orvell")], [fact("Count Orvell", "Count Orvell rules the harbour.")]),
          3: ([person("Serrin Vale", "Count Orvell"), person("Count Orvell", "Winner Lantern")], [])}


class KeptApart(unittest.TestCase):
    def load(self, corrections, merges=()):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            for n, (entities, facts) in STATES.items():
                (root / "state" / f"{n:04d}.json").write_text(json.dumps({"chapter": n, "extraction": {"entities": entities, "facts": facts}}))
            (root / "corrections.json").write_text(json.dumps({"entries": corrections}))
            (root / "merges.json").write_text(json.dumps({"pairs": list(merges)}))
            return load_states(root)

    def test_without_a_row_the_read_joins_the_two_pages(self):
        self.assertNotIn("Count Orvell", self.load([]).entities)

    def test_two_pages_kept_apart_never_merge(self):
        merge = {"a": "Serrin Vale", "b": "Count Orvell", "canonical": "Serrin Vale", "same": True,
                 "revealed": {"basis": "quote", "chapter": 3, "quote": "x"}}
        kb = self.load([{"name": "Count Orvell", "not_same_as": ["Serrin Vale"], "why": "Two different people."}], [merge])
        self.assertEqual(kb.resolve("Count Orvell"), "Count Orvell")
        self.assertEqual(sum(f["entity"] == "Serrin Vale" for f in kb.facts), 4)
        self.assertNotIn("Count Orvell", kb.entities["Serrin Vale"]["aliases"])

    def test_a_dropped_alias_is_never_attached(self):
        kb = self.load([{"name": "Count Orvell", "drop_aliases": ["Winner Lantern"]}])
        page = kb.resolve("Count Orvell")
        self.assertNotIn("Winner Lantern", kb.entities[page]["aliases"])
        self.assertIsNone(kb.resolve("Winner Lantern"))


if __name__ == "__main__":
    unittest.main()
