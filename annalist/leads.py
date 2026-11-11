from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .corpus import stems
from .files import read_json, write_json
from .llm import cached_llm
from .state import lead_key, load_states, write_derived


REPEATS_PROMPT = """Each item below is a pair of questions a reader noted while reading a novel: an earlier question that was still open, and a later one raised a chapter or two after it, each with the passage that raised it. Decide for each pair whether the later question asks the same mystery again, so that one answer would settle both, even if it adds details the later chapter showed. It is not the same when it asks about another person, thing, cause, or event, or asks how the mystery connects to something else, even when it names the same people or scene.

{items}

Reply with one JSON object: {{"pairs": [{{"id": "...", "same": true or false, "reason": "one sentence"}}]}}, one entry per item.
"""


LEADS_PROMPT = """Each item below is a mystery from a novel together with a proposed answer from a later chapter that a reviewer rejected as a full resolution, with the reviewer's reason. Decide for each whether the proposed answer is still a useful partial lead: it answers part of the question, or it points toward an answer that the quoted text itself supports, even if hedged. It is not a lead when it misreads the question, restates the setup, or the quote does not bear on the question.

{items}

Reply with one JSON object: {{"items": [{{"id": "...", "partial": true or false, "lead": "only when partial: one sentence saying what this chapter suggests, keeping the text's own hedging"}}]}}, one entry per item.
"""


def repeat_candidates(kb, span=2, least=2):
    by_chapter, terms = {}, {}
    for q in kb.questions.values():
        by_chapter.setdefault(q["chapter"], []).append(q)
        terms[q["id"]] = stems(q["question"])
    for later in kb.questions.values():
        for n in range(later["chapter"] - span, later["chapter"]):
            for earlier in by_chapter.get(n, []):
                if earlier.get("resolved_chapter", later["chapter"]) >= later["chapter"] and len(terms[earlier["id"]] & terms[later["id"]]) >= least:
                    yield earlier, later


def judge_repeats(workdir, pairs, jobs, batch=25):
    def judge(chunk):
        items = "\n\n".join(f"ID {a['id']}/{b['id']}\nEarlier question (ch{a['chapter']}): {a['question']}\nRaised by: \"{a['quote']}\"\n"
                            f"Later question (ch{b['chapter']}): {b['question']}\nRaised by: \"{b['quote']}\"" for a, b in chunk)
        reply = cached_llm(workdir, "repeats", REPEATS_PROMPT.format(items=items))
        verdicts = {str(v.get("id")): v for v in reply.get("pairs") or [] if isinstance(v, dict)}
        judged = [(a, b, verdicts.get(f"{a['id']}/{b['id']}") or {}) for a, b in chunk]
        return [{"earlier": a["id"], "later": b["id"], "same": v.get("same") is True, "reason": str(v.get("reason") or "").strip()}
                for a, b, v in judged]

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return [v for judged in pool.map(judge, [pairs[i:i + batch] for i in range(0, len(pairs), batch)]) for v in judged]


def cmd_leads(args):
    workdir = Path(args.workdir).resolve()
    path = workdir / "leads.json"
    repeats = judge_repeats(workdir, list(repeat_candidates(load_states(workdir, repeats=False))), args.jobs)
    write_json(path, {**read_json(path, {"leads": {}}), "repeats": repeats})
    kb = load_states(workdir)
    attempts = [(q, r) for q in kb.questions.values() for r in q["rejected"]]
    batches = [attempts[i:i + 25] for i in range(0, len(attempts), 25)]

    def classify(batch):
        items = "\n\n".join(
            f"ID {lead_key(q['id'], r['chapter'])}\nQuestion (ch{q['chapter']}): {q['question']}\n"
            f"Proposed answer (ch{r['chapter']}): {r['answer']}\nQuote: \"{r['quote']}\"\nReviewer: {r.get('reason', '')}"
            for q, r in batch)
        reply = cached_llm(workdir, "leads", LEADS_PROMPT.format(items=items))
        return [i for i in reply.get("items") or [] if isinstance(i, dict)]

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        verdicts = [v for batch in pool.map(classify, batches) for v in batch]
    wanted = {lead_key(q["id"], r["chapter"]) for q, r in attempts}
    leads = {}
    for v in verdicts:
        key = str(v.get("id"))
        if key in wanted:
            leads[key] = {"partial": v.get("partial") is True, "lead": str(v.get("lead") or "").strip(), "source": "llm"}
    write_json(path, {"leads": leads, "repeats": repeats})
    kb = load_states(workdir)
    write_derived(workdir, kb)
    statuses = {}
    for q in kb.questions.values():
        statuses[q["status"]] = statuses.get(q["status"], 0) + 1
    print(f"{sum(r['same'] for r in repeats)} of {len(repeats)} questions raised again folded into the open one; "
          f"{len(attempts)} rejected resolutions classified, {sum(v['partial'] for v in leads.values())} partial leads; questions: {statuses}")
