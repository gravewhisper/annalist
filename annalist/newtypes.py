from pathlib import Path

from .book import load_book, NEWTYPES_FILE, volume_types
from .files import read_json, write_json
from .llm import cached_llm, LLMError
from .names import name_key, names_of
from .state import load_states
from .survey import PERSON_WORDS, second_kind
from .template import BASE_TYPES, category_problems, PARENT_TYPES, written
from .text import chapter_text


NEWTYPES_PROMPT = """You keep the categories of a reference wiki for a novel that is being read volume by volume. The reader has just finished {volume}, which ends at chapter {end}, and knows nothing after it. {power_system}

Every entry is filed under a general type. Some general types have categories of this book's own below them:
{categories}

ENTRIES FILED ONLY UNDER A GENERAL TYPE SO FAR (name [type]: what it is):
{entries}

Long novels bring in new kinds of things as they go: a new part of the power system, a new kind of organization, a new kind of item. Decide whether the book has by now brought in a kind of entry that a fan wiki of this novel keeps a category of its own for and that no category above covers. Most volume ends bring in none; then reply with no new types.

Rules for a new type: it is a kind of one general type, its parent, and a kind of thing, never a kind of person. It does not overlap any category already below its parent: no entry fits both, and neither is described as a kind of the other. Its label is the plural name the novel itself writes for these entries, as the text writes it. It is never named like one entry of the novel: when a single group, place, or thing bears the name, choose another word the novel uses for such entries. It holds at least {least} of the entries listed above.

Then place each listed entry that belongs to a new type, or to a type added at an earlier volume end ({added}), under that type. Leave every other entry where it is.

Reply with one JSON object: {{"new_types": [{{"type": "lowercase singular noun", "parent": "one of {parents}", "label": "the plural name the novel writes", "description": "what entries of this type are"}}], "moves": [{{"name": "an entry name exactly as listed", "type": "a new type or a type added earlier"}}]}}
"""


NEW_TYPE_LEAST = 2


def read_upto(workdir, end):
    return "\n".join(chapter_text(workdir, n) for n in range(1, end + 1) if (Path(workdir) / "chapters" / f"{n:04d}.txt").exists())


def reply_types(reply):
    return {name_key(t["type"]): {"parent": name_key(t.get("parent") or ""), "label": str(t.get("label") or "").strip(),
                                  "description": str(t.get("description") or "").strip()}
            for t in reply.get("new_types") or [] if isinstance(t, dict) and str(t.get("type") or "").strip()}


def reply_moves(reply):
    return [(str(m.get("name") or "").strip(), name_key(m.get("type") or "")) for m in reply.get("moves") or [] if isinstance(m, dict)]


def new_type_problems(reply, kinds, added, entries, names, text):
    """kinds: every category so far; added: the ones added at earlier volume ends; entries: {name: general type} that may move."""
    new = reply_types(reply)
    problems = []
    for t, spec in new.items():
        if t in BASE_TYPES or t in kinds:
            problems.append(f'"{t}" is already a type; list only a type no category covers yet.')
        if spec["parent"] not in PARENT_TYPES:
            problems.append(f'new type "{t}" needs a parent, the general type it is a kind of: one of {", ".join(PARENT_TYPES)}.')
        if not spec["label"] or not written(spec["label"], text):
            problems.append(f'new type "{t}" needs a label the novel itself writes by this chapter, and "{spec["label"]}" is not one.')
        if PERSON_WORDS.search(spec["description"]):
            problems.append(f'new type "{t}" is described as a kind of person ("{spec["description"]}"). A class of people is not a type.')
        if second_kind(spec["description"]):
            problems.append(f'new type "{t}" is described as more than one kind of thing ("{spec["description"]}"); describe only the kind its name says.')
    every = {**kinds, **{t: s for t, s in new.items() if t not in kinds}}
    known = set(category_problems(kinds, names))
    problems += [p for p in category_problems(every, names) if p not in known]
    targets = {**{t: s["parent"] for t, s in added.items()}, **{t: s["parent"] for t, s in new.items()}}
    placed = {}
    for name, to in reply_moves(reply):
        if name not in entries:
            problems.append(f'"{name}" is not one of the listed entries; move only listed entries, by the name as listed.')
        elif to not in targets:
            problems.append(f'"{name}" is moved to "{to}", which is neither a new type nor one added earlier.')
        elif entries[name] != targets[to]:
            problems.append(f'"{name}" is filed under {entries[name]}, but "{to}" is a kind of {targets[to]}.')
        else:
            placed[to] = placed.get(to, 0) + 1
    problems += [f'new type "{t}" holds {placed.get(t, 0)} of the listed entries; a new type holds at least {NEW_TYPE_LEAST}.'
                 for t in new if placed.get(t, 0) < NEW_TYPE_LEAST]
    return " ".join(problems) or None


def categories(kinds):
    lines = []
    for parent in PARENT_TYPES:
        below = [f"{t} ({s['label']})" if s.get("label") else t for t, s in kinds.items() if s["parent"] == parent]
        lines.append(f"- {parent}: {', '.join(below) or 'no categories yet'}")
    return "\n".join(lines) + "\n" + "\n".join(f"  {t}: a kind of {s['parent']}, {s['description']}" for t, s in kinds.items())


def decide(workdir, book, volume, earlier):
    added = {t: {**s, "chapter": v["to"]} for v in earlier for t, s in v["types"].items()}
    kb = load_states(workdir, until=volume["to"], filled=(), added=False)
    kb.apply_added_types(added, [{**m, "chapter": v["to"]} for v in earlier for m in v["moves"]])
    entries = {n: e["type"] for n, e in kb.entities.items() if e["type"] in PARENT_TYPES}
    record = {"name": volume["name"], "from": volume["from"], "to": volume["to"], "types": {}, "moves": []}
    if not entries:
        return record
    kinds = {**book["power_types"], **{t: {k: s[k] for k in ("parent", "label", "description")} for t, s in added.items()}}
    names = {n: e["type"] for e in kb.entities.values() for n in names_of(e)}
    text = read_upto(workdir, volume["to"])
    prompt = NEWTYPES_PROMPT.format(
        volume=volume["name"], end=volume["to"], power_system=book["power_system"], categories=categories(kinds), least=NEW_TYPE_LEAST,
        entries="\n".join(f"- {n} [{t}]: {kb.entities[n]['summary'][:200]}" for n, t in sorted(entries.items())),
        added=", ".join(added) or "none yet", parents=", ".join(PARENT_TYPES))
    try:
        reply = cached_llm(workdir, "newtypes", prompt, check=lambda r: new_type_problems(r, kinds, added, entries, names, text))
    except LLMError as exc:
        return {**record, "rejected": str(exc)}
    new = reply_types(reply)
    targets = {**added, **new}
    return {**record, "types": new, "moves": [{"name": n, "from": entries[n], "to": to} for n, to in reply_moves(reply) if to in targets]}


def cmd_newtypes(args):
    workdir = Path(args.workdir).resolve()
    book = load_book(workdir)
    read = max((int(p.stem) for p in (workdir / "state").glob("[0-9][0-9][0-9][0-9].json")), default=0)
    read = min(read, args.to) if getattr(args, "to", None) else read
    kept = {(v["name"], v["from"], v["to"]): v for v in volume_types(workdir)}
    done = []
    for v in read_json(workdir / "volumes.json", {"volumes": []})["volumes"]:
        if v["to"] <= read:
            done.append(kept.get((v["name"], v["from"], v["to"])) or decide(workdir, book, v, done))
    write_json(workdir / NEWTYPES_FILE, {"volumes": done})
    for v in done:
        added = ", ".join(f"{t} ({s['label']}, a kind of {s['parent']})" for t, s in v["types"].items()) or "no new type"
        print(f"{v['name']} (ends ch {v['to']}): {added}; {len(v['moves'])} entries moved" + (f"; {v['rejected']}" if v.get("rejected") else ""))
