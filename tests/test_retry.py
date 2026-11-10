import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from annalist.files import read_jsonl
from annalist.llm import BACKOFF_S, LLMUnavailable, llm

OK = json.dumps({"model": "qwen3-8b", "choices": [{"message": {"content": '{"answer": 42}'}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 3}})


class ScriptedServer:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                server.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                status, headers, body = server.responses.pop(0)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class RetryTest(unittest.TestCase):
    def run_llm(self, responses):
        server = ScriptedServer(responses)
        self.addCleanup(server.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        workdir = Path(tmp.name)
        (workdir / "book.json").write_text(json.dumps({"backend": {"name": "openai", "base_url": server.url,
                                                                   "model": "qwen3-8b"}}), encoding="utf-8")
        sleeps = []
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("annalist.llm.time.sleep", sleeps.append):
            try:
                result = llm(str(workdir), "extract", "Read chapter 1.", chapter=1)
            except LLMUnavailable as exc:
                result = exc
        return result, sleeps, read_jsonl(workdir / "calls.jsonl"), server.requests

    def test_rate_limit_waits_at_least_retry_after_then_succeeds(self):
        result, sleeps, calls, requests = self.run_llm([(429, {"Retry-After": "90"}, '{"error": "slow down"}'),
                                                         (200, {}, OK)])
        self.assertEqual(result, {"answer": 42})
        self.assertEqual(sleeps, [90])
        self.assertEqual(len(requests), 2)
        self.assertIn("HTTP 429", calls[0]["error"])
        self.assertIsNone(calls[1]["error"])
        self.assertEqual(calls[1]["usage"], {"input_tokens": 5, "output_tokens": 3})

    def test_server_errors_back_off_then_stop_the_command(self):
        result, sleeps, calls, requests = self.run_llm([(503, {}, "overloaded")] * (len(BACKOFF_S) + 1))
        self.assertIsInstance(result, LLMUnavailable)
        self.assertEqual(sleeps, list(BACKOFF_S))
        self.assertEqual(len(requests), len(BACKOFF_S) + 1)
        self.assertTrue(all("HTTP 503" in c["error"] for c in calls))

    def test_rejected_request_stops_at_once(self):
        result, sleeps, calls, requests = self.run_llm([(401, {}, '{"error": "bad key"}')])
        self.assertIsInstance(result, LLMUnavailable)
        self.assertIn("HTTP 401", str(result))
        self.assertEqual(sleeps, [])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
