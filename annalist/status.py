import re
from dataclasses import dataclass

from .names import name_pattern, names_of
from .state import timeline_role


DEATH_CUE = re.compile(r"\b(dies|died|dead|death|deceased|killed|murdered|slain|perished|drowned|executed|corpse|funeral|buried)\b", re.I)

@dataclass(frozen=True)
class Status:
    value: str
    chapter: int
    basis: str
    earlier: tuple = ()
    erased_death: int | None = None


def spoken_appearances(rows, resolve):
    seen = {}
    for row in rows:
        name = resolve(row.get("asserted_by") or "", row["chapter"])
        if name:
            seen.setdefault(name, set()).add((row["chapter"], row.get("timeline", "main")))
    return {name: sorted(s) for name, s in seen.items()}


def stated_appearances(rows, named=()):
    """The chapters whose stated facts and relations are about each name, before the first chapter where a fact about
    that name, a relation that ends at it, or a row whose wording names it speaks of a death. rows holds (name, row, end)
    for each fact (end "entity") and for each end of each relation ("source", "target"); named holds (name, pattern) for
    the characters a row's wording may name."""
    seen, cue = {}, {}
    for name, row, end in rows:
        if not name:
            continue
        wording = row.get("claim") or f"{row.get('type', '')} {row.get('detail', '')}"
        if DEATH_CUE.search(wording):
            for dead in ([name] if end != "source" else []) + [n for n, pattern in named if pattern.search(wording)]:
                cue[dead] = min(cue.get(dead, row["chapter"]), row["chapter"])
        if row.get("status", "stated") == "stated":
            seen.setdefault(name, set()).add((row["chapter"], row.get("timeline", "main")))
    return {name: sorted((c, tid) for c, tid in s if c < cue.get(name, c + 1)) for name, s in seen.items()}


def named_characters(entities):
    return [(n, name_pattern(names_of(e))) for n, e in entities.items() if e["type"] == "character"]


def kb_appearances(kb):
    return stated_appearances([(kb.resolve(f["entity"]), f, "entity") for f in kb.facts]
                              + [(kb.resolve(r[end]), r, end) for r in kb.relations for end in ("source", "target")], named_characters(kb.entities))


def current_status(observations, spoken, timelines, until, appeared=()):
    def current(tid):
        return timeline_role(timelines.get(tid or "main"), until) == "current"

    visible = [o for o in observations if o.get("shown", o["chapter"]) <= until and o.get("quote_ok")]
    shown = [o for o in visible if current(o.get("timeline"))]
    erased_death = next((o["chapter"] for o in reversed(visible) if o["value"] == "dead" and not current(o.get("timeline"))
                         and timelines.get(o.get("timeline"), {}).get("kind") == "run"), None)
    distinct = []
    for o in reversed(shown):
        if all(o["value"] != d["value"] for d in distinct):
            distinct.append(o)
    seen = [c for c, tid in spoken if c <= until and current(tid)]
    if shown and not (shown[-1]["value"] == "missing" and max(seen, default=0) > shown[-1]["chapter"]):
        return Status(shown[-1]["value"], shown[-1]["chapter"], "observed", tuple(distinct[1:]))
    past = next((o for o in reversed(visible) if o["value"] == "dead"
                 and timelines.get(o.get("timeline"), {}).get("kind") == "flashback"), None)
    if past and past["chapter"] >= max(seen, default=0):
        return Status("dead", past["chapter"], "past")
    if seen:
        return Status("alive", max(seen), "spoke", erased_death=erased_death)
    present = [c for c, tid in appeared if c <= until and current(tid)]
    if present:
        return Status("alive", max(present), "appeared", erased_death=erased_death)
    if erased_death:
        return Status("alive", erased_death, "erased_death", erased_death=erased_death)
    return None
