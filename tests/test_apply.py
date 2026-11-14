import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from annalist.backends import load_settings
from annalist.estimate import prompt_pricer
from annalist.files import read_jsonl
from annalist.llm import Budget, BudgetSpent, cached_llm, cached_reply, Unpriced
from annalist.render import Ask, ask_all
from tests.test_asof_leaks import SAME_PERSON, echo_script
from tests.test_build import MiniBuild, ROOT

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


if __name__ == "__main__":
    unittest.main()
