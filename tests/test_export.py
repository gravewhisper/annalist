import json
import shutil
import subprocess
import sys
import unittest

from tests.test_build import MiniBuild, ROOT
from tests.test_eval import statuses_script
from tests.test_quotes import INVENTED
from annalist.families import relation_family


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
        facts = read_jsonl(workdir / "facts.jsonl")
        invented, mixed = facts[0], facts[1]
        good = mixed["quotes"][0]
        invented["quotes"] = [INVENTED]
        mixed["quotes"] = [good, INVENTED]
        write_jsonl(workdir / "facts.jsonl", facts)
        relations = read_jsonl(workdir / "relations.jsonl")
        relations[0]["quotes"] = [INVENTED]
        write_jsonl(workdir / "relations.jsonl", relations)
        wiki = self.export(workdir)
        shown = {f["id"]: f for f in wiki["facts"]}
        self.assertEqual(shown[invented["id"]]["quotes"], [])
        self.assertTrue(shown[invented["id"]]["unverified"])
        self.assertEqual(shown[mixed["id"]]["quotes"], [good])
        self.assertNotIn("unverified", shown[mixed["id"]])
        self.assertEqual(wiki["relations"][0]["quotes"], [])
        self.assertTrue(wiki["relations"][0]["unverified"])
        self.assertNotIn(INVENTED, json.dumps(wiki, ensure_ascii=False))

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
