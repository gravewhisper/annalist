import json
import os
import sys
import threading
import time
from pathlib import Path


def write_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path, data):
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path, rows):
    write_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


APPEND_LOCK = threading.Lock()


def append_line(path, line):
    with APPEND_LOCK, open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def log(workdir, message):
    print(message, file=sys.stderr, flush=True)
    append_line(Path(workdir) / "read.log", f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}")


def read_json(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
