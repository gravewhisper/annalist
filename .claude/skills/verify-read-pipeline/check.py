#!/usr/bin/env python3
"""Model-check the pipelined read stage (annalist/read.py) with TLC.

Usage, from the repo root:
  python3 .claude/skills/verify-read-pipeline/check.py            # drift report + TLC at N=5, MaxFaults=4
  python3 .claude/skills/verify-read-pipeline/check.py --mutants  # each broken variant must fail its rule
  python3 .claude/skills/verify-read-pipeline/check.py --bounds 6 4
  python3 .claude/skills/verify-read-pipeline/check.py --resync   # record covered code as matching the model

Exit codes: 0 pass and code unchanged since the sync commit; 1 a rule broke
(or a mutant was not caught); 2 tool or model error; 3 TLC passed but covered
code changed since the sync commit, so the model needs another look.
Logs and traces go to runs/verify-read-pipeline/<timestamp>/.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent
ROOT = SKILL.parents[2]
MODEL = SKILL / "model"
COVERAGE = SKILL / "coverage.json"
TLA_VERSION = "v1.7.4"
TLA_SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TLA_URL = f"https://github.com/tlaplus/tlaplus/releases/download/{TLA_VERSION}/tla2tools.jar"
RULES = ["SavedInOrder", "ReadAgainstKept", "OnlyPreviousUnchecked", "Resumable", "CleanRunFinishes"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tla_jar():
    candidates = [os.environ.get("TLA2TOOLS"), Path.home() / ".cache/annalist-tla" / TLA_VERSION / "tla2tools.jar",
                  Path.home() / ".cache/rcc-tla/1.7.4/tla2tools.jar"]
    for c in candidates:
        if c and Path(c).exists() and sha256(c) == TLA_SHA256:
            return Path(c)
    dest = Path(candidates[1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading tla2tools {TLA_VERSION} to {dest}", file=sys.stderr)
    urllib.request.urlretrieve(TLA_URL, dest)
    if sha256(dest) != TLA_SHA256:
        dest.unlink()
        sys.exit("tla2tools.jar checksum mismatch; refusing to run")
    return dest


def fingerprint(file, name):
    """AST digest of a module-level function, or of Class.method; ignores comments and formatting."""
    scope = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    *owners, leaf = name.split(".")
    for owner in owners:
        scope = next((c for c in scope.body if isinstance(c, ast.ClassDef) and c.name == owner), None)
        if scope is None:
            return None
    for node in scope.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == leaf:
            return hashlib.sha256(ast.dump(node).encode()).hexdigest()[:16]
    return None


def drift():
    cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
    changed = []
    for item in cov["covers"]:
        now = fingerprint(item["file"], item["function"])
        if now != item["fingerprint"]:
            changed.append((item, now))
    return cov, changed


def run_tlc(spec_dir, n, faults, out):
    cfg = (spec_dir / "ReadPipeline.cfg").read_text(encoding="utf-8")
    cfg = re.sub(r"N = \d+", f"N = {n}", cfg)
    cfg = re.sub(r"MaxFaults = \d+", f"MaxFaults = {faults}", cfg)
    (spec_dir / "run.cfg").write_text(cfg, encoding="utf-8")
    cmd = ["java", "-Xmx2g", "-XX:+UseParallelGC", "-cp", str(tla_jar()), "tlc2.TLC", "-workers", "2",
           "-metadir", str(out / "meta"), "-config", "run.cfg", "ReadPipeline.tla"]
    began = time.time()
    proc = subprocess.run(cmd, cwd=spec_dir, capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    (out / "tlc.log").write_text(log, encoding="utf-8")
    shutil.rmtree(out / "meta", ignore_errors=True)
    m = re.search(r"Invariant (\w+) is violated", log)
    states = re.findall(r"([\d,]+) distinct states found", log)
    result = {"seconds": round(time.time() - began, 1), "states": states[-1] if states else "?"}
    if m:
        result.update(verdict="violated", rule=m.group(1), steps=re.findall(r"^State \d+: <(\w+)", log, re.M))
    elif "Deadlock reached" in log:
        result.update(verdict="deadlock", steps=re.findall(r"^State \d+: <(\w+)", log, re.M))
    elif "No error has been found" in log:
        result.update(verdict="pass")
    else:
        result.update(verdict="error", tail=log[-1500:])
    return result


def scratch(tag):
    out = ROOT / "runs" / "verify-read-pipeline" / f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def check(n, faults):
    cov, changed = drift()
    out = scratch("check")
    spec = out / "model"
    shutil.copytree(MODEL, spec)
    r = run_tlc(spec, n, faults, out)
    (out / "result.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    print(f"TLC {TLA_VERSION}, N={n} chapters, MaxFaults={faults}: {r['verdict']} "
          f"({r['states']} distinct states, {r['seconds']}s). Log: {out / 'tlc.log'}")
    if r["verdict"] == "violated":
        print(f"RULE BROKEN: {r['rule']}. Shortest path: {' -> '.join(r['steps'])}")
    elif r["verdict"] == "deadlock":
        print(f"DEADLOCK after: {' -> '.join(r['steps'])}")
    elif r["verdict"] == "error":
        print(r["tail"])
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    if changed:
        print(f"DRIFT: covered code changed since sync commit {cov['sync_commit']} (now {head}):")
        for item, now in changed:
            print(f"  {item['file']}:{item['function']} ({'removed' if now is None else 'changed'}); model actions: {item['model']}")
    else:
        print(f"Covered code matches sync commit {cov['sync_commit']}.")
    if r["verdict"] in ("violated", "deadlock"):
        return 1
    if r["verdict"] == "error":
        return 2
    return 3 if changed else 0


def mutants(n, faults):
    base = (MODEL / "ReadPipeline.tla").read_text(encoding="utf-8")
    bad = 0
    for m in json.loads((MODEL / "mutants.json").read_text(encoding="utf-8")):
        text = base
        for old, new in m["edits"]:
            if text.count(old) != 1:
                print(f"{m['name']}: edit no longer applies to the model; update mutants.json")
                bad = 1
                break
            text = text.replace(old, new)
        else:
            out = scratch(f"mutant-{m['name']}")
            spec = out / "model"
            shutil.copytree(MODEL, spec)
            (spec / "ReadPipeline.tla").write_text(text, encoding="utf-8")
            r = run_tlc(spec, n, faults, out)
            caught = r["verdict"] == "violated" and r.get("rule") == m["expect"]
            bad |= not caught
            print(f"{'caught' if caught else 'MISSED'} {m['name']}: expected {m['expect']}, got "
                  f"{r['verdict']} {r.get('rule', '')} ({r['seconds']}s). {m['code']}")
    return bad


def resync():
    cov = json.loads(COVERAGE.read_text(encoding="utf-8"))
    files = sorted({c["file"] for c in cov["covers"]})
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *files], capture_output=True, text=True).stdout
    if dirty:
        sys.exit(f"refusing to resync: covered files have uncommitted changes:\n{dirty}Commit first, so the sync commit names the code the model describes.")
    for c in cov["covers"]:
        c["fingerprint"] = fingerprint(c["file"], c["function"])
        if c["fingerprint"] is None:
            sys.exit(f"{c['file']}:{c['function']} no longer exists; update coverage.json and the model first")
    cov["sync_commit"] = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    COVERAGE.write_text(json.dumps(cov, indent=2) + "\n", encoding="utf-8")
    print(f"coverage.json now records sync commit {cov['sync_commit']}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutants", action="store_true")
    ap.add_argument("--resync", action="store_true")
    ap.add_argument("--bounds", nargs=2, type=int, metavar=("N", "MAXFAULTS"))
    a = ap.parse_args()
    if a.resync:
        return resync()
    if a.mutants:
        return mutants(*(a.bounds or (4, 3)))
    return check(*(a.bounds or (5, 4)))


if __name__ == "__main__":
    sys.exit(main())
