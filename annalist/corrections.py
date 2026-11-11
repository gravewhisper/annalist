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
    if "same_as" in entry and not isinstance(entry.get("chapter"), int):
        sys.exit(f"corrections.json: {entry['name']} needs the chapter from which it is the same as {entry['same_as']}")
    if "same_as" in entry and not quoted(workdir, entry["name"], "same_as", entry):
        del entry["same_as"]
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


def joined_rows(rows, part_rows, chapter):
    held = [{**r, "shown": max(r.get("shown", r["chapter"]), chapter)} for r in part_rows]
    return sorted(rows + held, key=lambda r: r["chapter"])


def split_at(rows, chapter, at=lambda r: r["chapter"]):
    return [r for r in rows if at(r) < chapter], [r for r in rows if at(r) >= chapter]


def join_pages(corrected, part, page, chapter):
    for e in corrected["entities"]:
        if (e.get("merged") or {}).get("into") == part["id"]:
            e["merged"] = {"into": page["id"], "chapter": max(e["merged"]["chapter"], chapter)}
    part["merged"] = {"into": page["id"], "chapter": chapter}
    have = names_of(page)
    for name, seen in [(part["name"], part["name_chapter"])] + [(a["name"], a["chapter"]) for a in part["aliases"]]:
        if name_key(name) not in have:
            have.add(name_key(name))
            page["aliases"].append({"name": name, "chapter": max(seen, chapter)})
    page["aliases"].sort(key=lambda a: a["chapter"])
    for key, at in (("blurbs", lambda b: b[0]), ("present", lambda c: c)):
        if key in part:
            part[key], later = split_at(part[key], chapter, at)
            page[key] = sorted(page.get(key, []) + later, key=at)
    if part.get("profile"):
        profile = page.setdefault("profile", {"fields": {}, "lists": {}, "spoke": [], "personality": []})
        for group in ("fields", "lists"):
            for key, rows in part["profile"][group].items():
                profile[group][key] = joined_rows(profile[group].get(key, []), rows, chapter)
        part["profile"]["spoke"], later = split_at(part["profile"]["spoke"], chapter, lambda s: s[0])
        profile["spoke"] = sorted(profile["spoke"] + later)
    for f in corrected.get("facts", []):
        if f["entity"] == part["id"] and f["chapter"] >= chapter:
            f["entity"] = page["id"]
    for r in corrected.get("relations", []):
        for end in ("source", "target"):
            if r[end] == part["id"] and r["chapter"] >= chapter:
                r[end] = page["id"]
    corrected["relations"] = [r for r in corrected.get("relations", []) if r["source"] != r["target"]]


def same_person(corrected, correction):
    by_id = {e["id"]: e for e in corrected["entities"]}
    part, page, chapter = find_page(corrected["entities"], correction["name"]), find_page(corrected["entities"], correction["same_as"]), correction["chapter"]
    if page and "merged" in page:
        page, chapter = by_id[page["merged"]["into"]], max(chapter, page["merged"]["chapter"])
    problem = ("already part of another page" if "merged" in part else "already the same page" if part is page
               else f"chapter {chapter} is before one of them first appears" if chapter < max(part["first"], page["first"]) else None)
    if problem:
        print(f"warning: correction {correction['name']} same_as {correction['same_as']}: {problem}, skipped")
    else:
        join_pages(corrected, part, page, chapter)


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
        if "same_as" in correction and not find_page(entities, correction["same_as"]):
            missing.append(correction["same_as"])
        elif "same_as" in correction and page:
            same_person(corrected, correction)
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
        if "same_as" in correction and correction["chapter"] < chapter:
            parts.append(f"same as {correction['same_as']} from chapter {correction['chapter']}")
        if entity and parts:
            notes[entity] = "; ".join(parts)
    return notes


def join_same_person(kb, corrections, until):
    joined = []
    for c in corrections:
        part, page = (kb.resolve(c[k]) for k in ("name", "same_as")) if "same_as" in c else (None, None)
        if part and page and part != page and max(kb.entities[part]["first_chapter"], kb.entities[page]["first_chapter"]) <= c["chapter"] <= until:
            kb.merge(part, page, c["chapter"])
            joined.append((part, page, c["chapter"]))
    kb.relations = [r for r in kb.relations if r["source"] != r["target"]]
    return joined
