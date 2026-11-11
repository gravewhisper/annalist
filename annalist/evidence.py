import re

from .names import name_key, names_of, short_names
from .families import wording_key
from .template import AFFILIATION_RELATIONS
from .text import verified_quotes


def class_pattern(name):
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"\w*(?![\w-])", re.I)


def stems(value):
    return {w[:5] for w in re.findall(r"[a-z]{3,}", value.lower()) if w not in ("the", "and", "with", "his", "her", "can")}


def observation(workdir, value, row, source):
    return {"value": value, "chapter": row["chapter"], **verified_quotes(str(workdir), row["chapter"], row["quotes"]),
            "asserted_by": row.get("asserted_by") or "narrator", "timeline": row.get("timeline", "main"), "source": source}


def affiliations(workdir, kb, name):
    return [observation(workdir, r["target"], r, "relation") for r in kb.relations
            if r["source"] == name and wording_key(r["type"]) in AFFILIATION_RELATIONS and r.get("status") == "stated"
            and r["target"] in kb.entities and kb.types.is_a(kb.entities[r["target"]]["type"], ("organization",))
            and stems(r["target"]) & stems(" ".join(r["quotes"]))]


def predications(names, classes, ranks=()):
    subject = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    kinds = "|".join([re.escape(c) for c in sorted(classes, key=len, reverse=True)]
                     + [f"(?-i:{re.escape(r)})" for r in sorted(ranks, key=len, reverse=True) if r not in classes])
    article =r"(?:(?:a|an|the)\s+)?"
    close = r"(?:(?!of\b)[\w'/-]+\s+){0,2}?"
    return [re.compile(rf"^(?:{subject})(?:\s*\([^)]*\)|,[^,]{{1,60}},)?\s+(?:is|was|has been|had been|became|becomes|turned into)\s+{article}"
                       rf"(?:[\w'/-]+\s+){{0,4}}?({kinds})(?![\w-])", re.I),
            re.compile(rf"^(?:{subject})\b[^.]{{0,30}}?\b(?:drank|drinks|consumed|consumes)\s+{article}{close}({kinds})(?![\w-])", re.I),
            re.compile(rf"(?<!\w)(?:{subject}),\s+{article}{close}({kinds})(?![\w-])", re.I),
            re.compile(rf"^As\s+{article}{close}({kinds})(?![\w-])[^.]{{0,80}}?\b(?:{subject})(?!\w)", re.I)]


def field_classes(kb, book, key):
    classes = tuple(book["field_values"].get(key, ()))
    step = (book.get("ladder") or {}).get("step_type")
    return classes, tuple(e["name"] for e in kb.entities.values() if e["type"] == step) if classes else ()


def stated_classes(workdir, kb, name, classes, ranks=()):
    if not classes:
        return []
    patterns = predications(names_of(kb.entities[name]) + short_names(kb, name), classes, ranks)
    known = (*classes, *ranks)
    found = []
    for f in kb.facts:
        m = None
        if f["entity"] == name and f["status"] != "belief":
            m = next((hit for p in patterns if (hit := p.search(f["claim"]))), None)
        if m and any(class_pattern(m.group(1)).search(q) for q in f["quotes"]):
            value = next(c for c in known if c.lower() == m.group(1).lower())
            found.append(observation(workdir, value, f, "fact"))
    return found


def outlived(status, deaths, name):
    chapters = {d["chapter"] for d in deaths if d["name"] == name and d["value"] == "lives_on"}
    return [o for o in status if not (o["value"] == "dead" and o["chapter"] in chapters)]


def death_observations(deaths, name):
    return [{"value": d.get("value", "dead"), "chapter": d["chapter"], "quotes": d["quotes"], "asserted_by": "narrator", "quote_ok": d["quote_ok"],
             **({"dropped_quotes": d["dropped_quotes"]} if "dropped_quotes" in d else {}),
             "timeline": d.get("timeline", "main"), "source": "death", "circumstances": d["circumstances"]}
            for d in deaths if d["name"] == name and d["value"] in ("dead", "missing", "revived")]


def adds_nothing(o, latest):
    if latest is None:
        return False
    words = stems(o["value"])
    return name_key(o["value"]) == name_key(latest["value"]) or bool(words) and words <= stems(latest["value"])


def refines(o, latest):
    return latest is not None and latest["chapter"] == o["chapter"] and stems(latest["value"]) < stems(o["value"])


def merge_observations(*sources):
    kept, latest = [], {}
    for o in sorted((o for rows in sources for o in rows), key=lambda o: o["chapter"]):
        tid = o.get("timeline", "main")
        if adds_nothing(o, latest.get(tid)):
            continue
        if o.get("quote_ok") and refines(o, latest.get(tid)):
            kept.remove(latest[tid])
        kept.append(o)
        if o.get("quote_ok"):
            latest[tid] = o
    return kept


def add_evidence(workdir, kb, name, profile, probes, deaths, book):
    fields, extra = profile["fields"], profile["extra"]
    fields["status"] = merge_observations(outlived(fields.get("status", []), deaths, name), death_observations(deaths, name))
    fields["affiliation"] = merge_observations(fields.get("affiliation", []), affiliations(workdir, kb, name))
    for key in book["extra_fields"]:
        extra[key] = merge_observations(extra.get(key, []), stated_classes(workdir, kb, name, *field_classes(kb, book, key)), probes.get(key, []))
    return profile
