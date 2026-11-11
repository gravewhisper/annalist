import re

from .names import content_words, function_word_name, name_key, names_of
from .text import chapter_text, sentence_of, text_window


NUMBER = r"\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
ORDINAL = r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d+(?:st|nd|rd|th)"
NAME = r"[A-Z][\w'’-]*(?:\s+(?:of\s+)?[A-Z][\w'’-]*){0,2}"


def rank_form(word):
    w = re.escape(word)
    return rf"(?i:(?<!\w){w}s?\s+(?:{NUMBER})(?!\w)|(?<!\w)(?:{ORDINAL})\s+{w}(?!\w))"


def stated_steps(kb, spec, word):
    form, head = rank_form(word), re.escape(spec["group_type"].split()[-1])
    of_rank = re.compile(rf"{form}(?:\s+\w+)?\s+of$")
    claims = [f["claim"] for f in kb.facts if re.search(form, f["claim"])]
    found = {}
    for k, e in sorted(kb.entities.items()):
        if e["type"] != spec["group_type"]:
            continue
        named = "|".join(re.escape(n) for n in sorted(names_of(e), key=len, reverse=True))
        step = re.compile(rf"(?<!\w)(?:{named})(?:\s*[,:(]\s*|\s+(?:is|was|becomes|became)\s+)(?:(?:a|an|the)\s+)?{form}"
                          rf"|{form}\s*[:,]?\s+(?:the\s+)?(?:{named})(?![\w'’]|\s+(?i:{head}))")
        group = re.compile(rf"{form}\s+of\s+(?:the\s+)?(?:{named})(?!\w)|(?<!\w)(?:{named})['’]s\s+{form}"
                           rf"|{form}\s+(?:the\s+)?(?:{named})\s+(?i:{head})")
        steps = [c for c in claims if step.search(c)] + [f"{k} {r['type']} {r['target']}" for r in kb.relations
                                                         if r["source"] == k and of_rank.search(r["type"])]
        ranked = any(group.search(c) for c in claims) or any(r["target"] == k and of_rank.search(r["type"]) for r in kb.relations)
        if steps and not ranked:
            found[k] = steps[0]
    return found


COUNTS = {w: n for n, w in enumerate(NUMBER.split("|")[1:])}
COUNTS |= {w: n for n, w in enumerate(ORDINAL.split("|")[:-1], 1)}
LINK = r"\s+(?:of|in|for|within|corresponding\s+to)"


def rank_number(phrase):
    digits = re.search(r"\d+", phrase)
    return int(digits.group()) if digits else next((COUNTS[w] for w in phrase.lower().split() if w in COUNTS), None)


def stated_group(kb, name):
    words = name.split()
    for n in range(len(words), 0, -1):
        key = kb.resolve(" ".join(words[:n]), kb.group_type)
        if key and kb.entities[key]["type"] == kb.group_type:
            return key
    return None


def stated_ranks(kb, word, key):
    form, item = rank_form(word), re.escape(kb.entities[key]["type"].split()[-1])
    named = "|".join(re.escape(n) for n in sorted(names_of(kb.entities[key]), key=len, reverse=True))
    rank, group = rf"(?P<rank>{form})(?:\s+[a-z][\w-]*)?", rf"{LINK}\s+(?:the\s+)?(?P<group>{NAME})"
    exact = rf"(?:{named})(?![\w'’-])(?!\s+(?i:{item})(?!\w))"
    claims = (re.compile(rf"(?<![\w'’-]){exact}(?:\s*[,:(]\s*|\s+(?:is|was|becomes|became)\s+)(?:(?:a|an|the)\s+)?{rank}{group}"),
              re.compile(rf"{rank}{group}\s+(?:is|was)\s+(?:(?:called|named|known\s+as|the)\s+)?{exact}"))
    tie = re.compile(rf"(?:is\s+)?(?:(?:a|an|the)\s+)?{rank}{LINK}", re.I)
    for f in kb.facts:
        m = f["entity"] == key and f["quotes"] and next(filter(None, (p.search(f["claim"]) for p in claims)), None)
        holder = m and stated_group(kb, m["group"])
        if holder:
            yield {"entry": key, "group": holder, "rank": rank_number(m["rank"]), "chapter": f["chapter"], "quote": f["quotes"][0],
                   "text": f["claim"]}
    for r in kb.relations:
        m = r["source"] == key and r["quotes"] and not r.get("id", "").startswith("RG") and tie.fullmatch(r["type"])
        if m and r["target"] in kb.entities and kb.entities[r["target"]]["type"] == kb.group_type:
            yield {"entry": key, "group": r["target"], "rank": rank_number(m["rank"]), "chapter": r["chapter"], "quote": r["quotes"][0],
                   "text": f"{r['source']} {r['type']} {r['target']}"}


def rank_items(kb):
    ladder = {name_key(n) for e in kb.entities.values() if e["type"] in (kb.step_type, kb.group_type) for n in names_of(e)}
    items = set()
    for e in kb.entities.values():
        head, _, tail = name_key(e["name"]).rpartition(" ")
        if e["type"] in kb.power_types - {kb.group_type, kb.step_type} and head in ladder and tail == e["type"].split()[-1]:
            items.add(e["type"])
    return items


def item_named(key, items):
    return name_key(key).split()[-1] in {t.split()[-1] for t in items}


def stated_items(kb, word):
    items, found = rank_items(kb), {}
    for k in sorted(k for k, e in kb.entities.items() if e["type"] in items and not item_named(k, items)):
        stated = next(stated_ranks(kb, word, k), None)
        if stated:
            found[k] = stated["text"]
    return found


def stated_ladders(kb, word, ladders):
    placed = {kb.resolve(s["entry"], kb.step_type) for l in ladders for s in l["steps"]}
    items, first = rank_items(kb), {}
    for k in sorted(k for k, e in kb.entities.items() if e["type"] == kb.step_type) if word and kb.group_type else []:
        for s in stated_ranks(kb, word, k) if k not in placed and not item_named(k, items) else []:
            pair = (s["group"], k)
            if s["rank"] is not None and (pair not in first or s["chapter"] < first[pair]["chapter"]):
                first[pair] = s
    rows = {}
    for (group, k), s in sorted(first.items()):
        rows.setdefault(group, []).append({"entry": k, "rank": s["rank"], "chapter": s["chapter"], "quote": s["quote"]})
    return [{"group": g, "group_type": kb.group_type, "chapter": min(s["chapter"] for s in steps), "steps": steps} for g, steps in rows.items()]


def joined_ladders(kb, ladders, extra):
    sign = -1 if kb.spec.get("direction") == "descending" else 1
    out = [{**l, "steps": list(l["steps"])} for l in ladders]
    for row in extra:
        same = next((l for l in out if l["group"] and kb.resolve(l["group"], kb.group_type) == row["group"]), None)
        if same is None:
            out.append(same := {**row, "steps": []})
        same["steps"] = sorted(same["steps"] + row["steps"], key=lambda s: (sign * s["rank"], s["entry"]))
        same["chapter"] = min(s["chapter"] for s in same["steps"])
    return out


TITLED = r"[\"“]?(?P<name>{name})[.!](?=[\"”]?\s+[\"“]?(?:They|Their|Its?|He|She|His|Her|This|These|Those)(?!\w))".format(name=NAME)


def mention_patterns(word):
    w, number = re.escape(word), rf"(?i:{NUMBER})"
    rank = rf"(?i:(?<!\w){w})\s+{number}"
    return (re.compile(rf"{rank}\s*[:,]?\s+(?:(?:is|was)\s+(?:(?:called|named|known\s+as)\s+)?)?(?:the\s+|a\s+)?(?P<name>{NAME})"),
            re.compile(rf"(?<![\w'’])(?P<name>{NAME})(?:,\s*|\s*\()(?:a\s+|the\s+)?(?i:{w})\s+{number}(?!\w)"),
            re.compile(rf"{rank}(?!\w)[^.!?:\n\"“”]{{0,80}}[.!?][\"”’]?\s+{TITLED}"))


def rank_quote(text, start, end, limit=400):
    lo = text.rfind("\n", 0, start) + 1
    hi = text.find("\n", end)
    for piece in (text[lo:len(text) if hi < 0 else hi], sentence_of(text, start, end)):
        if len(piece.strip()) <= limit:
            return " ".join(piece.split())
    return " ".join(text_window(text, start, end, limit // 3).split())


def rank_mentions(workdir, chapters, word):
    patterns = mention_patterns(word)
    found = []
    for n in chapters:
        text = chapter_text(str(workdir), n)
        for m in sorted((m for p in patterns for m in p.finditer(text)), key=lambda m: m.start()):
            name = " ".join(content_words(m["name"]))
            if name and not (function_word_name(re.split(r"['’]", name)[0]) or name.lower().startswith(word.lower())):
                found.append({"chapter": n, "name": name, "form": " ".join(m.group(0).split()), "quote": rank_quote(text, m.start(), m.end())})
    return found
