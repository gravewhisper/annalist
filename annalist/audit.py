from .files import log
from .llm import llm, LLMError
from .state import parse_sourcing
from .text import chapter_text, locate_quote


SUPPORT_PROMPT = """You are auditing the citations of a wiki about a novel. Each item below is a claim followed by the quotes offered as its only evidence. Judge every claim against its own quotes ALONE. Ignore what you know or could guess from anywhere else, including the other items.

- "supported": every part of the claim (each person, action, cause, amount, purpose, time, place, and relationship) is stated or directly shown in its quotes. Paraphrase is fine, and a pronoun in a quote may be taken to mean the claim's subject.
- "trim": part of the claim is shown and part is not. Give "claim": the claim rewritten to keep only what the quotes show.
- "unsupported": the quotes do not show the core of the claim.
A claim tagged belief or implied only needs its quotes to show that belief or that strong suggestion. Relations (ids starting with R) are only supported or unsupported.

{items}

Reply with one JSON object: {{"verdicts": [{{"id": "F1", "verdict": "supported" or "trim" or "unsupported", "claim": "only for trim"}}]}}, one verdict per item.
"""


VERDICTS = ("supported", "trim", "unsupported")


def audit_items(workdir, label, ask, prompt, items, rounds=3):
    found = {}
    for _ in range(rounds):
        pending = [(iid, text) for iid, text in items if iid not in found]
        if not pending:
            break
        if len(pending) < len(items):
            log(workdir, f"  {label}: re-asking {len(pending)} ids the reply left out")
        try:
            reply = ask(prompt.format(items="\n\n".join(text for _, text in pending)))
        except LLMError as exc:
            return {**found, "error": str(exc)}
        wanted = {iid for iid, _ in pending}
        for v in reply.get("verdicts") if isinstance(reply.get("verdicts"), list) else []:
            if isinstance(v, dict) and str(v.get("id")) in wanted and v.get("verdict") in VERDICTS:
                found[str(v["id"])] = {"verdict": v["verdict"], "claim": v.get("claim")}
    missing = [iid for iid, _ in items if iid not in found]
    if missing:
        log(workdir, f"  {label}: no verdict for {missing} after {rounds} rounds; left unaudited")
    return found


def audit_support(workdir, out, n):
    items = []
    for i, f in enumerate(out.get("facts") or [], 1):
        if isinstance(f, dict):
            items.append((f"F{i}", f"[{f.get('status', 'stated')}] {f.get('entity')}: {f.get('claim')}", f))
    for i, r in enumerate(out.get("relations") or [], 1):
        if isinstance(r, dict):
            detail = f" {r['detail']}" if r.get("detail") else ""
            items.append((f"R{i}", f"[{r.get('status', 'stated')}] {r.get('source')} {r.get('type')} {r.get('target')}{detail}", r))
    return audit_items(workdir, f"support ch{n}", lambda p: llm(workdir, "support", p, chapter=n), SUPPORT_PROMPT, [
        (iid, f"{iid} {label}\n" + "\n".join(f"  > {q}" for q in parse_sourcing(raw)["quotes"])) for iid, label, raw in items])


REREAD_PROMPT = """You are checking whether a novel pays off an earlier setup. Use only the text below.

QUESTION (raised in chapter {qchapter}): {question}

SETUP PASSAGE from chapter {qchapter} (the raising quote is marked with >>> <<<):
<setup>
{context}
</setup>

PROPOSED RESOLUTION from chapter {rchapter}:
Answer: {answer}
Resolving quote: "{rquote}"

Reread the setup with the resolution in mind. Does the resolving passage genuinely answer the question raised by the setup? Reply with one JSON object:
{{"verdict": "accept" or "reject", "payoff": "two or three sentences linking the setup detail to its resolution, naming what the earlier passage hinted at; if rejecting, say why"}}
"""


def reread(workdir, q, r, n):
    context, found = reread_context(workdir, q)
    try:
        verdict = llm(workdir, "reread", REREAD_PROMPT.format(
            qchapter=q["chapter"], question=q["question"], context=context, rchapter=n,
            answer=r.get("answer", ""), rquote=r.get("quote", "")), chapter=n,
            check=lambda v: None if v.get("verdict") in ("accept", "reject") else f"no accept or reject verdict: {v.get('verdict')!r}")
    except LLMError as exc:
        return {"verdict": "error", "error": str(exc)}
    return {"verdict": verdict["verdict"], "payoff": verdict.get("payoff", ""), "context_found": found}


def reread_context(workdir, question, radius=750):
    text = chapter_text(workdir, question["chapter"])
    found = locate_quote(text, question["quote"])
    if not found["span"] or not found["ok"]:
        return f">>>{question['quote']}<<<\n(The surrounding text could not be located in chapter {question['chapter']}.)", False
    start, end = found["span"]
    lo, hi = max(0, start - radius), min(len(text), end + radius)
    return text[lo:start] + ">>>" + text[start:end] + "<<<" + text[end:hi], True
