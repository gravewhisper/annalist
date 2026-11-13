import math
import re
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .corpus import stems
from .files import read_json, state_paths
from .llm import cached_llm, LLMError
from .names import FUNCTION_WORDS, is_stub, LEADING_WORDS, name_key, name_pattern, name_words, NameIndex, names_of, ROLE_WORDS, short_names
from .text import chapter_text, locate_quote, text_window


BASES = ("explicit", "implied", "none")


@dataclass(frozen=True)
class Identification:
    descriptor: str
    candidates: tuple
    basis: str = "none"
    candidate: str = ""
    chapter: int | None = None
    quote: str = ""
    reason: str = ""

    def pair(self):
        if self.basis == "none":
            return None
        explicit = self.basis == "explicit"
        found = {"chapter": self.chapter, "quote": self.quote}
        record = {"a": self.descriptor, "b": self.candidate, "type": "character", "rules": [f"descriptor-identity: {self.basis}"],
                  "candidates": list(self.candidates), "same": explicit, "canonical": self.candidate if explicit else "",
                  "reason": self.reason, "source": "llm"}
        return {**record, "revealed": {**found, "basis": "quote"}} if explicit else {**record, "possibly": found}


IDENTIFY_PROMPT = """A wiki built from a novel has an entry for a character known only by a description, "{name}". The wiki shows each chapter's page only with what a reader knows by that chapter, so it must not name this character before the novel lets a reader know who it is.

THE DESCRIBED CHARACTER
{card}

NAMED CHARACTERS WHO MAY BE THE SAME PERSON
{candidates}

PASSAGES FROM THE NOVEL, in chapter order
{passages}

Decide whether the novel identifies the described character as one of the named characters, and from which chapter. The named character must be the very same single individual as the described character. A relative, a group or couple that includes the named character, a servant, an associate, or someone merely mentioned with them is "none".
- "explicit": a passage states or plainly shows that the described character is that named character.
- "implied": a passage suggests it, but the novel does not confirm it in these passages.
- "none": the passages do not identify the described character with any of them, or a reader could only connect them with hindsight.

Reply with one JSON object: {{"candidate": "the named character's name exactly as listed; empty for none", "basis": "explicit", "implied", or "none", "same_individual": true when the named character would be the described character in person, whether explicit or implied; false when they would only be a relative, a member of a group or couple with them, a servant, an associate, or someone mentioned with them, "chapter": the chapter number of the earliest passage that shows it, or null for none, "quote": "one or two sentences copied exactly from that passage that show it", "reason": "one sentence"}}
"""


def appearances(workdir, kb):
    seen = {}
    for path in state_paths(workdir):
        state = read_json(path, {})
        out = state["extraction"]
        named = [r.get("name") for r in out.get("entities") or [] if isinstance(r, dict)]
        named += [f.get("entity") for f in out.get("facts") or [] if isinstance(f, dict)]
        for name in named:
            holder = kb.resolve(str(name or ""))
            if holder:
                seen.setdefault(holder, set()).add(state["chapter"])
    return seen


PLAIN_WORDS = ROLE_WORDS | FUNCTION_WORDS | LEADING_WORDS


def stem(word):
    short = re.sub(r"(?:ed|ing|s)$", "", word)
    if len(short) >= 4:
        return short
    return word[:-1] if word.endswith("ed") and len(word) >= 5 else word


def anchor_pattern(kb, descriptor, people):
    taken = {w for p in people for n in names_of(kb.entities[p]) for w in name_words(n)}
    words = {w for n in names_of(kb.entities[descriptor]) for part in name_words(n) for w in part.split("-")}
    roots = sorted({stem(w) for w in words if len(w) >= 4 and w not in PLAIN_WORDS and w not in taken})
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, roots)) + r")\w*", re.I) if roots else None


def role_pattern(kb, descriptor):
    roles = sorted({w for n in names_of(kb.entities[descriptor]) for w in name_words(n) if w in ROLE_WORDS})
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, roles)) + r")(?!\w)", re.I) if roles else None


def description(entity, facts):
    own = set() if is_stub(entity) else stems(" ".join(w for n in names_of(entity) for w in n.split() if w[:1].isupper()))
    docs = [(None, stems(" ".join(names_of(entity)) + " " + (entity["summary"] or "")), None)]
    return [(n, terms - own, f) for n, terms, f in docs + [(f["chapter"], stems(f["claim"]), f) for f in facts]]


class Descriptors:
    def __init__(self, workdir, kb, by_entity, hedged, cap=6, radius=300):
        self.workdir, self.kb, self.by_entity, self.hedged, self.cap, self.radius = workdir, kb, by_entity, hedged, cap, radius
        self.people = sorted(n for n, e in kb.entities.items() if e["type"] == "character" and not is_stub(e))
        self.seen = appearances(workdir, kb)
        characters = [n for n, e in kb.entities.items() if e["type"] == "character"]
        self.docs = {n: description(kb.entities[n], by_entity.get(n, [])) for n in characters}
        self.terms = {n: set().union(*(terms for _, terms, _ in docs)) for n, docs in self.docs.items()}
        df = Counter(t for terms in self.terms.values() for t in terms)
        self.idf = {t: math.log(len(characters) / k) for t, k in df.items()}
        index = NameIndex({p: names_of(kb.entities[p]) for p in self.people})
        self.mentions = {n: index.mentions(chapter_text(str(workdir), n)) for n in sorted(kb.synopses)}

    def near(self, descriptor, anchor, first):
        hits = {}
        if not anchor:
            return hits
        for n in [c for c in self.mentions if c >= first]:
            text, mentions = chapter_text(str(self.workdir), n), self.mentions[n]
            at = [pos for pos, _ in mentions]
            for m in anchor.finditer(text):
                for _, p in mentions[bisect_left(at, m.start() - self.radius):bisect_right(at, m.end() + self.radius)]:
                    if n not in hits.setdefault(p, {}):
                        hits[p][n] = text_window(text, m.start(), m.end(), self.radius)
        return hits

    def told(self, descriptor, person):
        mine, first = self.terms[descriptor], self.kb.entities[descriptor]["first_chapter"]
        scored = []
        for n, terms, f in self.docs[person]:
            shared = mine & terms
            if len(shared) >= 2 and (n is None or n >= first):
                scored.append((sum(self.idf[t] for t in shared), len(shared), f))
        return sorted(scored, key=lambda x: -x[0])

    def candidates(self, descriptor, near):
        mine = self.seen.get(descriptor, set())
        score = {p: len(self.seen.get(p, set()) & mine) + len(near.get(p, {})) for p in self.people}
        hedged = [p for p in self.hedged.get(descriptor, []) if p in score]
        alike = {p: max(told) for p in self.people if (told := [s for s, k, _ in self.told(descriptor, p) if k >= 3])}
        described = sorted(alike, key=lambda p: (-alike[p], p))[:self.cap // 2]
        ranked = sorted((p for p in self.people if score[p]), key=lambda p: (-score[p], p))
        return tuple(dict.fromkeys(hedged + described + ranked))[:self.cap]

    def told_passages(self, descriptor, person):
        found = []
        for _, _, f in self.told(descriptor, person):
            if f is None:
                continue
            text = chapter_text(str(self.workdir), f["chapter"])
            span = next((s["span"] for q in f["quotes"] if (s := locate_quote(text, q))["ok"] and s["span"]), None)
            if span:
                found.append((f["chapter"], text_window(text, span[0], span[1], self.radius)))
            if len(found) == 2:
                break
        return found

    def scenes(self, descriptor, anchor):
        found = []
        for n in sorted(self.seen.get(descriptor, ()))[:3]:
            text = chapter_text(str(self.workdir), n)
            quotes = [q for f in self.by_entity.get(descriptor, []) if f["chapter"] == n for q in f["quotes"]]
            spans = (s["span"] for q in quotes if (s := locate_quote(text, q))["ok"] and s["span"])
            hits = ((m.start(), m.end()) for m in anchor.finditer(text)) if anchor else iter(())
            span = next(spans, None) or next(hits, None)
            if span:
                found.append((n, text_window(text, span[0], span[1], 2 * self.radius)))
        return found

    def passages(self, descriptor, anchor, candidates, near, limit=12):
        found = self.scenes(descriptor, anchor)
        for p in candidates:
            found += [h for h in self.told_passages(descriptor, p) if h not in found]
        for p in candidates:
            hits = sorted(near.get(p, {}).items())
            found += [h for h in dict.fromkeys(hits[:1] + hits[-1:]) if h[0] not in {n for n, _ in found}]
        return sorted(found[:limit])

    def card(self, name):
        e = self.kb.entities[name]
        facts = sorted(self.by_entity.get(name, []), key=lambda f: f["chapter"])[:6]
        lines = [f"Name: {e['name']}", f"Chapters: {e['first_chapter']} to {e['last_chapter']}", f"Summary: {e['summary'] or 'none'}"]
        return "\n".join(lines + [f"- ch{f['chapter']}: {f['claim']}" for f in facts])

    def identify(self, descriptor):
        anchor = anchor_pattern(self.kb, descriptor, self.people)
        role = anchor is None
        first = 1 if role else self.kb.entities[descriptor]["first_chapter"]
        anchor = role_pattern(self.kb, descriptor) if role else anchor
        near = self.near(descriptor, anchor, first)
        candidates = self.candidates(descriptor, near)
        if not candidates:
            return Identification(descriptor, candidates)
        passages = self.passages(descriptor, anchor, candidates, near)
        listed = "\n".join(f"- {p}" + (f" (also {', '.join(self.kb.entities[p]['aliases'])})" if self.kb.entities[p]["aliases"] else "")
                           + f": {self.kb.entities[p]['summary'] or 'no summary'}" for p in candidates)
        by_key = {name_key(p): p for p in candidates}

        def problem(reply):
            basis = reply.get("basis")
            if basis not in BASES:
                return f"basis must be one of {', '.join(BASES)}"
            if basis == "none":
                return None
            if not isinstance(reply.get("same_individual"), bool):
                return "same_individual must be true or false"
            if not reply["same_individual"]:
                return None
            candidate = by_key.get(name_key(reply.get("candidate") or ""))
            if not candidate:
                return f"candidate {reply.get('candidate')!r} is not one of the named characters listed"
            n = reply.get("chapter")
            if not isinstance(n, int) or n not in self.kb.synopses or n < first:
                return f"chapter {n!r} is not a chapter from {first} on"
            text = chapter_text(str(self.workdir), n)
            found = locate_quote(text, str(reply.get("quote") or ""))
            if not (found["ok"] and found["span"]):
                return f"the quote is not one contiguous span of chapter {n}; copy one or two adjacent sentences exactly"
            around = text[max(0, found["span"][0] - 1000):found["span"][1] + 1000]
            if not name_pattern(names_of(self.kb.entities[candidate]) + short_names(self.kb, candidate)).search(around):
                return f"the text around the quote in chapter {n} does not name {candidate}"
            return None

        try:
            reply = cached_llm(self.workdir, "identify", IDENTIFY_PROMPT.format(
                name=descriptor, card=self.card(descriptor), candidates=listed,
                passages="\n".join(f"- ch{n}: \"{text}\"" for n, text in passages) or "(none)"), check=problem)
        except LLMError:
            return Identification(descriptor, candidates)
        if reply["basis"] == "none" or not reply["same_individual"]:
            return Identification(descriptor, candidates)
        return Identification(descriptor, candidates, reply["basis"], by_key[name_key(reply["candidate"])], reply["chapter"],
                              str(reply["quote"]), str(reply.get("reason") or "").strip())


def identify_descriptors(workdir, kb, by_entity, hedged, settled, pool):
    descriptors = sorted(n for n, e in kb.entities.items() if e["type"] == "character" and is_stub(e) and n not in settled)
    finder = Descriptors(workdir, kb, by_entity, hedged)
    return list(pool.map(finder.identify, descriptors))
