import json
import shutil
import subprocess
import sys
import unittest

from tests.test_build import MiniBuild, ROOT
from tests.test_eval import statuses_script
from tests.test_quotes import INVENTED
from annalist.families import relation_family


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(statuses_script())
        cls.book.build()

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def export(self, workdir):
        proc = subprocess.run([sys.executable, "-m", "annalist", "export", str(workdir), str(workdir / "site")],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads((workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))

    def test_the_site_never_shows_a_fact_or_relation_quote_the_chapter_does_not_hold(self):
        workdir = self.book.root / "quotes"
        shutil.copytree(self.book.workdir, workdir)
        path = workdir / "state" / "0001.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        kept = {kind: [row for i, row in enumerate(state["extraction"][f"{kind}s"], 1)
                       if state["support"].get(f"{kind[0].upper()}{i}", {}).get("verdict") != "unsupported"] for kind in ("fact", "relation")}
        invented, mixed = kept["fact"][:2]
        good = mixed["quotes"][0]
        invented["quotes"] = [INVENTED]
        mixed["quotes"] = [good, INVENTED]
        kept["relation"][0]["quotes"] = [INVENTED]
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        wiki = self.export(workdir)
        shown = {f["id"]: f for f in wiki["facts"]}
        self.assertEqual(shown["F0001-001"]["quotes"], [])
        self.assertTrue(shown["F0001-001"]["unverified"])
        self.assertEqual(shown["F0001-002"]["quotes"], [good])
        self.assertNotIn("unverified", shown["F0001-002"])
        self.assertEqual(wiki["relations"][0]["quotes"], [])
        self.assertTrue(wiki["relations"][0]["unverified"])
        self.assertNotIn(INVENTED, json.dumps(wiki, ensure_ascii=False))

    def test_the_exported_page_asks_for_versioned_scripts_and_data_so_a_rebuild_is_not_served_from_cache(self):
        site = self.book.workdir / "site"
        html = (site / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'href="app\.css\?v=[0-9a-f]{10}"')
        self.assertRegex(html, r'src="app\.js\?v=[0-9a-f]{10}"')
        self.assertRegex(html, r'data-wiki="data/wiki\.json\?v=[0-9a-f]{10}"')

    def test_each_relation_carries_one_family_for_the_graph_filter(self):
        wiki = self.book.json("site/data/wiki.json")
        names = {e["id"]: e["name"] for e in wiki["entities"]}
        family = {(names[r["source"]], r["type"], names[r["target"]]): r["family"] for r in wiki["relations"]}
        self.assertEqual(family[("Ines Varro", "apprentice of", "Tomas Hale")], "teaching")
        self.assertEqual(family[("Bram Ostrow", "friend of", "Ines Varro")], "alliance")
        self.assertEqual(family[("Livia Hale", "daughter of", "Tomas Hale")], "kin")
        self.assertEqual(family[("Bram Ostrow", "enemy of", "Ines Varro")], "hostility")
        self.assertEqual(family[("Tomas Hale", "member of", "Lamplighters’ Guild")], "membership")
        self.assertEqual(family[("harbour lamp", "located in", "Corvel Quay")], "place")
        self.assertEqual(family[("Ines Varro", "holder of", "lamp room key")], "ownership")
        self.assertTrue(set(family.values()) <= {"kin", "romance", "faith", "teaching", "hostility", "investigation", "service", "membership",
                                                 "alliance", "place", "ownership", "kind", "other"})

    def test_relations_worded_for_allegiance_worship_teaching_work_rivalry_or_possession_get_a_family(self):
        expected = {
            "worships": "faith", "prays to": "faith", "high-ranking deacon of": "faith", "believes in": "faith",
            "mentor of": "teaching", "teaches mysticism lessons to": "teaching", "combat instructor of": "teaching",
            "learned a formula from": "teaching", "student of": "teaching",
            "boss of": "service", "gives orders to": "service", "customer of": "service", "maidservant of": "service",
            "landlord of": "service", "recruited by": "service",
            "hostile to": "hostility", "is at odds with": "hostility", "quarrels with": "hostility", "impersonates": "hostility",
            "believes his subordinate killed": "hostility", "rival in culture to": "hostility",
            "follower of": "alliance", "corresponds with": "alliance", "main supporter of": "alliance", "lives with": "alliance",
            "citizen of": "membership", "team of": "membership",
            "holds custody of": "ownership", "author of": "ownership", "uses": "ownership", "crafted": "ownership",
            "lived in": "place", "originated from": "place", "shops at": "place",
            "is a kind of": "kind", "is the same as": "kind", "precedes": "kind",
            "interested in": "other", "sat at": "other", "came from": "other", "related to": "other",
        }
        self.assertEqual({t: relation_family(t) for t in expected}, expected)


if __name__ == "__main__":
    unittest.main()
