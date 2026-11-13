import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from .book import added_types
from .checks import site_checks
from .corrections import correct_profiles, EVERY_CORRECTION, kept_deaths
from .families import read_families, relation_family
from .files import read_json, review_tools
from .llm import cached_reply
from .names import is_stub, name_key
from .pages import read_pages
from .profile import page_profiles
from .render import checkpoint_prompts, closed_arcs, history_prompts, kept_prompts, reader_parts, summary_prompt, WRITTEN, written_prompt
from .state import load_states
from .status import named_characters, spoken_appearances, stated_appearances
from .template import book_types, Types, written
from .text import mention_quote

SITE = Path(__file__).resolve().parent / "site"
THEMES = Path(__file__).resolve().parent / "themes"
QUOTE_KEYS = {"quote", "quotes", "resolve_quote"}
def entity_id(name):
    return hashlib.sha1(name.encode()).hexdigest()[:8]


def category_labels(categories, texts):
    """Each category's label in the book's words, from the first chapter that writes it, and never before its type exists."""
    labels = {}
    for t, spec in categories.items():
        start = next((n for n in sorted(texts) if spec.get("label") and written(spec["label"], texts[n])), None)
        if start is not None:
            labels[t] = {"text": spec["label"], "chapter": max(start, spec.get("chapter", 0))}
    return labels


def timeline(row):
    tid = row.get("timeline", "main")
    return {} if tid == "main" else {"timeline": tid}


def observations(rows):
    return [{"chapter": o["chapter"], "value": o["value"], "quotes": o["quotes"], **timeline(o),
             **({"shown": o["shown"]} if "shown" in o else {})} for o in rows if o.get("quote_ok")]


def written_history(workdir, key, page, evidence):
    history = []
    for c in sorted({o.get("shown", o["chapter"]) for o in evidence}):
        prompt = written_prompt(key, page, [o for o in evidence if o.get("shown", o["chapter"]) <= c])
        reply = prompt and cached_reply(workdir, WRITTEN[key].purpose, prompt)
        if reply and reply.get("paragraph"):
            history.append({"chapter": c, "text": str(reply["paragraph"]).strip()})
    return history


def export_profile(workdir, page, profile, spoke, appeared):
    fields = {k: observations(v) for k, v in {**profile["fields"], **profile["extra"]}.items()}
    lists = {k: observations(v) for k, v in profile["lists"].items()}
    written = {spec.purpose: written_history(workdir, key, page, [o for o in profile["lists"].get(key, []) if o.get("quote_ok")])
               for key, spec in WRITTEN.items()}
    return {"fields": {k: v for k, v in fields.items() if v}, "lists": {k: v for k, v in lists.items() if v},
            "spoke": [[c, tid] for c, tid in spoke], "appeared": [[c, tid] for c, tid in appeared], **written}


def entity_summary(workdir, entity, facts, safe_chapter, timelines, last, page):
    reply = cached_reply(workdir, "summary", summary_prompt(entity, facts, timelines, last, page))
    if not reply or not reply.get("summary"):
        return None
    return {"chapter": safe_chapter, "text": str(reply["summary"]).strip()}


def arc_history(workdir, prompts, page):
    history = []
    for arc, prompt in prompts:
        reply = cached_reply(workdir, "history", prompt)
        if reply and reply.get("paragraph"):
            history.append({"arc": arc["name"], "start": arc["start"], "end": arc["end"], "shown": max(arc["end"], page.known(arc["end"])[1]),
                            "text": str(reply["paragraph"]).strip()})
    return history


def kept_prose(workdir, prompts, joined, part, last, page):
    prose = {}
    if prompts["summary"]:
        unseen = last if len(part["aliases"]) < len(joined["aliases"]) else 0
        safe = max([joined["last_chapter"], part["name_chapter"], unseen] + [x["chapter"] for x in part["aliases"]])
        reply = cached_reply(workdir, "summary", prompts["summary"])
        if reply and reply.get("summary"):
            prose["summary"] = {"chapter": safe, "text": str(reply["summary"]).strip()}
    replies = {c: cached_reply(workdir, "summary", p) for c, p in prompts["summaries"].items()}
    running = [{"chapter": c, "text": str(r["summary"]).strip()} for c, r in replies.items() if r and r.get("summary")]
    history = arc_history(workdir, prompts["history"], page)
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


def ladder_records(ladders, registry, ids, step_type):
    records = []
    for ladder in ladders:
        group = ladder["group"] and registry.resolve(ladder["group"], ladder["group_type"])
        if group or ladder["group"] is None:
            steps = {}
            for s in ladder["steps"]:
                eid = ids[registry.resolve(s["entry"], step_type) or s["entry"]]
                if eid not in steps or s["chapter"] < steps[eid]["chapter"]:
                    steps[eid] = step_record(s, eid)
            records.append({"group": group and ids[group], "chapter": ladder["chapter"], "steps": list(steps.values())})
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


def version(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10]


def stamp_assets(outdir):
    page = outdir / "index.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace('href="app.css"', f'href="app.css?v={version(outdir / "app.css")}"')
    html = html.replace('<script src="app.js">', f'<script src="app.js?v={version(outdir / "app.js")}" '
                                                  f'data-wiki="data/wiki.json?v={version(outdir / "data" / "wiki.json")}">')
    page.write_text(html, encoding="utf-8")


def build(workdir, theme):
    book = {**read_json(workdir / "book.json", {}), **theme}
    title = book.get("title") or workdir.name
    kb = load_states(workdir, ladders=True, corrections=EVERY_CORRECTION)
    entities = list(kb.entities.values())
    pages = read_pages(workdir, kb)
    facts, relations, states, registry, absorbed = pages.facts, pages.relations, pages.states, pages.registry, pages.absorbed
    blurbs, texts, words, fact_page, rel_ends, names = pages.blurbs, pages.texts, pages.words, pages.fact_page, pages.rel_ends, pages.names
    timelines = kb.timelines
    spoken = spoken_appearances(facts + relations, lambda name, n: (c := registry.resolve(name)) and absorbed.page_for_name(c, name, n))
    appeared = stated_appearances([(fact_page[f["id"]], f, "entity") for f in facts]
                                  + [(page, r, end) for r, ends in zip(relations, rel_ends) for end, page in ends.items()], named_characters(kb.entities))
    titles = {c["index"]: c["title"] for c in read_json(workdir / "chapters.json", [])}
    chapters = [{"n": s["chapter"], "title": titles.get(s["chapter"], str(s["chapter"])),
                 "synopsis": str(s["extraction"].get("synopsis") or "").strip()} for s in states]
    last = max((c["n"] for c in chapters), default=0)
    by_entity = {}
    for f in facts:
        by_entity.setdefault(f["entity"], []).append(f)
    profiles, missed = correct_profiles(kb, page_profiles(workdir, entities, read_json(workdir / "profiles.json", {"characters": {}})["characters"]),
                                        kb.corrections)
    ids = {name: entity_id(name) for name in [e["name"] for e in entities] + list(absorbed.entries)}
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
    added = added_types(workdir)
    categories = {**book_types(book.get("power_types")), **added}
    kinds = Types({t: spec["parent"] for t, spec in categories.items()})
    types = {e["name"]: kinds.kind(e["type"]) for e in entities}

    out_entities = []
    for e in entities:
        page = names[e["name"]]
        record = {"id": ids[e["name"]], "name": page.name, "name_chapter": page.chapter, "type": e["type"],
                  "first": page.first, "aliases": page.aliases, "blurbs": blurbs.get(e["name"], []), **nameless(e["type"], e),
                  **({"retyped": e["retyped"]} if e.get("retyped") else {})}
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
            unseen = 0 if all(page.knows(a, last) for a in e["aliases"]) else last
            safe = max([e["last_chapter"], page.known(last)[1], unseen] + [a["chapter"] for a in page.aliases])
            summary = entity_summary(workdir, e, own, safe, timelines, last, page)
            if summary:
                record["summary"] = summary
            replies = {c: cached_reply(workdir, "summary", prompt) for c, prompt in checkpoint_prompts(e, own, timelines, page).items()}
            running = [{"chapter": c, "text": str(r["summary"]).strip()} for c, r in replies.items() if r and r.get("summary")]
            if running:
                record["summaries"] = running
        if e["name"] in profiles:
            record["profile"] = export_profile(workdir, page, profiles[e["name"]], spoken.get(e["name"], []), appeared.get(e["name"], []))
        if e["type"] == "character":
            history = arc_history(workdir, history_prompts(e, own, ties.get(e["name"], []), arcs, timelines, page), page)
            if history:
                record["history"] = history
        out_entities.append(record)
        kept = {a["name"]: kept_prompts(a, own, ties.get(e["name"], []), arcs, timelines, last, names[a["name"]]) for a in reader_parts(e)}
        for a in e.get("absorbed", []):
            kind = a.get("type", e["type"])
            named = names[a["name"]]
            part = {"id": ids[a["name"]], "name": named.name, "name_chapter": named.chapter, "type": kind, "first": named.first, "aliases": named.aliases,
                    "blurbs": blurbs.get(a["name"], []), "merged": {"into": ids[e["name"]], "chapter": a["chapter"]}, **nameless(kind, a)}
            part["mention"] = first_mention(texts, part)
            if kind == "character":
                part["present"] = sorted(present.get(a["name"], ()))
            if a["name"] in profiles:
                part["profile"] = export_profile(workdir, named, profiles[a["name"]], spoken.get(a["name"], []), appeared.get(a["name"], []))
            if a["name"] in kept:
                part.update(kept_prose(workdir, kept[a["name"]], a, part, last, named))
            out_entities.append(part)

    for record in out_entities:
        if record.get("nameless") and not is_stub({"name": record["name"]}):
            record["named_from"] = record["name_chapter"]
    return kb.problems + missed, {
        "book": {"title": title, "max": last,
                 "public_domain": book.get("public_domain") is True, "theme": book.get("theme") or stored_theme(title),
                 "power_types": sorted(categories), "parents": kinds.parents, "labels": category_labels(categories, texts),
                 "added": {t: spec["chapter"] for t, spec in added.items()},
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
        "ladders": ladder_records(kb.ladder_rows, registry, ids, (book.get("ladder") or {}).get("step_type")),
        "volumes": sorted((v for v in (volume_record(read_json(p, {}), kb) for p in (workdir / "volumes").glob("*.json")) if v["from"] <= last),
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
    if not args.public and review_tools(workdir):
        data["checks"] = site_checks(workdir, data["entities"], data["facts"])

    if outdir.exists() and any(outdir.iterdir()):
        if not (outdir / "data" / "wiki.json").exists():
            sys.exit(f"{outdir} is not empty and is not a previous export; refusing to replace it")
        shutil.rmtree(outdir)
    shutil.copytree(SITE, outdir)
    (outdir / "data").mkdir()
    (outdir / "data" / "wiki.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    stamp_assets(outdir)
    if not args.public:
        (outdir / "text").mkdir()
        for c in data["chapters"]:
            src = workdir / "chapters" / f"{c['n']:04d}.txt"
            if src.exists():
                shutil.copy(src, outdir / "text" / src.name)
    size = sum(p.stat().st_size for p in outdir.rglob("*") if p.is_file())
    print(f"exported {len(data['entities'])} entities, {len(data['facts'])} facts, chapters 1-{data['book']['max']} "
          f"to {outdir} ({'public' if args.public else 'private'}, {size / 1e6:.1f} MB)")

