import copy
import json
import shutil
import subprocess
import unittest

from tests.test_build import MiniBuild, ROOT
from tests.test_eval import statuses_script

NODE = shutil.which("node")


def relation(chapter, source, target, label, status="stated"):
    return {"chapter": chapter, "source": source, "target": target, "type": label, "family": "other", "status": status, "by": "narrator", "quotes": [f"Quote {chapter} {label}."]}


@unittest.skipIf(NODE is None, "node is not installed")
class GraphToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(statuses_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        people = [e["id"] for e in cls.wiki["entities"] if e["type"] == "character" and not e.get("merged")]
        cls.a, cls.b, cls.c = people[:3]

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, view, extra):
        wiki = copy.deepcopy(self.wiki)
        wiki["relations"] += extra
        path = self.book.root / "tools-wiki.json"
        path.write_text(json.dumps(wiki), encoding="utf-8")
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), view],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)[view]

    def test_disguises_list_a_face_with_its_chapters(self):
        m = self.site("graph:masks@3", [relation(1, self.a, self.b, "impersonates"), relation(3, self.a, self.b, "disguised as")])["model"]
        self.assertEqual([(w["id"], [(f["id"], f["first"], f["last"]) for f in w["faces"]]) for w in m["wearers"]], [(self.a, [(self.b, 1, 3)])])

    def test_a_disguise_stays_hidden_until_its_chapter(self):
        m = self.site("graph:masks@2", [relation(3, self.a, self.b, "impersonates")])["model"]
        self.assertEqual(m["wearers"], [])

    def test_a_suspected_disguise_is_not_listed(self):
        m = self.site("graph:masks@3", [relation(1, self.a, self.b, "impersonates", "belief")])["model"]
        self.assertEqual(m["wearers"], [])

    def test_a_direct_tie_is_not_repeated_as_a_chain(self):
        html = self.site(f"graph:path:{self.a}~{self.b}@2", [relation(1, self.a, self.b, "fears")])["html"]
        self.assertEqual(html.count("Quote 1 fears."), 1)

    def test_tie_story_lists_each_moment_up_to_the_chapter(self):
        html = self.site(f"graph:path:{self.a}~{self.b}@2", [relation(1, self.a, self.b, "fears"), relation(2, self.b, self.a, "rescues"), relation(3, self.a, self.b, "betrays")])["html"]
        self.assertIn("How this tie changed", html)
        self.assertLess(html.index("Quote 1 fears."), html.index("Quote 2 rescues."))
        self.assertNotIn("Quote 3 betrays.", html)


if __name__ == "__main__":
    unittest.main()
