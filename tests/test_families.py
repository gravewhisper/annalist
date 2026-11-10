import unittest

from annalist.families import relation_family
from annalist.state import Knowledge
from tests.test_build import MiniBuild
from tests.test_relate import TOMAS_ODILE, relate_script

COURTSHIP = "suspects a secret courtship between Ines Varro and"
PARTNER = "colleague and investigation partner of"
NEWS = "acting on news from"

RELATE_EXTRA = [
    {"source": "Odile Marr", "type": COURTSHIP, "target": "Tomas Hale", "quote": TOMAS_ODILE,
     "asserted_by": "narrator", "status": "belief"},
    {"source": "Tomas Hale", "type": PARTNER, "target": "Odile Marr", "quote": TOMAS_ODILE,
     "asserted_by": "narrator", "status": "stated"},
]

READINGS = {"kinds": [{"wording": PARTNER, "target": "character", "kind": "alliance"},
                      {"wording": NEWS, "target": "character", "kind": "alliance"}]}

CHANTS = "chants from"
LEDGER_LINE = ("Tomas lit it himself at half past four, trimmed the wick, wrote the hour in the Salt Ledger, "
               "and went down to the quay to watch for a red-and-white sail.")
RELATE_CH2 = {"relations": [{"source": "Tomas Hale", "type": CHANTS, "target": "Salt Ledger", "quote": LEDGER_LINE,
                             "asserted_by": "narrator", "status": "stated"}]}
THING_READING = {"kinds": READINGS["kinds"] + [{"wording": CHANTS, "target": "artifact", "kind": "ownership"}]}


def families_script():
    script = relate_script()
    script["replies"][0]["reply"] = {"relations": script["replies"][0]["reply"]["relations"] + RELATE_EXTRA}
    script["replies"].insert(0, {"purpose": "families", "contains": f"source [character] {CHANTS} target [artifact]", "reply": THING_READING})
    script["replies"].insert(0, {"purpose": "relate", "contains": "CHAPTER 2: Nine Winters Ago", "reply": RELATE_CH2})
    return script


def entity(name, etype="character"):
    return {"name": name, "type": etype, "aliases": [], "summary": ""}


def chapter_state(relations):
    names = ("Ada Brook", "Cyril Penn", "Dora Vale", "the Quiet Bureau")
    return {"chapter": 1, "title": "One", "extraction": {"entities": [entity(n) for n in names[:3]] + [entity(names[3], "organization")],
                                                        "relations": relations}}


def relation(source, rtype, target, status="belief", asserted_by="narrator"):
    return {"source": source, "type": rtype, "target": target, "quotes": ["q"], "asserted_by": asserted_by, "status": status}


def pairs(kb):
    return {(r["source"], r["type"], r["target"], r["status"], r["asserted_by"]) for r in kb.relations}


class RuleFamilyTest(unittest.TestCase):
    def test_investigating_or_suspecting_someone_is_investigation_not_hostility(self):
        for wording in ("investigates", "suspects performed the rite:", "is investigating", "suspected by"):
            self.assertEqual(relation_family(wording), "investigation", wording)
        self.assertEqual(relation_family("enemy of"), "hostility")

    def test_helping_in_any_tense_is_alliance(self):
        for wording in ("assists", "assist", "assisted", "helps", "helped"):
            self.assertEqual(relation_family(wording), "alliance", wording)

    def test_a_wording_with_a_friendly_tie_and_an_investigative_one_is_the_friendly_tie_without_a_reading(self):
        self.assertEqual(relation_family(PARTNER), "alliance")
        self.assertEqual(relation_family("friend and rival of"), "alliance")

    def test_a_reading_of_the_wording_decides_over_the_rules(self):
        self.assertEqual(relation_family(NEWS), "other")
        readings = {f"{NEWS} [character]": "alliance"}
        self.assertEqual(relation_family(NEWS, readings, "character"), "alliance")
        self.assertEqual(relation_family("Acting on news from.", readings, "character"), "alliance")
        self.assertEqual(relation_family(NEWS, readings, "artifact"), "other")
        self.assertEqual(relation_family(NEWS, readings), "other")


class ThirdPartyTest(unittest.TestCase):
    def test_a_belief_about_two_other_entries_is_filed_on_them_and_held_by_the_believer(self):
        kb = Knowledge()
        kb.apply(chapter_state([relation("Ada Brook", "suspects romantic interest between Cyril Penn and", "Dora Vale"),
                                relation("Ada Brook", "thinks Cyril Penn loves", "Dora Vale"),
                                relation("Ada Brook", "suspects Cyril Penn's debt to", "Dora Vale")]))
        self.assertEqual(pairs(kb), {("Cyril Penn", "romantic interest with", "Dora Vale", "belief", "Ada Brook"),
                                     ("Cyril Penn", "loves", "Dora Vale", "belief", "Ada Brook"),
                                     ("Cyril Penn", "debt to", "Dora Vale", "belief", "Ada Brook")})

    def test_a_relation_naming_only_its_own_ends_stated_as_fact_or_naming_another_only_in_passing_stays_on_its_pair(self):
        kb = Knowledge()
        kb.apply(chapter_state([relation("Ada Brook", "suspects Dora Vale of hiding", "Dora Vale"),
                                relation("Ada Brook", "mediator between Cyril Penn and", "Dora Vale", status="stated"),
                                relation("Ada Brook", "believes was sent by Cyril Penn to watch", "Dora Vale"),
                                relation("Ada Brook", "member of", "the Quiet Bureau", status="stated")]))
        self.assertEqual({(s, t) for s, _, t, _, _ in pairs(kb)}, {("Ada Brook", "Dora Vale"), ("Ada Brook", "the Quiet Bureau")})

    def test_a_filled_in_belief_about_two_other_entries_is_filed_on_them(self):
        kb = Knowledge()
        kb.apply(chapter_state([]))
        row = {"chapter": 1, "source": "Ada Brook", "target": "Dora Vale", "type": "thinks Cyril Penn loves", "quotes": ["q"],
               "asserted_by": "narrator", "status": "belief", "timeline": "main"}
        kb.apply_filled({"1": {"relations": [row]}}, None, "RF")
        self.assertEqual(pairs(kb), {("Cyril Penn", "loves", "Dora Vale", "belief", "Ada Brook")})
        self.assertEqual(kb.relations[0]["id"], "RF0001-001")


class FamiliesMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(families_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.names = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def shown(self, source, target):
        return [r for r in self.wiki["relations"] if (self.names[r["source"]], self.names[r["target"]]) == (source, target)]

    def test_wordings_the_rules_cannot_settle_are_read_once_and_the_reading_colours_the_graph(self):
        self.assertEqual({r["type"]: r["family"] for r in self.shown("Tomas Hale", "Odile Marr")},
                         {"confided in by": "other", NEWS: "alliance", PARTNER: "alliance"})
        asked = self.book.calls("families")
        self.assertEqual(len(asked), 1)
        self.book.run_annalist("families", str(self.book.workdir))
        self.assertEqual(len(self.book.calls("families")), 1)

    def test_a_wording_the_rules_cannot_settle_is_read_with_the_kind_of_its_target_and_coloured_by_that_reading(self):
        self.assertEqual({r["type"]: r["family"] for r in self.shown("Tomas Hale", "Salt Ledger")}, {CHANTS: "ownership"})

    def test_a_suspected_romance_between_two_others_is_drawn_between_them_as_the_believers_suspicion(self):
        self.assertFalse([r for r in self.shown("Odile Marr", "Tomas Hale") if "courtship" in r["type"]])
        rows = self.shown("Ines Varro", "Tomas Hale")
        self.assertEqual([(r["type"], r["family"], r["status"], r["by"]) for r in rows if "courtship" in r["type"]],
                         [("secret courtship with", "romance", "belief", "Odile Marr")])

    def test_every_relation_says_who_asserts_it(self):
        self.assertTrue(all("by" in r for r in self.wiki["relations"]))


if __name__ == "__main__":
    unittest.main()
