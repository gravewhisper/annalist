import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_build import MiniBuild, ROOT, site_views
from tests.test_eval import statuses_script
from tests.test_graph import NODE

LADDER = {"group_type": "path", "step_type": "rank", "rank": "number", "direction": "descending", "note": ""}


def factions_wiki(ladder=LADDER):
    names = [("Ada", "character", 1), ("Bram", "character", 1), ("Cora", "character", 1), ("Dax", "character", 4),
             ("Night Watch", "organization", 1), ("Grey Guild", "organization", 1), ("Harbour League", "organization", 2),
             ("Ember Path", "path", 1), ("Spark", "rank", 1), ("Flame", "rank", 1), ("Inferno", "rank", 2), ("Fire Palm", "skill", 2)]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": t, "first": c, "aliases": [], "blurbs": [[c, f"{n} is here."]]}
                for i, (n, t, c) in enumerate(names, 1)]
    ids = {e["name"]: e["id"] for e in entities}
    by_name = {e["name"]: e for e in entities}
    by_name["Flame"]["aliases"] = [{"name": "Blaze", "chapter": 3}, {"name": "Rank 8", "chapter": 3}]
    by_name["Spark"]["blurbs"] = [[1, "The first rank of the Ember Path."]]
    by_name["Ada"]["profile"] = {"fields": {"rank_and_path": [{"chapter": 2, "value": "Spark (Rank 9), Ember Path", "quotes": []}]}, "lists": {}, "spoke": [], "personality": []}
    by_name["Cora"]["profile"] = {"fields": {"affiliation": [{"chapter": 2, "value": "Grey Guild", "quotes": []}]}, "lists": {}, "spoke": [], "personality": []}
    rel = lambda c, a, t, b, fam, status="stated": {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": status,
                                                    "by": "narrator", "quotes": []}
    relations = [rel(1, "Ada", "member of", "Night Watch", "membership"), rel(3, "Ada", "member of", "Grey Guild", "membership"),
                 rel(1, "Bram", "leads", "Night Watch", "membership"), rel(5, "Dax", "member of", "Night Watch", "membership"),
                 rel(2, "Night Watch", "hostile to", "Grey Guild", "hostility"), rel(3, "Harbour League", "part of", "Grey Guild", "membership"),
                 rel(4, "Ada", "advanced to", "Flame", "kind"), rel(5, "Bram", "holds", "Inferno", "ownership"), rel(3, "Cora", "holds", "Inferno", "ownership"),
                 rel(3, "Cora", "attacks", "Spark", "hostility"), rel(2, "Fire Palm", "skill of", "Spark", "kind")]
    ladders = [{"group": ids["Ember Path"], "chapter": 1, "steps": [{"id": ids["Spark"], "rank": 9, "chapter": 1},
                                                                     {"id": ids["Flame"], "rank": 8, "chapter": 3},
                                                                     {"id": ids["Inferno"], "rank": 6, "chapter": 5}]}] if ladder else []
    return {"book": {"title": "Factions", "max": 6, "public_domain": False, "theme": {}, "power_types": ["path", "rank", "skill"], "ladder": ladder},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": ladders, "volumes": []}


def visible(markup):
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


@unittest.skipIf(NODE is None, "node is not installed")
class FactionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = factions_wiki()
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def site(self, *views, wiki=None):
        path = Path(self.dir.name) / "wiki.json"
        path.write_text(json.dumps(wiki or self.wiki), encoding="utf-8")
        return site_views(path, *views)

    def view(self, view, wiki=None):
        return self.site(view, wiki=wiki)[view]

    def members(self, model):
        return {self.name[g["id"]]: [self.name[m["id"]] for m in g["members"]] for g in model["groups"]}

    def rungs(self, model):
        return [(r["rank"], [self.name[s["id"]] for s in r["steps"]]) for r in model["ladders"][0]["rungs"]]

    def holders(self, model):
        return {self.name[s["id"]]: [self.name[h["holder"]] for h in s["holders"]] for r in model["ladders"][0]["rungs"] for s in r["steps"]}

    def test_an_entry_of_a_book_type_of_organization_is_a_faction(self):
        wiki = json.loads(json.dumps(self.wiki))
        wiki["book"].update(power_types=wiki["book"]["power_types"] + ["watch company"], parents={"watch company": "organization"})
        next(e for e in wiki["entities"] if e["name"] == "Night Watch")["type"] = "watch company"
        self.assertEqual(self.members(self.view("graph:factions@5", wiki=wiki)["model"])["Night Watch"], ["Bram", "Ada", "Dax"])

    def test_a_group_lists_only_the_members_known_by_the_chapter(self):

        out = self.site("graph:factions@4", "graph:factions@5")
        self.assertEqual(self.members(out["graph:factions@4"]["model"])["Night Watch"], ["Bram", "Ada"])
        self.assertNotIn("Dax", visible(out["graph:factions@4"]["html"]))
        self.assertEqual(self.members(out["graph:factions@5"]["model"])["Night Watch"], ["Bram", "Ada", "Dax"])

    def test_a_leader_comes_first_with_the_role_the_book_gives(self):
        nw = next(g for g in self.view("graph:factions@4")["model"]["groups"] if g["id"] == self.id["Night Watch"])
        self.assertEqual([(self.name[m["id"]], m["roles"], m["leader"]) for m in nw["members"]], [("Bram", ["leads"], True), ("Ada", ["member of"], False)])

    def test_a_person_in_two_groups_appears_in_each_and_links_to_the_other(self):
        out = self.site("graph:factions@2", "graph:factions@3")
        self.assertEqual({g: "Ada" in ms for g, ms in self.members(out["graph:factions@2"]["model"]).items()}, {"Night Watch": True, "Grey Guild": False})
        groups = {self.name[g["id"]]: g for g in out["graph:factions@3"]["model"]["groups"]}
        ada = {name: next(m for m in g["members"] if m["id"] == self.id["Ada"]) for name, g in groups.items()}
        self.assertEqual({name: [self.name[o] for o in m["also"]] for name, m in ada.items()}, {"Night Watch": ["Grey Guild"], "Grey Guild": ["Night Watch"]})
        self.assertIn(f'data-go="graph:factions:{self.id["Grey Guild"]}"', out["graph:factions@3"]["html"])

    def test_an_affiliation_field_makes_a_member_from_its_chapter(self):
        out = self.site("graph:factions@1", "graph:factions@2")
        self.assertNotIn("Grey Guild", self.members(out["graph:factions@1"]["model"]))
        self.assertEqual(self.members(out["graph:factions@2"]["model"])["Grey Guild"], ["Cora"])
        self.assertIn("affiliated", visible(out["graph:factions@2"]["html"]))

    def test_ties_between_groups_show_from_their_chapter_with_their_colour(self):
        out = self.site("graph:factions@1", "graph:factions@3")
        self.assertEqual(out["graph:factions@1"]["model"]["ties"], [])
        ties = [(self.name[t["a"]], t["label"], self.name[t["b"]], t["group"]) for t in out["graph:factions@3"]["model"]["ties"]]
        self.assertEqual(ties, [("Night Watch", "hostile to", "Grey Guild", "conflict"), ("Harbour League", "part of", "Grey Guild", "belong")])
        self.assertIn("var(--r-conflict)", out["graph:factions@3"]["html"])

    def test_selecting_a_group_brings_it_first_and_keeps_only_its_ties(self):
        guild = self.id["Night Watch"]
        out = self.view(f"graph:factions:{guild}@3")
        self.assertEqual(out["model"]["focus"], guild)
        self.assertEqual(re.findall(r'<section class="fcard( on)?"', out["html"])[0], " on")
        self.assertNotIn("part of", visible(out["html"]))

    def test_steps_run_from_weakest_to_strongest_and_hide_until_the_book_places_them(self):
        out = self.site("graph:ladder@2", "graph:ladder@4", "graph:ladder@5")
        self.assertEqual(self.rungs(out["graph:ladder@2"]["model"]), [(9, ["Spark"])])
        self.assertEqual(self.rungs(out["graph:ladder@4"]["model"]), [(9, ["Spark"]), (8, ["Flame"])])
        self.assertNotIn("Inferno", visible(out["graph:ladder@4"]["html"]))
        self.assertEqual(self.rungs(out["graph:ladder@5"]["model"]), [(9, ["Spark"]), (8, ["Flame"]), (6, ["Inferno"])])
        self.assertIn("One rank not yet known", visible(out["graph:ladder@5"]["html"]))
        rising = self.view("graph:ladder@5", wiki=factions_wiki({**LADDER, "direction": "ascending"}))
        self.assertEqual([r for r, _ in self.rungs(rising["model"])], [6, 8, 9])

    def test_a_holder_moves_up_the_ladder_as_the_chapters_go_on(self):
        out = self.site("graph:ladder@1", "graph:ladder@3", "graph:ladder@4", "graph:ladder@5")
        self.assertEqual(self.holders(out["graph:ladder@1"]["model"]), {"Spark": []})
        self.assertEqual(self.holders(out["graph:ladder@3"]["model"]), {"Spark": ["Ada"], "Flame": []})
        self.assertEqual(self.holders(out["graph:ladder@4"]["model"]), {"Spark": [], "Flame": ["Ada"]})
        flame = out["graph:ladder@4"]["model"]["ladders"][0]["rungs"][1]["steps"][0]["holders"][0]
        self.assertEqual(flame["since"], 4)
        self.assertIn("advanced from Spark (ch 2)", visible(out["graph:ladder@4"]["html"]))
        self.assertNotIn("earlier Spark", visible(out["graph:ladder@4"]["html"]))
        self.assertEqual(self.holders(out["graph:ladder@5"]["model"])["Inferno"], ["Cora", "Bram"])

    def rows(self, html, step):
        block = next(b for b in re.findall(r'<div class="lstep">.*?(?=<div class="lstep">|</li><li class="lrung|</li><li class="lgap|</ol>)', html, re.S) if f">{step}</a>" in b.split('class="lholders"')[0])
        return re.findall(r'<li( class="lpast")?>(.*?)</li>', block.split('class="lholders"')[1], re.S) if 'class="lholders"' in block else []

    def test_an_advanced_holder_stays_listed_fainter_on_the_step_they_passed(self):
        html = self.view("graph:ladder@4")["html"]
        self.assertEqual([(cls, visible(row)) for cls, row in self.rows(html, "Spark")], [(' class="lpast"', "Ada now Flame, ch 4")])
        self.assertEqual([(cls, visible(row)) for cls, row in self.rows(html, "Flame")], [("", "Ada since ch 4 new advanced from Spark (ch 2)")])

    def test_before_the_advance_the_holder_sits_on_the_lower_step_with_no_word_of_the_later_one(self):
        html = self.view("graph:ladder@3")["html"]
        self.assertEqual([(cls, visible(row)) for cls, row in self.rows(html, "Spark")], [("", "Ada since ch 2")])
        for hidden in ("advanced from", "now Flame", "lpast"):
            self.assertNotIn(hidden, html)

    def test_counts_name_each_holder_once_and_a_passed_step_is_not_new(self):
        at4, at5 = (self.view(f"graph:ladder@{n}")["html"] for n in (4, 5))
        self.assertIn("1 holder", visible(at4))
        self.assertNotIn("2 holders", visible(at4))
        self.assertIn("3 holders", visible(at5))
        self.assertNotIn("new", self.rows(at4, "Spark")[0][1])

    def with_relations(self, *extra):
        wiki = factions_wiki()
        names = [("Tide Path", "path"), ("Drop", "rank")]
        entities = [{"id": f"{0x90 + i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": []} for i, (n, t) in enumerate(names)]
        wiki["entities"] += entities
        ids = {e["name"]: e["id"] for e in wiki["entities"]}
        wiki["ladders"].append({"group": ids["Tide Path"], "chapter": 1, "steps": [{"id": ids["Drop"], "rank": 9, "chapter": 1}]})
        for c, a, b in extra:
            wiki["relations"].append({"chapter": c, "source": ids[a], "target": ids[b], "type": "holds", "family": "ownership", "status": "stated", "by": "narrator", "quotes": []})
        return wiki

    def test_nothing_carries_across_pathways(self):
        html = self.view("graph:ladder@5", wiki=self.with_relations((5, "Ada", "Drop")))["html"]
        self.assertEqual([visible(row) for _, row in self.rows(html, "Drop")], ["Ada since ch 5 new"])
        for step in ("Spark", "Flame"):
            self.assertEqual([visible(row) for _, row in self.rows(html, step)], [], step)
        self.assertNotIn("advanced from", html)

    def test_a_step_with_no_evidence_for_that_holder_is_not_inferred(self):
        wiki = self.with_relations((2, "Bram", "Spark"))
        html = self.view("graph:ladder@5", wiki=wiki)["html"]
        self.assertIn("Bram now Inferno, ch 5", [visible(row) for _, row in self.rows(html, "Spark")])
        self.assertFalse(any("Bram" in visible(row) for _, row in self.rows(html, "Flame")))

    def test_a_later_step_lower_on_the_ladder_is_not_an_advance(self):
        html = self.view("graph:ladder@5", wiki=self.with_relations((5, "Ada", "Spark")))["html"]
        self.assertEqual([visible(row) for _, row in self.rows(html, "Spark")], ["Ada since ch 5 new earlier Flame (ch 4)"])
        self.assertEqual([visible(row) for _, row in self.rows(html, "Flame")], [])

    def test_a_holder_of_a_step_the_book_has_not_placed_yet_stays_hidden(self):
        out = self.site("graph:ladder@4", "graph:ladder@5")
        self.assertNotIn("Cora", visible(out["graph:ladder@4"]["html"]))
        cora = next(h for h in out["graph:ladder@5"]["model"]["ladders"][0]["rungs"][2]["steps"][0]["holders"] if h["holder"] == self.id["Cora"])
        self.assertEqual(cora["since"], 3)

    def test_a_step_shows_its_other_names_and_what_is_known_of_it_by_the_chapter(self):
        out = self.site("graph:ladder@1", "graph:ladder@3")
        early, later = visible(out["graph:ladder@1"]["html"]), visible(out["graph:ladder@3"]["html"])
        self.assertIn("The first rank of the Ember Path.", early)
        self.assertNotIn("Fire Palm", early)
        self.assertIn("Skills: Fire Palm", later)
        self.assertIn("Flame also Blaze Ch 3", later)

    def test_the_power_ladder_tab_shows_only_when_the_book_declares_a_ladder(self):
        self.assertIn('data-go="graph:ladder"', self.view("graph:factions@3")["html"])
        plain = factions_wiki(None)
        self.assertNotIn('data-go="graph:ladder"', self.view("graph:factions@3", wiki=plain)["html"])
        self.assertEqual(self.view("graph:ladder@3", wiki=plain)["model"]["ladders"], [])

    def with_status(self, **deaths):
        wiki = json.loads(json.dumps(self.wiki))
        for e in wiki["entities"]:
            if e["name"] in deaths:
                e.setdefault("profile", {"fields": {}, "lists": {}, "spoke": [], "personality": []})
                e["profile"]["fields"]["status"] = [{"chapter": deaths[e["name"]], "value": "dead", "quotes": []}]
        return wiki

    def test_a_member_or_holder_is_marked_dead_from_the_chapter_of_their_death_only(self):
        wiki = self.with_status(Bram=4, Cora=6)
        path = Path(self.dir.name) / "dead.json"
        path.write_text(json.dumps(wiki), encoding="utf-8")
        out = site_views(path, "graph:factions@3", "graph:factions@4", "graph:ladder@5", "graph:ladder@6")
        self.assertNotIn("Died ch", out["graph:factions@3"]["html"])
        self.assertIn(f'<span class="dead" title="Died ch 4"><a class="ent" data-ent="{self.id["Bram"]}"', out["graph:factions@4"]["html"])
        self.assertNotIn("Died ch 6", out["graph:ladder@5"]["html"])
        self.assertIn(f'<span class="dead" title="Died ch 6"><a class="ent" data-ent="{self.id["Cora"]}"', out["graph:ladder@6"]["html"])

    def test_a_member_tie_or_step_first_known_in_the_chapter_carries_a_new_tag(self):
        out = self.site("graph:factions@3", "graph:factions@5", "graph:factions@6", "graph:ladder@3", "graph:ladder@4")
        dax = re.search(rf'<li>[^\n]*?data-ent="{self.id["Dax"]}".*?</li>', out["graph:factions@5"]["html"]).group(0)
        self.assertIn('class="newtag"', dax)
        self.assertNotIn('class="newtag"', out["graph:factions@6"]["html"])
        self.assertNotIn("new this chapter", out["graph:factions@6"]["html"])
        self.assertIn("1 new this chapter: 1 member", visible(out["graph:factions@5"]["html"]))
        self.assertIn("part of Grey Guild ch 3 new", visible(out["graph:factions@3"]["html"]))
        self.assertIn("Flame also Blaze Ch 3 new", visible(out["graph:ladder@3"]["html"]))
        self.assertIn("Flame also Blaze Ch 3", visible(out["graph:ladder@4"]["html"]))
        self.assertNotIn("Blaze Ch 3 new", visible(out["graph:ladder@4"]["html"]))

    def test_a_tie_read_from_both_ends_shows_once_with_its_latest_wording_and_first_chapter(self):
        wiki = json.loads(json.dumps(self.wiki))
        rel = lambda c, a, t, b: {"chapter": c, "source": self.id[a], "target": self.id[b], "type": t, "family": "hostility", "status": "stated", "by": "narrator", "quotes": []}
        wiki["relations"] += [rel(4, "Grey Guild", "destroyed by", "Night Watch"), rel(5, "Night Watch", "destroyed", "Grey Guild")]
        ties = [(self.name[t["a"]], t["label"], self.name[t["b"]], t["chapter"]) for t in self.view("graph:factions@5", wiki=wiki)["model"]["ties"]]
        self.assertEqual(ties, [("Night Watch", "destroyed", "Grey Guild", 2), ("Harbour League", "part of", "Grey Guild", 3)])

    def test_the_strip_of_ties_shows_six_rows_and_the_rest_behind_show_all(self):
        wiki = json.loads(json.dumps(self.wiki))
        extra = [{"id": f"{0xb0 + i:08x}", "name": f"Lodge {i}", "name_chapter": 1, "type": "organization", "first": 1, "aliases": [], "blurbs": []} for i in range(7)]
        wiki["entities"] += extra
        wiki["relations"] += [{"chapter": 2, "source": e["id"], "target": self.id["Grey Guild"], "type": "allied with", "family": "alliance",
                               "status": "stated", "by": "narrator", "quotes": []} for e in extra]
        out = self.view("graph:factions@5", wiki=wiki)
        self.assertEqual(len(out["model"]["ties"]), 9)
        strip = re.search(r'<div class="fties">(.*?)</div></div>', out["html"]).group(1)
        first, rest = strip.split('<button', 1)
        self.assertEqual(first.count("<li>"), 6)
        self.assertEqual(rest.count("<li>"), 3)
        self.assertIn("Show all 9", rest)

    def test_every_link_on_both_tabs_has_an_href_that_opens_the_same_view_at_the_same_chapter(self):
        for route in ("graph:factions", f"graph:factions:{self.id['Grey Guild']}", "graph:ladder", f"graph:ladder:{self.id['Ember Path']}"):
            links = self.view(f"links:{route}@5")
            self.assertEqual(links["bare"], [], route)
            self.assertTrue(any(r["go"] for r in links["rows"]), route)
            for r in links["rows"]:
                self.assertEqual(r["n"], 5, (route, r))
                if r["go"]:
                    self.assertEqual(r["p"], r["go"], route)
                if r["ent"]:
                    self.assertEqual(r["p"], "e:" + r["ent"], route)


@unittest.skipIf(NODE is None, "node is not installed")
class MiniStoryTabsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(statuses_script())
        cls.book.build()

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_a_book_without_a_ladder_has_no_power_ladder_tab(self):
        wiki = self.book.workdir / "site" / "data" / "wiki.json"
        self.assertIsNone(self.book.json("site/data/wiki.json")["book"]["ladder"])
        out = site_views(wiki, "graph@5", "graph:story@5", "graph:ladder@5")
        for view in ("graph@5", "graph:story@5"):
            self.assertNotIn("graph:ladder", out[view]["html"], view)
        self.assertIn("no power ladder", out["graph:ladder@5"]["html"])


if __name__ == "__main__":
    unittest.main()
