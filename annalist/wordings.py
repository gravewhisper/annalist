import re
from pathlib import Path

from .files import log, read_json, state_paths, write_json
from .llm import llm
from .names import function_word_name, name_key

FILE = "wordings.json"
FILLED = ("relate.json", "link.json")
BATCH = 40
KEPT_WORDS = 2

WORDINGS_PROMPT = """A wiki about a novel records each relation between two entries as a sentence "source <type> target <detail>". The wordings below come from an older version that put the whole relation in one wording read as "source <wording> target". Many of them swallow an object, a third party, or a circumstance, so they do not read as a sentence. Split each wording into:
- type: the predicate alone, a verb phrase or a role that reads "source type target" ("suspects", "gave", "member of", "father of");
- detail: what the sentence needs after the target ("of impersonating the baron", "to the innkeeper as payment"), or "" when nothing.

Rules:
- Move the wording's own words; do not reword them or change their letter case.
- A wording that already reads as "source wording target" stays whole as the type, with detail "".
- When the wording's subject is not the source ("father held"), rewrite it as a predicate about the source ("has a father who held"). When that cannot be done, give type "".
- Copy each wording exactly as listed.

WORDINGS:
{wordings}

Reply with one JSON object: {{"wordings": [{{"wording": "...", "type": "...", "detail": "..."}}]}}
"""


SUBJECTS = frozenset("he she it they we i you".split())
POSSESSIVES = frozenset("his her their its my our your".split())
OBJECT_PRONOUNS = frozenset("him her them it me us you".split())
FINITE = frozenset("is was are were has had does did will would can could may might must shall should".split())
CONNECTIVES = frozenset("who whom whose which that where when while because if since until though although how what why but and or not".split())
PREPOSITIONS = frozenset("""to as in of at for with by on from about through after against into via before under over near toward towards
    behind beyond during upon without within between among across around alongside along above below off out up down throughout despite
    per like than according together including except inside outside besides""".split())
DETERMINERS = frozenset("the a an this these those some any no each every all both one two three four five six seven eight nine ten several many most few".split())
IRREGULAR_PAST = frozenset("""went came gave took made found kept left told said held met sent saw knew thought brought bought got ran led lost won
    wrote became began felt heard paid stood taught wore drew fought sought""".split())
OPENERS = CONNECTIVES | PREPOSITIONS | DETERMINERS
UNCOUNTED = OPENERS | SUBJECTS | POSSESSIVES | OBJECT_PRONOUNS | FINITE | frozenset("be been being same".split())


def tokens(text):
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text.lower())


def stems(text):
    return {re.sub(r"(ies|es|s)$", "", re.sub(r"['’]s$", "", w)) for w in tokens(text) if w not in UNCOUNTED and (len(w) > 2 or w.isdigit())}


def past_shaped(word):
    return word in IRREGULAR_PAST or word.endswith("ed")


def present_shaped(word):
    return word.endswith("s") and not word.endswith(("ss", "us", "'s", "’s"))


def verb_shaped(word):
    return word in FINITE or past_shaped(word) or present_shaped(word)


def opens_clause(detail):
    words = tokens(detail)
    head, rest = words[0], words[1:]
    if head in SUBJECTS or ";" in detail:
        return True
    if head in POSSESSIVES:
        return any(w in FINITE or w.endswith("ed") for w in rest)
    if head not in CONNECTIVES and head not in PREPOSITIONS and any(w in FINITE and words[i] not in CONNECTIVES for i, w in enumerate(rest)):
        return True
    if head in OPENERS or head in FINITE or head.endswith("ing"):
        return False
    if detail[0].isupper():
        if head.endswith(("'s", "’s")):
            return any(w in FINITE or past_shaped(w) for w in rest[:2])
        return bool(rest) and verb_shaped(rest[0])
    if past_shaped(head):
        return bool(rest) and (rest[0] == "to" or rest[0] not in PREPOSITIONS)
    return present_shaped(head)


def restates(rtype, target, detail):
    said, named, typed = stems(detail), stems(target), stems(rtype)
    if not said or said <= named | typed:
        return True
    if named and named <= said and (typed & said or all(w.isdigit() for w in said - named - typed)):
        return True
    head, last = tokens(detail)[0], stems(" ".join(tokens(target)[-1:]))
    return head not in PREPOSITIONS and head not in CONNECTIVES and head not in FINITE and bool(last) and last <= said


def fitted(wording, target):
    detail = wording["detail"]
    if tokens(detail) and not opens_clause(detail) and not restates(wording["type"], target, detail):
        return wording
    return {**wording, "detail": ""}


def read_wordings(workdir):
    return read_json(Path(workdir) / FILE, {"wordings": {}})["wordings"]


def worded(rel, wordings):
    plain = {"type": str(rel["type"]).strip(), "detail": str(rel.get("detail") or "").strip()}
    return fitted(plain if "detail" in rel else wordings.get(name_key(rel["type"])) or plain, str(rel["target"]))


def legacy_wordings(workdir):
    rows = [r for path in state_paths(workdir)
            for r in read_json(path, {})["extraction"].get("relations") or []]
    for name in FILLED:
        rows += [r for c in read_json(workdir / name, {"chapters": {}})["chapters"].values() for r in c["relations"]]
    return {name_key(r["type"]) for r in rows if isinstance(r, dict) and "detail" not in r and str(r.get("type") or "").strip()}


def whole(phrases, flags=0):
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(phrases, key=len, reverse=True))) + r")(?!\w)", flags)


def casing(entities, book):
    names = {}
    for name in [e["name"] for e in entities] + [a for e in entities for a in e["aliases"]]:
        if not function_word_name(name):
            names.setdefault(name.lower(), name)
        for word in name.split():
            if word[0].isupper() and not function_word_name(word):
                names.setdefault(word.lower(), word)
    common = {w for w in re.findall(r"\w+", book) if w.islower()}
    candidates = [k for k in names if set(re.findall(r"\w+", k)) <= common]
    written = set(whole(candidates).findall(book)) if candidates else set()
    cased = {k: v for k, v in names.items() if k not in written}
    if not cased:
        return lambda text: text
    pattern = whole(cased, re.I)
    return lambda text: pattern.sub(lambda m: cased[m.group(0).lower()], text)


def check_split(reply):
    items = reply.get("wordings")
    if not isinstance(items, list):
        return "no wordings list"
    if any(not isinstance(i, dict) or not isinstance(i.get("type"), str) or not isinstance(i.get("detail", ""), str) for i in items):
        return "every item needs a wording, a type, and a detail, all strings"
    return None


def read_batch(workdir, wordings):
    reply = llm(workdir, "wordings", WORDINGS_PROMPT.format(wordings="\n".join(f"- {w}" for w in wordings)), check=check_split)
    given = {name_key(i.get("wording") or ""): {"type": i["type"].strip(), "detail": i.get("detail", "").strip()}
             for i in reply["wordings"]}
    return {w: given.get(w) or {"type": w, "detail": ""} for w in wordings}


def cmd_wordings(args):
    workdir = Path(args.workdir).resolve()
    known = read_wordings(workdir)
    legacy = legacy_wordings(workdir)
    unread = sorted(w for w in legacy if w not in known and len(w.split()) > KEPT_WORDS)
    for i in range(0, len(unread), BATCH):
        known.update(read_batch(workdir, unread[i:i + BATCH]))
    book = "\n".join(p.read_text(encoding="utf-8") for p in sorted((workdir / "chapters").glob("*.txt")))
    recase = casing(read_json(workdir / "entities.json", []), book)
    out = {w: {"type": recase(e["type"]), "detail": recase(e["detail"])} for w, e in known.items()}
    out.update({w: {"type": recase(w), "detail": ""} for w in legacy if w not in out and recase(w) != w})
    write_json(workdir / FILE, {"wordings": dict(sorted(out.items()))})
    log(workdir, f"wordings: {len(legacy)} legacy wordings, {len(unread)} read")
