import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .estimate import prompt_pricer
from .files import log, read_json, state_paths, write_json
from .backends import load_settings
from .llm import Budget, BudgetSpent, cached_llm, cached_reply, UNLIMITED
from .names import name_key, parse_aliases
from .state import FILLED, relation_key, VET_FILE
from .text import chapter_text, locate_quote, text_window

VET_PROMPT = """A wiki built from a novel states relations between its entries. Each relation below comes with the passage of chapter {chapter} it was drawn from, its quote marked >>> <<<. Judge each relation against its own passage alone, never against what you know of the novel.

{relations}

Judge each relation, exactly as worded and in this direction:
- correct: the passage states the relation or clearly implies it, with the right kind of tie, in the right direction, between these two.
- wrong: the passage shows a different tie between them (another kind of kin, the reverse direction, another person), or contradicts it.
- unsupported: the passage neither shows nor contradicts it.
A relation marked belief only needs the passage to show that the named character believes, suspects, or claims it. A relation marked implied needs the passage to strongly suggest it.

Reply with one JSON object: {{"verdicts": [{{"id": "...", "verdict": "correct" or "wrong" or "unsupported", "reason": "one sentence"}}]}}, one verdict per relation.
"""

VERDICTS = ("correct", "wrong", "unsupported")
RADIUS = 700
BATCH = 12


def filled_rows(workdir):
    rows = []
    for name in FILLED:
        for entry in read_json(Path(workdir) / name, {"chapters": {}})["chapters"].values():
            rows += entry["relations"]
    return sorted(rows, key=lambda r: r["chapter"])


def names_by_chapter(workdir):
    seen = {}
    for path in state_paths(workdir):
        state = json.loads(path.read_text(encoding="utf-8"))
        for rec in state["extraction"].get("entities") or []:
            if isinstance(rec, dict) and rec.get("name"):
                names = [str(rec["name"])] + parse_aliases(rec.get("aliases"))
                for a in names:
                    known = seen.setdefault(name_key(a), {})
                    for b in names:
                        if name_key(b) != name_key(a):
                            known.setdefault(b, state["chapter"])
    return seen


def also_called(seen, name, chapter):
    names = [b for b, first in seen.get(name_key(name), {}).items() if first <= chapter]
    return ", ".join(f'"{b}"' for b in names) or "no other names"


def passage(text, quote):
    found = locate_quote(text, quote)
    if not found["ok"] or not found["span"]:
        return f">>>{quote}<<<"
    start, end = found["span"]
    window = text_window(text, start, end, RADIUS)
    lo = text.find(window)
    return window[:start - lo] + ">>>" + text[start:end] + "<<<" + window[end - lo:]


def item(row, text, seen):
    status = row.get("status", "stated")
    mark = "" if status == "stated" else f" [{status}, asserted by {row.get('asserted_by') or 'narrator'}]"
    detail = f" {row['detail']}" if row.get("detail") else ""
    passages = "\n".join(passage(text, q) for q in row["quotes"][:2])
    return (f"id: {relation_key(row)}\nRelation: \"{row['source']}\" {row['type']} \"{row['target']}\"{detail}{mark}\n"
            f"\"{row['source']}\" is also called: {also_called(seen, row['source'], row['chapter'])}\n"
            f"\"{row['target']}\" is also called: {also_called(seen, row['target'], row['chapter'])}\n"
            f"<passage>\n{passages}\n</passage>")


def asks(workdir, rows):
    seen = names_by_chapter(workdir)
    by_chapter = {}
    for row in rows:
        by_chapter.setdefault(row["chapter"], []).append(row)
    out = []
    for n, chapter_rows in sorted(by_chapter.items()):
        text = chapter_text(workdir, n)
        for i in range(0, len(chapter_rows), BATCH):
            batch = chapter_rows[i:i + BATCH]
            prompt = VET_PROMPT.format(chapter=n, relations="\n\n".join(item(r, text, seen) for r in batch))
            out.append((n, prompt, [relation_key(r) for r in batch]))
    return out


def verdicts_of(reply, keys):
    found = {}
    for v in reply.get("verdicts") or []:
        if isinstance(v, dict) and str(v.get("id")) in keys and v.get("verdict") in VERDICTS:
            found[str(v["id"])] = {"verdict": v["verdict"], "reason": str(v.get("reason") or "")}
    return found


def vet(workdir, jobs, dry_run=False, budget=None):
    workdir = Path(workdir).resolve()
    rows = filled_rows(workdir)
    current = {relation_key(r) for r in rows}
    stored = {k: v for k, v in read_json(workdir / VET_FILE, {"verdicts": {}})["verdicts"].items() if k in current}
    todo = asks(workdir, [r for r in rows if relation_key(r) not in stored])
    settings = load_settings(workdir)
    price = prompt_pricer(workdir, settings)
    misses = {prompt: price("vet", prompt) for _, prompt, _ in todo if cached_reply(workdir, "vet", prompt, settings) is None}
    cost = None if None in misses.values() else sum(misses.values())
    print(f"vet: {len(rows)} relations, {len(stored)} checked before, {len(todo)} prompts, {len(misses)} not answered yet")
    print(f"price: {'unknown' if cost is None else f'${cost:,.2f}'}")
    if dry_run:
        return None
    gate = UNLIMITED if budget is None else Budget(budget, {("vet", p): c or 0.0 for p, c in misses.items()})
    check = lambda r: None if isinstance(r.get("verdicts"), list) else "no verdicts list"
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [(keys, pool.submit(cached_llm, workdir, "vet", prompt, chapter=n, check=check, settings=settings, gate=gate))
                   for n, prompt, keys in todo]
        try:
            for keys, future in futures:
                stored.update(verdicts_of(future.result(), set(keys)))
        except BudgetSpent as exc:
            for _, future in futures:
                future.cancel()
            write_json(workdir / VET_FILE, {"verdicts": stored})
            sys.exit(f"annalist vet: {exc}; the verdicts paid for are kept")
    write_json(workdir / VET_FILE, {"verdicts": stored})
    dropped = sum(v["verdict"] != "correct" for v in stored.values())
    log(workdir, f"vet: {len(stored)} of {len(rows)} relations checked, {dropped} left out as wrong or unsupported")
    return stored
