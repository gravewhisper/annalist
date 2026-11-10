import json
import re
from pathlib import Path

from .book import DEFAULT_BOOK, load_book
from .files import read_json, write_json
from .llm import cached_llm
from .names import name_key, slug
from .state import load_states
from .template import base_field, BASE_TYPES, distinct_fields, overlapping_pairs, PROFILE_FIELDS, STORY_TIMELINE_KINDS
from .text import chapter_text


BOOK_PROMPT = """You are setting up a reference wiki for a novel. From the material below, describe the novel's power or magic system, if it has one, so later steps can classify entities and fill character infoboxes. Use only this material.

CHAPTER TITLES:
{titles}

{material}

Reply with one JSON object:
{{
  "power_system": "one sentence naming the system and how characters gain or rank up in power; empty if there is none",
  "power_types": [{{"type": "lowercase singular noun", "description": "what entities of this type are"}}],
  "relation_example": "one short lowercase relation label between two power-system entities, read as 'source <label> target'",
  "extra_fields": [{{"name": "snake_case field name", "description": "what the character infobox should record and the exact format to write it in", "values": ["the class or rank names this field starts with, when it takes one of a few named values; else empty"]}}],
  "power_keywords": ["lowercase words or word stems that mark a passage about a character's powers or a change in rank"],
  "timeline_kind": "loop, flashback, or linear",
  "timeline_note": "one or two sentences on how the story moves through time"
}}
Rules: power_types lists the kinds of power-system entities (two to six), never the general types {base}. Include a type for specific powers or techniques. power_types are kinds of things (powers, techniques, items, ranks, schools, substances), never kinds of people: a person is always a character, however the novel classes people by their power, and a class or rank of people (a mutant, a hero class, a power category) is an extra field of the character, not a power type. Reuse an existing entity type name below when it is such a kind of thing; never keep one whose entries are people, even if the wiki so far used it. extra_fields lists the book-specific fact a fan-wiki infobox for this novel tracks per character as it changes over the story, such as their power, rank, or class: usually one field, two only when the book tracks two independent things, never a list of abilities and never one of the general fields {fields}. A field stays empty when the text does not state it, so never prescribe a placeholder value. power_keywords has five to twelve entries and leaves out character names. timeline_kind is loop when a character relives time and restarts undo events, flashback when the story often leaves its present for scenes set in the past, and linear otherwise; timeline_note says which (who loops and from what point, or which past periods recur), or that the story runs in order.
"""


def speakers(kb):
    spoke = set()
    for row in kb.facts + kb.relations:
        name = kb.resolve(row.get("asserted_by") or "")
        if name:
            spoke.add(name)
    return spoke


PERSON_WORDS = re.compile(r"\b(?:who|whose|whom|person|people|someone)\b", re.I)


def people_in_type(kb, power_type, spoke=None):
    spoke = speakers(kb) if spoke is None else spoke
    members = sorted(n for n, e in kb.entities.items() if e["type"] == power_type)
    return members, [n for n in members if n in spoke]


def field_name(raw):
    return slug(raw).replace("-", "_")


def book_problems(reply, kb):
    problems = []
    spoke = speakers(kb)
    for t in reply.get("power_types") or []:
        if not isinstance(t, dict) or not str(t.get("type") or "").strip():
            continue
        key = name_key(t["type"])
        members, people = people_in_type(kb, key, spoke)
        if len(members) >= 3 and 2 * len(people) > len(members):
            problems.append(f'power type "{key}" holds people: {len(people)} of its {len(members)} entries so far speak in the story '
                            f'({", ".join(people[:5])}). A class of people is an extra field of the character, not a power type.')
        elif PERSON_WORDS.search(str(t.get("description") or "")):
            problems.append(f'power type "{key}" is described as a kind of person ("{t.get("description")}"). '
                            f"A class of people is an extra field of the character, not a power type.")
    specs = {}
    for f in reply.get("extra_fields") or []:
        if isinstance(f, dict) and str(f.get("name") or "").strip():
            base = base_field(field_name(f["name"]))
            if base:
                problems.append(f'extra field "{f["name"]}" repeats the general field "{base.key}"; drop it.')
            specs[field_name(f["name"])] = extra_field_spec(f)
    for a, b in overlapping_pairs(specs):
        problems.append(f'extra fields "{a}" and "{b}" track the same thing; keep one field for it.')
    if reply.get("timeline_kind") not in STORY_TIMELINE_KINDS:
        problems.append(f"timeline_kind must be one of {', '.join(STORY_TIMELINE_KINDS)}, not {reply.get('timeline_kind')!r}.")
    return " ".join(problems) or None


def extra_field_spec(f):
    description = str(f.get("description") or "").strip()
    values = [str(v).strip() for v in f.get("values") or [] if str(v or "").strip()]
    return {"description": description, "values": values} if values else description


def stable_fields(previous, generated):
    kept = {k: spec for k, spec in (previous or {}).items() if base_field(k) is None}
    return distinct_fields({**kept, **{k: spec for k, spec in generated.items() if k not in kept}})


def generate_book(workdir, kb, extracted, last=None):
    workdir = Path(workdir)
    chapters = [c for c in json.loads((workdir / "chapters.json").read_text(encoding="utf-8")) if last is None or c["index"] <= last]
    titles = "\n".join(c["title"] for c in chapters[:300])
    if kb.entities:
        counts = {}
        for e in kb.entities.values():
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        facts = {}
        for f in kb.facts:
            facts[f["entity"]] = facts.get(f["entity"], 0) + 1
        sample = sorted((e for e in kb.entities.values() if e["type"] not in BASE_TYPES), key=lambda e: -facts.get(e["name"], 0))[:40]
        material = ("ENTITY TYPES IN THE WIKI SO FAR (type: count):\n" + "\n".join(f"{t}: {n}" for t, n in sorted(counts.items(), key=lambda x: -x[1]))
                    + "\n\nSAMPLE ENTITIES OF THE OTHER TYPES (name [type]: summary):\n"
                    + "\n".join(f"- {e['name']} [{e['type']}]: {e['summary']}" for e in sample)
                    + "\n\nCHAPTER SYNOPSES:\n" + "\n".join(f"Ch {n}: {kb.synopses[n]}" for n in sorted(kb.synopses)[:30]))
    else:
        material = "OPENING CHAPTERS:\n" + "\n\n".join(chapter_text(str(workdir), c["index"])[:3000] for c in chapters[:10])
    reply = cached_llm(workdir, "book", BOOK_PROMPT.format(titles=titles, material=material, base=", ".join(sorted(BASE_TYPES)), fields=", ".join(PROFILE_FIELDS)),
                       check=lambda r: book_problems(r, extracted))
    source = read_json(workdir / "source.json", {})
    previous = read_json(workdir / "book.json", {})
    book = {"power_system": str(reply.get("power_system") or "").strip(),
            "power_types": {name_key(t["type"]): str(t.get("description") or "").strip() for t in reply.get("power_types") or []
                            if isinstance(t, dict) and str(t.get("type") or "").strip() and name_key(t["type"]) not in BASE_TYPES},
            "relation_example": str(reply.get("relation_example") or DEFAULT_BOOK["relation_example"]).strip(),
            "extra_fields": stable_fields(previous.get("extra_fields"), {
                field_name(f["name"]): extra_field_spec(f) for f in reply.get("extra_fields") or []
                if isinstance(f, dict) and str(f.get("name") or "").strip()}),
            "power_keywords": [str(w).strip().lower() for w in reply.get("power_keywords") or [] if str(w or "").strip()],
            "timeline_kind": reply["timeline_kind"],
            "timeline_note": str(reply.get("timeline_note") or "").strip(),
            "complete": bool(source.get("complete")) or previous.get("complete") is True}
    write_json(workdir / "book.json", {**previous, **book})
    return book


def cmd_book(args):
    workdir = Path(args.workdir).resolve()
    if (workdir / "book.json").exists() and not args.force:
        print(f"{workdir / 'book.json'} exists; edit it by hand or pass --force to regenerate")
    else:
        generate_book(workdir, load_states(workdir), load_states(workdir, retypes=False))
    print(json.dumps(load_book(workdir), ensure_ascii=False, indent=2))
