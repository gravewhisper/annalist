import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .families import read_families, relation_family, signals, terms, wording_key
from .files import read_json, write_json
from .names import name_key
from .template import type_parents, Types

NEAR = 1

STATUS_RULES = (
    (r"\bpresumed (dead|drowned)\b|\bmissing\b", ("dead", "missing")),
    (r"\b(dead|died|killed|drowned)\b", ("dead",)),
    (r"\b(alive|free|at large|arrested|imprisoned|escaped|fled|rescued)\b", ("alive",)),
)


def fold(text):
    return re.sub(r"\s+", " ", name_key(text).replace(".", "")).strip()


def match_key(name):
    return re.sub(r"^the ", "", fold(re.sub(r"\([^)]*\)", " ", str(name))))


def mentions(text, name):
    key = match_key(name)
    return bool(key) and re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", fold(text)) is not None


def gold_families(rtype, readings, target_types):
    return set(signals(wording_key(rtype))) | {relation_family(rtype, readings, t) for t in target_types or [None]}


def shown_family(row, readings):
    return row.get("family") or relation_family(row["type"], readings)


STANDING_TIES = ("kin", "romance", "teaching")


STAGES = ({"marr", "husb", "wife", "spou", "wido"}, {"enga", "betr", "fian"})


def states_the_tie(gold_type, row, readings):
    gold_terms, row_terms = terms(wording_key(gold_type)), terms(wording_key(row["type"]))
    staged = [stage for stage in STAGES if gold_terms & stage]
    if staged:
        return any(row_terms & stage for stage in staged)
    return shown_family(row, readings) in STANDING_TIES or bool(gold_terms & row_terms)


def strength(name, aliases, wname, waliases):
    return 4 if name == wname else 3 if name in waliases else 2 if wname in aliases else 1 if aliases & waliases else 0


def accepted_statuses(text):
    return next((values for pattern, values in STATUS_RULES if re.search(pattern, text.lower())), None)


@dataclass
class Item:
    section: str
    id: str
    outcome: str
    detail: str
    evidence: list = field(default_factory=list)


class Wiki:
    def __init__(self, data):
        book = data["book"]
        self.types = Types(book.get("parents") or type_parents(dict.fromkeys(book.get("power_types") or [], "")))
        self.chapters = [c["n"] for c in data["chapters"]]
        self.all = {e["id"]: e for e in data["entities"]}
        self.entities = {k: e for k, e in self.all.items() if not e.get("merged")}
        self.parts = {}
        for k, e in self.all.items():
            if e.get("merged"):
                self.parts.setdefault(e["merged"]["into"], []).append(e)
        self.timelines = {t["id"]: t for t in data["timelines"]}
        self.facts, self.relations = {}, data["relations"]
        for f in data["facts"]:
            self.facts.setdefault(f["entity"], []).append(f)

    def page_id(self, eid, n):
        merged = self.all[eid].get("merged")
        return merged["into"] if merged and n >= merged["chapter"] else eid

    def root(self, eid):
        merged = self.all[eid].get("merged")
        return merged["into"] if merged else eid

    def first(self, eid):
        return min([self.all[eid]["first"]] + [p["first"] for p in self.parts.get(eid, [])])

    def own_facts(self, eid, n):
        ids = [eid] + [p["id"] for p in self.parts.get(eid, []) if n >= p["merged"]["chapter"]]
        return sorted((f for i in ids for f in self.facts.get(i, []) if f["chapter"] <= n), key=lambda f: f["chapter"])

    def role(self, tid, n):
        t = self.timelines.get(tid)
        if not t or t["kind"] == "main":
            return "current"
        if t.get("erased") is not None and t["erased"] <= n:
            return "erased"
        return "current" if t["kind"] == "run" else "aside"

    def visible(self, eid, n):
        return eid in self.all and self.all[eid]["first"] <= n and self.page_id(eid, n) == eid

    def present(self, eid, n):
        return self.visible(eid, n) or any(self.visible(p["id"], n) for p in self.parts.get(eid, []))

    def names(self, eid, n=None):
        e = self.all[eid]
        shown = [a["name"] for a in e["aliases"] if n is None or a["chapter"] <= n]
        return ([e["name"]] if n is None or e["name_chapter"] <= n else []) + shown

    def display(self, eid, n):
        eid = self.page_id(eid, n)
        return (self.names(eid, n) or [self.all[eid]["name"]])[0]

    def label(self, eid):
        e = self.all[eid]
        aka = "; aliases " + ", ".join(f"{a['name']} (ch{a['chapter']})" for a in e["aliases"]) if e["aliases"] else ""
        parts = "".join(f"; a separate page \"{p['name']}\" ch{p['first']}-{p['merged']['chapter'] - 1}" for p in self.parts.get(eid, []))
        return f"\"{e['name']}\" [{e['type']}] first ch{e['first']}{aka}{parts}"

    def rows(self, a, b):
        return [r for r in self.relations if {self.root(r["source"]), self.root(r["target"])} == {a, b} and a != b]

    def page(self, eid, n):
        e = self.all[eid]
        out = [("name", x) for x in self.names(eid, n)]
        blurbs = [b for b in e.get("blurbs", []) if b[0] <= n and self.role(b[2] if len(b) > 2 else "main", n) != "erased"]
        if e.get("summary") and e["summary"]["chapter"] <= n:
            out.append(("summary", e["summary"]["text"]))
        elif blurbs:
            out.append(("summary", blurbs[-1][1]))
        out += [(f"fact ch{f['chapter']}", f["claim"]) for f in self.own_facts(eid, n)]
        for r in self.relations:
            ends = (self.page_id(r["source"], n), self.page_id(r["target"], n))
            if eid in ends and r["chapter"] <= n and all(self.visible(x, n) for x in ends):
                out.append((f"relation ch{r['chapter']}",
                            f"{self.display(r['source'], n)} {r['type']} {self.display(r['target'], n)}"))
        profile = e.get("profile") or {}
        for group in ("fields", "lists"):
            for key, obs in (profile.get(group) or {}).items():
                out += [(f"infobox {key} ch{o['chapter']}", o["value"]) for o in obs if o.get("shown", o["chapter"]) <= n]
        out += [(f"personality ch{p['chapter']}", p["text"]) for p in profile.get("personality", []) if p["chapter"] <= n]
        return out

    def status(self, eid, n):
        profile = self.all[eid].get("profile")
        if profile is None:
            return None
        visible = [o for o in profile["fields"].get("status", []) if o.get("shown", o["chapter"]) <= n]
        shown = [o for o in visible if self.role(o.get("timeline", "main"), n) == "current"]
        spoke = [c for c, tid in profile.get("spoke", []) if c <= n and self.role(tid, n) == "current"]
        if shown and not (shown[-1]["value"] == "missing" and max(spoke, default=0) > shown[-1]["chapter"]):
            return {"value": shown[-1]["value"], "chapter": shown[-1]["chapter"], "basis": "observed"}
        past = next((o for o in reversed(visible) if o["value"] == "dead"
                     and self.timelines.get(o.get("timeline"), {}).get("kind") == "flashback"), None)
        if past and past["chapter"] >= max(spoke, default=0):
            return {"value": "dead", "chapter": past["chapter"], "basis": "past"}
        if spoke:
            return {"value": "alive", "chapter": max(spoke), "basis": "spoke"}
        appeared = [c for c, tid in profile.get("appeared", []) if c <= n and self.role(tid, n) == "current"]
        if appeared:
            return {"value": "alive", "chapter": max(appeared), "basis": "appeared"}
        if any(o["value"] == "dead" and self.timelines.get(o.get("timeline"), {}).get("kind") == "run" for o in visible):
            return {"value": "alive", "chapter": n, "basis": "erased_death"}
        return None

    def aside_statuses(self, eid, n):
        profile = self.all[eid].get("profile") or {"fields": {}}
        return [o for o in profile["fields"].get("status", []) if o.get("shown", o["chapter"]) <= n and self.role(o.get("timeline", "main"), n) == "aside"]


class Gold:
    def __init__(self, data):
        self.data = data
        self.entities = {e["id"]: e for e in data["entities"]}
        self.last = max(c["index"] for c in data["chapters"])
        self.reveal_aliases = {}
        for r in data.get("identity_reveals", []):
            self.reveal_aliases.setdefault(r["entity"], set()).add(match_key(r["alias"]))
        self.forbidden = {match_key(m["alias"]) for m in data.get("must_not_merge", [])}

    def names(self, gid):
        e = self.entities[gid]
        return [e["name"]] + e.get("aliases", [])

    def keys(self, gid):
        e = self.entities[gid]
        excluded = self.reveal_aliases.get(gid, set()) | self.forbidden
        return match_key(e["name"]), {match_key(a) for a in e.get("aliases", [])} - excluded - {""}

    def types(self, gid):
        e = self.entities[gid]
        return set(e.get("accepted_types") or [e["type"]])


class Match:
    def __init__(self, gold, wiki):
        self.candidates = {}
        for gid in gold.entities:
            name, aliases = gold.keys(gid)
            found = []
            for eid, e in wiki.entities.items():
                rank = strength(name, aliases, match_key(e["name"]), {match_key(a["name"]) for a in e["aliases"]})
                if rank:
                    found.append((rank, -len(wiki.facts.get(eid, [])), e["first"], eid))
            self.candidates[gid] = sorted(found, key=lambda c: (-c[0], c[1], c[2]))
        self.home = {gid: c[0][3] for gid, c in self.candidates.items() if c}
        self.strength = {gid: c[0][0] for gid, c in self.candidates.items() if c}
        self.owner = {}
        for gid in sorted(self.home, key=lambda g: -self.strength[g]):
            self.owner.setdefault(self.home[gid], gid)


def chapter_items(gold, workdir, wiki):
    stored = {c["index"]: c for c in read_json(workdir / "chapters.json", [])}
    items = []
    for c in gold.data["chapters"]:
        mine = stored.get(c["index"])
        evidence = [f"gold ch{c['index']} {c['href']} \"{c['title']}\""]
        if mine is None or c["index"] not in wiki.chapters:
            items.append(Item("chapters", f"chapter:{c['index']}", "fail", "chapter missing from the run", evidence))
            continue
        evidence.append(f"run ch{c['index']} {mine.get('href', '?')} \"{mine.get('title', '')}\"")
        ok = mine.get("href") is None or mine["href"] == c["href"]
        items.append(Item("chapters", f"chapter:{c['index']}", "pass" if ok else "fail",
                          "same spine document" if ok else "a different spine document has this number", evidence))
    extra = sorted(n for n in set(stored) - {c["index"] for c in gold.data["chapters"]} if not gold.data.get("partial") or n < gold.last)
    if extra:
        items.append(Item("chapters", "chapter:extra", "fail", f"run has chapters the gold lacks: {extra}", []))
    return items


def entity_items(gold, wiki, match):
    items = []
    for gid, g in gold.entities.items():
        eid = match.home.get(gid)
        iid = f"entity:{gid}"
        if eid is None:
            items.append(Item("entities", iid, "fail", "no wiki entity carries the name or an alias", [f"gold names: {', '.join(gold.names(gid))}"]))
            continue
        e = wiki.entities[eid]
        evidence = [f"gold \"{g['name']}\" [{'/'.join(sorted(gold.types(gid)))}] first ch{g['first_chapter']}",
                    f"wiki {wiki.label(eid)}"]
        owner = match.owner[eid]
        if owner != gid:
            items.append(Item("entities", iid, "fail", f"merged into the page for gold {owner}", evidence))
        elif not wiki.types.is_a(e["type"], gold.types(gid)):
            items.append(Item("entities", iid, "fail", f"type {e['type']} is not accepted", evidence))
        elif wiki.first(eid) > g["first_chapter"] + NEAR:
            items.append(Item("entities", iid, "fail", f"first appears in ch{wiki.first(eid)}, gold ch{g['first_chapter']}", evidence))
        else:
            items.append(Item("entities", iid, "pass", "found", evidence))
    return items


def precision_items(gold, wiki, match):
    items = []
    optional = {match_key(n) for o in gold.data.get("optional_entities", []) for n in [o["name"]] + o.get("aliases", [])}
    candidates = {}
    for gid, found in match.candidates.items():
        for c in found:
            candidates.setdefault(c[3], []).append(gid)
    for gid, keys in gold.reveal_aliases.items():
        for eid in wiki.entities:
            if gid in match.home and keys & {match_key(n) for n in wiki.names(eid)}:
                candidates.setdefault(eid, []).append(gid)
    for eid in sorted(candidates, key=lambda x: wiki.entities[x]["name"]):
        homes = [gid for gid, h in match.home.items() if h == eid]
        if homes:
            items.append(Item("precision", f"wiki:{wiki.entities[eid]['name']}", "pass", f"the page for gold {', '.join(homes)}",
                              [f"wiki {wiki.label(eid)}"]))
        else:
            others = [f"{gid} lives on \"{wiki.entities[match.home[gid]]['name']}\"" for gid in candidates[eid]]
            items.append(Item("precision", f"wiki:{wiki.entities[eid]['name']}", "fail",
                              "a second page for a gold entity", [f"wiki {wiki.label(eid)}"] + others))
    outside = [e["name"] for eid, e in wiki.entities.items() if eid not in candidates]
    unscored = [n for n in outside if match_key(n) not in optional]
    if outside:
        items.append(Item("precision", "wiki:outside-gold", "not_scored",
                          f"{len(unscored)} wiki entities are not in the gold, which is not exhaustive",
                          sorted(unscored) + [f"optional in gold: {n}" for n in sorted(set(outside) - set(unscored))]))
    return items


def merge_items(gold, wiki, match):
    items = []
    for m in gold.data.get("must_not_merge", []):
        iid = f"merge:{m['alias']}"
        homes = {gid: match.home.get(gid) for gid in m["entities"]}
        evidence = [f"{gid}: " + (wiki.label(eid) if eid else "not in the wiki") for gid, eid in homes.items()]
        found = [eid for eid in homes.values() if eid]
        if len(set(found)) < len(found):
            items.append(Item("forbidden_merges", iid, "fail", f"{' and '.join(m['entities'])} share one wiki page", evidence))
            continue
        alias = match_key(m["alias"])
        holders = [gid for gid, eid in homes.items() if eid and alias not in {match_key(n) for n in gold.names(gid)}
                   and alias in {match_key(n) for n in wiki.names(eid)}]
        if holders:
            items.append(Item("forbidden_merges", iid, "fail", f"\"{alias}\" is an alias of the page for {', '.join(holders)}", evidence))
        else:
            items.append(Item("forbidden_merges", iid, "pass", "kept apart", evidence))
    return items


def leak(wiki, eid, n, names):
    for channel, text in wiki.page(eid, n):
        hit = next((x for x in names if mentions(text, x)), None)
        if hit:
            return f"ch{n} {channel} on \"{wiki.display(eid, n)}\": {text}"
    return None


def reveal_items(gold, wiki, match):
    items = []
    for r in gold.data.get("identity_reveals", []):
        gid, alias = r["entity"], r["alias"]
        iid = f"reveal:{gid}:{alias}"
        allowed = min(r["reveal_chapter"], r.get("lenient_reveal_chapter", r["reveal_chapter"]))
        home = match.home.get(gid)
        own = [n for n in gold.names(gid) if match_key(n) not in gold.reveal_aliases.get(gid, set()) | gold.forbidden
               and not mentions(alias, n)]
        others = [eid for eid in wiki.all if eid != home and match_key(alias) in {match_key(n) for n in wiki.names(eid)}]
        found = None
        for n in range(1, allowed):
            if home and wiki.visible(home, n):
                found = leak(wiki, home, n, [alias])
            for eid in others:
                if not found and wiki.visible(eid, n):
                    found = leak(wiki, eid, n, own)
            if found:
                break
        evidence = [f"allowed from ch{allowed}", f"gold page: {wiki.label(home) if home else 'not in the wiki'}"]
        evidence += [f"alias page: {wiki.label(eid)}" for eid in others]
        if found:
            items.append(Item("reveals", iid, "fail", "linked before the reveal", evidence + [found]))
        else:
            linked = next((n for n in range(allowed, wiki.chapters[-1] + 1) if home and leak(wiki, home, n, [alias])), None)
            after = f"linked from ch{linked}" if linked else "never linked"
            items.append(Item("reveals", iid, "pass", f"not linked before ch{allowed}; {after}", evidence))
    return items


def reader_page(gold, wiki, home, gid, n):
    name, aliases = gold.keys(gid)
    pages = [p for p in [home] + [x["id"] for x in wiki.parts.get(home, [])] if wiki.visible(p, n)]

    def rank(pid):
        e = wiki.all[pid]
        wname = match_key(e["name"]) if e["name_chapter"] <= n else ""
        return strength(name, aliases, wname, {match_key(a["name"]) for a in e["aliases"] if a["chapter"] <= n}), pid == home

    return max(pages, key=rank, default=home)


def status_items(gold, wiki, match):
    items = []
    timelines = {t["id"]: t for t in gold.data.get("timelines", [])}
    for s in gold.data.get("statuses", []):
        gid = s["entity"]
        eid = match.home.get(gid)
        for point in s["timeline"]:
            n, want = point["chapter"], point["status"]
            iid = f"status:{gid}@{n}"
            evidence = [f"gold ch{n}: {want}" + (f" [{point['timeline_id']}]" if point.get("timeline_id") else "")]
            accepted = accepted_statuses(want)
            if eid is None:
                items.append(Item("statuses", iid, "fail", "entity not in the wiki", evidence))
                continue
            evidence.append(f"wiki {wiki.label(eid)}")
            if accepted is None:
                items.append(Item("statuses", iid, "not_scored", "status has no counterpart in the wiki's status values", evidence))
                continue
            page = reader_page(gold, wiki, eid, gid, n)
            e = wiki.all[page]
            if e.get("profile") is None:
                reason = f"the wiki has no status field for type {e['type']}" if e["type"] != "character" else "the character has no profile"
                outcome = "not_scored" if e["type"] != "character" else "fail"
                items.append(Item("statuses", iid, outcome, reason, evidence))
                continue
            shown = wiki.status(page, n)
            values = [shown["value"]] if shown else []
            evidence.append(f"infobox on \"{e['name']}\" at ch{n}: " + (f"{shown['value']} (ch{shown['chapter']}, {shown['basis']})" if shown else "no status"))
            kind = timelines.get(point.get("timeline_id"), {}).get("kind")
            if kind:
                aside = wiki.aside_statuses(page, n)
                values += [o["value"] for o in aside]
                evidence += [f"{o['value']} (ch{o['chapter']}, timeline {o.get('timeline')})" for o in aside]
            ok = any(v in accepted for v in values)
            items.append(Item("statuses", iid, "pass" if ok else "fail",
                              f"accepts {' or '.join(accepted)}", evidence))
    return items


def relation_items(gold, wiki, match, readings):
    recall, early = [], []
    for r in gold.data.get("relations", []):
        iid = f"relation:{r['source']}-{r['type']}-{r['target']}"
        a, b = match.home.get(r["source"]), match.home.get(r["target"])
        lenient = r.get("lenient", False)
        latest = gold.last if lenient else r["first_chapter"] + NEAR
        want = gold_families(r["type"], readings, {wiki.types.kind(t) for t in gold.types(r["target"])} if r["target"] in gold.entities else ())
        evidence = [f"gold ch{r['first_chapter']}: {r['source']} {r['type']} {r['target']} (families {', '.join(sorted(want))})"
                    + (", lenient" if lenient else "")]
        if not a or not b or a == b:
            reason = "both ends map to one wiki page" if a and a == b else "an end is not in the wiki"
            recall.append(Item("relations", iid, "fail", reason, evidence))
            continue
        rows = [x for x in wiki.rows(a, b) if lenient or shown_family(x, readings) in want]
        evidence += [f"ch{x['chapter']}: {wiki.all[x['source']]['name']} {x['type']} {wiki.all[x['target']]['name']}"
                     for x in rows] or ["wiki rows between the pair: "
                                        + ("; ".join(f"{x['type']}, coloured {shown_family(x, readings)}" for x in wiki.rows(a, b)) or "none")]
        first = min((x["chapter"] for x in rows if wiki.present(a, x["chapter"]) and wiki.present(b, x["chapter"])), default=None)
        if first is None:
            recall.append(Item("relations", iid, "fail", "no wiki relation of the same family", evidence))
        elif first > latest:
            recall.append(Item("relations", iid, "fail", f"first shown in ch{first}, accepted up to ch{latest}", evidence))
        else:
            recall.append(Item("relations", iid, "pass", f"first shown in ch{first}", evidence))
        if not lenient:
            shown = min((x["chapter"] for x in rows if states_the_tie(r["type"], x, readings)), default=None)
            earliest = r["first_chapter"] - NEAR
            if shown is not None and shown < earliest:
                early.append(Item("early_relations", f"early:{iid}", "fail", f"shown in ch{shown}, before the text reveals it in ch{r['first_chapter']}", evidence))
            else:
                early.append(Item("early_relations", f"early:{iid}", "pass", f"not shown before ch{earliest}", evidence))
    return recall + early


SECTIONS = ("chapters", "entities", "precision", "forbidden_merges", "reveals", "early_relations", "statuses", "relations")


def score(workdir, gold_data, wiki_data):
    gold, wiki = Gold(gold_data), Wiki(wiki_data)
    items = chapter_items(gold, Path(workdir), wiki)
    if all(i.outcome == "pass" for i in items):
        match = Match(gold, wiki)
        items += entity_items(gold, wiki, match) + precision_items(gold, wiki, match) + merge_items(gold, wiki, match)
        items += reveal_items(gold, wiki, match) + status_items(gold, wiki, match) + relation_items(gold, wiki, match, read_families(workdir))
    return items


def totals(items):
    out = {}
    for section in SECTIONS:
        rows = [i for i in items if i.section == section]
        counts = {k: sum(i.outcome == k for i in rows) for k in ("pass", "fail", "not_scored")}
        scored = counts["pass"] + counts["fail"]
        out[section] = {**counts, "score": round(counts["pass"] / scored, 3) if scored else None}
    quality = [t for section, t in out.items() if section != "chapters"]
    passed, failed = sum(t["pass"] for t in quality), sum(t["fail"] for t in quality)
    out["all"] = {"pass": passed, "fail": failed, "not_scored": sum(t["not_scored"] for t in quality),
                  "score": round(passed / (passed + failed), 3) if passed + failed else None}
    return out


def percent(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def markdown(items, sums, gold_path, workdir):
    lines = [f"# Eval of {workdir}", "", f"Gold: {gold_path}", "",
             "| section | pass | fail | not scored | score |", "|---|---:|---:|---:|---:|"]
    for section in SECTIONS + ("all",):
        t = sums[section]
        lines.append(f"| {section} | {t['pass']} | {t['fail']} | {t['not_scored']} | {percent(t['score'])} |")
    for section in SECTIONS:
        rows = sorted((i for i in items if i.section == section), key=lambda i: ("fail", "not_scored", "pass").index(i.outcome))
        if not rows:
            continue
        lines += ["", f"## {section}", ""]
        for i in rows:
            lines.append(f"- **{i.outcome}** `{i.id}`: {i.detail}")
            lines += [f"  - {e}" for e in i.evidence]
    return "\n".join(lines) + "\n"


def cmd_eval(args):
    if not args.gold and not args.reader_key:
        sys.exit("annalist eval: give a gold file, --reader-key, or both")
    if args.relation_sample is not None and (not args.gold or args.relation_sample < 1):
        sys.exit("annalist eval: --relation-sample needs a gold file and a count of 1 or more")
    workdir = Path(args.workdir).resolve()
    site = workdir / "site" / "data" / "wiki.json"
    if not site.exists():
        sys.exit(f"annalist eval: {site} is missing; run annalist build or export first")
    wiki_data = json.loads(site.read_text(encoding="utf-8"))
    out = Path(args.out).resolve() if args.out else workdir
    sums = None
    if args.gold:
        gold_data = json.loads(Path(args.gold).read_text(encoding="utf-8"))
        items = score(workdir, gold_data, wiki_data)
        sums = totals(items)
        report = {"gold": str(Path(args.gold).resolve()), "workdir": str(workdir), "totals": sums, "items": [asdict(i) for i in items]}
        text = markdown(items, sums, args.gold, workdir)
        if args.relation_sample and not sums["chapters"]["fail"]:
            from . import relation_precision
            report["relation_precision"] = relation_precision.relation_precision(workdir, wiki_data, args.relation_sample, args.judge_model)
            text += relation_precision.markdown(report["relation_precision"])
        write_json(out / "eval.json", report)
        (out / "eval.md").write_text(text, encoding="utf-8")
        for section in SECTIONS + ("all",):
            t = sums[section]
            print(f"  {section:<17} {t['pass']:>4} pass {t['fail']:>4} fail {t['not_scored']:>4} not scored  {percent(t['score']):>6}")
        if "relation_precision" in report:
            t = report["relation_precision"]["totals"]
            print(f"  relation precision {percent(t['precision'])} of {t['sampled']} sampled: {t['correct']} correct, "
                  f"{t['wrong']} wrong, {t['unsupported']} unsupported; judge spend ${report['relation_precision']['judge_spend_usd']:.4f}")
        print(f"wrote {out / 'eval.md'} and {out / 'eval.json'}")
    if args.reader_key:
        from .readerkey import run_reader_eval
        run_reader_eval(workdir, args.reader_key, wiki_data, out, args.judge_model)
    if sums and sums["chapters"]["fail"]:
        sys.exit("annalist eval: the run's chapters do not line up with the gold's; nothing else was scored")
