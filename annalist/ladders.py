from pathlib import Path

from .book import ladder_types, load_book
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

Decide whether the novel has a power ladder, and which of two shapes it has:
- grouped: named groups that are each their own ranked series of steps, where the groups are entries of one power type above and the steps are entries of another (for example schools with circles, or guilds with grades).
- shared: one ranked series of steps that every practitioner climbs, where the steps are entries of one power type above (for example cultivation realms), each often split into ordered sub-stages such as numbered layers or early, middle and late. Groups such as sects whose members all climb that one series do not make it grouped.

Reply with one JSON object:
{{"ladder": {{"shape": "grouped", "group_type": "the power type of the groups", "step_type": "the power type of the ranked steps", "rank": "number when the novel numbers the steps, order when it only names them in sequence", "direction": "ascending when a higher number is stronger, descending when a lower number is stronger", "note": "one sentence on how the steps rank within a group"}}}}
or {{"ladder": {{"shape": "shared", "step_type": "the power type of the ranked steps", "rank": "number or order, as above", "direction": "ascending or descending, as above", "note": "one sentence on how the steps rank and how each splits into sub-stages"}}}}
or {{"ladder": null}} when the power types form no such ladder. Every type is written exactly as listed above, and group_type and step_type are two different types.
"""


def ranked_problems(ladder):
    problems = []
    if ladder.get("rank") not in RANKS:
        problems.append(f"rank must be one of {', '.join(RANKS)}, not {ladder.get('rank')!r}.")
    if ladder.get("rank") == "number" and ladder.get("direction") not in DIRECTIONS:
        problems.append(f"direction must be one of {', '.join(DIRECTIONS)}, not {ladder.get('direction')!r}.")
    return problems


def typed_problems(ladder, keys, power_types):
    return [f'{key} "{ladder.get(key)}" is not one of the power types {", ".join(power_types)}.'
            for key in keys if name_key(ladder.get(key) or "") not in power_types]


def grouped_problems(ladder, power_types):
    problems = typed_problems(ladder, ("group_type", "step_type"), power_types)
    if name_key(ladder.get("group_type") or "") == name_key(ladder.get("step_type") or ""):
        problems.append("group_type and step_type must be two different power types.")
    return problems + ranked_problems(ladder)


def shared_problems(ladder, power_types):
    return typed_problems(ladder, ("step_type",), power_types) + ranked_problems(ladder)


def ranked_spec(raw):
    return {"rank": raw["rank"], "direction": raw["direction"] if raw["rank"] == "number" else "ascending",
            "note": str(raw.get("note") or "").strip()}


SHAPE_SPECS = {
    "grouped": (grouped_problems,
                lambda raw: {"group_type": name_key(raw["group_type"]), "step_type": name_key(raw["step_type"]), **ranked_spec(raw)}),
    "shared": (shared_problems, lambda raw: {"shape": "shared", "step_type": name_key(raw["step_type"]), **ranked_spec(raw)}),
}


def shape_of(ladder):
    return ladder.get("shape", "grouped")


def ladder_problems(reply, power_types):
    if "ladder" not in reply:
        return 'reply has no "ladder" key.'
    ladder = reply["ladder"]
    if ladder is None:
        return None
    if not isinstance(ladder, dict):
        return "ladder must be an object or null."
    if shape_of(ladder) not in SHAPE_SPECS:
        return f"shape must be one of {', '.join(SHAPE_SPECS)}, not {ladder.get('shape')!r}."
    return " ".join(SHAPE_SPECS[shape_of(ladder)][0](ladder, power_types)) or None


def ladder_spec(raw):
    return SHAPE_SPECS[shape_of(raw)][1](raw)


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


SHARED_LADDER_PROMPT = """You are building the power ladder page of a reference wiki for a novel. In this novel everyone climbs one shared ladder of {step} entries. {note}

{step_heading} ENTRIES (name: summary):
{steps}

EVIDENCE (chapter | what the wiki records | quote from that chapter):
{evidence}

Reply with one JSON object:
{{"steps": [{{"entry": "a {step} entry's exact name", "rank": 1, "chapter": 12, "quote": "the quote of the evidence line", "stages": [{{"name": "a sub-stage of this {step}", "chapter": 12, "quote": "the quote of the evidence line"}}]}}]}}
Rules: list every {step} the evidence places on the ladder. "entry" is the exact name of a listed {step} entry. {rank_rule} "chapter" and "quote" copy the chapter and quote of the earliest evidence line that places the {step} on the ladder. "stages" lists the sub-stages of that {step} the evidence names, such as a numbered layer or an early, middle or late stage, from the weakest to the strongest. A sub-stage's "name" is how the novel names it, without the {step}'s own name, and its "chapter" and "quote" copy the earliest evidence line that names it. Leave "stages" empty when the evidence names none, leave out a {step} the evidence does not place on the ladder, and never guess a rank or a sub-stage.
"""


SHARED_RANK_RULES = {"number": '"rank" is the number the novel gives the {step} on the ladder.',
                     "order": '"rank" is the {step}\'s position on the ladder counted from the weakest, starting at 1.'}


def entry_lines(kb, etype):
    return "\n".join(f"- {k}: {e['summary']}" for k, e in sorted(kb.entities.items()) if e["type"] == etype) or "(none)"


def first_verified(workdir, row):
    return verified_quotes(workdir, row["chapter"], row["quotes"])["quotes"][:1]


def evidence_lines(workdir, kb, spec):
    types = ladder_types(spec)
    members = {k for k, e in kb.entities.items() if e["type"] in types}
    named = name_pattern([n for k in members for n in names_of(kb.entities[k])] + list(types))
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


def grouped_prompt(workdir, kb, spec):
    words = {"group": spec["group_type"], "step": spec["step_type"]}
    return LADDERS_PROMPT.format(**words, note=spec["note"], group_heading=spec["group_type"].upper(), step_heading=spec["step_type"].upper(),
                                 groups=entry_lines(kb, spec["group_type"]), steps=entry_lines(kb, spec["step_type"]),
                                 evidence="\n".join(evidence_lines(workdir, kb, spec)) or "(none)",
                                 rank_rule=RANK_RULES[spec["rank"]].format(**words))


def shared_prompt(workdir, kb, spec):
    return SHARED_LADDER_PROMPT.format(step=spec["step_type"], note=spec["note"], step_heading=spec["step_type"].upper(),
                                       steps=entry_lines(kb, spec["step_type"]),
                                       evidence="\n".join(evidence_lines(workdir, kb, spec)) or "(none)",
                                       rank_rule=SHARED_RANK_RULES[spec["rank"]].format(step=spec["step_type"]))


def verified_place(workdir, raw, last):
    try:
        chapter = int(raw.get("chapter"))
    except (TypeError, ValueError):
        return None
    quote = str(raw.get("quote") or "").strip()
    if not 1 <= chapter <= last or not quote or not check_quote(workdir, chapter, quote)["ok"]:
        return None
    return {"chapter": chapter, "quote": quote}


def placed_step(workdir, kb, spec, raw, last):
    if not isinstance(raw, dict):
        return None
    key = kb.resolve(str(raw.get("entry") or "").strip(), spec["step_type"])
    try:
        rank = int(raw.get("rank"))
    except (TypeError, ValueError):
        return None
    if not key or kb.entities[key]["type"] != spec["step_type"]:
        return None
    place = verified_place(workdir, raw, last)
    return place and {"entry": key, "rank": rank, **place}


def ranked(steps, spec):
    sign = 1 if spec["direction"] == "ascending" else -1
    return sorted(steps, key=lambda s: (sign * s["rank"], s["entry"]))


def read_grouped(workdir, kb, spec, reply):
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
    ladders = [{"group": group, "group_type": spec["group_type"], "chapter": min(s["chapter"] for s in steps.values()),
                "steps": ranked(steps.values(), spec)}
               for group, steps in groups.items() if steps]
    return sorted(ladders, key=lambda l: (l["chapter"], l["group"]))


def placed_stages(workdir, raw, last):
    stages = {}
    for s in raw if isinstance(raw, list) else []:
        name = str(s.get("name") or "").strip() if isinstance(s, dict) else ""
        place = verified_place(workdir, s, last) if name else None
        if place and name_key(name) not in stages:
            stages[name_key(name)] = {"name": name, **place}
    return list(stages.values())


def read_shared(workdir, kb, spec, reply):
    last = max(kb.synopses, default=0)
    steps = {}
    for raw in reply["steps"]:
        step = placed_step(workdir, kb, spec, raw, last)
        if step and (step["entry"] not in steps or step["chapter"] < steps[step["entry"]]["chapter"]):
            steps[step["entry"]] = {**step, "stages": placed_stages(workdir, raw.get("stages"), last)}
    return [{"group": None, "group_type": None, "chapter": min(s["chapter"] for s in steps.values()),
             "steps": ranked(steps.values(), spec)}] if steps else []


def listed(key):
    return lambda r: None if isinstance(r.get(key), list) else f"no {key} list"


SHAPE_STAGES = {"grouped": (grouped_prompt, listed("ladders"), read_grouped),
                "shared": (shared_prompt, listed("steps"), read_shared)}


def cmd_ladders(args):
    workdir = Path(args.workdir).resolve()
    spec = load_book(workdir)["ladder"]
    kb = load_states(workdir)
    ladders = []
    if spec:
        prompt, check, read = SHAPE_STAGES[shape_of(spec)]
        reply = cached_llm(workdir, "ladders", prompt(workdir, kb, spec), check=check)
        ladders = read(workdir, kb, spec, reply)
    write_json(workdir / "ladders.json", ladders)
    write_derived(workdir, kb)
    log(workdir, f"ladders: {len(ladders)} {spec.get('group_type') or 'shared' if spec else 'group'} ladders with "
                 f"{sum(len(l['steps']) for l in ladders)} ranked steps")
