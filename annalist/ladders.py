from pathlib import Path

from .book import load_book
from .files import log, read_json, write_json
from .llm import cached_llm
from .names import name_key, name_pattern, names_of
from .state import load_states, write_derived
from .text import check_quote, verified_quotes


RANKS = ("number", "order")
DIRECTIONS = ("ascending", "descending")


LADDER_SPEC_PROMPT = """A reference wiki is being built from a novel. An earlier step described the novel's power system and the kinds of power-system entries the wiki keeps:

POWER SYSTEM: {power_system}

POWER TYPES (type: description):
{types}

Decide whether the novel has a power ladder: named groups that are each a ranked series of steps, where the groups are entries of one power type above and the steps are entries of another (for example schools with circles, or guilds with grades).

Reply with one JSON object:
{{"ladder": {{"group_type": "the power type of the groups", "step_type": "the power type of the ranked steps", "rank": "number when the novel numbers the steps, order when it only names them in sequence", "direction": "ascending when a higher number is stronger, descending when a lower number is stronger", "note": "one sentence on how the steps rank within a group"}}}}
or {{"ladder": null}} when no two of the power types form such a ladder. group_type and step_type are two different types from the list above, written exactly as listed.
"""


def ladder_problems(reply, power_types):
    if "ladder" not in reply:
        return 'reply has no "ladder" key.'
    ladder = reply["ladder"]
    if ladder is None:
        return None
    if not isinstance(ladder, dict):
        return "ladder must be an object or null."
    problems = [f'{key} "{ladder.get(key)}" is not one of the power types {", ".join(power_types)}.'
                for key in ("group_type", "step_type") if name_key(ladder.get(key) or "") not in power_types]
    if name_key(ladder.get("group_type") or "") == name_key(ladder.get("step_type") or ""):
        problems.append("group_type and step_type must be two different power types.")
    if ladder.get("rank") not in RANKS:
        problems.append(f"rank must be one of {', '.join(RANKS)}, not {ladder.get('rank')!r}.")
    if ladder.get("rank") == "number" and ladder.get("direction") not in DIRECTIONS:
        problems.append(f"direction must be one of {', '.join(DIRECTIONS)}, not {ladder.get('direction')!r}.")
    return " ".join(problems) or None


def ladder_spec(raw):
    return {"group_type": name_key(raw["group_type"]), "step_type": name_key(raw["step_type"]), "rank": raw["rank"],
            "direction": raw["direction"] if raw["rank"] == "number" else "ascending", "note": str(raw.get("note") or "").strip()}


def ladder_needed(book):
    return "ladder" not in book or ladder_problems({"ladder": book["ladder"]}, book.get("power_types") or {}) is not None


def generate_ladder(workdir):
    path = Path(workdir) / "book.json"
    book = read_json(path, {})
    types = book.get("power_types") or {}
    spec = None
    if len(types) >= 2:
        prompt = LADDER_SPEC_PROMPT.format(power_system=book.get("power_system") or "(none described)",
                                           types="\n".join(f"- {t}: {d}" for t, d in types.items()))
        raw = cached_llm(workdir, "ladder-spec", prompt, check=lambda r: ladder_problems(r, types))["ladder"]
        spec = ladder_spec(raw) if raw else None
    write_json(path, {**book, "ladder": spec})


LADDERS_PROMPT = """You are building the power ladder pages of a reference wiki for a novel. In this novel each {group} is a ranked series of {step} entries. {note}

{group_heading} ENTRIES (name: summary):
{groups}

{step_heading} ENTRIES (name: summary):
{steps}

EVIDENCE (chapter | what the wiki records | quote from that chapter):
{evidence}

Reply with one JSON object:
{{"ladders": [{{"group": "the {group}'s name", "steps": [{{"entry": "a {step} entry's exact name", "rank": 1, "chapter": 12, "quote": "the quote of the evidence line"}}]}}]}}
Rules: list every {group} the evidence places at least one {step} in. "group" is the exact name of a listed {group} entry when one is that {group}, else the name the novel gives it. "entry" is the exact name of a listed {step} entry. {rank_rule} "chapter" and "quote" copy the chapter and quote of the earliest evidence line that places the {step} in that {group}. Leave out a {step} the evidence does not place in a {group}, and never guess a rank.
"""


RANK_RULES = {"number": '"rank" is the number the novel gives the {step} within its {group}.',
              "order": '"rank" is the {step}\'s position in its {group} counted from the weakest, starting at 1.'}


def entry_lines(kb, etype):
    return "\n".join(f"- {k}: {e['summary']}" for k, e in sorted(kb.entities.items()) if e["type"] == etype) or "(none)"


def first_verified(workdir, row):
    return verified_quotes(workdir, row["chapter"], row["quotes"])["quotes"][:1]


def evidence_lines(workdir, kb, spec):
    members = {k for k, e in kb.entities.items() if e["type"] in (spec["group_type"], spec["step_type"])}
    named = name_pattern([n for k in members for n in names_of(kb.entities[k])] + [spec["group_type"], spec["step_type"]])
    rows = []
    for f in kb.facts:
        if f["entity"] in members or named.search(f["claim"]):
            rows += [(f["chapter"], f"{f['entity']}: {f['claim']}", q) for q in first_verified(workdir, f)]
    for r in kb.relations:
        if r["source"] in members or r["target"] in members:
            rows += [(r["chapter"], f"{r['source']} {r['type']} {r['target']}", q) for q in first_verified(workdir, r)]
    for name, profile in read_json(Path(workdir) / "profiles.json", {"characters": {}})["characters"].items():
        for field, observations in profile.get("extra", {}).items():
            rows += [(o["chapter"], f"{name} {field}: {o['value']}", o["quotes"][0]) for o in observations
                     if o.get("quote_ok") and o["quotes"] and named.search(o["value"])]
    return [f'- ch{c} | {text} | "{quote}"' for c, text, quote in sorted(set(rows))]


def ladders_prompt(workdir, kb, spec):
    words = {"group": spec["group_type"], "step": spec["step_type"]}
    return LADDERS_PROMPT.format(**words, note=spec["note"], group_heading=spec["group_type"].upper(), step_heading=spec["step_type"].upper(),
                                 groups=entry_lines(kb, spec["group_type"]), steps=entry_lines(kb, spec["step_type"]),
                                 evidence="\n".join(evidence_lines(workdir, kb, spec)) or "(none)",
                                 rank_rule=RANK_RULES[spec["rank"]].format(**words))


def placed_step(workdir, kb, spec, raw, last):
    if not isinstance(raw, dict):
        return None
    key = kb.resolve(str(raw.get("entry") or "").strip(), spec["step_type"])
    try:
        rank, chapter = int(raw.get("rank")), int(raw.get("chapter"))
    except (TypeError, ValueError):
        return None
    quote = str(raw.get("quote") or "").strip()
    if not key or kb.entities[key]["type"] != spec["step_type"] or not 1 <= chapter <= last or not quote:
        return None
    if not check_quote(workdir, chapter, quote)["ok"]:
        return None
    return {"entry": key, "rank": rank, "chapter": chapter, "quote": quote}


def read_ladders(workdir, kb, spec, reply):
    last = max(kb.synopses, default=0)
    groups = {}
    for raw in reply["ladders"]:
        name = str(raw.get("group") or "").strip() if isinstance(raw, dict) else ""
        if not name:
            continue
        holder = kb.resolve(name, spec["group_type"])
        steps = groups.setdefault(holder if holder and kb.entities[holder]["type"] == spec["group_type"] else name, {})
        for step in filter(None, (placed_step(workdir, kb, spec, s, last) for s in raw.get("steps") or [])):
            if step["entry"] not in steps or step["chapter"] < steps[step["entry"]]["chapter"]:
                steps[step["entry"]] = step
    sign = 1 if spec["direction"] == "ascending" else -1
    ladders = [{"group": group, "group_type": spec["group_type"], "chapter": min(s["chapter"] for s in steps.values()),
                "steps": sorted(steps.values(), key=lambda s: (sign * s["rank"], s["entry"]))}
               for group, steps in groups.items() if steps]
    return sorted(ladders, key=lambda l: (l["chapter"], l["group"]))


def cmd_ladders(args):
    workdir = Path(args.workdir).resolve()
    spec = load_book(workdir)["ladder"]
    kb = load_states(workdir)
    ladders = []
    if spec:
        reply = cached_llm(workdir, "ladders", ladders_prompt(workdir, kb, spec),
                           check=lambda r: None if isinstance(r.get("ladders"), list) else "no ladders list")
        ladders = read_ladders(workdir, kb, spec, reply)
    write_json(workdir / "ladders.json", ladders)
    write_derived(workdir, kb)
    log(workdir, f"ladders: {len(ladders)} {spec['group_type'] if spec else 'group'} ladders with "
                 f"{sum(len(l['steps']) for l in ladders)} ranked steps")
