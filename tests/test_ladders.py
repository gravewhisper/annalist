import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from annalist.files import read_jsonl, write_json
from annalist.ladders import generate_ladder
from annalist.pages import PageName, group_titles
from annalist.state import Knowledge
from tests.test_build import LATER_REPLIES, MiniBuild, plan_rows, ran, ROOT, site_views

DATA = ROOT / "tests" / "data"
EPUB = DATA / "ladder.epub"
NODE = shutil.which("node")

SPEC = {"group_type": "sect", "step_type": "realm", "rank": "order", "direction": "ascending",
        "note": "Each sect trains its students through its own realms, first to highest."}

SEED = {"power_system": "Students of a sect rise through its realms by breathing heat into the body.",
        "power_types": {"sect": "A school of cultivation with its own realms.",
                        "realm": "A named stage of cultivation within a sect.",
                        "technique": "A specific breathing or fighting method."},
        "relation_example": "first realm of", "extra_fields": {}, "power_keywords": ["realm", "sect", "warmth", "breath", "cultivat"],
        "timeline_kind": "linear", "timeline_note": "The story runs in order through one year on the mountain.",
        "complete": False, "backend": {"name": "fake", "script": "script.json"}}

QUOTES = {
    "Ashwalker": (2, "Ashwalker is the name of our sect, and Ashwalker is also the name of its first realm."),
    "Emberheart": (3, "Emberheart is the second realm of Ashwalker"),
    "Pyre Sovereign": (4, "The Pyre Sovereign is the third realm of Ashwalker"),
    "Clear Pane": (3, "Clear Pane is the first realm of the Glass Lantern Sect."),
    "Dusk Listener": (5, "Dusk Listener is the first realm of the Vesper Hollow"),
}
OLDER_SECT = "its first realm is the Dusk Listener"


def step(entry, rank, quote=None):
    chapter, text = QUOTES.get(entry, (3, None))
    return {"entry": entry, "rank": rank, "chapter": chapter, "quote": quote or text}


LADDERS_REPLY = {"ladders": [
    {"group": "Ashwalker", "steps": [step("Pyre Sovereign", 3), step("Ashwalker", 1), step("Emberheart", 2)]},
    {"group": "Glass Lantern Sect", "steps": [step("Clear Pane", 1),
                                              step("Prism Warden", 2, "Prism Warden is the second realm of the Glass Lantern Sect.")]},
    {"group": "Vesper Hollow", "steps": [step("Dusk Listener", 1)]},
    {"group": "Dusk Listener", "steps": [step("Dusk Listener", 1, OLDER_SECT)]},
]}


def ladder_script():
    extractions = json.loads((DATA / "ladder-extractions.json").read_text(encoding="utf-8"))
    replies = []
    for key, ext in extractions.items():
        ids = [f"F{i}" for i in range(1, len(ext["facts"]) + 1)] + [f"R{i}" for i in range(1, len(ext["relations"]) + 1)]
        replies += [{"purpose": "extract", "chapter": int(key), "reply": ext},
                    {"purpose": "support", "chapter": int(key), "reply": {"verdicts": [{"id": i, "verdict": "supported"} for i in ids]}}]
    replies += [{"purpose": "ladder-spec", "reply": {"ladder": {**SPEC, "step_type": "disciple"}}},
                {"purpose": "ladder-spec", "reply": {"ladder": SPEC}},
                {"purpose": "ladders", "reply": LADDERS_REPLY}]
    replies += [{"purpose": p, "reply": r} for p, r in LATER_REPLIES.items() if p != "book"]
    return {"replies": replies}


class LadderBuild(MiniBuild):
    def build(self, *extra, check=True):
        proc = subprocess.run([sys.executable, "-m", "annalist", "build", str(EPUB), str(self.workdir), "--yes", *extra],
                              cwd=self.code, env=self.env, capture_output=True, text=True, timeout=300)
        if check and proc.returncode:
            raise AssertionError(f"build exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc


class LadderBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = LadderBuild(ladder_script())
        (cls.book.workdir / "book.json").write_text(json.dumps(SEED, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cls.first = cls.book.build()
        cls.wiki = cls.book.json("site/data/wiki.json")
        cls.entries = {(e["name"], e["type"]): e for e in cls.wiki["entities"]}
        cls.id = {key: e["id"] for key, e in cls.entries.items()}

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def site(self, *views, wiki=None):
        path = self.book.workdir / "site" / "data" / "wiki.json"
        if wiki is not None:
            path = self.book.root / "reordered-wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
        return site_views(path, *views)

    def heading(self, html):
        return re.search(r"<h1>(.*?)</h1>", html).group(1)

    def test_the_ladder_and_the_epub_title_are_the_only_keys_added_to_an_existing_book_json(self):
        self.assertEqual((self.book.workdir / "book.json").read_text(encoding="utf-8"),
                         json.dumps({**SEED, "ladder": SPEC, "title": "The Ash Gate"}, ensure_ascii=False, indent=2) + "\n")
        self.assertEqual(self.book.calls("book"), [])

    def test_a_ladder_naming_a_type_outside_the_power_types_is_asked_again(self):
        calls = self.book.calls("ladder-spec")
        self.assertEqual(len(calls), 2)
        self.assertIn("disciple", calls[0]["error"])
        self.assertIsNone(calls[1]["error"])

    def test_a_group_and_a_step_with_the_same_name_are_two_entries_with_their_own_ids(self):
        realm, sect = self.entries[("Ashwalker", "realm")], self.entries[("Ashwalker Sect", "sect")]
        self.assertNotEqual(realm["id"], sect["id"])
        self.assertEqual((realm["first"], sect["first"]), (1, 2))
        claims = {f["entity"]: f["claim"] for f in self.wiki["facts"] if f["chapter"] == 2 and "fourteen students" in f["claim"]}
        self.assertEqual(list(claims), [sect["id"]])

    def test_a_group_named_after_its_first_step_is_titled_with_the_group_word_as_the_book_writes_it(self):
        realm, sect = self.id[("Ashwalker", "realm")], self.id[("Ashwalker Sect", "sect")]
        pages = self.site(f"{realm}@1", f"{realm}@5", f"{sect}@5")
        self.assertEqual(self.heading(pages[f"{realm}@1"]), "Ashwalker")
        self.assertEqual(self.heading(pages[f"{realm}@5"]), "Ashwalker")
        self.assertEqual(self.heading(pages[f"{sect}@5"]), "Ashwalker Sect")

    def test_search_shows_a_shared_name_qualified_without_repeating_it(self):
        results = self.site("search:Ashwalker@5")["search:Ashwalker@5"]
        self.assertIn("<span>Ashwalker</span>", results)
        self.assertIn("<span>Ashwalker Sect</span>", results)
        self.assertNotIn("(", results)

    def test_a_shared_name_in_text_links_to_the_step_whichever_entry_comes_first(self):
        for wiki in (None, {**self.wiki, "entities": self.wiki["entities"][::-1]}):
            synopsis = re.search(r'<div class="ccard full">.*?<p>(.*?)</p>', self.site("chapter:2@5", wiki=wiki)["chapter:2@5"]).group(1)
            self.assertIn(f'data-ent="{self.id[("Ashwalker", "realm")]}"', synopsis)
            self.assertNotIn(f'data-ent="{self.id[("Ashwalker Sect", "sect")]}"', synopsis)

    def test_ladders_json_ranks_each_groups_verified_steps_with_chapter_and_quote(self):
        self.assertEqual(self.book.json("ladders.json"), [
            {"group": "Ashwalker (sect)", "group_type": "sect", "chapter": 2,
             "steps": [{"entry": "Ashwalker", "rank": 1, "chapter": 2, "quote": QUOTES["Ashwalker"][1]},
                       {"entry": "Emberheart", "rank": 2, "chapter": 3, "quote": QUOTES["Emberheart"][1]},
                       {"entry": "Pyre Sovereign", "rank": 3, "chapter": 4, "quote": QUOTES["Pyre Sovereign"][1]}]},
            {"group": "Glass Lantern Sect", "group_type": "sect", "chapter": 3,
             "steps": [{"entry": "Clear Pane", "rank": 1, "chapter": 3, "quote": QUOTES["Clear Pane"][1]}]},
            {"group": "Dusk Listener", "group_type": "sect", "chapter": 5,
             "steps": [{"entry": "Dusk Listener", "rank": 1, "chapter": 5, "quote": OLDER_SECT}]},
            {"group": "Vesper Hollow", "group_type": "sect", "chapter": 5,
             "steps": [{"entry": "Dusk Listener", "rank": 1, "chapter": 5, "quote": QUOTES["Dusk Listener"][1]}]},
        ])

    def test_wiki_json_carries_each_ladder_by_id_with_ranks_and_chapters(self):
        i = self.id
        self.assertEqual(self.wiki["ladders"], [
            {"group": i[("Ashwalker Sect", "sect")], "chapter": 2,
             "steps": [{"id": i[("Ashwalker", "realm")], "rank": 1, "chapter": 2}, {"id": i[("Emberheart", "realm")], "rank": 2, "chapter": 3},
                       {"id": i[("Pyre Sovereign", "realm")], "rank": 3, "chapter": 4}]},
            {"group": i[("Glass Lantern Sect", "sect")], "chapter": 3, "steps": [{"id": i[("Clear Pane", "realm")], "rank": 1, "chapter": 3}]},
            {"group": i[("Dusk Listener Sect", "sect")], "chapter": 5, "steps": [{"id": i[("Dusk Listener", "realm")], "rank": 1, "chapter": 5}]},
            {"group": i[("Vesper Hollow Sect", "sect")], "chapter": 5, "steps": [{"id": i[("Dusk Listener", "realm")], "rank": 1, "chapter": 5}]},
        ])
        self.assertEqual(self.wiki["book"]["ladder"], SPEC)

    def test_each_step_links_to_its_group_from_its_evidence_chapter(self):
        name = {e["id"]: e["name"] for e in self.wiki["entities"]}
        links = sorted((r["chapter"], name[r["source"]], r["type"], name[r["target"]]) for r in self.wiki["relations"] if r["type"].startswith("realm "))
        self.assertEqual({r["family"] for r in self.wiki["relations"] if r["type"].startswith("realm ")}, {"kind"})
        self.assertEqual(links, [(2, "Ashwalker", "realm 1 of", "Ashwalker Sect"), (3, "Clear Pane", "realm 1 of", "Glass Lantern Sect"),
                                 (3, "Emberheart", "realm 2 of", "Ashwalker Sect"), (4, "Pyre Sovereign", "realm 3 of", "Ashwalker Sect"),
                                 (5, "Dusk Listener", "realm 1 of", "Dusk Listener Sect"), (5, "Dusk Listener", "realm 1 of", "Vesper Hollow Sect")])

    def test_a_group_the_evidence_names_but_no_entry_holds_becomes_an_entry_dated_at_its_evidence(self):
        hollow = self.entries[("Vesper Hollow Sect", "sect")]
        self.assertEqual(hollow["first"], 5)
        self.assertNotIn(("Vesper Hollow", "uncategorized"), self.entries)
        self.assertEqual(self.site(f"{hollow['id']}@4")[f"{hollow['id']}@4"].count("Not yet introduced"), 1)

    def test_a_group_the_ladder_stage_creates_under_a_steps_name_gets_its_own_entry(self):
        realm, sect = self.entries[("Dusk Listener", "realm")], self.entries[("Dusk Listener Sect", "sect")]
        self.assertNotEqual(realm["id"], sect["id"])
        self.assertEqual(sect["first"], 5)
        page = self.site(f"{sect['id']}@5")[f"{sect['id']}@5"]
        self.assertEqual(self.heading(page), "Dusk Listener Sect")

    def test_a_step_whose_quote_does_not_verify_stays_out_of_the_ladder(self):
        warden = self.id[("Prism Warden", "realm")]
        self.assertNotIn(warden, [s["id"] for ladder in self.wiki["ladders"] for s in ladder["steps"]])
        self.assertNotIn(warden, [r["source"] for r in self.wiki["relations"]])

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_category_page_lists_each_ladder_in_rank_order_up_to_the_chapter(self):
        pages = self.site("route:cat:sect@3", "route:cat:sect@5")
        before, after = (re.sub(r"<[^>]+>", " ", pages[k]["html"]) for k in ("route:cat:sect@3", "route:cat:sect@5"))
        self.assertNotIn("Pyre Sovereign", before)
        self.assertNotIn("Vesper Hollow", before)
        self.assertRegex(before, r"Ashwalker Sect\s+Realm 1\s+Ashwalker\s.*Emberheart")
        self.assertRegex(after, r"Ashwalker Sect\s+Realm 1\s+Ashwalker\s.*Emberheart.*Pyre Sovereign")
        self.assertRegex(after, r"Vesper Hollow.*Dusk Listener")

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_the_group_page_shows_its_ladder(self):
        sect = self.id[("Ashwalker Sect", "sect")]
        page = re.sub(r"<[^>]+>", " ", self.site(f"{sect}@5")[f"{sect}@5"])
        self.assertRegex(page, r"1\s+Ashwalker\s.*2\s+Emberheart.*3\s+Pyre Sovereign")

    def test_a_sect_named_after_its_first_realm_takes_the_group_word_so_the_two_titles_differ(self):
        index = (self.book.workdir / "wiki" / "index.md").read_text(encoding="utf-8")
        self.assertIn("[Ashwalker](realm/ashwalker.md)", index)
        self.assertIn("[Ashwalker Sect](sect/ashwalker-sect.md)", index)

    def test_a_second_build_finds_the_ladder_current(self):
        second = self.book.build()
        self.assertEqual(ran(second.stdout), [])
        self.assertEqual(plan_rows(second.stdout)["ladders"], "done")


class SameNameEntriesTest(unittest.TestCase):
    def kb(self, ladder):
        kb = Knowledge(ladder)
        kb.upsert_entity({"name": "Ashwalker", "type": "realm"}, 1)
        kb.upsert_entity({"name": "Ashwalker", "type": "sect"}, 2)
        kb.upsert_entity({"name": "Ashwalker", "type": "sect", "summary": "The sect of the mountain."}, 3)
        return kb

    def test_a_group_and_a_step_of_one_name_stay_apart_when_the_book_has_that_ladder(self):
        kb = self.kb(SPEC)
        self.assertEqual({k: e["type"] for k, e in kb.entities.items()}, {"Ashwalker": "realm", "Ashwalker (sect)": "sect"})
        self.assertEqual(kb.entities["Ashwalker (sect)"]["summary"], "The sect of the mountain.")
        self.assertEqual((kb.resolve("Ashwalker"), kb.resolve("Ashwalker", "sect")), ("Ashwalker", "Ashwalker (sect)"))

    def test_without_a_ladder_one_name_stays_one_entry(self):
        self.assertEqual(list(self.kb(None).entities), ["Ashwalker"])

    def test_a_group_written_with_the_group_word_and_one_named_like_its_step_are_one_entry(self):
        for order in ([("Ashwalker", "realm"), ("Ashwalker sect", "sect"), ("Ashwalker", "sect")],
                      [("Ashwalker", "realm"), ("Ashwalker", "sect"), ("Ashwalker sect", "sect")]):
            kb = Knowledge(SPEC)
            for n, (name, etype) in enumerate(order, 1):
                kb.upsert_entity({"name": name, "type": etype}, n)
            self.assertEqual(sorted((k, e["type"]) for k, e in kb.entities.items()),
                             [("Ashwalker", "realm"), (order[1][0] if order[1][1] == "sect" and order[1][0] != "Ashwalker" else "Ashwalker (sect)", "sect")])
            self.assertEqual(kb.resolve("Ashwalker", "sect"), kb.resolve("Ashwalker sect", "sect"))

    def test_every_group_takes_the_group_word_once_most_groups_are_titled_with_it(self):
        kb = Knowledge(SPEC)
        for name, etype in (("Ashwalker", "realm"), ("Ashwalker", "sect"), ("Glass Lantern Sect", "sect"), ("Vesper Hollow", "sect"),
                            ("Tide Sect", "sect"), ("Rook (sect)", "sect")):
            kb.upsert_entity({"name": name, "type": etype}, 1)
        names = {k: PageName(k, e.get("written", k), 1, 1, []) for k, e in kb.entities.items()}
        group_titles(kb, names)
        self.assertEqual(sorted(names[k].name for k, e in kb.entities.items() if e["type"] == "sect"),
                         ["Ashwalker Sect", "Glass Lantern Sect", "Rook Sect", "Tide Sect", "Vesper Hollow Sect"])
        self.assertEqual(names["Vesper Hollow"].aliases, [{"name": "Vesper Hollow", "chapter": 1}])
        self.assertEqual(names["Ashwalker (sect)"].aliases, [])

    def test_types_outside_the_ladder_keep_sharing_one_entry(self):
        kb = self.kb(SPEC)
        kb.upsert_entity({"name": "Ashwalker", "type": "place"}, 4)
        self.assertEqual(sorted(kb.entities), ["Ashwalker", "Ashwalker (sect)"])


class LadderSpecMaterialTest(unittest.TestCase):
    def test_a_note_naming_ranks_the_order_and_types_never_show_is_sent_back(self):
        book = {"title": "Wardens", "backend": {"name": "fake", "script": "script.json"},
                "power_system": "Wardens of the harbour guilds rise through numbered circles.",
                "power_types": {"guild": {"parent": "organization", "description": "a guild of wardens with its own circles"},
                                "circle": {"parent": "concept", "description": "a numbered circle of a guild, such as Circle 7 or Circle 5"}}}
        unshown = {"group_type": "guild", "step_type": "circle", "rank": "number", "direction": "descending",
                   "note": "Each guild ranks its wardens from Circle 9, the weakest, to Circle 1, the strongest."}
        shown = {**unshown, "note": "Each guild ranks its wardens by numbered circles, such as Circle 7 and Circle 5."}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                                                           if not k.startswith("ANNALIST_")}, clear=True):
            write_json(Path(tmp) / "book.json", book)
            write_json(Path(tmp) / "script.json", {"replies": [{"purpose": "ladder-spec", "reply": {"ladder": unshown}},
                                                               {"purpose": "ladder-spec", "reply": {"ladder": shown}}]})
            generate_ladder(tmp)
            calls = read_jsonl(Path(tmp) / "calls.jsonl")
            ladder = json.loads((Path(tmp) / "book.json").read_text(encoding="utf-8"))["ladder"]
        self.assertEqual(len(calls), 2)
        self.assertIn("Circle 1, Circle 9", calls[0]["error"])
        self.assertIsNone(calls[1]["error"])
        self.assertEqual(ladder["note"], shown["note"])


if __name__ == "__main__":
    unittest.main()
