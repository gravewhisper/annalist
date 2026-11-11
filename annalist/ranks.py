import re

from .names import function_word_name, names_of
from .text import chapter_text, sentence_of, text_window


NUMBER = r"\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
ORDINAL = r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d+(?:st|nd|rd|th)"
NAME = r"[A-Z][\w'’-]*(?:\s+(?:of\s+)?[A-Z][\w'’-]*){0,2}"


def rank_form(word):
    w = re.escape(word)
    return rf"(?i:(?<!\w){w}s?\s+(?:{NUMBER})(?!\w)|(?<!\w)(?:{ORDINAL})\s+{w}(?!\w))"


def stated_steps(kb, spec, word):
    form = rank_form(word)
    of_rank = re.compile(rf"{form}(?:\s+\w+)?\s+of$")
    claims = [f["claim"] for f in kb.facts if re.search(form, f["claim"])]
    found = {}
    for k, e in sorted(kb.entities.items()):
        if e["type"] != spec["group_type"]:
            continue
        named = "|".join(re.escape(n) for n in sorted(names_of(e), key=len, reverse=True))
        step = re.compile(rf"(?<!\w)(?:{named})(?:\s*[,:(]\s*|\s+(?:is|was|becomes|became)\s+)(?:(?:a|an|the)\s+)?{form}"
                          rf"|{form}\s*[:,]?\s+(?:the\s+)?(?:{named})(?![\w'’])")
        group = re.compile(rf"{form}\s+of\s+(?:the\s+)?(?:{named})(?!\w)|(?<!\w)(?:{named})['’]s\s+{form}")
        steps = [c for c in claims if step.search(c)] + [f"{k} {r['type']} {r['target']}" for r in kb.relations
                                                         if r["source"] == k and of_rank.search(r["type"])]
        ranked = any(group.search(c) for c in claims) or any(r["target"] == k and of_rank.search(r["type"]) for r in kb.relations)
        if steps and not ranked:
            found[k] = steps[0]
    return found


def mention_patterns(word):
    w, number = re.escape(word), rf"(?i:{NUMBER})"
    return (re.compile(rf"(?i:(?<!\w){w})\s+{number}\s*[:,]?\s+(?:the\s+|a\s+)?(?P<name>{NAME})"),
            re.compile(rf"(?<![\w'’])(?P<name>{NAME})(?:,\s*|\s*\()(?:a\s+|the\s+)?(?i:{w})\s+{number}(?!\w)"))


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
            if not function_word_name(m["name"]):
                found.append({"chapter": n, "name": m["name"], "form": " ".join(m.group(0).split()),
                              "quote": rank_quote(text, m.start(), m.end())})
    return found
