import hashlib
import json
import re
import threading
import time
from collections import Counter
from pathlib import Path

from .backends import Fatal, Request, Transient, load_settings, open_backend, prompt_sha1
from .files import append_line, log, read_jsonl, write_json


SYSTEM_PROMPT = "You are a meticulous literary analyst building a reference wiki of a novel. You reply with exactly one JSON object and nothing else."


BACKOFF_S = (60, 120, 300, 600, 720)


ASKED = Counter()
ASKED_LOCK = threading.Lock()


def tally(key):
    with ASKED_LOCK:
        ASKED[key] += 1


class LLMError(Exception):
    pass


class LLMUnavailable(Exception):
    pass


def parse_json_object(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    decoder, objects, i = json.JSONDecoder(strict=False), [], start
    while i >= 0:
        try:
            obj, i = decoder.raw_decode(text, i)
        except ValueError:
            break
        objects.append(obj)
        i = text.find("{", i)
    if objects:
        return objects[-1]
    return without_stray_brackets(escape_stray_quotes(text[start:end + 1]).replace("\\'", "'"))


def without_stray_brackets(text):
    while True:
        try:
            return json.loads(text, strict=False)
        except json.JSONDecodeError as exc:
            if not (exc.msg == "Expecting ',' delimiter" and text[exc.pos:exc.pos + 1] == "]"):
                raise
            text = text[:exc.pos] + text[exc.pos + 1:]


def escape_stray_quotes(text):
    out, in_string, escaped = [], False, False
    for i, ch in enumerate(text):
        if in_string and escaped:
            escaped = False
        elif in_string and ch == "\\":
            escaped = True
        elif ch == '"' and in_string:
            rest = text[i + 1:].lstrip()
            if rest and rest[0] not in ",}]:":
                out.append('\\"')
                continue
            in_string = False
        elif ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


REPAIR_PROMPT = """The text between the markers was meant to be one JSON object, but it does not parse ({error}). Return the same content as one valid JSON object. Fix only the syntax: brackets, braces, commas, colons, quoting, and escaping. Do not add, remove, shorten, or reword any content.

<broken>
{reply}
</broken>
"""


REVISE_PROMPT = """

Your previous reply to the request above was rejected: {error}
Reply again with one JSON object that follows every rule above and fixes this.

<previous>
{reply}
</previous>
"""


def llm(workdir, purpose, prompt, chapter=None, check=None, rejected=None, settings=None):
    tally("fresh")
    settings = settings or load_settings(workdir)
    model = settings.model_for(purpose)
    backend = open_backend(workdir, settings)
    attempt_prompt, mode = prompt, "original"
    if rejected:
        attempt_prompt, mode = prompt + REVISE_PROMPT.format(error=rejected[1], reply=rejected[0]), "revise"
    waits = iter(BACKOFF_S)
    attempt = content_failures = 0
    while True:
        attempt += 1
        started = time.time()
        record = {"purpose": purpose, "chapter": chapter, "attempt": attempt, "mode": mode, "backend": settings.backend,
                  "model": model, "prompt_chars": len(attempt_prompt), "prompt_sha1": prompt_sha1(prompt), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        reply = transient = None
        try:
            reply = backend.complete(Request(system=SYSTEM_PROMPT, prompt=attempt_prompt, model=model, purpose=purpose, chapter=chapter))
        except Transient as exc:
            transient = exc
        except Fatal as exc:
            append_line(Path(workdir) / "calls.jsonl", json.dumps({**record, "error": str(exc)}, ensure_ascii=False))
            raise LLMUnavailable(f"{purpose}: {exc}")
        record["wall_s"] = round(time.time() - started, 2)
        result = content_error = None
        if reply is not None:
            record.update(reply_model=reply.model, usage=reply.usage, total_cost_usd=reply.cost_usd,
                          duration_s=reply.duration_s, **reply.meta)
            try:
                result = parse_json_object(reply.text)
                content_error = check(result) if check else None
            except ValueError as exc:
                content_error = f"unusable reply: {exc}"
            if content_error:
                result = None
                record["reply"] = reply.text
        record["error"] = str(transient) if transient else content_error
        append_line(Path(workdir) / "calls.jsonl", json.dumps(record, ensure_ascii=False))
        if result is not None:
            return result
        if transient:
            wait = next(waits, None)
            if wait is None:
                raise LLMUnavailable(f"{purpose} still failing after backing off {sum(BACKOFF_S)}s: {transient}")
            wait = max(wait, transient.retry_after or 0)
            log(workdir, f"  {purpose} ch{chapter} attempt {attempt}: {transient}; waiting {wait:g}s")
            time.sleep(wait)
            continue
        content_failures += 1
        log(workdir, f"  {purpose} ch{chapter} attempt {attempt} ({mode}): {content_error}")
        if content_failures == 4:
            raise LLMError(f"{purpose} gave unusable replies four times; the last was rejected because {content_error}")
        if mode == "original" and content_error.startswith("unusable reply"):
            attempt_prompt, mode = REPAIR_PROMPT.format(error=content_error, reply=reply.text), "repair"
        elif mode != "repair" and not content_error.startswith("unusable reply"):
            attempt_prompt, mode = prompt + REVISE_PROMPT.format(error=content_error, reply=reply.text), "revise"
        else:
            attempt_prompt, mode = prompt, "original"


def cache_key(purpose, text):
    return f"{purpose}-{hashlib.sha1(text.encode()).hexdigest()[:16]}.json"


def cache_paths(workdir, settings, purpose, prompt):
    model = settings.model_for(purpose)
    current = Path(workdir) / "cache" / cache_key(purpose, f"{settings.backend}\n{model}\n{prompt}")
    legacy = Path(workdir) / "cache" / cache_key(purpose, prompt)
    return [current, legacy] if settings.backend == "claude-cli" else [current]


def cached_reply(workdir, purpose, prompt, settings=None):
    for path in cache_paths(workdir, settings or load_settings(workdir), purpose, prompt):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["reply"]
    return None


def cached_llm(workdir, purpose, prompt, check=None, chapter=None, settings=None):
    settings = settings or load_settings(workdir)
    reply = cached_reply(workdir, purpose, prompt, settings)
    error = check(reply) if reply is not None and check else None
    if reply is not None and not error:
        tally("cached")
        return reply
    if error:
        log(workdir, f"  {purpose}: cached reply rejected: {error}")
    reply = llm(workdir, purpose, prompt, chapter=chapter, check=check,
                rejected=(json.dumps(reply, ensure_ascii=False), error) if error else None, settings=settings)
    write_json(cache_paths(workdir, settings, purpose, prompt)[0],
               {"purpose": purpose, "backend": settings.backend, "model": settings.model_for(purpose), "reply": reply})
    return reply


def spent_since(workdir, started):
    return sum(c.get("total_cost_usd") or 0 for c in read_jsonl(Path(workdir) / "calls.jsonl") if c.get("ts", "") >= started)
