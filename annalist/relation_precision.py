import hashlib
import time
from dataclasses import asdict, dataclass

from .llm import cached_llm, spent_since
from .readerkey import judge_settings
from .scorecard import Wiki, percent
from .text import chapter_text, locate_quote, text_window

SEED = "relation-precision-1"
VERDICTS = ("correct", "wrong", "unsupported")
RADIUS = 700
MAX_QUOTES = 2

JUDGE_PROMPT = """A wiki built from a novel states a relation between two of its entries, backed by a quote from chapter {chapter}. Judge whether the relation, exactly as worded and in this direction, is correct given the quote and the passage around it.

Relation: "{source}" {type} "{target}"
"{source}" is also called: {source_names}
"{target}" is also called: {target_names}

{passages}

Reply with one JSON object: {{"verdict": "correct" or "wrong" or "unsupported", "reasoning": "one or two sentences"}}.
- correct: the passage states the relation or clearly implies it, with the right kind of tie, in the right direction, between these two.
- wrong: the passage shows a different tie between them (another kind of kin, the reverse direction, another person), or contradicts the relation.
- unsupported: the passage neither shows nor contradicts the relation.
"""


@dataclass(frozen=True)
class Row:
    key: str
    chapter: int
    source: str
    type: str
    target: str
    quotes: tuple
    verdict: str
    reason: str


def relation_key(wiki, r):
    return f"ch{r['chapter']} {wiki.all[r['source']]['name']} | {r['type']} | {wiki.all[r['target']]['name']}"


def rank(key):
    return hashlib.sha1(f"{SEED}\n{key}".encode()).hexdigest()


def sample(wiki, n):
    distinct = {}
    for r in wiki.relations:
        distinct.setdefault(relation_key(wiki, r), r)
    picked = sorted(distinct, key=rank)[:n]
    return len(distinct), sorted(((k, distinct[k]) for k in picked), key=lambda p: (p[1]["chapter"], p[0]))


def also_called(wiki, eid):
    names = [n for n in dict.fromkeys(wiki.names(eid) + wiki.names(wiki.root(eid))) if n != wiki.all[eid]["name"]]
    return ", ".join(f'"{n}"' for n in names) or "no other names"


def passages(workdir, r):
    text = chapter_text(workdir, r["chapter"])
    out = []
    for i, quote in enumerate(r.get("quotes", [])[:MAX_QUOTES], 1):
        span = locate_quote(text, quote)["span"]
        around = text_window(text, span[0], span[1], RADIUS) if span else "(the quote was not found in the chapter text)"
        out.append(f"Quote {i}: \"{quote}\"\nPassage around quote {i}:\n<passage>\n{around}\n</passage>")
    return "\n\n".join(out) or "(the relation has no quote)"


def judge_problem(reply):
    return None if reply.get("verdict") in VERDICTS else f"verdict must be one of {', '.join(VERDICTS)}"


def judge(workdir, settings, wiki, key, r):
    source, target = wiki.all[r["source"]]["name"], wiki.all[r["target"]]["name"]
    prompt = JUDGE_PROMPT.format(chapter=r["chapter"], source=source, type=r["type"], target=target,
                                 source_names=also_called(wiki, r["source"]), target_names=also_called(wiki, r["target"]),
                                 passages=passages(workdir, r))
    reply = cached_llm(workdir, "judge", prompt, check=judge_problem, settings=settings)
    return Row(key, r["chapter"], source, r["type"], target, tuple(r.get("quotes", [])[:MAX_QUOTES]),
               reply["verdict"], str(reply.get("reasoning") or "").strip())


def relation_precision(workdir, wiki_data, n, judge_model=None):
    settings = judge_settings(workdir, judge_model)
    wiki = Wiki(wiki_data)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    total, picked = sample(wiki, n)
    rows = [judge(workdir, settings, wiki, key, r) for key, r in picked]
    counts = {v: sum(row.verdict == v for row in rows) for v in VERDICTS}
    return {"seed": SEED, "requested": n, "judge_model": settings.model_for("judge"),
            "judge_spend_usd": spent_since(workdir, started),
            "totals": {"relations": total, "sampled": len(rows), **counts,
                       "precision": round(counts["correct"] / len(rows), 3) if rows else None},
            "rows": [asdict(row) for row in rows]}


def markdown(section):
    t = section["totals"]
    lines = ["", "## relation_precision", "",
             f"Sampled {t['sampled']} of {t['relations']} relations (seed {section['seed']}). "
             f"Judge: {section['judge_model']}. Judge spend: ${section['judge_spend_usd']:.4f}.", "",
             f"Precision: {percent(t['precision'])} ({t['correct']} correct, {t['wrong']} wrong, {t['unsupported']} unsupported)", ""]
    for row in sorted(section["rows"], key=lambda row: ("wrong", "unsupported", "correct").index(row["verdict"])):
        lines.append(f"- **{row['verdict']}** `{row['key']}`: {row['reason']}")
        lines += [f"  - quote: \"{q}\"" for q in row["quotes"]]
    return "\n".join(lines) + "\n"
