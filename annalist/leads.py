from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .files import write_json
from .llm import cached_llm
from .state import lead_key, load_states, write_derived


LEADS_PROMPT = """Each item below is a mystery from a novel together with a proposed answer from a later chapter that a reviewer rejected as a full resolution, with the reviewer's reason. Decide for each whether the proposed answer is still a useful partial lead: it answers part of the question, or it points toward an answer that the quoted text itself supports, even if hedged. It is not a lead when it misreads the question, restates the setup, or the quote does not bear on the question.

{items}

Reply with one JSON object: {{"items": [{{"id": "...", "partial": true or false, "lead": "only when partial: one sentence saying what this chapter suggests, keeping the text's own hedging"}}]}}, one entry per item.
"""


def cmd_leads(args):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir)
    path = workdir / "leads.json"
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
    write_json(path, {"leads": leads})
    kb = load_states(workdir)
    write_derived(workdir, kb)
    statuses = {}
    for q in kb.questions.values():
        statuses[q["status"]] = statuses.get(q["status"], 0) + 1
    print(f"{len(attempts)} rejected resolutions classified, {sum(v['partial'] for v in leads.values())} partial leads; questions: {statuses}")
