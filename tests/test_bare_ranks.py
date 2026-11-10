import json
import tempfile
import unittest
from pathlib import Path

from annalist.state import Knowledge, load_states

ROOT = Path(__file__).resolve().parent.parent
NUMBERED = {"group_type": "school", "step_type": "rank", "rank": "number", "direction": "ascending", "note": ""}
ORDERED = {**NUMBERED, "rank": "order", "direction": "ascending"}


def entry(name, aliases=()):
    return {"name": name, "type": "rank", "aliases": list(aliases), "summary": f"{name} is a step."}


def relation(source, target, kind):
    return {"source": source, "target": target, "type": kind, "detail": "", "quotes": [f"{source} {kind} {target}"]}


EXTRACTION = {"entities": [{"name": "Lin Wei", "type": "character", "aliases": [], "summary": "A disciple."},
                           entry("Iron Fist"), entry("Jade Palm")],
              "facts": [{"entity": "Rank 3", "claim": "Rank 3 is the third step.", "quotes": ["Rank 3 is the third step."]}],
              "relations": [relation("Iron Fist", "Rank 3", "is"), relation("Lin Wei", "Iron Fist", "holds"),
                            relation("Lin Wei", "Jade Palm", "seeks")]}


def same(a, b):
    return {"a": a, "b": b, "type": "rank", "rules": ["co-mentioned"], "same": True, "canonical": b, "reason": "",
            "revealed": {"chapter": 1, "quote": "", "basis": "quote"}}


HUB_VERDICTS = [same("Rank 3", "Iron Fist"), same("Rank 3", "Jade Palm")]


def built(ladder, verdicts=HUB_VERDICTS, extraction=EXTRACTION):
    with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
        work = Path(tmp)
        (work / "state").mkdir()
        (work / "book.json").write_text(json.dumps({"ladder": ladder}), encoding="utf-8")
        (work / "merges.json").write_text(json.dumps({"pairs": verdicts}), encoding="utf-8")
        (work / "state" / "0001.json").write_text(json.dumps({"chapter": 1, "extraction": extraction}), encoding="utf-8")
        return load_states(work)


def names(kb):
    return {e["name"]: e["aliases"] for e in kb.entities.values()}


class BareRankTest(unittest.TestCase):
    def test_cached_verdicts_through_a_bare_rank_leave_each_named_step_its_own_entry(self):
        kb = built(NUMBERED)
        self.assertEqual(names(kb), {"Lin Wei": [], "Iron Fist": [], "Jade Palm": []})
        self.assertEqual({(r["source"], r["type"], r["target"]) for r in kb.relations},
                         {("Lin Wei", "holds", "Iron Fist"), ("Lin Wei", "seeks", "Jade Palm")})

    def test_a_bare_rank_is_no_entry_whatever_its_case_and_holds_no_facts(self):
        kb = built(NUMBERED, [], {"entities": [entry("RANK  3"), entry("Iron Fist")], "facts": EXTRACTION["facts"], "relations": []})
        self.assertEqual(names(kb), {"Iron Fist": []})
        self.assertEqual(kb.facts, [])

    def test_a_shared_bare_rank_alias_neither_joins_two_steps_nor_stays_on_either(self):
        kb = Knowledge(NUMBERED)
        kb.upsert_entity(entry("Iron Fist", ["Rank 3", "The Fist"]), 1)
        kb.upsert_entity(entry("Jade Palm", ["Rank 3"]), 2)
        self.assertEqual(names(kb), {"Iron Fist": ["The Fist"], "Jade Palm": []})

    def test_a_rank_with_its_name_stays_an_entry(self):
        kb = Knowledge(NUMBERED)
        self.assertEqual(kb.upsert_entity(entry("Rank 3 Iron Fist"), 1), "Rank 3 Iron Fist")

    def test_a_legitimate_merge_of_two_named_steps_still_applies(self):
        kb = built(NUMBERED, [same("Jade Palm", "Iron Fist")])
        self.assertEqual(names(kb), {"Lin Wei": [], "Iron Fist": ["Jade Palm"]})

    def test_without_a_numbered_ladder_the_same_name_is_an_ordinary_entry(self):
        for ladder in (None, ORDERED):
            with self.subTest(ladder=ladder):
                kb = built(ladder)
                self.assertEqual(set(names(kb)), {"Lin Wei", "Jade Palm"})
                self.assertCountEqual(names(kb)["Jade Palm"], ["Rank 3", "Iron Fist"])


if __name__ == "__main__":
    unittest.main()
