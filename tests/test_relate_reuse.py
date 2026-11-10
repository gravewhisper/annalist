import json
import unittest

from annalist.relate import reusable_reply
from tests.test_build import MiniBuild, ran
from tests.test_relate import relate_script


class Renames:
    def resolve(self, name):
        return {"Old Name": "New Name"}.get(name, name)


def request(pairs, basis="same"):
    return {"kb": Renames(), "basis": basis, "pairs": pairs}


def saved(pairs, basis="same"):
    return {"basis": basis, "pairs": pairs, "reply": {"relations": []}}


class ReusableReplyTest(unittest.TestCase):
    def test_reuses_a_reply_when_the_pairs_are_the_same(self):
        self.assertTrue(reusable_reply(saved([["A", "B"]]), request([("A", "B")])))

    def test_follows_a_rename_when_comparing_pairs(self):
        self.assertTrue(reusable_reply(saved([["Old Name", "B"]]), request([("B", "New Name")])))

    def test_allows_two_new_pairs(self):
        self.assertTrue(reusable_reply(saved([["A", "B"]]), request([("A", "B"), ("A", "C"), ("A", "D")])))

    def test_asks_again_for_three_new_pairs(self):
        self.assertFalse(reusable_reply(saved([["A", "B"]]), request([("A", "B"), ("A", "C"), ("A", "D"), ("A", "E")])))

    def test_asks_again_when_the_chapter_or_rules_change(self):
        self.assertFalse(reusable_reply(saved([["A", "B"]]), request([("A", "B")], basis="different")))

    def test_asks_when_nothing_was_saved(self):
        self.assertFalse(reusable_reply(None, request([("A", "B")])))


class AliasChangeTest(unittest.TestCase):
    def test_a_new_alias_does_not_reask_relate(self):
        book = MiniBuild(relate_script())
        try:
            book.build()
            asked = len(book.calls("relate"))
            path = book.workdir / "state" / "0001.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            sabine = next(e for e in state["extraction"]["entities"] if e["name"] == "Sabine Oake")
            sabine["aliases"] = [*sabine.get("aliases", []), {"name": "Mistress of the Ledgers", "unique": True}]
            path.write_text(json.dumps(state), encoding="utf-8")
            rebuilt = book.build()
            self.assertIn("relate", ran(rebuilt.stdout))
            self.assertEqual(len(book.calls("relate")), asked)
        finally:
            book.close()


if __name__ == "__main__":
    unittest.main()
