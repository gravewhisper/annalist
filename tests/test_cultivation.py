import json
import re
import shutil
import subprocess
import sys
import unittest

from tests.test_build import LATER_REPLIES, MiniBuild, plan_rows, ran, ROOT, site_views

DATA = ROOT / "tests" / "data"
EPUB = DATA / "cultivation.epub"
NODE = shutil.which("node")

SPEC = {"shape": "shared", "step_type": "realm", "rank": "order", "direction": "ascending",
        "note": "Every cultivator climbs the same realms in order, each split into layers or stages."}

SEED = {"power_system": "Cultivators draw mist into the body and climb one shared ladder of realms.",
        "power_types": {"realm": "A named realm of cultivation that every cultivator climbs.",
                        "sect": "A school of cultivators."},
        "relation_example": "teaches", "extra_fields": {"cultivation_realm": "the realm and the layer or stage the character has reached"},
        "power_keywords": ["realm", "layer", "stage", "mist", "cultivat"],
        "timeline_kind": "linear", "timeline_note": "The story runs in order over one year in the valley.",
        "complete": False, "backend": {"name": "fake", "script": "script.json"}}

NINE_LAYERS = "It has nine layers, from the first layer to the ninth layer"
EARLY_MIDDLE_LATE = "Root Binding has an early stage, a middle stage and a late stage."


def stage(name, chapter, quote):
    return {"name": name, "chapter": chapter, "quote": quote}


LADDERS_REPLY = {"steps": [
    {"entry": "Root Binding", "rank": 2, "chapter": 2, "quote": "Root Binding is the second realm",
     "stages": [stage("Early Stage", 2, EARLY_MIDDLE_LATE), stage("Middle Stage", 2, EARLY_MIDDLE_LATE), stage("Late Stage", 2, EARLY_MIDDLE_LATE)]},
    {"entry": "Pearl Forming", "rank": 3, "chapter": 4, "quote": "Pearl Forming is the third realm.", "stages": []},
    {"entry": "Mist Gathering", "rank": 1, "chapter": 1, "quote": "Mist Gathering is the first realm",
     "stages": [stage("First Layer", 1, NINE_LAYERS), stage("Third Layer", 1, "Tamsin Vey has reached the third layer of Mist Gathering."),
                stage("Seventh Layer", 2, "Tamsin Vey has reached the seventh layer of Mist Gathering"),
                stage("Ninth Layer", 1, NINE_LAYERS), stage("Tenth Layer", 1, "It has ten layers, from the first to the tenth")]},
]}

RISE = [("Third Layer of Mist Gathering", 1, "Tamsin Vey has reached the third layer of Mist Gathering."),
        ("Seventh Layer of Mist Gathering", 2, "Tamsin Vey has reached the seventh layer of Mist Gathering"),
        ("Ninth Layer of Mist Gathering", 3, "Tamsin Vey has reached the ninth layer of Mist Gathering"),
        ("Early Stage of Root Binding", 4, "Tamsin Vey has broken through to the early stage of Root Binding")]

PROFILE = {"extra": {"cultivation_realm": [{"value": v, "chapter": c, "quotes": [q], "asserted_by": "Kovic Brannoch"} for v, c, q in RISE]}}


def cultivation_script():
    extractions = json.loads((DATA / "cultivation-extractions.json").read_text(encoding="utf-8"))
    replies = []
    for key, ext in extractions.items():
        ids = [f"F{i}" for i in range(1, len(ext["facts"]) + 1)] + [f"R{i}" for i in range(1, len(ext["relations"]) + 1)]
        replies += [{"purpose": "extract", "chapter": int(key), "reply": ext},
                    {"purpose": "support", "chapter": int(key), "reply": {"verdicts": [{"id": i, "verdict": "supported"} for i in ids]}}]
    replies += [{"purpose": "ladder-spec", "reply": {"ladder": SPEC}},
                {"purpose": "ladders", "reply": LADDERS_REPLY},
                {"purpose": "profile", "contains": 'the character "Tamsin Vey"', "reply": PROFILE},
                {"purpose": "profile-support", "contains": "Tamsin Vey:",
                 "reply": {"verdicts": [{"id": f"O{i}", "verdict": "supported"} for i in range(1, 9)]}}]
    replies += [{"purpose": p, "reply": r} for p, r in LATER_REPLIES.items() if p != "book"]
    return {"replies": replies}


class CultivationBuild(MiniBuild):
    def build(self, *extra, check=True):
        proc = subprocess.run([sys.executable, "-m", "annalist", "build", str(EPUB), str(self.workdir), "--yes", *extra],
                              cwd=self.code, env=self.env, capture_output=True, text=True, timeout=300)
        if check and proc.returncode:
            raise AssertionError(f"build exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc


def visible(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class SharedLadderBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = CultivationBuild(cultivation_script())
        (cls.book.workdir / "book.json").write_text(json.dumps(SEED, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cls.first = cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, *views):
        return site_views(self.book.workdir / "site" / "data" / "wiki.json", *views)

    def rungs(self, model):
        return [(r["rank"], [(self.name[s["id"]], [t["name"] for t in s["stages"]]) for s in r["steps"]]) for r in model["ladders"][0]["rungs"]]

    def holders(self, model):
        return {self.name[s["id"]]: [(self.name[h["holder"]], h["stage"] and h["stage"]["name"]) for h in s["holders"]]
                for r in model["ladders"][0]["rungs"] for s in r["steps"]}

    def test_the_ladder_spec_accepts_one_shared_ladder_without_a_group_type(self):
        calls = self.book.calls("ladder-spec")
        self.assertEqual([c["error"] for c in calls], [None])
        self.assertEqual(self.book.json("book.json")["ladder"], SPEC)
        self.assertEqual(self.wiki["book"]["ladder"], SPEC)

    def test_ladders_json_orders_the_realms_and_their_verified_sub_stages(self):
        ladders = self.book.json("ladders.json")
        self.assertEqual([(l["group"], l["chapter"]) for l in ladders], [(None, 1)])
        self.assertEqual([(s["entry"], s["rank"], s["chapter"], [t["name"] for t in s["stages"]]) for s in ladders[0]["steps"]], [
            ("Mist Gathering", 1, 1, ["First Layer", "Third Layer", "Seventh Layer", "Ninth Layer"]),
            ("Root Binding", 2, 2, ["Early Stage", "Middle Stage", "Late Stage"]),
            ("Pearl Forming", 3, 4, []),
        ])
        self.assertEqual(ladders[0]["steps"][0]["stages"][2], stage("Seventh Layer", 2, "Tamsin Vey has reached the seventh layer of Mist Gathering"))

    def test_wiki_json_carries_the_shared_ladder_by_id_with_stage_chapters(self):
        i = self.id
        self.assertEqual(self.wiki["ladders"], [{"group": None, "chapter": 1, "steps": [
            {"id": i["Mist Gathering"], "rank": 1, "chapter": 1,
             "stages": [{"name": "First Layer", "chapter": 1}, {"name": "Third Layer", "chapter": 1},
                        {"name": "Seventh Layer", "chapter": 2}, {"name": "Ninth Layer", "chapter": 1}]},
            {"id": i["Root Binding"], "rank": 2, "chapter": 2,
             "stages": [{"name": "Early Stage", "chapter": 2}, {"name": "Middle Stage", "chapter": 2}, {"name": "Late Stage", "chapter": 2}]},
            {"id": i["Pearl Forming"], "rank": 3, "chapter": 4, "stages": []}]}])

    def test_a_shared_ladder_adds_no_group_relations(self):
        self.assertEqual([r for r in self.wiki["relations"] if r["type"].startswith("realm ")], [])

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_ladder_page_lists_the_realms_in_order_with_the_sub_stages_known_so_far(self):
        out = self.site("graph:ladder@1", "graph:ladder@2", "graph:ladder@4")
        self.assertEqual(self.rungs(out["graph:ladder@1"]["model"]), [(1, [("Mist Gathering", ["First Layer", "Third Layer", "Ninth Layer"])])])
        self.assertEqual(self.rungs(out["graph:ladder@2"]["model"]), [
            (1, [("Mist Gathering", ["First Layer", "Third Layer", "Seventh Layer", "Ninth Layer"])]),
            (2, [("Root Binding", ["Early Stage", "Middle Stage", "Late Stage"])])])
        self.assertEqual([r["rank"] for r in out["graph:ladder@4"]["model"]["ladders"][0]["rungs"]], [1, 2, 3])
        page = visible(out["graph:ladder@4"]["html"])
        self.assertRegex(page, r"Realms 3 ranks known.*#1 Mist Gathering.*First Layer Third Layer Seventh Layer Ninth Layer.*#2 Root Binding.*Early Stage Middle Stage Late Stage.*#3 Pearl Forming")
        self.assertIn("One ladder of realms that everyone climbs", page)
        self.assertIn('data-go="graph:ladder"', out["graph:ladder@1"]["html"])

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_a_cultivator_climbs_realm_and_sub_stage_without_showing_a_later_advance(self):
        out = self.site("graph:ladder@1", "graph:ladder@2", "graph:ladder@3", "graph:ladder@4")
        self.assertEqual(self.holders(out["graph:ladder@1"]["model"]), {"Mist Gathering": [("Tamsin Vey", "Third Layer")]})
        self.assertEqual(self.holders(out["graph:ladder@2"]["model"]),
                         {"Mist Gathering": [("Tamsin Vey", "Seventh Layer")], "Root Binding": []})
        self.assertIn("rose from Third Layer (ch 1)", visible(out["graph:ladder@2"]["html"]))
        self.assertEqual(self.holders(out["graph:ladder@3"]["model"])["Mist Gathering"], [("Tamsin Vey", "Ninth Layer")])
        self.assertNotIn("Pearl Forming", visible(out["graph:ladder@3"]["html"]))
        at4 = self.holders(out["graph:ladder@4"]["model"])
        self.assertEqual(at4["Root Binding"], [("Tamsin Vey", "Early Stage")])
        self.assertEqual(at4["Mist Gathering"], [])
        self.assertIn("advanced from Mist Gathering (ch 1)", visible(out["graph:ladder@4"]["html"]))

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_infobox_shows_the_rank_as_of_the_chapter(self):
        tamsin = self.id["Tamsin Vey"]
        pages = self.site(f"{tamsin}@2", f"{tamsin}@4")
        box = {n: visible(re.search(r'<aside class="infobox">.*?</aside>', pages[f"{tamsin}@{n}"], re.S).group(0)) for n in (2, 4)}
        self.assertIn("Seventh Layer of Mist Gathering", box[2])
        self.assertNotIn("Root Binding", box[2])
        self.assertIn("Early Stage of Root Binding", box[4])

    def test_a_second_build_finds_the_ladder_current(self):
        second = self.book.build()
        self.assertEqual(ran(second.stdout), [])
        self.assertEqual(plan_rows(second.stdout)["ladders"], "done")


if __name__ == "__main__":
    unittest.main()
