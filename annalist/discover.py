import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .book import load_book
from .files import log, write_json
from .llm import cached_llm
from .names import function_word_name, LEADING_WORDS, name_tokens, name_words, names_of, singular
from .state import load_states, write_derived
from .template import ENTITY_TYPES
from .text import chapter_text, text_window

WORD = r"[A-Z][\w’'-]+"
OF = rf"\s(?:of\s(?:the\s)?|de\s){WORD}(?:\s{WORD})*"
NAME = re.compile(rf"{WORD}(?:\s{WORD})*(?:{OF}(?:\s(?:and|for)\s{WORD}(?:\s{WORD})*|{OF})*)?")
OPENERS = re.compile(r"(?:[.!?“”\"‘’(—:]\s*|\n[ \t]*)$")

DISCOVER_PROMPT = """A wiki is being built from a novel. The names below recur in the text but have no wiki entry yet. Each comes with the passage where it first appears.

Choose the ones that name a specific thing in the story a reader might look up: a place, an organization, a character, an object, an event, or another named thing. Leave out words capitalized for other reasons: pronouns, interjections, contractions, months, nationalities and languages, a family surname in the plural when the family is not a group in the story, and God or Heaven used as an exclamation.

TYPES:
{types}

CANDIDATES:
{candidates}

Reply with one JSON object: {{"entries": [{{"id": "C1", "type": "one of the types", "summary": "one sentence on what it is, from its passage alone"}}]}}, listing only the candidates that deserve an entry.
"""


def candidates(workdir, kb, min_chapters=2):
    known = [name_tokens(n) for e in kb.entities.values() for n in names_of(e) if name_tokens(n)]
    forms = {tuple(map(singular, name_words(n))) for e in kb.entities.values() for n in names_of(e)}
    found = {}
    for n in sorted(kb.synopses):
        text = chapter_text(workdir, n)
        for m in NAME.finditer(text):
            before = text[max(0, m.start() - 3):m.start()]
            name = re.sub(r"['’]s?$", "", m.group(0))
            head, _, rest = name.partition(" ")
            article = head.lower() in LEADING_WORDS and rest[:1].isupper()
            if (not before.strip() or OPENERS.search(before)) and not article:
                continue
            name = rest if article else name
            if function_word_name(name):
                continue
            entry = found.setdefault(tuple(map(singular, name_words(name))),
                                     {"name": name, "chapters": [], "passage": text_window(text, m.start(), m.end(), 200)})
            if n not in entry["chapters"]:
                entry["chapters"].append(n)
    return [c for key, c in found.items()
            if len(c["chapters"]) >= min_chapters and (toks := name_tokens(c["name"])) and key not in forms
            and not any(toks <= k or (k <= toks and 2 * len(k) >= len(toks)) for k in known)]


BOOK_TYPE = "an element of this book's power or magic system that the book itself calls by this word"


def judge(workdir, batch):
    types = {**{name: BOOK_TYPE for name in load_book(workdir)["power_types"]}, **{t.name: t.description for t in ENTITY_TYPES.values()}}
    lines = [f"- C{i} \"{c['name']}\" (named in {len(c['chapters'])} chapters): \"{c['passage']}\""
             for i, c in enumerate(batch, 1)]
    reply = cached_llm(workdir, "discover", DISCOVER_PROMPT.format(
        types="\n".join(f"- {name}: {description}" for name, description in types.items()), candidates="\n".join(lines)),
        check=lambda r: None if isinstance(r.get("entries"), list) else "no entries list")
    kept = []
    for e in reply["entries"]:
        i = str(e.get("id") or "").removeprefix("C") if isinstance(e, dict) else ""
        if i.isdigit() and 1 <= int(i) <= len(batch) and e.get("type") in types:
            c = batch[int(i) - 1]
            kept.append({"name": c["name"], "type": e["type"], "summary": str(e.get("summary") or "").strip(),
                         "chapter": c["chapters"][0]})
    return kept


def cmd_discover(args, batch=80):
    workdir = Path(args.workdir).resolve()
    found = candidates(workdir, load_states(workdir, merges=False, discovered=False, filled=()))
    by_chapter = {}
    for c in found:
        by_chapter.setdefault(c["chapters"][0], []).append(c)
    batches = [group[i:i + batch] for group in by_chapter.values() for i in range(0, len(group), batch)]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        kept = [e for judged in pool.map(lambda b: judge(workdir, b), batches) for e in judged]
    names = {e["name"] for e in kept}
    write_json(workdir / "discover.json", {"entities": kept, "rejected": [c["name"] for c in found if c["name"] not in names]})
    log(workdir, f"discover: {len(kept)} of {len(found)} recurring names without an entry added")
    write_derived(workdir, load_states(workdir))
