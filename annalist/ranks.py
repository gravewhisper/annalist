import re

from .names import UNTYPED, content_words, function_word_name, name_key, names_of
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
        if e["type"] != spec["group_type"] or (len(k.split()) > 1 and name_key(k.split()[-1]) == name_key(spec["group_type"].split()[-1])):
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


def named_items(kb, mentions):
    """Items named exactly as a rank the text names with the rank word and a number ("Circle 2: Warden"), unless the name ends in the
    item word. The rank wins: an item and a rank of one name are one rank."""
    items, found = rank_items(kb), {}
    for m in mentions:
        key = kb.index.get(name_key(m["name"]))
        if key and key not in found and kb.entities[key]["type"] in items and not item_named(key, items) and name_key(key) == name_key(m["name"]):
            found[key] = f'The text names "{m["form"]}" in chapter {m["chapter"]}'
    return found


def named_groups(kb):
    """Entries filed under the rank type whose name ends in the group word, such as "Rook school"."""
    return {k: f'The name ends in "{group_word(kb)}"' for k, e in sorted(kb.entities.items())
            if e["type"] == kb.step_type and len(k.split()) > 1 and name_key(k.split()[-1]) == name_key(group_word(kb))}


def ranked_decisions(kb, spec, word, mentions, decisions):
    """The retype decisions with the moves rank statements make. An entry stated to be a group's rank moves to the rank type, an entry of the
    rank type whose name ends in the group word to the group type, and an item named as a rank to the rank type unless the decisions file
    it under the group type, as a group named after its first rank."""
    named = {n: why for n, why in named_items(kb, mentions).items()
             if not any(d["name"] == n and d["to"] == spec["group_type"] for d in decisions)}
    moves = {**{n: (spec["step_type"], f'The wiki records "{text}"') for n, text in {**stated_steps(kb, spec, word), **stated_items(kb, word)}.items()},
             **{n: (spec["step_type"], why) for n, why in named.items()},
             **{n: (spec["group_type"], why) for n, why in named_groups(kb).items()}}
    return ([d for d in decisions if d["name"] not in moves]
            + [{"name": n, "from": kb.entities[n]["type"], "to": to, "source": "rank", "reason": why} for n, (to, why) in moves.items()])


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


OPENS = re.compile(r"(?:^|\n|[.!?…][\"”’]?\s+)[\"“]?$")
ALIASED = (re.compile(rf"\s+(?:with|whose|and)\s+(?:the|its|an?)\s+(?:[a-z]+\s+)?name\s+(?:is\s+)?(?:the\s+)?(?P<name>{NAME})"),
           re.compile(rf",?\s+(?:also|once|formerly|previously)\s+(?:called|named|known\s+as)\s+(?:the\s+)?(?P<name>{NAME})"))


def rank_mentions(workdir, chapters, word):
    patterns = mention_patterns(word)
    found = []
    for n in chapters:
        text = chapter_text(str(workdir), n)
        for kind, m in sorted(((kind, m) for kind, p in enumerate(patterns) for m in p.finditer(text)), key=lambda km: km[1].start()):
            name = " ".join(content_words(m["name"]))
            if name and not (function_word_name(re.split(r"['’]", name)[0]) or name.lower().startswith(word.lower())):
                alias = next(filter(None, (p.match(text, m.end()) for p in ALIASED)), None) if kind == 0 else None
                found.append({"chapter": n, "name": name, "form": " ".join(m.group(0).split()), "quote": rank_quote(text, m.start(), m.end()),
                              "kind": kind, "paragraph": text.rfind("\n", 0, m.start()) + 1, "start": m.start(), "end": m.end(),
                              "sentence": " ".join(sentence_of(text, m.start(), m.end()).split()),
                              "opens": bool(OPENS.search(text, 0, m.start("name"))) and kind == 1,
                              "article": kind < 2 and bool(re.search(r"(?<!\w)an?\s", m.group(0))),
                              **({"alias": " ".join(content_words(alias["name"]))} if alias else {})})
    return found


def common_words(workdir, chapters):
    return {w for n in chapters for w in re.findall(r"(?<![\w'’])[a-z]+(?![\w'’])", chapter_text(str(workdir), n))}


def rank_names(kb, mentions, word, common, ranks=()):
    """The mentions that name a rank, each with the rank's own name. A mention is dropped when it names a holder, as in "Maren, a Circle 3",
    when a sentence opens with a lone word before the rank ("However, Circle 3"), when a lone name in the next sentence is a word the book
    also writes in lower case ("Indeed!"), when the name holds the rank word itself, or when it ends in a person's or organization's name
    and starts with no known rank. A name that starts with a known rank and goes on ("Warden Holt", "Warden brews") is cut to that rank,
    a plural "Wardens" to "Warden", and a possessive "Warden's" to "Warden". A mention that overlaps the one before, as "Warden, Circle 3" in
    "Circle 2 Warden, Circle 3 Sage", is dropped. A name the text gives three or more numbers is a kind of
    person, as "a Circle 2 Mage" and "a Circle 4 Mage", not a rank. Known ranks are the rank entries and the names in ranks."""
    known = {name_key(n) for n in ranks}

    def rank(name):
        return name_key(name) in known or (kb.step_type and held_step(kb, name))

    out, last = [], (0, 0)
    for m in mentions:
        if (m["chapter"], m.get("start", 0)) < last:
            continue
        last = (m["chapter"], m.get("end", 0))
        name = re.sub(r"['’]s?$", "", m["name"]).strip()
        words = name.split()
        if (not words or m.get("article") or re.search(rf"(?i)(?<![^\W\d_]){re.escape(word)}", name)
                or (len(words) == 1 and (m.get("opens") or (m.get("kind") == 2 and words[0].lower() in common)))):
            continue
        if kb.resolve(name) is None and not rank(name):
            noun = words.index("of") - 1 if "of" in words[1:] else len(words) - 1
            stems = [words[noun][:-k] for k in (1, 2) if re.search(r"[^s]s$" if k == 1 else r"[^s]es$", words[noun])]
            single = next((n for w in stems if rank(n := " ".join(words[:noun] + [w] + words[noun + 1:]))), None)
            cut = next((" ".join(words[:n]) for n in range(len(words) - 1, 0, -1) if words[n] != "of" and rank(" ".join(words[:n]))), None)
            holder = kb.resolve(words[-1])
            if single:
                name = single
            elif cut:
                name = cut
            elif holder and kb.types.kind(kb.entities[holder]["type"]) in HOLDERS:
                continue
        out.append({**m, "name": name})
    numbers = {}
    for m in out:
        numbers.setdefault(name_key(m["name"]), set()).add(rank_number(m["form"]))
    return [m for m in out if len(numbers[name_key(m["name"])]) < KINDS]


KINDS = 3


HOLDERS = ("character", "deity", "organization")


def rank_entry(kb, name):
    """The step a ranked name holds: an entry of the rank type, else None for a name no entry holds or one filed under the rank type's
    general type, which the ladder files under the rank type. False for a name another kind of entry holds or one that ends in the
    group word."""
    key = held_step(kb, name)
    if key:
        return key
    if len(name.split()) > 1 and name_key(name.split()[-1]) == name_key(group_word(kb)):
        return False
    other = kb.resolve(name, kb.step_type)
    return None if other is None or kb.entities[other]["type"] in UNTYPED or kb.types.refines(kb.step_type, kb.entities[other]["type"]) else False


def group_word(kb):
    return kb.group_type.split()[-1]


def bare_group(name, kb):
    return re.sub(rf"\s+\({re.escape(kb.group_type)}\)$|\s+(?i:{re.escape(group_word(kb))})$", "", name)


def group_key(kb, name):
    """The group entry a ladder's group name stands for, also when one writes it "Lantern (school)" and the other "Rook school"."""
    bare = bare_group(name, kb)
    for n in dict.fromkeys((name, bare, f"{bare} {group_word(kb)}")):
        key = kb.resolve(n, kb.group_type)
        if key and kb.entities[key]["type"] == kb.group_type:
            return key
    return None


def text_ladders(workdir, kb, ladders, word):
    """Steps that the text ranks in a group although no ladder holds them. A ranked name joins a group when its sentence names that group
    with the group word ("the Rook School's Circle 3 is Oracle", or a rank of the group followed by the group word), or when it
    stands in a list of ranks ("Circle 2: Warden. Circle 3: Oracle.") whose other names the ladder gives that one group, each at
    the number the list gives it.
    A name the text gives the same rank under ("Circle 2 Warden, once called Keeper") joins at that rank. Only what the ladder
    places by the mention's chapter counts, and each step keeps the mention's chapter and quote."""
    rows = [{**l, "steps": list(l["steps"])} for l in ladders]
    held, bases = {}, []
    for i, l in enumerate(rows):
        if not l["group"]:
            continue
        group = group_key(kb, l["group"])
        names = [l["group"]] + (names_of(kb.entities[group]) if group else [])
        bases += [(i, bare_group(n, kb), 0) for n in names]
        for s in l["steps"]:
            key = held_step(kb, s["entry"]) or name_key(s["entry"])
            held.setdefault(key, []).append((i, s["rank"], s["chapter"]))
            bases += [(i, n, s["chapter"]) for n in ([s["entry"]] + (names_of(kb.entities[key]) if key in kb.entities else []))]
    word_after = rf"(?:['’]s)?\s+(?i:{re.escape(group_word(kb))})(?![\w-])"
    patterns = [(i, re.compile(rf"(?<![\w'’-]){re.escape(b)}{word_after}"), c) for i, b, c in dict.fromkeys(bases) if b]
    mentions = rank_names(kb, rank_mentions(workdir, sorted(kb.synopses), word), word, common_words(workdir, sorted(kb.synopses)),
                          [s["entry"] for l in ladders for s in l["steps"]])
    mentions += [{**m, "name": m["alias"]} for m in mentions if m.get("alias")]
    by_paragraph = {}
    for m in mentions:
        by_paragraph.setdefault((m["chapter"], m["paragraph"]), []).append(m)
    for (chapter, _), ms in sorted(by_paragraph.items()):
        ms = sorted(ms, key=lambda m: m["start"])
        group, todo, anchors = [None] * len(ms), [], {}
        for k, m in enumerate(ms):
            key, rank = rank_entry(kb, m["name"]), rank_number(m["form"])
            if (key or name_key(m["name"])) in held:
                now = [(i, r) for i, r, c in held[key or name_key(m["name"])] if c <= chapter]
                known = {i for i, r in now if r == rank}
                if now:
                    anchors[k] = next(iter(known)) if len(known) == 1 else None
            elif key is not False and rank is not None and re.search(re.escape(m["name"]), m["quote"], re.I):
                named = {i for i, p, c in patterns if c <= chapter and p.search(m["sentence"])}
                group[k] = next(iter(named)) if len(named) == 1 else None
                todo.append(k)
        start = 0
        for k in range(1, len(ms) + 1):
            if k == len(ms) or not listed(ms[k - 1], ms[k]):
                found = {anchors[j] for j in range(start, k) if j in anchors}
                for j in range(start, k):
                    if j in todo and group[j] is None and len(found) == 1:
                        group[j] = next(iter(found))
                start = k
        for k in todo:
            m, key = ms[k], rank_entry(kb, ms[k]["name"])
            if group[k] is not None and (key or name_key(m["name"])) not in held:
                rank = rank_number(m["form"])
                rows[group[k]]["steps"].append({"entry": key or m["name"], "rank": rank, "chapter": chapter, "quote": m["quote"],
                                                **({} if key else {"new": True})})
                held.setdefault(key or name_key(m["name"]), []).append((group[k], rank, chapter))
    sign = -1 if kb.spec.get("direction") == "descending" else 1
    for l in rows:
        l["steps"] = sorted(l["steps"], key=lambda s: (sign * s["rank"], s["entry"]))
        l["chapter"] = min(s["chapter"] for s in l["steps"])
    return rows


LISTED = 40


def listed(a, b):
    """Two ranked names next to each other in one list, as "Circle 2: Warden. Circle 3: Oracle."."""
    return b["start"] - a["end"] <= LISTED


def held_step(kb, name):
    key = kb.resolve(name, kb.step_type)
    return key if key and kb.entities[key]["type"] == kb.step_type else None
