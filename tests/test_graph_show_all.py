import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs

from tests.test_build import ROOT

NODE = shutil.which("node")


def wiki():
    names = ["Star Main", "Second Hub", "Truename Vale"] + [f"Person {i:02d}" for i in range(1, 51)]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, n in enumerate(names, 1)]
    entities.append({"id": "000000a0", "name": "Harbour Town", "name_chapter": 1, "type": "place", "first": 1, "aliases": [], "blurbs": []})
    ids = {e["name"]: e["id"] for e in entities}
    veiled = next(e for e in entities if e["name"] == "Truename Vale")
    veiled.update(name_chapter=3, aliases=[{"name": "The Stranger", "chapter": 1}])
    rel = lambda c, a, b, fam="alliance": {"chapter": c, "source": ids[a], "target": ids[b], "type": "friend of", "family": fam, "status": "stated", "quotes": []}
    relations = [rel(1, "Truename Vale", f"Person {i:02d}") for i in (1, 2, 3)]
    relations += [rel(2, "Second Hub", f"Person {i:02d}") for i in range(1, 44)]
    relations += [rel(2, "Second Hub", f"Person {i:02d}", "hostility") for i in (44, 45)]
    relations += [rel(2, "Second Hub", "Harbour Town", "place")]
    relations += [rel(3, "Star Main", f"Person {i:02d}") for i in range(1, 51)]
    return {"book": {"title": "Hubs", "max": 3, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 4)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class ShowAllAndBackLinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.second = cls.id["Second Hub"]
        cls.star = cls.id["Star Main"]

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def site(self, *views):
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(self.path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def drawn(self, html):
        ids = {e["id"]: e["name"] for e in self.wiki["entities"]}
        return {ids[i] for i in re.findall(r'data-gn="([^"]+)"', html)}

    def back_links(self, html):
        return re.findall(r'<a class="gback"[^>]*href="#([^"]*)"[^>]*>(.*?)</a>', html)

    def show_all_on_second(self):
        route, click = f"route:graph:{self.second}@3", "click:gall=1@3"
        return self.site(route, click)[click]

    def test_show_all_reveals_every_connected_entry_for_a_focus_off_the_default_and_then_goes_away(self):
        route = f"route:graph:{self.second}@3"
        before = self.site(route)[route]
        self.assertIn("data-gall", before["html"])
        self.assertIn("gbubble", before["html"])
        after = self.show_all_on_second()
        expected = {"Second Hub"} | {f"Person {i:02d}" for i in range(1, 46)}
        self.assertEqual(self.drawn(after["html"]), expected)
        self.assertEqual(after["p"], f"graph:{self.second}")
        self.assertNotIn("gbubble", after["html"])
        self.assertNotIn("data-gall", after["html"])
        self.assertNotIn("data-gmore", after["html"])
        self.assertIn("45 of 45 linked to", after["html"])

    def test_show_all_is_absent_when_a_focus_has_nothing_hidden(self):
        route = f"route:graph:{self.id['Person 50']}@3"
        self.assertNotIn("data-gall", self.site(route)[route]["html"])

    def test_show_all_keeps_to_the_show_and_lines_filters(self):
        filters, route, click = f"graph:{self.second}@3?hideFam=hostility&limit=1", f"route:graph:{self.second}@3", "click:gall=1@3"
        html = self.site(filters, route, click)[click]["html"]
        self.assertEqual(self.drawn(html), {"Second Hub"} | {f"Person {i:02d}" for i in range(1, 44)})
        self.assertNotIn("Harbour Town", self.drawn(html))

    def test_show_all_draws_the_same_page_on_every_visit(self):
        self.assertEqual(self.show_all_on_second()["html"], self.show_all_on_second()["html"])

    def test_show_all_ends_when_the_reader_moves_to_another_centre_like_show_more(self):
        other = f"route:graph:{self.id['Person 01']}@3"
        again = f"route:graph:{self.second}@3"
        steps = self.site("route:home@3", again, "click:gall=1@3", other, f"click:gc={self.second}@3")
        html = steps[f"click:gc={self.second}@3"]["html"]
        self.assertIn("data-gall", html)
        self.assertEqual(len(self.drawn(html)), 21)

    def test_show_all_survives_a_chapter_step_like_show_more(self):
        route, click, step = f"route:graph:{self.second}@3", "click:gall=1@3", f"route:graph:{self.second}@2"
        html = self.site(route, click, step)[step]["html"]
        self.assertEqual(self.drawn(html), {"Second Hub"} | {f"Person {i:02d}" for i in range(1, 46)})
        self.assertNotIn("data-gall", html)

    def test_back_link_from_a_remembered_centre_also_ends_show_all(self):
        remembered, plain, reveal, back = f"route:graph:{self.second}@3", "route:graph@3", "click:gall=1@3", "click:gback=1@3"
        html = self.site(remembered, plain, reveal, back)[back]["html"]
        self.assertEqual(len(self.drawn(html)), 21)
        self.assertIn("data-gall", html)

    def test_back_link_appears_off_the_default_and_goes_to_the_plain_characters_route(self):
        route = f"route:graph:{self.second}@3"
        links = self.back_links(self.site(route)[route]["html"])
        self.assertEqual(len(links), 1)
        href, text = links[0]
        self.assertEqual(parse_qs(href.replace("&amp;", "&"))["p"], ["graph"])
        self.assertIn("Back to Star Main", text)

    def test_back_link_is_hidden_on_the_default(self):
        for route in ("route:graph@3", f"route:graph:{self.star}@3"):
            self.assertEqual(self.back_links(self.site(route)[route]["html"]), [], route)

    def test_back_link_returns_a_remembered_centre_to_the_default_on_the_plain_route(self):
        remembered, plain, click = f"route:graph:{self.second}@3", "route:graph@3", "click:gback=1@3"
        steps = self.site(remembered, plain, click)
        self.assertEqual(len(self.back_links(steps[plain]["html"])), 1)
        self.assertEqual(steps[click]["p"], "graph")
        self.assertIn("Star Main", self.drawn(steps[click]["html"]))
        self.assertEqual(self.back_links(steps[click]["html"]), [])

    def test_back_link_never_names_anyone_before_their_chapter(self):
        route = f"route:graph:{self.id['Person 01']}@1"
        html = self.site(route)[route]["html"]
        links = self.back_links(html)
        self.assertEqual(len(links), 1)
        self.assertIn("Back to The Stranger", links[0][1])
        for later in ("Truename Vale", "Star Main", "Second Hub"):
            self.assertNotIn(later, html)
        late = self.site(f"route:graph:{self.second}@2", f"route:graph:{self.id['Person 01']}@2")
        self.assertNotIn("Star Main", late[f"route:graph:{self.id['Person 01']}@2"]["html"])
