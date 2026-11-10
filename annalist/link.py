import re
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path

from .families import wording_key
from .files import log, read_json, write_json
from .llm import cached_llm
from .names import content_words, name_key, name_pattern, NameIndex, names_of, ROLE_WORDS, short_names
from .state import load_states, write_derived
from .template import ENTITY_TYPES, UNCATEGORIZED
from .text import chapter_text, QUOTE_CHARS, sentence_of, text_window, verified_quotes


POSSESSION = "owned by"

VOCABULARY = {
    "place": ("lives at", "works at", "studies at", "born in", "visits", "imprisoned at", "owns"),
    "organization": ("member of", "works for", "leads", "studies at", "founded"),
    "artifact": ("owns", "carries", "made", "uses", "handed over", "received"),
}

POSSESSIVE = re.compile(r"^(.+?)'s\s+(.+)$")

OWNERS = ("character", "organization", "deity")

LINK_PROMPT = """A wiki about a novel files facts under its entries. Each fact below names a character and a place, organization, or item. Label the relationship the fact states between the two, read as "character label other", with one of the labels for the other's type, or "none".

LABELS by the other's type:
{labels}

FACTS (fact id | character -> other [type]: fact):
{facts}

Reply with one JSON object: {{"labels": [{{"fact": "fact id", "target": "the other's name as listed", "type": "a label or none"}}]}}, one item per line above.
Rules:
- Choose a label only when the fact itself states that relationship. A fact that only names both, or tells of something that is none of the labels, is "none".
- "lives at" is the character's home; a place the character only goes to is "visits".
- Label what the fact says even when a character only believes or claims it.
"""


def type_label(etype):
    return ENTITY_TYPES[etype].label.lower()


def short_owners(kb):
    owners = {}
    for k, e in kb.entities.items():
        if e["type"] == "character":
            for w in short_names(kb, k):
                owners.setdefault(name_key(w), set()).add(k)
    return {w: ks.pop() for w, ks in owners.items() if len(ks) == 1}


def owner_of(kb, prefix, shorts):
    words = content_words(prefix)
    while words and words[0].lower() in ROLE_WORDS:
        words = words[1:]
    found = ((c if k == kb.resolve(c) else k, k) for c in [prefix, " ".join(words)] + words[-1:]
             for k in (kb.resolve(c), shorts().get(name_key(c))))
    return next(((named, k) for named, k in found if k and kb.entities[k]["type"] in OWNERS), (None, None))


def literal(text):
    return re.compile(r"(?<!\w)" + re.escape(text).replace("'", "['’]") + r"(?:e?s)?(?!\w)", re.I)


def sentence_at(text, start, end, limit=300):
    quote = sentence_of(text, start, end).strip()
    return quote if len(quote) <= limit else text_window(text, start, end, (limit - (end - start)) // 3)


def possessives(workdir, kb):
    book = read_json(workdir / "book.json", {})
    possessed = set(VOCABULARY) | set(book.get("power_types") or {}) | {UNCATEGORIZED}
    shorts = cache(lambda: short_owners(kb))
    for k, e in kb.entities.items():
        if e["type"] not in possessed:
            continue
        for name in names_of(e):
            m = POSSESSIVE.match(name.translate(QUOTE_CHARS))
            named, owner = owner_of(kb, m.group(1), shorts) if m else (None, None)
            if owner and owner != k:
                yield k, name, named, literal(m.group(0)), literal(m.group(1) + "'s"), literal(m.group(2).split()[-1])
                break


def possessive_row(k, owner, n, quote):
    return {"chapter": n, "source": k, "target": owner, "type": POSSESSION, "detail": "", "quotes": [quote], "asserted_by": "narrator",
            "status": "stated", "timeline": "main"}


def possessive_rows(workdir, kb):
    pending = {k: rest for k, *rest in possessives(workdir, kb)}
    rows = []
    for n in sorted(kb.synopses):
        text = chapter_text(workdir, n)
        for k, (name, owner, full, _, _) in list(pending.items()):
            m = full.search(text)
            if m:
                del pending[k]
                rows.append(possessive_row(name, owner, n, sentence_at(text, m.start(), m.end())))
    for k, (name, owner, _, prefix, head) in pending.items():
        n = kb.entities[k]["first_chapter"]
        text = chapter_text(workdir, n)
        quote = next((q for m in prefix.finditer(text) if head.search(q := sentence_at(text, m.start(), m.end()))), None)
        if quote:
            rows.append(possessive_row(name, owner, n, quote))
    return rows


def typed_name_rows(workdir, kb):
    ladder = set((read_json(workdir / "book.json", {}).get("ladder") or {}).values())
    rows = []
    for k, e in sorted(kb.entities.items()):
        for name in names_of(e):
            base = re.sub(rf"\s+{re.escape(e['type'])}$", "", name, flags=re.I)
            other = kb.resolve(base) if base != name else None
            if not other or other == k or kb.entities[other]["type"] in (e["type"], UNCATEGORIZED) or {e["type"], kb.entities[other]["type"]} <= ladder:
                continue
            start = max(e["first_chapter"], kb.entities[other]["first_chapter"])
            hit = next(((n, m) for n in sorted(kb.synopses) if n >= start for m in [literal(name).search(chapter_text(workdir, n))] if m), None)
            if hit:
                n, m = hit
                rows.append({"chapter": n, "source": name, "target": base, "type": f"{e['type']} of", "detail": "",
                             "quotes": [sentence_at(chapter_text(workdir, n), m.start(), m.end())], "asserted_by": "narrator",
                             "status": "stated", "timeline": "main"})
                break
    return rows


def as_named(kb, fact, k):
    if k == fact["entity"]:
        return fact.get("filed") or k
    return next((n for n in names_of(kb.entities[k]) if name_pattern([n]).search(fact["claim"])), k)


def fact_candidates(workdir, kb):
    kinds = {k: e["type"] for k, e in kb.entities.items() if e["type"] == "character" or e["type"] in VOCABULARY}
    index = NameIndex({k: names_of(kb.entities[k]) for k in kinds})
    found = []
    for f in kb.facts:
        a = f["entity"]
        if a not in kinds:
            continue
        pairs = [(a, b) if kinds[a] == "character" else (b, a) for b in sorted(index.find(f["claim"]) - {a})
                 if (kinds[a] == "character") != (kinds[b] == "character")]
        quotes = verified_quotes(workdir, f["chapter"], f["quotes"])["quotes"] if pairs else []
        found += [{"fact": f, "source": as_named(kb, f, s), "target": as_named(kb, f, t), "type": kinds[t], "quotes": quotes}
                  for s, t in pairs if quotes]
    return found


def label_batch(workdir, batch):
    lines = [f"- {c['fact']['id']} | {c['source']} -> {c['target']} [{type_label(c['type'])}]: {c['fact']['claim']}" for c in batch]
    labels = "\n".join(f"- {type_label(t)}: {', '.join(v)}" for t, v in VOCABULARY.items())
    reply = cached_llm(workdir, "link", LINK_PROMPT.format(labels=labels, facts="\n".join(lines)),
                       chapter=batch[0]["fact"]["chapter"],
                       check=lambda r: None if isinstance(r.get("labels"), list) else "no labels list")
    listed = {(c["fact"]["id"], name_key(c["target"])): c for c in batch}
    rows, rejected = [], []
    for item in reply["labels"]:
        if not isinstance(item, dict):
            continue
        c = listed.get((str(item.get("fact") or ""), name_key(item.get("target") or "")))
        rtype = str(item.get("type") or "").strip().lower()
        if c is None or rtype == "none":
            continue
        f = c["fact"]
        if rtype not in VOCABULARY[c["type"]]:
            rejected.append((f["chapter"], {"label": item, "reason": f"not a label for {type_label(c['type'])}"}))
            continue
        rows.append({"chapter": f["chapter"], "source": c["source"], "target": c["target"], "type": rtype, "detail": "", "quotes": c["quotes"],
                     "asserted_by": f["asserted_by"], "status": f["status"], "timeline": f["timeline"], "fact": f["id"]})
    return rows, rejected


def cmd_link(args, batch=40):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir, filled=("relate.json",))
    found = fact_candidates(workdir, kb)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        labelled = list(pool.map(lambda i: label_batch(workdir, found[i:i + batch]), range(0, len(found), batch)))
    known = {(r["source"], r["target"], wording_key(r["type"]), r["chapter"]) for r in kb.relations}
    chapters = {}
    for row in possessive_rows(workdir, kb) + typed_name_rows(workdir, kb) + [r for rows, _ in labelled for r in rows]:
        key = (kb.resolve(row["source"]), kb.resolve(row["target"]), wording_key(row["type"]), row["chapter"])
        if key not in known:
            known.add(key)
            chapters.setdefault(row["chapter"], {"relations": [], "rejected": []})["relations"].append(row)
    for _, rejected in labelled:
        for n, r in rejected:
            chapters.setdefault(n, {"relations": [], "rejected": []})["rejected"].append(r)
    write_json(workdir / "link.json", {"chapters": {str(n): chapters[n] for n in sorted(chapters)}})
    added = sum(len(c["relations"]) for c in chapters.values())
    log(workdir, f"link: {added} relations added from possessive names and {len(found)} character facts")
    write_derived(workdir, load_states(workdir))
