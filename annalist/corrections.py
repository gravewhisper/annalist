import sys
from dataclasses import dataclass
from pathlib import Path

from .files import read_json
from .names import name_key
from .template import PROFILE_FIELDS, PROFILE_LISTS
from .text import check_quote


PAGES, QUESTIONS = "pages", "questions"
EVERY_CORRECTION = (PAGES, QUESTIONS)


@dataclass(frozen=True)
class Corrections:
    entries: list
    relations: list
    dropped: list
    questions: list
    problems: list


def require(ok, message):
    if not ok:
        sys.exit(f"corrections.json: {message}")


def load_corrections(workdir):
    raw = read_json(Path(workdir) / "corrections.json", {})
    problems = []

    def quoted(label, row):
        quote = next((q for q in row.get("quotes", []) if check_quote(str(workdir), row["chapter"], q)["ok"]), None)
        if quote is None:
            problems.append(f"correction {label} ch{row['chapter']} has no quote found in that chapter, skipped")
        return quote

    entries = raw.get("entries", [])
    require(all(isinstance(e, dict) and e.get("name") for e in entries), "every entry needs a name")
    relations = raw.get("relations", [])
    require(all(isinstance(r, dict) and r.get("source") and r.get("target") and r.get("type") and r.get("chapter") for r in relations),
            "every relation needs a source, target, type and chapter")
    dropped = raw.get("drop_relations", [])
    require(all(isinstance(r, dict) and r.get("source") and r.get("target") and r.get("type") and r.get("chapter") for r in dropped),
            "every dropped relation needs a source, target, type and chapter")
    questions = raw.get("questions", [])
    require(all(isinstance(q, dict) and (q.get("id") or q.get("question")) for q in questions), "every question needs an id or its question text")
    require(all(q.get("dismiss") is True or (isinstance(q.get("chapter"), int) and str(q.get("answer") or "").strip()) for q in questions),
            'every question needs "dismiss": true, or a chapter and an answer')
    questions = [q if q.get("dismiss") is True else {**q, "quote": quoted(question_label(q), q)} for q in questions]
    return Corrections(entries=[checked_entry(e, quoted) for e in entries],
                       relations=[r for r in relations if quoted(f"{r['source']} -> {r['target']}.{r['type']}", r)],
                       dropped=dropped, questions=[q for q in questions if q.get("dismiss") is True or q["quote"]], problems=problems)


def question_label(row):
    return row.get("id") or row["question"]


def checked_entry(entry, quoted):
    entry = dict(entry)
    name = entry["name"]
    if "fields" in entry:
        entry["fields"] = {key: [{**r, "quote_ok": True} for r in rows if quoted(f"{name}.{key}", r)] for key, rows in entry["fields"].items()}
    if "known_from" in entry and not quoted(f"{name}.known_from", entry["known_from"]):
        del entry["known_from"]
    require("same_as" not in entry or isinstance(entry.get("chapter"), int),
            f"{name} needs the chapter from which it is the same as {entry.get('same_as')}")
    if "same_as" in entry and not quoted(f"{name}.same_as", entry):
        del entry["same_as"]
    require(all(isinstance(r, dict) and isinstance(r.get("chapter"), int) and str(r.get("value") or "").strip()
                for rows in entry.get("drop", {}).values() for r in rows), f"{name}: every dropped value needs a chapter and a value")
    return entry


def unmatched(name):
    return f"corrections.json names {name!r}, which matches no entry, skipped"


def known_from(corrections):
    return {name_key(e["name"]): e["known_from"]["chapter"] for e in corrections.entries if "known_from" in e}


def absorbed_part(entity, name):
    key = name_key(name)
    return next((a for a in entity.get("absorbed", []) if key in map(name_key, [a["name"]] + a["aliases"])), None)


def join(kb, entry, until):
    part, page, chapter = kb.resolve(entry["name"]), kb.resolve(entry["same_as"]), entry["chapter"]
    if page is None:
        return [unmatched(entry["same_as"])]
    later = absorbed_part(kb.entities[page], entry["same_as"])
    chapter = max(chapter, later["chapter"]) if later else chapter
    problem = ("already part of another page" if absorbed_part(kb.entities[part], entry["name"]) and name_key(entry["name"]) != name_key(part)
               else "already the same page" if part == page
               else f"chapter {chapter} is before one of them first appears"
               if chapter < max(kb.entities[part]["first_chapter"], kb.entities[page]["first_chapter"]) else None)
    if problem:
        return [f"correction {entry['name']} same_as {entry['same_as']}: {problem}, skipped"]
    if chapter <= until:
        own = kb.entities[part]
        kept = {"by": "reader", "type": own["type"], "last_chapter": own["last_chapter"]}
        kb.merge(part, page, chapter)
        for a in kb.entities[page].get("absorbed", []):
            if a["name"] == part and a["chapter"] == chapter:
                a.update(kept)
        kb.relations = [r for r in kb.relations if r["source"] != r["target"] or r["chapter"] < chapter]
    return []


def add_relation(kb, row, k, until):
    ends = {end: kb.resolve(row[end]) for end in ("source", "target")}
    missing = [unmatched(row[end]) for end, key in ends.items() if key is None]
    if missing or row["chapter"] > until:
        return missing
    filed = {end: a["name"] for end, key in ends.items() if (a := absorbed_part(kb.entities[key], row[end]))}
    kb.relations.append({"id": f"RC{row['chapter']:04d}-{k:03d}", "chapter": row["chapter"], **ends, "type": row["type"],
                         "detail": row.get("detail", ""), "family": row.get("family", "other"), "status": row.get("status", "stated"),
                         "asserted_by": row.get("by", "narrator"), "quotes": row["quotes"], "timeline": "main", **({"filed": filed} if filed else {})})
    return []


def drop_relation(kb, row):
    ends = {end: kb.resolve(row[end]) for end in ("source", "target")}
    kept = [r for r in kb.relations if not (r["chapter"] == row["chapter"] and r["type"] == row["type"]
                                             and all(r[end] == key for end, key in ends.items()))]
    if len(kept) == len(kb.relations):
        return [unmatched(f"{row['source']} -> {row['target']}: {row['type']} (ch {row['chapter']})")]
    kb.relations = kept
    return []


def correct_pages(kb, corrections, until):
    problems = [unmatched(e["name"]) for e in corrections.entries if kb.resolve(e["name"]) is None]
    for entry in corrections.entries:
        if "same_as" in entry and kb.resolve(entry["name"]):
            problems += join(kb, entry, until)
    for entry in corrections.entries:
        key = kb.resolve(entry["name"])
        if key and "type" in entry:
            kb.entities[key]["type"] = entry["type"]
        if key and "title" in entry:
            kb.entities[key]["title"] = {"name": entry["title"], **({"chapter": entry["title_chapter"]} if "title_chapter" in entry else {})}
    for k, row in enumerate(corrections.relations, 1):
        problems += add_relation(kb, row, k, until)
    for row in corrections.dropped:
        problems += drop_relation(kb, row)
    return problems


RESOLUTION = ("resolved_chapter", "resolved_shown", "answer", "resolve_quote", "payoff", "found_by", "context_found", "premise", "ending")


def find_question(questions, row):
    if row.get("id"):
        return questions.get(row["id"])
    return next((q for q in questions.values() if q["question"] == row["question"].strip()), None)


def settle_questions(kb, corrections, until):
    problems = []
    for row in corrections.questions:
        q = find_question(kb.questions, row)
        if q is None:
            problems.append(f"corrections.json names question {question_label(row)!r}, which matches no question, skipped")
        elif row.get("dismiss") is True:
            del kb.questions[q["id"]]
        elif row["chapter"] < q["chapter"]:
            problems.append(f"correction {question_label(row)} is answered in chapter {row['chapter']}, before chapter {q['chapter']} raises it, skipped")
        else:
            for key in RESOLUTION:
                q.pop(key, None)
            q["status"] = "partial" if q["leads"] else "open"
            if row["chapter"] <= until:
                q.update(status="resolved", resolved_chapter=row["chapter"], resolved_shown=row["chapter"], answer=row["answer"].strip(),
                         resolve_quote=row["quote"], payoff=str(row.get("payoff") or "").strip(), found_by="reader")
    return problems


def joined_rows(rows, part_rows, chapter):
    held = [{**r, "shown": max(r.get("shown", r["chapter"]), chapter)} for r in part_rows]
    return sorted(rows + held, key=lambda r: r["chapter"])


def merged_rows(existing, rows):
    chapters = {r["chapter"] for r in rows}
    return sorted([o for o in existing if o["chapter"] not in chapters] + rows, key=lambda o: o["chapter"])


def profile_group(key):
    return "lists" if key in PROFILE_LISTS else "fields" if key in PROFILE_FIELDS else "extra"


def empty_profile():
    return {"fields": {}, "extra": {}, "lists": {}}


def drop_value(rows_by_field, field, row):
    rows = rows_by_field.get(field, [])
    kept = [o for o in rows if not (o["chapter"] == row["chapter"] and name_key(o["value"]) == name_key(row["value"]))]
    if len(kept) < len(rows):
        rows_by_field[field] = kept
    return len(rows) - len(kept)


def correct_profiles(kb, pages, corrections):
    problems = []
    for entry in corrections.entries:
        key = kb.resolve(entry["name"])
        if key is None:
            continue
        part = absorbed_part(kb.entities[key], entry["name"]) if name_key(entry["name"]) != name_key(key) else None
        for field, rows in entry.get("fields", {}).items():
            group = profile_group(field)
            earlier = [r for r in rows if part and r["chapter"] < part["chapter"]]
            if earlier:
                own = pages.setdefault(part["name"], empty_profile())[group]
                own[field] = merged_rows(own.get(field, []), earlier)
            page = pages.setdefault(key, empty_profile())[group]
            page[field] = merged_rows(page.get(field, []), [{**r, "shown": part["chapter"]} if r in earlier else r for r in rows])
        names = [key] + [a["name"] for a in kb.entities[key].get("absorbed", [])]
        for field, rows in entry.get("drop", {}).items():
            for row in rows:
                if not sum(drop_value(pages[n][profile_group(field)], field, row) for n in names if n in pages):
                    problems.append(f"correction {entry['name']}.drop {field} ch{row['chapter']} {row['value']!r} matches no value, skipped")
    return pages, problems


def kept_deaths(kb, deaths):
    dropped = {(kb.resolve(e["name"]), r["chapter"]) for e in kb.corrections.entries for r in e.get("drop", {}).get("status", [])
               if name_key(r["value"]) == "dead"}
    return [d for d in deaths if (kb.resolve(d["name"]), d["chapter"]) not in dropped]


def reader_notes(kb, corrections, chapter):
    notes = {}
    for correction in corrections.entries:
        entity = kb.resolve(correction["name"])
        parts = [f"type: {correction['type']}"] if "type" in correction else []
        parts += [f"{key}: {row['value']} (chapter {row['chapter']})" for key, rows in correction.get("fields", {}).items()
                  for row in rows if row["chapter"] < chapter]
        if "same_as" in correction and correction["chapter"] < chapter:
            parts.append(f"same as {correction['same_as']} from chapter {correction['chapter']}")
        if entity and parts:
            notes[entity] = "; ".join(parts)
    return notes
