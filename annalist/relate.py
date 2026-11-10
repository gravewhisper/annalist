import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .families import wording_key
from .files import log, read_json, write_json
from .llm import cached_llm, tally
from .names import character_words, name_key, name_pattern, names_of, short_names
from .state import load_states, timeline_line, write_derived
from .text import chapter_text, locate_quote


RELATE_PROMPT = """You are filling in the relationships of a wiki about a novel, one chapter at a time. Below are the wiki's entries as known at chapter {n}, the pairs of entries this chapter names close together, the relations the wiki already records between them, and the chapter text.

List every relationship between two entries that THIS chapter shows and the KNOWN list lacks: kinship, marriage, romance or courtship, employment or service, residence, ownership, membership, alliance, hostility, correspondence, custody, and similar. Include a relationship a character asserts or suspects, with its status.

ENTRIES (name [type] (aliases)):
{entries}

PAIRS named close together in this chapter:
{pairs}

KNOWN relations between these entries:
{known}
{timelines}
CHAPTER {n}: {title}
<chapter>
{text}
</chapter>

Reply with one JSON object: {{"relations": [{{"source": "entry name", "type": "...", "target": "entry name", "detail": "", "quote": "...", "asserted_by": "narrator", "status": "stated"{timeline_key}}}]}}
Rules:
- type: the predicate alone, a verb phrase or a role that reads "source type target" as a sentence ("suspects", "gave", "member of", "father of"). Never fold an object, a third entry, or a circumstance into it.
- detail: whatever the sentence needs after the target, read as "source type target detail" ("of impersonating the baron", "to the innkeeper as payment"); "" when nothing. Write names in type and detail as the book writes them.
- Use only this chapter's text. Never use what you know of the novel beyond it, and never a relationship a later chapter reveals.
- source and target are entry names exactly as listed above, and two different entries.
- When a pronoun or possessive refers to a person who is a listed entry, the relationship belongs to that entry, never to a nearby object, place, or container.
- quote: one contiguous span of one or two sentences copied exactly, character for character, from this chapter, at most 300 characters, that shows the relationship. The quote or the sentences right around it must name both entries. This is checked by machine.
- asserted_by: "narrator" when the narration states it, otherwise the name of the character who says or thinks it.
- status: "stated" when the narrative presents it as true; "implied" when the text strongly suggests it; "belief" when a character believes, suspects, or claims it.
- An empty list is a fine answer when the chapter shows nothing new.
"""


MAX_NEW_PAIRS = 2


def co_mentioned(text, patterns, radius):
    hits = sorted((m.start(), k) for k, p in patterns.items() for m in p.finditer(text))
    pairs = {}
    for i, (pos, a) in enumerate(hits):
        for pos2, b in hits[i + 1:]:
            if pos2 - pos > radius:
                break
            if a != b:
                key = tuple(sorted((a, b)))
                pairs[key] = pairs.get(key, 0) + 1
    return pairs


def chapter_request(workdir, n, title, radius, max_pairs):
    kb = load_states(workdir, until=n, filled=())
    text = chapter_text(workdir, n)
    words = character_words(kb)
    patterns = {k: name_pattern(names_of(e) + short_names(kb, k, words)) for k, e in kb.entities.items()}
    pairs = sorted(co_mentioned(text, patterns, radius).items(), key=lambda p: (-p[1], p[0]))[:max_pairs]
    if not pairs:
        return None
    named = sorted({k for k, e in kb.entities.items() if name_pattern(names_of(e)).search(text)} | {k for (a, b), _ in pairs for k in (a, b)})
    shown = [r for r in kb.relations if r["source"] in named and r["target"] in named]
    known = sorted({" ".join(filter(None, (r["source"], r["type"], r["target"], r["detail"]))) for r in shown})
    entries = []
    for k in named:
        e = kb.entities[k]
        aka = f" ({', '.join(e['aliases'])})" if e["aliases"] else ""
        entries.append(f"- {e['name']} [{e['type']}]{aka}")
    timelines = ""
    if len(kb.timelines) > 1:
        timelines = ("\nTIMELINES so far; give each relation the id of the timeline its scene is set in:\n"
                     + "\n".join(f"- {timeline_line(t)}" for t in kb.timelines.values()) + "\n")
    prompt = RELATE_PROMPT.format(n=n, title=title, text=text, entries="\n".join(entries),
                                  pairs="\n".join(f"- {a} / {b}" for (a, b), _ in pairs),
                                  known="\n".join(f"- {k}" for k in known) or "(none)", timelines=timelines,
                                  timeline_key=', "timeline": "main"' if timelines else "")
    return {"kb": kb, "text": text, "patterns": patterns, "prompt": prompt, "pairs": [pair for pair, _ in pairs],
            "basis": hashlib.sha1("\n\n".join((RELATE_PROMPT, timelines, title, text)).encode()).hexdigest()[:16],
            "known": {(r["source"], wording_key(r["type"]), r["target"]) for r in shown}}


def resolved_pair(kb, pair):
    return tuple(sorted(kb.resolve(name) or name for name in pair))


def reusable_reply(saved, req):
    if not saved or saved["basis"] != req["basis"]:
        return False
    before = {resolved_pair(req["kb"], pair) for pair in saved["pairs"]}
    return len({resolved_pair(req["kb"], pair) for pair in req["pairs"]} - before) <= MAX_NEW_PAIRS


def check_relation(req, raw, n, window):
    kb = req["kb"]
    if not isinstance(raw, dict):
        return None, "not an object"
    source, target = kb.resolve(str(raw.get("source") or "")), kb.resolve(str(raw.get("target") or ""))
    rtype = str(raw.get("type") or "").strip()
    if not source or not target or source == target or not rtype:
        return None, "source or target is not a distinct entry"
    if (source, wording_key(rtype), target) in req["known"]:
        return None, "already known"
    quote = str(raw.get("quote") or "").strip()
    found = locate_quote(req["text"], quote)
    if not found["ok"] or not found["span"]:
        return None, "quote not found in the chapter"
    start, end = found["span"]
    around = req["text"][max(0, start - window):end + window]
    if not (req["patterns"][source].search(around) and req["patterns"][target].search(around)):
        return None, "the quote and the text around it do not name both entries"
    tid = str(raw.get("timeline") or "main")
    status = raw.get("status") if raw.get("status") in ("stated", "implied", "belief") else "stated"
    return {"chapter": n, "source": source, "target": target, "type": rtype, "detail": str(raw.get("detail") or "").strip(), "quotes": [quote],
            "asserted_by": str(raw.get("asserted_by") or "narrator").strip(), "status": status,
            "timeline": tid if tid in kb.timelines else "main"}, None


def relate_chapter(workdir, chapter, radius, max_pairs, window, replies):
    n = chapter["index"]
    req = chapter_request(workdir, n, chapter["title"], radius, max_pairs)
    if req is None:
        return n, {"relations": [], "rejected": []}, None
    saved = replies.get(str(n))
    if reusable_reply(saved, req):
        tally("cached")
        reply = saved["reply"]
    else:
        reply = cached_llm(workdir, "relate", req["prompt"], chapter=n,
                           check=lambda r: None if isinstance(r.get("relations"), list) else "no relations list")
    kept, rejected = [], []
    for raw in reply["relations"]:
        row, reason = check_relation(req, raw, n, window)
        if row:
            kept.append(row)
        else:
            rejected.append({"relation": raw, "reason": reason})
    return n, {"relations": kept, "rejected": rejected}, {"basis": req["basis"], "pairs": req["pairs"], "reply": reply}


def cmd_relate(args, radius=250, max_pairs=40, window=1000):
    workdir = Path(args.workdir).resolve()
    chapters = [c for c in read_json(workdir / "chapters.json", []) if (workdir / "state" / f"{c['index']:04d}.json").exists()]
    replies = read_json(workdir / "relate-replies.json", {"chapters": {}})["chapters"]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda c: relate_chapter(workdir, c, radius, max_pairs, window, replies), chapters))
    done = {n: result for n, result, _ in results}
    write_json(workdir / "relate.json", {"chapters": {str(n): done[n] for n in sorted(done)}})
    write_json(workdir / "relate-replies.json", {"chapters": {str(n): record for n, _, record in results if record}})
    kept = sum(len(c["relations"]) for c in done.values())
    rejected = sum(len(c["rejected"]) for c in done.values())
    log(workdir, f"relate: {kept} relations added, {rejected} rejected, over {len(done)} chapters")
    write_derived(workdir, load_states(workdir))
