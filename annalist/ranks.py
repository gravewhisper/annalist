import re

from .names import names_of


NUMBER = r"\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
ORDINAL = r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d+(?:st|nd|rd|th)"


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
