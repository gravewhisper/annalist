import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import reread
from .book import load_book
from .corpus import Corpus, match_score, question_terms, stems
from .corrections import QUESTIONS
from .files import log, read_json, state_paths, write_json
from .llm import cached_llm, LLMError, spent_since
from .names import name_pattern, names_of
from .state import ENDING_VERDICTS, load_states, unfinished, write_derived
from .sweep import judge_answer
from .text import check_quote
from .tiers import tier_at


def ending_status(workdir, read, total):
    if not load_book(workdir)["complete"]:
        return "book.json does not mark the book complete, so its open questions may still be answered by a later volume"
    if read < total:
        return f"chapters {read + 1}-{total} are not read"
    return None


def observations_upto(profile, last):
    for observations in list(profile.get("fields", {}).values()) + list(profile.get("lists", {}).values()):
        yield [o for o in observations if o["chapter"] <= last]


def evidence_chapters(kb, profiles, last):
    chapters = {}
    for f in kb.facts:
        chapters.setdefault(f["entity"], set()).add(f["chapter"])
    for r in kb.relations:
        for end in ("source", "target"):
            chapters.setdefault(r[end], set()).add(r["chapter"])
    for name, p in profiles.items():
        for observations in observations_upto(p, last):
            chapters.setdefault(name, set()).update(o["chapter"] for o in observations if o.get("quote_ok", True))
    return chapters


def evidence_text(kb, profiles, last):
    text = {}
    for r in kb.relations:
        text.setdefault(r["chapter"], []).append(f"{r['source']} {r['type']} {r['target']}")
    for name, p in profiles.items():
        for observations in observations_upto(p, last):
            for o in observations:
                text.setdefault(o["chapter"], []).append(f"{name} {o.get('value', '')}")
    return {n: stems(" ".join(lines)) for n, lines in text.items()}


class Finder:
    def __init__(self, workdir, kb):
        profiles = read_json(Path(workdir) / "profiles.json", {"characters": {}})["characters"]
        self.corpus = Corpus(workdir, kb)
        self.by_entity = evidence_chapters(kb, profiles, self.corpus.last)
        self.extra = evidence_text(kb, profiles, self.corpus.last)
        self.patterns = {k: name_pattern([a for a in names_of(e) if len(a) >= 3]) for k, e in kb.entities.items()
                         if any(len(a) >= 3 for a in names_of(e))}

    def named(self, q):
        text = q["question"] + " " + q.get("quote", "")
        return [k for k, p in self.patterns.items() if p.search(text)]

    def candidates(self, q, chapters=6, after=False, full=None):
        corpus = self.corpus
        terms = question_terms(q)
        weights = {t: corpus.idf(t) for t in terms}
        named = self.named(q)
        scores = {}
        for n in range(q["chapter"] if after else 1, corpus.last + 1):
            best = corpus.best_windows(terms, weights, n, 1)
            score = (best[0][0] if best else 0) + match_score(terms & corpus.dense[n], weights)
            score += match_score(terms & self.extra.get(n, set()), weights)
            score += sum(math.log(1 + corpus.last / len(self.by_entity[k])) for k in named if n in self.by_entity.get(k, ()))
            if score > 0:
                scores[n] = score
        ranked = sorted(scores, key=lambda n: (-scores[n], n))[:chapters]
        doubled = set(ranked[:full])
        passages = []
        for n in sorted(ranked):
            picked = sorted({i for _, i in corpus.best_windows(terms, weights, n, 2 if n in doubled else 1)} or {0})
            passages.append({"chapter": n, "texts": [corpus.windows[n][i] for i in picked]})
        return passages


ENDING_PROMPT = """The novel is finished: chapter {last} is its last chapter. Below are questions a reader noted while reading it that were still open at the end. Each comes with the passage that raised it, how the story treated it afterwards, and passages from anywhere in the book that may bear on it, each with its chapter's synopsis.

HOW THE STORY ENDS (synopses of the last chapters):
{ending}

{items}

For each question, do two things.
1. Decide whether one of its passages itself answers the core of the question. If so, set "answered": true and give "chapter", "quote" and "answer". A synopsis alone is not enough; a passage that repeats or only hints at the mystery is not an answer.
2. Always give "verdict", your judgement of the question at the end of the book if step 1 does not hold:
- "answered-implicitly": the book does answer it, but only by implication across passages or by the outcome of the ending. Give "answer" and "quotes" that together show it.
- "left-open": a central mystery of the story that the ending deliberately leaves unanswered.
- "dropped-thread": a minor or passing detail the story never followed up and that does not matter to how it ends.
- "unclear": none of these fits with confidence.
Scope and how often the story came back to a question are signals: a series-scope question the story keeps returning to is rarely a dropped thread; a scene detail never mentioned again rarely is a central mystery.

Reply with one JSON object: {{"results": [{{"id": "...", "answered": true or false, "chapter": chapter number of the answering passage, "quote": "...", "answer": "...", "verdict": "answered-implicitly" or "left-open" or "dropped-thread" or "unclear", "quotes": [{{"chapter": n, "quote": "..."}}], "reason": "one sentence"}}]}}, one entry per question.
Rules:
- answer states only what the text up to that chapter shows for step 1; for answered-implicitly it may draw on the whole book.
- every quote is one contiguous span of one or two sentences copied exactly, character for character, from a passage of that chapter, at most 300 characters. No ellipses, no paraphrase. This is checked by machine.
- quotes is empty unless the verdict is answered-implicitly.
"""


def treatment(q, tier, last):
    signals = tier.get("signals") or {}
    recurring = [n for n in signals.get("recurring", []) if n > q["chapter"]]
    lines = [f"Scope by the end: {tier_at(tier, last)}" if tier else "Scope by the end: unknown",
             f"The story came back to it in {len(recurring)} later chapters"
             + (f" (last in chapter {recurring[-1]})" if recurring else "")]
    for r in q.get("rejected", []):
        lines.append(f"Earlier proposed answer from chapter {r['chapter']}"
                     + (f", kept as a lead: {r['lead']}" if r.get("lead") else f", rejected: {r.get('answer', '')}"))
    lines += [f"Lead found at a volume end, from chapter {l['chapter']}: {l['text']}" for l in q["leads"] if l["by"] == "answers"]
    return lines


def ending_item(q, tier, passages, synopses, last):
    lines = [f"ID {q['id']} (raised in chapter {q['chapter']})", f"Question: {q['question']}",
             f"Raising passage: \"{q.get('quote', '')}\"", *treatment(q, tier, last), "Passages:"]
    for p in passages:
        lines.append(f"[chapter {p['chapter']}] Synopsis: {synopses.get(p['chapter'], '')}")
        lines += [f"<passage chapter=\"{p['chapter']}\">\n{t}\n</passage>" for t in p["texts"]]
    return "\n".join(lines)


def checked_quotes(workdir, rows, last):
    kept, dropped = [], []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            n = int(row.get("chapter"))
        except (TypeError, ValueError):
            n = None
        quote = str(row.get("quote") or "").strip()
        if n is not None and 1 <= n <= last and quote and check_quote(str(workdir), n, quote)["ok"]:
            kept.append({"chapter": n, "quote": quote})
        elif quote:
            dropped.append({"chapter": n, "quote": quote})
    return kept, dropped


def decide(workdir, kb, q, reply, candidates, last):
    attempt = judge_answer(workdir, kb, q, reply, candidates)
    entry = {"source": "llm", "candidates": candidates, "attempt": attempt}
    if attempt["verdict"] == "accept":
        return {**entry, "verdict": "answered", "chapter": max(attempt["chapter"], q["chapter"]), "answer": attempt["answer"],
                "quote": attempt["quote"], "payoff": attempt.get("payoff", ""), "quote_chapter": attempt["chapter"]}
    if attempt["verdict"] == "error":
        return {**entry, "verdict": "error", "reason": attempt.get("reason", "")}
    verdict = reply.get("verdict") if reply.get("verdict") in ENDING_VERDICTS else "unclear"
    reason = str(reply.get("reason") or "").strip()
    if verdict != "answered-implicitly":
        return {**entry, "verdict": verdict, "reason": reason}
    if attempt["verdict"] == "reject" and attempt.get("quote_ok"):
        return {**entry, "verdict": "unclear", "reason": f"the reread rejected its answer from chapter {attempt['chapter']}: "
                                                         f"{attempt.get('payoff', '')}"}
    kept, dropped = checked_quotes(workdir, reply.get("quotes"), last)
    answer = str(reply.get("answer") or "").strip()
    if not kept or not answer:
        return {**entry, "verdict": "unclear", "reason": "no quote of its implied answer was found in the text",
                "dropped_quotes": dropped}
    return {**entry, "verdict": verdict, "answer": answer, "quotes": kept, "reason": reason,
            **({"dropped_quotes": dropped} if dropped else {})}


def confirm_implied(workdir, q, d):
    quote = " ... ".join(f"[chapter {r['chapter']}] {r['quote']}" for r in d["quotes"])
    verdict = reread(workdir, q, {"answer": d["answer"], "quote": quote}, max(r["chapter"] for r in d["quotes"]))
    if verdict["verdict"] == "error":
        return d
    checked = {**d, "reread": {"verdict": verdict["verdict"], "payoff": verdict["payoff"]}}
    if verdict["verdict"] == "accept":
        return checked
    return {**{k: v for k, v in checked.items() if k not in ("answer", "quotes")}, "verdict": "unclear",
            "implied": {"answer": d["answer"], "quotes": d["quotes"]},
            "reason": f"the reread rejected its implied answer: {verdict['payoff']}"}


def cmd_ending(args):
    workdir = Path(args.workdir).resolve()
    read = len(state_paths(workdir))
    refusal = ending_status(workdir, read, len(read_json(workdir / "chapters.json", [])))
    if refusal:
        sys.exit(f"annalist ending: {refusal}; the end-of-book pass runs only on a complete book read to its last chapter")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    kb = load_states(workdir, corrections=(QUESTIONS,))
    last = max(kb.synopses)
    path = workdir / "ending.json"
    opened = {q["id"] for q in kb.open_questions()}
    done = {k: v for k, v in read_json(path, {"questions": {}})["questions"].items()
            if not unfinished(v) or (k in opened and v["verdict"] == "answered-implicitly")}
    write_json(path, {"last": last, "questions": done})
    tiers = read_json(workdir / "tiers.json", {"questions": {}})["questions"]
    todo = [q for q in kb.open_questions() if q["id"] not in done]
    finder = Finder(workdir, kb)
    work = [(q, finder.candidates(q)) for q in todo]
    batches = [work[i:i + args.batch] for i in range(0, len(work), args.batch)]
    ending = "\n".join(f"Chapter {n}: {kb.synopses[n]}" for n in sorted(kb.synopses)[-3:])
    lock = threading.Lock()
    log(workdir, f"ending: {len(todo)} questions open at chapter {last} in {len(batches)} batches")

    def run(batch):
        items = "\n\n".join(ending_item(q, tiers.get(q["id"], {}), passages, kb.synopses, last) for q, passages in batch)
        try:
            reply = cached_llm(workdir, "ending", ENDING_PROMPT.format(last=last, ending=ending, items=items))
            results = {str(r.get("id")): r for r in reply.get("results") or [] if isinstance(r, dict)}
            decided = {q["id"]: decide(workdir, kb, q, results[q["id"]], [p["chapter"] for p in passages], last)
                       for q, passages in batch if q["id"] in results}
        except LLMError as exc:
            log(workdir, f"  ending batch {batch[0][0]['id']}: {exc}")
            decided = {q["id"]: {"source": "llm", "verdict": "error", "reason": str(exc)} for q, _ in batch}
        with lock:
            current = read_json(path, {"questions": {}})
            current["questions"].update(decided)
            write_json(path, {"last": last, "questions": current["questions"]})
        return len(decided)

    def confirm(qid):
        checked = confirm_implied(workdir, kb.questions[qid], read_json(path, {"questions": {}})["questions"][qid])
        with lock:
            current = read_json(path, {"questions": {}})
            current["questions"][qid] = checked
            write_json(path, {"last": last, "questions": current["questions"]})

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        judged = sum(pool.map(run, batches))
        implied = [k for k, d in read_json(path, {"questions": {}})["questions"].items()
                   if unfinished(d) and d["verdict"] == "answered-implicitly" and k in kb.questions]
        log(workdir, f"ending: rereading {len(implied)} implied answers")
        list(pool.map(confirm, implied))
    decisions = read_json(path, {"questions": {}})["questions"]
    write_json(path, {"last": last, "questions": decisions})
    kb = load_states(workdir)
    write_derived(workdir, kb)
    counts = {}
    for d in decisions.values():
        counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
    log(workdir, f"ending: judged {judged} of {len(todo)} this run, ${spent_since(workdir, started):.2f}; all verdicts {counts}")
