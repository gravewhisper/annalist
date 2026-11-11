import html as html_lib
import json
import math
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from annalist.families import NAMES
from annalist.template import ENTITY_TYPES, UNCATEGORIZED
from tests.test_build import MiniBuild, ROOT
from tests.test_eval import statuses_script

NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node is not installed")
class GraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(statuses_script())
        cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, *views, wiki=None):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        if wiki is not None:
            path = self.book.root / "graph-wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def graph(self, view, wiki=None):
        return self.site(view, wiki=wiki)[view]

    def labels(self, model):
        return {n["label"] for n in model["nodes"]}

    def edges(self, model):
        return {(self.name[e["source"]], e["label"], self.name[e["target"]]) for e in model["edges"]}

    def text(self, html):
        return re.sub(r"<[^>]+>", " ", html)

    def test_no_entry_relation_or_label_from_a_later_chapter_is_drawn(self):
        first = {e["id"]: e["first"] for e in self.wiki["entities"]}
        every = "&".join(f"type={t}" for t in sorted({e["type"] for e in self.wiki["entities"]}))
        views = [(n, view) for n in range(1, 6) for view in (f"graph:all@{n}?isolates=1", f"graph@{n}", f"graph@{n}?limit=1",
                                                              f"graph@{n}?limit=1&{every}", f"graph@{n}?{every}")]
        for n, view in views:
            g = self.graph(view)
            self.assertTrue(g["model"]["nodes"], view)
            drawn = [node["id"] for node in g["model"]["nodes"]] + [m for b in g["model"]["bubbles"] for m in b["members"]]
            drawn += [h["id"] for h in g["model"].get("hulls", [])] + [b["org"] for b in g["model"].get("bands", [])]
            self.assertTrue(all(first[i] <= n for i in drawn), view)
            self.assertTrue(all(max(e["chapters"]) <= n for e in g["model"]["edges"]), view)
            shown = self.text(g["html"])
            for later in {r["type"] for r in self.wiki["relations"] if r["chapter"] > n} - {r["type"] for r in self.wiki["relations"] if r["chapter"] <= n}:
                self.assertNotIn(later, shown, f"chapter {n}")
            for e in self.wiki["entities"]:
                if e["first"] > n:
                    self.assertNotIn(e["name"], shown, f"chapter {n}")

    def test_sister_wren_is_her_own_node_until_chapter_4_names_her_livia_hale(self):
        at3, at4 = self.graph("graph:all@3?allTypes=1")["model"], self.graph("graph:all@4?allTypes=1")["model"]
        self.assertIn(("Sister Wren", "archivist of", "Brannoc Abbey"), self.edges(at3))
        self.assertIn("Livia Hale", self.labels(at3))
        self.assertFalse([e for e in at3["edges"] if {self.name[e["source"]], self.name[e["target"]]} == {"Sister Wren", "Livia Hale"}])
        self.assertNotIn("Wren", " ".join(n["label"] for n in at3["nodes"] if n["id"] == self.id["Livia Hale"]))
        self.assertIn(("Livia Hale", "archivist of", "Brannoc Abbey"), self.edges(at4))
        self.assertFalse([e for e in at4["edges"] if self.id["Sister Wren"] in (e["source"], e["target"])])

    def identity_views(self, n):
        wren, livia, abbey = self.id["Sister Wren"], self.id["Livia Hale"], self.id["Brannoc Abbey"]
        views = {"whole": f"graph:all@{n}?allTypes=1", "orbit": f"graph:{livia}@{n}", "path": f"graph:path:{livia}~{abbey}@{n}"}
        out = self.site(*views.values())
        return {kind: out[view] for kind, view in views.items()}

    def identity_ties(self, model):
        pair = {self.id["Sister Wren"], self.id["Livia Hale"]}
        return [l.get("same") for l in model["links"] if {l["a"], l["b"]} == pair]

    def test_a_secret_identity_joins_its_true_identity_at_the_reveal_with_a_same_person_tie_shown_that_chapter(self):
        wren = self.id["Sister Wren"]
        for kind, g in self.identity_views(3).items():
            self.assertEqual(self.identity_ties(g["model"]), [], kind)
            self.assertNotIn("Same person", g["html"], kind)
            self.assertNotIn("Also known as", g["html"], kind)
            self.assertFalse(any(n.get("ghost") for n in g["model"]["nodes"]), kind)
        self.assertIn(wren, {n["id"] for n in self.identity_views(3)["whole"]["model"]["nodes"]})
        for kind, g in self.identity_views(4).items():
            self.assertEqual(self.identity_ties(g["model"]), [4], kind)
            self.assertEqual([n["id"] for n in g["model"]["nodes"] if n.get("ghost")], [wren], kind)
            self.assertFalse([e for e in g["model"]["edges"] if wren in (e["source"], e["target"])], kind)
            self.assertIn("Same person, revealed ch 4", g["html"], kind)
        self.assertIn(("Livia Hale", "archivist of", "Brannoc Abbey"), self.edges(self.identity_views(4)["path"]["model"]))
        self.assertIn("Also known as Sister Wren since ch 4", self.identity_views(4)["orbit"]["html"])
        for kind, g in self.identity_views(5).items():
            self.assertEqual(self.identity_ties(g["model"]), [], kind)
            self.assertNotIn(wren, {n["id"] for n in g["model"]["nodes"]}, kind)
        self.assertIn("Also known as Sister Wren since ch 4", self.identity_views(5)["orbit"]["html"])

    def test_a_flashback_relation_is_labelled_and_drawn_apart_from_the_present_one(self):
        at3, at4 = self.graph("graph:all@3"), self.graph("graph:all@4")
        flash = [e for e in at3["model"]["edges"] if e["label"] == "daughter of"]
        self.assertEqual([e["badge"] for e in flash], ["flashback"])
        self.assertIn("daughter of (flashback)", self.text(at3["html"]))
        self.assertEqual(sorted(e["badge"] for e in at4["model"]["edges"] if e["label"] == "daughter of"), ["", "flashback"])

    def erased_wiki(self):
        wiki = json.loads(json.dumps(self.wiki))
        wiki["timelines"].append({"id": "run1", "kind": "run", "label": "The first run", "period": "", "started": 1, "erased": 3})
        friend = next(r for r in wiki["relations"] if r["type"] == "friend of")
        friend["timeline"] = "run1"
        return wiki

    def test_a_relation_from_an_erased_timeline_is_hidden_until_asked_for_then_drawn_dashed_with_its_badge(self):
        wiki = self.erased_wiki()
        pair = ("Bram Ostrow", "friend of", "Ines Varro")
        before = self.site("graph:all@2", "graph:all@3", "graph:all@3?erased=1", wiki=wiki)
        self.assertIn(pair, self.edges(before["graph:all@2"]["model"]))
        self.assertNotIn(pair, self.edges(before["graph:all@3"]["model"]))
        shown = before["graph:all@3?erased=1"]
        edge = next(e for e in shown["model"]["edges"] if e["label"] == "friend of")
        self.assertEqual((edge["role"], edge["badge"]), ("erased", "erased timeline"))
        self.assertIn('class="edge erased', shown["html"])
        self.assertIn("friend of (erased timeline)", self.text(shown["html"]))

    def test_type_and_family_filters_hide_their_entries_and_relations(self):
        no_places = self.graph("graph:all@5?hideType=place")["model"]
        self.assertFalse({"Corvel Quay", "Brannoc Abbey"} & self.labels(no_places))
        self.assertFalse([e for e in no_places["edges"] if "Corvel Quay" in (self.name[e["source"]], self.name[e["target"]])])
        no_kin = self.graph("graph:all@5?hideFam=kin")["model"]
        self.assertNotIn("daughter of", {e["label"] for e in no_kin["edges"]})
        self.assertIn("friend of", {e["label"] for e in no_kin["edges"]})

    def test_the_characters_tab_shows_the_centres_linked_characters_and_chips_add_other_types(self):
        livia = self.id["Livia Hale"]
        people = self.graph(f"graph:{livia}@5")["model"]
        self.assertEqual(self.labels(people), {"Livia Hale", "Tomas Hale"})
        self.assertEqual([n["label"] for n in people["nodes"] if n["focus"]], ["Livia Hale"])
        more = self.graph(f"graph:{livia}@5?type=character&type=artifact&type=place")["model"]
        self.assertEqual(self.labels(more), {"Livia Hale", "Tomas Hale", "Gannet", "Brannoc Abbey", "harbour lamp"})
        early = self.graph(f"graph:{self.id['Captain Fenn']}@2")["model"]
        self.assertNotIn("Captain Fenn", self.labels(early))
        self.assertEqual([n["label"] for n in early["nodes"] if n["focus"]], [self.most_connected_character(2)])

    def test_an_entry_with_no_relations_shows_only_when_asked_for(self):
        self.assertNotIn("Salt Ledger", self.labels(self.graph("graph:all@5?allTypes=1")["model"]))
        self.assertIn("Salt Ledger", self.labels(self.graph("graph:all@5?isolates=1&allTypes=1")["model"]))

    def test_a_chapter_lays_out_the_same_whatever_chapters_were_seen_first(self):
        places = lambda g: {n["id"]: (n["x"], n["y"]) for n in g["model"]["nodes"]}
        walked = self.site("graph:all@5?allTypes=1", "graph:all@3?allTypes=1", "graph:all@4?allTypes=1")
        fresh = self.site("graph:all@3?allTypes=1")
        self.assertEqual(places(walked["graph:all@3?allTypes=1"]), places(fresh["graph:all@3?allTypes=1"]))

    def test_the_entry_page_draws_its_neighbours_as_of_the_chapter(self):
        livia, wren = self.id["Livia Hale"], self.id["Sister Wren"]
        pages = self.site(f"{livia}@3", f"{livia}@4", f"{wren}@3")
        ego = {k: self.text(re.search(r'<div class="egobox">.*?as of chapter', v, re.S).group(0)) for k, v in pages.items()}
        self.assertIn("Tomas Hale", ego[f"{livia}@3"])
        self.assertIn("Gannet", ego[f"{livia}@3"])
        self.assertNotIn("Brannoc Abbey", ego[f"{livia}@3"])
        self.assertIn("Brannoc Abbey", ego[f"{livia}@4"])
        self.assertIn("Brannoc Abbey", ego[f"{wren}@3"])
        self.assertNotIn("Livia", ego[f"{wren}@3"])
        self.assertNotIn("Tomas", ego[f"{wren}@3"])

    def plain(self, html):
        spaced = re.sub(r"</?(?:div|h\d|li|ul|blockquote|p|button)\b[^>]*>", " ", html)
        return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", spaced))).strip()

    def cards(self, html):
        return re.findall(r'<div class="myst [\w-]+">.*?(?=<div class="myst |$)', html, re.S)

    def staged(self):
        wiki = json.loads(json.dumps(self.wiki))
        q = {x["id"]: x for x in wiki["questions"]}
        lead, premise = q["Q0003-01"], q["Q0001-01"]
        del lead["resolved"], premise["resolved"]
        lead["leads"] = [{"chapter": 4, "text": "The ledger page turns up torn.", "quote": "The torn page lay under the lamp."}]
        premise["premise"] = {"chapter": 4, "explanation": "Nobody hid anything.", "quotes": [{"chapter": 4, "quote": "There was nothing hidden."}]}
        return wiki, lead, premise

    def test_a_resolved_mystery_labels_its_question_and_sets_its_answer_apart(self):
        html = self.site("mysteries@5?m=resolved")["mysteries@5?m=resolved"]
        resolved = [q for q in self.wiki["questions"] if q.get("resolved")]
        cards = self.cards(html)
        self.assertEqual(len(cards), len(resolved))
        for q in resolved:
            card = next(c for c in cards if q["question"] in self.plain(c))
            question = self.plain(re.search(r'<div class="mq">(.*?)</div><div class="mans">', card, re.S).group(1))
            answer = self.plain(re.search(r'<div class="mans">(.*)', card, re.S).group(1))
            self.assertTrue(question.startswith(f"Question \u00b7 raised in Ch {q['chapter']} {q['question']}"), question)
            self.assertTrue(answer.startswith(f"Answer \u00b7 resolved in Ch {q['resolved']['chapter']} {q['resolved']['answer']}"), answer)
            self.assertNotIn(q["resolved"]["answer"], question)

    def test_leads_and_a_failed_premise_carry_their_own_labels_from_their_chapter_on(self):
        wiki, lead, premise = self.staged()
        out = self.site("mysteries@3?m=open", "mysteries@4?m=partial", "mysteries@4?m=resolved", wiki=wiki)
        self.assertNotIn("Lead &middot;", out["mysteries@3?m=open"])
        self.assertNotIn("Nobody hid anything", out["mysteries@3?m=open"])
        self.assertIn("Lead \u00b7 Ch 4 The ledger page turns up torn.", self.plain(out["mysteries@4?m=partial"]))
        card = next(c for c in self.cards(out["mysteries@4?m=resolved"]) if "Nobody hid anything" in c)
        self.assertIn('<div class="mans"><div class="mlbl">Premise does not hold &middot; ch 4</div>', card)

    def test_every_disclosure_is_a_button_that_flips_aria_expanded_and_its_panel(self):
        livia = self.id["Livia Hale"]
        out = self.site("toggle:mysteries@5?m=resolved&label=how it pays off", f"toggle:e:{livia}@5?tab=facts&label=quote", f"toggle:e:{livia}@5?tab=relations&label=quote")
        closed, opened = {"expanded": "false", "hidden": True}, {"expanded": "true", "hidden": False}
        for view, steps in out.items():
            self.assertEqual(steps, [closed, opened, closed], view)
        html = self.site("mysteries@5?m=resolved")["mysteries@5?m=resolved"]
        self.assertNotIn("<details", html)
        self.assertRegex(html, r'<button type="button" class="disc" aria-expanded="false" aria-controls="(\w+)"><span><span class="ifshut">Show</span>'
                               r'<span class="ifopen">Hide</span> how it pays off</span></button><div class="discbody" id="\1" hidden>')

    def belief_wiki(self):
        wiki = json.loads(json.dumps(self.wiki))
        odile = next(e for e in wiki["entities"] if e["name"] == "Odile Marr")
        odile["name_chapter"] = 5
        odile["aliases"].append({"name": "the ferrywoman", "chapter": 1})
        wiki["relations"] += [
            {"chapter": 2, "source": self.id["Ines Varro"], "target": self.id["Sabine Oake"], "type": "secret courtship with",
             "family": "romance", "status": "belief", "by": "Odile Marr", "quotes": []},
            {"chapter": 2, "source": self.id["Tomas Hale"], "target": self.id["Sabine Oake"], "type": "rumoured rival of",
             "family": "hostility", "status": "belief", "by": "narrator", "quotes": []},
        ]
        return wiki

    def test_a_belief_is_drawn_dashed_and_names_who_suspects_it_without_spoiling_their_name(self):
        ines, sabine, bram = self.id["Ines Varro"], self.id["Sabine Oake"], self.id["Bram Ostrow"]
        views = self.site(f"graph:{ines}@3", f"{ines}@3", f"{sabine}@3", f"{ines}@3?tab=relations", wiki=self.belief_wiki())
        graph, page = views[f"graph:{ines}@3"]["html"], views[f"{ines}@3"]
        edge = lambda a, b: re.search(rf'<path class="([^"]*)" data-a="{min(a, b)}" data-b="{max(a, b)}"[^>]*><title>(.*?)</title>', graph)
        dashed, title = edge(ines, sabine).groups()
        self.assertIn("belief", dashed.split())
        self.assertNotIn("belief", edge(ines, bram).group(1).split())
        self.assertEqual(html_lib.unescape(title), "Ines Varro has a secret courtship with Sabine Oake (suspected by the ferrywoman), ch 2")
        sentence = next(li for li in re.findall(r"<li>(.*?)</li>", page) if "secret courtship" in li)
        self.assertEqual(self.plain(sentence), "Ines Varro has a secret courtship with Sabine Oake suspected by the ferrywoman since ch 2")
        self.assertIn('<b class="belief"', sentence)
        self.assertIn('<i class="sus">suspected by the ferrywoman</i>', sentence)
        rumour = next(li for li in re.findall(r"<li>(.*?)</li>", views[f"{sabine}@3"]) if "rumoured rival" in li)
        self.assertEqual(self.plain(rumour), "Tomas Hale is a rumoured rival of Sabine Oake suspected since ch 2")
        self.assertIn('<b class="belief"', rumour)
        listed = re.search(r'<div class="chgroup">.*', views[f"{ines}@3?tab=relations"], re.S).group(0)
        self.assertIn("Ines Varro has a secret courtship with Sabine Oake Ch 2 suspected by the ferrywoman Bram", self.plain(listed))

    def test_every_family_and_entity_type_the_pipeline_gives_sits_in_exactly_one_group_with_a_colour_in_both_themes(self):
        tables = self.site("tables@1")["tables@1"]
        self.assertEqual(sorted(f for g in tables["rel"] for f in g["fams"]), sorted(NAMES))
        listed = [t for g in tables["types"] for t in g["types"]]
        self.assertEqual(len(listed), len(set(listed)))
        self.assertLessEqual(set(ENTITY_TYPES) | {UNCATEGORIZED}, set(listed))
        css = (ROOT / "annalist" / "site" / "app.css").read_text(encoding="utf-8")
        for theme in ("light", "dark"):
            tokens = set(re.findall(r"--r-(\w+):#[0-9a-f]{6}", re.search(rf':root\[data-theme="{theme}"\]\{{[^}}]*\}}', css).group(0)))
            self.assertEqual({g["key"] for g in tables["rel"]}, tokens, theme)
            self.assertNotIn("--f-", css)

    def test_the_header_shows_the_title_from_the_epubs_metadata(self):
        self.assertEqual(self.site("header@1")["header@1"], {"brand": "The Salt Ledger", "title": "The Salt Ledger"})

    def test_the_connections_list_reads_each_relation_in_its_own_direction(self):
        livia, abbey = self.id["Livia Hale"], self.id["Brannoc Abbey"]
        pages = self.site(f"{livia}@3", f"{livia}@4", f"{abbey}@4")
        groups = {k: {re.sub(r" \d+$", "", self.plain(head)): [self.plain(li) for li in re.findall(r"<li>(.*?)</li>", rows)]
                      for head, rows in re.findall(r"<h4>(.*?)</h4><ul class=\"clist\">(.*?)</ul>", re.search(r'<div class="egobox">.*', v, re.S).group(0))}
                  for k, v in pages.items()}
        self.assertNotIn("Brannoc Abbey", str(groups[f"{livia}@3"]))
        self.assertIn("Livia Hale is an archivist of Brannoc Abbey since ch 3", groups[f"{livia}@4"]["Allies"])
        self.assertIn("Livia Hale is an archivist of Brannoc Abbey since ch 3", groups[f"{abbey}@4"]["Allies"])
        for page in groups.values():
            for line in sum(page.values(), []):
                self.assertNotIn("Brannoc Abbey is an archivist of Livia Hale", line)
                self.assertNotIn("\u2190", line)
                self.assertNotIn("\u2026", line)

    def test_every_internal_link_has_an_href_that_opens_the_same_view_at_the_same_chapter(self):
        livia = self.id["Livia Hale"]
        for route in ("home", f"e:{livia}", "mysteries", "chapters", "ch:3", "cat:character", "v:the-salt-ledger", f"graph:{livia}", "graph:story"):
            links = self.site(f"links:{route}@4")[f"links:{route}@4"]
            self.assertEqual(links["bare"], [], route)
            self.assertTrue(any(r["go"] for r in links["rows"]), route)
            for r in links["rows"]:
                self.assertEqual(r["n"], 4, (route, r))
                if r["go"]:
                    self.assertEqual(r["p"], r["go"], route)
                if r["ent"]:
                    self.assertEqual(r["p"], "e:" + r["ent"], route)
                if r["tabTo"]:
                    self.assertEqual((r["p"], r["tab"]), (route, r["tabTo"]))
                if r["mTo"]:
                    self.assertEqual((r["p"], r["m"]), (route, r["mTo"]))

    def test_a_plain_click_on_a_link_routes_in_place_and_a_modified_or_middle_click_is_left_to_the_browser(self):
        mods = ("", "ctrl", "meta", "shift", "alt", "middle")
        out = self.site(*(f"navclick:{m}@3?to=chapters" for m in mods))
        self.assertEqual(out["navclick:@3?to=chapters"], {"prevented": True, "routed": True})
        for m in mods[1:]:
            self.assertEqual(out[f"navclick:{m}@3?to=chapters"], {"prevented": False, "routed": False}, m)

    def story(self, *views, wiki=None):
        return {k: {**v, "lines": {l["id"]: l for l in v["model"]["lines"]}} if "model" in v else v
                for k, v in self.site(*views, wiki=wiki).items()}

    def dead_wiki(self, name, chapter):
        wiki = json.loads(json.dumps(self.wiki))
        entry = next(e for e in wiki["entities"] if e["name"] == name)
        entry["profile"]["fields"]["status"] = [{"chapter": chapter, "value": "dead", "quotes": ["They buried him at the quay."]}]
        return wiki

    def test_the_storyline_draws_no_line_past_the_chapter_and_names_no_one_not_yet_met(self):
        first = {e["id"]: e["first"] for e in self.wiki["entities"]}
        out = self.story(*(f"graph:story@{n}" for n in range(1, 6)))
        for n in range(1, 6):
            g = out[f"graph:story@{n}"]
            self.assertTrue(g["lines"], n)
            for line in g["lines"].values():
                self.assertLessEqual(first[line["id"]], line["start"], n)
                self.assertTrue(all(c <= n for c, _ in line["points"]), (n, line["id"]))
                self.assertLessEqual(line["end"], n)
            shown = self.text(g["html"])
            for e in self.wiki["entities"]:
                if e["first"] > n:
                    self.assertNotIn(e["name"], shown, f"chapter {n}")

    def test_a_line_starts_where_its_character_first_appears_and_a_death_ends_it_with_a_marker(self):
        tomas = self.id["Tomas Hale"]
        out = self.story("graph:story@2", "graph:story@5", wiki=self.dead_wiki("Tomas Hale", 3))
        alive, dead = out["graph:story@2"]["lines"][tomas], out["graph:story@5"]["lines"][tomas]
        self.assertEqual((alive["start"], alive["end"], alive["death"]), (1, 2, None))
        self.assertEqual((dead["start"], dead["end"], dead["death"]), (1, 3, 3))
        self.assertEqual(max(c for c, _ in dead["points"]), 3)
        self.assertNotIn(f'data-death="{tomas}"', out["graph:story@2"]["html"])
        self.assertIn(f'data-death="{tomas}"', out["graph:story@5"]["html"])
        self.assertEqual(out["graph:story@5"]["lines"][self.id["Captain Fenn"]]["start"], 3)

    def test_a_secret_identity_runs_under_the_name_known_at_each_chapter(self):
        livia, wren = self.id["Livia Hale"], self.id["Sister Wren"]
        out = self.story("graph:story@3", "graph:story@5")
        before, after = out["graph:story@3"]["lines"], out["graph:story@5"]["lines"]
        self.assertEqual([s["label"] for s in before[wren]["segments"]], ["Sister Wren"])
        self.assertNotIn("Wren", " ".join(s["label"] for s in before[livia]["segments"]))
        self.assertNotIn(wren, after)
        self.assertEqual([(s["from"], s["label"]) for s in after[livia]["segments"]], [(2, "Livia Hale"), (3, "Sister Wren"), (4, "Livia Hale")])

    def test_characters_who_share_a_chapter_are_drawn_side_by_side(self):
        g = self.story("graph:story@5")["graph:story@5"]
        y = {i: dict(map(tuple, l["points"])) for i, l in g["lines"].items()}
        trio = {self.id[n] for n in ("Ines Varro", "Tomas Hale", "Bram Ostrow")}
        group = next(set(gr["members"]) for gr in g["model"]["groups"] if gr["chapter"] == 1 and trio <= set(gr["members"]))
        column = sorted((y[i][1], i) for i in y if 1 in y[i])
        spots = sorted(i for i, (_, line) in enumerate(column) if line in group)
        self.assertEqual(spots, list(range(spots[0], spots[0] + len(group))))
        inside = max(b[0] - a[0] for a, b in zip(column, column[1:]) if a[1] in group and b[1] in group)
        outside = [b[0] - a[0] for a, b in zip(column, column[1:]) if (a[1] in group) != (b[1] in group)]
        self.assertTrue(outside)
        self.assertTrue(all(inside < gap for gap in outside), (inside, outside))

    def test_a_character_can_be_removed_added_back_and_focused(self):
        fenn, ines = self.id["Captain Fenn"], self.id["Ines Varro"]
        picked = self.story("route:graph:story@5", f"click:sdrop={fenn}@5", "graph:story@5", f"click:sadd={fenn}@5", "graph:story@5?back=1")
        self.assertIn(f'data-line="{fenn}"', picked["route:graph:story@5"]["html"])
        self.assertNotIn(fenn, picked["graph:story@5"]["lines"])
        self.assertIn(fenn, picked["graph:story@5"]["model"]["candidates"])
        self.assertIn(fenn, picked["graph:story@5?back=1"]["lines"])
        focus = self.story("route:graph:story@5", f"click:sfocus={ines}@5", f"graph:story:{ines}@5")
        self.assertEqual(focus[f"click:sfocus={ines}@5"]["p"], f"graph:story:{ines}")
        self.assertEqual(focus[f"graph:story:{ines}@5"]["model"]["focus"], ines)
        self.assertEqual(re.findall(r'<g class="sline focus" data-line="(\w+)"', focus[f"graph:story:{ines}@5"]["html"]), [ines])
        again = self.site(f"route:graph:story:{ines}@5", f"click:sfocus={ines}@5")
        self.assertEqual(again[f"click:sfocus={ines}@5"]["p"], "graph:story")

    def test_the_storyline_lays_out_the_same_whatever_chapters_were_seen_first(self):
        walked = self.site("graph:story@3", "graph:story@4", "graph:story@5")["graph:story@5"]
        fresh = self.site("graph:story@5")["graph:story@5"]
        self.assertEqual(walked, fresh)

    def most_connected_character(self, n):
        everything = self.graph(f"graph:all@{n}?allTypes=1")["model"]
        people = [node for node in everything["nodes"] if node["type"] == "character"]
        return max(people, key=lambda node: (node["degree"], [-ord(c) for c in node["label"]]))["label"]

    def test_the_graph_opens_on_the_most_connected_character_known_by_the_chapter(self):
        for n in (2, 5):
            g = self.graph(f"graph@{n}")
            self.assertEqual([node["label"] for node in g["model"]["nodes"] if node["focus"]], [self.most_connected_character(n)])
            self.assertIn('data-go="graph:all"', g["html"])
        whole = self.graph("graph:all@5")
        self.assertEqual([n["id"] for n in whole["model"]["nodes"] if n["focus"]], [whole["model"]["focus"]])
        self.assertRegex(whole["html"], r'data-go="graph" href="#[^"]*" class="">Characters')

    def test_the_graph_reopens_on_the_last_focused_entry_while_it_is_known(self):
        livia, fenn = self.id["Livia Hale"], self.id["Captain Fenn"]
        views = self.site(f"graph:{livia}@5", "graph@5", "graph:all@5", "graph@4")
        self.assertEqual([views[v]["model"]["focus"] for v in ("graph@5", "graph@4")], [livia, livia])
        hidden = self.site(f"graph:{fenn}@5", "graph@2")["graph@2"]["model"]
        self.assertEqual([node["label"] for node in hidden["nodes"] if node["focus"]], [self.most_connected_character(2)])


def orbit_angle(point, start=-90):
    return (math.degrees(math.atan2(point["y"], point["x"])) - start) % 360


def assert_tidy_bands(test, model):
    nodes = {n["id"]: n for n in model["nodes"]}
    for b in model["bands"]:
        test.assertEqual(len({nodes[i]["r"] for i in b["members"]}), 1, "a band stays on one ring")
        span = [orbit_angle(nodes[i]) for i in b["members"]]
        inside = {n["id"] for n in model["nodes"] if not n["focus"] and n["r"] == nodes[b["members"][0]]["r"] and min(span) <= orbit_angle(n) <= max(span)}
        test.assertEqual(inside, set(b["members"]), "no outsider sits inside a band")


def hub_wiki():
    names = ["Ada Hub"] + [f"Person {i:02d}" for i in range(1, 26)] + ["Outsider A", "Outsider B", "Outsider C"]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, n in enumerate(names, 1)]
    entities += [{"id": f"{0xa0 + i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": []}
                 for i, (n, t) in enumerate([("Nighthawks", "organization"), ("Quiet Guild", "organization"), ("Harbour Town", "place")])]
    ids = {e["name"]: e["id"] for e in entities}
    rel = lambda c, a, t, b, fam: {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "quotes": []}
    linked = {i: 5 if i <= 5 else 4 if i <= 10 else 3 if i <= 15 else 2 if i <= 19 else 1 for i in range(1, 26)}
    first = {i: 2 if i <= 5 else 1 for i in linked}
    relations = [rel(c, "Ada Hub", "friend of", f"Person {i:02d}", "alliance") for i, k in linked.items() for c in range(first[i], first[i] + k)]
    relations += [rel(c, "Ada Hub", "met", f"Person {i:02d}", "alliance") for i in range(6, 11) for c in range(1, 5)]
    relations += [rel(1, f"Person {i:02d}", "member of", "Nighthawks", "membership") for i in (1, 2, 3, 20, 21, 22)]
    relations += [rel(1, "Person 23", "member of", "Quiet Guild", "membership"), rel(1, "Ada Hub", "lives in", "Harbour Town", "place")]
    relations += [rel(1, "Person 25", "rival of", o, "hostility") for o in ("Outsider A", "Outsider B", "Outsider C")]
    relations += [rel(6, "Person 01", "enemy of", "Person 02", "hostility")]
    return {"book": {"title": "Hub", "max": 6, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class CharactersTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = hub_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}
        cls.hub = cls.id["Ada Hub"]

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def site(self, *views):
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(self.path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def model(self, query="", n=6):
        return self.site(f"graph:{self.hub}@{n}?{query}")[f"graph:{self.hub}@{n}?{query}"]

    def people(self, *numbers):
        return {f"Person {i:02d}" for i in numbers}

    def shown(self, model):
        return {n["label"] for n in model["nodes"]} - {"Ada Hub"}

    def test_the_twenty_strongest_links_show_and_the_rest_wait_behind_show_more(self):
        g = self.model()
        self.assertEqual(self.shown(g["model"]), self.people(*range(1, 20), 25))
        self.assertEqual(g["model"]["more"], 5)
        self.assertIn("Show 5 more", g["html"])
        everyone = self.model("limit=40")
        self.assertEqual(self.shown(everyone["model"]), self.people(*range(1, 26)))
        self.assertEqual((everyone["model"]["more"], everyone["model"]["bubbles"]), (0, []))
        self.assertNotIn("more</button>", everyone["html"])

    def test_the_hidden_neighbours_gather_into_bubbles_by_shared_organization_then_by_type(self):
        g = self.model()["model"]
        bubbles = {b["label"]: {self.name[m] for m in b["members"]} for b in g["bubbles"]}
        self.assertEqual(bubbles, {"+3 Nighthawks members": self.people(20, 21, 22), "+2 characters": self.people(23, 24)})
        opened = self.model(f"open=org:{self.id['Nighthawks']}")["model"]
        self.assertEqual(self.shown(opened), self.people(*range(1, 23), 25))
        self.assertEqual([b["label"] for b in opened["bubbles"]], ["+2 characters"])

    def test_members_of_one_organization_share_a_faint_band_on_each_ring_they_sit_on(self):
        def bands(m):
            assert_tidy_bands(self, m)
            return {self.name[i] for b in m["bands"] for i in b["members"]}, {b["name"] for b in m["bands"]}
        self.assertEqual(bands(self.model()["model"]), (self.people(1, 2, 3), {"Nighthawks"}))
        self.assertEqual(bands(self.model(f"open=org:{self.id['Nighthawks']}")["model"]), (self.people(1, 2, 3, 20, 21, 22), {"Nighthawks"}))
        self.assertEqual(bands(self.model("limit=1")["model"]), (set(), set()))

    def test_other_types_join_only_when_their_chip_is_on(self):
        self.assertNotIn("Harbour Town", {n["label"] for n in self.model()["model"]["nodes"]})
        self.assertIn("Harbour Town", {n["label"] for n in self.model("type=character&type=place&limit=40")["model"]["nodes"]})

    def test_a_neighbours_place_depends_only_on_the_chapter_shown_not_on_the_chapters_visited_before(self):
        at = lambda g: {n["id"]: (n["x"], n["y"]) for n in g["model"]["nodes"]}
        for query in ("", "limit=40"):
            view = lambda n: f"graph:{self.hub}@{n}?{query}"
            walk = (6, 2, 4, 1, 5, 3, 6)
            walked = [at(g) for g in [self.site(*map(view, walk[:i + 1]))[view(n)] for i, n in enumerate(walk)]]
            for n, seen in zip(walk, walked):
                fresh = self.site(view(n), view(n))[view(n)]
                self.assertEqual(seen, at(fresh), (query, n))
                self.assertEqual(fresh["html"], self.site(view(n))[view(n)]["html"], (query, n))
            spots = list(walked[0].values())
            self.assertEqual(len(set(spots)), len(spots), query)

    def test_selecting_an_entry_centres_the_graph_on_it_without_leaving_the_graph(self):
        p1 = self.id["Person 01"]
        steps = self.site(f"route:graph:{self.hub}@6", f"click:gn={p1}@6")
        self.assertEqual(steps[f"click:gn={p1}@6"]["p"], f"graph:{p1}")
        self.assertIn("Characters linked to Person 01", steps[f"click:gn={p1}@6"]["html"])
        keyed = self.site(f"route:graph:{self.hub}@6", f"key:gn={self.id['Person 02']}:Enter@6")
        self.assertEqual(keyed[f"key:gn={self.id['Person 02']}:Enter@6"]["p"], f"graph:{self.id['Person 02']}")

    def test_double_click_o_or_open_page_opens_the_entry_page(self):
        p1, p2, p3 = self.id["Person 01"], self.id["Person 02"], self.id["Person 03"]
        double = self.site(f"route:graph:{self.hub}@6", f"click:gn={p1}@6", "click:graph@6")
        self.assertEqual(double["click:graph@6"]["p"], f"e:{p1}")
        card = self.site(f"route:graph:{self.hub}@6", f"click:gopen={p2}@6")
        self.assertIn(f'data-gopen="{self.hub}"', card[f"route:graph:{self.hub}@6"]["html"])
        self.assertEqual(card[f"click:gopen={p2}@6"]["p"], f"e:{p2}")
        key = self.site(f"route:graph:{self.hub}@6", f"key:gn={p3}:o@6")
        self.assertEqual(key[f"key:gn={p3}:o@6"]["p"], f"e:{p3}")

    def test_a_bubble_or_show_more_reveals_its_entries_in_place(self):
        bubble = self.site(f"route:graph:{self.hub}@6", f"click:gb=org:{self.id['Nighthawks']}@6")[f"click:gb=org:{self.id['Nighthawks']}@6"]
        self.assertEqual((bubble["p"], "Person 20" in bubble["html"], "Person 24" in bubble["html"]), (f"graph:{self.hub}", True, False))
        more = self.site(f"route:graph:{self.hub}@6", "click:gmore=1@6")["click:gmore=1@6"]
        self.assertEqual((more["p"], "Person 24" in more["html"]), (f"graph:{self.hub}", True))


def grouped_wiki():
    names = [("Ada", "character"), ("Bea", "character"), ("Cy", "character"), ("Dee", "character")]
    names += [(f"Extra {i}", "character") for i in range(1, 10)]
    names += [("Guild", "organization"), ("Port", "place"), ("Blade", "artifact"), ("Way of Ash", "pathway"), ("Rite", "event")]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, (n, t) in enumerate(names, 1)]
    ids = {e["name"]: e["id"] for e in entities}
    rel = lambda c, a, t, b, fam, status="stated", by="narrator": {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam,
                                                                   "status": status, "by": by, "quotes": []}
    relations = [rel(1, "Bea", "sister of", "Ada", "kin")] + [rel(c, "Ada", "friend of", "Bea", "alliance") for c in (1, 2, 3)]
    relations += [rel(c, "Bea", "rival of", "Ada", "hostility") for c in (2, 3)] + [{**rel(2, "Bea", "taught", "Ada", "teaching"), "timeline": "past"}]
    relations += [rel(c, "Ada", "friend of", "Cy", "alliance") for c in (1, 2)] + [rel(5, "Cy", "suspects", "Ada", "investigation", "belief", "Dee")]
    relations += [rel(1, "Ada", "colleague of", "Dee", "alliance"), rel(1, "Bea", "cousin of", "Cy", "kin"), rel(1, "Dee", "knows", "Bea", "alliance")]
    relations += [rel(1, "Dee", "knows", f"Extra {i}", "alliance") for i in range(1, 10)] + [rel(1, "Ada", "knows", f"Extra {i}", "alliance") for i in (1, 2, 3)]
    relations += [rel(1, "Ada", "member of", "Guild", "membership"), rel(1, "Ada", "lives in", "Port", "place"), rel(1, "Ada", "owns", "Blade", "ownership"),
                  rel(1, "Ada", "follows", "Way of Ash", "kind"), rel(1, "Ada", "attended", "Rite", "other")]
    return {"book": {"title": "Groups", "max": 6, "public_domain": False, "theme": {}, "power_types": ["pathway"], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 7)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None},
                          {"id": "past", "kind": "flashback", "label": "Childhood", "period": "", "started": 2, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class GroupedGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = grouped_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}
        cls.ada = cls.id["Ada"]

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def site(self, *views):
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(self.path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def graph(self, query="", n=3):
        view = f"graph:{self.ada}@{n}?{query}"
        return self.site(view)[view]

    def line(self, html, a, b):
        a, b = self.id[a], self.id[b]
        found = re.findall(rf'<path class="([^"]*)" data-a="{min(a, b)}" data-b="{max(a, b)}"[^>]*style="stroke:var\(--r-(\w+)\)[^"]*"><title>(.*?)</title>', html)
        return [(cls.split(), group, html_lib.unescape(title)) for cls, group, title in found]

    def chips(self, html, attr):
        return {k: (cls, re.sub(r"<[^>]+>", " ", body).split()) for k, cls, body in re.findall(rf'<a data-{attr}="(\w+)" class="([^"]*)"[^>]*>(.*?)</a>', html)}

    def test_the_network_opens_on_people_only_and_a_group_chip_adds_its_types(self):
        g = self.graph()
        self.assertEqual({n["label"] for n in g["model"]["nodes"]}, {"Ada", "Bea", "Cy", "Dee", "Extra 1", "Extra 2", "Extra 3"})
        chips = self.chips(g["html"], "ggt")
        self.assertEqual(chips["people"][0], "on")
        self.assertEqual({k: v[1][-1] for k, v in chips.items()}, {"people": "13", "groups": "1", "places": "1", "things": "1", "lore": "2"})
        self.assertTrue(all(cls == "" for k, (cls, _) in chips.items() if k != "people"))
        steps = self.site(f"route:graph:{self.ada}@3", "click:ggt=lore@3")
        lore = steps["click:ggt=lore@3"]["html"]
        self.assertIn(f'data-gn="{self.id["Way of Ash"]}"', lore)
        self.assertIn(f'data-gn="{self.id["Rite"]}"', lore)
        self.assertNotIn(f'data-gn="{self.id["Port"]}"', lore)

    def test_one_line_joins_a_pair_and_lists_every_kind_on_hover(self):
        html = self.graph()["html"]
        [(cls, group, title)] = self.line(html, "Ada", "Bea")
        for kind in ("Bea is a sister of Ada", "Ada is a friend of Bea", "Bea is a rival of Ada", "Bea taught (flashback) Ada"):
            self.assertIn(kind, title)
        self.assertNotIn("aside", cls)

    def test_the_latest_kind_of_tie_colours_the_line_and_family_wins_a_tie_within_one_chapter(self):
        self.assertEqual(self.line(self.graph(n=1)["html"], "Ada", "Bea")[0][1], "close")
        html = self.graph()["html"]
        self.assertEqual(self.line(html, "Ada", "Bea")[0][1], "allies")
        self.assertEqual(self.line(html, "Ada", "Cy")[0][1], "allies")
        self.assertEqual(self.line(html, "Bea", "Cy")[0][1], "close")

    def flipped(self, *views):
        wiki = json.loads(self.path.read_text(encoding="utf-8"))
        rel = lambda c, b, t, fam: {"chapter": c, "source": self.ada, "target": self.id[b], "type": t, "family": fam, "status": "stated", "by": "narrator", "quotes": []}
        wiki["relations"] += [rel(c, "Extra 1", "helps", "alliance") for c in (2, 3)] + [rel(4, "Extra 1", "fights", "hostility"), rel(6, "Extra 1", "forgives", "alliance"), rel(5, "Extra 2", "loves", "romance")]
        path = Path(self.dir.name) / "flipped.json"
        path.write_text(json.dumps(wiki), encoding="utf-8")
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_a_line_changes_colour_in_the_chapter_its_tie_changes_kind(self):
        views = {n: f"graph:{self.ada}@{n}" for n in range(3, 7)}
        out = self.flipped(*views.values())
        colour = {(n, b): self.line(out[v]["html"], "Ada", b)[0][1] for n, v in views.items() for b in ("Extra 1", "Extra 2")}
        self.assertEqual([colour[(n, "Extra 1")] for n in range(3, 7)], ["allies", "conflict", "conflict", "allies"])
        self.assertEqual([colour[(n, "Extra 2")] for n in range(3, 7)], ["allies", "allies", "close", "close"])

    def test_hovering_a_line_lists_its_kinds_in_chapter_order_up_to_the_chapter_shown(self):
        views = {n: f"graph:{self.ada}@{n}" for n in (3, 4, 5, 6)}
        out = self.flipped(*views.values())
        title = {n: self.line(out[v]["html"], "Ada", "Extra 1")[0][2] for n, v in views.items()}
        self.assertTrue(title[3].endswith("\nch 1 knows · ch 2 helps"), title[3])
        self.assertTrue(title[4].endswith("\nch 1 knows · ch 2 helps · ch 4 fights"), title[4])
        self.assertTrue(title[5].endswith("\nch 1 knows · ch 2 helps · ch 4 fights"), title[5])
        self.assertTrue(title[6].endswith("\nch 1 knows · ch 2 helps · ch 4 fights · ch 6 forgives"), title[6])

    def test_a_line_group_chip_hides_its_kinds_and_keeps_the_rest_of_the_pair(self):
        steps = self.site(f"route:graph:{self.ada}@3", "click:ggr=conflict@3")
        html = steps["click:ggr=conflict@3"]["html"]
        self.assertEqual(self.chips(html, "ggr")["conflict"][0], "")
        [(_, group, title)] = self.line(html, "Ada", "Bea")
        self.assertNotIn("rival of", title)
        self.assertEqual(group, "allies")

    def test_a_suspicion_on_a_pair_with_stated_ties_names_who_suspects_it_and_leaves_the_line_solid(self):
        [(cls, group, title)] = self.line(self.graph(n=6)["html"], "Ada", "Cy")
        self.assertNotIn("belief", cls)
        self.assertIn("Cy suspects Ada (suspected by Dee)", title)
        self.assertEqual(self.line(self.graph(n=4)["html"], "Ada", "Cy")[0][2], "Ada is a friend of Cy, ch 1, 2")

    def test_every_tie_between_two_shown_neighbours_is_drawn_and_no_dot_carries_a_count(self):
        g = self.graph()
        pairs = {frozenset((self.name[e["source"]], self.name[e["target"]])) for e in g["model"]["edges"]}
        self.assertTrue({frozenset(("Dee", x)) for x in ("Ada", "Bea", "Extra 1", "Extra 2", "Extra 3")} <= pairs)
        self.assertIn(frozenset(("Bea", "Cy")), pairs)
        self.assertNotIn("connections</title>", g["html"])
        self.assertNotIn('class="ini"', g["html"])


ORBIT_SECTORS = ["close", "allies", "conflict", "belong", "things"]


def orbit_wiki():
    names = ["Orla", "Kin A", "Ally 1", "Ally 2", "Ally 3", "Foe", "Acolyte 1", "Acolyte 2", "Tinker",
             "Guildsman 1", "Guildsman 2", "Raider 1", "Raider 2", "Raider 3", "Raider 4"]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, n in enumerate(names, 1)]
    entities.append({"id": f"{0xb0:08x}", "name": "Guild", "name_chapter": 1, "type": "organization", "first": 1, "aliases": [], "blurbs": []})
    ids = {e["name"]: e["id"] for e in entities}
    rel = lambda c, a, t, b, fam: {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam, "status": "stated", "quotes": []}
    relations = [rel(c, "Kin A", "sister of", "Orla", "kin") for c in (1, 2, 3)]
    relations += [rel(c, "Orla", "friend of", f"Ally {i}", "alliance") for i in (1, 2, 3) for c in (1, 2, 3)]
    relations += [rel(c, "Acolyte " + i, "follower of", "Orla", "faith") for i in "12" for c in (1, 2)]
    relations += [rel(c, "Tinker", "same kind as", "Orla", "kind") for c in (1, 2)]
    relations += [rel(c, "Foe", "enemy of", "Orla", "hostility") for c in (4, 5)]
    relations += [rel(1, f"Ally {i}", "member of", "Guild", "membership") for i in (1, 3)]
    relations += [rel(3, "Orla", "met", f"Guildsman {i}", "alliance") for i in (1, 2)] + [rel(3, f"Guildsman {i}", "member of", "Guild", "membership") for i in (1, 2)]
    relations += [rel(3, f"Raider {i}", "attacked", "Orla", "hostility") for i in (1, 2, 3, 4)]
    return {"book": {"title": "Orbit", "max": 5, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 6)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class OrbitTest(unittest.TestCase):
    SECTOR = {"Kin A": "close", "Ally 1": "allies", "Ally 2": "allies", "Ally 3": "allies", "Guildsman 1": "allies", "Guildsman 2": "allies",
              "Foe": "conflict", "Raider 1": "conflict", "Raider 2": "conflict", "Raider 3": "conflict", "Raider 4": "conflict",
              "Acolyte 1": "belong", "Acolyte 2": "belong", "Tinker": "things"}

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = orbit_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.name = {e["id"]: e["name"] for e in cls.wiki["entities"]}

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def site(self, *views):
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(self.path), *views],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def graph(self, n, query=""):
        view = f"graph:{self.id['Orla']}@{n}?{query}"
        return self.site(view)[view]

    def around(self, g):
        items = [(n["label"], n) for n in g["model"]["nodes"] if not n["focus"]]
        items += [(b["label"], b) for b in g["model"]["bubbles"]]
        return sorted(items, key=lambda item: orbit_angle(item[1], start=-120))

    def sectors_in_order(self, g, sector_of):
        return [ORBIT_SECTORS.index(sector_of(label)) for label, _ in self.around(g)]

    def test_each_kind_of_tie_keeps_its_place_clockwise_from_close_ties_at_the_top(self):
        for n in (1, 2, 4, 5):
            g = self.graph(n)
            order = self.sectors_in_order(g, self.SECTOR.get)
            self.assertEqual(order, sorted(order), n)
            kin = next(node for node in g["model"]["nodes"] if node["label"] == "Kin A")
            self.assertLess(abs(orbit_angle(kin, start=-90 - 180) - 180), 1, n)
        self.assertIn(2, self.sectors_in_order(self.graph(4), self.SECTOR.get))

    def test_a_kind_with_nobody_in_it_leaves_only_a_thin_gap_and_the_others_share_the_circle(self):
        g = self.graph(2)
        self.assertNotIn("conflict", {self.SECTOR[n["label"]] for n in g["model"]["nodes"] if not n["focus"]})
        angles = sorted(orbit_angle(p) for _, p in self.around(g))
        gaps = [b - a for a, b in zip(angles, angles[1:] + [angles[0] + 360])]
        self.assertLess(max(gaps), 1.5 * 360 / len(angles), gaps)

    def test_a_bubble_sits_at_the_outer_edge_of_the_kind_most_of_its_members_share(self):
        g = self.graph(3, "limit=7")
        self.assertEqual({b["label"] for b in g["model"]["bubbles"]}, {"+2 Guild members", "+4 characters"})
        sector = {**self.SECTOR, "+2 Guild members": "allies", "+4 characters": "conflict"}
        order = self.sectors_in_order(g, sector.get)
        self.assertEqual(order, sorted(order))
        reach = max(math.hypot(n["x"], n["y"]) for n in g["model"]["nodes"])
        for b in g["model"]["bubbles"]:
            self.assertGreater(math.hypot(b["x"], b["y"]), reach, b["label"])
            self.assertNotIn(f'data-b="{b["key"]}"', g["html"])

    def test_every_label_sits_outside_its_dot_on_the_side_away_from_the_centre(self):
        g = self.graph(3, "limit=7")
        spots = {p.get("id", p.get("key")): p for p in g["model"]["nodes"] + g["model"]["bubbles"]}
        labels = re.findall(r'<text class="lbl[^"]*" data-for="([^"]+)"[^>]*x="([-\d.]+)" y="([-\d.]+)"', g["html"])
        self.assertEqual({k for k, *_ in labels}, set(spots))
        for key, x, y in labels:
            p, x, y = spots[key], float(x), float(y)
            self.assertGreater(math.hypot(x - p["x"], y - p["y"]), p["r"], key)
            if not p.get("focus"):
                self.assertGreater(math.hypot(x, y), math.hypot(p["x"], p["y"]), key)
                self.assertGreater((x - p["x"]) * p["x"] + (y - p["y"]) * p["y"], 0, key)

    def test_the_strongest_ties_sit_on_the_inner_ring_with_the_largest_dots(self):
        nodes = self.graph(3)["model"]["nodes"]
        centre = next(n for n in nodes if n["focus"])
        others = [n for n in nodes if not n["focus"]]
        self.assertEqual(len({n["r"] for n in others}), 3)
        self.assertGreater(centre["r"], max(n["r"] for n in others))
        by_size = sorted(others, key=lambda n: -n["r"])
        self.assertLessEqual(max(math.hypot(n["x"], n["y"]) for n in by_size if n["r"] == by_size[0]["r"]),
                             min(math.hypot(n["x"], n["y"]) for n in by_size if n["r"] == by_size[-1]["r"]))
        self.assertLessEqual({"Kin A", "Ally 1", "Ally 2", "Ally 3"}, {n["label"] for n in by_size if n["r"] == by_size[0]["r"]})
        self.assertLessEqual({f"Raider {i}" for i in (1, 2, 3, 4)}, {n["label"] for n in by_size if n["r"] == by_size[-1]["r"]})

    def test_members_of_one_group_sit_side_by_side_under_one_band_per_ring(self):
        g = self.graph(3)["model"]
        assert_tidy_bands(self, g)
        self.assertEqual({(b["name"], tuple(sorted(self.name[i] for i in b["members"]))) for b in g["bands"]},
                         {("Guild", ("Ally 1", "Ally 3")), ("Guild", ("Guildsman 1", "Guildsman 2"))})

    def test_a_first_tap_on_a_touch_screen_previews_an_entry_and_a_second_tap_centres_on_it(self):
        orla, ally = self.id["Orla"], self.id["Ally 1"]
        steps = self.site(f"route:graph:{orla}@3", f"tap:gn={ally}@3")
        self.assertEqual(steps[f"tap:gn={ally}@3"]["p"], f"graph:{orla}")
        twice = self.site(f"route:graph:{orla}@3", f"tap:gn={ally}@3", f"tap:gn={ally}@3")
        self.assertEqual(twice[f"tap:gn={ally}@3"]["p"], f"graph:{ally}")


FAMILIES = ["kin", "alliance", "hostility", "membership", "kind"]


def crowded_wiki(linked):
    names = ["Hub"] + [f"Villager {i:03d}" for i in range(linked)]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": "character", "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, n in enumerate(names, 1)]
    relations = [{"chapter": 1, "source": entities[0]["id"], "target": e["id"], "type": "friend of", "family": FAMILIES[i % len(FAMILIES)], "status": "stated", "quotes": []} for i, e in enumerate(entities[1:])]
    return {"book": {"title": "Crowd", "max": 3, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 4)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class CrowdedOrbitTest(unittest.TestCase):
    def render(self, linked, *views):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(crowded_wiki(linked)), encoding="utf-8")
            proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), *views],
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def rings(self, linked):
        view = f"graph:00000001@1?limit={linked}"
        others = [n for n in self.render(linked, view)[view]["model"]["nodes"] if not n["focus"]]
        by_radius = sorted(others, key=lambda n: math.hypot(n["x"], n["y"]))
        rings, last = [], None
        for n in by_radius:
            r = math.hypot(n["x"], n["y"])
            if last is None or r - last > 40:
                rings.append([])
            rings[-1].append(n)
            last = r
        return rings

    def test_each_ring_of_a_large_focus_holds_more_people_than_the_ring_inside_it(self):
        sizes = [len(ring) for ring in self.rings(66)]
        self.assertGreaterEqual(len(sizes), 3, sizes)
        self.assertEqual(sum(sizes), 66)
        self.assertEqual(sizes, sorted(sizes), sizes)
        self.assertTrue(all(inner < outer for inner, outer in zip(sizes, sizes[1:])), sizes)

    def test_labels_of_a_large_focus_do_not_collide_at_fit_zoom_and_dots_stay_readable(self):
        view = "fitted:00000001@1?limit=66"
        fit = self.render(66, view)[view]
        self.assertGreater(fit["k"], 0.4)
        boxes = fit["boxes"]
        pairs = [(i, j) for i, a in enumerate(boxes) for j, b in enumerate(boxes[:i]) if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]]
        self.assertEqual(pairs, [])

    def test_a_small_focus_keeps_its_radius(self):
        for linked in (6, 20):
            view = f"graph:00000001@1?limit={linked}"
            nodes = [n for n in self.render(linked, view)[view]["model"]["nodes"] if not n["focus"]]
            reach = max(math.hypot(n["x"], n["y"]) for n in nodes)
            self.assertAlmostEqual(reach / 300, 0.95 + 0.06, delta=0.05, msg=linked)

    def test_the_reveal_stays_short_however_many_people_are_drawn(self):
        for count in (7, 67, 196, 800):
            view = f"reveal:{count}@1"
            timing = self.render(6, view)[view]
            self.assertLessEqual(timing["dur"] + timing["lag"] * (count - 1), 400.0001, count)
        small = self.render(6, "reveal:7@1")["reveal:7@1"]
        self.assertEqual(small["lag"], 20)


@unittest.skipIf(NODE is None, "node is not installed")
class ConnectionsListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = grouped_wiki()
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.ada = cls.id["Ada"]

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def page(self, n, wiki=None, id=None):
        path = Path(self.dir.name) / "wiki.json"
        path.write_text(json.dumps(wiki or self.wiki), encoding="utf-8")
        view = f"{id or self.ada}@{n}"
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path), view],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return re.search(r'<div class="egobox">.*', json.loads(proc.stdout)[view], re.S).group(0)

    def plain(self, html):
        return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", html))).strip()

    def sections(self, box):
        return {self.plain(head).rsplit(" ", 1)[0]: re.findall(r"<li>(.*?)</li>", body)
                for head, body in re.findall(r'<h4>(.*?)</h4>(.*?)(?=<h4>|<div class="asof">)', box, re.S)}

    def partner(self, li):
        return next(n for n, i in self.id.items() if f'data-ent="{i}"' in li)

    def row(self, box, name):
        return next(li for rows in self.sections(box).values() for li in rows if self.partner(li) == name)

    def marks(self, li):
        return [int(c) for c in re.findall(r'data-ch="(\d+)"', li)]

    def test_each_partner_sits_in_one_section_by_its_strongest_kind_with_family_first(self):
        found = {k: [self.partner(li).split(" ")[0] for li in rows] for k, rows in self.sections(self.page(6)).items()}
        self.assertEqual(list(found), ["Close", "Allies", "Belonging", "Things & places"])
        self.assertEqual(found["Close"], ["Bea"])
        self.assertEqual(sorted(found["Allies"]), ["Cy", "Dee", "Extra", "Extra", "Extra"])
        self.assertEqual(sorted(found["Things & places"]), ["Blade", "Port", "Rite", "Way"])

    def test_a_row_names_its_entry_with_a_link_and_reads_the_role_in_its_own_direction_since_its_first_chapter(self):
        box = self.page(6)
        bea, cy = self.row(box, "Bea"), self.row(box, "Cy")
        self.assertEqual(self.plain(bea), "Bea is a sister of Ada +3 since ch 1")
        self.assertIn(f'href="#n=6&p=e%3A{self.id["Bea"]}"', bea)
        self.assertEqual(self.plain(cy), "Ada is a friend of Cy +1 since ch 1")
        self.assertEqual(self.plain(self.row(box, "Port")), "Ada lives in Port since ch 1")

    def test_the_bar_marks_where_the_tie_began_and_each_change_of_kind_up_to_the_chapter_shown(self):
        at4, at6 = self.row(self.page(4), "Cy"), self.row(self.page(6), "Cy")
        self.assertEqual(self.marks(at4), [1])
        self.assertEqual(self.marks(at6), [1, 5])
        self.assertIn('data-ch="5" style="left:83.3%;--c:var(--r-conflict)"', at6)
        self.assertIn("from ch 1, then conflict ch 5", html_lib.unescape(at6))

    def test_the_bar_is_coloured_in_segments_by_the_kind_of_tie_each_stretch_of_chapters(self):
        segments = lambda li: re.findall(r'<b[^>]*style="left:([\d.]+)%;right:([\d.]+)%;--c:var\(--r-(\w+)\)"', li)
        self.assertEqual(segments(self.row(self.page(4), "Cy")), [("25", "0", "allies")])
        self.assertEqual(segments(self.row(self.page(6), "Cy")), [("16.7", "16.7", "allies"), ("83.3", "0", "conflict")])

    def test_bar_marks_never_pass_the_chapter_shown_and_stay_few(self):
        wiki = json.loads(json.dumps(self.wiki))
        flip = [("alliance", "helps"), ("hostility", "fights")]
        wiki["relations"] += [{"chapter": c, "source": self.ada, "target": self.id["Extra 1"], "type": flip[c % 2][1], "family": flip[c % 2][0],
                               "status": "stated", "by": "narrator", "quotes": []} for c in range(1, 7)]
        for n in range(1, 7):
            li = self.row(self.page(n, wiki), "Extra 1")
            marks = self.marks(li)
            self.assertEqual(marks[0], 1, n)
            self.assertLessEqual(len(marks), 5, n)
            self.assertTrue(all(m <= n for m in marks), n)
            self.assertTrue(all(float(x) <= 100 for x in re.findall(r"left:([\d.]+)%", li)), n)
        self.assertEqual(self.marks(self.row(self.page(6, wiki), "Extra 1")), [1, 3, 4, 5, 6])

    def test_a_suspected_role_says_who_suspects_it_beside_its_dashed_mark(self):
        wiki = json.loads(json.dumps(self.wiki))
        wiki["relations"].append({"chapter": 2, "source": self.id["Dee"], "target": self.ada, "type": "plots against", "family": "hostility",
                                  "status": "belief", "by": "Bea", "quotes": []})
        wiki["relations"] = [r for r in wiki["relations"] if not (r["source"] == self.ada and r["target"] == self.id["Dee"])]
        dee = self.row(self.page(3, wiki), "Dee")
        self.assertEqual(self.plain(dee), "Dee plots against Ada suspected by Bea since ch 2")
        self.assertIn('<i class="sus">suspected by Bea</i>', dee)
        self.assertIn('<b class="belief"', dee)
        for li in sum(self.sections(self.page(3, wiki)).values(), []):
            self.assertEqual('class="belief"' in li, "suspected" in li)
        cy = self.row(self.page(6), "Cy")
        self.assertNotIn("belief", cy)
        wiki["relations"].append({"chapter": 2, "source": self.ada, "target": self.id["Extra 2"], "type": "suspects", "family": "investigation",
                                  "status": "belief", "by": "Ada", "quotes": []})
        self.assertEqual(self.plain(self.row(self.page(3, wiki), "Extra 2")), "Ada suspects Extra 2 suspected +1 since ch 1")

    def test_a_section_shows_six_rows_and_the_rest_behind_show_all(self):
        hub = hub_wiki()
        box = self.page(6, hub, next(e["id"] for e in hub["entities"] if e["name"] == "Ada Hub"))
        allies = re.search(r"<h4>.*?Allies.*?</h4>(.*?)(?=<h4>|<div class=\"asof\">)", box, re.S).group(1)
        shown, rest = allies.split('<button type="button" class="disc"')
        self.assertEqual(len(re.findall(r"<li>", shown)), 6)
        self.assertIn('<span class="ifshut">Show all 25</span>', rest)
        self.assertRegex(rest, r'<div class="discbody" id="\w+" hidden><ul class="clist">')
        self.assertEqual(len(re.findall(r"<li>", rest)), 19)

    def test_the_drawing_waits_behind_a_button_after_the_list(self):
        box = self.page(6)
        self.assertLess(box.index('<ul class="clist">'), box.index("<svg"))
        self.assertRegex(box, r'<span class="ifshut">Show</span><span class="ifopen">Hide</span> drawing</span></button><div class="discbody" id="\w+" hidden><svg class="graph ego"')


RING = [("Celestial Worthy of Heaven and Earth for Blessings", "deity", "faith", 9, "prays to"),
        ("Klein Moretti", "character", "alliance", 8, "friend of"),
        ("Tingen Housing Improvement Association for the Working Class", "organization", "membership", 8, "member of"),
        ("Audrey Hall", "character", "alliance", 7, "friend of"),
        ("Leonard Mitchell", "character", "hostility", 7, "suspects"),
        ("Dunn Smith", "character", "service", 6, "serves"),
        ("Quintessential Divination and Arcane Arts of the Qin and Han Dynasty", "artifact", "ownership", 6, "owns"),
        ("Old Neil", "character", "teaching", 5, "taught by"),
        ("Benson Moretti", "character", "kin", 5, "brother of"),
        ("Melissa Moretti", "character", "kin", 4, "sister of"),
        ("Azik Eggers", "character", "teaching", 3, "taught by"),
        ("Alger Wilson", "character", "hostility", 2, "rival of"),
        ("Backlund Bridge District", "place", "place", 1, "lives in"),
        ("Tingen City", "place", "place", 1, "lives in"),
        ("Blue Mountain Spring", "place", "place", 1, "visits")]


def ring_wiki():
    names = [("Marguerite of the Long Watch", "character")] + [(n, t) for n, t, *_ in RING] + [("Small Fry", "character")]
    entities = [{"id": f"{i:08x}", "name": n, "name_chapter": 1, "type": t, "first": 1, "aliases": [], "blurbs": [[1, f"{n} is here."]]}
                for i, (n, t) in enumerate(names, 1)]
    ids = {e["name"]: e["id"] for e in entities}
    rel = lambda c, a, t, b, fam, status="stated": {"chapter": c, "source": ids[a], "target": ids[b], "type": t, "family": fam,
                                                    "status": status, "by": "Klein Moretti", "quotes": []}
    relations = [rel(c, "Marguerite of the Long Watch", verb, name, fam, "belief" if name == "Leonard Mitchell" else "stated")
                 for name, _, fam, k, verb in RING for c in range(1, k + 1)]
    relations += [rel(2, "Small Fry", "friend of", n, "alliance") for n in ("Klein Moretti", "Audrey Hall", "Dunn Smith")]
    return {"book": {"title": "Ring", "max": 10, "public_domain": False, "theme": {}, "power_types": [], "ladder": None},
            "chapters": [{"n": n, "title": str(n), "synopsis": ""} for n in range(1, 11)],
            "timelines": [{"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}],
            "entities": entities, "facts": [], "relations": relations, "questions": [], "ladders": [], "volumes": []}


@unittest.skipIf(NODE is None, "node is not installed")
class ConnectionsPanelTest(unittest.TestCase):
    FONT = {"lbl": 13, "me": 15}

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        cls.wiki = ring_wiki()
        cls.path = Path(cls.dir.name) / "wiki.json"
        cls.path.write_text(json.dumps(cls.wiki), encoding="utf-8")
        cls.id = {e["name"]: e["id"] for e in cls.wiki["entities"]}
        cls.centre = cls.id["Marguerite of the Long Watch"]
        proc = subprocess.run([NODE, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(cls.path),
                               f"{cls.centre}@10", f"{cls.id['Small Fry']}@10", f"links:e:{cls.centre}@10"],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        cls.out = json.loads(proc.stdout)
        cls.page = cls.out[f"{cls.centre}@10"]
        cls.svg = re.search(r'<svg class="graph ego".*?</svg>', cls.page, re.S).group(0)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def nodes(self):
        return {m.group(1): m.group(0) for m in re.finditer(r'<a [^>]*data-ent="(\w+)"[^>]*>.*?</a>', self.svg, re.S)}

    def lines(self, text):
        spans = re.findall(r"<tspan[^>]*>(.*?)</tspan>", text, re.S) or [re.sub(r"<title>.*?</title>|<[^>]+>", "", text)]
        return [html_lib.unescape(s).strip() for s in spans]

    def labels(self):
        return [m.groupdict() for m in re.finditer(r'<text class="(?P<cls>[^"]*)"(?P<attrs>[^>]*)>(?P<body>.*?)</text>', self.svg, re.S)]

    def box(self, label):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', label["attrs"]))
        size = self.FONT["me" if "me" in label["cls"].split() else "lbl"]
        ys = [float(y) for y in re.findall(r'<tspan[^>]*\by="([-\d.]+)"', label["body"])] or [float(attrs["y"])]
        width = max(len(line) for line in self.lines(label["body"])) * size * 0.6
        x = float(attrs["x"])
        left = {"start": x, "end": x - width, "middle": x - width / 2}[attrs.get("text-anchor", "start")]
        return left, min(ys) - size, left + width, max(ys) + size * 0.3

    def test_every_drawn_connection_is_named_beside_its_dot(self):
        nodes = self.nodes()
        self.assertEqual(len(nodes), 12)
        for name, *_ in RING[:12]:
            body = nodes[self.id[name]]
            text = " ".join(self.lines(re.search(r"<text[^>]*>(.*?)</text>", body, re.S).group(1)))
            if text.endswith("\u2026"):
                self.assertTrue(name.startswith(text[:-1].strip()), (name, text))
                self.assertIn(f"<title>{name}</title>", body)
            else:
                self.assertEqual(text, name)
            self.assertLessEqual(len(self.lines(re.search(r"<text[^>]*>(.*?)</text>", body, re.S).group(1))), 2)

    def test_no_two_labels_overlap(self):
        boxes = [self.box(label) for label in self.labels()]
        self.assertEqual(len(boxes), 13)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3], (a, b))

    def test_labels_sit_on_the_side_away_from_the_centre(self):
        around = [label for label in self.labels() if "me" not in label["cls"].split()]
        self.assertEqual(len(around), 12)
        for label in around:
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', label["attrs"]))
            x = float(attrs["x"])
            self.assertEqual(attrs["text-anchor"], "start" if x > 0 else "end")

    def test_the_centre_is_labelled_with_the_entrys_own_name(self):
        me = [label for label in self.labels() if "me" in label["cls"].split()]
        self.assertEqual([" ".join(self.lines(label["body"])) for label in me], ["Marguerite of the Long Watch"])

    def test_the_twelve_strongest_are_drawn_and_the_rest_link_to_the_graph(self):
        self.assertEqual(set(self.nodes()), {self.id[n] for n, *_ in RING[:12]})
        more = re.search(r'<a ([^>]*)>\+3 more', self.page)
        self.assertIsNotNone(more)
        self.assertIn(f'data-go="graph:{self.centre}"', more.group(1))

    def test_each_node_links_to_its_page_and_carries_the_relation_wording(self):
        rows = {r["ent"]: r for r in self.out[f"links:e:{self.centre}@10"]["rows"] if r["ent"]}
        for name, *_ in RING[:12]:
            self.assertEqual(rows[self.id[name]]["p"], f"e:{self.id[name]}")
        klein = self.nodes()[self.id["Klein Moretti"]]
        self.assertIn("Marguerite of the Long Watch is a friend of Klein Moretti, ch 1, 2, 3, 4, 5, 6, 7, 8", html_lib.unescape(klein))

    def test_spokes_carry_their_kind_and_a_belief_is_dashed(self):
        leonard, klein = self.nodes()[self.id["Leonard Mitchell"]], self.nodes()[self.id["Klein Moretti"]]
        self.assertIn("var(--r-conflict)", leonard)
        self.assertIn("belief", re.search(r'<path class="([^"]*spoke[^"]*)"', leonard).group(1).split())
        self.assertNotIn("belief", re.search(r'<path class="([^"]*spoke[^"]*)"', klein).group(1).split())

    def test_the_legend_lists_only_the_kinds_drawn(self):
        legend = re.search(r'<div class="egolegend">(.*?)</div>', self.page, re.S).group(1)
        kinds = [html_lib.unescape(k).strip() for k in re.findall(r"</i>([^<]+)", legend)]
        self.assertEqual(kinds, ["Close", "Allies", "Conflict", "Belonging", "Things & places", "Suspected"])

    def test_an_entry_with_three_connections_lists_them_without_a_drawing(self):
        page = self.out[f"{self.id['Small Fry']}@10"]
        box = re.search(r'<div class="egobox">.*', page, re.S).group(0)
        self.assertNotIn("<svg", box)
        for name in ("Klein Moretti", "Audrey Hall", "Dunn Smith"):
            self.assertIn(name, box)


if __name__ == "__main__":
    unittest.main()
