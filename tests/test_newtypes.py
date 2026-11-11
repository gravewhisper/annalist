import html
import json
import re
import unittest

from annalist.newtypes import new_type_problems
from annalist.state import load_states
from tests.test_build import MiniBuild, build_script, MINI, ran, site_views

SHIP = {"type": "ship", "parent": "artifact", "label": "Ships", "description": "a vessel that sails the coast"}
FIRST_VOLUME = {"new_types": [SHIP], "moves": [{"name": "Gannet", "type": "ship"}, {"name": "Kestrel", "type": "ship"}]}


def two_volume_script():
    script = build_script()
    script["replies"].insert(0, {"purpose": "newtypes", "contains": "which ends at chapter 3", "reply": FIRST_VOLUME})
    return script


def text(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


class VolumeEndTypeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(two_volume_script())
        cls.first = cls.book.build("--volumes", "1-3,4-5")
        cls.calls = len(cls.book.calls("newtypes"))
        cls.second = cls.book.build("--volumes", "1-3,4-5")
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.ids = {e["name"]: e["id"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_a_volume_end_adds_a_type_and_files_earlier_entries_under_it_from_that_chapter_on(self):
        volumes = self.book.json("newtypes.json")["volumes"]
        self.assertEqual([(v["to"], list(v["types"])) for v in volumes], [(3, ["ship"]), (5, [])])
        self.assertEqual(volumes[0]["moves"], [{"name": "Gannet", "from": "artifact", "to": "ship"},
                                               {"name": "Kestrel", "from": "artifact", "to": "ship"}])
        early, late = (load_states(self.book.workdir, until=n) for n in (2, 3))
        self.assertEqual((early.entities["Kestrel"]["type"], late.entities["Kestrel"]["type"]), ("artifact", "ship"))
        self.assertEqual(late.types.kind("ship"), "artifact")

    def test_the_site_shows_the_new_category_only_from_the_volume_end(self):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        kestrel = self.ids["Kestrel"]
        views = site_views(path, "home@2", "home@3", f"{kestrel}@2", f"{kestrel}@3", "route:cat:ship@2", "route:cat:artifact@3")
        self.assertNotIn("Ships", text(views["home@2"]))
        self.assertIn("Ships", text(views["home@3"]))
        self.assertIn("Home › Artifacts Kestrel", text(views[f"{kestrel}@2"]))
        self.assertIn("Home › Artifacts › Ships Kestrel", text(views[f"{kestrel}@3"]))
        self.assertNotRegex(text(views["route:cat:ship@2"]["html"]), r"(?i)\bships?\b")
        self.assertIn("Subcategories Ships 2", text(views["route:cat:artifact@3"]["html"]))

    def test_a_rebuild_keeps_the_decision_and_asks_nothing_again(self):
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(self.book.calls("newtypes")), 2)
        self.assertNotIn("newtypes", ran(self.second.stdout))


ENTRIES = {"Gannet": "artifact", "Kestrel": "artifact", "Corvel Quay": "place", "Lamplighters' Guild": "organization"}
KINDS = {"ward": {"parent": "artifact", "description": "a protective charm a keeper sets"}}
TEXT = "A ship came in under a red sail. The ships of the quay. The Guild kept wards and charms. A guild of keepers met."


def problems(reply, kinds=KINDS, added=None, names=None):
    return new_type_problems(reply, kinds, added or {}, ENTRIES, names or ENTRIES, TEXT) or ""


class NewTypeCheckTest(unittest.TestCase):
    def test_a_valid_new_type_passes(self):
        self.assertEqual(problems(FIRST_VOLUME), "")

    def test_a_label_the_book_has_not_written_by_the_volume_end_is_rejected(self):
        reply = {**FIRST_VOLUME, "new_types": [{**SHIP, "label": "Galleons"}]}
        self.assertIn('new type "ship" needs a label the novel itself writes', problems(reply))

    def test_a_new_type_that_overlaps_a_sibling_or_holds_too_few_entries_is_rejected(self):
        charm = {"type": "warding charm", "parent": "artifact", "label": "charms", "description": "a charm against the sea"}
        reply = {"new_types": [charm], "moves": [{"name": "Gannet", "type": "warding charm"}]}
        found = problems(reply)
        self.assertIn('the artifact subcategories "ward" and "warding charm" overlap', found)
        self.assertIn('new type "warding charm" holds 1 of the listed entries', found)

    def test_a_new_type_named_like_an_entry_is_rejected(self):
        guild = {"type": "guild", "parent": "organization", "label": "guilds", "description": "a body of keepers"}
        reply = {"new_types": [guild], "moves": [{"name": "Lamplighters' Guild", "type": "guild"}, {"name": "Gannet", "type": "guild"}]}
        names = {**ENTRIES, "The Guild": "organization"}
        found = problems(reply, names=names)
        self.assertIn('the subcategory "guilds" is named like the organization "The Guild"', found)
        self.assertIn('"Gannet" is filed under artifact, but "guild" is a kind of organization', found)

    def test_an_entry_may_move_into_a_type_an_earlier_volume_added(self):
        added = {"ship": {**SHIP, "chapter": 3}}
        reply = {"new_types": [], "moves": [{"name": "Gannet", "type": "ship"}, {"name": "Corvel Quay", "type": "harbour"}]}
        found = problems(reply, kinds={**KINDS, "ship": SHIP}, added=added)
        self.assertNotIn("Gannet", found)
        self.assertIn('"Corvel Quay" is moved to "harbour", which is neither a new type nor one added earlier', found)


if __name__ == "__main__":
    unittest.main()
