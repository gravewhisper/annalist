import copy
import sys
from pathlib import Path

from .files import read_json
from .names import name_key
from .text import check_quote


def load_corrections(workdir):
    entries = read_json(Path(workdir) / "corrections.json", {"entries": []})["entries"]
    if not all(isinstance(e, dict) and e.get("name") for e in entries):
        sys.exit("corrections.json: every entry needs a name")
    return [checked_entry(workdir, e) for e in entries]


def checked_entry(workdir, entry):
    entry = dict(entry)
    if "fields" in entry:
        entry["fields"] = {key: [r for r in rows if quoted(workdir, entry["name"], key, r)] for key, rows in entry["fields"].items()}
    if "known_from" in entry and not quoted(workdir, entry["name"], "known_from", entry["known_from"]):
        del entry["known_from"]
    return entry


def load_relations(workdir):
    rows = read_json(Path(workdir) / "corrections.json", {}).get("relations", [])
    if not all(isinstance(r, dict) and r.get("source") and r.get("target") and r.get("type") and r.get("chapter") for r in rows):
        sys.exit("corrections.json: every relation needs a source, target, type and chapter")
    return [r for r in rows if quoted(workdir, f"{r['source']} -> {r['target']}", r["type"], r)]


def quoted(workdir, name, key, row):
    if any(check_quote(str(workdir), row["chapter"], q)["ok"] for q in row.get("quotes", [])):
        return True
    print(f"warning: correction {name}.{key} ch{row['chapter']} has no quote found in that chapter, skipped")
    return False


def names_of(entity):
    return {name_key(entity["name"]), *(name_key(a["name"]) for a in entity["aliases"])}


def merged_rows(existing, rows):
    chapters = {r["chapter"] for r in rows}
    return sorted([o for o in existing if o["chapter"] not in chapters] + rows, key=lambda o: o["chapter"])


def correct_page(page, correction):
    if "type" in correction:
        page["type"] = correction["type"]
    if "title" in correction:
        page["aliases"] = [a for a in page["aliases"] if name_key(a["name"]) != name_key(correction["title"])] + [{"name": page["name"], "chapter": page["first"]}]
        page["name"], page["name_chapter"] = correction["title"], correction.get("title_chapter", page["first"])
    if correction.get("fields"):
        profile = page.setdefault("profile", {"fields": {}, "lists": {}, "spoke": [], "personality": []})
        for key, rows in correction["fields"].items():
            profile["fields"][key] = merged_rows(profile["fields"].get(key, []), rows)


def known_from(part, parent, chapter):
    old = part["merged"]["chapter"]
    part["merged"]["chapter"] = chapter
    own = {name_key(part["name"]), *(name_key(a["name"]) for a in part["aliases"])}
    for alias in parent["aliases"]:
        if name_key(alias["name"]) in own:
            alias["chapter"] = min(alias["chapter"], chapter)
    profile = parent.get("profile") or {}
    for rows in [*profile.get("fields", {}).values(), *profile.get("lists", {}).values()]:
        for row in rows:
            if row.get("shown") == old:
                row["shown"] = max(row["chapter"], chapter)


def find_page(entities, name):
    key = name_key(name)
    return next((e for e in entities if name_key(e["name"]) == key), None) or next((e for e in entities if key in names_of(e)), None)


def added_relation(row, source, target):
    return {"chapter": row["chapter"], "source": source["id"], "target": target["id"], "type": row["type"], "family": row.get("family", "other"),
            "status": row.get("status", "stated"), "by": row.get("by", "narrator"), "quotes": row["quotes"], **({"detail": row["detail"]} if "detail" in row else {})}


def load_dropped_relations(workdir):
    rows = read_json(Path(workdir) / "corrections.json", {}).get("drop_relations", [])
    if not all(isinstance(r, dict) and r.get("source") and r.get("target") and r.get("type") and r.get("chapter") for r in rows):
        sys.exit("corrections.json: every dropped relation needs a source, target, type and chapter")
    return rows


def without_dropped(corrected, row):
    ends = {end: find_page(corrected["entities"], row[end]) for end in ("source", "target")}
    ids = {end: page["id"] for end, page in ends.items() if page}
    kept = [r for r in corrected["relations"] if not (r["chapter"] == row["chapter"] and r["type"] == row["type"] and r["source"] == ids.get("source") and r["target"] == ids.get("target"))]
    found = len(kept) < len(corrected["relations"])
    corrected["relations"] = kept
    return found


def apply_to_wiki(data, corrections, relations=(), dropped=()):
    corrected, missing = copy.deepcopy(data), []
    entities = corrected["entities"]
    by_id = {e["id"]: e for e in entities}
    for correction in corrections:
        page = find_page(entities, correction["name"])
        if page:
            correct_page(page, correction)
            if "known_from" in correction and "merged" in page:
                known_from(page, by_id[page["merged"]["into"]], correction["known_from"]["chapter"])
        else:
            missing.append(correction["name"])
    for row in relations:
        ends = {end: find_page(entities, row[end]) for end in ("source", "target")}
        missing += [row[end] for end, page in ends.items() if page is None]
        if all(ends.values()):
            corrected["relations"].append(added_relation(row, ends["source"], ends["target"]))
    missing += [f"{row['source']} -> {row['target']}: {row['type']} (ch {row['chapter']})" for row in dropped if not without_dropped(corrected, row)]
    if relations:
        corrected["relations"].sort(key=lambda r: r["chapter"])
    return corrected, missing


def reader_notes(kb, corrections, chapter):
    notes = {}
    for correction in corrections:
        entity = kb.resolve(correction["name"])
        parts = [f"type: {correction['type']}"] if "type" in correction else []
        parts += [f"{key}: {row['value']} (chapter {row['chapter']})" for key, rows in correction.get("fields", {}).items()
                  for row in rows if row["chapter"] < chapter]
        if entity and parts:
            notes[entity] = "; ".join(parts)
    return notes
