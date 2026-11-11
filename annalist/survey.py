import json
import re
from pathlib import Path

from .book import DEFAULT_BOOK, load_book, type_named
from .files import read_json, write_json
from .llm import cached_llm
from .names import name_key, names_of, slug
from .state import load_states
from .template import (base_field, BASE_TYPES, category_problems, distinct_fields, ENTITY_TYPES, INDIVIDUALS, overlapping_pairs,
                       PARENT_TYPES, PROFILE_FIELDS, STORY_TIMELINE_KINDS, written)
from .text import chapter_text


BOOK_PROMPT = """You are setting up a reference wiki for a novel, meant to rival a fan wiki for it. From the material below, decide what a fan wiki of this novel tracks that a wiki of any novel would not: the book-specific facts in each character's infobox, and the kinds of world entries it keeps pages for beyond the general types. A power or magic system is one source of these, never the only one: a fan wiki may track a character's cultivation stage or power class, but also a noble title or social rank, a military rank or regiment, a species or bloodline, a house or clan, or a ship. Later steps use your answer to classify entities and fill character infoboxes. Use only this material.

CHAPTER TITLES:
{titles}

{material}

Reply with one JSON object:
{{
  "power_system": "one sentence naming the order the fields and types below belong to: a power or magic system and how characters gain or rank up in it, or else the social, military, or other order the novel ranks its characters by; empty if the novel has none",
  "power_types": [{{"type": "lowercase singular noun", "parent": "the general type below that this type is a kind of: {parents}", "label": "the plural name the novel itself writes for these entries, as the material writes it (Bound Relics); empty if the novel has no word for them", "description": "what entities of this type are"}}],
  "rank_word": "the word the novel uses for one rank of the order above when it gives each rank a name of its own, as the material writes it (Tier in Tier 2: Warden); empty otherwise",
  "relation_example": "one short lowercase relation label between two entries of the types above, read as 'source <label> target'",
  "extra_fields": [{{"name": "snake_case field name", "description": "what the character infobox should record and the exact format to write it in", "values": ["the class, rank, or title names this field starts with, when it takes one of a few named values; else empty"]}}],
  "power_keywords": ["lowercase words or word stems that mark a passage stating or changing a character's extra field, or about entries of the types above"],
  "timeline_kind": "loop, flashback, or linear",
  "timeline_note": "one or two sentences on how the story moves through time"
}}
GENERAL TYPES (type: what it covers):
{base}

Rules: power_types lists the kinds of world entries a fan wiki of this novel keeps a category of their own for beyond the general types above, such as the powers, techniques, ranks, schools, spells, or creatures of a power system. Each power type is a kind of one general type, its parent: a technique or spell is a concept, a relic is an artifact, a sect is an organization, a breed of spirit beast is a creature. When the novel has a power or magic system, list two to six and include a type for specific powers or techniques. Otherwise list a type only when the novel names many entries of that kind and no general type covers them (a club or society is an organization, a book or letter is an item, a trial is an event), and list none when the general types cover the novel. power_types are kinds of things, never kinds of people: a person is always a character, however the novel classes people, and a class, rank, species, or title of people (a mutant, a hero class, a vampire, a baronet) is an extra field of the character, not a power type. The one exception is a named rank of the order (Tier 2: Warden): when the novel gives its ranks names of their own, set rank_word and list a power type named by it whose entries are the ranks themselves, and keep an extra field for the rank a character holds. Reuse an existing entity type name below when it is such a kind of thing; never keep one whose entries are people, even if the wiki so far used it. Power types that are kinds of one general type never overlap: no entry fits two of them, and none is described as a kind of another. A power type is never named like one entry of the novel: when a single group, place, or thing bears the name (the Silver Order), name the category by another word the novel uses for such entries. extra_fields lists the book-specific fact a fan-wiki infobox for this novel tracks per character as it changes over the story, such as their power, cultivation stage, class, title, rank, regiment, species, or house: usually one field, two only when the book tracks two independent things, none when the novel's characters differ only in the general fields. A field tracks one thing, so never join two in one field (a title or an occupation); never a list of abilities, a personality trait, or another name or code name for the character, and never one of the general fields {fields}. A field stays empty when the text does not state it, so never prescribe a placeholder value. power_keywords has five to twelve entries whenever extra_fields or power_types is not empty, is empty otherwise, and leaves out character names. timeline_kind is loop when a character relives time and restarts undo events, flashback when the story often leaves its present for scenes set in the past, and linear otherwise; timeline_note says which (who loops and from what point, or which past periods recur), or that the story runs in order.
"""


FORMS_OF_ADDRESS = {"mr", "mrs", "miss", "ms", "dr", "mister", "madam", "madame", "monsieur", "mademoiselle", "señor", "señora"}


def speakers(kb):
    spoke = set()
    for row in kb.facts + kb.relations:
        name = kb.resolve(row.get("asserted_by") or "")
        if name:
            spoke.add(name)
    return spoke


PERSON_WORDS = re.compile(r"\b(?:who|whose|whom|person|people|someone)\b", re.I)


EXAMPLES = re.compile(r"\b(?:such as|e\.g\.|for example|including)\b", re.I)
SECOND_KIND = re.compile(r"\bor (?:an?|another|any)\b", re.I)
CATCH_ALL = re.compile(r"\bor any\b", re.I)


def second_kind(description):
    return bool(SECOND_KIND.search(EXAMPLES.split(description, 1)[0]) or CATCH_ALL.search(description))


def people_in_type(kb, power_type, spoke=None):
    spoke = speakers(kb) if spoke is None else spoke
    members = sorted(n for n, e in kb.entities.items() if e["type"] == power_type)
    return members, [n for n in members if n in spoke]


def field_name(raw):
    return slug(raw).replace("-", "_")


CAPITALIZED = re.compile(r"(?<![\w'’-])[A-Z][\w'’-]*[a-z][\w'’-]*")


def unseen_names(texts, material):
    seen = material.lower()
    names = {m.group(0).rstrip("'’-") for text in texts for m in CAPITALIZED.finditer(text)
             if text[:m.start()].rstrip()[-1:] not in ("", ".", "!", "?", ":", ";", '"', "“", "(")}
    def found(word):
        return any(re.search(rf"(?<!\w){re.escape(form)}(?!\w)", seen) for form in {word.lower(), word.lower().removesuffix("s")})
    return sorted(w for w in names if not found(w))


def survey_texts(reply):
    texts = [str(reply.get("power_system") or ""), str(reply.get("timeline_note") or "")]
    texts += [f"{t.get('type', '')} {t.get('description', '')}" for t in reply.get("power_types") or [] if isinstance(t, dict)]
    for f in reply.get("extra_fields") or []:
        if isinstance(f, dict):
            texts += [str(f.get("description") or "")] + [str(v) for v in f.get("values") or []]
    return texts


def book_problems(reply, kb, material=None, novel=None):
    problems = []
    if material is not None:
        unseen = unseen_names(survey_texts(reply), material)
        if unseen:
            problems.append(f"the reply names {', '.join(unseen)}, which the material never mentions; describe the novel only from the material.")
    spoke = speakers(kb)
    for t in reply.get("power_types") or []:
        if not isinstance(t, dict) or not str(t.get("type") or "").strip():
            continue
        key = name_key(t["type"])
        parent = name_key(t.get("parent") or "")
        if parent in INDIVIDUALS:
            problems.append(f'power type "{key}" has the parent "{parent}", so its entries would be people. '
                            f"A class of people is an extra field of the character, not a power type.")
        elif parent not in PARENT_TYPES:
            problems.append(f'power type "{key}" needs a parent, the general type it is a kind of: one of {", ".join(PARENT_TYPES)}.')
        members, people = people_in_type(kb, key, spoke)
        if len(members) >= 3 and 2 * len(people) > len(members):
            problems.append(f'power type "{key}" holds people: {len(people)} of its {len(members)} entries so far speak in the story '
                            f'({", ".join(people[:5])}). A class of people is an extra field of the character, not a power type.')
        elif PERSON_WORDS.search(str(t.get("description") or "")):
            problems.append(f'power type "{key}" is described as a kind of person ("{t.get("description")}"). '
                            f"A class of people is an extra field of the character, not a power type.")
        if second_kind(str(t.get("description") or "")):
            problems.append(f'power type "{key}" is described as more than one kind of thing ("{t.get("description")}"), so it would take '
                            f"in entries its name does not cover; describe only the kind its name says.")
    specs = {}
    for f in reply.get("extra_fields") or []:
        if isinstance(f, dict) and str(f.get("name") or "").strip():
            base = base_field(field_name(f["name"]))
            joined = next((b for b in map(base_field, re.split(r"_(?:or|and)_", field_name(f["name"]))) if b), None)
            if base:
                problems.append(f'extra field "{f["name"]}" repeats the general field "{base.key}"; drop it.')
            elif joined:
                problems.append(f'extra field "{f["name"]}" joins the general field "{joined.key}" to another fact; keep only the other fact.')
            values = [str(v).strip().lower().rstrip(".") for v in f.get("values") or [] if str(v or "").strip()]
            if values and 2 * sum(v in FORMS_OF_ADDRESS for v in values) >= len(values):
                problems.append(f'extra field "{f["name"]}" lists forms of address ({", ".join(f["values"])}), which every novel has; '
                                f"keep a field only for a rank, title, class or other fact this novel tracks.")
            specs[field_name(f["name"])] = extra_field_spec(f)
    for a, b in overlapping_pairs(specs):
        problems.append(f'extra fields "{a}" and "{b}" track the same thing; keep one field for it.')
    if specs and not [w for w in reply.get("power_keywords") or [] if str(w or "").strip()]:
        problems.append("power_keywords is empty, so no passage about the extra fields can be found; list the words that mark one.")
    problems += label_problems(reply, novel)
    problems += category_problems(reply_types(reply), {n: e["type"] for e in kb.entities.values() for n in names_of(e)})
    problems += rank_problems(reply, novel)
    if reply.get("timeline_kind") not in STORY_TIMELINE_KINDS:
        problems.append(f"timeline_kind must be one of {', '.join(STORY_TIMELINE_KINDS)}, not {reply.get('timeline_kind')!r}.")
    return " ".join(problems) or None


def reply_types(reply):
    return {name_key(t["type"]): {"parent": name_key(t.get("parent") or ""), "description": str(t.get("description") or "").strip(),
                                  **({"label": str(t["label"]).strip()} if str(t.get("label") or "").strip() else {})}
            for t in reply.get("power_types") or [] if isinstance(t, dict) and str(t.get("type") or "").strip() and name_key(t["type"]) not in BASE_TYPES}


def label_problems(reply, text):
    if text is None:
        return []
    return [f'power type "{t}" has the label "{spec["label"]}", which the material never writes; give the plural name the novel itself '
            f"writes for these entries, or leave the label empty." for t, spec in reply_types(reply).items()
            if spec.get("label") and not written(spec["label"], text)]


def rank_problems(reply, novel):
    word = name_key(reply.get("rank_word") or "")
    if not word:
        return []
    if novel is not None and not re.search(rf"(?<!\w){re.escape(word)}", novel, re.I):
        return [f'rank_word "{word}" never appears in the material; give the word the novel itself writes for a rank, or leave it empty.']
    types = [name_key(t.get("type") or "") for t in reply.get("power_types") or [] if isinstance(t, dict)]
    if type_named(word, types) is None:
        return [f'rank_word is "{word}", so the novel names its ranks, but no power type holds them. List a power type "{word}" whose entries '
                f'are the named ranks themselves, and keep the extra field for the rank a character holds.']
    return []


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
    prompt = BOOK_PROMPT.format(titles=titles, material=material, base="\n".join(f"- {t.name}: {t.description}" for t in ENTITY_TYPES.values()),
                                fields=", ".join(PROFILE_FIELDS), parents=", ".join(PARENT_TYPES))
    known = "\n".join([str(read_json(workdir / "book.json", {}).get("title") or "")] + [n for e in kb.entities.values() for n in names_of(e)])
    reply = cached_llm(workdir, "book", prompt, check=lambda r: book_problems(r, extracted, prompt + "\n" + known, titles + "\n" + material))
    source = read_json(workdir / "source.json", {})
    previous = read_json(workdir / "book.json", {})
    book = {"power_system": str(reply.get("power_system") or "").strip(),
            "power_types": reply_types(reply),
            "rank_word": name_key(reply.get("rank_word") or ""),

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
