import json
import re
import tempfile
import unittest
from pathlib import Path

from annalist.state import load_states
from tests.test_build import ROOT, site_views
from tests.test_merge_rules import entry, fact, Run

CHAPTERS = {
    1: ("The Eel",
        "A lantern eel rose beside the quay while Ilse lit the lamp. Gristle, the grey eel of the harbour, said: "
        "\"Keep your lamp lit, girl.\" Far out, a tide wraith moaned over the shoals.\n"),
}

EXTRACTIONS = {
    1: {"entities": [entry("Ilse", "character", "A lamp girl."), entry("Lantern eel", "beast", "A glowing eel of the quay."),
                     entry("Gristle", "creature", "The grey eel of the harbour."),
                     entry("Tide wraith", "creature", "A spirit that moans over the shoals.")],
        "facts": [{**fact("Ilse", "Gristle told Ilse to keep her lamp lit.", "\"Keep your lamp lit, girl.\""), "asserted_by": "Gristle"},
                  fact("Tide wraith", "A tide wraith moaned over the shoals.", "a tide wraith moaned over the shoals")]},
}

BOOK = {"title": "Quay", "backend": {"name": "fake", "script": "script.json"}, "power_system": "", "timeline_kind": "linear",
        "power_types": {}}

REPLIES = [
    {"purpose": "retype", "contains": "Name: Tide wraith", "reply": {"items": [
        {"id": str(i), "type": "concept", "reason": "Checked by mistake."} for i in range(1, 4)]}},
    {"purpose": "retype", "contains": "- creature: a kind, species, or race of non-human being", "reply": {"items": [
        {"id": "1", "type": "character", "reason": "A named eel who speaks."},
        {"id": "2", "type": "creature", "reason": "A kind of eel."}]}},
    {"purpose": "retype", "reply": {"items": []}},
]


def creature_wiki():
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": [[1, f"{n} of the quay."]]}
                for i, (n, t) in enumerate([("Ilse", "character"), ("Lantern eel", "creature"), ("Gristle", "character")], 1)]
    ids = {e["name"]: e["id"] for e in entities}
    facts = [{"id": "F0001-001", "chapter": 1, "entity": ids["Lantern eel"], "claim": "A lantern eel rose beside the quay.", "status": "stated",
              "by": "narrator", "quotes": []}]
    return {"book": {"title": "Quay", "max": 1, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": 1, "title": "The Eel", "synopsis": ""}],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": facts, "relations": [], "questions": [], "ladders": [], "volumes": []}, ids


def plain(markup):
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


class CreatureRetypeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quay = Run(CHAPTERS, EXTRACTIONS, BOOK, REPLIES)
        cls.quay.run("retype", str(cls.quay.workdir), "--jobs", "1")
        cls.kb = load_states(cls.quay.workdir)

    @classmethod
    def tearDownClass(cls):
        cls.quay.close()

    def test_a_kind_of_being_can_be_filed_as_a_creature(self):
        self.assertEqual(self.kb.entities["Lantern eel"]["type"], "creature")

    def test_a_creature_that_speaks_is_checked_and_can_become_a_character(self):
        self.assertEqual(self.kb.entities["Gristle"]["type"], "character")

    def test_a_creature_that_never_speaks_is_a_general_type_and_is_not_checked(self):
        self.assertEqual(self.kb.entities["Tide wraith"]["type"], "creature")


class CreatureSiteTest(unittest.TestCase):
    def test_a_creature_has_its_own_category_and_a_page_without_a_character_profile(self):
        wiki, ids = creature_wiki()
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
            views = site_views(path, "route:cat:creature@1", "home@1", f"{ids['Lantern eel']}@1", "tables@1")
        self.assertIn("Lantern eel", plain(views["route:cat:creature@1"]["html"]))
        self.assertNotIn("Gristle", plain(views["route:cat:creature@1"]["html"]))
        self.assertIn("Creatures 1", plain(views["home@1"]))
        page = views[f"{ids['Lantern eel']}@1"]
        self.assertIn("Type Creature", plain(page))
        self.assertNotIn('data-tab="profile"', page)
        self.assertIn("creature", next(g for g in views["tables@1"]["types"] if g["key"] == "lore")["types"])


if __name__ == "__main__":
    unittest.main()
