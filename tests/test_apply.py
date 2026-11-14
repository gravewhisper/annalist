import fcntl
import json
import os
import re
import tempfile
import unittest
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from unittest import mock

from annalist.apply import built_run
from annalist.backends import load_settings
from annalist.build import run_stage, STAGES
from annalist.estimate import prompt_pricer
from annalist.export import cmd_export
from annalist.files import read_jsonl
from annalist.llm import Budget, BudgetSpent, cached_llm, cached_reply, Unpriced
from annalist.render import Ask, ask_all
from tests.test_asof_leaks import RETITLED, SAME_PERSON, echo_script
from tests.test_build import build_script, MiniBuild, plan_rows, ROOT

RENDER_PURPOSES = ("summary", "personality", "appearance", "history")
RENDER_KEYS = ROOT / "tests" / "data" / "mini-render-keys.txt"


def render_keys(workdir):
    return sorted(p.name for p in (workdir / "cache").iterdir() if p.name.split("-")[0] in RENDER_PURPOSES)


class RenderKeysTest(unittest.TestCase):
    def test_a_two_volume_build_asks_the_render_prompts_it_always_asked(self):
        book = MiniBuild(echo_script())
        self.addCleanup(book.close)
        (book.workdir / "corrections.json").write_text(json.dumps(SAME_PERSON), encoding="utf-8")
        book.build("--volumes", "1-3,4-5")
        self.assertEqual(render_keys(book.workdir), RENDER_KEYS.read_text(encoding="utf-8").split(),
                         "a render prompt changed, so every built run pays for it again; if that is meant, rewrite " + RENDER_KEYS.name)


TRAITS = {"entries": [{"name": "Ines Varro", "fields": {"personality_evidence": [
    {"chapter": 2, "value": "watchful", "quotes": ["He trained an apprentice."]},
    {"chapter": 4, "value": "steadfast", "quotes": ["My name was Livia Hale. Tomas was my father.”"]}]}}]}


def personality_chapters(book, name):
    wiki = book.json("site/data/wiki.json")
    page = next(e for e in wiki["entities"] if e["name"] == name)
    return [p["chapter"] for p in page["profile"].get("personality", [])]


class AsOfRenderTest(unittest.TestCase):
    def test_a_correction_reaches_the_personality_the_site_shows_at_an_earlier_volume_end(self):
        book = MiniBuild(echo_script())
        self.addCleanup(book.close)
        book.build("--volumes", "1-3,4-5")
        self.assertEqual(personality_chapters(book, "Ines Varro"), [1])
        (book.workdir / "corrections.json").write_text(json.dumps(TRAITS), encoding="utf-8")
        book.build("--volumes", "1-3,4-5")
        self.assertEqual(personality_chapters(book, "Ines Varro"), [1, 2, 4])


PRICED = {"name": "fake", "script": "script.json", "prices": {"fake": {"input": 10000.0, "output": 10000.0}}}


class GateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.workdir = Path(tmp.name)
        (self.workdir / "book.json").write_text(json.dumps({"backend": PRICED}), encoding="utf-8")
        (self.workdir / "script.json").write_text(json.dumps({"replies": [{"purpose": "summary", "reply": {"summary": "S."}}]}), encoding="utf-8")
        env = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_a_budget_lets_no_prompt_it_did_not_price_reach_the_model(self):
        with self.assertRaises(Unpriced):
            cached_llm(self.workdir, "summary", "Who keeps the lamp?", gate=Budget(5.0, {}))
        self.assertEqual(read_jsonl(self.workdir / "calls.jsonl"), [])

    def test_a_budget_stops_before_the_call_that_would_pass_it_and_keeps_the_replies_paid_for(self):
        asks = [Ask("summary", f"Prompt {n}", "Ines", None) for n in range(3)]
        with self.assertRaises(BudgetSpent):
            ask_all(self.workdir, asks, 1, Budget(0.5, {(a.purpose, a.prompt): 0.3 for a in asks}))
        calls = read_jsonl(self.workdir / "calls.jsonl")
        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0]["total_cost_usd"], 0)
        self.assertIsNotNone(cached_reply(self.workdir, "summary", "Prompt 0"))

    def test_a_prompt_is_priced_from_the_tokens_this_runs_calls_of_its_purpose_used(self):
        rows = [{"purpose": "summary", "prompt_chars": 2000, "usage": {"input_tokens": 600, "cache_read_input_tokens": 400, "output_tokens": 80}},
                {"purpose": "summary", "prompt_chars": 2000, "usage": {"input_tokens": 1000, "output_tokens": 120}}]
        (self.workdir / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        price = prompt_pricer(self.workdir, load_settings(self.workdir))
        self.assertAlmostEqual(price("summary", "x" * 4000), (4000 * 0.5 + 100) * 10000.0 / 1e6)


CHEAP = {"name": "fake", "script": "script.json", "prices": {"fake": {"input": 3.0, "output": 15.0}}}
UNQUOTED = {"entries": [{"name": "Ines Varro", "fields": {"age": [{"chapter": 1, "value": "twenty", "quotes": ["She was twenty that winter."]}]}}]}


def pages(workdir):
    return {p.relative_to(workdir): p.read_bytes() for d in ("wiki", "site") for p in (workdir / d).rglob("*") if p.is_file()}


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.book = MiniBuild(build_script(), book={"backend": CHEAP})
        self.addCleanup(self.book.close)
        self.book.build()
        self.workdir = self.book.workdir

    def correct(self, rows):
        (self.workdir / "corrections.json").write_text(json.dumps(rows), encoding="utf-8")

    def apply(self, *args):
        return self.book.run_annalist("apply", str(self.workdir), *args, check=False)

    def test_apply_asks_only_the_prompts_a_title_row_changes_and_leaves_render_and_export_done(self):
        self.correct({"entries": [RETITLED]})
        calls, cached = len(self.book.calls()), set(render_keys(self.workdir))
        dry = self.apply("--dry-run")
        self.assertEqual((dry.returncode, len(self.book.calls())), (0, calls))
        planned = int(re.search(r"(\d+) not answered yet", dry.stdout).group(1))
        self.assertGreater(planned, 0)
        applied = self.apply("--yes", "--budget", "5")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        asked = self.book.calls()[calls:]
        self.assertEqual(len(asked), planned)
        self.assertEqual(len(set(render_keys(self.workdir)) - cached), planned)
        self.assertLessEqual({c["purpose"] for c in asked}, set(RENDER_PURPOSES))
        rows = plan_rows(self.book.build("--dry-run").stdout)
        self.assertEqual((rows["render"], rows["export"]), ("done", "done"))
        self.assertIn(RETITLED["title"], {e["name"] for e in self.book.json("site/data/wiki.json")["entities"]})
        again = self.apply("--yes")
        self.assertEqual((again.returncode, len(self.book.calls())), (0, calls + planned), again.stderr)

    def test_apply_refuses_a_row_whose_quote_is_not_in_its_chapter_before_asking_anything(self):
        self.correct(UNQUOTED)
        calls, before = len(self.book.calls()), pages(self.workdir)
        refused = self.apply("--yes", "--budget", "5")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Ines Varro.age ch1 has no quote found in that chapter", refused.stderr)
        self.assertEqual((len(self.book.calls()), pages(self.workdir)), (calls, before))

    def test_a_budget_below_the_price_stops_before_the_first_call_and_writes_no_page(self):
        self.correct({"entries": [RETITLED]})
        calls, before = len(self.book.calls()), pages(self.workdir)
        stopped = self.apply("--yes", "--budget", "0.000001")
        self.assertEqual(stopped.returncode, 3, stopped.stderr)
        self.assertEqual((len(self.book.calls()), pages(self.workdir)), (calls, before))
        self.assertEqual(plan_rows(self.book.build("--dry-run").stdout)["render"], "run: input changed")

    def test_yes_without_a_budget_spends_nothing_when_there_is_a_price(self):
        self.correct({"entries": [RETITLED]})
        calls = len(self.book.calls())
        refused = self.apply("--yes")
        self.assertIn("--budget", refused.stderr)
        self.assertEqual((refused.returncode != 0, len(self.book.calls())), (True, calls))

    def test_apply_refuses_a_run_whose_build_has_not_finished(self):
        stamps = self.book.json("build.json")
        (self.workdir / "build.json").write_text(json.dumps({**stamps, "started": "2026-11-15T10:00:00"}), encoding="utf-8")
        refused = self.apply("--dry-run")
        self.assertIn("has not finished", refused.stderr)

    def test_apply_does_not_run_while_another_command_writes_the_run(self):
        with open(self.workdir / ".lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            busy = [self.apply("--dry-run"), self.book.build(check=False),
                    self.book.run_annalist("export", str(self.workdir), str(self.workdir / "site"), check=False)]
        for proc in busy:
            self.assertIn("another annalist build, apply or export is writing", proc.stderr)

    def test_an_input_edited_while_a_stage_runs_leaves_the_stage_stale(self):
        render = next(s for s in STAGES if s.name == "render")
        with mock.patch.dict(os.environ, self.book.env, clear=True):
            run_stage(built_run(self.workdir, 1), replace(render, run=lambda run: self.correct({"entries": [RETITLED]})))
        self.assertEqual(plan_rows(self.book.build("--dry-run").stdout)["render"], "run: input changed")


class ExportSwapTest(unittest.TestCase):
    def test_an_export_that_fails_partway_leaves_the_previous_site_whole(self):
        book = MiniBuild(build_script())
        self.addCleanup(book.close)
        book.build()
        site = book.workdir / "site"
        before = pages(book.workdir)
        with mock.patch.dict(os.environ, book.env, clear=True), mock.patch("annalist.export.stamp_assets", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                cmd_export(Namespace(workdir=str(book.workdir), outdir=str(site), public=False, theme=None))
        self.assertEqual(pages(book.workdir), before)
        self.assertEqual(sorted(p.name for p in book.workdir.iterdir() if p.name.startswith("site")), ["site"])


if __name__ == "__main__":
    unittest.main()
