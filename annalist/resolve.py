import re
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

from .files import read_json, write_json
from .llm import cached_llm, LLMError
from .identify import identify_descriptors
from .names import (content_words, FUNCTION_WORDS, is_stub, NameIndex, parse_aliases, name_key, name_pattern, name_stems, name_tokens,
                    name_words, names_of, near_spelling, ROLE_WORDS, short_names, UNTYPED)
from .state import load_states, write_derived
from .text import chapter_text, locate_quote, SENTENCE_END, sentence_of, text_window


def candidate_pairs(workdir, kb, by_entity, max_chapter, radius=150, stub_partners=3):
    pairs = {}

    def add(a, b, rule, evidence=None):
        if a == b:
            return
        key = tuple(sorted((a, b)))
        entry = pairs.setdefault(key, {"rules": [], "evidence": []})
        if rule not in entry["rules"]:
            entry["rules"].append(rule)
        if evidence and len(entry["evidence"]) < 4:
            entry["evidence"].append(evidence)

    def variants(a, b):
        for x in names_of(kb.entities[a]):
            for y in names_of(kb.entities[b]):
                tx, ty = name_stems(x), name_stems(y)
                if tx and ty and (tx <= ty or ty <= tx):
                    add(a, b, f"name-containment: '{x}' / '{y}'")
                elif len(tx) == len(ty) and len(tx ^ ty) == 2 and near_spelling(*(tx ^ ty)):
                    add(a, b, f"near-spelling: '{x}' / '{y}'")

    typed = {}
    for name, e in kb.entities.items():
        if e["type"] not in UNTYPED:
            typed.setdefault(e["type"], []).append(name)
    for names in typed.values():
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                variants(a, b)
    for a, e in kb.entities.items():
        if e["type"] in UNTYPED:
            for b in (b for names in typed.values() for b in names):
                variants(a, b)

    people = [n for n in typed.get("character", []) if not is_stub(kb.entities[n])]
    name_words = {n: {w for a in names_of(kb.entities[n]) for w in name_tokens(a)} for n in people}
    for a in typed.get("character", []):
        facts = by_entity.get(a, [])
        for b in people:
            led = [f for f in facts if (name_tokens(" ".join(f["claim"].split()[:1])) & name_words[b])]
            if b != a and len(led) >= 3 and 3 * len(led) >= len(facts):
                add(a, b, f"claims-about-other: {len(led)} of {len(facts)} facts filed under {a} start with {b}'s name",
                    {"chapter": led[0]["chapter"], "text": led[0]["claim"]})

    patterns = {b: name_pattern(names_of(kb.entities[b])) for b in people}
    for a in typed.get("character", []):
        e = kb.entities[a]
        if not is_stub(e):
            continue
        anchors = [w for w in sorted(name_tokens(e["name"])) if len(w) >= 5 and w not in name_words.get(a, set())
                   and not any(w in name_words[p] for p in people)]
        if not anchors:
            continue
        anchor = name_pattern(anchors)
        hits = {}
        for n in range(e["first_chapter"], min(max_chapter, e["last_chapter"] + 5) + 1):
            text = chapter_text(str(workdir), n)
            for m in anchor.finditer(text):
                window = text[max(0, m.start() - radius):m.end() + radius]
                for b in people:
                    if b != a and patterns[b].search(window):
                        hits.setdefault(b, []).append({"chapter": n, "text": text_window(text, m.start(), m.end(), radius)})
        for b in sorted(hits, key=lambda b: (-len(hits[b]), -max(h["chapter"] for h in hits[b])))[:stub_partners]:
            later = sorted(hits[b], key=lambda h: -h["chapter"])
            add(a, b, f"stub-descriptor '{anchors[0]}' near {b} in text ({len(hits[b])} passages)", later[0])
            if len(later) > 1:
                add(a, b, f"stub-descriptor '{anchors[0]}' near {b} in text ({len(hits[b])} passages)", later[-1])
    holders = {name_key(e["name"]): n for n, e in kb.entities.items()}
    for a, e in kb.entities.items():
        for x in e["aliases"]:
            b = holders.get(name_key(x))
            if b and b != a:
                add(a, b, f"alias-is-other-entry: '{x}'")
        letters = INITIALS.fullmatch(e["name"])
        if letters:
            for b in typed.get("character", []):
                if b != a and any(initials(y) == letters.group(0).replace(".", "").replace(" ", "").lower()
                                  for y in names_of(kb.entities[b])):
                    add(a, b, f"initials: '{e['name']}'")
    for a, b in resemblances(kb, by_entity, people):
        add(a, b, "resemblance")
        pairs[tuple(sorted((a, b)))].setdefault("subject", (a, b))
    for a, b, cue in false_names(kb, typed, people):
        add(a, b, f"false-name: '{cue}'")
    for a, b, evidence in equated(workdir, kb, typed, max_chapter):
        add(a, b, "equated-in-sentence", evidence)
    for a, targets in hedged_identities(kb, by_entity).items():
        for b in targets:
            add(a, b, "hedged-identity")
    for holder, items in sorted(holdings(kb).items()):
        for a, b in combinations(sorted(items), 2):
            if kb.entities[a]["type"] == kb.entities[b]["type"]:
                add(a, b, f"same-holder: {holder}")
    for a, b, n, passages in listed_together(workdir, kb, typed, max_chapter):
        for p in passages:
            add(a, b, f"listed-together: ch{n}", p)
        pairs[tuple(sorted((a, b)))].setdefault("listed", n)
    for a, b in group_meetings(typed, kb):
        add(a, b, "group-and-meeting")
        pairs[tuple(sorted((a, b)))].setdefault("keep", a)
    for a, b, c in same_frames(kb, typed):
        add(a, b, f"same-frame: {c}")
    for (a, b), seen in co_mentioned(workdir, kb, max_chapter).items():
        for n in sorted(seen)[:2]:
            add(a, b, "co-mentioned", {"chapter": n, "text": seen[n]})
    for (a, b), entry in pairs.items():
        if not entry["evidence"]:
            entry["evidence"] = co_mentions(workdir, kb.entities[a], kb.entities[b], max_chapter, radius)
    return pairs


RESEMBLE = re.compile(r"\b(?:resembl\w*|looks? (?:just |exactly )?like|identical to|same\b[^.;]{0,60}?\bas)\s+", re.I)


def resemblances(kb, by_entity, people):
    patterns = {b: name_pattern(names_of(kb.entities[b])) for b in people}
    for a in people:
        for f in by_entity.get(a, []):
            for m in RESEMBLE.finditer(f["claim"]):
                rest = f["claim"][m.end():m.end() + 60]
                yield from ((a, b) for b in people if b != a and (hit := patterns[b].search(rest)) and hit.start() <= 12)


FALSE_NAME = re.compile(r"\b(?:(?:fake|false|assumed|cover|code|stage|pen)[ -]?names?|(?:fake|false|cover|secret) identit(?:y|ies)|"
                        r"alias(?:es)?|pseudonyms?|personas?|alter egos?)\b", re.I)


def false_names(kb, typed, people):
    for a in typed.get("character", []):
        for summary in {text for _, _, text in kb.summary_log.get(a, [])} | {kb.entities[a]["summary"]}:
            cue = FALSE_NAME.search(summary)
            if cue:
                yield from ((a, b, cue.group(0)) for b in people if b != a and called(kb, b).search(summary))


def listed_together(workdir, kb, typed, max_chapter, least=2, span=5):
    for names in typed.values():
        for a, b in combinations(names, 2):
            sa, sb = (set().union(*map(name_stems, names_of(kb.entities[x]))) for x in (a, b))
            if len(sa & sb) < least or sa <= sb or sb <= sa:
                continue
            pa, pb = (name_pattern(names_of(kb.entities[x])) for x in (a, b))
            lo = max(kb.entities[a]["first_chapter"], kb.entities[b]["first_chapter"])
            for n in range(lo, min(max_chapter, lo + span) + 1):
                text = chapter_text(str(workdir), n)
                line = next((m for m in re.finditer(r"[^\n]+", text) if pa.search(m.group(0)) and pb.search(m.group(0))), None)
                if not line:
                    continue
                hits = [h for p in (pa, pb) for h in p.finditer(line.group(0))]
                listing = sentence_of(line.group(0), min(h.start() for h in hits), max(h.end() for h in hits))
                passages = [{"chapter": n, "text": " ".join(listing.split())}]
                passages += [p for x, y in ((pa, pb), (pb, pa)) if (p := named_alone(workdir, x, y, n, line.end(), max_chapter))]
                yield a, b, n, passages
                break


def named_alone(workdir, pattern, other, chapter, offset, max_chapter, context=4):
    for n in range(chapter, max_chapter + 1):
        text = chapter_text(str(workdir), n)
        for m in pattern.finditer(text, offset if n == chapter else 0):
            sentence = " ".join(sentence_of(text, m.start(), m.end()).split())
            if not other.search(sentence) and len(name_words(sentence)) >= len(name_words(m.group(0))) + context:
                return {"chapter": n, "text": sentence}
    return None


def group_meetings(typed, kb):
    def words(name):
        return [w.lower() for w in content_words(name)]

    for a in typed.get("organization", []):
        for b in typed.get("event", []):
            if any(len(x) == len(y) >= 2 and x[:-1] == y[:-1] and x[-1] != y[-1]
                   for x in map(words, names_of(kb.entities[a])) for y in map(words, names_of(kb.entities[b]))):
                yield a, b


def frame(name):
    words = content_words(name)
    cut = next((i for i, w in enumerate(words) if w.lower() == "of"), None)
    if cut is None:
        return None
    return frozenset(name_stems(" ".join(words[:cut]))), frozenset(name_stems(" ".join(words[cut + 1:])))


def same_frames(kb, typed):
    forms = [(k, name_stems(n)) for k, e in kb.entities.items() if e["type"] not in UNTYPED for n in names_of(e)]
    for names in typed.values():
        framed = [(x, f) for x in names for n in names_of(kb.entities[x]) if (f := frame(n))]
        for (a, (ha, ia)), (b, (hb, ib)) in combinations(framed, 2):
            if a == b or ha != hb or not ia or not ib or ia == ib:
                continue
            c = next((k for k, stems in forms if k not in (a, b) and ia | ib <= stems), None)
            if c:
                yield a, b, c


HEDGE = re.compile(r"\b(?:likely|probably|possibly|presumably|perhaps|apparently|may be|might be|seems to be|appears to be)\s+"
                   r"(?:to be\s+)?((?:the|an?)\s+)?", re.I)


def hedged_identities(kb, by_entity):
    names = {}
    for e in kb.entities.values():
        if e["type"] not in UNTYPED:
            names.setdefault(e["type"], []).extend(names_of(e))
    patterns = {t: name_pattern(ns) for t, ns in names.items()}
    found = {}
    for a in sorted(kb.entities):
        e = kb.entities[a]
        pattern = patterns.get(e["type"])
        if not pattern:
            continue
        for text in [e["summary"]] + [f["claim"] for f in by_entity.get(a, [])]:
            for m in HEDGE.finditer(text):
                hit = next((h for start in (m.start(1), m.end()) if start >= 0 and (h := pattern.match(text, start))), None)
                b = kb.resolve(hit.group(0)) if hit else None
                if b and b != a and kb.entities[b]["type"] == e["type"] and b not in found.get(a, []):
                    found.setdefault(a, []).append(b)
    return found


EQUATES = re.compile(r"\b(?:about the same|the same as|similar to|also known as|ancient name|equivalent)\b", re.I)


def equated(workdir, kb, typed, max_chapter, limit=200):
    kinds = {n: t for t, names in typed.items() for n in names}
    index = NameIndex({n: names_of(kb.entities[n]) for n in kinds})

    def named(sentence):
        cue = EQUATES.search(sentence) if len(sentence) <= limit else None
        spots = {}
        for at, e in index.mentions(sentence) if cue else ():
            spots.setdefault(e, at)
        return (cue.start() if cue else 0), spots

    for n in sorted(c for c in kb.synopses if c <= max_chapter):
        for line in chapter_text(str(workdir), n).split("\n"):
            for sentence in map(str.strip, SENTENCE_END.split(line)):
                cue, spots = named(sentence)
                for a, b in combinations(sorted(spots), 2):
                    if kinds[a] == kinds[b] and min(spots[a], spots[b]) < cue:
                        yield a, b, {"chapter": n, "text": sentence}
    for a in sorted(kinds):
        for sentence in map(str.strip, SENTENCE_END.split(kb.entities[a]["summary"])):
            cue, spots = named(sentence)
            yield from ((a, b, None) for b, at in sorted(spots.items()) if b != a and kinds[b] == kinds[a] and at > cue)


OWNS = re.compile(r"\b(?:owns?|owned|owner|holds?|held|holder|carr(?:y|ies|ied)|wields?|wielded|possess\w*|belongs?|property|keeps?|kept)\b",
                  re.I)
OWNED_BY = re.compile(r"\b(?:by|belongs?|property)\b", re.I)
POSSESSIVE = re.compile(r"((?:[A-Z][\w-]*\s+)*[A-Z][\w-]*)['’]s\b")


def things(kb):
    return {n: e for n, e in kb.entities.items() if e["type"] not in UNTYPED and e["type"] != "character"}


def possessor(kb, phrase):
    words = phrase.split()
    return next((h for i in range(len(words)) if (h := kb.resolve(" ".join(words[i:])))), None)


def holdings(kb):
    held = {}
    items = things(kb)
    for name in sorted(items):
        lead = re.split(r"[,;.]", items[name]["summary"], maxsplit=1)[0]
        for text in names_of(items[name]) + [lead]:
            for m in POSSESSIVE.finditer(text):
                holder = possessor(kb, m.group(1))
                if holder and holder != name:
                    held.setdefault(holder, set()).add(name)
    for r in kb.relations:
        if OWNS.search(r["type"]):
            holder, item = (r["target"], r["source"]) if OWNED_BY.search(r["type"]) else (r["source"], r["target"])
            if item in items and holder != item:
                held.setdefault(holder, set()).add(item)
    return held


def co_mentioned(workdir, kb, max_chapter, least=2):
    items = things(kb)
    index = NameIndex({n: names_of(e) for n, e in items.items()})
    seen = {}
    for n in sorted(c for c in kb.synopses if c <= max_chapter):
        for line in chapter_text(str(workdir), n).split("\n"):
            for sentence in SENTENCE_END.split(line):
                for a, b in combinations(sorted(index.find(sentence)), 2):
                    if items[a]["type"] == items[b]["type"]:
                        seen.setdefault((a, b), {}).setdefault(n, sentence.strip())
    return {k: v for k, v in seen.items() if len(v) >= least}


INITIALS = re.compile(r"(?:[A-Z]\.\s?){2,3}")


def initials(name):
    return "".join(w[0] for w in content_words(name) if w[:1].isupper() and w.lower() not in ROLE_WORDS).lower()


def apart(na, nb):
    def overlaps(x, y):
        return name_key(x) in name_key(y) or name_key(y) in name_key(x)
    return [x for x in na if not any(overlaps(x, y) for y in nb)], [y for y in nb if not any(overlaps(x, y) for x in na)]


def co_mentions(workdir, a, b, max_chapter, radius, limit=3):
    na, nb = apart(names_of(a), names_of(b))
    if not na or not nb:
        return []
    pa, pb = name_pattern(na), name_pattern(nb)
    lo = min(a["first_chapter"], b["first_chapter"])
    hi = min(max_chapter, max(a["last_chapter"], b["last_chapter"]), lo + 20)
    found = []
    for n in range(lo, hi + 1):
        text = chapter_text(str(workdir), n)
        for m in pb.finditer(text):
            if pa.search(text[max(0, m.start() - radius):m.end() + radius]):
                found.append({"chapter": n, "text": text_window(text, m.start(), m.end(), radius)})
                break
        if len(found) >= limit:
            break
    return found


RESOLVE_PROMPT = """Two entries in a wiki built from a novel may describe the same {type}. Decide from the material below alone whether they are the same {type} (one person, place, or thing, possibly under different names, a description used before the name was known, a persona, or a spelling variant) or two different ones that merely share words or appear together. The novel is a translation, so the same name or serial number can be spelled inconsistently between chapters.{listing}

ENTRY A
{a}

ENTRY B
{b}

PASSAGES FROM THE NOVEL THAT MAY LINK THEM
{evidence}

Reply with one JSON object: {{"same": true or false, "canonical_name": "the name the merged page should use, exactly one of the two entry names; empty if not the same", "reason": "one or two sentences citing the material"}}
"""


LISTED = """

The two names are listed together in one passage. Titles that share an epithet and are addressed in one prayer or incantation name one being when the text treats the addressee as one, for example when it speaks of whom the prayer is for. Separate steps of one ritual are not by themselves separate beings."""


POSSESSIVE_END = re.compile(r"['’]s$")


def entity_card(kb, name, facts, other):
    e = kb.entities[name]
    mentions = name_pattern(names_of(kb.entities[other]))
    ordered = sorted(facts, key=lambda f: (not mentions.search(f["claim"]), f["chapter"]))
    shown = sorted(ordered[:6], key=lambda f: f["chapter"])
    lines = [f"Name: {e['name']}", f"Aliases: {', '.join(e['aliases']) or 'none'}",
             f"Chapters: {e['first_chapter']} to {e['last_chapter']}", f"Summary: {e['summary'] or 'none'}",
             f"Facts ({len(shown)} of {len(facts)}):"]
    for f in shown:
        lines.append(f"- ch{f['chapter']}: {f['claim']}" + (f' Quote: "{f["quotes"][0]}"' if f["quotes"] else ""))
    return "\n".join(lines)


def decide_pair(workdir, kb, by_entity, attached, a, b, info):
    evidence = "\n".join(f"- ch{p['chapter']}: \"{p['text']}\"" for p in info["evidence"]) or "(none)"
    same_type = kb.entities[a]["type"] == kb.entities[b]["type"]
    listed = LISTED if any(r.startswith("listed-together") for r in info["rules"]) else ""
    reply = cached_llm(workdir, "resolve", RESOLVE_PROMPT.format(
        type=kb.entities[a]["type"] if same_type else "person or thing", evidence=evidence, listing=listed,
        a=entity_card(kb, a, by_entity.get(a, []), b), b=entity_card(kb, b, by_entity.get(b, []), a)))
    same = reply.get("same") is True
    choice = name_key(info["keep"]) if "keep" in info else name_key(reply.get("canonical_name") or "") if same_type else ""
    canonical = min((a, b), key=lambda n: (kb.entities[n]["type"] in UNTYPED, bool(POSSESSIVE_END.search(n)), name_key(n) != choice,
                                           -len(by_entity.get(n, []))))
    decision = {"a": a, "b": b, "type": kb.entities[a]["type"], "rules": info["rules"], "same": same,
                "canonical": canonical if same else "", "reason": str(reply.get("reason") or "").strip(), "source": "llm"}
    if same:
        decision["revealed"] = reveal_chapter(workdir, kb, by_entity, attached, a, b, info)
    return decision


SUSPECT_PROMPT = """A wiki built from a novel has two character entries, "{a}" and "{b}". The novel says or shows that {a} resembles {b}. The wiki shows each chapter's page only with what a reader knows by that chapter.

ENTRY A
{card_a}

ENTRY B
{card_b}

PASSAGES that name both, earliest first:
{passages}

Decide whether the novel makes A and B the very same individual, and from which chapter.
- "explicit": a passage states or plainly shows that they are one person.
- "implied": a character strongly suspects it, or the text points to it without confirming it in these passages.
- "none": they only look alike, are relatives or descendants, or a reader could only connect them with hindsight.

Reply with one JSON object: {{"basis": "explicit", "implied", or "none", "chapter": the chapter number of the earliest passage that shows it, or null for none, "quote": "one or two sentences copied exactly from that passage that show it", "reason": "one sentence"}}
"""


def suspect_pair(workdir, kb, by_entity, a, b, info):
    passages, pa, pb = reveal_passages(workdir, kb, a, b, max(kb.synopses, default=0))

    def problem(reply):
        if reply.get("basis") not in ("explicit", "implied", "none"):
            return "basis must be explicit, implied or none"
        n = reply.get("chapter")
        if reply["basis"] == "none":
            return None
        if not isinstance(n, int) or n not in kb.synopses:
            return f"chapter {n!r} is not one of the passages' chapters"
        text = chapter_text(str(workdir), n)
        found = locate_quote(text, str(reply.get("quote") or ""))
        if not (found["ok"] and found["span"]):
            return f"the quote is not one contiguous span of chapter {n}; copy one or two adjacent sentences exactly"
        around = text[max(0, found["span"][0] - 1000):found["span"][1] + 1000]
        if not (pa and pb and pa.search(around) and pb.search(around)):
            return f"the text around the quote in chapter {n} does not name both {a} and {b}"
        return None

    decision = {"a": a, "b": b, "type": "character", "rules": info["rules"], "same": False, "canonical": "", "source": "llm"}
    try:
        reply = cached_llm(workdir, "suspect", SUSPECT_PROMPT.format(
            a=a, b=b, card_a=entity_card(kb, a, by_entity.get(a, []), b), card_b=entity_card(kb, b, by_entity.get(b, []), a),
            passages="\n".join(f"- ch{p['chapter']}: \"{p['text']}\"" for p in passages) or "(none)"), check=problem)
    except LLMError:
        return {**decision, "reason": "no usable reply"}
    found = {"chapter": reply.get("chapter"), "quote": str(reply.get("quote") or "")}
    decision["reason"] = str(reply.get("reason") or "").strip()
    if reply["basis"] == "explicit":
        return {**decision, "same": True, "canonical": max((a, b), key=lambda n: len(by_entity.get(n, []))),
                "revealed": {**found, "basis": "quote"}}
    return {**decision, "possibly": found} if reply["basis"] == "implied" else decision


REVEAL_PROMPT = """Two entries in a wiki built from a novel have been judged to be the same {type}. The wiki shows each chapter's page only with what a reader knows by that chapter, so it must not link the two before the novel lets a reader know they are the same.

ENTRY A: {a}
ENTRY B: {b}

PASSAGES that name both, earliest first:
{passages}

Find the earliest passage that states or plainly shows that A and B are the same {type}. A passage that only names both, or that a reader could only connect with hindsight, does not count.

Reply with one JSON object: {{"chapter": the chapter number of that passage, or null if none of them shows it, "quote": "one or two sentences copied exactly from that passage that show it"}}
"""


VARIANT_RULES = ("name-containment", "near-spelling", "alias-is-other-entry", "listed-together", "group-and-meeting")


def reveal_passages(workdir, kb, a, b, max_chapter, radius=1000, limit=6):
    na, nb = (names_of(kb.entities[x]) + short_names(kb, x) for x in (a, b))
    na = apart(na, nb)[0]
    nb = apart(nb, na)[0]
    if not na or not nb:
        return [], None, None
    pa, pb = name_pattern(na), name_pattern(nb)
    found = []
    for n in range(max(kb.entities[a]["first_chapter"], kb.entities[b]["first_chapter"]), max_chapter + 1):
        text = chapter_text(str(workdir), n)
        for m in pb.finditer(text):
            if pa.search(text[max(0, m.start() - radius):m.end() + radius]):
                found.append({"chapter": n, "text": text_window(text, m.start(), m.end(), radius)})
                break
        if len(found) >= limit:
            break
    return found, pa, pb


def head_word(name):
    words = content_words(name)
    cut = next((i for i, w in enumerate(words) if w.lower() in FUNCTION_WORDS), len(words))
    return [w for w in words[:cut][-1:] if w.lower() not in ROLE_WORDS]


def called(kb, x):
    e = kb.entities[x]
    return name_pattern(names_of(e) + short_names(kb, x) + (head_word(e["name"]) if is_stub(e) else []))


def fact_passages(workdir, kb, by_entity, named, a, b, radius=1000, limit=6):
    start = max(kb.entities[a]["first_chapter"], kb.entities[b]["first_chapter"])
    facts = [(x, f) for x in (a, b) for f in by_entity.get(x, []) if f["chapter"] >= start and f["chapter"] in kb.synopses]

    def shows(n):
        here = [(x, f) for x, f in facts if f["chapter"] == n]
        return {x for x, _ in here} == {a, b} or any(named[b if x == a else a].search(" ".join([f["claim"]] + f["quotes"]))
                                                     for x, f in here)

    found = []
    for n in sorted(n for n in {f["chapter"] for _, f in facts} if shows(n)):
        text = chapter_text(str(workdir), n)
        spans = sorted(tuple(hit["span"]) for _, f in facts if f["chapter"] == n for q in f["quotes"]
                       if (hit := locate_quote(text, q))["ok"] and hit["span"])
        merged = []
        for lo, hi in spans:
            if merged and lo - merged[-1][1] <= 2 * radius:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        found += [{"chapter": n, "text": text_window(text, lo, hi, radius)} for lo, hi in merged]
    return found[:limit]


def name_chapters(workdir, kb):
    attached = {}
    for path in sorted((Path(workdir) / "state").glob("[0-9][0-9][0-9][0-9].json")):
        state = read_json(path, {})
        for rec in state["extraction"].get("entities") or []:
            holder = kb.resolve(str(rec.get("name") or "")) if isinstance(rec, dict) else None
            for name in [str(rec.get("name") or "")] + parse_aliases(rec.get("aliases")) if holder else []:
                attached.setdefault((holder, name_key(name)), state["chapter"])
    return attached


def variant_chapter(kb, attached, a, b):
    def overlaps(x, y):
        return name_key(x) in name_key(y) or name_key(y) in name_key(x)
    def since(e, name):
        merged = [m["chapter"] for m in kb.entities[e].get("absorbed", [])
                  if name_key(name) in map(name_key, [m["name"]] + m["aliases"])]
        return max([attached.get((e, name_key(name)), kb.entities[e]["first_chapter"])] + merged)

    linked = [max(since(a, x), since(b, y)) for x in names_of(kb.entities[a]) for y in names_of(kb.entities[b]) if overlaps(x, y)]
    return max(kb.entities[a]["first_chapter"], kb.entities[b]["first_chapter"], min(linked, default=0))


def reveal_chapter(workdir, kb, by_entity, attached, a, b, info, window=1000):
    passages, pa, pb = reveal_passages(workdir, kb, a, b, max(kb.synopses, default=0))
    named = {x: called(kb, x) for x in (a, b)}
    variant = {"chapter": max(variant_chapter(kb, attached, a, b), info.get("listed", 0)), "quote": "", "basis": "variant"} \
        if any(r.startswith(VARIANT_RULES) for r in info["rules"]) else None

    def problem(reply, relaxed):
        n = reply.get("chapter")
        if n is None:
            return None
        if not isinstance(n, int) or n not in kb.synopses:
            return f"chapter {n!r} is not one of the passages' chapters"
        text = chapter_text(str(workdir), n)
        found = locate_quote(text, str(reply.get("quote") or ""))
        if not (found["ok"] and found["span"]):
            return f"the quote is not one contiguous span of chapter {n}; copy one or two adjacent sentences exactly"
        around = text[max(0, found["span"][0] - window):found["span"][1] + window]
        if n in relaxed:
            if not (named[a].search(around) or named[b].search(around)):
                return f"the text around the quote in chapter {n} names neither {a} nor {b}"
        elif not (pa and pb and pa.search(around) and pb.search(around)):
            return f"the text around the quote in chapter {n} does not name both {a} and {b}"
        return None

    def ask(shown, relaxed):
        same_type = kb.entities[a]["type"] == kb.entities[b]["type"]
        try:
            return cached_llm(workdir, "reveal", REVEAL_PROMPT.format(
                type=kb.entities[a]["type"] if same_type else "person or thing", a=a, b=b,
                passages="\n".join(f"- ch{p['chapter']}: \"{p['text']}\"" for p in shown)), check=lambda r: problem(r, relaxed))
        except LLMError:
            return {"chapter": None}

    reply = ask(passages, set()) if passages else {"chapter": None}
    if reply.get("chapter") is None:
        shown = fact_passages(workdir, kb, by_entity, named, a, b)
        reply = ask(shown, {p["chapter"] for p in shown}) if shown else reply
    n = reply.get("chapter")
    if n is not None and not (variant and variant["chapter"] < n):
        return {"chapter": n, "quote": str(reply.get("quote") or ""), "basis": "quote"}
    return variant or {"chapter": None, "quote": "", "basis": "unverified"}


def decide(workdir, kb, by_entity, attached, key, info):
    if info["rules"] == ["resemblance"]:
        a, b = info.get("subject", key)
        return suspect_pair(workdir, kb, by_entity, a, b, info)
    return decide_pair(workdir, kb, by_entity, attached, key[0], key[1], info)


def cmd_resolve(args):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir, merges=False, filled=())
    by_entity = {}
    for f in kb.facts:
        by_entity.setdefault(f["entity"], []).append(f)
    pairs = candidate_pairs(workdir, kb, by_entity, max(kb.synopses, default=0))
    attached = name_chapters(workdir, kb)
    path = workdir / "merges.json"
    todo = sorted(pairs, key=lambda k: (kb.entities[k[0]]["type"], k))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        decisions = list(pool.map(lambda k: decide(workdir, kb, by_entity, attached, k, pairs[k]), todo))
        settled = {n for d in decisions if d["same"] and (d.get("revealed") or {}).get("basis") != "unverified"
                   for n in (d["a"], d["b"])}
        found = identify_descriptors(workdir, kb, by_entity, hedged_identities(kb, by_entity), settled, pool)
    decisions += [pair for pair in (i.pair() for i in found) if pair]
    write_json(path, {"pairs": decisions})
    for d in decisions:
        verdict = f"ACCEPT -> {d['canonical']}" if d["same"] else f"POSSIBLY -> {d['b']}" if d.get("possibly") else "REJECT"
        print(f"{verdict:<34} [{d['type']}] {d['a']} <> {d['b']} ({d.get('source')}; {'; '.join(d.get('rules', []))}): {d['reason']}")
    kb = load_states(workdir)
    write_derived(workdir, kb)
    print(f"{len(pairs)} candidate pairs, {sum(d['same'] for d in decisions)} merges; "
          f"{len(kb.entities)} entities after merging")
