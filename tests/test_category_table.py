import html
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import ROOT, site_views


def person(i, name, first, *, name_chapter=None, aliases=(), fields=None, present=()):
    return {"id": f"p{i:07d}", "name": name, "name_chapter": name_chapter or first, "type": "character", "first": first,
            "aliases": [{"name": a, "chapter": c} for a, c in aliases], "blurbs": [[first, f"{name} works the quay."]],
            "present": list(present), "profile": {"fields": fields or {}, "lists": {}}}


def thing(i, name, kind, first):
    return {"id": f"t{i:07d}", "name": name, "name_chapter": first, "type": kind, "first": first, "aliases": [],
            "blurbs": [[first, f"{name} of the quay."]]}


def table_wiki():
    seen = lambda *rows: [{"value": v, "chapter": c} for v, c in rows]
    entities = [
        person(1, "Ada Marsh", 1, present=(1, 2, 3), fields={
            "status": seen(("alive", 1), ("dead", 3)), "affiliation": seen(("Lamp Guild", 2)),
            "occupation": seen(("ferryman", 1), ("harbour master", 4))}),
        person(2, "Bo Fenwick", 1, name_chapter=3, aliases=[("The Stranger", 1)], fields={"affiliation": seen(("Tide Watch", 2))}),
        person(3, "Cara Dunn", 2, fields={"status": seen(("missing", 2)), "occupation": seen(("clerk", 2))}),
        person(4, "Dex Oro", 3),
        thing(5, "Lamp Guild", "organization", 1), thing(6, "Tide Watch", "organization", 2),
        thing(7, "Harbour", "place", 1), thing(8, "North Pier", "place", 2),
        thing(9, "Ember Way", "path", 1), thing(10, "Spark", "rung", 1), thing(11, "Flare", "rung", 3),
    ]
    ids = {e["name"]: e["id"] for e in entities}
    facts = [{"id": f"F{i}", "chapter": e["first"], "entity": e["id"], "claim": f"{e['name']} is on the quay.", "status": "stated",
              "by": "narrator", "quotes": []} for i, e in enumerate(entities, 1)]
    facts.append({"id": "F99", "chapter": 3, "entity": ids["Ada Marsh"], "claim": "Ada Marsh rows out at dusk.", "status": "stated",
                  "by": "narrator", "quotes": []})
    tie = lambda s, t, label, family, c: {"chapter": c, "source": ids[s], "target": ids[t], "type": label, "family": family,
                                          "status": "stated", "by": "narrator", "quotes": []}
    relations = [tie("Ada Marsh", "Lamp Guild", "member of", "membership", 2), tie("North Pier", "Harbour", "located in", "place", 2),
                 tie("Ada Marsh", "North Pier", "lives in", "place", 3)]
    ladders = [{"group": ids["Ember Way"], "steps": [{"id": ids["Spark"], "rank": 9, "chapter": 1}, {"id": ids["Flare"], "rank": 8, "chapter": 3}]}]
    wiki = {"book": {"title": "Quay", "max": 4, "public_domain": False, "theme": {}, "power_types": ["path", "rung"], "parents": {},
                     "ladder": {"group_type": "path", "step_type": "rung", "rank": "number", "direction": "descending"}},
            "chapters": [{"n": n, "title": f"Chapter {n}", "synopsis": ""} for n in (1, 2, 3, 4)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": facts, "relations": relations, "questions": [], "ladders": ladders, "volumes": []}
    return wiki, ids


def text(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def table(markup):
    body = re.search(r"<tbody>(.*?)</tbody>", markup, re.S)
    return [[text(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1), re.S)] if body else []


def rows(markup):
    return [" ".join(cells) for cells in table(markup)]


def names(markup):
    return [cells[0] for cells in table(markup)]


def headers(markup):
    head = re.search(r"<thead>(.*?)</thead>", markup, re.S)
    spoken = re.sub(r'<span [^>]*aria-hidden="true"[^>]*>.*?</span>', "", head.group(1)) if head else ""
    return [text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", spoken, re.S)]


class CategoryTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wiki, cls.id = table_wiki()
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.path = Path(cls.tmp.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def site(self, *views):
        return site_views(self.path, *views)

    def page(self, view):
        return self.site(view)[view]["html"]

    def test_the_characters_table_shows_each_value_only_from_its_chapter(self):
        out = self.site(*(f"route:cat:character@{n}" for n in (1, 2, 3, 4)))
        table = {n: {r.split(" ")[0]: r for r in rows(out[f"route:cat:character@{n}"]["html"])} for n in (1, 2, 3, 4)}
        self.assertEqual(sorted(table[1]), ["Ada", "The"])
        self.assertNotIn("Lamp Guild", table[1]["Ada"])
        self.assertIn("Alive", table[1]["Ada"])
        self.assertIn("Ferryman", table[1]["Ada"])
        self.assertIn("Lamp Guild", table[2]["Ada"])
        self.assertIn("Alive", table[2]["Ada"])
        self.assertIn("Dead", table[3]["Ada"])
        self.assertNotIn("Harbour master", table[3]["Ada"])
        self.assertIn("Harbour master", table[4]["Ada"])
        self.assertIn("Dex", table[3])
        self.assertNotIn("Dex", table[2])

    def test_the_characters_table_has_the_columns_a_reader_sorts_by(self):
        cols = headers(self.page("route:cat:character@4"))
        for col in ("Name", "Status", "Affiliation", "Occupation", "First seen", "Last seen", "Chapters present", "Facts"):
            self.assertIn(col, cols)

    def test_a_name_shows_as_known_at_the_chapter_and_sorts_by_that_name(self):
        early, late = self.page("route:cat:character@2"), self.page("route:cat:character@3")
        self.assertNotIn("Bo Fenwick", early)
        self.assertEqual(names(early), ["Ada Marsh", "Cara Dunn", "The Stranger"])
        self.assertEqual(names(late), ["Ada Marsh", "Bo Fenwick The Stranger", "Cara Dunn", "Dex Oro"])

    def test_last_seen_and_chapters_present_count_only_chapters_read(self):
        ada = lambda n: rows(self.page(f"route:cat:character@{n}"))[0]
        self.assertRegex(ada(2), r"Ch 1 Ch 2 2 1$")
        self.assertRegex(ada(4), r"Ch 1 Ch 3 3 2$")

    def test_sorting_orders_rows_by_the_column_and_keeps_empty_cells_last(self):
        order = lambda q: [r.split(" ")[0] for r in rows(self.page(f"route:cat:character@2?sort={q}"))]
        self.assertEqual(order("status"), ["Ada", "Cara", "The"])
        self.assertEqual(order("-status"), ["Cara", "Ada", "The"])
        self.assertEqual(order("affiliation"), ["Ada", "The", "Cara"])
        self.assertEqual(order("-name"), ["The", "Cara", "Ada"])
        self.assertEqual(order("first"), ["Ada", "The", "Cara"])
        self.assertEqual(order("nonsense"), ["Ada", "Cara", "The"])

    def test_a_header_click_sorts_marks_the_column_and_stays_in_the_url_while_the_slider_moves(self):
        out = self.site("route:cat:character@2", "click:sort=status@2", "route:cat:character@3", "route:home@3", "route:cat:character@3")
        clicked, moved, back = out["click:sort=status@2"], out["route:cat:character@3"], out["route:cat:character@3"]
        self.assertIn("sort=status", clicked["url"])
        self.assertRegex(clicked["html"], r'<th[^>]*aria-sort="ascending"[^>]*><a [^>]*data-sort="-status"')
        self.assertNotIn("sort=", back["url"])
        moved = self.site("route:cat:character@2", "click:sort=status@2", "route:cat:character@3")["route:cat:character@3"]
        self.assertIn("sort=status", moved["url"])
        self.assertIn("n=3", moved["url"])
        self.assertEqual([r.split(" ")[0] for r in rows(moved["html"])], ["Ada", "Cara", "Bo", "Dex"])

    def test_every_sort_control_is_a_link_with_an_href(self):
        head = re.search(r"<thead>(.*?)</thead>", self.page("route:cat:character@4"), re.S).group(1)
        cells = re.findall(r"<th[^>]*>(.*?)</th>", head, re.S)
        self.assertTrue(cells)
        for cell in cells:
            self.assertRegex(cell, r'^<a [^>]*href="#[^"]*sort=[^"]*"')

    def test_other_categories_get_their_own_columns(self):
        out = self.site("route:cat:organization@2", "route:cat:place@3", "route:cat:rung@2", "route:cat:rung@3", "route:cat:path@3")
        orgs, places = out["route:cat:organization@2"]["html"], out["route:cat:place@3"]["html"]
        self.assertIn("Members", headers(orgs))
        self.assertEqual(table(orgs)[0], ["Lamp Guild", "1", "Ch 1", "Ch 2", "1"])
        self.assertIn("Located in", headers(places))
        self.assertIn(["North Pier", "Harbour", "1", "Ch 2", "Ch 3", "1"], table(places))
        self.assertEqual(table(out["route:cat:rung@2"]["html"]), [["Spark", "Ember Way", "9", "Ch 1", "Ch 1", "1"]])
        self.assertEqual(len(rows(out["route:cat:rung@3"]["html"])), 2)
        self.assertEqual(table(out["route:cat:path@3"]["html"]), [["Ember Way", "2", "Ch 1", "Ch 1", "1"]])

    def test_the_list_view_keeps_each_entry_s_summary(self):
        page = self.page("route:cat:character@2?tab=list")
        self.assertNotIn("<table", page)
        self.assertIn("Ada Marsh works the quay.", text(page))


if __name__ == "__main__":
    unittest.main()
