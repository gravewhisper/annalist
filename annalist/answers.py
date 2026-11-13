import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .audit import reread_context
from .corrections import QUESTIONS
from .ending import checked_quotes, Finder
from .files import log, read_json, state_paths, write_json
from .llm import cached_llm, LLMError, spent_since
from .state import load_states, write_derived
from .sweep import fingerprint, judge_answer
from .text import chapter_text, check_quote, locate_quote


ANSWERS_PROMPT = """A reader is partway through a novel that goes on after chapter {to}, the last chapter of {name}. Below are questions they noted while reading that were still open at that point. Each comes with the passage that raised it, any leads found so far, and passages from chapters up to {to} that may bear on it, each with its chapter's synopsis. The passages include the rest of the chapter that raised the question, and may include a few from the chapters before it. Judge each question on its own passages: some are answered in them, some only narrowed down, some left for later.

{items}

For each question, report what its passages show, if anything:
- "answer": a passage whose own text answers the core of the question. Give its "chapter", a "quote" from it, and "answer", one or two sentences answering the question from that passage and earlier text only. It answers the core when it names who or what the question asks for, or when a character reaches a firm conclusion that the story then treats as settled; when the passages together leave only one reading, quote the passage that completes it. A synopsis alone is not enough; a passage that repeats, deepens, or only hints at the mystery is not an answer. When several passages answer it, choose the earliest.
- "lead": a passage, earlier than the answer if there is one, that narrows the question down without answering it. It may come from before the question was raised, such as an earlier scene that shows the person or thing the question asks about. Give its "chapter", a "quote" from it, and "text", one sentence saying what it suggests, keeping the text's own hedging. Leave it out when it only repeats the setup or a lead already listed.
- "premise": the question takes for granted something the text shows is not so, such as a person, object or event that the passages show does not exist or did not happen. A question asking whether someone is real, or who fills a role, rests on a false premise when the text shows that no one fills that role, for example because it is a cover story or an invented name; report that as premise, not answer. Give "explanation", one or two sentences, and "quotes" that show it. Only when the text shows the assumption false, never because the text is silent about it.

Reply with one JSON object: {{"results": [{{"id": "...", "answer": {{"chapter": n, "quote": "...", "answer": "..."}} or null, "lead": {{"chapter": n, "quote": "...", "text": "..."}} or null, "premise": {{"explanation": "...", "quotes": [{{"chapter": n, "quote": "..."}}]}} or null}}]}}, one entry per question.
Rules:
- answer, lead and premise state only what the text up to their chapter shows, or up to the chapter that raised the question for a passage from before it. Never use a name, event, or detail from a later passage or from outside the novel.
- every quote is one contiguous span of one or two sentences copied exactly, character for character, from a passage of that chapter, at most 300 characters. No ellipses, no paraphrase. This is checked by machine.
"""


PREMISE_PROMPT = """You are checking whether a reader's question about a novel rests on a false assumption. Use only the text below.

QUESTION (raised in chapter {qchapter}): {question}

SETUP PASSAGE from chapter {qchapter} (the raising quote is marked with >>> <<<):
<setup>
{context}
</setup>

PROPOSED FINDING: the question takes for granted something the novel shows is not so. {explanation}

EVIDENCE:
{evidence}

Does the evidence itself show that what the question takes for granted is false? Reject when the evidence only leaves the assumption unconfirmed, when it may still turn out true later in the story, or when the question does not in fact assume it. Reply with one JSON object:
{{"verdict": "accept" or "reject", "reason": "one or two sentences"}}
"""


SETTLED = ("answered", "premise-false")
MAX_SWAPPED_CHAPTERS = 2
PROMPT_STAMP = fingerprint(ANSWERS_PROMPT)


def verdict_basis(v, q):
    return fingerprint(ANSWERS_PROMPT, f"{v['name']}\n{v['to']}", q["question"], q.get("quote", ""), *[f"{l['chapter']}:{l['text']}" for l in q["leads"]],
                       *[f"again {a['chapter']}:{a['question']}" for a in q.get("again", [])])


def reusable(old, basis, chapters):
    swapped = set(old.get("candidates", [])) ^ set(chapters)
    return old.get("verdict") != "error" and old.get("basis", basis) == basis and len(swapped) <= 2 * MAX_SWAPPED_CHAPTERS


def answers_item(q, passages, synopses):
    lines = [f"ID {q['id']} (raised in chapter {q['chapter']})", f"Question: {q['question']}", f"Raising passage: \"{q.get('quote', '')}\""]
    lines += [f"Asked again in chapter {a['chapter']}: {a['question']}" for a in q.get("again", [])]
    lines += [f"Lead from chapter {l['chapter']}: {l['text']}" for l in q["leads"]]
    lines.append("Passages:")
    for p in passages:
        before = ", before the question was raised" if p.get("before") else ""
        lines.append(f"[chapter {p['chapter']}{before}] Synopsis: {synopses.get(p['chapter'], '')}")
        lines += [f"<passage chapter=\"{p['chapter']}\">\n{t}\n</passage>" for t in p["texts"]]
    return "\n".join(lines)


def rest_of_chapter(workdir, q, passages):
    text = chapter_text(str(workdir), q["chapter"])
    found = locate_quote(text, q.get("quote", ""))
    start = text.rfind("\n\n", 0, found["span"][0]) + 1 if found["ok"] else 0
    rest = "\n".join(p.strip() for p in text[start:].split("\n\n"))
    return [{"chapter": q["chapter"], "texts": [rest]}] + [p for p in passages if p["chapter"] != q["chapter"]]


def checked_lead(workdir, q, raw, last):
    if not isinstance(raw, dict):
        return None
    try:
        n = int(raw.get("chapter"))
    except (TypeError, ValueError):
        return None
    text, quote = str(raw.get("text") or "").strip(), str(raw.get("quote") or "").strip()
    if text and quote and 1 <= n <= last and check_quote(str(workdir), n, quote)["ok"]:
        return {"chapter": n, "text": text, "quote": quote, **({"shown": q["chapter"]} if n < q["chapter"] else {})}
    return None


def confirm_premise(workdir, q, explanation, quotes):
    context, _ = reread_context(workdir, q)
    evidence = "\n".join(f"[chapter {r['chapter']}] \"{r['quote']}\"" for r in quotes)
    prompt = PREMISE_PROMPT.format(qchapter=q["chapter"], question=q["question"], context=context, explanation=explanation, evidence=evidence)
    try:
        reply = cached_llm(workdir, "premise", prompt,
                           check=lambda v: None if v.get("verdict") in ("accept", "reject") else f"no accept or reject verdict: {v.get('verdict')!r}")
    except LLMError as exc:
        return {"verdict": "error", "reason": str(exc)}
    return {"verdict": reply["verdict"], "reason": str(reply.get("reason") or "").strip()}


def judge_premise(workdir, q, raw, last):
    kept, dropped = checked_quotes(workdir, raw.get("quotes"), last)
    explanation = str(raw.get("explanation") or "").strip()
    proposed = {"explanation": explanation, "quotes": kept, **({"dropped_quotes": dropped} if dropped else {})}
    if not kept or not explanation:
        return {"premise_attempt": {**proposed, "verdict": "reject", "reason": "no quote of it was found in the text"}}
    check = confirm_premise(workdir, q, explanation, kept)
    if check["verdict"] == "error":
        return {"verdict": "error", "reason": check["reason"]}
    if check["verdict"] == "reject":
        return {"premise_attempt": {**proposed, **check}}
    return {"verdict": "premise-false", "premise": {"chapter": max([q["chapter"]] + [r["chapter"] for r in kept]),
                                                    "explanation": explanation, "quotes": kept, "reason": check["reason"]}}


def decide(workdir, kb, q, reply, candidates, last):
    entry = {"source": "llm", "candidates": candidates, "verdict": "unanswered"}
    if isinstance(reply.get("premise"), dict):
        entry.update(judge_premise(workdir, q, reply["premise"], last))
    if entry["verdict"] == "unanswered" and isinstance(reply.get("answer"), dict):
        attempt = judge_answer(workdir, kb, q, {**reply["answer"], "answered": True}, candidates)
        entry["attempt"] = attempt
        if attempt["verdict"] == "error":
            return {**entry, "verdict": "error", "reason": attempt.get("reason", "")}
        if attempt["verdict"] == "accept":
            entry.update(verdict="answered", answer={"chapter": max(attempt["chapter"], q["chapter"]), "quote_chapter": attempt["chapter"],
                                                     "answer": attempt["answer"], "quote": attempt["quote"], "payoff": attempt.get("payoff", "")})
    lead = checked_lead(workdir, q, reply.get("lead"), last)
    if lead and (entry["verdict"] != "answered" or lead["chapter"] < entry["answer"]["chapter"]):
        entry["lead"] = lead
    return entry


def kept_lead(entry, old):
    lead = (old or {}).get("lead")
    if not lead or "lead" in entry or entry["verdict"] == "error":
        return entry
    if entry["verdict"] == "answered" and lead["chapter"] >= entry["answer"]["chapter"]:
        return entry
    return {**entry, "lead": lead}


def eligible(workdir, to):
    last = to or len(state_paths(workdir))
    return sorted((v for v in read_json(Path(workdir) / "volumes.json", {"volumes": []})["volumes"] if v["to"] <= last),
                  key=lambda v: v["to"])


def last_judged(before, qid):
    for b in sorted(before, key=lambda b: -b["to"]):
        d = b["questions"].get(qid)
        if d:
            return b["to"] if d.get("verdict") == "unanswered" and d.get("prompt") == PROMPT_STAMP else None
    return None


def came_back(q, since, chapters):
    return (any(n > since for n in chapters) or any(l["chapter"] > since and l.get("by") != "answers" for l in q["leads"])
            or any(a["chapter"] > since for a in q.get("again", [])))


def pending(workdir, kb, v, old, before):
    finder = Finder(workdir, kb)
    opened = kb.open_questions()
    asked = {q["id"] for q in opened}
    keep = {k: d for k, d in old.items() if k not in asked and d.get("verdict") in SETTLED}
    work, carried = [], 0
    for q in opened:
        if q["id"] in keep:
            continue
        stamp = verdict_basis(v, q)
        since = last_judged(before, q["id"])
        passages = rest_of_chapter(workdir, q, finder.candidates(q, chapters=10, after=True, full=5))
        if since is not None and not came_back(q, since, [p["chapter"] for p in passages]):
            keep[q["id"]] = {"source": "carried", "verdict": "unanswered", "since": since, "basis": stamp, "prompt": PROMPT_STAMP}
            carried += 1
            continue
        if since is None:
            passages = finder.earlier(q) + passages
        if q["id"] in old and reusable(old[q["id"]], stamp, [p["chapter"] for p in passages]):
            keep[q["id"]] = old[q["id"]]
        else:
            work.append((q, passages, stamp))
    return keep, work, carried


def ask(workdir, kb, v, batch):
    items = "\n\n".join(answers_item(q, passages, kb.synopses) for q, passages, _ in batch)
    try:
        reply = cached_llm(workdir, "answers", ANSWERS_PROMPT.format(to=v["to"], name=v["name"], items=items))
    except LLMError as exc:
        log(workdir, f"  answers batch {batch[0][0]['id']}: {exc}")
        return {q["id"]: {"source": "llm", "verdict": "error", "reason": str(exc)} for q, _, _ in batch}
    results = {str(r.get("id")): r for r in reply.get("results") or [] if isinstance(r, dict)}
    return {q["id"]: {**decide(workdir, kb, q, results.get(q["id"], {}), [p["chapter"] for p in passages], v["to"]), "basis": stamp,
                      "prompt": PROMPT_STAMP}
            for q, passages, stamp in batch}


def cmd_answers(args):
    workdir = Path(args.workdir).resolve()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = workdir / "answers.json"
    volumes = eligible(workdir, args.to)
    stored = read_json(path, {"boundaries": {}})["boundaries"]
    boundaries = {str(v["to"]): stored.get(str(v["to"]), {"name": v["name"], "to": v["to"], "questions": {}}) for v in volumes}
    write_json(path, {"boundaries": boundaries})
    lock = threading.Lock()
    asked = 0
    for v in volumes:
        key = str(v["to"])
        kb = load_states(workdir, until=v["to"], answers_before=v["to"], corrections=(QUESTIONS,), only_mysteries=True)
        earlier = boundaries[key]["questions"]
        keep, work, carried = pending(workdir, kb, v, earlier, [boundaries[str(u["to"])] for u in volumes if u["to"] < v["to"]])
        boundaries[key] = {"name": v["name"], "to": v["to"], "questions": keep}
        write_json(path, {"boundaries": boundaries})
        batches = [work[i:i + args.batch] for i in range(0, len(work), args.batch)]
        log(workdir, f"answers: {len(work)} of {len(kb.open_questions())} questions open at the end of {v['name']} (ch {v['to']}) "
                     f"to ask in {len(batches)} batches; {carried} kept from an earlier volume end, as no chapter since came back to them")

        def record(batch):
            decided = ask(workdir, kb, v, batch)
            with lock:
                questions = boundaries[key]["questions"]
                questions.update({k: kept_lead(d, earlier.get(k)) for k, d in decided.items()})
                write_json(path, {"boundaries": boundaries})
            return len(decided)

        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            asked += sum(pool.map(record, batches))
    write_derived(workdir, load_states(workdir))
    counts = {}
    for entry in boundaries.values():
        for d in entry["questions"].values():
            counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
    log(workdir, f"answers: asked about {asked} questions this run, ${spent_since(workdir, started):.2f}; all verdicts {counts}")
