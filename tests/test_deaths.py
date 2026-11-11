import json
import unittest

from annalist.deaths import DEATH_WORDS, death_candidates
from annalist.state import load_states

from tests.test_build import TOMAS_DIES
from tests.test_pipeline import MiniBook, mini_script

ALIVE_AFTER = "\"If anything happens to me, the lamp is yours,\" Tomas said."
NOT_IN_BOOK = "Tomas opened his eyes in the body of the drowned keeper and stood up."


class OutlivedDeathTest(unittest.TestCase):
    def setUp(self):
        self.book = MiniBook(mini_script())
        self.addCleanup(self.book.tmp.cleanup)
        self.book.read(5)

    def profile_status(self, death):
        dead = {"value": "dead", "chapter": 3, "asserted_by": "narrator", "quotes": TOMAS_DIES["quotes"]}
        self.book.workdir.joinpath("script.json").write_text(json.dumps({"replies": [
            {"purpose": "profile", "reply": {"status": [dead]}},
            {"purpose": "profile-support", "reply": {"verdicts": [{"id": "O1", "verdict": "supported"}]}},
            {"purpose": "profile-field", "reply": {"observations": []}},
            {"purpose": "death", "contains": '"Tomas Hale" die in chapter 3', "reply": death},
            {"purpose": "death", "reply": {"died": False}}]}), encoding="utf-8")
        for cached in self.book.workdir.joinpath("cache").glob("*.json"):
            cached.unlink()
        self.book.run("profile", str(self.book.workdir), "--character", "Tomas Hale")
        data = json.loads(self.book.workdir.joinpath("profiles.json").read_text(encoding="utf-8"))
        status = [(o["value"], o["chapter"]) for o in data["characters"]["Tomas Hale"]["fields"]["status"]]
        return status, [(d["name"], d["chapter"]) for d in data["deaths"]]

    def test_a_death_the_character_lives_on_after_is_not_their_death(self):
        status, deaths = self.profile_status({**TOMAS_DIES, "lives_on": True, "lives_on_quotes": [ALIVE_AFTER]})
        self.assertNotIn(("dead", 3), status)
        self.assertEqual(deaths, [])

    def test_a_death_stands_when_living_on_is_not_shown_by_the_text(self):
        status, deaths = self.profile_status({**TOMAS_DIES, "lives_on": True, "lives_on_quotes": [NOT_IN_BOOK]})
        self.assertIn(("dead", 3), status)
        self.assertEqual(deaths, [("Tomas Hale", 3)])

    def test_a_present_death_without_living_on_stands(self):
        status, deaths = self.profile_status({**TOMAS_DIES, "lives_on": False})
        self.assertIn(("dead", 3), status)
        self.assertEqual(deaths, [("Tomas Hale", 3)])


LATER_QUOTE = "Captain Fenn arrested Sabine Oake for the wreck of the Gannet and the deaths of twenty-two people, and Bram Ostrow for the death of Tomas Hale."


class RepeatedDeathTest(unittest.TestCase):
    def test_a_death_reported_again_later_stays_one_death_at_its_first_chapter_with_the_later_detail(self):
        book = MiniBook(mini_script())
        self.addCleanup(book.tmp.cleanup)
        book.read(5)
        dead = [{"value": "dead", "chapter": 3, "asserted_by": "narrator", "quotes": TOMAS_DIES["quotes"]},
                {"value": "dead", "chapter": 5, "asserted_by": "narrator", "quotes": [LATER_QUOTE]}]
        again = {"died": True, "chapter": 5, "circumstances": "Bram Ostrow is arrested for Tomas Hale's death.", "quotes": [LATER_QUOTE]}
        book.workdir.joinpath("script.json").write_text(json.dumps({"replies": [
            {"purpose": "profile", "reply": {"status": dead}},
            {"purpose": "profile-support", "reply": {"verdicts": [{"id": "O1", "verdict": "supported"}, {"id": "O2", "verdict": "supported"}]}},
            {"purpose": "profile-field", "reply": {"observations": []}},
            {"purpose": "death", "contains": '"Tomas Hale" die in chapter 3', "reply": TOMAS_DIES},
            {"purpose": "death", "contains": '"Tomas Hale" die in chapter 5', "reply": again},
            {"purpose": "death", "reply": {"died": False}}]}), encoding="utf-8")
        for cached in book.workdir.joinpath("cache").glob("*.json"):
            cached.unlink()
        book.run("profile", str(book.workdir), "--character", "Tomas Hale")
        deaths = json.loads(book.workdir.joinpath("profiles.json").read_text(encoding="utf-8"))["deaths"]
        self.assertEqual([(d["name"], d["chapter"]) for d in deaths], [("Tomas Hale", 3)])
        self.assertEqual([(l["chapter"], l["circumstances"]) for l in deaths[0]["later"]], [(5, again["circumstances"])])
        self.assertEqual(deaths[0]["later"][0]["quotes"], [LATER_QUOTE])


if __name__ == "__main__":
    unittest.main()


class KillerSideDeathTest(unittest.TestCase):
    def test_a_death_filed_only_under_the_killer_makes_the_victim_a_candidate(self):
        book = MiniBook(mini_script())
        self.addCleanup(book.tmp.cleanup)
        book.read(5)
        kb = load_states(book.workdir)
        kb.facts = [f for f in kb.facts if not (f["entity"] == "Tomas Hale" and DEATH_WORDS.search(f["claim"]))]
        kb.relations = [r for r in kb.relations if r["target"] != "Tomas Hale"]
        kb.facts.append({"entity": "Bram Ostrow", "chapter": 3, "claim": "Bram Ostrow kills Tomas Hale on the stairs.",
                         "quotes": [], "status": "stated", "timeline": "main"})
        volumes = [{"from": 1, "to": 5}]
        self.assertIn(("Tomas Hale", 3), death_candidates(kb, {}, volumes, 5))


class FuneralDeathTest(unittest.TestCase):
    def test_a_death_shown_only_by_a_funeral_or_a_grave_makes_a_candidate(self):
        book = MiniBook(mini_script())
        self.addCleanup(book.tmp.cleanup)
        book.read(5)
        for claim in ("After Tomas Hale's funeral, the crowd stood in the rain.", "Tomas Hale's tombstone reads 'Keeper of the lamp'."):
            kb = load_states(book.workdir)
            kb.facts = [f for f in kb.facts if not (f["entity"] == "Tomas Hale" and DEATH_WORDS.search(f["claim"]))]
            kb.relations = [r for r in kb.relations if r["target"] != "Tomas Hale"]
            kb.facts.append({"entity": "Tomas Hale", "chapter": 3, "claim": claim, "quotes": [], "status": "stated", "timeline": "main"})
            self.assertIn(("Tomas Hale", 3), death_candidates(kb, {}, [{"from": 1, "to": 5}], 5), claim)
