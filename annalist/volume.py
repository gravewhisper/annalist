import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .files import read_json, write_json
from .llm import cached_llm
from .names import slug
from .render import cmd_render
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


ARCS_PROMPT = """Below are synopses of chapters {lo} to {hi} of a novel, which make up "{name}". Divide them into consecutive story arcs of about 15 to 25 chapters each, the way a fan wiki would, breaking where the story turns: a new main conflict, a new setting, or a climax resolved. A range under 25 chapters is one or two arcs. Give each arc a short name a fan wiki would use. Use only these synopses.

{synopses}

Reply with one JSON object: {{"arcs": [{{"name": "...", "start": first chapter number, "end": last chapter number}}]}}, in order, covering every chapter exactly once.
"""


ARC_PROMPT = """Write the plot summary of one story arc of a novel for a fan wiki, using ONLY the chapter synopses below. Two to four paragraphs of plain past-tense prose, naming the characters and places involved, in story order. No outside knowledge of the novel and nothing beyond chapter {end}.

Arc: {arc} (chapters {start} to {end})

{synopses}

Reply with one JSON object: {{"summary": "paragraphs separated by blank lines"}}
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
    starts = {}
    for a in arcs if isinstance(arcs, list) else []:
        try:
            start = int(a.get("start"))
        except (TypeError, ValueError, AttributeError):
            continue
        if lo <= start <= hi:
            starts.setdefault(start, str(a.get("name") or "").strip())
    ordered = sorted(starts.items()) or [(lo, "")]
    ordered[0] = (lo, ordered[0][1])
    bounds = [s for s, _ in ordered[1:]] + [hi + 1]
    return [{"name": name or f"Arc {k + 1}", "start": start, "end": end - 1}
            for k, ((start, name), end) in enumerate(zip(ordered, bounds))]


def cmd_volume(args):
    workdir = Path(args.workdir).resolve()
    lo, hi = args.start, args.end
    kb = load_states(workdir, until=hi)
    missing = [n for n in range(lo, hi + 1) if not kb.synopses.get(n)]
    if missing:
        sys.exit(f"chapters without a synopsis: {missing[:10]}; read them first")
    titles = {c["index"]: c["title"] for c in json.loads((workdir / "chapters.json").read_text(encoding="utf-8"))}

    def synopses(a, b):
        return "\n".join(f"Ch {n} ({titles[n]}): {kb.synopses[n]}" for n in range(a, b + 1))

    arcs = repair_arcs(cached_llm(workdir, "arcs", ARCS_PROMPT.format(lo=lo, hi=hi, name=args.name, synopses=synopses(lo, hi))).get("arcs"), lo, hi)
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = pool.map(lambda a: cached_llm(workdir, "arc", ARC_PROMPT.format(
            arc=a["name"], start=a["start"], end=a["end"], synopses=synopses(a["start"], a["end"]))), arcs)
        for arc, reply in zip(arcs, replies):
            arc["summary"] = str(reply.get("summary") or "").strip()
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
