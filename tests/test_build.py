import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from annalist.backends import parse_settings
from annalist.build import STAGES
from annalist.estimate import estimate, measure_rates, RATES
from annalist.export import entity_id
from tests.test_backends import stub_claude
from tests.test_pipeline import mini_script

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"
MINI = ROOT / "tests" / "data" / "mini.epub"
MINI_WORDS = 3896
STAGE_ORDER = ["extract", "book", "read", "timelines", "wordings", "retype", "discover", "resolve", "relate", "link", "leads", "sweep", "tiers", "profile", "ladders", "families", "answers", "ending", "volumes",
               "render", "export", "review"]

BOOK_REPLY = {"power_system": "", "power_types": [{"type": "ward", "parent": "artifact", "description": "a protective charm a keeper sets"}],
              "relation_example": "guards", "extra_fields": [], "power_keywords": ["ward", "charm", "lamp", "oath", "guild"],
              "timeline_kind": "flashback", "timeline_note": "Chapter two goes back to the night the Gannet was wrecked."}

PROFILE_QUOTE = "Ines was nineteen and had been Tomas's apprentice for six years."

LATER_REPLIES = {
    "book": BOOK_REPLY,
    "retype": {"items": []},
    "wordings": {"wordings": []},
    "resolve": {"same": False, "reason": "Different people."},
    "discover": {"entries": []},
    "relate": {"relations": []},
    "link": {"labels": []},
    "families": {"kinds": []},
    "repeats": {"pairs": []},
    "leads": {"items": []},
    "sweep": {"answers": []},
    "answers": {"results": []},
    "premise": {"verdict": "reject", "reason": "The quotes do not show the assumption is false."},
    "tiers": {"labels": []},
    "profile": {"age": [{"value": "nineteen", "chapter": 1, "quotes": [PROFILE_QUOTE], "asserted_by": "narrator"}]},
    "profile-support": {"verdicts": [{"id": "O1", "verdict": "supported"}]},
    "profile-field": {"observations": []},
    "summary": {"summary": "A figure of Corvel Quay and the Lamplighters' Guild."},
    "personality": {"paragraph": "Careful and stubborn (ch 1)."},
    "history": {"paragraph": "Ines kept the lamp and searched for the cut page (ch 1)."},
    "arcs": {"arcs": [{"name": "The Missing Page", "start": 1}]},
    "arc": {"name": "The Missing Page", "summary": "Ines follows the cut page of the Salt Ledger to the Gannet's wreck."},
    "volume": {"overview": "The keepers of Corvel Quay and the night the lamp went dark.", "character_development": []},
    "events": {"events": []},
    "death": {"died": False},
}


TOMAS_DIES = {"died": True, "chapter": 3, "circumstances": "Tomas was found at the foot of the abbey stair.",
              "quotes": ["They found Tomas himself at the bottom, three hundred steps down, where the stair turned on the last "
                         "landing above the beach. He had been dead for some time."]}


def build_script(skip_chapters=(), skip_purposes=()):
    script = mini_script(skip=set(skip_chapters))
    script["replies"] += [{"purpose": p, "reply": r} for p, r in LATER_REPLIES.items() if p not in skip_purposes]
    if "death" not in skip_purposes:
        script["replies"].append({"purpose": "death", "contains": '"Tomas Hale" die in chapter 3', "reply": TOMAS_DIES})
    return script


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class MiniBuild:
    def __init__(self, script, book=None):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=CACHE)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "run"
        self.workdir.mkdir()
        self.code = ROOT
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}
        self.env.update(stub_claude(self.root, "", 1))
        self.script(script)
        (self.workdir / "book.json").write_text(json.dumps(book or {"backend": {"name": "fake", "script": "script.json"}}),
                                                encoding="utf-8")

    def script(self, script):
        (self.workdir / "script.json").write_text(json.dumps(script), encoding="utf-8")

    def build(self, *extra, check=True):
        proc = subprocess.run([sys.executable, "-m", "annalist", "build", str(MINI), str(self.workdir), "--yes", *extra],
                              cwd=self.code, env=self.env, capture_output=True, text=True, timeout=300)
        if check and proc.returncode:
            raise AssertionError(f"build exited {proc.returncode}:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return proc

    def run_annalist(self, *args, check=True):
        proc = subprocess.run([sys.executable, "-m", "annalist", *args], cwd=self.code, env=self.env, capture_output=True, text=True,
                              timeout=300)
        if check and proc.returncode:
            raise AssertionError(f"annalist {args[0]} exited {proc.returncode}:\n{proc.stderr[-3000:]}")
        return proc

    def calls(self, purpose=None):
        rows = read_jsonl(self.workdir / "calls.jsonl") if (self.workdir / "calls.jsonl").exists() else []
        return [c for c in rows if purpose is None or c["purpose"] == purpose]

    def json(self, name):
        return json.loads((self.workdir / name).read_text(encoding="utf-8"))

    def edit_code(self, rel, old, new):
        if self.code == ROOT:
            self.code = self.root / "code"
            shutil.copytree(ROOT / "annalist", self.code / "annalist", ignore=shutil.ignore_patterns("__pycache__"))
        path = self.code / "annalist" / rel
        source = path.read_text(encoding="utf-8")
        assert source.count(old) == 1, f"{rel} does not hold {old!r} exactly once"
        path.write_text(source.replace(old, new), encoding="utf-8")

    def close(self):
        self.tmp.cleanup()


def plan_rows(stdout):
    return {m.group(1): m.group(2) for m in re.finditer(r"^  (\w+)\s+(done|run(?:: [^\n]*?)?|skip: [^\n]*?)[ \t]*(?:[ \t][\d,]+[ \t].*)?$", stdout, re.M)
            if m.group(1) in STAGE_ORDER}


def site_views(wiki_path, *views):
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("node is not installed")
    proc = subprocess.run([node, str(ROOT / "tests" / "site_render.mjs"), str(ROOT / "annalist" / "site" / "app.js"), str(wiki_path), *views],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def ran(stdout):
    return re.findall(r"^== (\w+)$", stdout, re.M)


class BuildMiniTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = MiniBuild(build_script())
        cls.first = cls.book.build()
        cls.calls_after_first = len(cls.book.calls())
        cls.second = cls.book.build()

    @classmethod
    def tearDownClass(cls):
        cls.book.close()

    def test_one_command_runs_every_stage_in_order(self):
        self.assertEqual(ran(self.first.stdout), [s for s in STAGE_ORDER if s not in ("timelines", "ladders", "ending")])
        self.assertEqual(plan_rows(self.second.stdout)["timelines"], "done")

    def test_the_site_holds_the_books_entities_and_volume(self):
        site = json.loads((self.book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        self.assertIn("Ines Varro", {e["name"] for e in site["entities"]})
        self.assertEqual([(v["name"], v["from"], v["to"]) for v in site["volumes"]], [("The Salt Ledger", 1, 5)])
        self.assertTrue((self.book.workdir / "site" / "index.html").exists())
        self.assertTrue((self.book.workdir / "wiki" / "volumes" / "the-salt-ledger.md").exists())

    def test_the_volume_page_names_book_type_entries_without_assuming_a_power_system(self):
        page = (self.book.workdir / "wiki" / "volumes" / "the-salt-ledger.md").read_text(encoding="utf-8")
        self.assertNotIn("Power system", page)
        wards = [e for e in self.book.json("entities.json") if e["type"] == "ward"]
        self.assertEqual("## World introduced" in page, bool(wards))

    def test_book_json_is_generated_validated_and_keeps_the_backend(self):
        book = self.book.json("book.json")
        self.assertEqual(book["timeline_kind"], "flashback")
        self.assertEqual(book["power_types"], {"ward": {"parent": "artifact", "description": "a protective charm a keeper sets"}})

        self.assertEqual(book["backend"], {"name": "fake", "script": "script.json"})

    def test_a_book_without_a_power_ladder_builds_no_ladders_and_keeps_every_name_and_id(self):
        self.assertIsNone(self.book.json("book.json")["ladder"])
        self.assertEqual(self.book.calls("ladder-spec"), [])
        self.assertFalse((self.book.workdir / "ladders.json").exists())
        site = json.loads((self.book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        self.assertEqual(site["ladders"], [])
        self.assertIsNone(site["book"]["ladder"])
        names = {e["name"] for e in self.book.json("entities.json")}
        self.assertEqual({(e["name"], e["id"]) for e in site["entities"] if e["name"] in names},
                         {(n, entity_id(n)) for n in names})

    def test_the_review_is_written_and_summarised(self):
        review = self.book.json("review.json")
        self.assertEqual(len(review["checks"]), 10)
        self.assertTrue((self.book.workdir / "review.md").exists())
        self.assertIn("review:", self.first.stdout)
        self.assertIn("Main characters with an empty status or power field", self.first.stdout.split("review:")[-1])

    def test_a_death_found_in_the_facts_reaches_the_volume_and_the_site_status(self):
        volume = self.book.json("volumes/the-salt-ledger.json")
        self.assertEqual([(d["name"], d["chapter"]) for d in volume["deaths"]], [("Tomas Hale", 3)])
        site = json.loads((self.book.workdir / "site" / "data" / "wiki.json").read_text(encoding="utf-8"))
        tomas = next(e for e in site["entities"] if e["name"] == "Tomas Hale")
        self.assertEqual([(o["value"], o["chapter"]) for o in tomas["profile"]["fields"]["status"]], [("dead", 3)])

    def test_strict_fails_the_build_when_main_characters_lack_status_or_power(self):
        missing = len(self.book.json("review.json")["checks"][0]["findings"])
        self.assertGreater(missing, 0)
        strict = self.book.build("--strict", check=False)
        self.assertEqual(strict.returncode, 4)
        self.assertIn(f"{missing} main characters have an empty status or power field", strict.stderr)
        self.assertEqual(self.book.build("--strict", str(missing)).returncode, 0)

    def test_profiles_come_from_the_profile_stage(self):
        ines = self.book.json("profiles.json")["characters"]["Ines Varro"]
        self.assertEqual([o["value"] for o in ines["fields"]["age"]], ["nineteen"])

    def test_the_plan_is_printed_before_running(self):
        self.assertLess(self.first.stdout.index("est. cost"), self.first.stdout.index("== extract"))
        self.assertEqual(plan_rows(self.first.stdout)["read"], "run")

    def test_a_second_build_finds_everything_current_and_calls_nothing(self):
        self.assertEqual(ran(self.second.stdout), [])
        rows = plan_rows(self.second.stdout)
        self.assertEqual({state for stage, state in rows.items() if stage not in ("ladders", "ending")}, {"done"})
        self.assertTrue(rows["ending"].startswith("skip:"))
        self.assertTrue(rows["ladders"].startswith("skip:"))
        self.assertEqual(len(self.book.calls()), self.calls_after_first)


class CodeChangeTest(unittest.TestCase):
    def setUp(self):
        self.book = MiniBuild(build_script())
        self.book.build()
        self.calls = len(self.book.calls())

    def tearDown(self):
        self.book.close()

    def test_a_change_to_a_stages_code_reruns_it_and_the_stages_whose_inputs_it_changes(self):
        self.book.edit_code("resolve.py", 'write_json(path, {"pairs": decisions})',
                            'write_json(path, {"pairs": decisions, "rules": 2})')
        rebuilt = self.book.build()
        self.assertEqual(plan_rows(rebuilt.stdout)["resolve"], "run: code changed")
        self.assertEqual(plan_rows(rebuilt.stdout)["retype"], "done")
        self.assertEqual(ran(rebuilt.stdout), ["resolve", "relate", "link", "leads", "sweep", "tiers", "profile", "families", "answers", "volumes", "render", "export",
                                                "review"])
        self.assertEqual(self.book.json("merges.json")["rules"], 2)
        self.assertEqual(len(self.book.calls()), self.calls)

    def test_a_code_change_that_leaves_the_output_alone_reruns_only_that_stage(self):
        self.book.edit_code("resolve.py", "def cmd_resolve(args):", "RULES = 2\n\n\ndef cmd_resolve(args):")
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["resolve"])
        self.assertEqual(len(self.book.calls()), self.calls)
        self.assertEqual(ran(self.book.build().stdout), [])

    def test_a_change_to_a_module_a_stage_imports_reruns_the_stages_that_import_it(self):
        self.book.edit_code("corpus.py", "\nimport re\n", "\nimport re\n\nRULES = 2\n")
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["resolve", "leads", "sweep", "tiers", "answers", "volumes", "render", "export"])
        self.assertEqual(len(self.book.calls()), self.calls)

    def test_a_change_to_the_site_assets_reruns_export(self):
        self.book.edit_code("site/app.css", ":root{--heading-font:", ".rules{order:2}\n:root{--heading-font:")
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["export"])
        self.assertIn(".rules{order:2}", (self.book.workdir / "site" / "app.css").read_text(encoding="utf-8"))

    def test_a_run_built_before_titles_were_recorded_gets_its_title_without_rerunning_a_paid_stage(self):
        book = self.book.json("book.json")
        self.assertEqual(book.pop("title"), "The Salt Ledger")
        (self.book.workdir / "book.json").write_text(json.dumps(book), encoding="utf-8")
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["book"])
        self.assertEqual(self.book.json("book.json")["title"], "The Salt Ledger")
        self.assertEqual(len(self.book.calls()), self.calls)

    def test_a_title_changed_in_book_json_reruns_only_export_and_reaches_the_header(self):
        book = {**self.book.json("book.json"), "title": "The Salt Ledger, Revised"}
        (self.book.workdir / "book.json").write_text(json.dumps(book), encoding="utf-8")
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["export"])
        header = site_views(self.book.workdir / "site" / "data" / "wiki.json", "header@1")["header@1"]
        self.assertEqual(header["brand"], "The Salt Ledger, Revised")

    def test_a_theme_kept_for_the_books_title_styles_the_site_without_a_theme_flag(self):
        self.assertEqual(self.book.json("site/data/wiki.json")["book"]["theme"], {})
        self.book.edit_code("themes/lotm.json", '"title": "Lord of the Mysteries"', '"title": "The Salt Ledger"')
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["export"])
        theme = self.book.json("site/data/wiki.json")["book"]["theme"]
        self.assertEqual(theme["heading_font"], "Cinzel")
        self.assertEqual(theme["dark"]["accent"], "#b38b4d")

    def test_a_prompt_change_pays_only_for_the_new_prompts(self):
        related = len(self.book.calls("relate"))
        self.assertGreater(related, 0)
        self.book.edit_code("relate.py", 'RELATE_PROMPT = """You are filling', 'RELATE_PROMPT = """Rules 2. You are filling')
        rebuilt = self.book.build()
        self.assertEqual(ran(rebuilt.stdout), ["relate"])
        self.assertEqual([c["purpose"] for c in self.book.calls()[self.calls:]], ["relate"] * related)


    def relate_plan(self):
        self.book.edit_code("relate.py", "\ndef co_mentioned(", f"\nRULES_{len(self.book.calls())} = 1\n\n\ndef co_mentioned(")
        plan = self.book.build("--dry-run", "--backend", "claude-cli").stdout
        row = re.search(r"^  relate\s+run: code changed\s+[\d,]+\s+\$([\d.,]+)\s+\S+\s*(?:\$([\d.,]+))?$", plan, re.M)
        return float(row.group(1)), row.group(2) and float(row.group(2))

    def test_the_plan_prices_a_rerun_by_how_much_of_the_stages_last_rerun_the_cache_answered(self):
        up_to, likely = self.relate_plan()
        self.assertGreater(up_to, 0)
        self.assertIsNone(likely)
        self.book.build()
        up_to, likely = self.relate_plan()
        self.assertGreater(up_to, 0)
        self.assertEqual(likely, 0)
        self.book.edit_code("relate.py", 'RELATE_PROMPT = """You are filling', 'RELATE_PROMPT = """Rules 2. You are filling')
        self.book.build()
        up_to, likely = self.relate_plan()
        self.assertGreater(up_to, 0)
        self.assertIsNone(likely)

class StandaloneExportTest(unittest.TestCase):
    def setUp(self):
        self.book = MiniBuild(build_script())
        self.book.build()

    def tearDown(self):
        self.book.close()

    def export(self):
        return self.book.run_annalist("export", str(self.book.workdir), str(self.book.root / "site"), check=False)

    def assert_refused(self, proc, stage):
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn(stage, proc.stderr)
        self.assertIn("annalist build", proc.stderr)
        self.assertFalse((self.book.root / "site" / "data" / "wiki.json").exists())

    def test_export_of_a_current_build_writes_the_site(self):
        proc = self.export()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.book.root / "site" / "data" / "wiki.json").exists())

    def test_export_refuses_a_run_whose_volume_code_changed_until_build_reruns_it(self):
        self.book.edit_code("volume.py", "def cmd_volume(args):", "RULES = 2\n\n\ndef cmd_volume(args):")
        self.assert_refused(self.export(), "volumes")
        self.assertIn("volumes", ran(self.book.build().stdout))
        self.assertEqual(self.export().returncode, 0)

    def test_export_refuses_a_run_built_before_build_records_until_build_reruns_its_stages(self):
        (self.book.workdir / "build.json").unlink()
        for path in (self.book.workdir / "volumes").glob("*.json"):
            volume = json.loads(path.read_text(encoding="utf-8"))
            volume["key_events"] = [{"event": "Tomas was found at the foot of the abbey stair.", "facts": [], "chapters": [3]}]
            path.write_text(json.dumps(volume), encoding="utf-8")
        self.assert_refused(self.export(), "build.json")
        self.assertIn("volumes", ran(self.book.build().stdout))
        proc = self.export()
        self.assertEqual(proc.returncode, 0, proc.stderr)


class ResumeTest(unittest.TestCase):
    def test_a_build_that_stops_mid_read_resumes_at_the_missing_chapter(self):
        book = MiniBuild(build_script(skip_chapters={("extract", 3)}))
        try:
            stopped = book.build(check=False)
            self.assertEqual(stopped.returncode, 2)
            self.assertIn("stage read stopped", stopped.stderr)
            self.assertEqual(sorted(p.name for p in (book.workdir / "state").glob("*.json")), ["0001.json", "0002.json"])
            book.script(build_script())
            resumed = book.build()
            self.assertEqual(ran(resumed.stdout)[0], "read")
            self.assertNotIn("extract", ran(resumed.stdout))
            extracted = [c["chapter"] for c in book.calls("extract") if not c["error"]]
            self.assertEqual(extracted, [1, 2, 3, 4, 5])
            self.assertTrue((book.workdir / "site" / "data" / "wiki.json").exists())
        finally:
            book.close()

    def test_a_build_that_stops_mid_profile_reuses_the_profiles_already_answered(self):
        book = MiniBuild(build_script(skip_purposes={"profile-support"}))
        try:
            stopped = book.build(check=False)
            self.assertEqual(stopped.returncode, 2)
            self.assertIn("stage profile stopped", stopped.stderr)
            self.assertEqual(ran(stopped.stdout)[-1], "profile")
            self.assertFalse((book.workdir / "profiles.json").exists())
            self.assertGreater(len([c for c in book.calls("profile") if not c["error"]]), 0)
            book.script(build_script())
            resumed = book.build()
            self.assertEqual(ran(resumed.stdout), ["profile", "families", "answers", "volumes", "render", "export", "review"])
            profiled = len(book.json("profiles.json")["characters"])
            self.assertEqual(len([c for c in book.calls("profile") if not c["error"]]), profiled)
        finally:
            book.close()

    def test_a_resumed_build_counts_the_spend_of_the_invocations_before_it_against_the_budget(self):
        book = MiniBuild(build_script(skip_purposes={"profile-support"}))
        try:
            self.assertEqual(book.build(check=False).returncode, 2)
            spent = {"purpose": "profile", "ts": book.calls()[-1]["ts"], "total_cost_usd": 1.5}
            with open(book.workdir / "calls.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(spent) + "\n")
            time.sleep(1.1)
            book.script(build_script())
            capped = book.build("--budget", "1", check=False)
            self.assertEqual(capped.returncode, 3)
            self.assertIn("spent $1.50 of the $1.00 budget", capped.stderr)
            self.assertEqual(ran(capped.stdout), [])
            finished = book.build("--budget", "2")
            self.assertIn("$1.50 spent since this build started", finished.stdout)
            book.edit_code("review.py", "def cmd_review(args):", "RULES = 2\n\n\ndef cmd_review(args):")
            again = book.build("--budget", "1")
            self.assertEqual(ran(again.stdout), ["review"])
            self.assertIn("$0.00 spent since this build started", again.stdout)
        finally:
            book.close()

    def test_a_book_json_that_never_validates_stops_before_reading(self):
        book = MiniBuild({"replies": [{"purpose": "book", "reply": {**BOOK_REPLY, "timeline_kind": "spiral"}}]})
        try:
            stopped = book.build(check=False)
            self.assertEqual(stopped.returncode, 2)
            self.assertIn("book.json failed validation after every retry", stopped.stderr)
            self.assertIn("timeline_kind must be one of", stopped.stderr)
            self.assertFalse((book.workdir / "state").exists())
        finally:
            book.close()


LATER_CHAPTERS = ["Two Names", "The Salt Ledger\n\n", "They buried Tomas Hale in the Guild plot",
                  "Livia Hale broke the Abbess's seal that night", "Sister Wren reveals that she is Livia Hale"]


def leak_script():
    script = build_script()
    script["replies"] = [{"purpose": "book", "contains": text, "reply": {**BOOK_REPLY, "power_system": f"leaked {text}"}}
                         for text in LATER_CHAPTERS] + script["replies"]
    return script


class BookCapTest(unittest.TestCase):
    def test_the_book_prompt_holds_no_title_or_text_past_the_last_chapter(self):
        book = MiniBuild(leak_script())
        try:
            book.build("--to", "3")
            self.assertEqual(book.json("book.json")["power_system"], "")
            self.assertEqual(sorted(p.name for p in (book.workdir / "state").glob("*.json")), ["0001.json", "0002.json", "0003.json"])
        finally:
            book.close()

    def test_a_book_regenerated_at_an_earlier_chapter_ignores_the_states_read_past_it(self):
        book = MiniBuild(build_script())
        try:
            book.build()
            book.script(leak_script())
            stripped = {k: v for k, v in book.json("book.json").items() if k != "timeline_kind"}
            (book.workdir / "book.json").write_text(json.dumps(stripped), encoding="utf-8")
            book.build("--to", "3")
            self.assertEqual(book.json("book.json")["power_system"], "")
        finally:
            book.close()

    def test_a_book_with_overlapping_extra_fields_is_regenerated_keeping_the_first(self):
        book = MiniBuild(build_script())
        try:
            book.build()
            settings = book.json("book.json")
            settings["extra_fields"] = {"lamp_rank": "the character's lamp rank, written as 'Rank (Lamp)'",
                                        "rank": {"description": "the rank", "values": ["Keeper", "Master"]}}
            (book.workdir / "book.json").write_text(json.dumps(settings), encoding="utf-8")
            self.assertIn("book", ran(book.build().stdout))
            self.assertEqual(book.json("book.json")["extra_fields"], {
                "lamp_rank": {"description": "the character's lamp rank, written as 'Rank (Lamp)'", "values": ["Keeper", "Master"]}})
        finally:
            book.close()


class DryRunTest(unittest.TestCase):
    def dry_run(self, *extra):
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
            workdir = Path(tmp) / "fresh"
            env = {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}
            proc = subprocess.run([sys.executable, "-m", "annalist", "build", str(MINI), str(workdir), "--dry-run", *extra],
                                  cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=True)
            self.assertFalse(workdir.exists())
        return proc.stdout

    def stage_cost(self, stdout, stage):
        return float(re.search(rf"^  {stage}\s+run\s+[\d,]+\s+\$([\d.,]+)", stdout, re.M).group(1))

    def test_dry_run_lists_chapter_words_and_writes_nothing(self):
        out = self.dry_run()
        self.assertEqual(re.findall(r"^  ch\s+(\d+)\s+([\d,]+)", out, re.M),
                         [("1", "800"), ("2", "739"), ("3", "785"), ("4", "797"), ("5", "775")])
        self.assertIn("volumes (whole-book): The Salt Ledger 1-5", out)
        self.assertNotIn("== ", out)

    def test_read_estimate_follows_the_measured_rates_and_the_model_price(self):
        sonnet = self.dry_run()
        expected = estimate(parse_settings({}, {}), ("extract", "support", "reread", "timelines"), MINI_WORDS)
        self.assertAlmostEqual(self.stage_cost(sonnet, "read"), round(expected.dollars, 2), places=2)
        self.assertGreater(self.stage_cost(sonnet, "read"), 0.05)
        opus = self.dry_run("--model", "opus")
        self.assertAlmostEqual(self.stage_cost(opus, "read"), 2 * self.stage_cost(sonnet, "read"), delta=0.011)

    def test_the_fake_backend_costs_nothing(self):
        self.assertRegex(self.dry_run("--backend", "fake", "--option", "script=script.json"), r"total\s+\$0\.00")


class RatesTest(unittest.TestCase):
    def test_rates_are_tokens_and_seconds_per_thousand_words_read(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
            run = Path(tmp)
            (run / "state").mkdir()
            (run / "state" / "0001.json").write_text("{}", encoding="utf-8")
            (run / "chapters.json").write_text(json.dumps([{"index": 1, "words": 2000}, {"index": 2, "words": 9000}]), encoding="utf-8")
            rows = [{"purpose": "extract", "wall_s": 10, "usage": {"input_tokens": 3000, "cache_read_input_tokens": 1000, "output_tokens": 500}},
                    {"purpose": "extract", "wall_s": 6, "usage": {"input_tokens": 4000, "output_tokens": 700}}]
            (run / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            rates = measure_rates([run])
        self.assertEqual(rates["extract"].__dict__, {"input_tokens": 4000.0, "output_tokens": 600.0, "wall_s": 8.0})

    def test_every_llm_purpose_has_a_default_rate(self):
        self.assertTrue({"book", "extract", "support", "reread", "timelines", "retype", "resolve", "leads", "sweep", "tiers",
                         "profile", "profile-support", "summary", "personality", "arcs", "arc", "volume", "events", "death", "ending",
                         "answers", "premise"} <= set(RATES))
        self.assertEqual({p for stage in STAGES for p in stage.purposes} - set(RATES), set())


if __name__ == "__main__":
    unittest.main()
