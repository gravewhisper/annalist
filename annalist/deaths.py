import re
from concurrent.futures import ThreadPoolExecutor

from .families import wording_key
from .llm import cached_llm, LLMError
from .names import name_pattern, names_of, short_names
from .state import timeline_line, timeline_role
from .status import spoken_appearances
from .text import chapter_text, text_window, verified_quotes


DEATH_PROMPT = """Did the character "{name}" die in chapter {chapter} of a novel, or was their death revealed there? Use ONLY the facts and passages below, all from chapters {lo} to {hi}. Never use outside knowledge.

FACTS (chapter, entity the fact is about with its other names, claim, quotes):
{facts}

PASSAGES (chapter: verbatim text):
{passages}

Reply with one JSON object: {{"died": true or false, "missing": true or false, "chapter": the chapter where the death or disappearance happens or is revealed, "circumstances": "two or three sentences in the voice of a fan wiki telling how the death came about, in order: what was done to them leading up to it (objects or powers used on them, who restrained or trapped them), then the fatal blow and by whose hand, and whether it happens on the page or is reported", "quotes": ["one to three verbatim excerpts from the passages or fact quotes of that chapter, each one contiguous span of at most 300 characters"], "lives_on": true or false, "lives_on_quotes": ["when lives_on is true, one or two verbatim excerpts from the passages showing {name} alive in the story after that death"]}}
Rules: died is true only if the death is an event of the story's present in these chapters: it happens on the page, or the body is found there. A death in the backstory (years before, told by a character or recalled), a character only believed dead, a habit or ability (dying again and again, coming back each time), or someone else's death, is false. lives_on is true only when died is true and the story goes on with {name} under this name as a living person after that death with no revival: the one who died was the body's previous owner or occupant, a former self, or a past life, and the {name} the story follows lives in their place. missing is true only when died is false and in that chapter the character vanishes for good as far as the story tells: flees beyond reach, is lost, or is presumed dead with no body found; someone only out of sight for a while is not missing. Name every person and object the material shows taking part in the death, using the names the passages use; when an object has both a name and a catalogue number or code, give both. Write only about the story, never about the material or what it lacks.
"""


DEATH_TIMELINE_RULES = """
TIMELINES (id [kind]: label, chapters):
{registry}
Facts outside main carry their timeline id in brackets. Add "timeline": the id of the timeline the death happens in, such as a run of a time loop or a flashback; main when it holds across timelines.
"""


DEATH_WORDS = re.compile(r"\b(die|dies|died|dead|death|deaths|dying|kill|kills|killed|killing|murder|murders|murdered|murdering|suicide|corpse|body|"
                         r"euthanas\w*|perish\w*|slay|slays|slew|slain|executed|funeral|tombstone|grave|buried|burial|coffin|epitaph|mourn\w*)\b", re.I)


DEATH_RELATIONS = ("killed", "kills", "murdered", "murders", "executed", "executes", "slew", "slays")


STATUS_WORDS = (r"died|dead|death|corpse|kills|killed|murder\w*|slain|slew|alive|revived?|resurrect\w*|breathing|heartbeat|missing heart|healed|"
                r"stopped breathing|lifeless|perished")


STATUS_CUE = re.compile(STATUS_WORDS, re.I)


def volume_end(volumes, chapter, last):
    return next((v["to"] for v in volumes if v["from"] <= chapter <= v["to"]), last)


def death_candidates(kb, profiles, volumes, last):
    def standing(row):
        return timeline_role(kb.timelines.get(row.get("timeline", "main")), volume_end(volumes, row["chapter"], last)) == "current"

    def character(name):
        e = kb.entities.get(name)
        return e is not None and e["type"] == "character"

    rows = []
    for name, p in profiles.items():
        rows += [(name, o) for o in p["fields"].get("status", []) if o["value"] == "dead" and o.get("quote_ok")]
    named = [(n, name_pattern(names_of(e))) for n, e in kb.entities.items() if e["type"] == "character"]
    for f in kb.facts:
        if DEATH_WORDS.search(f["claim"]):
            rows += [(f["entity"], f)] + [(n, f) for n, pattern in named if n != f["entity"] and pattern.search(f["claim"])]
    rows += [(r["target"], r) for r in kb.relations if wording_key(r["type"]) in DEATH_RELATIONS and r.get("status") == "stated"]
    chapters = {}
    for name, row in rows:
        if character(name) and standing(row):
            chapters.setdefault(name, set()).add(row["chapter"])
    found = []
    for name, seen in chapters.items():
        last_asked = None
        for chapter in sorted(seen):
            if last_asked is None or chapter - last_asked > 1:
                found.append((name, chapter))
                last_asked = chapter
    return found


def lives_on_shown(workdir, window, quotes):
    quotes = [str(q).strip() for q in quotes or [] if str(q or "").strip()][:2]
    return any(verified_quotes(str(workdir), n, quotes)["quote_ok"] for n in window)


def death_entry(workdir, kb, name, chapter, lo, hi, radius=400):
    pattern = name_pattern(names_of(kb.entities[name]) + short_names(kb, name))
    window = range(max(lo, chapter - 1), min(hi, chapter + 1) + 1)
    facts = [f for f in kb.facts if f["chapter"] in window and (f["entity"] == name or pattern.search(f["claim"]))]
    passages = []
    for n in window:
        text = chapter_text(str(workdir), n)
        spans = sorted(pattern.finditer(text), key=lambda m: (not STATUS_CUE.search(text[max(0, m.start() - 150):m.end() + 150]), m.start()))
        if n != chapter:
            spans = [m for m in spans if STATUS_CUE.search(text[max(0, m.start() - 150):m.end() + 150])]
        kept = []
        for m in spans:
            if all(abs(m.start() - k.start()) > 2 * radius for k in kept) and len(kept) < (5 if n == chapter else 2):
                kept.append(m)
        kept.sort(key=lambda m: m.start())
        passages += [f"- ch{n}: {text_window(text, m.start(), m.end(), radius)}" for m in kept]
    prompt = DEATH_PROMPT.format(
        name=name, chapter=chapter, lo=window[0], hi=window[-1],
        facts="\n".join(f"- ch{f['chapter']}" + (f" [{f['timeline']}]" if f.get("timeline", "main") != "main" else "")
                        + f" [{' / '.join(names_of(kb.entities[f['entity']]))}]: {f['claim']}"
                        + "".join(f' | "{q}"' for q in f["quotes"]) for f in facts) or "(none)",
        passages="\n".join(passages) or "(none)")
    if len(kb.timelines) > 1:
        prompt += DEATH_TIMELINE_RULES.format(registry="\n".join(f"- {timeline_line(t)}" for t in kb.timelines.values()))
    reply = cached_llm(workdir, "death", prompt)
    value = "dead" if reply.get("died") is True else "missing" if reply.get("missing") is True else None
    if value is None:
        return None
    try:
        died_in = int(reply.get("chapter"))
    except (TypeError, ValueError):
        died_in = chapter
    if not lo <= died_in <= hi:
        return None
    if value == "dead" and reply.get("lives_on") is True and lives_on_shown(workdir, window, reply.get("lives_on_quotes")):
        value = "lives_on"
    quotes = [str(q).strip() for q in reply.get("quotes") or [] if str(q or "").strip()][:3]
    return {"name": name, "value": value, "chapter": died_in, "shown": window[-1], "circumstances": str(reply.get("circumstances") or "").strip(),
            **verified_quotes(str(workdir), died_in, quotes), "timeline": reply["timeline"] if reply.get("timeline") in kb.timelines else "main"}


REVIVAL_PROMPT = """The character "{name}" is recorded as having died in chapter {died} of a novel. The passages below come from that chapter and from later chapters where the character appears to speak or act. Use ONLY these passages. Never use outside knowledge.

PASSAGES (chapter: verbatim text):
{passages}

Decide whether {name} truly came back to life in the story's present after that death. A false report of the death followed by the character being alive counts as returned, dated to the chapter that shows them alive. These do not count: a spirit channeled or summoned by someone else, a corpse moved by another's power, a flashback or memory, a dream or vision, an impersonator, or someone merely speaking of {name}.

Reply with one JSON object: {{"returned": true or false, "chapter": the chapter number of the earliest passage that shows {name} alive after the death, or null when false, "quotes": ["one to three verbatim excerpts from that chapter's passage, each one contiguous span of at most 300 characters"], "reason": "one sentence"}}
"""


def appearance_windows(workdir, pattern, chapters, radius=400, per_chapter=2):
    lines = []
    for n in chapters:
        text = chapter_text(str(workdir), n)
        kept = []
        for m in pattern.finditer(text):
            if len(kept) < per_chapter and all(abs(m.start() - k.start()) > 2 * radius for k in kept):
                kept.append(m)
        lines += [f"- ch{n}: {text_window(text, m.start(), m.end(), radius)}" for m in kept]
    return lines


def revival_candidates(kb, profiles, deaths, last):
    def current(tid):
        return timeline_role(kb.timelines.get(tid or "main"), last) == "current"

    spoken = spoken_appearances(kb.facts + kb.relations, lambda name, _: kb.resolve(name))
    recorded = {}
    for name, p in profiles.items():
        recorded[name] = [o["chapter"] for o in p["fields"].get("status", []) if o["value"] == "dead" and o.get("quote_ok") and current(o.get("timeline"))]
    for d in deaths:
        if d["value"] == "dead" and d["quote_ok"] and current(d.get("timeline")) and d["name"] in recorded:
            recorded[d["name"]].append(d["chapter"])
    found = []
    for name, died in recorded.items():
        status = profiles[name]["fields"].get("status", [])
        for chapter in sorted(set(died), reverse=True):
            later = sorted({c for c, tid in spoken.get(name, []) if c > chapter and current(tid)})
            if later and not any(o["value"] in ("alive", "revived") and o["chapter"] > chapter for o in status):
                found.append((name, chapter, later))
                break
    return found


def revival_entry(workdir, kb, name, died, later, shown=5):
    pattern = name_pattern(names_of(kb.entities[name]) + short_names(kb, name))
    offered = list(dict.fromkeys(later[:shown] + later[-1:]))
    passages = appearance_windows(workdir, pattern, [died] + offered)

    def problem(reply):
        if reply.get("returned") is not True:
            return None
        n = reply.get("chapter")
        if n not in offered:
            return f"chapter {n!r} is not one of the later chapters shown: {offered}"
        quotes = [str(q).strip() for q in reply.get("quotes") or [] if str(q or "").strip()][:3]
        if not quotes or not verified_quotes(str(workdir), n, quotes)["quote_ok"]:
            return f"the quotes are not verbatim spans of chapter {n}"
        return None

    try:
        reply = cached_llm(workdir, "revival", REVIVAL_PROMPT.format(name=name, died=died, passages="\n".join(passages)), check=problem)
    except LLMError:
        return None
    if reply.get("returned") is not True:
        return None
    quotes = [str(q).strip() for q in reply["quotes"] if str(q or "").strip()][:3]
    return {"name": name, "value": "revived", "chapter": reply["chapter"], "shown": reply["chapter"],
            "circumstances": str(reply.get("reason") or "").strip(), **verified_quotes(str(workdir), reply["chapter"], quotes), "timeline": "main"}


def verified_revivals(workdir, kb, profiles, deaths, last, jobs=4):
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return [r for r in pool.map(lambda c: revival_entry(workdir, kb, *c), revival_candidates(kb, profiles, deaths, last)) if r]


def verified_deaths(workdir, kb, profiles, volumes, last, jobs=4):
    candidates = death_candidates(kb, profiles, volumes, last)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        entries = [d for d in pool.map(lambda c: death_entry(workdir, kb, c[0], c[1], 1, last), candidates) if d]
    deaths = {}
    for d in sorted(entries, key=lambda d: d["chapter"]):
        key = (d["name"], d["timeline"]) if d["value"] == "dead" else (d["name"], d["timeline"], d["value"], d["chapter"])
        first = deaths.setdefault(key, d)
        if first is not d and d["chapter"] > first["chapter"] and d["quote_ok"]:
            first.setdefault("later", []).append({k: d[k] for k in ("chapter", "shown", "circumstances", "quotes")})
    return sorted(deaths.values(), key=lambda d: (d["chapter"], d["name"]))
