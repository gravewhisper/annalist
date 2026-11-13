import re
from dataclasses import dataclass
from pathlib import Path

from .book import added_types, load_book
from .files import read_json, state_paths, write_atomic, write_json
from .evidence import class_pattern, stems
from .names import name_key, names_of
from .ranks import rank_mentions
from .state import load_states, timeline_role
from .status import current_status, kb_appearances, spoken_appearances
from .survey import people_in_type, speakers
from .template import category_problems, INDIVIDUALS, UNCATEGORIZED
from .text import chapter_text


@dataclass
class Run:
    workdir: Path
    kb: object
    extracted: object
    book: dict
    profiles: dict
    states: list
    until: int

    def role(self, tid):
        return timeline_role(self.kb.timelines.get(tid or "main"), self.until)


def main_characters(run, top=20):
    counts = {}
    for f in run.kb.facts:
        counts[f["entity"]] = counts.get(f["entity"], 0) + 1
    people = [n for n, e in run.kb.entities.items() if e["type"] == "character"]
    return sorted(people, key=lambda n: (-counts.get(n, 0), n))[:top]


def visible(observations, run):
    return [o for o in observations if o["chapter"] <= run.until and o.get("quote_ok")]


def empty_fields(run):
    spoken = spoken_appearances(run.kb.facts + run.kb.relations, lambda name, _: run.kb.resolve(name))
    appeared = kb_appearances(run.kb)
    out = []
    for name in main_characters(run):
        profile = run.profiles.get(name)
        if not profile:
            out.append({"character": name, "missing": ["profile"], "text": f"**{name}** has no profile"})
            continue
        missing = []
        if not current_status(profile["fields"].get("status", []), spoken.get(name, []), run.kb.timelines, run.until, appeared.get(name, [])):
            missing.append("status")
        missing += [k for k in run.book["extra_fields"] if not visible(profile["extra"].get(k, []), run)]
        if missing:
            out.append({"character": name, "missing": missing, "text": f"**{name}** has no {', '.join(missing)}"})
    return out


def death_explanation(run, death, later):
    t = run.kb.timelines.get(death.get("timeline") or "main")
    if t and t["kind"] == "run" and run.role(t["id"]) == "erased":
        return f"the death is in run {t['id']}, erased in ch {t['erased']}"
    if t and run.role(t["id"]) == "aside":
        return f"the death is in {t['kind']} {t['id']}"
    if later.get("value") == "revived":
        return f"a revival is recorded in ch {later['chapter']}"
    return ""


def dead_then_alive(run):
    spoken = spoken_appearances(run.kb.facts + run.kb.relations, lambda name, _: run.kb.resolve(name))
    out = []
    for name, profile in run.profiles.items():
        status = visible(profile["fields"].get("status", []), run)
        for death in [o for o in status if o["value"] == "dead"]:
            later = next((o for o in status if o["chapter"] > death["chapter"] and o["value"] in ("alive", "revived")), None)
            if later is None:
                spoke = [c for c, tid in spoken.get(name, []) if c > death["chapter"] and run.role(tid) == "current"]
                later = {"value": "speaks", "chapter": spoke[0]} if spoke else None
            if later is None:
                continue
            why = death_explanation(run, death, later)
            out.append({"character": name, "died": death["chapter"], "death_timeline": death.get("timeline", "main"),
                        "later": later["value"], "later_chapter": later["chapter"], "explained_by": why,
                        "text": f"**{name}** dead in ch {death['chapter']} ({death.get('timeline', 'main')}), "
                                f"{later['value']} in ch {later['chapter']}: " + (why or "**not explained by any timeline**")})
    return out


HEDGES = re.compile(r"\b(?:likely|probably|possibly|perhaps|may|might|seems?|appears? to|unclear|could be)\b", re.I)


def merges(run):
    out = []
    for d in read_json(run.workdir / "merges.json", {"pairs": []})["pairs"]:
        if not d.get("same"):
            continue
        types = [run.extracted.entities[n]["type"] for n in (d["a"], d["b"]) if n in run.extracted.entities]
        reasons = []
        if len(set(types)) > 1 and not run.extracted.types.kin(*types):
            reasons.append(f"cross-type ({' / '.join(types)})")
        hedge = HEDGES.search(d.get("reason") or "")
        if hedge:
            reasons.append(f"hedged reason (\"{hedge.group(0)}\")")
        if reasons:
            out.append({"a": d["a"], "b": d["b"], "canonical": d.get("canonical"), "reasons": reasons, "reason": d.get("reason", ""),
                        "text": f"{d['a']} + {d['b']} -> {d.get('canonical')}: {'; '.join(reasons)}. {d.get('reason', '')}"})
    return out


def chapter_timelines(run):
    by_chapter = {}
    for row in run.kb.facts + run.kb.relations:
        by_chapter.setdefault(row["chapter"], []).append(row.get("timeline", "main"))
    return by_chapter


def erased_resolutions(run):
    by_chapter = chapter_timelines(run)
    out = []
    for q in run.kb.questions.values():
        if q["status"] != "resolved":
            continue
        tids = by_chapter.get(q["resolved_chapter"], [])
        erased = sorted({t for t in tids if run.role(t) == "erased"})
        count = sum(run.role(t) == "erased" for t in tids)
        if tids and 2 * count > len(tids):
            out.append({"id": q["id"], "question": q["question"], "resolved_chapter": q["resolved_chapter"], "timelines": erased,
                        "text": f"**{q['id']}** {q['question']} (resolved ch {q['resolved_chapter']}, where {count} of {len(tids)} "
                                f"items are in erased timelines {', '.join(erased)})"})
    return out


def quote_gaps(run):
    out = []
    keyed = ("full_name", "affiliation")
    for name, profile in run.profiles.items():
        rows = [(k, o) for k in keyed for o in profile["fields"].get(k, [])]
        rows += [(k, o) for k, obs in profile["extra"].items() for o in obs]
        for key, o in rows:
            if not o.get("quote_ok"):
                continue
            quotes = " ".join(o["quotes"])
            classes = [c for c in run.book["field_values"].get(key, ()) if class_pattern(c).search(o["value"])]
            missing = [c for c in classes if not class_pattern(c).search(quotes)]
            words = stems(o["value"])
            if not missing and (not words or words & stems(quotes)):
                continue
            gap = f"class {', '.join(missing)} not in the quote" if missing else "none of the value's words are in the quote"
            out.append({"character": name, "field": key, "chapter": o["chapter"], "value": o["value"], "quotes": o["quotes"],
                        "gap": gap, "text": f"**{name}** {key} ch {o['chapter']} \"{o['value']}\": {gap}"})
    return out


def power_type_people(run):
    spoke = speakers(run.kb)
    out = []
    for power_type in run.book["power_types"]:
        members, people = people_in_type(run.kb, power_type, spoke)
        if people:
            out.append({"type": power_type, "members": len(members), "people": people,
                        "text": f"**{power_type}**: {len(people)} of {len(members)} entries speak ({', '.join(people[:8])})"})
    return out


def category_clashes(run):
    types = {**run.book["power_types"], **added_types(run.workdir)}
    names = {n: e["type"] for e in run.kb.entities.values() for n in names_of(e)}
    return [{"text": p} for p in category_problems(types, names)]


def relation_rejections(run, floor=0.3, least=4):
    out, totals = [], [0, 0]
    for state in run.states:
        verdicts = [v.get("verdict") for k, v in (state.get("support") or {}).items() if k.startswith("R") and isinstance(v, dict)]
        rejected = verdicts.count("unsupported")
        totals[0] += rejected
        totals[1] += len(verdicts)
        if len(verdicts) >= least and rejected / len(verdicts) >= floor:
            out.append({"chapter": state["chapter"], "rejected": rejected, "audited": len(verdicts),
                        "text": f"ch {state['chapter']}: {rejected} of {len(verdicts)} relations rejected"})
    if totals[1] and totals[0] / totals[1] >= floor:
        out.insert(0, {"chapter": None, "rejected": totals[0], "audited": totals[1],
                       "text": f"whole run: {totals[0]} of {totals[1]} relations rejected"})
    return out


FRONT_MATTER = re.compile(r"project gutenberg|\blicen[cs]e\b|\bcopyright\b|all rights reserved|\bisbn\b|\be-?book\b|"
                          r"translator'?s note|table of contents|^\s*contents\s*$", re.I | re.M)


def front_matter(run, edge=2000):
    out = []
    for n in sorted(run.kb.synopses):
        text = chapter_text(str(run.workdir), n)
        hits = sorted({m.group(0).strip().lower() for part in (text[:edge], text[-edge:]) for m in FRONT_MATTER.finditer(part)})
        if hits:
            out.append({"chapter": n, "hits": hits, "text": f"ch {n}: {', '.join(hits)}"})
    return out


def minor_mentions(run):
    entries = [run.kb.entities[name] for name in run.kb.bare_entities()]
    return [{"name": e["name"], "type": e["type"], "chapter": e["first_chapter"],
             "text": f"**{e['name']}** ({e['type']}, ch {e['first_chapter']})"} for e in entries]


def uncategorized(run):
    return [{"name": e["name"], "chapter": e["first_chapter"], "text": f"**{e['name']}** (ch {e['first_chapter']})"}
            for e in run.kb.entities.values() if e["type"] == UNCATEGORIZED]


HOLDERS = INDIVIDUALS + ("organization",)


def ranks_off_ladder(run):
    word = run.book["rank_word"]
    if not word:
        return []
    placed = set()
    for ladder in read_json(run.workdir / "ladders.json", []):
        for s in ladder["steps"]:
            key = run.kb.resolve(s["entry"], (run.book.get("ladder") or {}).get("step_type") or "")
            placed |= {name_key(n) for n in [s["entry"]] + (names_of(run.kb.entities[key]) if key else [])}
    out, seen = [], set()
    for m in rank_mentions(run.workdir, sorted(run.kb.synopses), word):
        key = run.kb.resolve(m["name"])
        if name_key(m["name"]) in placed | seen | set(run.book["power_types"]) or (key and run.kb.types.kind(run.kb.entities[key]["type"]) in HOLDERS):
            continue
        seen.add(name_key(m["name"]))
        status = f"filed as {run.kb.entities[key]['type']}" if key else "no entry"
        out.append({"name": m["name"], "chapter": m["chapter"], "form": m["form"], "entry": key,
                    "text": f"**{m['name']}** ({m['form']}, ch {m['chapter']}): {status}"})
    return out


@dataclass(frozen=True)
class Check:
    key: str
    title: str
    find: object


CHECKS = (
    Check("empty_fields", "Main characters with an empty status or power field", empty_fields),
    Check("dead_then_alive", "Dead, then alive again", dead_then_alive),
    Check("merges", "Cross-type or low-confidence merges", merges),
    Check("erased_resolutions", "Questions resolved in erased timelines", erased_resolutions),
    Check("quote_gaps", "Profile values whose quote lacks the value's key words", quote_gaps),
    Check("power_type_people", "Power types that contain people", power_type_people),
    Check("category_clashes", "Categories that overlap or are named like an entry", category_clashes),
    Check("relation_rejections", "High relation audit rejection rates", relation_rejections),
    Check("front_matter", "Front matter or license text in chapters", front_matter),
    Check("minor_mentions", "Entries shown only as minor mentions", minor_mentions),
    Check("uncategorized", "Entries left without a type", uncategorized),
    Check("ranks_off_ladder", "Ranks the text names that are not on a ladder", ranks_off_ladder),
)


def load_run(workdir):
    kb = load_states(workdir)
    states = [read_json(p, {}) for p in state_paths(workdir)]
    return Run(workdir, kb, load_states(workdir, merges=False, retypes=False), load_book(workdir),
               read_json(workdir / "profiles.json", {"characters": {}})["characters"], states, max(kb.synopses, default=0))


def review(workdir):
    run = load_run(Path(workdir))
    return {"workdir": str(run.workdir), "until": run.until,
            "checks": [{"key": c.key, "title": c.title, "findings": c.find(run)} for c in CHECKS]}


def review_markdown(report):
    lines = [f"# Review of {Path(report['workdir']).name}", "", f"Chapters 1 to {report['until']}.", ""]
    lines += [f"- {c['title']}: {len(c['findings'])}" for c in report["checks"]] + [""]
    for c in report["checks"]:
        lines += [f"## {c['title']} ({len(c['findings'])})", ""]
        lines += [f"- {f['text']}" for f in c["findings"]] or ["None."]
        lines.append("")
    return "\n".join(lines)


def cmd_review(args):
    workdir = Path(args.workdir).resolve()
    report = review(workdir)
    write_json(workdir / "review.json", report)
    write_atomic(workdir / "review.md", review_markdown(report))
    for c in report["checks"]:
        print(f"{len(c['findings']):>5}  {c['title']}")
    print(f"wrote {workdir / 'review.md'} and {workdir / 'review.json'}")
