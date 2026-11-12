import json
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NOTES_FILE = "reader-notes.jsonl"
NOTES_PATH = "/api/notes"
MAX_BODY = 64_000
FIELDS = {"page": str, "title": str, "chapter": int, "url": str, "text": str}


def read_notes(workdir):
    path = Path(workdir) / NOTES_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_note(body):
    """A reader's note as the site posts it, or ValueError naming what is wrong."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc}")
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    note = {}
    for key, kind in FIELDS.items():
        value = data.get(key, "" if kind is str else None)
        if not isinstance(value, kind) or isinstance(value, bool):
            raise ValueError(f"{key} must be {kind.__name__}")
        note[key] = value.strip() if kind is str else value
    if not note["text"]:
        raise ValueError("text is empty")
    return note


class NotesHandler(SimpleHTTPRequestHandler):
    workdir = None
    lock = threading.Lock()

    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == NOTES_PATH:
            return self.reply(200, {"notes": read_notes(self.workdir)})
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != NOTES_PATH:
            return self.reply(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self.reply(400, {"error": f"body must be 1 to {MAX_BODY} bytes"})
        try:
            note = parse_note(self.rfile.read(length).decode("utf-8", "replace"))
        except ValueError as exc:
            return self.reply(400, {"error": str(exc)})
        note = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **note}
        with self.lock:
            with open(Path(self.workdir) / NOTES_FILE, "a", encoding="utf-8") as out:
                out.write(json.dumps(note, ensure_ascii=False) + "\n")
            count = len(read_notes(self.workdir))
        return self.reply(201, {"ok": True, "count": count})

    def log_message(self, *args):
        pass


def make_server(workdir, port=8765, host="127.0.0.1"):
    workdir = Path(workdir).resolve()
    site = workdir / "site"
    if not (site / "index.html").exists():
        raise SystemExit(f"annalist serve: no site at {site}; run the export stage first")
    handler = type("Handler", (NotesHandler,), {"workdir": workdir,
                                                "__init__": lambda self, *a, **k: NotesHandler.__init__(self, *a, directory=str(site), **k)})
    return ThreadingHTTPServer((host, port), handler)


def cmd_serve(args):
    server = make_server(args.workdir, args.port)
    print(f"serving {Path(args.workdir).resolve() / 'site'} at http://127.0.0.1:{server.server_address[1]}/")
    print(f"notes from the report button go to {Path(args.workdir).resolve() / NOTES_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
