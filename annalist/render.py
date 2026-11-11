import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .book import load_book
from .files import read_json, write_atomic
from .families import wording_key
from .llm import cached_llm
from .names import display_names, name_key, slug
from .profile import page_profiles
from .state import load_states, timeline_line, timeline_role, timeline_tag, UNRESOLVED
from .status import current_status, spoken_appearances
from .template import PROFILE_FIELDS, PROFILE_LISTS, SECTIONS
from .text import chapter_text, mention_quote, verified_quotes
from .tiers import tier_at, TIER_HEADINGS, TIER_ORDER


SUMMARY_PROMPT = """Write the opening paragraph of a wiki page about "{name}" ({type}) from a novel, using ONLY the facts below, which come from the chapters read so far. Do not add anything from outside knowledge. Keep what characters merely believe or suspect clearly marked as belief, not fact. Three to six sentences, plain prose, no headings.

Known aliases: {aliases}

Facts (chapter, status, asserted by, claim):
{facts}

Reply with one JSON object: {{"summary": "..."}}
"""


SUMMARY_TIMELINE_RULE = """
Some facts carry a timeline tag in brackets. A fact tagged erased happened only in a timeline that was later undone: mention it only as such, never as the present state. A fact tagged flashback, vision, or alternate holds only for that past or scene, not the present.
"""


def tagged_lines(rows, timelines, until, line):
    tags = [timeline_tag(timelines, r.get("timeline", "main"), until) for r in rows]
    return "\n".join(line(r, f" [{tag}]" if tag else "") for r, tag in zip(rows, tags)), any(tags)


def fact_line(f, tag):
    return f"- ch{f['chapter']}, {f['status']}, {f['asserted_by']}{tag}: {f['claim']}"


def summary_prompt(entity, facts, timelines, until, aliases=None):
    lines, tagged = tagged_lines(facts, timelines, until, fact_line)
    aliases = entity["aliases"] if aliases is None else aliases
    prompt = SUMMARY_PROMPT.format(name=entity["name"], type=entity["type"], aliases=", ".join(aliases) or "none", facts=lines)
    return prompt + SUMMARY_TIMELINE_RULE if tagged else prompt


def page_facts(entity, facts):
    later = {a["name"]: a["chapter"] for a in entity.get("absorbed", [])}
    return sorted((f for f in facts if not (f.get("filed") in later and f["chapter"] < later[f["filed"]])), key=lambda f: f["chapter"])


def named_aliases(entity, text):
    return [a for a in entity["aliases"] if re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text)]


def checkpoint_prompts(entity, facts, timelines, first=3):
    own = page_facts(entity, facts)
    prompts, k = {}, first
    while k < len(own):
        c = own[k - 1]["chapter"]
        upto = [f for f in own if f["chapter"] <= c]
        aliases = named_aliases(entity, " ".join(x for f in upto for x in [f["claim"], *f["quotes"]]))
        prompts.setdefault(c, summary_prompt(entity, upto, timelines, c, aliases))
        k *= 2
    return prompts


HISTORY_PROMPT = """Write one section of the History of "{name}", a character in a novel, for a fan wiki: what this character did and what happened to them during the story arc "{arc}" (chapters {start} to {end}). Use ONLY the facts and relations below, which come from those chapters. One paragraph of two to five sentences of plain past-tense prose, in story order. Cite the chapter of each claim inline as (ch N). Keep what characters merely believe or suspect clearly marked as belief. Do not add anything from outside knowledge.

Known aliases: {aliases}

Facts (chapter, status, asserted by, claim):
{facts}

Relations (chapter, source, relation, target):
{relations}

Reply with one JSON object: {{"paragraph": "..."}}
"""


HISTORY_MIN_FACTS = 5


def relation_line(r, tag):
    ends = [(r.get("filed") or {}).get(end, r[end]) for end in ("source", "target")]
    detail = f" {r['detail']}" if r.get("detail") else ""
    return f"- ch{r['chapter']}{tag}: {ends[0]} {r['type']} {ends[1]}{detail}"


def history_prompts(entity, facts, relations, arcs, timelines):
    own = [f for f in page_facts(entity, facts) if f.get("quote_ok")]
    later = {a["name"]: a["chapter"] for a in entity.get("absorbed", [])}
    ties = sorted((r for r in relations if r.get("quote_ok") and any(
        r[end] == entity["name"] and not ((r.get("filed") or {}).get(end) in later and r["chapter"] < later[r["filed"][end]])
        for end in ("source", "target"))), key=lambda r: r["chapter"])
    prompts = []
    for arc in arcs:
        inside = [f for f in own if arc["start"] <= f["chapter"] <= arc["end"]]
        if len(inside) < HISTORY_MIN_FACTS:
            continue
        rels = [r for r in ties if arc["start"] <= r["chapter"] <= arc["end"]]
        fact_text, fact_tagged = tagged_lines(inside, timelines, arc["end"], fact_line)
        rel_text, rel_tagged = tagged_lines(rels, timelines, arc["end"], relation_line)
        aliases = named_aliases(entity, " ".join(x for row in inside + rels for x in [row.get("claim", ""), *row["quotes"]]))
        prompt = HISTORY_PROMPT.format(name=entity["name"], arc=arc["name"], start=arc["start"], end=arc["end"],
                                       aliases=", ".join(aliases) or "none", facts=fact_text, relations=rel_text or "none")
        prompts.append((arc, prompt + SUMMARY_TIMELINE_RULE if fact_tagged or rel_tagged else prompt))
    return prompts


def finished_arcs(workdir, until=None):
    volumes = sorted((read_json(p, {}) for p in (Path(workdir) / "volumes").glob("*.json")), key=lambda v: v["from"])
    return [a for v in volumes for a in v.get("arcs", []) if until is None or a["end"] <= until]


def entity_summary(workdir, entity, facts, timelines, until):
    out = cached_llm(workdir, "summary", summary_prompt(entity, facts, timelines, until))
    return str(out.get("summary") or "").strip()


def chapter_refs(numbers, lo, hi, link):
    valid = sorted({n for n in numbers if isinstance(n, int) and lo <= n <= hi}) if isinstance(numbers, list) else []
    return ", ".join(link(n) for n in valid)


UNCLEAR_NOTE = " *(unclear whether the story means to leave this open)*"


def ending_groups(opens):
    verdict = {q["id"]: q.get("ending", {}).get("verdict") for q in opens}
    implied = [q for q in opens if verdict[q["id"]] == "answered-implicitly"]
    loose = [q for q in opens if verdict[q["id"]] == "dropped-thread"]
    mysteries = sorted((q for q in opens if q not in implied and q not in loose), key=lambda q: (verdict[q["id"]] != "left-open", q["id"]))
    return implied, mysteries, loose


def volume_markdown(spec, kb, paths, chapter_link, power_types):
    lo, hi, page = spec["from"], spec["to"], spec["page"]

    def link(n):
        return f"[{n}]({chapter_link(n, 1).split('](', 1)[1]}"

    def entity(name):
        for key in dict.fromkeys([name_key(name), name_key(re.sub(r"\s*\(.*?\)", "", name))]):
            people = [k for k, e in kb.entities.items()
                      if e["type"] == "character" and key in map(name_key, [e["name"]] + e["aliases"])]
            canonical = (people or [kb.resolve(key)])[0]
            if canonical in paths:
                return f"[{name}](../{paths[canonical]}.md)"
        return name

    def item_list(rows):
        return [f"- {r}" for r in rows] + [""] if rows else ["None.", ""]

    lines = [f"# {spec['name']}", "", f"*Chapters {lo} to {hi}. Built only from chapters 1 to {hi}.*", "",
             "## Overview", "", str(page.get("overview") or "").strip(), "", "## Plot summary", ""]
    for a in spec["arcs"]:
        lines += [f"### {a['name']}", "", f"*Chapters {link(a['start'])} to {link(a['end'])}.*", "", a["summary"], ""]
    facts = {f["id"]: f for f in kb.facts}
    lines += ["## Key events", ""]
    for e in spec.get("key_events") or []:
        lines.append(f"- {e['event']} (ch {chapter_refs(e['chapters'], lo, hi, link)})")
        quote = next((facts[i]["quotes"][0] for i in e["facts"] if i in facts and facts[i]["quotes"]), "")
        lines += [blockquote(quote), ""] if quote else []
    if not spec.get("key_events"):
        lines += ["None.", ""]
    lines += ["## Deaths", ""]
    for d in spec.get("deaths") or []:
        flag = "" if d["quote_ok"] else " **[quote not found in chapter]**"
        revived = f" Revived in ch {link(d['revived'])}." if d.get("revived") else ""
        lines.append(f"- **{entity(d['name'])}** (ch {link(d['chapter'])}): {d['circumstances']}{revived}{flag}")
        lines += [blockquote(d["quotes"][0]), ""] if d["quotes"] else []
    if not spec.get("deaths"):
        lines += ["None.", ""]
    lines += ["## Character development", ""]
    lines += item_list([f"**{entity(c.get('character', ''))}**: {c.get('development', '')} (ch {chapter_refs(c.get('chapters'), lo, hi, link)})"
                        for c in page.get("character_development") or [] if isinstance(c, dict)])
    introduced = sorted((e for e in kb.entities.values() if lo <= e["first_chapter"] <= hi), key=lambda e: (e["first_chapter"], e["name"]))
    lines += ["## Characters introduced", ""]
    lines += item_list([f"{entity(e['name'])} (ch {link(e['first_chapter'])}): {e['summary']}" for e in introduced if e["type"] == "character"])
    lines += ["## Power system introduced", ""]
    lines += item_list([f"{entity(e['name'])} *{e['type']}* (ch {link(e['first_chapter'])}): {e['summary']}" for e in introduced if e["type"] in power_types])
    base = slug(spec["name"])
    resolved = [q for q in kb.questions.values() if q["status"] == "resolved" and lo <= q["resolved_chapter"] <= hi]
    _, threads, loose = ending_groups([q for q in kb.questions.values() if q["status"] in UNRESOLVED])
    lines += ["## Mysteries and open threads", "",
              f"- [Mysteries raised and resolved]({base}-mysteries.md): {len(resolved)} payoffs",
              f"- [Threads left open at volume end]({base}-threads.md): {len(threads)} questions"
              + (f", {len(loose)} loose ends" if loose else ""), ""]
    mysteries = [f"# {spec['name']}: mysteries raised and resolved", "", f"[Back to {spec['name']}]({base}.md)", ""]
    mysteries += item_list([f"**{q['question']}** Raised in ch {link(q['chapter'])}, resolved in ch {link(q['resolved_chapter'])}: {q['answer']} *Payoff:* {q.get('payoff', '')}"
                            for q in resolved])
    open_lines = [f"# {spec['name']}: threads left open", "", f"[Back to {spec['name']}]({base}.md)", ""]
    for q in threads:
        note = UNCLEAR_NOTE if q.get("ending", {}).get("verdict") == "unclear" else ""
        open_lines.append(f"- {q['question']} (raised in ch {link(q['chapter'])}){note}")
        open_lines += [f"- *Lead from ch {link(l['chapter'])}:* {l['text']}" for l in q["leads"]]
    if not threads:
        open_lines.append("None.")
    if loose:
        open_lines += ["", f"## Loose ends ({len(loose)})", ""]
        open_lines += [f"- {q['question']} (raised in ch {link(q['chapter'])})" for q in loose]
    return {f"volumes/{base}.md": (spec["name"], "\n".join(lines)),
            f"volumes/{base}-mysteries.md": (f"{spec['name']}: mysteries", "\n".join(mysteries)),
            f"volumes/{base}-threads.md": (f"{spec['name']}: open threads", "\n".join(open_lines))}


def blockquote(text):
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


PERSONALITY_PROMPT = """Write the Personality section of a fan-wiki page about "{name}", a character in a novel, using ONLY the evidence below (chapter, trait, quote). One paragraph of three to five sentences in plain prose. Cite the chapter of each claim inline as (ch N). Do not add anything the evidence does not show and nothing from outside the novel.

{evidence}

Reply with one JSON object: {{"paragraph": "..."}}
"""


def visible(observations, until):
    return [o for o in observations if o.get("shown", o["chapter"]) <= until and o.get("quote_ok")]


def personality_paragraph(workdir, name, evidence):
    lines = "\n".join(f"- ch{o['chapter']}: {o['value']} | \"{o['quotes'][0]}\"" for o in evidence if o["quotes"])
    return str(cached_llm(workdir, "personality", PERSONALITY_PROMPT.format(name=name, evidence=lines)).get("paragraph") or "").strip()


def capitalized(value):
    return value[:1].upper() + value[1:]


def status_cell(status, link):
    if status.basis == "erased_death":
        return f"Alive (died only in an erased timeline, {link(status.chapter)})"
    if status.basis == "spoke":
        cell = f"Alive (as of {link(status.chapter)}, inferred)"
        if status.erased_death:
            cell += f", died only in an erased timeline ({link(status.erased_death)})"
    else:
        cell = f"{capitalized(status.value)} ({link(status.chapter)})"
    if status.earlier:
        cell += ", previously " + ", ".join(f"{capitalized(o['value'])} ({link(o['chapter'])})" for o in status.earlier)
    return cell


def infobox_rows(profile, until, link, timelines, spoken):
    rows = []
    fields = [(PROFILE_FIELDS[k], k, profile["fields"].get(k, [])) for k in PROFILE_FIELDS]
    fields += [(k.replace("_", " ").capitalize(), k, v) for k, v in profile["extra"].items()]
    for label, key, observations in fields:
        if key == "status":
            status = current_status(observations, spoken, timelines, until)
            rows += [f"| **{label}** | {status_cell(status, link)} |"] if status else []
            continue
        shown = [o for o in visible(observations, until) if timeline_role(timelines.get(o.get("timeline", "main")), until) == "current"]
        if not shown:
            continue
        latest = shown[-1]
        earlier = []
        for o in reversed(shown[:-1]):
            if name_key(o["value"]) != name_key(latest["value"]) and all(name_key(o["value"]) != name_key(e["value"]) for e in earlier):
                earlier.append(o)
        cell = f"{capitalized(latest['value'])} ({link(latest['chapter'])})"
        if earlier:
            cell += ", previously " + ", ".join(f"{capitalized(o['value'])} ({link(o['chapter'])})" for o in earlier)
        rows.append(f"| **{label}** | {cell} |")
    return rows


def cited_chapters(text, until, link):
    return re.sub(r"\(ch ?(\d+)\)", lambda m: f"({link(int(m.group(1)))})" if int(m.group(1)) <= until else m.group(0), text)


def arc_histories(workdir, kb, by_entity, arcs, pool):
    people = [n for n, e in kb.entities.items() if e["type"] == "character" and len(by_entity.get(n, [])) >= HISTORY_MIN_FACTS]
    wanted, ties = set(people), {}
    for r in kb.relations:
        for end in ("source", "target"):
            if r[end] in wanted:
                ties.setdefault(r[end], []).append(r)
    for r in {id(r): r for rows in ties.values() for r in rows}.values():
        r.update(verified_quotes(workdir, r["chapter"], r["quotes"]))
    jobs = [(n, arc, prompt) for n in people
            for arc, prompt in history_prompts(kb.entities[n], by_entity[n], ties.get(n, []), arcs, kb.timelines)]
    replies = pool.map(lambda job: cached_llm(workdir, "history", job[2]), jobs)
    histories = {}
    for (n, arc, _), reply in zip(jobs, replies):
        text = str(reply.get("paragraph") or "").strip()
        if text:
            histories.setdefault(n, []).append((arc, text))
    return histories


def profile_sections(profile, personality, until, link, timelines, spoken):
    lines = []
    rows = infobox_rows(profile, until, link, timelines, spoken)
    if rows:
        lines += ["| | |", "|---|---|"] + rows + [""]
    for key, title in PROFILE_LISTS.items():
        shown = visible(profile["lists"].get(key, []), until)
        if not shown:
            continue
        lines += [f"## {title}", ""]
        if key == "personality_evidence":
            lines += [cited_chapters(personality, until, link), ""]
            continue
        for o in shown:
            tag = timeline_tag(timelines, o.get("timeline", "main"), until)
            lines.append(f"- {o['value']} ({link(o['chapter'])})" + (f" *({tag})*" if tag else ""))
            for q in o["quotes"][:1]:
                lines += [blockquote(q), ""]
    return lines


def group_relations(rows, role):
    groups = {}
    for r in rows:
        key = (r["source"], wording_key(r["type"]), r["target"], wording_key(r["detail"]),
               "" if role(r) == "current" else r.get("timeline", "main"))
        groups.setdefault(key, []).append(r)
    return list(groups.values())


def md_inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{re.sub(r"[.]md$", ".html", m.group(2))}">{m.group(1)}</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)


def md_to_html(markdown, title):
    body, para, quote, items, table = [], [], [], [], []

    def flush():
        if table:
            cells = [[md_inline(c.strip()) for c in row.strip().strip("|").split("|")] for row in table
                     if not re.fullmatch(r"\|[\s|:-]*\|", row.strip()) and row.strip("| \t")]
            body.append('<table class="infobox">' + "".join(
                f"<tr><th>{r[0]}</th><td>{' | '.join(r[1:])}</td></tr>" for r in cells) + "</table>")
            table.clear()
        if para:
            body.append(f"<p>{md_inline(' '.join(para))}</p>")
            para.clear()
        if quote:
            body.append("<blockquote><p>" + "<br>".join(md_inline(q) for q in quote) + "</p></blockquote>")
            quote.clear()
        if items:
            body.append("<ul>" + "".join(f"<li>{md_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in markdown.splitlines():
        heading = re.match(r"(#{1,6}) (.*)", line)
        if line.startswith(("<details>", "</details>")):
            flush()
            body.append(line)
        elif heading:
            flush()
            level = len(heading.group(1))
            body.append(f"<h{level}>{md_inline(heading.group(2))}</h{level}>")
        elif line.startswith("|"):
            if para or quote or items:
                flush()
            table.append(line)
        elif line.startswith(">"):
            if para or items:
                q = list(quote)
                quote.clear()
                flush()
                quote.extend(q)
            quote.append(line[1:].strip())
        elif line.startswith("- "):
            if para or quote or table:
                flush()
            items.append(line[2:])
        elif not line.strip():
            flush()
        else:
            if quote or items or table:
                flush()
            para.append(line.strip())
    flush()
    style = ("body{max-width:46rem;margin:2rem auto;padding:0 1rem;font:16px/1.55 Georgia,serif;color:#222;background:#fdfcf8}"
             "blockquote{margin:.3rem 0 1rem 1rem;padding-left:.8rem;border-left:3px solid #ccc;color:#555}"
             "a{color:#2a5d9f}li{margin:.4rem 0}"
             ".infobox{float:right;margin:0 0 1rem 1rem;border:1px solid #ccc;background:#f4f1e8;font-size:14px;max-width:18rem;border-collapse:collapse}"
             ".infobox th,.infobox td{padding:.3rem .5rem;text-align:left;vertical-align:top;border-top:1px solid #ddd}")
    return (f"<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title>"
            f"<style>{style}</style></head><body>\n" + "\n".join(body) + "\n</body></html>\n")


def cmd_render(args):
    workdir = Path(args.workdir).resolve()
    until = args.until
    kb = load_states(workdir, until=until, ladders=True)
    shown = display_names(kb.entities)
    until = until if until is not None else max(kb.synopses, default=0)
    out_dir = workdir / (f"wiki-ch{args.until:04d}" if args.until is not None else "wiki")
    titles = {c["index"]: c["title"] for c in json.loads((workdir / "chapters.json").read_text(encoding="utf-8"))}
    profiles = page_profiles(workdir, read_json(workdir / "entities.json", []),
                             read_json(workdir / "profiles.json", {"characters": {}})["characters"])
    profiles = {k: v for k, v in profiles.items() if k in kb.entities and kb.entities[k]["type"] == "character"}
    for f in kb.facts:
        f.update(verified_quotes(workdir, f["chapter"], f["quotes"]))

    by_entity = {}
    for f in kb.facts:
        by_entity.setdefault(f["entity"], []).append(f)
    spoken = spoken_appearances(kb.facts + kb.relations, lambda name, _: kb.resolve(name))
    bare = set(kb.bare_entities())
    paths, used = {}, set()
    for name, e in kb.entities.items():
        if name in bare:
            continue
        rel = f"{slug(e['type'])}/{slug(name)}"
        while rel in used:
            rel += "-x"
        used.add(rel)
        paths[name] = rel

    needs_summary = [n for n in kb.entities if len(by_entity.get(n, [])) >= 3]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        summaries = dict(zip(needs_summary, pool.map(
            lambda n: entity_summary(workdir, kb.entities[n], by_entity[n], kb.timelines, until), needs_summary)))
        list(pool.map(lambda prompt: cached_llm(workdir, "summary", prompt),
                      [x for n in needs_summary for x in checkpoint_prompts(kb.entities[n], by_entity[n], kb.timelines).values()]))
        evidence = {n: visible(p["lists"].get("personality_evidence", []), until) for n, p in profiles.items()}
        evidence = {n: v for n, v in evidence.items() if v}
        personalities = dict(zip(evidence, pool.map(lambda n: personality_paragraph(workdir, n, evidence[n]), evidence)))
        histories = arc_histories(workdir, kb, by_entity, finished_arcs(workdir, until), pool)

    def chapter_link(n, depth):
        return f"[Ch {n}: {titles.get(n, n)}]({'../' * depth}../chapters/{n:04d}.txt)"

    def cite(n):
        return f"[ch {n}](../../chapters/{n:04d}.txt)"

    def role(row):
        return timeline_role(kb.timelines.get(row.get("timeline", "main")), until)

    def tag(row):
        text = timeline_tag(kb.timelines, row.get("timeline", "main"), until)
        return f" *({text})*" if text and role(row) != "erased" else ""

    def fact_lines(rows):
        lines = []
        for f in rows:
            flag = " **[quote not found in chapter]**" if not f["quote_ok"] else ""
            source = "narrator" if f["asserted_by"].lower() == "narrator" else f"according to {f['asserted_by']}"
            lines.append(f"- {chapter_link(f['chapter'], 1)}: {f['claim']} *({f['status']}, {source})*{tag(f)}{flag}")
            for q in f["quotes"]:
                lines += [blockquote(q), ""]
        return lines

    def relation_lines(rows, name):
        lines = []
        for group in group_relations(rows, role):
            r = group[0]
            ends = [f"[{shown[x]}](../{paths[x]}.md)" if x != name else shown[x] for x in (r["source"], r["target"])]
            chapters = ", ".join(chapter_link(c, 1) for c in sorted({g["chapter"] for g in group}))
            statuses = ", ".join(dict.fromkeys(g["status"] for g in group))
            detail = f" {r['detail']}" if r["detail"] else ""
            lines.append(f"- {ends[0]} *{r['type']}* {ends[1]}{detail} ({chapters}, {statuses}){tag(r)}")
        return lines

    pages = {}
    for name, e in kb.entities.items():
        if name in bare:
            continue
        facts = sorted(by_entity.get(name, []), key=lambda f: (f["chapter"], f["id"]))
        lines = [f"# {shown[name]}", "",
                 f"*Type: {e['type']}. First seen: chapter {e['first_chapter']}."
                 + (f" Also known as: {', '.join(e['aliases'])}.*" if e["aliases"] else "*"), "",
                 summaries.get(name) or e["summary"] or "No summary yet.", ""]
        if name in profiles:
            lines += profile_sections(profiles[name], personalities.get(name, ""), until, cite, kb.timelines, spoken.get(name, []))
        if histories.get(name):
            lines += ["## History", ""]
        for arc, text in histories.get(name, []):
            lines += [f"### {arc['name']}", "", f"*Chapters {arc['start']} to {arc['end']}.*", "", cited_chapters(text, until, cite), ""]
        rels = [r for r in kb.relations if name in (r["source"], r["target"])]
        erased = {}
        for row in facts + rels:
            if role(row) == "erased":
                erased.setdefault(row["timeline"], []).append(row)
        facts = [f for f in facts if role(f) != "erased"]
        rels = [r for r in rels if role(r) != "erased"]
        lines += [f"## {SECTIONS['facts']}", ""]
        if not facts:
            lines += ["No facts recorded yet.", ""]
        lines += fact_lines(facts)
        if rels:
            lines += [f"## {SECTIONS['relations']}", ""]
        lines += relation_lines(rels, name)
        if erased:
            lines += ["", f"## {SECTIONS['erased']}", ""]
        for tid in sorted(erased, key=lambda t: kb.timelines[t]["started"]):
            t = kb.timelines[tid]
            lines += [f"### {t['label'] or tid}", "", f"*Began in ch {t['started']}, undone in ch {t['erased']}.*", ""]
            lines += fact_lines([f for f in erased[tid] if "claim" in f])
            lines += relation_lines([r for r in erased[tid] if "claim" not in r], name)
        pages[paths[name] + ".md"] = (shown[name], "\n".join(lines))

    types = {}
    for name, e in kb.entities.items():
        types.setdefault(e["type"], []).append(name)
    index = [f"# Wiki as of chapter {until}", "",
             f"{len(paths)} entities, {len(kb.facts)} facts, {len(kb.questions)} questions. "
             f"Only chapters 1 to {until} are used, so nothing here spoils later chapters.", "",
             "[Chapter synopses](chapters/index.md) | [Open questions and payoffs](open-questions.md)"
             + (" | [Timelines](timelines.md)" if len(kb.timelines) > 1 else ""), ""]
    volumes = sorted((json.loads(p.read_text(encoding="utf-8")) for p in (workdir / "volumes").glob("*.json")), key=lambda v: (v["from"], v["to"]))
    volumes = [v for v in volumes if v["to"] <= until]
    if volumes:
        index += ["## Volumes", ""]
    for v in volumes:
        index.append(f"- [{v['name']}](volumes/{slug(v['name'])}.md): chapters {v['from']} to {v['to']}")
        pages.update(volume_markdown(v, load_states(workdir, until=v["to"], ladders=True), paths, chapter_link, load_book(workdir)["power_types"]))
    if volumes:
        index.append("")
    for t in sorted(types, key=lambda t: (-len(types[t]), t)):
        full = [n for n in types[t] if n not in bare]
        index += [f"## {t} ({len(full)})", ""]
        for name in sorted(full, key=lambda n: (-len(by_entity.get(n, [])), n.lower())):
            index.append(f"- [{shown[name]}]({paths[name]}.md): {kb.entities[name]['summary']} ({len(by_entity.get(name, []))} fact{'' if len(by_entity.get(name, [])) == 1 else 's'})")
        minor = sorted((kb.entities[n] for n in types[t] if n in bare), key=lambda e: (e["first_chapter"], e["name"].lower()))
        if minor:
            index += ["", f"### Minor mentions ({len(minor)})", ""]
        for e in minor:
            quote = mention_quote(chapter_text(workdir, e["first_chapter"]), [e["name"]] + e["aliases"])
            index.append(f"- {shown[e['name']]} (ch {e['first_chapter']})" + (f": \"{quote}\"" if quote else ""))
        index.append("")
    pages["index.md"] = (f"Wiki as of chapter {until}", "\n".join(index))

    opens = [q for q in kb.questions.values() if q["status"] in UNRESOLVED]
    resolved = [q for q in kb.questions.values() if q["status"] == "resolved"]
    tiers = read_json(workdir / "tiers.json", {"questions": {}})["questions"]
    oq = [f"# Questions as of chapter {until}", ""]
    end = read_json(workdir / "ending.json", {"last": None})["last"]
    if end is not None and until >= end:
        answered = [q for q in resolved if q.get("found_by") == "ending"]
        implied, mysteries, loose = ending_groups(opens)
        resolved = [q for q in resolved if q not in answered]
        oq += [f"## Answered at the end ({len(answered) + len(implied)})", ""]
        for q in answered:
            oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}", blockquote(q["quote"]), "",
                   f"- *Answered in* {chapter_link(q['resolved_chapter'], 0)}: {q['answer']}", blockquote(q["resolve_quote"]), "",
                   f"- *Payoff:* {q.get('payoff', '')}", ""]
        for q in implied:
            oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}", blockquote(q["quote"]), "",
                   f"- *Answered by the story as a whole:* {q['ending']['answer']}", ""]
            for row in q["ending"]["quotes"]:
                oq += [f"- *From* {chapter_link(row['chapter'], 0)}:", blockquote(row["quote"]), ""]
        oq += [f"## Open mysteries ({len(mysteries)})", ""]
        for q in mysteries:
            note = {"left-open": "", "unclear": UNCLEAR_NOTE}.get(q.get("ending", {}).get("verdict"), " *(not judged)*")
            oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}{tag(q)}{note}", blockquote(q["quote"]), ""]
        oq += [f"## Loose ends ({len(loose)})", "", f"<details><summary>Threads the story never followed up ({len(loose)})</summary>", ""]
        oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}{tag(q)}" for q in loose]
        oq += ["", "</details>", ""]
        opens = []
    else:
        oq += [f"## Open ({len(opens)})", ""]
    for tier in reversed(TIER_ORDER):
        group = [q for q in opens if tier_at(tiers.get(q["id"], {}), until) == tier]
        if group:
            oq += [f"### {TIER_HEADINGS[tier]} ({len(group)})", ""]
        for q in group:
            if tier == "cliffhanger":
                oq.append(f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}{tag(q)}")
                continue
            oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}{tag(q)}", blockquote(q["quote"]), ""]
            if q["leads"]:
                oq += ["*Leads:*", ""]
            for l in q["leads"]:
                oq += [f"- *Lead from* {chapter_link(l['chapter'], 0)}: {l['text']}", blockquote(l["quote"]), ""]
            for r in q.get("rejected", []):
                if not r.get("lead"):
                    oq += [f"- *Rejected resolution from chapter {r['chapter']}:* {r['answer']} *Reread verdict:* {r.get('reason', '')}", ""]
        if group and tier == "cliffhanger":
            oq.append("")
    oq += [f"## Resolved ({len(resolved)})", ""]
    for q in resolved:
        oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}", blockquote(q["quote"]), "",
               f"- *Resolved in* {chapter_link(q['resolved_chapter'], 0)}: {q['answer']}", blockquote(q["resolve_quote"]), "",
               f"- *Payoff:* {q.get('payoff', '')}", ""]
    if not resolved:
        oq += ["None yet.", ""]
    refuted = [q for q in kb.questions.values() if q["status"] == "premise-false"]
    if refuted:
        oq += [f"## Premise does not hold ({len(refuted)})", ""]
    for q in refuted:
        oq += [f"- **{q['id']}** {chapter_link(q['chapter'], 0)}: {q['question']}", blockquote(q["quote"]), "",
               f"- *Shown false by* {chapter_link(q['premise']['chapter'], 0)}: {q['premise']['explanation']}", ""]
        for row in q["premise"]["quotes"]:
            oq += [f"- *From* {chapter_link(row['chapter'], 0)}:", blockquote(row["quote"]), ""]
    pages["open-questions.md"] = (f"Questions as of chapter {until}", "\n".join(oq))

    chap = [f"# Chapters 1 to {until}", ""]
    for n in sorted(kb.synopses):
        chap += [f"## {chapter_link(n, 1)}", "", kb.synopses[n] or "No synopsis recorded.", ""]
    pages["chapters/index.md"] = (f"Chapters 1 to {until}", "\n".join(chap))
    if len(kb.timelines) > 1:
        tl = [f"# Timelines as of chapter {until}", ""]
        for t in kb.timelines.values():
            items = sum(row.get("timeline", "main") == t["id"] for row in kb.facts + kb.relations)
            tl.append(f"- {timeline_line(t)} ({items} facts and relations)")
        pages["timelines.md"] = (f"Timelines as of chapter {until}", "\n".join(tl))

    written = set()
    for rel, (title, text) in pages.items():
        write_atomic(out_dir / rel, text)
        written.add(out_dir / rel)
        if args.html:
            write_atomic(out_dir / re.sub(r"[.]md$", ".html", rel), md_to_html(text, title))
            written.add(out_dir / re.sub(r"[.]md$", ".html", rel))
    stale = [p for p in out_dir.rglob("*") if p.is_file() and p.suffix in (".md", ".html") and p not in written]
    for p in stale:
        p.unlink()
    for d in sorted((d for d in out_dir.rglob("*") if d.is_dir()), key=lambda d: -len(d.parts)):
        if not any(d.iterdir()):
            d.rmdir()
    print(f"rendered {len(pages)} pages to {out_dir} ({len(summaries)} summaries, {len(stale)} stale files removed)")
