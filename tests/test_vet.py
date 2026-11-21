import unittest

from annalist.vet import relation_key
from tests.test_build import MiniBuild
from tests.test_relate import RELATE_CH3, relate_script

NEWS = "acting on news from"
CONFIDED = "confided in by"
AFTER_NEWS_QUOTE = "Sister Wren looked at him for a long moment."


def relate_row(rtype):
    raw = next(r for r in RELATE_CH3["relations"] if r["type"] == rtype)
    return {"chapter": 3, "source": raw["source"], "type": rtype, "target": raw["target"], "detail": "", "quotes": [raw["quote"]]}


def vet_script():
    script = relate_script()
    script["replies"].insert(0, {"purpose": "vet", "contains": AFTER_NEWS_QUOTE, "reply": {"verdicts": [
        {"id": relation_key(relate_row(NEWS)), "verdict": "unsupported", "reason": "The line says nothing of news."},
        {"id": relation_key(relate_row(CONFIDED)), "verdict": "correct", "reason": "They spoke for an hour."}]}})
    return script


class VetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(vet_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def shown(self, chapter):
        names = {e["id"]: e["name"] for e in self.wiki["entities"]}
        return {(names[r["source"]], r["type"], names[r["target"]]) for r in self.wiki["relations"] if r["chapter"] == chapter}

    def test_a_relation_the_check_finds_unsupported_leaves_the_wiki_and_a_correct_one_stays(self):
        self.assertNotIn(("Tomas Hale", NEWS, "Odile Marr"), self.shown(3))
        self.assertIn(("Tomas Hale", CONFIDED, "Odile Marr"), self.shown(3))

    def test_the_check_reads_the_passage_around_each_quote_not_only_the_quote(self):
        self.assertEqual([c["chapter"] for c in self.book.calls("vet") if c["chapter"] == 3], [3])

    def test_the_verdicts_are_kept_with_their_reasons(self):
        verdicts = self.book.json("vet.json")["verdicts"]
        self.assertEqual(verdicts[relation_key(relate_row(NEWS))], {"verdict": "unsupported", "reason": "The line says nothing of news."})
        self.assertEqual(verdicts[relation_key(relate_row(CONFIDED))]["verdict"], "correct")

    def test_a_rebuild_with_unchanged_relations_asks_nothing_new(self):
        before = len(self.book.calls("vet"))
        self.book.build()
        self.assertEqual(len(self.book.calls("vet")), before)

    def test_a_dry_run_prices_the_check_and_asks_nothing(self):
        before = len(self.book.calls())
        out = self.book.run_annalist("vet", str(self.book.workdir), "--dry-run").stdout
        self.assertIn("price:", out)
        self.assertEqual(len(self.book.calls()), before)


if __name__ == "__main__":
    unittest.main()
