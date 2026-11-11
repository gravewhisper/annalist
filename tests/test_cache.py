import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from annalist.files import read_jsonl
from annalist.llm import cached_llm, cached_reply
from tests.test_backends import stub_claude

PROMPT = "Write the summary of Ines Varro as of chapter 3."


def envelope(result):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(result),
                       "total_cost_usd": 0.01, "usage": {"input_tokens": 10, "output_tokens": 5}, "duration_ms": 1000})


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name) / "run"
        (self.workdir / "cache").mkdir(parents=True)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.env = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("ANNALIST_")}, clear=True)
        self.env.start()
        self.no_sleep = mock.patch("annalist.llm.time.sleep", side_effect=AssertionError("an LLM call failed and backed off"))
        self.no_sleep.start()

    def tearDown(self):
        self.no_sleep.stop()
        self.env.stop()
        self.tmp.cleanup()

    def book(self, **book):
        (self.workdir / "book.json").write_text(json.dumps(book), encoding="utf-8")

    def claude_replies(self, result, code=0):
        os.environ.update(stub_claude(self.bin, envelope(result) if result is not None else "", code))

    def legacy_entry(self, reply):
        name = f"summary-{hashlib.sha1(PROMPT.encode()).hexdigest()[:16]}.json"
        (self.workdir / "cache" / name).write_text(json.dumps({"purpose": "summary", "reply": reply}), encoding="utf-8")

    def calls(self):
        return read_jsonl(self.workdir / "calls.jsonl")

    def test_claude_cli_reuses_a_cache_written_before_backends(self):
        self.book()
        self.legacy_entry({"summary": "old"})
        self.claude_replies(None, 1)
        self.assertEqual(cached_llm(str(self.workdir), "summary", PROMPT), {"summary": "old"})
        self.assertEqual(cached_reply(str(self.workdir), "summary", PROMPT), {"summary": "old"})
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(list((self.workdir / "cache").iterdir())), 1)

    def test_claude_cli_new_entries_are_hit_on_the_next_run(self):
        self.book()
        self.claude_replies({"summary": "fresh"})
        self.assertEqual(cached_llm(str(self.workdir), "summary", PROMPT), {"summary": "fresh"})
        self.claude_replies(None, 1)
        self.assertEqual(cached_llm(str(self.workdir), "summary", PROMPT), {"summary": "fresh"})
        self.assertEqual(len(self.calls()), 1)
        entry = json.loads(next((self.workdir / "cache").iterdir()).read_text(encoding="utf-8"))
        self.assertEqual((entry["backend"], entry["model"]), ("claude-cli", "sonnet"))

    def test_a_cacheable_prefix_reaches_the_cli_but_leaves_the_reply_cache_key_alone(self):
        self.book()
        self.claude_replies({"summary": "fresh"})
        prefix = "<book>The lamp burned.</book>\n"
        self.assertEqual(cached_llm(str(self.workdir), "summary", prefix + PROMPT, prefix=prefix), {"summary": "fresh"})
        seen = json.loads((self.bin / "argv.json").read_text())
        self.assertEqual((seen["stdin"], seen["ttl"]), (PROMPT, "5m"))
        self.assertTrue(seen["system_file"].endswith(prefix))
        self.claude_replies(None, 1)
        self.assertEqual(cached_llm(str(self.workdir), "summary", prefix + PROMPT), {"summary": "fresh"})
        self.assertEqual(self.calls()[0]["prompt_sha1"], hashlib.sha1((prefix + PROMPT).encode()).hexdigest())
        key = hashlib.sha1(f"claude-cli\nsonnet\n{prefix}{PROMPT}".encode()).hexdigest()[:16]
        self.assertEqual([p.name for p in (self.workdir / "cache").iterdir()], [f"summary-{key}.json"])

    def test_a_reply_at_one_effort_is_never_reused_at_another(self):
        self.book()
        self.legacy_entry({"summary": "old"})
        self.claude_replies({"summary": "default"})
        self.assertEqual(cached_llm(str(self.workdir), "summary", "another prompt"), {"summary": "default"})
        self.book(efforts={"summary": "high"})
        self.claude_replies({"summary": "high"})
        self.assertEqual(cached_llm(str(self.workdir), "summary", PROMPT), {"summary": "high"})
        self.assertEqual(cached_llm(str(self.workdir), "summary", "another prompt"), {"summary": "high"})
        self.assertEqual([c.get("effort") for c in self.calls()], [None, "high", "high"])

    def test_other_backends_and_models_never_reuse_each_others_answers(self):
        self.legacy_entry({"summary": "from claude"})
        (self.workdir / "script.json").write_text(json.dumps({"replies": [{"purpose": "summary", "reply": {"summary": "fake"}}]}))
        self.book(backend={"name": "fake", "script": "script.json"})
        self.assertEqual(cached_reply(str(self.workdir), "summary", PROMPT), None)
        self.assertEqual(cached_llm(str(self.workdir), "summary", PROMPT), {"summary": "fake"})
        self.book(backend={"name": "fake", "script": "script.json"}, models={"summary": "fake-large"})
        self.assertEqual(cached_reply(str(self.workdir), "summary", PROMPT), None)
        cached_llm(str(self.workdir), "summary", PROMPT)
        self.assertEqual([c["model"] for c in self.calls()], ["fake", "fake-large"])
        self.assertEqual(len(list((self.workdir / "cache").iterdir())), 3)

    def test_export_reads_the_cache_without_api_credentials(self):
        self.book(backend={"name": "anthropic"})
        self.assertIsNone(cached_reply(str(self.workdir), "summary", PROMPT))


if __name__ == "__main__":
    unittest.main()
