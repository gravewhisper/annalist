import copy
import re
from itertools import combinations
from pathlib import Path

from .book import ladder_types, load_book, rank_type
from .files import log, read_json, write_json
from .llm import cached_llm
from .names import function_word_name, name_key, name_pattern, names_of
from .ranks import group_key, rank_mentions, text_ladders
from .resolve import decide_pair, name_chapters, reveal_passages
from .state import load_states, write_derived
from .survey import unseen_names
from .template import book_types
from .text import check_quote, verified_quotes


RANKS = ("number", "order")
DIRECTIONS = ("ascending", "descending")


RANKED = re.compile(r"(?<![\w'’-])(?:[A-Za-z][\w'’-]*\s+\d+|\d+(?:st|nd|rd|th)|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
                    r"tenth|eleventh|twelfth|(?:thir|four|fif|six|seven|eigh|nine)teenth|twentieth)\b", re.I)


def unseen_ranks(texts, material):
    seen = " ".join(material.lower().split())
    terms = {" ".join(m.group(0).split()) for text in texts for m in RANKED.finditer(text)}
    return sorted(t for t in terms if not re.search(rf"(?<!\w){re.escape(t.lower())}(?!\w)", seen))


def unseen_terms(texts, material):
    return sorted(set(unseen_names(texts, material)) | set(unseen_ranks(texts, material)))


LADDER_SPEC_PROMPT = """A reference wiki is being built from a novel. An earlier step named the order that the novel's power types belong to (a power or magic system, or a social, military, or other order) and described each power type:

ORDER: {power_system}

POWER TYPES (type: description):
{types}

Decide whether the novel has a power ladder, and which of two shapes it has:
- grouped: named groups that are each their own ranked series of steps, where the groups are entries of one power type above and the steps are entries of another (for example schools with circles, or guilds with grades).
- shared: one ranked series of steps that every practitioner climbs, where the steps are entries of one power type above (for example cultivation realms), each often split into ordered sub-stages such as numbered layers or early, middle and late. Groups such as sects whose members all climb that one series do not make it grouped.

Reply with one JSON object:
{{"ladder": {{"shape": "grouped", "group_type": "the power type of the groups", "step_type": "the power type of the ranked steps", "rank": "number when the novel numbers the steps, order when it only names them in sequence", "direction": "ascending when a higher number is stronger, descending when a lower number is stronger", "note": "one sentence on how the steps rank within a group"}}}}
or {{"ladder": {{"shape": "shared", "step_type": "the power type of the ranked steps", "rank": "number or order, as above", "direction": "ascending or descending, as above", "note": "one sentence on how the steps rank and how each splits into sub-stages"}}}}
or {{"ladder": null}} when the power types form no such ladder. Every type is written exactly as listed above, and group_type and step_type are two different types. The steps are the ranks themselves: when a power type holds the ranks, step_type is that type, never an item type whose entries are named after or made for a rank, such as a brew or a manual for each rank.
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


def ladder_problems(reply, power_types, material=None, rank=None):
    if "ladder" not in reply:
        return 'reply has no "ladder" key.'
    ladder = reply["ladder"]
    if ladder is None:
        return None
    if not isinstance(ladder, dict):
        return "ladder must be an object or null."
    if shape_of(ladder) not in SHAPE_SPECS:
        return f"shape must be one of {', '.join(SHAPE_SPECS)}, not {ladder.get('shape')!r}."
    problems = SHAPE_SPECS[shape_of(ladder)][0](ladder, power_types)
    if rank and name_key(ladder.get("step_type") or "") != rank:
        problems.append(f'step_type must be "{rank}", the type of the ranks themselves; an item named after a rank links to that rank '
                        f'and is not a step.')
    terms = unseen_terms([str(ladder.get("note") or "")], material) if material is not None else []
    if terms:
        problems.append(f"the note names {', '.join(terms)}, which the order and power types above never mention; "
                        f"describe the ladder only from them, without a rank they do not name.")
    return " ".join(problems) or None


def ladder_spec(raw):
    return SHAPE_SPECS[shape_of(raw)][1](raw)


def ladder_needed(book):
    return "ladder" not in book or ladder_problems({"ladder": book["ladder"]}, book.get("power_types") or {}, rank=rank_type(book)) is not None


def generate_ladder(workdir):
    path = Path(workdir) / "book.json"
    book = read_json(path, {})
    types = book_types(book.get("power_types"))
    spec = None
    if len(types) >= 2:
        prompt = LADDER_SPEC_PROMPT.format(power_system=book.get("power_system") or "(none described)",
                                           types="\n".join(f"- {t}: {d['description']}" for t, d in types.items()))

        raw = cached_llm(workdir, "ladder-spec", prompt, check=lambda r: ladder_problems(r, types, prompt, rank_type(book)))["ladder"]
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
Rules: list every {group} the evidence places at least one {step} in. "group" is the exact name of a listed {group} entry when one is that {group}, else the name the novel gives it. "entry" is the exact name of a listed {step} entry.{unlisted_rule} {rank_rule} "chapter" and "quote" copy the chapter and quote of the earliest evidence line that places the {step} in that {group}. Leave out a {step} the evidence does not place in a {group}, and never guess a rank.
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
Rules: list every {step} the evidence places on the ladder. "entry" is the exact name of a listed {step} entry.{unlisted_rule} {rank_rule} "chapter" and "quote" copy the chapter and quote of the earliest evidence line that places the {step} on the ladder. "stages" lists the sub-stages of that {step} the evidence names, such as a numbered layer or an early, middle or late stage, from the weakest to the strongest. A sub-stage's "name" is how the novel names it, without the {step}'s own name, and its "chapter" and "quote" copy the earliest evidence line that names it. Leave "stages" empty when the evidence names none, leave out a {step} the evidence does not place on the ladder, and never guess a rank or a sub-stage.
"""


UNLISTED_RULES = {"grouped": ' When the evidence names a {step} that no listed {step} entry holds, such as the first {step} of a {group} named after '
                            'it, "entry" is its name as the novel writes it, and its quote names it.',
                  "shared": ' When the evidence names a {step} that no listed {step} entry holds, "entry" is its name as the novel writes it, '
                            'and its quote names it.'}


SHARED_RANK_RULES = {"number": '"rank" is the number the novel gives the {step} on the ladder.',
                     "order": '"rank" is the {step}\'s position on the ladder counted from the weakest, starting at 1.'}


def entry_lines(kb, etype):
    return "\n".join(f"- {k}: {e['summary']}" for k, e in sorted(kb.entities.items()) if e["type"] == etype) or "(none)"


def first_verified(workdir, row):
    return verified_quotes(workdir, row["chapter"], row["quotes"])["quotes"][:1]


def evidence_lines(workdir, kb, spec, word):
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
    listed = {}
    for m in rank_mentions(workdir, sorted(kb.synopses), word) if word else []:
        listed.setdefault((m["chapter"], m["quote"]), []).append(m["form"])
    rows += [(c, f"names {'; '.join(dict.fromkeys(forms))}", quote) for (c, quote), forms in listed.items()]
    return [f'- ch{c} | {text} | "{quote}"' for c, text, quote in sorted(set(rows))]


def unlisted_rule(spec, word):
    return UNLISTED_RULES[shape_of(spec)].format(group=spec.get("group_type"), step=spec["step_type"]) if word else ""


def grouped_prompt(workdir, kb, spec, word):
    words = {"group": spec["group_type"], "step": spec["step_type"]}
    return LADDERS_PROMPT.format(**words, note=spec["note"], group_heading=spec["group_type"].upper(), step_heading=spec["step_type"].upper(),
                                 groups=entry_lines(kb, spec["group_type"]), steps=entry_lines(kb, spec["step_type"]),
                                 evidence="\n".join(evidence_lines(workdir, kb, spec, word)) or "(none)",
                                 unlisted_rule=unlisted_rule(spec, word), rank_rule=RANK_RULES[spec["rank"]].format(**words))


def shared_prompt(workdir, kb, spec, word):
    return SHARED_LADDER_PROMPT.format(step=spec["step_type"], note=spec["note"], step_heading=spec["step_type"].upper(),
                                       steps=entry_lines(kb, spec["step_type"]),
                                       evidence="\n".join(evidence_lines(workdir, kb, spec, word)) or "(none)",
                                       unlisted_rule=unlisted_rule(spec, word),
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


def names_step(quote, name, word):
    return all(re.search(rf"(?<!\w){re.escape(w)}", quote, re.I) for w in (name, word))


def placed_step(workdir, kb, spec, raw, last, word):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("entry") or "").strip()
    key = kb.resolve(name, spec["step_type"])
    try:
        rank = int(raw.get("rank"))
    except (TypeError, ValueError):
        return None
    listed = key is not None and kb.entities[key]["type"] == spec["step_type"]
    unlisted = (key is None and word and name and not function_word_name(name) and not kb.bare_rank(name))
    place = verified_place(workdir, raw, last) if listed or unlisted else None
    if place and listed:
        return {"entry": key, "rank": rank, **place}
    if place and names_step(place["quote"], name, word):
        return {"entry": name, "rank": rank, **place, "new": True}
    return None


def ranked(steps, spec):
    sign = 1 if spec["direction"] == "ascending" else -1
    return sorted(steps, key=lambda s: (sign * s["rank"], s["entry"]))


def read_grouped(workdir, kb, spec, reply, word):
    last = max(kb.synopses, default=0)
    groups = {}
    for raw in reply["ladders"]:
        name = str(raw.get("group") or "").strip() if isinstance(raw, dict) else ""
        if not name:
            continue
        steps = groups.setdefault(group_key(kb, name) or name, {})
        for step in filter(None, (placed_step(workdir, kb, spec, s, last, word) for s in raw.get("steps") or [])):
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


def read_shared(workdir, kb, spec, reply, word):
    last = max(kb.synopses, default=0)
    steps = {}
    for raw in reply["steps"]:
        step = placed_step(workdir, kb, spec, raw, last, word)
        if step and (step["entry"] not in steps or step["chapter"] < steps[step["entry"]]["chapter"]):
            steps[step["entry"]] = {**step, "stages": placed_stages(workdir, raw.get("stages"), last)}
    return [{"group": None, "group_type": None, "chapter": min(s["chapter"] for s in steps.values()),
             "steps": ranked(steps.values(), spec)}] if steps else []


def listed(key):
    return lambda r, material: None if isinstance(r.get(key), list) else f"no {key} list"


def stage_problems(reply, material):
    if not isinstance(reply.get("steps"), list):
        return "no steps list"
    names = [str(s.get("name") or "") for step in reply["steps"] if isinstance(step, dict)
             for s in step.get("stages") or [] if isinstance(s, dict)]
    terms = unseen_terms(names, material)
    return (f"the sub-stage names use {', '.join(terms)}, which the entries and evidence above never show; "
            f"name a sub-stage only as the evidence names it.") if terms else None


SHAPE_STAGES = {"grouped": (grouped_prompt, listed("ladders"), read_grouped),
                "shared": (shared_prompt, stage_problems, read_shared)}


def same_rank_pairs(kb, ladders):
    pairs = {}
    for ladder in ladders:
        held = {}
        for s in ladder["steps"]:
            key = kb.resolve(s["entry"], kb.step_type)
            if key and kb.entities[key]["type"] == kb.step_type:
                held.setdefault(s["rank"], {}).setdefault(key, s["chapter"])
        for rank, chapters in held.items():
            for a, b in combinations(sorted(chapters), 2):
                pairs[(a, b)] = {"group": ladder["group"], "rank": rank, "chapter": max(chapters[a], chapters[b])}
    return pairs


def judged_same_ranks(workdir, kb, ladders):
    placed = copy.deepcopy(kb)
    placed.apply_ladders(ladders)
    pairs = same_rank_pairs(placed, [l for l in ladders if l["group"]])
    if not pairs:
        return ladders
    by_entity, attached, last = {}, name_chapters(workdir, placed), max(placed.synopses, default=0)
    for f in placed.facts:
        by_entity.setdefault(f["entity"], []).append(f)
    same = {}
    for (a, b), pair in sorted(pairs.items()):
        info = {"rules": ["same-rank"], "evidence": reveal_passages(workdir, placed, a, b, last)[0]}
        d = {**decide_pair(workdir, placed, by_entity, attached, a, b, info), "rank": pair["rank"]}
        if d["same"] and d["revealed"]["chapter"] is not None:
            d["revealed"] = {**d["revealed"], "chapter": max(d["revealed"]["chapter"], pair["chapter"])}
        same.setdefault(pair["group"], []).append(d)
    return [{**l, "same": same[l["group"]]} if l["group"] in same else l for l in ladders]


def cmd_ladders(args):
    workdir = Path(args.workdir).resolve()
    book = load_book(workdir)
    spec = book["ladder"]
    word = book["rank_word"] if spec and spec["step_type"] == rank_type(book) else ""
    kb = load_states(workdir)
    ladders = []
    if spec:
        prompt, check, read = SHAPE_STAGES[shape_of(spec)]
        material = prompt(workdir, kb, spec, word)
        reply = cached_llm(workdir, "ladders", material, check=lambda r: check(r, material))
        ladders = read(workdir, kb, spec, reply, word)
        if word and shape_of(spec) == "grouped":
            ladders = text_ladders(workdir, kb, ladders, word)
        ladders = judged_same_ranks(workdir, kb, ladders)
    write_json(workdir / "ladders.json", ladders)
    write_derived(workdir, kb)
    log(workdir, f"ladders: {len(ladders)} {spec.get('group_type') or 'shared' if spec else 'group'} ladders with "
                 f"{sum(len(l['steps']) for l in ladders)} ranked steps")
