import hashlib
import re

from .files import read_json

MANY_NAMES = 6
NAMELESS_FACTS = 5


def plain_reason(reason):
    hedged = re.fullmatch(r'hedged reason \("(.*)"\)', reason)
    if hedged:
        return f"the judge only said \u201c{hedged.group(1)}\u201d"
    kinds = re.fullmatch(r"cross-type \((.*) / (.*)\)", reason)
    if kinds:
        return f"one was filed as {kinds.group(1)}, the other as {kinds.group(2)}"
    return reason


def check_id(*parts):
    return hashlib.sha1("\x1f".join(map(str, parts)).encode()).hexdigest()[:10]


def site_checks(workdir, entities, facts):
    """Pages a reader should look at first, each with a reason and the chapter from which it shows: names two
    character pages share, merges review.json found cross-type or hedged, deaths followed by an unexplained return,
    pages holding many names, and pages with many facts still titled by a description."""
    into = {e["id"]: e["merged"]["into"] for e in entities if e.get("merged")}
    by_name = {}
    for e in sorted(entities, key=lambda e: bool(e.get("merged"))):
        for name in [e["name"], *(a["name"] for a in e.get("aliases", []))]:
            by_name.setdefault(name.casefold(), []).append(e)
    page = lambda name: (by_name.get((name or "").casefold()) or [None])[0]
    counts = {}
    for f in facts:
        counts[f["entity"]] = counts.get(f["entity"], 0) + 1
    out = []

    def add(kind, e, chapter, reason):
        out.append({"id": check_id(kind, e["id"], reason), "kind": kind, "entity": e["id"], "chapter": chapter, "reason": reason})

    for e in (e for e in entities if e["type"] == "character"):
        shared = {}
        for a in e.get("aliases", []):
            for o in by_name.get(a["name"].casefold(), []):
                if (o is not e and o["type"] == "character" and into.get(e["id"]) != o["id"] and into.get(o["id"]) != e["id"]
                        and counts.get(e["id"], 0) <= counts.get(o["id"], 0)):
                    shared.setdefault(o["id"], (o, []))[1].append(a)
        for o, names in shared.values():
            listed = ", ".join(f"“{a['name']}”" for a in names)
            add("shared_name", e, min(a["chapter"] for a in names), f"shares {listed} with the page “{o['name']}”")
        if e.get("merged"):
            continue
        if len(e.get("aliases", [])) >= MANY_NAMES:
            add("many_names", e, max(a["chapter"] for a in e["aliases"]),
                f"holds {len(e['aliases'])} names; check they all belong to one person or thing")
        if e.get("nameless") and counts.get(e["id"], 0) >= NAMELESS_FACTS:
            add("description_title", e, e["first"], f"titled “{e['name']}” with {counts[e['id']]} facts; does the book name them?")

    review = {c["key"]: c["findings"] for c in read_json(workdir / "review.json", {"checks": []}).get("checks", [])}
    for m in review.get("merges", []):
        e = page(m["canonical"])
        if e:
            add("merge", e, e["first"], f"\u201c{m['a']}\u201d and \u201c{m['b']}\u201d were joined; {'; '.join(map(plain_reason, m['reasons']))}")
    for d in review.get("dead_then_alive", []):
        e = page(d["character"])
        if e and not d["explained_by"]:
            add("dead_alive", e, d["later_chapter"], f"dead in ch {d['died']}, then {d['later']} in ch {d['later_chapter']} with no revival recorded")
    seen = set()
    return [c for c in out if not (c["id"] in seen or seen.add(c["id"]))]
