import json
import sys
from pathlib import Path

from .book import load_book
from .files import log, read_json, write_json
from .llm import llm, LLMError, LLMUnavailable
from .names import name_key
from .state import Knowledge, load_states, parse_sourcing, TIMELINE_KINDS, timeline_line, write_derived
from .text import chapter_text


TIMELINE_PROMPT = """You are tracking the timelines of a novel for a reference wiki, one chapter at a time, like a first-time reader. Never use outside knowledge of this novel. {note}

Timeline kinds:
- main: the story's present, plus everything that holds whichever timeline it was learned in: who someone is, their powers and appearance, their history as recalled or told in the present, the rules of the world, and what a character who remembers across timelines knows or feels.
{kinds}

TIMELINES SO FAR (id [kind]: label, chapters):
{registry}

END OF THE PREVIOUS CHAPTER:
<previous>
{previous}
</previous>

CHAPTER {n}: {title}
<chapter>
{text}
</chapter>

ITEMS EXTRACTED FROM THIS CHAPTER (id: item):
{items}

Reply with one JSON object:
{{
  "new": [{{"id": "a short id not used above", "kind": "run, flashback, vision, or alternate", "label": "a few words naming it", "period": "when it is set if the text says, else empty"}}],
  "erased": ["ids of earlier timelines this chapter shows were undone, other than the run a new run replaces"],
  "labels": {{"F1": "timeline id"}}
}}
Rules:
- new: only timelines that begin in this chapter, in the order they begin, including runs that begin and end inside it. A run begins every time the story returns to the loop's starting point (the looping character dies or resets and is back at the start), so one chapter can begin several (a character dies and restarts twice), and a chapter that opens back at the starting point begins a new run even when the previous chapter did not show the reset. Judge by what happens, never by the book's own loop count, which can repeat or skip. The scenes before a restart belong to the run that was current when the chapter opened. A new run ends and erases the previous run by itself.
- labels: give every item id above a timeline id from the list above or from new. An item is main when it would still be true after a restart or outside the scene: an ability ("he regenerates"), an identity, a relationship that predates the story, an appearance, backstory, a rule of the world, or the memories and plans of a character who keeps them across restarts. An item takes a run id when it is something that happened in that run, which its restart undoes for everyone else: a death, an injury, an arrest, a fight, a deal, a bribe, a threat, a meeting or friendship the others will forget, an object destroyed. When unsure whether an event survives a restart, it does not. Everything a flashback, vision, or alternate scene shows (who people were then, what they did, how they looked, what they could do) takes that timeline's id, even when it may still hold in the present. For an entity (E ids) label its summary the same way.
- When nothing in the chapter changes timeline, events take the current run's id (the latest run that is not erased), or main when there is no run.
"""


def timeline_items(out):
    lines = []
    for i, e in enumerate(out.get("entities") or [], 1):
        if isinstance(e, dict) and e.get("name"):
            lines.append(f"E{i}: {e['name']}: {e.get('summary') or ''}")
    for i, f in enumerate(out.get("facts") or [], 1):
        if isinstance(f, dict):
            quotes = parse_sourcing(f)["quotes"]
            lines.append(f"F{i}: {f.get('entity')}: {f.get('claim')}" + (f' | "{quotes[0]}"' if quotes else ""))
    for i, r in enumerate(out.get("relations") or [], 1):
        if isinstance(r, dict):
            lines.append(f"R{i}: {r.get('source')} {r.get('type')} {r.get('target')}")
    for i, q in enumerate(out.get("questions_raised") or [], 1):
        if isinstance(q, dict):
            lines.append(f"Q{i}: {q.get('question')}" + (f' | "{q["quote"]}"' if q.get("quote") else ""))
    return lines


def clean_timelines(reply, ids, existing, n):
    new, renamed = [], {}
    for t in reply.get("new") or []:
        tid = str(t.get("id") or "").strip() if isinstance(t, dict) else ""
        if not tid or name_key(tid) == "main" or t.get("kind") not in TIMELINE_KINDS:
            continue
        renamed[tid] = tid if tid not in existing else f"{tid}@{n}"
        new.append({"id": renamed[tid], "kind": t["kind"], "label": str(t.get("label") or "").strip(),
                    "period": str(t.get("period") or "").strip()})
    erased = [str(x).strip() for x in reply.get("erased") or [] if isinstance(x, str) and x.strip() in existing]
    labels = {k: renamed.get(v.strip(), v.strip()) for k, v in reply["labels"].items()
              if k in ids and isinstance(v, str) and v.strip()}
    return {"new": new, "erased": erased, "labels": labels}


def label_timelines(workdir, kb, state, book):
    n, out = state["chapter"], state["extraction"]
    items = timeline_items(out)
    prompt = TIMELINE_PROMPT.format(
        note=book["timeline_note"], kinds="\n".join(f"- {k}: {d}" for k, d in TIMELINE_KINDS.items()),
        registry="\n".join(f"- {timeline_line(t)}" for t in kb.timelines.values()), n=n,
        previous=chapter_text(str(workdir), n - 1)[-2000:] if n > 1 else "(this is the first chapter)",
        title=state.get("title", ""), text=chapter_text(str(workdir), n), items="\n".join(items) or "(none)")
    reply = llm(workdir, "timelines", prompt, chapter=n,
                check=lambda r: None if isinstance(r.get("labels"), dict) else "no labels object")
    sidecar = clean_timelines(reply, {line.split(":", 1)[0] for line in items}, kb.timelines, n)
    missing = len(items) - len(sidecar["labels"])
    if missing:
        log(workdir, f"  timelines ch{n}: {missing} of {len(items)} items unlabelled, filed under main")
    return sidecar


def label_counts(sidecar):
    counts = {}
    for tid in sidecar["labels"].values():
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def cmd_timelines(args):
    workdir = Path(args.workdir).resolve()
    book = load_book(workdir)
    if book["timeline_kind"] == "linear":
        sys.exit("book.json timeline_kind is linear, so every item stays on main; set it to loop or flashback to label timelines")
    kb = Knowledge(book["ladder"])
    kb.leads = read_json(workdir / "leads.json", {"leads": {}})["leads"]
    for path in sorted((workdir / "state").glob("[0-9][0-9][0-9][0-9].json")):
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["chapter"] >= (args.start or 10 ** 9) or "timelines" not in state:
            try:
                state["timelines"] = label_timelines(workdir, kb, state, book)
            except (LLMError, LLMUnavailable) as exc:
                log(workdir, f"stopped before labelling chapter {state['chapter']}: {exc}. Rerun the same command to resume.")
                sys.exit(2)
            write_json(path, state)
            t = state["timelines"]
            log(workdir, f"timelines ch {state['chapter']:4d}: new {[x['id'] + ' ' + x['kind'] for x in t['new']]}, "
                         f"erased {t['erased']}, labels {label_counts(t)}")
        kb.apply(state)
    kb = load_states(workdir)
    write_derived(workdir, kb)
    for t in kb.timelines.values():
        print(timeline_line(t))
