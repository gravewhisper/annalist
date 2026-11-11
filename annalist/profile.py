import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import audit_items
from .book import load_book
from .corrections import joined_rows
from .deaths import STATUS_WORDS, verified_deaths, verified_revivals
from .evidence import add_evidence, class_pattern, stems
from .files import read_json, write_json
from .llm import cached_llm
from .names import name_key, name_pattern, names_of, short_names
from .state import load_states, timeline_line
from .template import CHARACTER_FIELDS, PROFILE_FIELDS, PROFILE_LISTS, STATUS_VALUES
from .text import chapter_text, locate_quote, text_window, verified_quotes, widen_to


PASSAGE_CUES = {
    "appearance": (r"\b(?:hair|eyes|face|features|wore|wearing|dressed|beard|mustache|skin|complexion|build|figure|"
                   r"handsome|beautiful|pretty|slim|thin|plump|stout|lanky|outline|appearance)\b", 12, "first"),
    "age": (r"years old|year-old|aged|his age|her age|in (?:his|her) (?:teens|twenties|thirties|forties|fifties|sixties)", 6, "first"),
    "birth": (r"birthday|was born|date of birth", 4, "first"),
    "height": (r"\btall\b|height|meters|metres|feet|inches|centimeters", 6, "first"),
    "marital": (r"married|marry|wife|husband|fianc[ée]e?|widow|widower|engaged|bachelor|spouse", 6, "first"),
    "status": (STATUS_WORDS, 10, "last"),
}


def cue_patterns(kb, book):
    patterns = {cue: (re.compile(regex, re.I), cap, order, 2 if cue == "appearance" else 1)
                for cue, (regex, cap, order) in PASSAGE_CUES.items()}
    power_names = [e["name"] for e in kb.entities.values() if e["type"] in book["power_types"]]
    words = [r"(?i:\b" + re.escape(w) + r"\w*)" for w in book["power_keywords"]]
    if power_names or words:
        names = [name_pattern(power_names).pattern] if power_names else []
        patterns["power"] = (re.compile("|".join(words + names)), 8, "spread", 2)
    return patterns


def pick_chapters(scores, cap, order):
    chapters = sorted(scores)
    ranked = sorted(chapters, key=lambda n: (-scores[n], n))
    if order == "first":
        picks = chapters[:cap // 2] + ranked
    elif order == "last":
        picks = chapters[-cap:]
    else:
        picks = ranked[:cap // 2] + chapters[::max(1, len(chapters) // cap)]
    return sorted(list(dict.fromkeys(picks))[:cap])


def profile_passages(workdir, kb, name, max_chapter, cues, radius=200):
    pattern = name_pattern(names_of(kb.entities[name]) + short_names(kb, name))
    e = kb.entities[name]
    chosen = []
    for cue, (cue_re, cap, order, least) in cues.items():
        per_chapter = {}
        for n in range(e["first_chapter"], min(max_chapter, e["last_chapter"]) + 1):
            text = chapter_text(str(workdir), n)
            windows = []
            for m in pattern.finditer(text):
                hits = {h.group(0).lower() for h in cue_re.finditer(text[max(0, m.start() - radius):m.end() + radius])}
                if len(hits) >= least:
                    windows.append((len(hits), m.start(), m.end()))
            best, wide = [], 2 * radius if cue == "status" else radius
            for hits, start, end in sorted(windows, key=lambda w: (-w[0], w[1])):
                if len(best) < (2 if cue == "status" else 1) and all(abs(start - b[1]) > 2 * radius for b in best):
                    best.append((hits, start, text_window(text, start, end, wide)))
            if best:
                per_chapter[n] = best
        for n in pick_chapters({n: v[0][0] for n, v in per_chapter.items()}, cap, order):
            chosen += [{"chapter": n, "cue": cue, "text": w[2]} for w in sorted(per_chapter[n], key=lambda w: w[1])]
    unique = {}
    for p in chosen:
        unique.setdefault((p["chapter"], p["text"]), p)
    return sorted(unique.values(), key=lambda p: p["chapter"])


PROFILE_PROMPT = """You are filling the infobox and profile sections of a fan-wiki page about the character "{name}" in a novel, using ONLY the facts and passages below. Never use outside knowledge of this novel and never guess: a field nothing below states stays empty.

Also known as: {aliases}

FACTS (chapter, claim, quotes):
{facts}

PASSAGES (chapter: verbatim text):
{passages}

Reply with one JSON object. Every observation has the shape {{"value": "...", "chapter": N, "quotes": ["..."], "asserted_by": "narrator" or a character name}}.
{{
{fields},
  "extra": {{{extra}}},
  "appearance": [observation],
  "personality_evidence": [observation],
  "trivia": [observation]
}}
Rules:
- Each field is a list of observations in chapter order. Add a new observation only when the value is first stated or changes, so a reader can see how it changes over the story. Date each observation to the earliest chapter below that shows it, not a later recap.
- "chapter" is the chapter whose facts or passages hold the quotes. Every quote is one contiguous span copied character for character from a fact quote or passage of THAT chapter, at most 300 characters, no ellipses. The value must be fully shown by its quotes alone, and must not use anything from a later chapter.
- status is one of {statuses}. Record it only from what the text narrates happening to this character: a death on the page, a body found, a revival, a disappearance. Never record what the character can do, does habitually, or would do ("every time", "whenever", "can", "could"), nor a hypothetical or a plan. What another character is told or believes is not status evidence unless the narration confirms it. Give one observation per change, in order (for example dead in one chapter, revived in a later one), dated to the chapter where it happens on the page.
- {stated}
- appearance: concrete physical description (hair, eyes, build, face, clothes they are described wearing), one observation per description.
- personality_evidence: a short trait label as the value ("cautious", "sardonic") with the quote that shows it. Prefer behavior and narration over self-description. Up to 8.
- trivia: odd but true details a fan would enjoy (a habit, a hobby, a quirk, a possession, a phrase they repeat), each with its quote. Up to 6. Skip anything ordinary.
- extra fields: write each value in the format its description gives, and add an observation every time it changes (each rank gained, each new power).
- An empty list is the right answer whenever the material does not state the field.
"""


STATED = [f for f in CHARACTER_FIELDS.values() if not f.values]
STATED_RULE = (", ".join(f.key for f in STATED[:-1]) + f", and {STATED[-1].key} only when stated."
               + "".join(f" {f.key} is {f.hint}." for f in STATED if f.hint))


PROFILE_TIMELINE_RULES = """
TIMELINES (id [kind]: label, chapters):
{registry}
Facts outside main carry their timeline id in brackets. Every observation also takes "timeline": the id of the timeline it holds in. Use main for what holds across timelines: sex, age, appearance, personality, a power or class, a lasting affiliation. Use a run, flashback, vision, or alternate id for a value that holds only there: a death or injury in a run that was later erased keeps that run's id, and so does anything true only in a flashback. A passage from a chapter that holds several timelines belongs to whichever its scene shows.
"""


def profile_facts(facts, cues, cap=60):
    picked = set()
    for cue_re, cue_cap, order, _ in cues.values():
        by_chapter = {}
        for f in facts:
            hits = len({h.group(0).lower() for h in cue_re.finditer(f["claim"])})
            if hits:
                by_chapter.setdefault(f["chapter"], []).append((hits, f))
        for n in pick_chapters({n: sum(h for h, _ in v) for n, v in by_chapter.items()}, cue_cap, order):
            picked.update(f["id"] for _, f in sorted(by_chapter[n], key=lambda v: -v[0])[:2])
    rest = [f for f in facts if f["id"] not in picked]
    room = max(0, cap - len(picked))
    picked.update(f["id"] for f in (rest[::max(1, len(rest) // room)][:room] if room and rest else []))
    return [f for f in facts if f["id"] in picked]


NAME_PARTICLES = {"de", "van", "von", "der", "den", "da", "di", "du", "del", "la", "le", "of", "bin", "ibn", "al", "el", "y"}


def name_span(value, most=6):
    head = re.split(r"[,;:()]|\s[-–—]\s|\.\s+(?=[a-z])", value, maxsplit=1)[0].strip(" \"'")
    head = re.sub(r"(?<=\w\w)\.$", "", head)
    words = head.split()
    if not 1 <= len(words) <= most or any(w[:1].islower() and w.lower() not in NAME_PARTICLES for w in words):
        return None
    return head


def value_shaper(names):
    subject = re.compile(r"(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")"
                         r"(?:\s*[:,–—-]\s*|\s+(?:is|was)\s+)", re.I)

    def shape(key, value):
        if CHARACTER_FIELDS.get(key) and CHARACTER_FIELDS[key].kind == "name":
            return name_span(value)
        m = subject.match(value)
        return value[m.end():].strip() or value if m else value
    return shape


def clean_observations(workdir, raw, max_chapter, values=None, timelines=("main",), shape=None):
    out = []
    for o in raw if isinstance(raw, list) else []:
        if not isinstance(o, dict):
            continue
        value = str(o.get("value") or "").strip()
        try:
            chapter = int(o.get("chapter"))
        except (TypeError, ValueError):
            continue
        if shape and value:
            value = shape(value)
        if not value or not 1 <= chapter <= max_chapter:
            continue
        if values is not None:
            value = value.lower()
            if value not in values:
                continue
        quotes = [str(q).strip() for q in (o.get("quotes") or []) if str(q or "").strip()][:3]
        out.append({"value": value, "chapter": chapter, **verified_quotes(str(workdir), chapter, quotes),
                    "asserted_by": str(o.get("asserted_by") or "narrator").strip(),
                    "timeline": o["timeline"] if o.get("timeline") in timelines else "main"})
    return sorted(out, key=lambda o: o["chapter"])


def quote_naming_class(workdir, o, classes):
    named = [class_pattern(c) for c in classes if class_pattern(c).search(o["value"])]
    if not named or not o["quote_ok"] or any(p.search(q) for p in named for q in o["quotes"]):
        return o
    text = chapter_text(str(workdir), o["chapter"])
    pattern = re.compile("|".join(p.pattern for p in named), re.I)
    for i, q in enumerate(o["quotes"]):
        span = locate_quote(text, q)["span"]
        wider = span and widen_to(text, span[0], span[1], pattern)
        if wider:
            quotes = o["quotes"][:i] + [wider] + o["quotes"][i + 1:]
            checked = verified_quotes(str(workdir), o["chapter"], quotes)
            if checked["quotes"] == quotes:
                return {**o, "quotes": quotes, "quote_ratios": checked["quote_ratios"], "quote_widened_from": q}
    return o


def build_profile(workdir, kb, name, facts, max_chapter, extra_fields, cues, classes):
    passages = profile_passages(workdir, kb, name, max_chapter, cues)
    if len(facts) < 3 and not passages:
        return None
    shown = profile_facts(sorted(facts, key=lambda f: (f["chapter"], f["id"])), cues)
    fact_lines = "\n".join(f"- ch{f['chapter']}" + (f" [{f['timeline']}]" if f.get("timeline", "main") != "main" else "")
                           + f": {f['claim']}" + "".join(f' | "{q}"' for q in f["quotes"]) for f in shown)
    passage_lines = "\n".join(f"- ch{p['chapter']}: {p['text']}" for p in passages)
    fields = ",\n".join(f'  "{k}": [observation]' for k in PROFILE_FIELDS)
    extra = ", ".join(f'"{k}": [observation] ({desc})' for k, desc in extra_fields.items())
    e = kb.entities[name]
    prompt = PROFILE_PROMPT.format(
        name=name, aliases=", ".join(e["aliases"]) or "none", facts=fact_lines or "(none)",
        passages=passage_lines or "(none)", fields=fields, extra=extra, statuses=" / ".join(STATUS_VALUES), stated=STATED_RULE)
    if len(kb.timelines) > 1:
        prompt += PROFILE_TIMELINE_RULES.format(registry="\n".join(f"- {timeline_line(t)}" for t in kb.timelines.values()))
    reply = cached_llm(workdir, "profile", prompt)
    profile = {"fields": {}, "extra": {}, "lists": {}, "inputs": {"facts": len(shown), "passages": len(passages)}}
    shape = value_shaper(names_of(e))
    for k in PROFILE_FIELDS:
        profile["fields"][k] = clean_observations(workdir, reply.get(k), max_chapter, STATUS_VALUES if k == "status" else None, kb.timelines,
                                                  lambda v, k=k: shape(k, v))
    raw_extra = reply.get("extra") if isinstance(reply.get("extra"), dict) else {}
    for k, v in raw_extra.items():
        profile["extra"][str(k)] = [quote_naming_class(workdir, o, classes.get(str(k), ()))
                                    for o in clean_observations(workdir, v, max_chapter, timelines=kb.timelines,
                                                                shape=lambda v, k=str(k): shape(k, v))]
    for k in PROFILE_LISTS:
        profile["lists"][k] = clean_observations(workdir, reply.get(k), max_chapter, timelines=kb.timelines)
    audit_profile(workdir, name, profile, shape)
    return profile


FIELD_PROMPT = """You are filling one infobox field of a fan-wiki page about the character "{name}" in a novel, using ONLY the facts and passages below. Never use outside knowledge of this novel and never guess.

Also known as: {aliases}

Field "{field}": {description}{values}

FACTS (chapter, claim, quotes):
{facts}

PASSAGES (chapter: verbatim text):
{passages}

Reply with one JSON object: {{"observations": [{{"value": "...", "chapter": N, "quotes": ["..."], "asserted_by": "narrator" or a character name}}]}}
Rules:
- Record the field only where the material shows it about {name}. A passage naming it about someone else is not evidence; a pronoun or a description such as "the" plus a class name counts when the passage plainly means {name}.
- Add an observation when the value is first shown and each time it changes, in chapter order, dated to the earliest chapter below that shows it. Give every part of the value the format asks for that the material shows.
- "chapter" is the chapter whose facts or passages hold the quotes. Every quote is one contiguous span copied character for character from a fact quote or passage of THAT chapter, at most 300 characters, no ellipses. The value must be fully shown by its quotes alone.
- An empty list is the right answer whenever the material does not show the field.
"""


def field_cue(cues, classes):
    words = [cues["power"][0].pattern] if "power" in cues else []
    words += [class_pattern(c).pattern for c in classes]
    return {"power": (re.compile("|".join(words), re.I), 12, "spread", 1)} if words else {}


def probe_field(workdir, kb, name, facts, max_chapter, key, description, cues, classes):
    cue = field_cue(cues, classes)
    if not cue:
        return []
    passages = profile_passages(workdir, kb, name, max_chapter, cue)
    shown = profile_facts(sorted(facts, key=lambda f: (f["chapter"], f["id"])), cue, cap=30)
    if not passages and not shown:
        return []
    e = kb.entities[name]
    prompt = FIELD_PROMPT.format(
        name=name, aliases=", ".join(e["aliases"]) or "none", field=key.replace("_", " "), description=description,
        values=f" It starts with one of: {', '.join(classes)}." if classes else "",
        facts="\n".join(f"- ch{f['chapter']}" + (f" [{f['timeline']}]" if f.get("timeline", "main") != "main" else "")
                        + f": {f['claim']}" + "".join(f' | "{q}"' for q in f["quotes"]) for f in shown) or "(none)",
        passages="\n".join(f"- ch{p['chapter']}: {p['text']}" for p in passages) or "(none)")
    if len(kb.timelines) > 1:
        prompt += PROFILE_TIMELINE_RULES.format(registry="\n".join(f"- {timeline_line(t)}" for t in kb.timelines.values()))
    reply = cached_llm(workdir, "profile-field", prompt)
    shape = value_shaper(names_of(e))
    found = [quote_naming_class(workdir, o, classes)
             for o in clean_observations(workdir, reply.get("observations"), max_chapter, timelines=kb.timelines,
                                         shape=lambda v: shape(key, v))]
    probe = {"fields": {}, "extra": {key: found}, "lists": {}}
    audit_profile(workdir, name, probe, shape)
    return [{**o, "source": "probe"} for o in probe["extra"][key]]


PROFILE_SUPPORT_PROMPT = """You are auditing a fan-wiki character profile built from a novel. Each item below is one value recorded for a field of a character's profile, followed by the quotes offered as its only evidence. Judge every value against its own quotes ALONE. Ignore what you know or could guess from anywhere else, including the other items.

- "supported": the quotes show this value for this character, every part of it. Paraphrase is fine, a pronoun in a quote may be taken to mean the character, and "we" or "us" in a quote spoken by the character includes them. Showing is enough: a status is supported by a scene that plainly shows it (a body that stops moving, a dead character who sits up again), and a personality trait by behavior or words that plainly display it.
- "trim": part of the value is shown and part is not, including filler such as "unspecified" or "unknown" standing in for something the quotes do not state. Give "claim": the value rewritten to keep only what the quotes show.
- "unsupported": the quotes do not show the value, or show it about someone else. A status whose quotes describe an ability, a habit, or a hypothetical rather than narrate the event happening is unsupported.

{items}

Reply with one JSON object: {{"verdicts": [{{"id": "O1", "verdict": "supported" or "trim" or "unsupported", "claim": "only for trim"}}]}}, one verdict per item.
"""


def trimmed_value(group, key, value, claim, shape):
    if key == "status":
        return claim.lower()
    if group == "lists":
        return claim
    shaped = shape(key, claim)
    return shaped if shaped and stems(shaped) <= stems(value) else None


def audit_profile(workdir, name, profile, shape):
    profile["audit"] = {}
    audited = [(group, key, o) for group, key, o in profile_observations(profile) if o["quote_ok"]]
    items = [(f"O{i}", f"O{i} [{key.replace('_', ' ')}] {name}: {o['value']} (asserted by {o['asserted_by']})\n"
              + "\n".join(f"  > {q}" for q in o["quotes"]))
             for i, (group, key, o) in enumerate(audited, 1)]
    verdicts = audit_items(workdir, f"profile support {name}", lambda p: cached_llm(workdir, "profile-support", p),
                           PROFILE_SUPPORT_PROMPT, items)
    for (iid, _), (group, key, o) in zip(items, audited):
        v = verdicts.get(iid) or {}
        o["support"] = v.get("verdict") or "unaudited"
        profile["audit"][o["support"]] = profile["audit"].get(o["support"], 0) + 1
        trimmed = str(v.get("claim") or "").strip()
        if o["support"] == "trim" and trimmed:
            value = trimmed_value(group, key, o["value"], trimmed, shape)
            if value:
                o["original_value"], o["value"] = o["value"], value
            else:
                o["refused_trim"] = trimmed
    for group in ("fields", "extra", "lists"):
        for key, obs in profile[group].items():
            obs[:] = [o for o in obs if o.get("support") != "unsupported"
                      and not (key == "status" and o["value"] not in STATUS_VALUES)]


def profile_observations(profile):
    for group in ("fields", "extra", "lists"):
        for key, obs in profile[group].items():
            for o in obs:
                yield group, key, o


def filed_page(workdir, entity, o):
    pending = [a for a in entity.get("absorbed", []) if o["chapter"] < a["chapter"]]
    names = names_of(entity) + [n for a in pending for n in [a["name"]] + a["aliases"]]
    owner = {name_key(n): entity["name"] for n in names}
    owner.update({name_key(n): a["name"] for a in pending for n in [a["name"]] + a["aliases"]})
    text = chapter_text(str(workdir), o["chapter"])
    spans = [s for s in (locate_quote(text, q)["span"] for q in o["quotes"]) if s]
    if not spans:
        return None
    distance = {}
    for m in name_pattern(names).finditer(text):
        gap = min(max(s[0] - m.end(), m.start() - s[1], 0) for s in spans)
        page = owner[name_key(m.group(0))]
        distance[page] = min(distance.get(page, gap), gap)
    ranked = sorted(distance.items(), key=lambda d: d[1])
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def page_profiles(workdir, entities, profiles):
    pages = {}
    for e in entities:
        if e["type"] != "character":
            continue
        joined = [a for a in e.get("absorbed", []) if a.get("by") == "reader" and a["name"] in profiles]
        pages.update(split_profile(workdir, {**e, "absorbed": [a for a in e.get("absorbed", []) if a.get("by") != "reader"]}, profiles))
        for a in joined:
            own = pages[a["name"]] = {group: dict(profiles[a["name"]][group]) for group in ("fields", "extra", "lists")}
            page = pages.setdefault(e["name"], {"fields": {}, "extra": {}, "lists": {}})
            for group, rows in own.items():
                for key, obs in rows.items():
                    page[group][key] = joined_rows(page[group].get(key, []), obs, a["chapter"])
    return pages


def split_profile(workdir, e, profiles):
    if e["name"] not in profiles:
        return {}
    merged_at = {a["name"]: a["chapter"] for a in e.get("absorbed", [])}
    split = {page: {"fields": {}, "extra": {}, "lists": {}} for page in [e["name"]] + list(merged_at)}
    for group in ("fields", "extra", "lists"):
        for key, obs in profiles[e["name"]][group].items():
            for page in split.values():
                page[group][key] = []
            for o in obs:
                pending = [c for c in merged_at.values() if o["chapter"] < c]
                page = filed_page(workdir, e, o) if pending else e["name"]
                if page == e["name"]:
                    split[page][group][key].append(o)
                    continue
                if page in merged_at:
                    split[page][group][key].append(o)
                split[e["name"]][group][key].append({**o, "shown": merged_at.get(page, max(pending))})
    return split


def more_specific(old, new, classes):
    names_class = [any(class_pattern(c).search(o["value"]) for c in classes) for o in (old, new)]
    if names_class[0] != names_class[1]:
        return names_class[0]
    return stems(new["value"]) < stems(old["value"])


def keep_specific(profile, previous, classes):
    for group in ("fields", "extra"):
        for key, obs in profile[group].items():
            verified = {(o["chapter"], o.get("timeline", "main")): o for o in (previous or {}).get(group, {}).get(key, [])
                        if o.get("support") == "supported" and o.get("quote_ok") and "source" not in o}
            for i, o in enumerate(obs):
                old = verified.get((o["chapter"], o.get("timeline", "main")))
                if old and old["value"] != o["value"] and more_specific(old, o, classes.get(key, ())):
                    obs[i] = {**old, "replaced": old.get("replaced", []) + [{"value": o["value"], "support": o.get("support")}]}
    return profile


def cmd_profile(args):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir)
    max_chapter = max(kb.synopses, default=0)
    by_entity = {}
    for f in kb.facts:
        by_entity.setdefault(f["entity"], []).append(f)
    characters = sorted((n for n, e in kb.entities.items() if e["type"] == "character"
                         and (not args.character or n in args.character)), key=lambda n: -len(by_entity.get(n, [])))
    book = load_book(workdir)
    extra_fields, cues = book["extra_fields"], cue_patterns(kb, book)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        built = list(pool.map(lambda n: build_profile(workdir, kb, n, by_entity.get(n, []), max_chapter, extra_fields, cues,
                                                      book["field_values"]), characters))
    previous = read_json(workdir / "profiles.json", {"characters": {}})["characters"]
    profiles = {n: keep_specific(p, previous.get(n), book["field_values"]) for n, p in zip(characters, built) if p}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        probes = dict(zip(profiles, pool.map(lambda n: {
            k: probe_field(workdir, kb, n, by_entity.get(n, []), max_chapter, k, desc, cues, book["field_values"].get(k, ()))
            for k, desc in extra_fields.items()}, profiles)))
    everyone = {**previous, **profiles} if args.character else profiles
    volumes = read_json(workdir / "volumes.json", {"volumes": []})["volumes"]
    deaths = verified_deaths(workdir, kb, everyone, volumes, max_chapter, args.jobs)
    deaths += verified_revivals(workdir, kb, profiles, deaths, max_chapter, args.jobs)
    for n, p in profiles.items():
        add_evidence(workdir, kb, n, p, probes[n], deaths, book)
    deaths = [d for d in deaths if d["value"] == "dead"]
    write_json(workdir / "profiles.json", {"characters": everyone, "deaths": deaths})
    filled, quotes = {}, [0, 0]
    for p in profiles.values():
        for group, key, o in profile_observations(p):
            filled.setdefault(f"{group}.{key}", set()).add(id(p))
            quotes[0] += o["quote_ok"]
            quotes[1] += 1
    audit = {}
    for n in characters:
        for verdict, count in (profiles.get(n) or {}).get("audit", {}).items():
            audit[verdict] = audit.get(verdict, 0) + count
    print(f"profiled {sum(p is not None for p in built)} of {len(characters)} characters; {quotes[0]}/{quotes[1]} observations quote-verified; support audit {audit}")
    print(f"{len(deaths)} verified deaths")
    for key in sorted(filled, key=lambda k: -len(filled[k])):
        print(f"  {key}: {len(filled[key])} characters")
