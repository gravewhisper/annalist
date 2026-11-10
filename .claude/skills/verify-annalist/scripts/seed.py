"""Write a fake-backend run directory for the five-chapter test book.

Usage: python3 seed.py WORKDIR

Writes WORKDIR/run/script.json (the scripted replies the test suite uses),
WORKDIR/run/book.json (backend: fake), and WORKDIR/bin/claude, a stub that
exits 1 so any call that escapes the fake backend fails instead of spending.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tests.test_build import build_script  # noqa: E402

work = Path(sys.argv[1]).resolve()
run = work / "run"
run.mkdir(parents=True, exist_ok=True)
(run / "script.json").write_text(json.dumps(build_script()), encoding="utf-8")
(run / "book.json").write_text(json.dumps({"backend": {"name": "fake", "script": "script.json"}}), encoding="utf-8")
stub = work / "bin" / "claude"
stub.parent.mkdir(exist_ok=True)
stub.write_text("#!/bin/sh\necho 'verify-annalist: real claude call blocked' >&2\nexit 1\n")
stub.chmod(0o755)
print(run)
