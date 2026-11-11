import copy
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from annalist.families import read_families, relation_family
from annalist.relation_precision import sample
from annalist.scorecard import score, states_the_tie, Wiki
from annalist.state import load_states
from tests.test_build import MiniBuild, build_script

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "tests" / "data" / "mini-gold.json"

STATUS_REPLIES = {
    "Sabine Oake": [{"value": "alive", "chapter": 1, "asserted_by": "narrator",
                     "quotes": ["Sabine Oake had been master of the Lamplighters’ Guild for eleven years."]}],
    "Bram Ostrow": [{"value": "alive", "chapter": 1, "asserted_by": "narrator",
                     "quotes": ["Bram was a journeyman of the Guild, two years older than Ines, and her oldest friend"]}],
    "Livia Hale": [{"value": "missing", "chapter": 2, "asserted_by": "narrator", "timeline": "gannet-night",
                    "quotes": ["The Guild entered Livia Hale’s name in the register of the drowned"]}],
}


def statuses_script():
    script = build_script()
    script["replies"] = [{"purpose": "profile", "contains": f'page about the character "{name}"', "reply": {"status": rows}}
                         for name, rows in STATUS_REPLIES.items()] + script["replies"]
    return script


def outcomes(items):
    return {i.id: i.outcome for i in items}


class EvalMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(statuses_script())
        cls.book.build()
        cls.proc = subprocess.run([sys.executable, "-m", "annalist", "eval", str(cls.book.workdir), str(GOLD)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
        cls.report = cls.book.json("eval.json")
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.gold = json.loads(GOLD.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def ids(self, outcome):
        return {i["id"] for i in self.report["items"] if i["outcome"] == outcome}

    def rescore(self, wiki):
        return outcomes(score(self.book.workdir, self.gold, wiki))

    def entity(self, wiki, name):
        return next(e for e in wiki["entities"] if e["name"] == name)

    def test_a_book_type_whose_parent_is_artifact_passes_where_the_gold_expects_an_artifact(self):
        self.assertEqual(self.wiki["book"]["parents"], {"ward": "artifact"})
        wiki = copy.deepcopy(self.wiki)
        self.entity(wiki, "Salt Ledger")["type"] = "ward"
        self.assertEqual(self.rescore(wiki)["entity:salt_ledger"], "pass")
        wiki["book"]["parents"] = {"ward": "concept"}
        self.assertEqual(self.rescore(wiki)["entity:salt_ledger"], "fail")

    def test_an_older_export_without_parents_gives_its_book_types_the_parent_their_name_names(self):
        wiki = copy.deepcopy(self.wiki)
        del wiki["book"]["parents"]
        wiki["book"]["power_types"] = ["warding item", "ward"]
        self.entity(wiki, "Salt Ledger")["type"] = "warding item"
        self.entity(wiki, "Gannet")["type"] = "ward"
        found = self.rescore(wiki)
        self.assertEqual((found["entity:salt_ledger"], found["entity:gannet"]), ("pass", "fail"))

    def test_the_mini_built_from_its_expected_extractions_passes_every_scored_item(self):

        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertEqual(self.ids("fail"), set())
        reveal = next(i for i in self.report["items"] if i["id"] == "reveal:livia:Sister Wren")
        self.assertIn("linked from ch4", reveal["detail"])

    def test_sister_wren_keeps_her_own_page_until_chapter_4_names_her_livia_hale(self):
        wiki = Wiki(self.wiki)
        livia, wren = self.entity(self.wiki, "Livia Hale"), self.entity(self.wiki, "Sister Wren")
        self.assertEqual(wren["merged"], {"into": livia["id"], "chapter": 4})
        self.assertEqual({a["name"]: a["chapter"] for a in livia["aliases"]}, {"Sister Wren": 4, "Wren": 4})
        self.assertFalse([text for _, text in wiki.page(livia["id"], 3) if "Wren" in text])
        self.assertIn("Sister Wren is the abbey's archivist", " ".join(text for _, text in wiki.page(wren["id"], 3)))
        self.assertIn("Sister Wren is the abbey's archivist", " ".join(text for _, text in wiki.page(livia["id"], 4)))
        self.assertTrue(wiki.visible(wren["id"], 3))
        self.assertFalse(wiki.visible(wren["id"], 4))

    def test_the_site_shows_sister_wren_apart_until_chapter_4_then_on_livia_hales_page(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        livia, wren = self.entity(self.wiki, "Livia Hale")["id"], self.entity(self.wiki, "Sister Wren")["id"]
        proc = subprocess.run([node, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"),
                               str(self.book.workdir / "site" / "data" / "wiki.json"), f"{livia}@3", f"{wren}@3", f"{wren}@4"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pages = {k: re.sub(r"<[^>]+>", " ", v) for k, v in json.loads(proc.stdout).items()}
        self.assertNotIn("Wren", pages[f"{livia}@3"])
        self.assertIn("Sister Wren", pages[f"{wren}@3"])
        self.assertIn("Facts (1)", pages[f"{wren}@3"])
        self.assertIn("Livia Hale", pages[f"{wren}@4"])
        self.assertIn("Facts (9)", pages[f"{wren}@4"])

    def test_the_load_at_each_chapter_and_the_site_agree_on_which_pages_exist(self):
        wiki = Wiki(self.wiki)
        for n in range(1, 6):
            shown = {e["name"] for eid, e in wiki.all.items() if wiki.visible(eid, n)}
            self.assertEqual(shown, set(load_states(self.book.workdir, until=n).entities), f"chapter {n}")

    def test_a_page_starts_at_the_first_chapter_whose_text_names_it_even_when_the_read_listed_it_later(self):
        late = self.book.root / "late"
        shutil.copytree(self.book.workdir, late)
        entities = json.loads((late / "entities.json").read_text(encoding="utf-8"))
        quay = next(e for e in entities if e["name"] == "Corvel Quay")
        self.assertEqual(quay["first_chapter"], 1)
        quay["first_chapter"] = 4
        (late / "entities.json").write_text(json.dumps(entities), encoding="utf-8")
        proc = subprocess.run([sys.executable, "-m", "annalist", "export", str(late), str(late / "site")],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        exported = json.loads((late / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        self.assertEqual(self.entity(exported, "Corvel Quay")["first"], 1)

    def test_a_death_set_in_a_flashback_holds_in_the_present_until_the_character_speaks_there(self):
        wiki = copy.deepcopy(self.wiki)
        bram = self.entity(wiki, "Bram Ostrow")
        bram["profile"]["fields"]["status"] = [{"chapter": 2, "value": "dead", "quotes": ["q"], "timeline": "gannet-night"}]
        bram["profile"]["spoke"] = [[4, "main"]]
        found = Wiki(wiki)
        self.assertEqual(found.status(bram["id"], 3)["value"], "dead")
        self.assertEqual(found.status(bram["id"], 4)["value"], "alive")
        node = shutil.which("node")
        if node is None:
            return
        path = self.book.root / "flashback-death.json"
        path.write_text(json.dumps(wiki), encoding="utf-8")
        proc = subprocess.run([node, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(path),
                               f"{bram['id']}@3", f"{bram['id']}@4"], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        pages = json.loads(proc.stdout)
        self.assertRegex(pages[f"{bram['id']}@3"], r"<th>Status</th><td>Dead")
        self.assertRegex(pages[f"{bram['id']}@4"], r"<th>Status</th><td>Alive")

    def test_a_merge_dated_before_the_reveal_is_caught(self):
        wiki = copy.deepcopy(self.wiki)
        self.entity(wiki, "Sister Wren")["merged"]["chapter"] = 3
        self.assertEqual(self.rescore(wiki)["reveal:livia:Sister Wren"], "fail")

    def test_every_gold_entity_status_and_relation_is_scored(self):
        scored = self.ids("pass") | self.ids("fail")
        self.assertTrue({f"entity:{e['id']}" for e in self.gold["entities"]} <= scored)
        self.assertTrue({f"relation:{r['source']}-{r['type']}-{r['target']}" for r in self.gold["relations"]} <= scored)
        self.assertEqual(len([i for i in scored if i.startswith("status:")]), 8)
        self.assertEqual(self.report["totals"]["entities"]["score"], 1.0)

    def test_a_ship_status_is_reported_as_not_scored(self):
        self.assertIn("status:gannet@2", self.ids("not_scored"))

    def test_a_merge_through_the_captain_title_is_caught(self):
        wiki = copy.deepcopy(self.wiki)
        odile, fenn = self.entity(wiki, "Odile Marr"), self.entity(wiki, "Captain Fenn")
        odile["aliases"].append({"name": "Captain Fenn", "chapter": 3})
        wiki["entities"].remove(fenn)
        for row in wiki["facts"] + wiki["relations"]:
            for key in ("entity", "source", "target"):
                if row.get(key) == fenn["id"]:
                    row[key] = odile["id"]
        self.assertEqual(outcomes(score(self.book.workdir, self.gold, self.wiki))["merge:the Captain"], "pass")
        found = self.rescore(wiki)
        self.assertEqual(found["merge:the Captain"], "fail")
        self.assertEqual(found["entity:fenn"], "fail")

    def test_a_bare_title_alias_is_caught_even_without_a_merge(self):
        wiki = copy.deepcopy(self.wiki)
        self.entity(wiki, "Captain Fenn")["aliases"].append({"name": "the Captain", "chapter": 3})
        self.assertEqual(self.rescore(wiki)["merge:the Captain"], "fail")

    def test_a_reveal_leaked_in_a_fact_before_its_chapter_is_caught(self):
        wiki = copy.deepcopy(self.wiki)
        sabine = self.entity(wiki, "Sabine Oake")
        wiki["facts"].append({"id": "F-leak", "chapter": 3, "entity": sabine["id"], "claim": "Sabine was the person in the lamp room.",
                              "status": "stated", "by": "narrator", "quotes": []})
        self.assertEqual(self.rescore(wiki)["reveal:sabine:the person in the lamp room"], "fail")

    def test_a_reveal_in_a_fact_dated_at_its_chapter_is_not_a_leak(self):
        wiki = copy.deepcopy(self.wiki)
        sabine = self.entity(wiki, "Sabine Oake")
        wiki["facts"].append({"id": "F-late", "chapter": 5, "entity": sabine["id"], "claim": "Sabine was the person in the lamp room.",
                              "status": "stated", "by": "narrator", "quotes": []})
        found = {i.id: i for i in score(self.book.workdir, self.gold, wiki)}
        self.assertEqual(found["reveal:sabine:the person in the lamp room"].outcome, "pass")
        self.assertIn("linked from ch5", found["reveal:sabine:the person in the lamp room"].detail)
        self.assertIn("never linked", {i.id: i for i in score(self.book.workdir, self.gold, self.wiki)}["reveal:sabine:the person in the lamp room"].detail)

    def test_a_wrong_status_is_caught(self):
        wiki = copy.deepcopy(self.wiki)
        tomas = self.entity(wiki, "Tomas Hale")
        tomas["profile"]["fields"]["status"] = [{**o, "value": "alive"} for o in tomas["profile"]["fields"]["status"]]
        self.assertEqual(outcomes(score(self.book.workdir, self.gold, self.wiki))["status:tomas@3"], "pass")
        self.assertEqual(self.rescore(wiki)["status:tomas@3"], "fail")

    def test_a_status_before_a_merge_is_read_from_the_page_the_gold_name_leads_to(self):
        gold = copy.deepcopy(self.gold)
        next(s for s in gold["statuses"] if s["entity"] == "livia")["timeline"].append({"chapter": 3, "status": "alive"})
        self.assertEqual(outcomes(score(self.book.workdir, gold, self.wiki))["status:livia@3"], "fail")
        livia = next(e for e in gold["entities"] if e["id"] == "livia")
        livia["name"], livia["aliases"] = "Sister Wren", ["Livia Hale", "Wren"]
        found = {i.id: i for i in score(self.book.workdir, gold, self.wiki)}
        self.assertEqual(found["status:livia@3"].outcome, "pass")
        self.assertIn("infobox on \"Sister Wren\" at ch3: alive", " ".join(found["status:livia@3"].evidence))
        self.assertEqual(found["status:livia@4"].outcome, "pass")

    def test_a_relation_shown_before_the_text_reveals_it_is_caught(self):
        wiki = copy.deepcopy(self.wiki)
        enemy = next(r for r in wiki["relations"] if r["type"] == "enemy of")
        wiki["relations"].append({**enemy, "chapter": 1})
        found = self.rescore(wiki)
        self.assertEqual(found["relation:bram-enemy_of-ines"], "pass")
        self.assertEqual(found["early:relation:bram-enemy_of-ines"], "fail")

    def test_another_tie_of_the_same_colour_shown_early_does_not_reveal_the_relation(self):
        wiki = copy.deepcopy(self.wiki)
        enemy = next(r for r in wiki["relations"] if r["type"] == "enemy of")
        wiki["relations"].append({**enemy, "chapter": 1, "type": "quarrels with", "family": "hostility"})
        self.assertEqual(self.rescore(wiki)["early:relation:bram-enemy_of-ines"], "pass")

    def test_a_family_tie_worded_differently_before_the_text_reveals_it_is_caught(self):
        wiki = copy.deepcopy(self.wiki)
        daughter = next(r for r in wiki["relations"] if r["type"] == "daughter of")
        wiki["relations"].append({**daughter, "chapter": 1, "type": "child of", "family": "kin"})
        gold = copy.deepcopy(self.gold)
        next(r for r in gold["relations"] if r["type"] == "daughter_of")["first_chapter"] = 4
        found = outcomes(score(self.book.workdir, gold, wiki))
        self.assertEqual(found["early:relation:livia-daughter_of-tomas"], "fail")

    def test_a_second_page_named_by_a_reveal_alias_counts_against_precision(self):
        wiki = copy.deepcopy(self.wiki)
        wiki["entities"].append({**self.entity(wiki, "Captain Fenn"), "id": "wren0000", "name": "Sister Wren", "name_chapter": 3,
                                 "first": 3, "aliases": []})
        self.assertEqual(self.rescore(wiki)["wiki:Sister Wren"], "fail")

    def test_a_relation_worded_as_a_near_synonym_still_matches_its_family(self):
        wiki = copy.deepcopy(self.wiki)
        friend = next(r for r in wiki["relations"] if r["type"] == "friend of")
        friend["type"], friend["family"] = "collaborator of", relation_family("collaborator of")
        self.assertEqual(self.rescore(wiki)["relation:bram-friend_of-ines"], "pass")

    def reworded(self, wording):
        wiki = copy.deepcopy(self.wiki)
        sabine, guild = self.entity(wiki, "Sabine Oake")["id"], self.entity(wiki, "Lamplighters’ Guild")["id"]
        for r in wiki["relations"]:
            if {r["source"], r["target"]} == {sabine, guild}:
                r["type"], r["family"] = wording, relation_family(wording, read_families(self.book.workdir))
        return wiki

    def test_a_relation_matches_only_when_the_site_colours_it_with_the_gold_wordings_family(self):
        self.assertEqual(self.rescore(self.reworded("keeper of"))["relation:sabine-master_of-guild"], "pass")
        found = {i.id: i for i in score(self.book.workdir, self.gold, self.reworded("leads"))}
        self.assertEqual(found["relation:sabine-master_of-guild"].outcome, "fail")
        self.assertIn("leads, coloured membership", " ".join(found["relation:sabine-master_of-guild"].evidence))

    def test_a_reading_of_the_gold_wording_is_the_family_the_wiki_must_show(self):
        path = self.book.workdir / "families.json"
        kept = path.read_text(encoding="utf-8")
        try:
            readings = {**read_families(self.book.workdir), "master of [organization]": "membership", "leads [organization]": "membership"}
            path.write_text(json.dumps({"readings": readings}), encoding="utf-8")
            self.assertEqual(self.rescore(self.reworded("leads"))["relation:sabine-master_of-guild"], "pass")
        finally:
            path.write_text(kept, encoding="utf-8")

    def test_chapters_numbered_differently_from_the_gold_stop_the_scoring(self):
        gold = copy.deepcopy(self.gold)
        gold["chapters"][0], gold["chapters"][1] = {**gold["chapters"][0], "href": gold["chapters"][1]["href"]}, {**gold["chapters"][1], "href": gold["chapters"][0]["href"]}
        items = score(self.book.workdir, gold, self.wiki)
        self.assertEqual({i.id for i in items if i.outcome == "fail"}, {"chapter:1", "chapter:2"})
        self.assertFalse([i for i in items if i.section == "entities"])

    def test_a_gold_marked_partial_scores_a_run_that_has_chapters_past_its_last(self):
        gold = copy.deepcopy(self.gold)
        gold["chapters"] = gold["chapters"][:3]
        whole = outcomes(score(self.book.workdir, gold, self.wiki))
        self.assertEqual(whole["chapter:extra"], "fail")
        partial = outcomes(score(self.book.workdir, {**gold, "partial": True}, self.wiki))
        self.assertNotIn("chapter:extra", partial)
        self.assertEqual({k: v for k, v in partial.items() if k.startswith("chapter:")}, {"chapter:1": "pass", "chapter:2": "pass", "chapter:3": "pass"})


class RelationPrecisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = statuses_script()
        cls.book = MiniBuild(script)
        cls.book.build()
        cls.calls_after_build = len(cls.book.calls())
        cls.plain = cls.eval_run("plain")
        cls.calls_after_plain = len(cls.book.calls())
        judge = [{"purpose": "judge", "contains": '"Bram Ostrow" enemy of',
                  "reply": {"verdict": "wrong", "reasoning": "The passage shows a quarrel, not enmity."}},
                 {"purpose": "judge", "reply": {"verdict": "correct", "reasoning": "The passage states it."}}]
        cls.book.script({**script, "replies": judge + script["replies"]})
        cls.wiki = cls.book.json("site/data/wiki.json")

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    @classmethod
    def eval_run(cls, name, *flags):
        out = cls.book.root / name
        out.mkdir()
        cls.book.run_annalist("eval", str(cls.book.workdir), str(GOLD), "--out", str(out), *flags)
        return json.loads((out / "eval.json").read_text(encoding="utf-8")), (out / "eval.md").read_text(encoding="utf-8")

    def test_eval_without_a_relation_sample_makes_no_llm_call(self):
        self.assertEqual(self.calls_after_plain, self.calls_after_build)
        self.assertNotIn("relation_precision", self.plain[0])
        self.assertNotIn("relation_precision", self.plain[1])

    def test_a_sample_judges_the_requested_number_of_relations_and_a_rerun_is_free_and_identical(self):
        report, text = self.eval_run("three", "--relation-sample", "3", "--judge-model", "judge-model-x")
        section = report["relation_precision"]
        self.assertEqual(len(section["rows"]), 3)
        self.assertEqual(section["totals"]["sampled"], 3)
        self.assertEqual(section["judge_model"], "judge-model-x")
        self.assertEqual({c["model"] for c in self.book.calls("judge")}, {"judge-model-x"})
        self.assertIn("## relation_precision", text)
        calls = len(self.book.calls("judge"))
        again, _ = self.eval_run("three-again", "--relation-sample", "3", "--judge-model", "judge-model-x")
        self.assertEqual([r["key"] for r in again["relation_precision"]["rows"]], [r["key"] for r in section["rows"]])
        self.assertEqual(len(self.book.calls("judge")), calls)
        self.assertEqual(again["relation_precision"]["judge_spend_usd"], 0)

    def test_precision_counts_the_judges_verdicts_and_keeps_the_reason_and_quote_of_each_row(self):
        report, text = self.eval_run("all", "--relation-sample", "1000")
        section = report["relation_precision"]
        total = section["totals"]["relations"]
        self.assertEqual(section["totals"]["sampled"], total)
        self.assertEqual((section["totals"]["correct"], section["totals"]["wrong"]), (total - 1, 1))
        self.assertEqual(section["totals"]["precision"], round((total - 1) / total, 3))
        wrong = next(r for r in section["rows"] if r["verdict"] == "wrong")
        self.assertEqual((wrong["source"], wrong["type"]), ("Bram Ostrow", "enemy of"))
        self.assertEqual(wrong["reason"], "The passage shows a quarrel, not enmity.")
        self.assertTrue(wrong["quotes"])
        self.assertIn(f"- **wrong** `{wrong['key']}`: The passage shows a quarrel, not enmity.", text)

    def test_the_sample_keeps_its_rows_when_the_wiki_gains_or_loses_a_relation_outside_it(self):
        wiki = Wiki(self.wiki)
        total, picked = sample(wiki, 3)
        keys = [k for k, _ in picked]
        self.assertGreater(total, 4)
        self.assertTrue(set(keys) <= {k for k, _ in sample(wiki, 5)[1]})
        outside = next(r for r in self.wiki["relations"] if r not in [p for _, p in picked])
        fewer = copy.deepcopy(self.wiki)
        fewer["relations"].remove(outside)
        self.assertEqual([k for k, _ in sample(Wiki(fewer), 3)[1]], keys)
        more = copy.deepcopy(self.wiki)
        more["relations"].append({**outside, "type": "rival of"})
        self.assertGreaterEqual(len(set(keys) & {k for k, _ in sample(Wiki(more), 3)[1]}), 2)


class StagedTieTest(unittest.TestCase):
    def test_an_engagement_does_not_state_a_marriage_but_a_husband_does(self):
        self.assertFalse(states_the_tie("married_to", {"type": "engaged to", "family": "romance"}, {}))
        self.assertFalse(states_the_tie("engaged_to", {"type": "in love with", "family": "romance"}, {}))
        self.assertTrue(states_the_tie("married_to", {"type": "husband of", "family": "romance"}, {}))
        self.assertTrue(states_the_tie("in_love_with", {"type": "admires", "family": "romance"}, {}))


if __name__ == "__main__":
    unittest.main()
