from dataclasses import dataclass

from .state import timeline_role

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


def current_status(observations, spoken, timelines, until):
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
    if erased_death:
        return Status("alive", erased_death, "erased_death", erased_death=erased_death)
    return None
