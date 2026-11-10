from pathlib import Path

from .files import read_json, read_jsonl, write_json, write_jsonl
from .profile import profile_observations
from .text import check_quote, verified_quotes


def cmd_verify(args):
    workdir = Path(args.workdir)
    questions = read_jsonl(workdir / "questions.jsonl")
    failures = []
    for kind in ("facts", "relations"):
        rows = read_jsonl(workdir / f"{kind}.jsonl")
        quote_total = quote_pass = 0
        for f in rows:
            f.update(verified_quotes(workdir, f["chapter"], f["quotes"] + f.pop("dropped_quotes", [])))
            dropped = f.get("dropped_quotes", [])
            quote_total += len(f["quotes"]) + len(dropped)
            quote_pass += len(f["quotes"])
            failures += [(f["id"], f["chapter"], q) for q in dropped or ([] if f["quotes"] else ["(no quote)"])]
        write_jsonl(workdir / f"{kind}.jsonl", rows)
        f_pass = sum(f["quote_ok"] for f in rows)
        print(f"{kind}: {f_pass}/{len(rows)} with a verified quote ({100 * f_pass / max(1, len(rows)):.1f}%), "
              f"{quote_pass}/{quote_total} quotes verified ({100 * quote_pass / max(1, quote_total):.1f}%)")
    q_checks = q_pass = 0
    for q in questions:
        found = check_quote(workdir, q["chapter"], q["quote"])
        q["quote_ok"], q["quote_ratio"] = found["ok"], found["ratio"]
        checks = [(q["id"], q["chapter"], found, q["quote"])]
        if q.get("status") == "resolved":
            rfound = check_quote(workdir, q["resolved_chapter"], q["resolve_quote"])
            q["resolve_quote_ok"] = rfound["ok"]
            checks.append((q["id"] + " (resolution)", q["resolved_chapter"], rfound, q["resolve_quote"]))
        for qid, ch, res, quote in checks:
            q_checks += 1
            q_pass += res["ok"]
            if not res["ok"]:
                failures.append((qid, ch, quote))
    write_jsonl(workdir / "questions.jsonl", questions)
    print(f"questions: {q_pass}/{q_checks} quotes verified ({100 * q_pass / max(1, q_checks):.1f}%)")
    profiles = read_json(workdir / "profiles.json", {"characters": {}})
    o_total = o_pass = 0
    for name, profile in profiles["characters"].items():
        for group, key, o in profile_observations(profile):
            o.update(verified_quotes(str(workdir), o["chapter"], o["quotes"] + o.pop("dropped_quotes", [])))
            o_total += 1
            o_pass += o["quote_ok"]
            failures += [(f"{name} {key}", o["chapter"], q) for q in o.get("dropped_quotes") or ([] if o["quotes"] else ["(no quote)"])]
    if profiles["characters"]:
        write_json(workdir / "profiles.json", profiles)
        print(f"profiles: {o_pass}/{o_total} observations with a verified quote ({100 * o_pass / max(1, o_total):.1f}%)")
    for qid, ch, quote in failures:
        print(f"FAIL {qid} ch{ch}: {quote}")
