import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .book import load_book
from .files import write_json
from .llm import cached_llm
from .names import name_key
from .state import INDIVIDUALS, load_states, write_derived
from .template import BASE_TYPES, ENTITY_TYPES, UNCATEGORIZED
from .text import chapter_text, text_window


RETYPE_PROMPT = """Each entry below comes from a wiki built from a novel and shows the type it was filed under. {power_system}

Decide for each entry whether it is one specific individual: a named or uniquely described person, creature, or being with an identity of its own. An individual is a deity if the novel worships it as a god or godlike being, and a character otherwise, whatever class, species, rank, or power category the novel puts them in. An entry that is a kind, class, or group of beings, a power, an item, a rank, a place, or a concept is not an individual: give it the best type from this list:
{types}

{items}

Reply with one JSON object: {{"items": [{{"id": "...", "type": "character, deity, or a type from the list", "reason": "one short sentence"}}]}}, one entry per item.
"""


KIND_SHARE = 3
KIND_LEAST = 5


def kind_usage(workdir, kb, name, least=2):
    words = name.split()
    if len(words) < 2 or not all(w[:1].isupper() for w in words):
        return None
    pattern = re.compile(rf"(?<![\w-])((?:an?|some|many|other)\s+)?({re.escape(name)})(e?s)?(?![\w-])", re.I)
    kinds, named = [], 0
    for n in sorted(kb.synopses):
        text = chapter_text(str(workdir), n)
        for m in pattern.finditer(text):
            if m.group(1) or m.group(3):
                kinds.append((text, m))
            elif m.group(2) == name:
                named += 1
    if len(kinds) < least:
        return None
    text, m = kinds[0]
    return {"kind": len(kinds), "named": named, "window": text_window(text, m.start(), m.end(), 120)}


def a_kind(usage):
    return usage["kind"] >= KIND_LEAST and usage["kind"] >= KIND_SHARE * usage["named"]


def checked(kb, n, usage):
    return kb.entities[n]["type"] not in BASE_TYPES or kb.entities[n]["type"] == UNCATEGORIZED or n in usage


def cmd_retype(args):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir, merges=False, retypes=False, discovered=False)
    book = load_book(workdir)
    allowed = {**{t: "" for t in sorted(ENTITY_TYPES)}, **book["power_types"]}
    by_entity = {}
    for f in kb.facts:
        by_entity.setdefault(f["entity"], []).append(f)
    path = workdir / "types.json"
    usage = {n: u for n, e in kb.entities.items() if e["type"] in INDIVIDUALS and (u := kind_usage(workdir, kb, n))}
    ties = {}
    for r in kb.relations:
        for end in ("source", "target"):
            ties.setdefault(r[end], []).append(f"- {r['source']} {r['type']} {r['target']}")
    kinds = sorted(n for n, u in usage.items() if a_kind(u))
    counted = [{"name": n, "from": kb.entities[n]["type"], "to": "concept", "source": "usage",
                "reason": f"The text uses the name as a kind {usage[n]['kind']} times and as a name {usage[n]['named']} times."}
               for n in kinds]
    todo = sorted(n for n in kb.entities if checked(kb, n, usage) and n not in kinds)
    batches = [todo[i:i + 20] for i in range(0, len(todo), 20)]
    ladder = set((book.get("ladder") or {}).values()) & set(book["power_types"])

    def decide(batch):
        items = "\n\n".join(
            f"ID {k}\nName: {n} [{kb.entities[n]['type']}]\nAliases: {', '.join(kb.entities[n]['aliases']) or 'none'}\n"
            f"Summary: {kb.entities[n]['summary']}\n" + "\n".join(f"- {f['claim']}" for f in by_entity.get(n, [])[:4])
            + "".join(f"\n{t}" for t in ties.get(n, [])[:4] if not by_entity.get(n))
            + (f"\nThe text uses the name as a kind {usage[n]['kind']} times, as in \"{usage[n]['window']}\", "
               f"and as a name {usage[n]['named']} times." if n in usage else "")
            for k, n in enumerate(batch, 1))
        reply = cached_llm(workdir, "retype", RETYPE_PROMPT.format(
            power_system=book["power_system"], items=items,
            types="\n".join(f"- {t}" + (f": {d}" if d else "") for t, d in allowed.items() if t not in INDIVIDUALS)))
        found = {str(i.get("id")): i for i in reply.get("items") or [] if isinstance(i, dict)}
        out = []
        for k, n in enumerate(batch, 1):
            item = found.get(str(k)) or {}
            to = name_key(item.get("type") or "")
            if kb.entities[n]["type"] in ladder and to in book["power_types"]:
                to = kb.entities[n]["type"]
            if to in allowed:
                out.append({"name": n, "from": kb.entities[n]["type"], "to": to,
                            "reason": str(item.get("reason") or "").strip(), "source": "llm"})
        return out

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        decisions = counted + [d for batch in pool.map(decide, batches) for d in batch]
    write_json(path, {"entities": decisions})
    for d in decisions:
        verdict = f"{d['from']} -> {d['to']}" if d["to"] != d["from"] else f"keep {d['from']}"
        print(f"{verdict:<28} {d['name']} ({d['source']}): {d['reason']}")
    kb = load_states(workdir)
    write_derived(workdir, kb)
    print(f"{len(todo)} entries checked, {sum(d['to'] != d['from'] for d in decisions)} retyped, "
          f"{sum(d['to'] == 'character' and d['from'] != 'character' for d in decisions)} now characters")
