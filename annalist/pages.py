import json
import re
from collections import Counter
from dataclasses import dataclass, replace

from .files import read_json
from .names import name_key, parse_aliases, written_summary
from .text import chapter_text, verified_quotes
from .titles import common_name, page_title, revealed_name


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


class Absorbed:
    def __init__(self, entities):
        self.entries = {a["name"]: {**a, "into": e["name"]} for e in entities for a in e.get("absorbed", [])}
        self.owner = {(a["into"], name_key(n)): a for a in self.entries.values() for n in a["aliases"]}
        self.owner.update({(a["into"], name_key(a["name"])): a for a in self.entries.values()})

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


@dataclass(frozen=True)
class PageName:
    entry: str
    name: str
    chapter: int
    first: int
    aliases: list

    def known(self, chapter):
        if self.chapter <= chapter:
            return self.name, self.chapter
        # Before any of the page's names is known, prose keeps the pipeline's name and counts it as known from the title's chapter.
        return next(((a["name"], a["chapter"]) for a in self.aliases if a["chapter"] <= chapter), (self.entry, self.chapter))

    def at(self, chapter):
        return self.known(chapter)[0]

    def knows(self, name, chapter):
        named = [(self.name, self.chapter)] + [(a["name"], a["chapter"]) for a in self.aliases]
        return any(name_key(n) == name_key(name) and c <= chapter for n, c in named)

    def titled(self, title):
        old = [] if name_key(self.name) == name_key(title["name"]) else [{"name": self.name, "chapter": self.chapter}]
        aliases = [a for a in self.aliases if name_key(a["name"]) != name_key(title["name"])] + old
        return replace(self, name=title["name"], chapter=title.get("chapter", self.first), aliases=sorted(aliases, key=lambda a: a["chapter"]))


def page_name(e, seen, blurbs, own_facts, texts, words, registry, absorbed, shown_at):
    name_seen = seen.get((e["name"], e["name"]), e["first_chapter"])
    aliases = [{"name": a, "chapter": absorbed.floor(e["name"], a, seen[(e["name"], a)])} for a in e["aliases"]
               if (e["name"], a) in seen and a != e.get("written")]
    if e.get("absorbed"):
        first = min([c for (page, _), c in seen.items() if page == e["name"]] + [b[0] for b in blurbs.get(e["name"], [])] + shown_at,
                    default=e["first_chapter"])
    else:
        first = first_named(texts, e["name"], e["first_chapter"])
        name_seen = min(name_seen, first)
    shown_name = e.get("written", e["name"])
    own_names = [a for a in e["aliases"] if len(set(registry.index[name_key(a)])) == 1]
    if not e.get("absorbed") and "written" not in e:
        own = [b[1] for b in blurbs.get(e["name"], [])] + [x for f in own_facts for x in [f["claim"], *f["quotes"]]]
        shown_name, used = page_title(e["name"], own_names, own, texts)
        first = min([first, *used.values()])
        aliases = [{**a, "chapter": min(a["chapter"], used.get(a["name"], a["chapter"]))} for a in aliases if a["name"] != shown_name]
        if shown_name != e["name"]:
            aliases.append({"name": e["name"], "chapter": name_seen})
            name_seen = max(first, used[shown_name])
    real = None
    if e["type"] == "character" and shown_name == e["name"]:
        real = revealed_name(e["name"], [a for a in aliases if a["name"] in own_names], words)
    if real is None and e["type"] == "character":
        best = common_name(shown_name, [a["name"] for a in aliases if a["name"] in own_names], texts, words, bool(e.get("absorbed")))
        real = next((a for a in aliases if a["name"] == best), None)
    if real:
        aliases = [a for a in aliases if a["name"] != real["name"]] + [{"name": shown_name, "chapter": name_seen}]
        shown_name, name_seen = real["name"], real["chapter"]
    page = PageName(e["name"], shown_name, name_seen, first, sorted(aliases, key=lambda a: (a["chapter"], a["name"] != e["name"])))
    return page.titled(e["title"]) if e.get("title") else page


def part_name(part, seen):
    aliases = [{"name": x, "chapter": seen[(part["name"], x)]} for x in part["aliases"] if (part["name"], x) in seen]
    return PageName(part["name"], part["name"], seen.get((part["name"], part["name"]), part["first_chapter"]), part["first_chapter"],
                    sorted(aliases, key=lambda x: x["chapter"]))


@dataclass
class Pages:
    facts: list
    relations: list
    states: list
    registry: Registry
    absorbed: Absorbed
    blurbs: dict
    texts: dict
    words: Counter
    fact_page: dict
    rel_ends: list
    names: dict


def read_pages(workdir, kb):
    entities = list(kb.entities.values())
    facts = [{**f, **verified_quotes(workdir, f["chapter"], f["quotes"])} for f in kb.facts]
    relations = [{**r, **verified_quotes(workdir, r["chapter"], r["quotes"])} for r in kb.relations]
    states = list(read_states(workdir))
    registry = Registry(entities)
    absorbed = Absorbed(entities)
    seen, blurbs = first_seen(registry, facts, relations, states, kb.timelines, absorbed)
    for d in read_json(workdir / "discover.json", {"entities": []})["entities"]:
        canonical = registry.resolve(d["name"], d["type"])
        if canonical:
            page = absorbed.page_for_name(canonical, d["name"], d["chapter"])
            seen[(page, d["name"])] = min(seen.get((page, d["name"]), d["chapter"]), d["chapter"])
        if canonical and d["summary"]:
            blurbs[page] = sorted(blurbs.get(page, []) + [[d["chapter"], d["summary"]]], key=lambda b: b[0])
    texts = {s["chapter"]: chapter_text(workdir, s["chapter"]) for s in states}
    words = Counter(w for text in texts.values() for w in re.findall(r"\w+", text))
    fact_page = {f["id"]: absorbed.page(f["entity"], f.get("filed"), f["chapter"]) for f in facts}
    rel_ends = [{end: absorbed.page(r[end], (r.get("filed") or {}).get(end), r["chapter"]) for end in ("source", "target")}
                for r in relations]
    shown_at, own_facts = {}, {}
    for f in facts:
        shown_at.setdefault(fact_page[f["id"]], []).append(f["chapter"])
        own_facts.setdefault(f["entity"], []).append(f)
    for r, ends in zip(relations, rel_ends):
        for page in set(ends.values()):
            shown_at.setdefault(page, []).append(r["chapter"])
    names = {}
    for e in entities:
        names[e["name"]] = page_name(e, seen, blurbs, own_facts.get(e["name"], []), texts, words, registry, absorbed, shown_at.get(e["name"], []))
        names.update((a["name"], part_name(a, seen)) for a in e.get("absorbed", []))
    return Pages(facts, relations, states, registry, absorbed, blurbs, texts, words, fact_page, rel_ends, names)
