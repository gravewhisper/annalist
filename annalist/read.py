import copy
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import audit_support, reread
from .book import load_book
from .corrections import load_corrections, reader_notes
from .files import log, read_jsonl, write_json
from .llm import llm, LLMError, LLMUnavailable
from .state import load_states, write_derived
from .survey import generate_book
from .template import ENTITY_TYPES, RELATION_TYPES
from .text import chapter_text
from .timelines import label_timelines


EXTRACT_PROMPT = """You are reading a novel one chapter at a time, like a first-time reader, and maintaining a wiki of what you have learned. You know ONLY what the chapters so far have shown. Never use outside knowledge of this novel.

{knowledge}

CHAPTER {n}: {title}
<chapter>
{text}
</chapter>

Extract what this chapter adds to the wiki. Reply with one JSON object of this exact shape:
{{
  "synopsis": "...",
  "entities": [{{"name": "...", "type": "...", "aliases": [{{"name": "...", "unique": false}}], "summary": "..."}}],
  "facts": [{{"entity": "...", "claim": "...", "quotes": ["..."], "asserted_by": "narrator", "status": "stated"}}],
  "relations": [{{"source": "...", "target": "...", "type": "...", "detail": "", "quotes": ["..."], "asserted_by": "narrator", "status": "stated"}}],
  "questions_raised": [{{"question": "...", "quote": "..."}}],
  "questions_resolved": [{{"id": "...", "answer": "...", "quote": "..."}}]
}}

Rules:
- synopsis: three to six sentences of plain prose saying what happens in this chapter, who is involved, and where it takes place.
- entities: every character, place, organization, artifact, event, or concept that matters in this chapter and is new or whose understanding changed. "type" is a short lowercase singular noun. Use these exact types where they fit: {base_types}.{book_types} Choose another short noun only when none of these fits. Reuse the exact registry name and type for known entities so they merge. "summary" is one line describing the entity as currently understood.
- aliases: an alias is only another name for the SAME thing, never a related thing. A secret identity or persona a character uses (a code name, a title they adopt) is an alias of that character. An object, token, symbol, place, or group connected to a character is a separate entity of its own type, never an alias, even when it carries the character's name or code name. Entities of different types never merge, and they never share a name: if an object, title, place, or group would carry the same name as an entity of another type, name it distinctly ("the Owl badge", not "the Owl"). Bare titles and roles ("Captain", "the inspector", "the landlord") are always discarded. Generic descriptions ("the mysterious man", "the red moon") are discarded unless you set "unique": true, which means this exact phrase is used in the book as a fixed name for this one entity and nothing else.
- facts: concrete, specific claims this chapter establishes about an entity (identity, relationships, abilities, history, appearance, goals, rules of the world). Aim for 10 to 30 strong facts, not trivia. "entity" must be a registry name or an entity you list above.
- quotes: one to three verbatim excerpts from this chapter. Each excerpt is ONE contiguous span of one or two sentences copied EXACTLY, character for character, from a single paragraph, at most 300 characters. No ellipses, no paraphrase, no stitching. This is checked by machine.
- The claim must be fully supported by its quotes alone: a reader who sees only the quotes must be able to confirm every part of the claim. If a part needs another passage, add that passage as another quote. If it would need more than three, or a part is not in the text at all, split the claim or drop the unsupported part. Never state a cause, amount, purpose, or relationship the quotes do not show.
- asserted_by: "narrator" when the narration itself states it, otherwise the name of the character who says or thinks it.
- status: "stated" when the narrative presents it as true; "implied" when the text strongly suggests it without saying it; "belief" when a character believes, suspects, guesses, or claims it but the narrative has not confirmed it.
- relations: links between two entities that this chapter shows: kinship, membership, mentorship, rivalry, employment, location, ownership, rank or hierarchy, and similar. "source" and "target" are registry names or entities you list above. "type" is the predicate alone, a verb phrase or a role read as "source <type> target" ({relation_types}, "{power_relation}"); never fold an object, a third entity, or a circumstance into it. "detail" is whatever the sentence needs after the target, read as "source <type> target <detail>" ("of impersonating the baron", "to the innkeeper as payment"), or "" when nothing. Write names in type and detail as the book writes them. quotes, asserted_by, and status follow the same rules as facts, and the quotes alone must show the relation.
- questions_raised: genuine mysteries, foreshadowing, or unexplained details a careful reader would want answered later. "quote" is the one passage that raises it (same excerpt rules). Do not repeat an already open question.
- questions_resolved: only open questions (by id from the list above) that THIS chapter clearly answers, with the answer and the quote from this chapter that answers it. Leave empty if none.
"""


BOOK_TYPES_RULE = " Entries of this book's own types matter too. Each always takes its book type, never the general type that the book type is a kind of: {types}."


def cmd_read(args):
    workdir = Path(args.workdir).resolve()
    chapters = {c["index"]: c for c in json.loads((workdir / "chapters.json").read_text(encoding="utf-8"))}
    kb = load_states(workdir)
    write_derived(workdir, kb)
    if not (workdir / "book.json").exists():
        generate_book(workdir, kb, load_states(workdir, retypes=False), args.end)
    log(workdir, f"read {args.start}-{args.end}: {len(kb.synopses)} chapters already read")
    pending = None
    with ThreadPoolExecutor(max_workers=1) as checks:
        for n in range(args.start, args.end + 1):
            state_path = workdir / "state" / f"{n:04d}.json"
            if state_path.exists():
                continue
            if n > 1 and not (workdir / "state" / f"{n - 1:04d}.json").exists() and not (pending and pending["n"] == n - 1):
                sys.exit(f"chapter {n - 1} has not been read; read in order")
            later = sorted(p.name for p in (workdir / "state").glob("[0-9][0-9][0-9][0-9].json") if int(p.stem) > n)
            if later:
                sys.exit(f"chapter {n} is missing but later chapters were read against it ({later[0]} onward); "
                         "delete those states too so the reread sees only earlier chapters")
            try:
                out, began, chars = extract_chapter(workdir, kb, chapters[n], pending)
                if pending:
                    save_checked(workdir, kb, pending)
                pending = {"n": n, "chapter": chapters[n], "out": out, "began": began, "chars": chars, "path": state_path,
                           "state": checks.submit(checked_state, workdir, kb, chapters[n], out)}
            except (LLMError, LLMUnavailable) as exc:
                stop_reading(workdir, kb, pending, n, exc)
        if pending:
            try:
                save_checked(workdir, kb, pending)
            except (LLMError, LLMUnavailable) as exc:
                stop_reading(workdir, kb, None, pending["n"], exc)
    log(workdir, f"read {args.start}-{args.end}: done")


def stop_reading(workdir, kb, pending, n, exc):
    if pending and pending["n"] < n and not pending["path"].exists():
        try:
            save_checked(workdir, kb, pending)
        except (LLMError, LLMUnavailable) as earlier:
            log(workdir, f"stopped before saving chapter {pending['n']}: {earlier}. Rerun the same command to resume.")
            sys.exit(2)
    log(workdir, f"stopped before saving chapter {n}: {exc}. Rerun the same command to resume.")
    sys.exit(2)


def with_unchecked(kb, pending):
    view = copy.deepcopy(kb)
    view.apply({"chapter": pending["n"], "title": pending["chapter"]["title"], "extraction": pending["out"]})
    return view


def extract_chapter(workdir, kb, chapter, pending):
    n = chapter["index"]
    began = time.time()
    text = chapter_text(workdir, n)
    book = load_book(workdir)
    view = with_unchecked(kb, pending) if pending else kb
    notes = reader_notes(view, load_corrections(workdir), n)
    types = ", ".join(f"{t} (a kind of {spec['parent']}: {spec['description']})" for t, spec in book["power_types"].items())
    prompt = EXTRACT_PROMPT.format(knowledge=view.compact_view(text, book["view"], notes), n=n, title=chapter["title"], text=text,
                                   power_relation=book["relation_example"], base_types=", ".join(ENTITY_TYPES),
                                   relation_types=", ".join(f'"{r}"' for r in RELATION_TYPES),
                                   book_types=BOOK_TYPES_RULE.format(types=types) if types else "")
    return llm(workdir, "extract", prompt, chapter=n), began, len(prompt)


def checked_state(workdir, kb, chapter, out):
    n = chapter["index"]
    book = load_book(workdir)
    labelled = book["timeline_kind"] != "linear"
    claims = {}
    for r in out.get("questions_resolved") or []:
        q = kb.questions.get(str(r.get("id"))) if isinstance(r, dict) else None
        if q and q["status"] != "resolved" and q["chapter"] != n:
            claims.setdefault(q["id"], (q, r))
    with ThreadPoolExecutor(max_workers=4) as pool:
        audit = pool.submit(audit_support, workdir, out, n)
        timelines = labelled and pool.submit(label_timelines, workdir, kb, {"chapter": n, "title": chapter["title"], "extraction": out}, book)
        verdicts = {qid: pool.submit(reread, workdir, q, r, n) for qid, (q, r) in claims.items()}
        support = audit.result()
        rereads = {qid: v.result() for qid, v in verdicts.items()}
    state = {"chapter": n, "title": chapter["title"], "extraction": out, "support": support, "rereads": rereads}
    if labelled:
        try:
            state["timelines"] = timelines.result()
        except LLMError as exc:
            log(workdir, f"  timelines ch{n}: {exc}; saved without labels, run timelines to add them")
    return state


def save_checked(workdir, kb, pending):
    n, chapter, out, began = pending["n"], pending["chapter"], pending["out"], pending["began"]
    state = pending["state"].result()
    support, rereads = state["support"], state["rereads"]
    write_json(pending["path"], state)
    relations_before = len(kb.relations)
    new_facts = kb.apply(state)
    write_derived(workdir, kb)
    resolved = sum(1 for v in rereads.values() if v.get("verdict") == "accept")
    cost = sum(c.get("total_cost_usd") or 0 for c in read_jsonl(Path(workdir) / "calls.jsonl") if c["chapter"] == n)
    trimmed = sum(v.get("verdict") == "trim" for v in support.values() if isinstance(v, dict))
    dropped = sum(v.get("verdict") == "unsupported" for v in support.values() if isinstance(v, dict))
    log(workdir, f"ch {n:4d} {chapter['title']!r}: {len(out.get('entities') or [])} entities, {len(new_facts)} facts "
                 f"({trimmed} trimmed, {dropped} dropped by support audit), "
                 f"{len(kb.relations) - relations_before} relations, {len(out.get('questions_raised') or [])} raised, "
                 f"{resolved}/{len(rereads)} resolved, prompt {pending['chars']} chars, ${cost:.3f}, {time.time() - began:.0f}s")
