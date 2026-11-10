import copy
import unittest

from annalist.scorecard import Wiki
from tests.test_build import MiniBuild, build_script

TOMAS_LOST = {"died": False, "missing": True, "chapter": 3, "circumstances": "Tomas walked to the gate in the fog and did not come back.",
              "quotes": ["He did not come back."]}


def missing_script():
    script = build_script(skip_purposes={"death"})
    script["replies"].insert(0, {"purpose": "death", "contains": '"Tomas Hale" die in chapter 3', "reply": TOMAS_LOST})
    script["replies"].append({"purpose": "death", "reply": {"died": False, "missing": False}})
    return script


class MissingStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(missing_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.tomas = next(e for e in cls.wiki["entities"] if e["name"] == "Tomas Hale")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_a_character_the_death_reading_finds_vanished_is_missing_and_not_listed_among_the_deaths(self):
        self.assertEqual(Wiki(self.wiki).status(self.tomas["id"], 3)["value"], "missing")
        self.assertNotIn("Tomas Hale", [d["name"] for d in self.book.json("profiles.json")["deaths"]])

    def test_a_missing_character_who_speaks_later_in_the_present_is_alive(self):
        wiki = copy.deepcopy(self.wiki)
        tomas = next(e for e in wiki["entities"] if e["name"] == "Tomas Hale")
        tomas["profile"]["spoke"].append([5, "main"])
        self.assertEqual(Wiki(wiki).status(tomas["id"], 4)["value"], "missing")
        self.assertEqual(Wiki(wiki).status(tomas["id"], 5)["value"], "alive")


if __name__ == "__main__":
    unittest.main()
