import hashlib
import json
from collections import Counter
import re
import shutil
import sys
from pathlib import Path

from .corrections import correct_profiles, EVERY_CORRECTION, kept_deaths
from .families import read_families, relation_family
from .files import read_json
from .llm import cached_reply
from .names import is_stub, name_key, parse_aliases, written_summary
from .profile import page_profiles
from .render import checkpoint_prompts, closed_arcs, history_prompts, kept_prompts, PERSONALITY_PROMPT, reader_parts, summary_prompt
from .state import load_states
from .status import spoken_appearances
from .template import type_parents, Types
from .text import chapter_text, mention_quote, verified_quotes
from .titles import page_title, revealed_name

SITE = Path(__file__).resolve().parent / "site"
THEMES = Path(__file__).resolve().parent / "themes"
QUOTE_KEYS = {"quote", "quotes", "resolve_quote"}
def entity_id(name):
    return hashlib.sha1(name.encode()).hexdigest()[:8]


def mentions(names, text):
    lower = text.lower()
    return {n for n in names if re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", lower)}


def read_states(workdir):
    for path in sorted((workdir / "state").glob("[0-9][0-9][0-9][0-9].json")):
        yield json.loads(path.read_text(encoding="utf-8"))


class Registry:
    def __init__(self, entities):
        self.entities = {e["name"]: e for e in entities}
        self.index = {}
        for e in entities:
            for n in [e["name"]] + e["aliases"]:
                self.index.setdefault(name_key(n), []).append(e["name"])

    def resolve(self, name, etype=""):
        found = list(dict.fromkeys(self.index.get(name_key(name), [])))
        typed = [n for n in found if self.entities[n]["type"] == name_key(etype)]
        if len(typed) == 1:
            return typed[0]
        return found[0] if len(found) == 1 else None


def timeline(row):
    tid = row.get("timeline", "main")
    return {} if tid == "main" else {"timeline": tid}


class Absorbed:
    def __init__(self, entities):
        self.entries = {a["name"]: {**a, "into": e["name"]} for e in entities for a in e.get("absorbed", [])}
        self.owner = {(a["into"], name_key(n)): a for a in self.entries.values() for n in [a["name"]] + a["aliases"]}

    def page(self, canonical, filed, chapter):
        a = self.entries.get(filed)
        return filed if a and a["into"] == canonical and chapter < a["chapter"] else canonical

    def page_for_name(self, canonical, name, chapter):
        a = self.owner.get((canonical, name_key(name)))
        return a["name"] if a and chapter < a["chapter"] else canonical

    def floor(self, canonical, name, chapter):
        a = self.owner.get((canonical, name_key(name)))
        return max(chapter, a["chapter"]) if a else chapter


def first_seen(registry, facts, relations, states, timelines, absorbed):
    seen = {}

    def note(page, chapter, text):
        for n in mentions(names(page), text):
            key = (page, n)
            seen[key] = min(seen.get(key, chapter), chapter)

    def names(page):
        e = registry.entities.get(page) or absorbed.entries[page]
        return [e["name"]] + e["aliases"]

    for f in facts:
        note(absorbed.page(f["entity"], f.get("filed"), f["chapter"]), f["chapter"], " | ".join([f["claim"]] + f["quotes"]))
    for r in relations:
        for end in ("source", "target"):
            if r[end] in registry.entities:
                note(absorbed.page(r[end], (r.get("filed") or {}).get(end), r["chapter"]), r["chapter"], " | ".join(r["quotes"]))
    blurbs = {}
    for state in states:
        n = state["chapter"]
        labels = (state.get("timelines") or {}).get("labels") or {}
        for i, rec in enumerate(state["extraction"].get("entities") or [], 1):
            if not isinstance(rec, dict) or not rec.get("name"):
                continue
            canonical = registry.resolve(str(rec["name"]), str(rec.get("type") or ""))
            if not canonical:
                continue
            page = absorbed.page_for_name(canonical, str(rec["name"]), n)
            own = {name_key(x): x for x in names(page)}
            for alias in [str(rec["name"])] + parse_aliases(rec.get("aliases")):
                if name_key(alias) in own:
                    key = (page, own[name_key(alias)])
                    seen[key] = min(seen.get(key, n), n)
            summary = written_summary(rec)
            history = blurbs.setdefault(page, [])
            tid = labels.get(f"E{i}") if labels.get(f"E{i}") in timelines else "main"
            if summary and (not history or history[-1][1] != summary):
                history.append([n, summary] + ([tid] if tid != "main" else []))
    return seen, blurbs


def first_named(texts, name, before):
    pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
    return next((n for n in sorted(texts) if n < before and name in texts[n] and pattern.search(texts[n])), before)


def observations(rows):
    return [{"chapter": o["chapter"], "value": o["value"], "quotes": o["quotes"], **timeline(o),
             **({"shown": o["shown"]} if "shown" in o else {})} for o in rows if o.get("quote_ok")]


def personality_history(workdir, name, evidence):
    history = []
    for c in sorted({o.get("shown", o["chapter"]) for o in evidence}):
        shown = [o for o in evidence if o.get("shown", o["chapter"]) <= c and o["quotes"]]
        lines = "\n".join(f"- ch{o['chapter']}: {o['value']} | \"{o['quotes'][0]}\"" for o in shown)
        reply = cached_reply(workdir, "personality", PERSONALITY_PROMPT.format(name=name, evidence=lines))
        if reply and reply.get("paragraph"):
            history.append({"chapter": c, "text": str(reply["paragraph"]).strip()})
    return history


def export_profile(workdir, name, profile, spoke):
    fields = {k: observations(v) for k, v in {**profile["fields"], **profile["extra"]}.items()}
    lists = {k: observations(v) for k, v in profile["lists"].items()}
    evidence = [o for o in profile["lists"].get("personality_evidence", []) if o.get("quote_ok")]
    return {"fields": {k: v for k, v in fields.items() if v}, "lists": {k: v for k, v in lists.items() if v},
            "spoke": [[c, tid] for c, tid in spoke],
            "personality": personality_history(workdir, name, evidence)}


def entity_summary(workdir, entity, facts, safe_chapter, timelines, last):
    reply = cached_reply(workdir, "summary", summary_prompt(entity, facts, timelines, last))
    if not reply or not reply.get("summary"):
        return None
    return {"chapter": safe_chapter, "text": str(reply["summary"]).strip()}


def arc_history(workdir, prompts, name_seen):
    history = []
    for arc, prompt in prompts:
        reply = cached_reply(workdir, "history", prompt)
        if reply and reply.get("paragraph"):
            history.append({"arc": arc["name"], "start": arc["start"], "end": arc["end"], "shown": max(arc["end"], name_seen),
                            "text": str(reply["paragraph"]).strip()})
    return history


def kept_prose(workdir, prompts, joined, part, last):
    prose = {}
    if prompts["summary"]:
        unseen = last if len(part["aliases"]) < len(joined["aliases"]) else 0
        safe = max([joined["last_chapter"], part["name_chapter"], unseen] + [x["chapter"] for x in part["aliases"]])
        reply = cached_reply(workdir, "summary", prompts["summary"])
        if reply and reply.get("summary"):
            prose["summary"] = {"chapter": safe, "text": str(reply["summary"]).strip()}
    replies = {c: cached_reply(workdir, "summary", p) for c, p in prompts["summaries"].items()}
    running = [{"chapter": c, "text": str(r["summary"]).strip()} for c, r in replies.items() if r and r.get("summary")]
    history = arc_history(workdir, prompts["history"], part["name_chapter"])
    return {**prose, **({"summaries": running} if running else {}), **({"history": history} if history else {})}


def nameless(etype, entry):
    return {"nameless": True} if etype == "character" and is_stub(entry) else {}


def first_mention(texts, record):
    names = [record["name"]] if record["name_chapter"] <= record["first"] else []
    names += [a["name"] for a in record["aliases"] if a["chapter"] <= record["first"]]
    quote = mention_quote(texts.get(record["first"], ""), names)
    return {"chapter": record["first"], **({"quote": quote} if quote else {})}


def question_record(q, tier):
    record = {"id": q["id"], "chapter": q["chapter"], "question": q["question"], "quote": q.get("quote", ""), **timeline(q),
              "leads": [{"chapter": l["chapter"], "text": l["text"], "quote": l["quote"]} for l in q["leads"]],
              "tier": {"arc": tier.get("arc_at"), "series": tier.get("series_at")}}
    if q["status"] == "resolved":
        record["resolved"] = {"chapter": q["resolved_chapter"], "shown": q.get("resolved_shown", q["resolved_chapter"]), "answer": q.get("answer", ""),
                              "quote": q.get("resolve_quote", ""), "payoff": q.get("payoff", ""),
                              **({"at_end": True} if q.get("found_by") == "ending" else {})}
    if q["status"] == "premise-false":
        record["premise"] = {k: q["premise"][k] for k in ("chapter", "explanation", "quotes")}
    if q.get("ending"):
        record["ending"] = q["ending"]
    return record


def volume_record(v, kb):
    page = v.get("page") or {}
    return {"name": v["name"], "id": re.sub(r"[^a-z0-9]+", "-", v["name"].lower()).strip("-"),
            "from": v["from"], "to": v["to"],
            "arcs": [{k: a[k] for k in ("name", "start", "end", "summary")} for a in v.get("arcs", [])],
            "key_events": [{k: e[k] for k in ("event", "chapters", "shown")} for e in v.get("key_events", [])],
            "deaths": [{k: d.get(k, []) for k in ("name", "chapter", "shown", "circumstances", "quotes", "later")} for d in kept_deaths(kb, v.get("deaths", []))
                       if d.get("quote_ok", True)],
            "overview": page.get("overview", ""),
            "development": page.get("character_development", [])}


def step_record(s, eid):
    stages = {"stages": [{"name": t["name"], "chapter": t["chapter"]} for t in s["stages"]]} if "stages" in s else {}
    return {"id": eid, "rank": s["rank"], "chapter": s["chapter"], **stages}


def ladder_records(workdir, registry, ids, step_type):
    records = []
    for ladder in read_json(workdir / "ladders.json", []):
        group = ladder["group"] and registry.resolve(ladder["group"], ladder["group_type"])
        if group or ladder["group"] is None:
            records.append({"group": group and ids[group], "chapter": ladder["chapter"],
                            "steps": [step_record(s, ids[registry.resolve(s["entry"], step_type) or s["entry"]]) for s in ladder["steps"]]})
    return records


def strip_quotes(value):
    if isinstance(value, dict):
        return {k: strip_quotes(v) for k, v in value.items() if k not in QUOTE_KEYS}
    if isinstance(value, list):
        return [strip_quotes(v) for v in value]
    return value


def stored_theme(title):
    styles = (read_json(p, {}) for p in sorted(THEMES.glob("*.json")))
    return next((s.get("theme") or {} for s in styles if name_key(s.get("title", "")) == name_key(title)), {})


def titled(record, title):
    aliases = [a for a in record["aliases"] if name_key(a["name"]) != name_key(title["name"])] + [{"name": record["name"], "chapter": record["first"]}]
    return {**record, "name": title["name"], "name_chapter": title.get("chapter", record["first"]),
            "aliases": sorted(aliases, key=lambda a: a["chapter"])}


def build(workdir, theme):
    book = {**read_json(workdir / "book.json", {}), **theme}
    title = book.get("title") or workdir.name
    kb = load_states(workdir, ladders=True, corrections=EVERY_CORRECTION)
    entities = list(kb.entities.values())
    facts = [{**f, **verified_quotes(workdir, f["chapter"], f["quotes"])} for f in kb.facts]
    relations = [{**r, **verified_quotes(workdir, r["chapter"], r["quotes"])} for r in kb.relations]
    states = list(read_states(workdir))
    registry = Registry(entities)
    absorbed = Absorbed(entities)
    timelines = kb.timelines
    seen, blurbs = first_seen(registry, facts, relations, states, timelines, absorbed)
    for d in read_json(workdir / "discover.json", {"entities": []})["entities"]:
        canonical = registry.resolve(d["name"], d["type"])
        if canonical:
            page = absorbed.page_for_name(canonical, d["name"], d["chapter"])
            seen[(page, d["name"])] = min(seen.get((page, d["name"]), d["chapter"]), d["chapter"])
        if canonical and d["summary"]:
            blurbs[page] = sorted(blurbs.get(page, []) + [[d["chapter"], d["summary"]]], key=lambda b: b[0])
    spoken = spoken_appearances(facts + relations, lambda name, n: (c := registry.resolve(name)) and absorbed.page_for_name(c, name, n))
    titles = {c["index"]: c["title"] for c in read_json(workdir / "chapters.json", [])}
    chapters = [{"n": s["chapter"], "title": titles.get(s["chapter"], str(s["chapter"])),
                 "synopsis": str(s["extraction"].get("synopsis") or "").strip()} for s in states]
    last = max((c["n"] for c in chapters), default=0)
    texts = {c["n"]: chapter_text(workdir, c["n"]) for c in chapters}
    by_entity = {}
    for f in facts:
        by_entity.setdefault(f["entity"], []).append(f)
    profiles, missed = correct_profiles(kb, page_profiles(workdir, entities, read_json(workdir / "profiles.json", {"characters": {}})["characters"]),
                                        kb.corrections)
    ids = {name: entity_id(name) for name in [e["name"] for e in entities] + list(absorbed.entries)}
    fact_page = {f["id"]: absorbed.page(f["entity"], f.get("filed"), f["chapter"]) for f in facts}
    rel_ends = [{end: absorbed.page(r[end], (r.get("filed") or {}).get(end), r["chapter"]) for end in ("source", "target")}
                for r in relations]
    words = Counter(w for text in texts.values() for w in re.findall(r"\w+", text))
    present = {}
    for state in states:
        for rec in state["extraction"].get("entities") or []:
            canonical = registry.resolve(str(rec.get("name") or ""), str(rec.get("type") or "")) if isinstance(rec, dict) else None
            if canonical:
                present.setdefault(absorbed.page_for_name(canonical, str(rec["name"]), state["chapter"]), set()).add(state["chapter"])
    for f in facts:
        present.setdefault(fact_page[f["id"]], set()).add(f["chapter"])
    for r, ends in zip(relations, rel_ends):
        for page in ends.values():
            present.setdefault(page, set()).add(r["chapter"])
    tiers = read_json(workdir / "tiers.json", {"questions": {}})["questions"]
    readings = read_families(workdir)
    arcs = closed_arcs(workdir, last)
    ties = {}
    for r in relations:
        for end in ("source", "target"):
            ties.setdefault(r[end], []).append(r)
    kinds = Types(type_parents(book.get("power_types")))
    types = {e["name"]: kinds.kind(e["type"]) for e in entities}

    out_entities = []
    for e in entities:
        name_seen = seen.get((e["name"], e["name"]), e["first_chapter"])
        aliases = [{"name": a, "chapter": absorbed.floor(e["name"], a, seen[(e["name"], a)])} for a in e["aliases"]
                   if (e["name"], a) in seen and a != e.get("written")]
        first = e["first_chapter"]
        if e.get("absorbed"):
            shown = [c for (page, _), c in seen.items() if page == e["name"]] + [b[0] for b in blurbs.get(e["name"], [])]
            shown += [f["chapter"] for f in facts if fact_page[f["id"]] == e["name"]]
            shown += [r["chapter"] for r, ends in zip(relations, rel_ends) if e["name"] in ends.values()]
            first = min(shown, default=e["first_chapter"])
        else:
            first = first_named(texts, e["name"], first)
            name_seen = min(name_seen, first)
        shown_name = e.get("written", e["name"])
        own_names = [a for a in e["aliases"] if len(set(registry.index[name_key(a)])) == 1]
        if not e.get("absorbed") and "written" not in e:
            own = [b[1] for b in blurbs.get(e["name"], [])] + [x for f in by_entity.get(e["name"], []) for x in [f["claim"], *f["quotes"]]]
            shown_name, used = page_title(e["name"], own_names, own, texts)
            first = min([first, *used.values()])
            aliases = [{**a, "chapter": min(a["chapter"], used.get(a["name"], a["chapter"]))} for a in aliases if a["name"] != shown_name]
            if shown_name != e["name"]:
                aliases.append({"name": e["name"], "chapter": name_seen})
                name_seen = max(first, used[shown_name])
        real = None
        if e["type"] == "character" and shown_name == e["name"]:
            real = revealed_name(e["name"], [a for a in aliases if a["name"] in own_names], words)
        if real:
            aliases = [a for a in aliases if a["name"] != real["name"]] + [{"name": e["name"], "chapter": name_seen}]
            shown_name, name_seen = real["name"], real["chapter"]
        record = {"id": ids[e["name"]], "name": shown_name, "name_chapter": name_seen, "type": e["type"],
                  "first": first, "aliases": sorted(aliases, key=lambda a: (a["chapter"], a["name"] != e["name"])),
                  "blurbs": blurbs.get(e["name"], []), **nameless(e["type"], e)}
        record["mention"] = first_mention(texts, record)
        if e["type"] == "character":
            record["present"] = sorted(present.get(e["name"], ()))
        common = [n for n in [record["name"]] + [a["name"] for a in record["aliases"]] if " " not in n and words[n.lower()] >= max(1, words[n])]
        if common:
            record.update(common_names=common, linked_chapters=sorted(present.get(e["name"], ())))
        leads = [{"id": ids[target], "chapter": p["chapter"], "quote": p["quote"]}
                 for p in e.get("possibly", []) if (target := registry.resolve(p["name"]))]
        if leads:
            record["possibly"] = leads
        own = by_entity.get(e["name"], [])
        if len(own) >= 3:
            unseen = last if len(aliases) < len(e["aliases"]) else 0
            safe = max([e["last_chapter"], name_seen, unseen] + [a["chapter"] for a in aliases])
            summary = entity_summary(workdir, e, own, safe, timelines, last)
            if summary:
                record["summary"] = summary
            replies = {c: cached_reply(workdir, "summary", prompt) for c, prompt in checkpoint_prompts(e, own, timelines).items()}
            running = [{"chapter": c, "text": str(r["summary"]).strip()} for c, r in replies.items() if r and r.get("summary")]
            if running:
                record["summaries"] = running
        if e["name"] in profiles:
            record["profile"] = export_profile(workdir, e["name"], profiles[e["name"]], spoken.get(e["name"], []))
        if e["type"] == "character":
            history = arc_history(workdir, history_prompts(e, own, ties.get(e["name"], []), arcs, timelines), name_seen)
            if history:
                record["history"] = history
        out_entities.append(titled(record, e["title"]) if e.get("title") else record)
        kept = {a["name"]: kept_prompts(a, own, ties.get(e["name"], []), arcs, timelines, last) for a in reader_parts(e)}
        for a in e.get("absorbed", []):
            kind = a.get("type", e["type"])
            aliases = [{"name": x, "chapter": seen[(a["name"], x)]} for x in a["aliases"] if (a["name"], x) in seen]
            part = {"id": ids[a["name"]], "name": a["name"], "name_chapter": seen.get((a["name"], a["name"]), a["first_chapter"]),
                    "type": kind, "first": a["first_chapter"], "aliases": sorted(aliases, key=lambda x: x["chapter"]),
                    "blurbs": blurbs.get(a["name"], []), "merged": {"into": ids[e["name"]], "chapter": a["chapter"]},
                    **nameless(kind, a)}
            part["mention"] = first_mention(texts, part)
            if kind == "character":
                part["present"] = sorted(present.get(a["name"], ()))
            if a["name"] in profiles:
                part["profile"] = export_profile(workdir, a["name"], profiles[a["name"]], spoken.get(a["name"], []))
            if a["name"] in kept:
                part.update(kept_prose(workdir, kept[a["name"]], a, part, last))
            out_entities.append(part)

    return kb.problems + missed, {
        "book": {"title": title, "max": last,
                 "public_domain": book.get("public_domain") is True, "theme": book.get("theme") or stored_theme(title),
                 "power_types": sorted((book.get("power_types") or {}).keys()), "parents": type_parents(book.get("power_types")),
                 "ladder": book.get("ladder")},
        "chapters": chapters,
        "timelines": list(timelines.values()),
        "entities": out_entities,
        "facts": [{"id": f["id"], "chapter": f["chapter"], "entity": ids[fact_page[f["id"]]], "claim": f["claim"],
                   "status": f["status"], "by": f["asserted_by"], "quotes": f["quotes"], **timeline(f),
                   **({} if f["quote_ok"] else {"unverified": True})}
                  for f in facts if f["entity"] in ids],
        "relations": [{"chapter": r["chapter"], "source": ids[ends["source"]], "target": ids[ends["target"]], "type": r["type"],
                       "family": r.get("family") or relation_family(r["type"], readings, types.get(r["target"], "")), "status": r["status"],
                       "by": r["asserted_by"],
                       "quotes": r["quotes"], **timeline(r), **({"detail": r["detail"]} if r["detail"] else {}),
                       **({} if r["quote_ok"] else {"unverified": True})}
                      for r, ends in zip(relations, rel_ends) if r["source"] in ids and r["target"] in ids],
        "questions": [question_record(q, tiers.get(q["id"], {})) for q in kb.questions.values()],
        "ladders": ladder_records(workdir, registry, ids, (book.get("ladder") or {}).get("step_type")),
        "volumes": sorted((volume_record(read_json(p, {}), kb) for p in (workdir / "volumes").glob("*.json")),
                          key=lambda v: v["from"]),
    }


def cmd_export(args):
    workdir, outdir = Path(args.workdir).resolve(), Path(args.outdir).resolve()
    theme = read_json(args.theme, {}) if args.theme else {}
    problems, data = build(workdir, theme)
    for problem in problems:
        print(f"warning: {problem}")
    if args.public and not data["book"]["public_domain"]:
        data = strip_quotes(data)
    data["book"]["text"] = not args.public

    if outdir.exists() and any(outdir.iterdir()):
        if not (outdir / "data" / "wiki.json").exists():
            sys.exit(f"{outdir} is not empty and is not a previous export; refusing to replace it")
        shutil.rmtree(outdir)
    shutil.copytree(SITE, outdir)
    (outdir / "data").mkdir()
    (outdir / "data" / "wiki.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if not args.public:
        (outdir / "text").mkdir()
        for c in data["chapters"]:
            src = workdir / "chapters" / f"{c['n']:04d}.txt"
            if src.exists():
                shutil.copy(src, outdir / "text" / src.name)
    size = sum(p.stat().st_size for p in outdir.rglob("*") if p.is_file())
    print(f"exported {len(data['entities'])} entities, {len(data['facts'])} facts, chapters 1-{data['book']['max']} "
          f"to {outdir} ({'public' if args.public else 'private'}, {size / 1e6:.1f} MB)")

