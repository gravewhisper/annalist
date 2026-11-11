import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from annalist.backends import (Anthropic, ClaudeCLI, ConfigError, Fake, Fatal, OpenAI, Request, Transient,
                               parse_settings, prompt_sha1)
from annalist.llm import SYSTEM_PROMPT

PAYLOADS = Path(__file__).parent / "data" / "payloads"


def payload(name):
    return (PAYLOADS / name).read_text(encoding="utf-8")


def request(**kw):
    return Request(**{"system": SYSTEM_PROMPT, "prompt": "Audit these claims.", "model": "sonnet", "purpose": "support",
                      "chapter": 3, **kw})


class Recorder:
    def __init__(self, status, body, headers=None):
        self.status, self.body, self.headers, self.calls = status, body, headers or {}, []

    def __call__(self, url, headers, data, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": data})
        return self.status, self.headers, self.body


class AnthropicBackendTest(unittest.TestCase):
    def backend(self, post, **options):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            return Anthropic("/tmp", options, post=post)

    def test_sends_messages_request_with_alias_resolved(self):
        post = Recorder(200, payload("anthropic-message.json"))
        self.backend(post).complete(request(prompt="Audit F1."))
        sent = post.calls[0]
        self.assertEqual(sent["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(sent["headers"], {"x-api-key": "sk-test", "anthropic-version": "2026-10-21"})
        self.assertEqual(sent["payload"], {"model": "claude-sonnet-5-5", "max_tokens": 32000, "system": SYSTEM_PROMPT,
                                           "messages": [{"role": "user", "content": "Audit F1."}]})

    def test_reply_joins_text_blocks_and_prices_usage(self):
        reply = self.backend(Recorder(200, payload("anthropic-message.json"))).complete(request())
        self.assertEqual(json.loads(reply.text), {"verdicts": [{"id": "F1", "verdict": "supported"}]})
        self.assertEqual(reply.model, "claude-sonnet-5-5")
        self.assertEqual((reply.usage["input_tokens"], reply.usage["output_tokens"]), (1200, 300))
        self.assertAlmostEqual(reply.cost_usd, 1200 * 2 / 1e6 + 300 * 10 / 1e6)

    def test_config_prices_override_the_table(self):
        backend = self.backend(Recorder(200, payload("anthropic-message.json")),
                               prices={"claude-sonnet-5-5": {"input": 1, "output": 1}})
        self.assertAlmostEqual(backend.complete(request()).cost_usd, 1500 / 1e6)

    def test_overload_and_rate_limit_are_retried_with_retry_after(self):
        for status in (429, 529, 503):
            with self.assertRaises(Transient) as caught:
                self.backend(Recorder(status, payload("anthropic-overloaded.json"), {"retry-after": "7"})).complete(request())
            self.assertEqual(caught.exception.retry_after, 7)

    def test_client_errors_stop_at_once(self):
        with self.assertRaises(Fatal):
            self.backend(Recorder(401, '{"type":"error","error":{"type":"authentication_error"}}')).complete(request())

    def test_missing_key_is_a_config_error(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ConfigError):
            Anthropic("/tmp", {})


class OpenAIBackendTest(unittest.TestCase):
    def test_local_server_needs_no_key_and_gets_chat_request(self):
        post = Recorder(200, payload("openai-chat.json"))
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = OpenAI("/tmp", {"base_url": "http://localhost:1234/v1/"}, post=post)
        backend.complete(request(model="qwen3-8b", prompt="Reread."))
        self.assertEqual(post.calls[0]["url"], "http://localhost:1234/v1/chat/completions")
        self.assertEqual(post.calls[0]["headers"], {})
        self.assertEqual(post.calls[0]["payload"], {"model": "qwen3-8b", "messages": [
            {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Reread."}]})

    def test_hosted_server_gets_bearer_key_and_max_tokens(self):
        post = Recorder(200, payload("openai-chat.json"))
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test"}, clear=True):
            backend = OpenAI("/tmp", {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
                                      "max_tokens": 9000}, post=post)
        backend.complete(request(model="qwen/qwen3-8b"))
        self.assertEqual(post.calls[0]["headers"], {"authorization": "Bearer or-test"})
        self.assertEqual(post.calls[0]["payload"]["max_tokens"], 9000)

    def test_reply_text_usage_and_cost(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = OpenAI("/tmp", {"base_url": "http://localhost:1234/v1",
                                      "prices": {"qwen3-8b": {"input": 0.5, "output": 1.0}}},
                             post=Recorder(200, payload("openai-chat.json")))
        reply = backend.complete(request(model="qwen3-8b"))
        self.assertEqual(json.loads(reply.text)["verdict"], "accept")
        self.assertEqual(reply.usage, {"input_tokens": 2000, "output_tokens": 100})
        self.assertAlmostEqual(reply.cost_usd, 2000 * 0.5 / 1e6 + 100 / 1e6)

    def test_unpriced_model_has_unknown_cost(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = OpenAI("/tmp", {"base_url": "http://localhost:1234/v1"}, post=Recorder(200, payload("openai-chat.json")))
        self.assertIsNone(backend.complete(request(model="qwen3-8b")).cost_usd)

    def test_null_content_is_an_empty_reply(self):
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": None}}]})
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = OpenAI("/tmp", {"base_url": "http://localhost:1234/v1"}, post=Recorder(200, body))
        self.assertEqual(backend.complete(request(model="m")).text, "")

    def test_openai_without_key_is_a_config_error(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ConfigError):
            OpenAI("/tmp", {})

    def test_refused_connection_stops_with_a_hint(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            backend = OpenAI("/tmp", {"base_url": "http://127.0.0.1:9/v1", "timeout_s": 5})
        with self.assertRaisesRegex(Fatal, "is the server running"):
            backend.complete(request(model="m"))


def stub_claude(directory, stdout, code=0):
    script = Path(directory) / "claude"
    script.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                      f"open({str(Path(directory) / 'argv.json')!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'caching': os.environ.get('DISABLE_PROMPT_CACHING')}}))\n"
                      f"sys.stdout.write({stdout!r})\nsys.exit({code})\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{directory}{os.pathsep}{os.environ['PATH']}"}


class ClaudeCLIBackendTest(unittest.TestCase):
    def test_runs_claude_with_the_original_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, stub_claude(tmp, payload("claude-cli-envelope.json"))):
                reply = ClaudeCLI(tmp, {}).complete(request(model="opus", prompt="Extract chapter 3."))
            seen = json.loads((Path(tmp) / "argv.json").read_text())
        self.assertEqual(seen["argv"], ["-p", "--output-format", "json", "--model", "opus", "--tools", "",
                                        "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
                                        "--system-prompt", SYSTEM_PROMPT])
        self.assertEqual(seen["stdin"], "Extract chapter 3.")
        self.assertEqual(seen["caching"], "1")
        self.assertEqual(json.loads(reply.text), {"ok": True, "word": "lamp"})
        self.assertEqual(reply.cost_usd, 0.0000787)
        self.assertEqual((reply.usage["input_tokens"], reply.usage["output_tokens"]), (697, 18))

    def test_an_effort_is_passed_to_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, stub_claude(tmp, payload("claude-cli-envelope.json"))):
                ClaudeCLI(tmp, {}).complete(Request(system=SYSTEM_PROMPT, prompt="p", model="sonnet", purpose="extract", effort="high"))
            seen = json.loads((Path(tmp) / "argv.json").read_text())
        self.assertEqual(seen["argv"][:7], ["-p", "--output-format", "json", "--model", "sonnet", "--effort", "high"])

    def test_efforts_pick_a_step_then_the_default_and_reject_bad_values(self):
        settings = parse_settings({"efforts": {"default": "medium", "extract": "high"}}, {})
        self.assertEqual((settings.effort_for("extract"), settings.effort_for("support")), ("high", "medium"))
        self.assertIsNone(parse_settings({}, {}).effort_for("extract"))
        with self.assertRaisesRegex(ConfigError, "efforts must map"):
            parse_settings({"efforts": {"extract": "huge"}}, {})
        with self.assertRaisesRegex(ConfigError, "only with the claude-cli backend"):
            parse_settings({"efforts": {"extract": "high"}, "backend": {"name": "openai", "model": "m"}}, {})

    def test_error_envelope_is_retried(self):
        envelope = json.dumps({"is_error": True, "subtype": "error_during_execution", "result": "overloaded"})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, stub_claude(tmp, envelope, 1)):
            with self.assertRaisesRegex(Transient, "overloaded"):
                ClaudeCLI(tmp, {}).complete(request())


class FakeBackendTest(unittest.TestCase):
    def fake(self, replies):
        tmp = tempfile.mkdtemp()
        Path(tmp, "script.json").write_text(json.dumps({"replies": replies}))
        return Fake(tmp, {"script": "script.json"})

    def test_replays_by_purpose_and_chapter_then_by_prompt_hash(self):
        fake = self.fake([{"purpose": "support", "chapter": 3, "reply": {"verdicts": []}},
                          {"prompt_sha1": prompt_sha1("exact prompt"), "reply": "not json"}])
        self.assertEqual(json.loads(fake.complete(request()).text), {"verdicts": []})
        self.assertEqual(fake.complete(request(prompt="exact prompt", chapter=9)).text, "not json")

    def test_a_reply_scripted_for_prompt_text_wins_over_the_purpose_default(self):
        fake = self.fake([{"purpose": "death", "reply": {"died": False}},
                          {"purpose": "death", "contains": '"Tomas Hale" die', "reply": {"died": True}}])
        self.assertEqual(json.loads(fake.complete(request(purpose="death", chapter=None, prompt='Did "Tomas Hale" die?')).text), {"died": True})
        self.assertEqual(json.loads(fake.complete(request(purpose="death", chapter=None, prompt='Did "Livia Hale" die?')).text), {"died": False})

    def test_unscripted_call_fails_loudly(self):
        fake = self.fake([{"purpose": "support", "chapter": 3, "reply": {}}])
        with self.assertRaisesRegex(Fatal, "no scripted reply for purpose 'support' chapter 4"):
            fake.complete(request(chapter=4))


class SettingsTest(unittest.TestCase):
    def test_default_is_claude_cli_with_per_step_models(self):
        settings = parse_settings({"models": {"extract": "opus"}}, {})
        self.assertEqual(settings.backend, "claude-cli")
        self.assertEqual((settings.model_for("extract"), settings.model_for("support")), ("opus", "sonnet"))

    def test_book_block_selects_backend_and_default_model(self):
        settings = parse_settings({"backend": {"name": "openai", "base_url": "http://localhost:1234/v1", "model": "qwen3-8b"},
                                   "models": {"extract": "qwen3-32b"}}, {})
        self.assertEqual((settings.backend, settings.model_for("extract"), settings.model_for("reread")),
                         ("openai", "qwen3-32b", "qwen3-8b"))
        self.assertEqual(settings.options, {"base_url": "http://localhost:1234/v1"})

    def test_env_overrides_the_book_and_drops_options_for_another_backend(self):
        settings = parse_settings({"backend": {"name": "openai", "model": "qwen3-8b"}}, {"ANNALIST_BACKEND": "claude-cli"})
        self.assertEqual((settings.backend, settings.model_for("extract"), settings.options), ("claude-cli", "sonnet", {}))

    def test_invalid_configs_name_the_problem(self):
        cases = [
            ({"backend": {"name": "gemini"}}, {}, "unknown backend 'gemini'"),
            ({"backend": {"name": "anthropic", "script": "x"}}, {}, "backend.script is not an option of the anthropic backend"),
            ({"backend": {"name": "openai", "max_tokens": "lots", "model": "m"}}, {}, "backend.max_tokens must be a whole number"),
            ({"backend": {"name": "openai", "model": "m"}, "models": {"extract": "opus"}}, {}, "Claude CLI aliases"),
            ({"backend": {"name": "fake"}}, {}, "needs backend.script"),
            ({"backend": {"name": "anthropic", "prices": {"m": [1, 2]}}}, {}, "backend.prices"),
            ({"backend": "openai"}, {}, "must be an object"),
        ]
        for book, env, message in cases:
            with self.subTest(message), self.assertRaisesRegex(ConfigError, message):
                parse_settings(book, env)

    def test_openai_without_a_model_fails_when_a_step_needs_one(self):
        settings = parse_settings({"backend": {"name": "openai"}}, {})
        with self.assertRaisesRegex(ConfigError, "set backend.model"):
            settings.model_for("extract")


if __name__ == "__main__":
    unittest.main()
