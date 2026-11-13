import bisect
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .book import load_book
from .corpus import Corpus, question_terms
from .files import read_json, write_json
from .llm import cached_llm
from .names import name_pattern, names_of
from .state import load_states


TIER_ORDER = ("cliffhanger", "arc", "series")


TIER_HEADINGS = {"series": "Series mysteries", "arc": "Arc mysteries", "cliffhanger": "Cliffhangers"}


TIER_PROMPT = """Below are questions a reader noted while reading a novel, each with the passage that raised it. Classify the scope of each question, judging only from the question and its passage. Never use outside knowledge of this novel.
- "series": a central mystery of the whole story, such as the nature of the world, its powers or gods, the protagonist's origin or secret, or a hidden power's aims. Likely to stay open across many volumes.
- "arc": a mystery driving the current storyline, such as a case, a culprit, an enemy's plan, or a character's hidden motive. Likely answered within tens of chapters.
- "cliffhanger": a question about the immediate scene or a passing detail, such as who is at the door or what happens next. Likely answered within a few chapters or never revisited.

{items}

Reply with one JSON object: {{"labels": [{{"id": "...", "scope": "series" or "arc" or "cliffhanger"}}]}}, one entry per question.
"""


MYSTERY_PROMPT = """Below are questions a reader noted while reading a novel, each with the passage that raised it. Decide for each whether it is a mystery: something the story keeps hidden or unexplained that a reader would want answered later, such as who someone is, what something is, what really happened, or a hidden reason or plan.
It is not a mystery when it only asks what a character will say, tell, or do next, how someone will react, or how a scene will play out, even when what they will tell is a secret, or when it asks the reason for a passing gesture, courtesy, or mood, such as a bow, a farewell, or a smile, when nothing in the passage points to a hidden reason. When unsure, answer true. Judge only from the question and its passage. Never use outside knowledge of this novel.

{items}

Reply with one JSON object: {{"questions": [{{"id": "...", "mystery": true or false}}]}}, one entry per question.
"""


def tier_at(tier, n):
    if tier.get("series_at") is not None and tier["series_at"] <= n:
        return "series"
    if tier.get("arc_at") is not None and tier["arc_at"] <= n:
        return "arc"
    return "cliffhanger"


def tier_labels(workdir, questions, jobs, batch=40):
    labels = {}
    def label(chunk):
        items = "\n\n".join(f"ID {q['id']}\nQuestion: {q['question']}\nPassage: \"{q.get('quote', '')}\"" for q in chunk)
        return cached_llm(workdir, "tiers", TIER_PROMPT.format(items=items))
    for _ in range(3):
        pending = [q for q in questions if q["id"] not in labels]
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            replies = list(pool.map(label, [pending[i:i + batch] for i in range(0, len(pending), batch)]))
        for reply in replies:
            for row in reply.get("labels") or []:
                if isinstance(row, dict) and row.get("scope") in TIER_ORDER:
                    labels[str(row.get("id"))] = row["scope"]
    return labels


def mystery_checks(workdir, questions, jobs, batch=40):
    def check(chunk):
        items = "\n\n".join(f"ID {q['id']}\nQuestion: {q['question']}\nPassage: \"{q.get('quote', '')}\"" for q in chunk)
        reply = cached_llm(workdir, "mystery", MYSTERY_PROMPT.format(items=items))
        return [row for row in reply.get("questions") or [] if isinstance(row, dict) and isinstance(row.get("mystery"), bool)]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        rows = [row for chunk in pool.map(check, [questions[i:i + batch] for i in range(0, len(questions), batch)]) for row in chunk]
    wanted = {q["id"] for q in questions}
    return {str(row["id"]): row["mystery"] for row in rows if str(row.get("id")) in wanted}


def tier_signals(corpus, kb, q, fact_chapters, patterns):
    c0 = q["chapter"]
    end = min(q.get("resolved_chapter", corpus.last + 1) - 1, corpus.last)
    terms = question_terms(q)
    weights = {t: corpus.idf(t, c0) for t in terms}
    recurring = []
    for n in range(c0 + 1, end + 1):
        for hits in (terms & wt for wt in corpus.window_terms[n]):
            if sum(weights[t] >= 1 for t in hits) >= 2 and sum(weights[t] for t in hits) >= 3:
                recurring.append(n)
                break
    text = q["question"] + " " + q.get("quote", "")
    named = [k for k, p in patterns.items() if kb.entities[k]["first_chapter"] <= c0 and p.search(text)
             and 2 * len({x for x in fact_chapters.get(k, []) if x <= c0}) < c0]
    return {"end": end, "recurring": recurring, "entities": named,
            "attempts": sorted(r["chapter"] for r in q["rejected"] if r["chapter"] <= end),
            "entity_facts": sorted(x for k in named for x in fact_chapters.get(k, []) if x <= end)}


def promotions(signals, c0, label, rule):
    tier = {"arc_at": None, "series_at": None}
    for n in range(c0, signals["end"] + 1):
        engaged = bisect.bisect_right(signals["recurring"], n) + bisect.bisect_right(signals["attempts"], n)
        facts = bisect.bisect_right(signals["entity_facts"], n)
        gate = 0
        if n - c0 >= rule["arc_age"] or engaged or facts >= rule["arc_entity_facts"]:
            gate = 1
        if n - c0 >= rule["series_age"] and engaged >= rule["series_engaged"]:
            gate = 2
        reached = min(TIER_ORDER.index(label), gate)
        if engaged >= rule["promote_engaged"]:
            reached = max(reached, min(gate, 1))
        if reached >= 1 and tier["arc_at"] is None:
            tier["arc_at"] = n
        if reached == 2 and tier["series_at"] is None:
            tier["series_at"] = n
    return tier


def cmd_tiers(args):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir)
    corpus = Corpus(workdir, kb)
    rule = load_book(workdir)["tiers"]
    fact_chapters = {}
    for f in kb.facts:
        fact_chapters.setdefault(f["entity"], []).append(f["chapter"])
    patterns = {}
    for k, e in kb.entities.items():
        names = [a for a in names_of(e) if len(a) >= 3]
        if names:
            patterns[k] = name_pattern(names)
    path = workdir / "tiers.json"
    old = read_json(path, {"questions": {}})["questions"]
    labels = {k: v["label"] for k, v in old.items() if v.get("label") in TIER_ORDER}
    todo = [q for q in kb.questions.values() if q["id"] not in labels]
    labels.update(tier_labels(workdir, todo, args.jobs))
    mystery = {k: v["mystery"] for k, v in old.items() if isinstance(v.get("mystery"), bool)}
    mystery.update(mystery_checks(workdir, [q for q in kb.questions.values() if q["id"] not in mystery], args.jobs))
    tiers = {}
    for q in kb.questions.values():
        checked = {"mystery": mystery[q["id"]]} if q["id"] in mystery else {}
        if q["id"] not in labels:
            if checked:
                tiers[q["id"]] = checked
            continue
        signals = tier_signals(corpus, kb, q, fact_chapters, patterns)
        tiers[q["id"]] = {"label": labels[q["id"]], **promotions(signals, q["chapter"], labels[q["id"]], rule), "source": "rule",
                          "signals": {"recurring": signals["recurring"], "attempts": signals["attempts"],
                                      "entities": signals["entities"], "entity_facts": len(signals["entity_facts"])}, **checked}
    write_json(path, {"rule": rule, "questions": tiers})
    counts = {}
    for q in kb.open_questions():
        t = tier_at(tiers.get(q["id"], {}), corpus.last)
        counts[t] = counts.get(t, 0) + 1
    labeled = sum(1 for t in tiers.values() if "label" in t)
    print(f"tiered {labeled} questions ({len(kb.questions) - labeled} unlabeled, "
          f"{sum(1 for t in tiers.values() if t.get('mystery') is False)} not mysteries); "
          f"open at chapter {corpus.last}: {counts}")
