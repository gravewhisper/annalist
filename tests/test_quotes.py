import unittest

from annalist.scorecard import Wiki
from tests.test_build import PROFILE_QUOTE, TOMAS_DIES, MiniBuild, build_script

ELSEWHERE = "Tomas was the keeper of the harbour lamp and a sworn member of the Lamplighters' Guild"
INVENTED = "Ines was forty and had never set foot in Corvel Quay."


def mixed_quote_script():
    script = build_script(skip_purposes={"death", "profile"})
    script["replies"].insert(0, {"purpose": "death", "contains": '"Tomas Hale" die in chapter 3',
                                 "reply": {**TOMAS_DIES, "quotes": TOMAS_DIES["quotes"] + [ELSEWHERE]}})
    script["replies"].insert(0, {"purpose": "profile", "reply": {
        "age": [{"value": "nineteen", "chapter": 1, "quotes": [PROFILE_QUOTE, INVENTED], "asserted_by": "narrator"}]}})
    script["replies"].append({"purpose": "death", "reply": {"died": False}})
    return script


class MixedQuotesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(mixed_quote_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.profiles = cls.book.json("profiles.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def entity(self, name):
        return next(e for e in self.wiki["entities"] if e["name"] == name)

    def test_a_death_with_one_quote_from_another_chapter_still_sets_the_status(self):
        self.assertEqual(Wiki(self.wiki).status(self.entity("Tomas Hale")["id"], 3)["value"], "dead")
        death = next(d for d in self.profiles["deaths"] if d["name"] == "Tomas Hale")
        self.assertEqual(death["quotes"], TOMAS_DIES["quotes"])
        self.assertEqual(death["dropped_quotes"], [ELSEWHERE])

    def test_a_profile_observation_keeps_its_verified_quote_and_records_the_dropped_one(self):
        age = self.profiles["characters"]["Ines Varro"]["fields"]["age"]
        self.assertEqual([(o["value"], o["quotes"], o["dropped_quotes"]) for o in age], [("nineteen", [PROFILE_QUOTE], [INVENTED])])
        self.assertEqual([o["value"] for o in self.entity("Ines Varro")["profile"]["fields"]["age"]], ["nineteen"])


if __name__ == "__main__":
    unittest.main()
