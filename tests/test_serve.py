import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from annalist.serve import make_server, NOTES_FILE
from tests.test_build import ROOT, site_views
from tests.test_category_table import table_wiki


def call(url, body=None):
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read()


class ServeNotesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)
        (self.workdir / "site").mkdir()
        (self.workdir / "site" / "index.html").write_text("<!doctype html><title>Wiki</title>", encoding="utf-8")
        (self.workdir / "book.json").write_text(json.dumps({"review_tools": True}), encoding="utf-8")
        self.server = make_server(self.workdir, port=0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, note):
        return call(self.base + "/api/notes", json.dumps(note).encode())

    def test_the_site_is_served_and_a_note_is_saved_with_its_page_and_chapter(self):
        self.assertEqual(call(self.base + "/")[0], 200)
        self.assertEqual(json.loads(call(self.base + "/api/notes")[1]), {"notes": []})
        status, body = self.post({"page": "e:abc", "title": "Ada Marsh", "chapter": 12, "url": "#e:abc@12", "text": "  Not her brother.  "})
        self.assertEqual((status, json.loads(body)), (201, {"ok": True, "count": 1}))
        saved = [json.loads(line) for line in (self.workdir / NOTES_FILE).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(saved), 1)
        self.assertEqual({k: saved[0][k] for k in ("page", "title", "chapter", "url", "text")},
                         {"page": "e:abc", "title": "Ada Marsh", "chapter": 12, "url": "#e:abc@12", "text": "Not her brother."})
        self.assertIn("ts", saved[0])
        self.post({"page": "home", "title": "Home", "chapter": 3, "url": "", "text": "Second"})
        self.assertEqual([n["text"] for n in json.loads(call(self.base + "/api/notes")[1])["notes"]], ["Not her brother.", "Second"])

    def test_a_bad_note_is_refused_and_nothing_is_saved(self):
        for body in (b"not json", json.dumps([1]).encode(), json.dumps({"page": "home", "chapter": 1, "text": "   "}).encode(),
                     json.dumps({"page": "home", "chapter": "1", "text": "x"}).encode(), json.dumps({"page": "home", "chapter": True, "text": "x"}).encode()):
            self.assertEqual(call(self.base + "/api/notes", body)[0], 400, body)
        self.assertEqual(call(self.base + "/elsewhere", b"{}")[0], 404)
        self.assertFalse((self.workdir / NOTES_FILE).exists())

    def test_a_note_may_answer_a_check_with_a_known_verdict(self):
        base = {"page": "e:abc", "title": "Wren", "chapter": 4, "url": "", "text": "Looks right"}
        self.assertEqual(self.post({**base, "check": "c1", "verdict": "right"})[0], 201)
        self.assertEqual(self.post({**base, "check": "c2", "verdict": "maybe"})[0], 400)
        self.assertEqual(self.post({**base, "check": 7, "verdict": "wrong"})[0], 400)
        notes = json.loads(call(self.base + "/api/notes")[1])["notes"]
        self.assertEqual([(n["check"], n["verdict"]) for n in notes], [("c1", "right")])

    def test_notes_are_off_unless_book_json_turns_the_review_tools_on(self):
        (self.workdir / "book.json").write_text(json.dumps({"title": "Wiki"}), encoding="utf-8")
        server = make_server(self.workdir, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            self.assertEqual(call(base + "/")[0], 200)
            self.assertEqual(call(base + "/api/notes")[0], 404)
            self.assertEqual(call(base + "/api/notes", json.dumps({"page": "home", "chapter": 1, "text": "x"}).encode())[0], 404)
            self.assertFalse((self.workdir / NOTES_FILE).exists())
        finally:
            server.shutdown()
            server.server_close()

    def test_serving_needs_a_built_site(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(SystemExit):
            make_server(empty, port=0)


class VolumeIndicatorTest(unittest.TestCase):
    def test_the_slider_names_the_volume_and_marks_its_last_chapter(self):
        wiki, _ = table_wiki()
        wiki["volumes"] = [{"id": "v1", "name": "Book One", "from": 1, "to": 2, "arcs": []},
                           {"id": "v2", "name": "Book Two", "from": 3, "to": 4, "arcs": []}]
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            path = Path(tmp) / "wiki.json"
            path.write_text(json.dumps(wiki), encoding="utf-8")
            out = site_views(path, "volumeat:1@1", "volumeat:2@2", "volumeat:3@3", "volumeat:9@4")
        self.assertEqual(out["volumeat:1@1"], {"id": "v1", "to": 2, "end": False, "label": "Book One · 1 of 2"})
        self.assertEqual(out["volumeat:2@2"], {"id": "v1", "to": 2, "end": True, "label": "End of Book One"})
        self.assertEqual(out["volumeat:3@3"]["label"], "Book Two · 1 of 2")
        self.assertIsNone(out["volumeat:9@4"])
