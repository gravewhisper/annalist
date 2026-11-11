import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .files import read_json, write_json
from .llm import cached_llm
from .names import slug
from .render import ARCS_FILE, cmd_render
from .state import load_states, timeline_role


KEY_EVENTS_PROMPT = """Below are the recorded facts from chapters {start} to {end} of a novel, the story arc "{arc}". Each fact has an id, a chapter, the entity it is about, and a claim backed by quotes from the text. Pick the one or two turning points of this arc a fan wiki would list as key events: what changes the story, not background or description. Use only these facts.

{facts}

Reply with one JSON object: {{"events": [{{"event": "one sentence in past tense naming who did what", "facts": ["ids of the facts that show it"]}}]}}, in story order.
"""


def key_events(workdir, kb, arcs):
    facts = {f["id"]: f for f in kb.facts}

    def pick(arc):
        rows = [f for f in kb.facts if arc["start"] <= f["chapter"] <= arc["end"]]
        lines = "\n".join(f"{f['id']} ch{f['chapter']} {f['entity']}: {f['claim']}" for f in rows)
        reply = cached_llm(workdir, "events", KEY_EVENTS_PROMPT.format(arc=arc["name"], start=arc["start"], end=arc["end"], facts=lines))
        events = []
        for e in reply.get("events") or []:
            cited = [facts[i] for i in e.get("facts") or [] if i in facts and arc["start"] <= facts[i]["chapter"] <= arc["end"]] if isinstance(e, dict) else []
            if cited and str(e.get("event") or "").strip():
                events.append({"event": str(e["event"]).strip(), "facts": [f["id"] for f in cited],
                               "chapters": sorted({f["chapter"] for f in cited}), "shown": arc["end"]})
        return events[:2]

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [e for events in pool.map(pick, arcs) for e in events]


ARCS_PROMPT = """Below are synopses of chapters {lo} to {hi} of a novel, which make up {part}. Divide them into consecutive story arcs of about 15 to 25 chapters each, the way a fan wiki would, breaking where the story turns: a new main conflict, a new setting, or a climax resolved. A range under 25 chapters is one or two arcs. Give each arc a short name a fan wiki would use. Use only these synopses.

{synopses}

Reply with one JSON object: {{"arcs": [{{"name": "...", "start": first chapter number, "end": last chapter number}}]}}, in order, covering every chapter exactly once.
"""


ARCS_OPEN_RULE = """
The novel goes on after chapter {hi}, so the last arc may still be in progress. End it at chapter {hi}.
"""


ARC_PROMPT = """Name and summarise one story arc of a novel for a fan wiki, using ONLY the chapter synopses below. Give the arc a short name a fan wiki would use. Write its plot summary in two to four paragraphs of plain past-tense prose, naming the characters and places involved, in story order. No outside knowledge of the novel and nothing beyond chapter {end}.

Arc: chapters {start} to {end}

{synopses}

Reply with one JSON object: {{"name": "...", "summary": "paragraphs separated by blank lines"}}
"""


VOLUME_PROMPT = """You are writing the main page of a fan wiki for "{name}", chapters {lo} to {hi} of a novel. Use ONLY the material below. No outside knowledge of the novel and nothing beyond chapter {hi}.

ARCS:
{arcs}

CHAPTER SYNOPSES:
{synopses}

Reply with one JSON object:
{{
  "overview": "one or two paragraphs: what this volume is about, its setting, its protagonist, and its central conflict",
  "character_development": [{{"character": "...", "development": "two or three sentences on how they change or what we learn about them over the volume", "chapters": [chapter numbers]}}]
}}
Rules: character_development covers the 3 to 8 most important characters. Every chapter number must be one where the synopses show it.
"""


def repair_arcs(arcs, lo, hi):
    starts = {lo}
    for a in arcs if isinstance(arcs, list) else []:
        try:
            start = int(a.get("start"))
        except (TypeError, ValueError, AttributeError):
            continue
        if lo < start <= hi:
            starts.add(start)
    ordered = sorted(starts)
    return [{"start": start, "end": end - 1} for start, end in zip(ordered, ordered[1:] + [hi + 1])]


def synopsis_lines(workdir, kb, lo, hi):
    missing = [n for n in range(lo, hi + 1) if not kb.synopses.get(n)]
    if missing:
        sys.exit(f"chapters without a synopsis: {missing[:10]}; read them first")
    titles = {c["index"]: c["title"] for c in json.loads((workdir / "chapters.json").read_text(encoding="utf-8"))}
    return lambda a, b: "\n".join(f"Ch {n} ({titles[n]}): {kb.synopses[n]}" for n in range(a, b + 1))


def close_arcs(workdir, name, lo, hi, read, synopses):
    """A closed arc is frozen, so a rebuild with more chapters read divides only the chapters after it. Until the volume
    ends, the last arc of a division stays open. Names come from each arc's own synopses, never from later chapters."""
    stored = read_json(workdir / ARCS_FILE, {"volumes": []})["volumes"]
    entry = next((v for v in stored if v["name"] == name and v["from"] == lo and all(a["end"] <= hi for a in v["arcs"])),
                 {"name": name, "from": lo, "read": lo - 1, "arcs": []})
    if read <= entry["read"]:
        return entry["arcs"]
    start = entry["arcs"][-1]["end"] + 1 if entry["arcs"] else lo
    if start <= read:
        prompt = ARCS_PROMPT.format(lo=start, hi=read, part=f'"{name}"' if (start, read) == (lo, hi) else f'part of "{name}"',
                                    synopses=synopses(start, read))
        divided = repair_arcs(cached_llm(workdir, "arcs", prompt + (ARCS_OPEN_RULE.format(hi=read) if read < hi else "")).get("arcs"), start, read)
        closed = divided if read == hi else divided[:-1]
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = pool.map(lambda a: cached_llm(workdir, "arc", ARC_PROMPT.format(
                start=a["start"], end=a["end"], synopses=synopses(a["start"], a["end"]))), closed)
            entry["arcs"] += [{"name": str(r.get("name") or "").strip() or f"Chapters {a['start']} to {a['end']}",
                               "start": a["start"], "end": a["end"], "summary": str(r.get("summary") or "").strip()}
                              for a, r in zip(closed, replies)]
    entry["read"] = read
    write_json(workdir / ARCS_FILE, {"volumes": sorted([v for v in stored if v["name"] != name] + [entry], key=lambda v: v["from"])})
    return entry["arcs"]


def cmd_open_volume(workdir, name, lo, hi, read):
    kb = load_states(workdir, until=read)
    close_arcs(workdir, name, lo, hi, read, synopsis_lines(workdir, kb, lo, read))


def cmd_volume(args):
    workdir = Path(args.workdir).resolve()
    lo, hi = args.start, args.end
    kb = load_states(workdir, until=hi)
    synopses = synopsis_lines(workdir, kb, lo, hi)
    arcs = close_arcs(workdir, args.name, lo, hi, hi, synopses)
    page = cached_llm(workdir, "volume", VOLUME_PROMPT.format(
        name=args.name, lo=lo, hi=hi, synopses=synopses(lo, hi),
        arcs="\n\n".join(f"{a['name']} (chapters {a['start']} to {a['end']}):\n{a['summary']}" for a in arcs)))
    stored = read_json(workdir / "profiles.json", {"characters": {}, "deaths": []})
    profiles = stored["characters"]
    deaths = [d for d in stored.get("deaths", []) if lo <= d["chapter"] <= hi
              and timeline_role(kb.timelines.get(d.get("timeline", "main")), hi) == "current"]
    for d in deaths:
        revivals = [o["chapter"] for o in profiles.get(d["name"], {}).get("fields", {}).get("status", [])
                    if o["value"] == "revived" and d["chapter"] < o["chapter"] <= hi and o.get("quote_ok")]
        if revivals:
            d["revived"] = revivals[0]
    write_json(workdir / "volumes" / f"{slug(args.name)}.json",
               {"name": args.name, "from": lo, "to": hi, "arcs": arcs, "page": page,
                "key_events": key_events(workdir, kb, arcs), "deaths": deaths})
    print(f"{len(deaths)} deaths")
    cmd_render(argparse.Namespace(workdir=str(workdir), until=hi, html=True, jobs=4))
    print(f"volume page: {workdir / f'wiki-ch{hi:04d}' / 'volumes' / (slug(args.name) + '.md')}")
