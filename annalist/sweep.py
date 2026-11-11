import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import reread
from .corpus import chapter_scores, Corpus, question_terms
from .corrections import QUESTIONS
from .files import log, read_json, write_json
from .llm import llm, LLMError, spent_since
from .names import name_pattern, names_of
from .state import load_states, write_derived
from .text import chapter_text, check_quote


def sweep_candidates(corpus, q, near=2, chapters=5, feedback=3):
    terms = question_terms(q)
    base = {t: corpus.idf(t) for t in terms}
    scores = chapter_scores(corpus, q, terms, base)
    weights = dict(base)
    for n in sorted(scores, key=lambda n: -scores[n])[:feedback]:
        for claim, names in corpus.facts.get(n, []):
            if sum(base[t] for t in claim & terms if base[t] >= 0.5) >= 1.5:
                for t in names - terms:
                    weights[t] = corpus.idf(t) / 2
    scores = chapter_scores(corpus, q, set(weights), weights)
    nearby = list(range(q["chapter"] + 1, min(corpus.last, q["chapter"] + near) + 1))
    ranked = sorted(scores, key=lambda n: (-scores[n], n))
    passages = []
    for n in sorted(list(dict.fromkeys(nearby + ranked))[:chapters]):
        hits = corpus.best_windows(terms, base, n, 2 if n in nearby else 1) + corpus.best_windows(set(weights), weights, n, 1)
        picked = sorted({i for _, i in hits} or {0})
        passages.append({"chapter": n, "texts": [corpus.windows[n][i] for i in picked]})
    return passages


SWEEP_PROMPT = """Below are open questions a reader noted while reading a novel, each with the passage that raised it, followed by passages from LATER chapters that may answer it. Each later passage comes with that chapter's synopsis for context. For each question, decide whether one of its later passages answers it.

{items}

Reply with one JSON object: {{"answers": [{{"id": "...", "answered": true or false, "quote": "the words from the passage that show the answer", "chapter": the chapter number of that passage, "answer": "one or two sentences answering the question from that passage and earlier text only"}}]}}, one entry per question.
Rules:
- answered is true only when the text of a passage itself answers the core of the question. A synopsis alone is not enough. A passage that repeats, deepens, or only hints at the mystery is not an answer.
- chapter is the chapter of the passage the quote comes from. When several passages answer the core of the question, choose the earliest; when an earlier passage only narrows it down and a later one answers it, choose the later one.
- answer states only what the text up to that chapter shows. Never use a name, event, or detail from a later passage or from outside the novel.
- quote: one contiguous span of one or two sentences copied exactly, character for character, from a passage of that chapter, at most 300 characters. When the question has two parts answered in different sentences of that chapter, give both spans joined by " ... ". No other ellipses, no paraphrase. This is checked by machine.
"""


def sweep_item(q, passages, synopses):
    lines = [f"ID {q['id']} (raised in chapter {q['chapter']})", f"Question: {q['question']}",
             f"Raising passage: \"{q.get('quote', '')}\"", "Later passages:"]
    for p in passages:
        lines.append(f"[chapter {p['chapter']}] Synopsis: {synopses.get(p['chapter'], '')}")
        lines += [f"<passage chapter=\"{p['chapter']}\">\n{t}\n</passage>" for t in p["texts"]]
    return "\n".join(lines)


def fingerprint(*parts):
    return hashlib.sha1("\n\n".join(parts).encode()).hexdigest()[:16]


def current(decision, stamp):
    if decision.get("verdict") == "error":
        return False
    return decision.get("verdict") == "accept" or decision.get("fingerprint") == stamp


def judge_answer(workdir, kb, q, reply, candidates):
    entry = {"source": "llm", "candidates": candidates}
    if reply.get("answered") is not True:
        return {**entry, "verdict": "unanswered"}
    try:
        n = int(reply.get("chapter"))
    except (TypeError, ValueError):
        n = None
    answer, quote = str(reply.get("answer") or "").strip(), str(reply.get("quote") or "").strip()
    entry.update(chapter=n, answer=answer, quote=quote)
    if n not in candidates:
        return {**entry, "verdict": "reject", "reason": f"chapter {n} is not one of the candidate chapters"}
    later = [e["name"] for e in kb.entities.values() if e["first_chapter"] > n and name_pattern(names_of(e)).search(answer)
             and not any(name_pattern(names_of(e)).search(chapter_text(str(workdir), m)) for m in range(1, n + 1))]
    if later:
        return {**entry, "verdict": "reject", "reason": f"answer names {', '.join(later)}, first seen after chapter {n}"}
    found = check_quote(str(workdir), n, quote)
    entry["quote_ok"] = found["ok"]
    if not found["ok"]:
        return {**entry, "verdict": "reject", "reason": f"quote not found in chapter {n} (ratio {found['ratio']})"}
    verdict = reread(workdir, q, {"answer": answer, "quote": quote}, n)
    if verdict["verdict"] not in ("accept", "reject"):
        return {**entry, "verdict": "error", "reason": verdict.get("error", "")}
    return {**entry, "verdict": verdict["verdict"], "payoff": verdict.get("payoff", ""),
            "context_found": verdict.get("context_found", True)}


def cmd_sweep(args):
    workdir = Path(args.workdir).resolve()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    kb = load_states(workdir, corrections=(QUESTIONS,))
    path = workdir / "sweep.json"
    corpus = Corpus(workdir, kb)
    asked = {q["id"]: (q, sweep_candidates(corpus, q)) for q in kb.open_questions() if q["chapter"] < corpus.last}
    prints = {qid: fingerprint(SWEEP_PROMPT, sweep_item(q, passages, kb.synopses)) for qid, (q, passages) in asked.items()}
    stored = read_json(path, {"questions": {}})["questions"]
    work = [asked[k] for k in asked if not (k in stored and current(stored[k], prints[k])) and (not args.only or k in args.only)][:args.limit]
    todo = [q for q, _ in work]
    redo = {q["id"] for q in todo}
    write_json(path, {"questions": {k: v for k, v in stored.items() if v.get("verdict") != "error" and k not in redo}})
    batches = [work[i:i + args.batch] for i in range(0, len(work), args.batch)]
    lock = threading.Lock()
    log(workdir, f"sweep: {len(todo)} open questions in {len(batches)} batches")

    def run(batch):
        if args.budget and spent_since(workdir, started) >= args.budget:
            return 0
        items = "\n\n".join(sweep_item(q, passages, kb.synopses) for q, passages in batch)
        read = max(p["chapter"] for _, passages in batch for p in passages)
        try:
            reply = llm(workdir, "sweep", SWEEP_PROMPT.format(items=items))
            answers = {str(a.get("id")): a for a in reply.get("answers") or [] if isinstance(a, dict)}
            decided = {q["id"]: {**judge_answer(workdir, kb, q, answers[q["id"]], [p["chapter"] for p in passages]), "shown": read,
                                 "fingerprint": prints[q["id"]]}
                       for q, passages in batch if q["id"] in answers}
        except LLMError as exc:
            log(workdir, f"  sweep batch {batch[0][0]['id']}: {exc}")
            decided = {q["id"]: {"source": "llm", "verdict": "error", "reason": str(exc)} for q, _ in batch}
        with lock:
            current = read_json(path, {"questions": {}})
            current["questions"].update(decided)
            write_json(path, current)
        return len(decided)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        swept = sum(pool.map(run, batches))
    decisions = read_json(path, {"questions": {}})["questions"]
    write_json(path, {"questions": decisions})
    counts = {}
    for s in decisions.values():
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
    kb = load_states(workdir)
    write_derived(workdir, kb)
    log(workdir, f"sweep: decided {swept} of {len(todo)} this run, ${spent_since(workdir, started):.2f}; all decisions {counts}; "
                 f"{len(kb.open_questions())} questions still open or partial")
