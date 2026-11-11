import hashlib
import math
import re
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .backends import load_settings
from .corrections import absorbed_part, blockers, claims, find_question, profile_group, PROOFREAD_FILE
from .families import read_families, relation_family
from .files import log, read_json, write_json
from .llm import BudgetSpent, cached_llm, cached_reply, spent_since
from .names import name_key
from .profile import page_profiles
from .state import load_states, UNRESOLVED
from .template import CHARACTER_FIELDS, CHARACTER_LISTS, ENTITY_TYPES
from .text import chapter_text, check_quote


PURPOSE = "proofread"
LISTS = ("entries", "relations", "drop_relations", "questions")
STATUSES = ("stated", "implied", "belief")

CHARS_PER_TOKEN = 2.9
WINDOW_TOKENS = 1_000_000
REPLY_TOKENS = 48_000
SLICE_TOKENS = 100_000
PART_TOKENS = WINDOW_TOKENS - REPLY_TOKENS - SLICE_TOKENS


HEAD = """Below is the full text of chapters {first} to {last} of a novel, {scope}. The novel goes on after chapter {last}.

<book>
{book}
</book>
"""


TASK = """
A reference wiki of this novel was built by a reader who saw one chapter at a time and only a short list of the entries so far. So it makes mistakes that a reader who knows the whole text above would not make, such as:
- a rank, title, office, or kind filed under the group, place, or person it belongs to, or under another wrong type;
- a page for a description, such as "the bespectacled man", never joined to the named person the text shows it is, or two pages for one person, place, or thing;
- an ordinary word or phrase filed as a person, god, place, or thing of its own;
- an infobox value that is wrong, or missing where the text states it;
- a tie between two entries that is wrong, or missing where the text states it;
- a question left open that the text answers, or a question that is no real mystery.

Below is one part of that wiki as it stands after chapter {last}: the {title}. An entry gives its name, its [type], the chapters it spans, its other names, the pages joined into it, its summary, its infobox values with the chapter of each, its facts from chapters {first} to {last}, and its ties from those chapters as "source | wording | target". A question gives its id, the chapter that raised it, whether it is open or answered, and its leads or answer.

<wiki>
{slice}
</wiki>

Review this part of the wiki against the text above, as a careful reader who has just finished chapter {last}. Propose a correction only where the text shows that the wiki is wrong, or that it lacks something a reader of a fan wiki would want; leave everything else alone. Reply with one JSON object holding four lists, each row one correction, and an empty list where you have none:

{{"entries": [...], "relations": [...], "drop_relations": [...], "questions": [...]}}

Rows of "entries", one change each:
- join two pages that are one person, place, or thing: {{"name": "<page>", "same_as": "<the page it is part of>", "chapter": n, "quotes": ["..."], "why": "..."}}. chapter is the first chapter from which a reader can tell they are one, and the quote from it is the clue.
- file an entry under its right type: {{"name": "...", "type": "<one of: {types}>", "chapter": n, "quotes": ["..."], "why": "..."}}, the quote showing what it is.
- give a page the name the text reveals for it: {{"name": "...", "title": "<name>", "title_chapter": n, "quotes": ["..."], "why": "..."}}, title_chapter being the chapter that reveals it.
- set a character's infobox value from a chapter: {{"name": "...", "fields": {{"<field>": [{{"chapter": n, "value": "...", "quotes": ["..."]}}]}}, "why": "..."}}. The fields are {fields}. A value for a chapter that already has one replaces it.
- remove a wrong infobox value: {{"name": "...", "drop": {{"<field>": [{{"chapter": n, "value": "<the value as the wiki shows it>"}}]}}, "why": "..."}}.
A row of "relations" adds a missing tie: {{"source": "...", "target": "...", "type": "<a short wording, such as sister of>", "status": "stated, implied, or belief", "chapter": n, "quotes": ["..."], "why": "..."}}.
A row of "drop_relations" removes a wrong tie, giving its source, wording, target, and chapter exactly as the wiki shows them: {{"source": "...", "target": "...", "type": "...", "chapter": n, "why": "..."}}.
A row of "questions" answers a question: {{"id": "Q...", "chapter": n, "answer": "...", "quotes": ["..."]}}, chapter being the chapter whose text answers it; or dismisses a question that is no real mystery: {{"id": "Q...", "dismiss": true, "why": "..."}}.

Rules:
- Every chapter you give is one of chapters {first} to {last}, and the text up to that chapter shows what you claim. Never use what a later chapter says, or anything from outside the text above.
- An answer, value, title, or tie says only what a reader knows at its chapter, in words the text has used by then.
- Name an entry as the wiki writes it, by its name or one of its other names. An entry not in this part of the wiki may be named as the text names it.
- Every quote is one contiguous span of one or two sentences copied exactly, character for character, from that chapter, at most 300 characters. No ellipses, no paraphrase. A machine checks each quote, and drops a row whose quote is not in its chapter.
- "why" is one sentence for the person who checks the wiki.
"""


def tokens(text):
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def chapter_block(workdir, n, title):
    return f'<chapter n="{n}" title="{title}">\n{chapter_text(str(workdir), n)}\n</chapter>'


def plan_parts(sizes, budget=PART_TOKENS):
    parts, current, used = [], [], 0
    for n, size in sizes:
        if current and used + size > budget:
            parts.append((current[0], current[-1]))
            current, used = [], 0
        current.append(n)
        used += size
    return parts + ([(current[0], current[-1])] if current else [])


@dataclass(frozen=True)
class Slice:
    key: str
    title: str
    text: str


GROUPS = {
    "characters": "characters",
    "powers": "entries of the book's own types, and its ladders",
    "world": "places, organizations, and other entries",
    "mysteries": "questions a reader noted",
}


def group_of(kb, entry):
    return "characters" if entry["type"] == "character" else "powers" if entry["type"] in kb.power_types else "world"


def shown(rows, until):
    return [o for o in rows if o.get("quote_ok") and o["chapter"] <= until and o.get("shown", o["chapter"]) <= until]


def infobox(page, until):
    values = [(key, shown(rows, until)) for group in ("fields", "extra", "lists") for key, rows in (page or {}).get(group, {}).items()]
    return " | ".join(f"{key}: " + "; ".join(f"{o['value']} (ch{o['chapter']})" for o in rows) for key, rows in values if rows)


def tie_line(r):
    detail = f"; detail: {r['detail']}" if r.get("detail") else ""
    return f"- ch{r['chapter']} tie: {r['source']} | {r['type']} | {r['target']} ({r['status']}{detail})"


def entry_block(entry, facts, ties, page, until):
    lines = [f"## {entry['name']} [{entry['type']}], chapters {entry['first_chapter']}-{entry['last_chapter']}"]
    if entry["aliases"]:
        lines.append("Also called: " + "; ".join(entry["aliases"]))
    lines += [f"Joined from ch{a['chapter']}: {a['name']}" for a in entry.get("absorbed", [])]
    if entry.get("title"):
        lines.append(f"Page title: {entry['title']['name']}" + (f" from ch{entry['title']['chapter']}" if "chapter" in entry["title"] else ""))
    if entry["summary"]:
        lines.append(f"Summary: {entry['summary']}")
    box = infobox(page, until)
    if box:
        lines.append(f"Infobox: {box}")
    lines += [f"- ch{f['chapter']}: {f['claim']}" for f in facts]
    lines += [tie_line(r) for r in ties]
    return "\n".join(lines)


def question_block(q):
    status = {"resolved": f"answered ch{q.get('resolved_chapter')}", "premise-false": "false premise"}.get(q["status"], "open")
    lines = [f"## {q['id']} (raised ch{q['chapter']}, {status}): {q['question']}"]
    lines += [f"- lead ch{lead['chapter']}: {lead['text']}" for lead in q["leads"]]
    if q["status"] == "resolved":
        lines.append(f"- answer: {q['answer']}")
    return "\n".join(lines)


def ladder_block(workdir, until):
    lines = []
    for row in read_json(Path(workdir) / "ladders.json", []):
        steps = [s for s in row["steps"] if s["chapter"] <= until]
        if steps and row["group"]:
            lines.append(f"- {row['group']}: " + "; ".join(f"{s['rank']} {s['entry']} (ch{s['chapter']})" for s in steps))
    return "## Ladders\n" + "\n".join(lines) if lines else ""


def bucketed(items, budget):
    total = sum(tokens(text) for _, text in items)
    count = max(1, math.ceil(total / budget))
    while True:
        buckets = [[] for _ in range(count)]
        for key, text in items:
            buckets[int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % count].append(text)
        if count >= len(items) or all(sum(map(tokens, b)) <= budget for b in buckets):
            return [b for b in buckets if b]
        count += 1


def wiki_items(workdir, kb, pages, first, last):
    facts, ties = {}, {}
    for f in kb.facts:
        if first <= f["chapter"] <= last:
            facts.setdefault(f["entity"], []).append(f)
    for r in kb.relations:
        if first <= r["chapter"] <= last:
            ties.setdefault(r["source"], []).append(r)
    items = {group: [] for group in GROUPS}
    for name, e in sorted(kb.entities.items(), key=lambda kv: (kv[1]["first_chapter"], kv[0])):
        latest = max([e["last_chapter"]] + [x["chapter"] for x in facts.get(name, []) + ties.get(name, [])])
        if e["first_chapter"] <= last and latest >= first:
            items[group_of(kb, e)].append((name, entry_block(e, facts.get(name, []), ties.get(name, []), pages.get(name), last)))
    ladders = ladder_block(workdir, last)
    if ladders:
        items["powers"].append(("ladders", ladders))
    for q in sorted(kb.questions.values(), key=lambda q: q["id"]):
        if q["chapter"] <= last and (q["status"] in UNRESOLVED or q["chapter"] >= first or (q.get("resolved_chapter") or 0) >= first):
            items["mysteries"].append((q["id"], question_block(q)))
    return items


def slices(items, budget=SLICE_TOKENS):
    out = []
    for group, entries in items.items():
        buckets = bucketed(entries, budget) if entries else []
        for k, texts in enumerate(buckets, 1):
            part = f", part {k} of {len(buckets)}" if len(buckets) > 1 else ""
            out.append(Slice(f"{group}-{k}", GROUPS[group] + part, "\n\n".join(texts)))
    return out


WORD = re.compile(r"[a-z]+")


class Review:
    def __init__(self, workdir, kb, pages, book):
        self.workdir, self.kb, self.pages = workdir, kb, pages
        self.types = sorted(ENTITY_TYPES) + sorted(kb.power_types)
        self.fields = {**{k: f.values for k, f in {**CHARACTER_FIELDS, **CHARACTER_LISTS}.items()},
                       **{k: () for k in (book.get("extra_fields") or {})}}
        self.readings = read_families(workdir)

    @cached_property
    def first_use(self):
        first = {}
        for c in sorted(read_json(self.workdir / "chapters.json", []), key=lambda c: c["index"]):
            for w in set(WORD.findall(chapter_text(str(self.workdir), c["index"]).lower())):
                first.setdefault(w, c["index"])
        return first

    def later_words(self, text, chapter):
        return sorted(w for w in set(WORD.findall(text.lower())) if self.first_use.get(w, 0) > chapter)

    def quoted(self, row, chapter):
        quotes = row.get("quotes")
        if not isinstance(quotes, list) or not any(isinstance(q, str) and check_quote(str(self.workdir), chapter, q)["ok"] for q in quotes):
            return f"no quote found in chapter {chapter}"
        return None

    def entry(self, name):
        return self.kb.resolve(name) if isinstance(name, str) and name.strip() else None

    def dated(self, row, key, part, *texts):
        n = row.get(key)
        if not isinstance(n, int) or not part[0] <= n <= part[1]:
            return f"{key} {n!r} is outside chapters {part[0]}-{part[1]}"
        problem = self.quoted(row, n)
        later = self.later_words(" ".join(texts), n) if not problem else []
        return problem or (f"uses {', '.join(later)}, which the book first uses after chapter {n}" if later else None)

    def join(self, row, part):
        key, page = self.entry(row["name"]), self.entry(row["same_as"])
        if key is None or page is None:
            return f"names no entry {row['name'] if key is None else row['same_as']!r}"
        if key == page:
            return "already the same page"
        if absorbed_part(self.kb.entities[key], row["name"]) and name_key(row["name"]) != name_key(key):
            return "already part of another page"
        first = max(self.kb.entities[key]["first_chapter"], self.kb.entities[page]["first_chapter"])
        if isinstance(row["chapter"], int) and row["chapter"] < first:
            return f"chapter {row['chapter']} is before one of them first appears"
        return self.dated(row, "chapter", part, row["same_as"])

    def retype(self, row, part):
        key = self.entry(row["name"])
        if key is None:
            return f"names no entry {row['name']!r}"
        if row["type"] not in self.types:
            return f"type {row['type']!r} is not one of the wiki's types"
        if row["type"] == self.kb.entities[key]["type"]:
            return f"already filed as {row['type']}"
        return self.dated(row, "chapter", part)

    def title(self, row, part):
        if self.entry(row["name"]) is None:
            return f"names no entry {row['name']!r}"
        if not isinstance(row["title"], str) or not row["title"].strip():
            return "gives no title"
        return self.dated(row, "title_chapter", part, row["title"])

    def value(self, row, part):
        key = self.entry(row["name"])
        (field, (value,)), = row["fields"].items()
        if key is None:
            return f"names no entry {row['name']!r}"
        if self.kb.entities[key]["type"] != "character":
            return f"{key} is not a character, and only characters have an infobox"
        if field not in self.fields:
            return f"{field!r} is not an infobox field"
        if not isinstance(value, dict) or not str(value.get("value") or "").strip():
            return "gives no value"
        if self.fields[field] and str(value["value"]).strip().lower() not in self.fields[field]:
            return f"{field} must be one of {', '.join(self.fields[field])}"
        return self.dated(value, "chapter", part, str(value["value"]))

    def drop(self, row, part):
        key = self.entry(row["name"])
        (field, (value,)), = row["drop"].items()
        if key is None:
            return f"names no entry {row['name']!r}"
        if field not in self.fields:
            return f"{field!r} is not an infobox field"
        if not isinstance(value, dict) or not isinstance(value.get("chapter"), int) or not part[0] <= value["chapter"] <= part[1]:
            return f"chapter is outside chapters {part[0]}-{part[1]}"
        names = [key] + [a["name"] for a in self.kb.entities[key].get("absorbed", [])]
        rows = [o for n in names for o in (self.pages.get(n) or {}).get(profile_group(field), {}).get(field, [])]
        if not any(o["chapter"] == value["chapter"] and name_key(o["value"]) == name_key(value.get("value") or "") for o in rows):
            return "matches no value the wiki shows"
        return None

    def tie(self, row, part):
        ends = [self.entry(row.get(end)) for end in ("source", "target")]
        if None in ends:
            return f"names no entry {row.get('source') if ends[0] is None else row.get('target')!r}"
        if ends[0] == ends[1]:
            return "ties an entry to itself"
        if not isinstance(row.get("type"), str) or not row["type"].strip():
            return "gives no wording"
        if row.get("status", "stated") not in STATUSES:
            return f"status must be one of {', '.join(STATUSES)}"
        return self.dated(row, "chapter", part, row["type"], str(row.get("detail") or ""))

    def untie(self, row, part):
        ends = [self.entry(row.get(end)) for end in ("source", "target")]
        if None in ends:
            return f"names no entry {row.get('source') if ends[0] is None else row.get('target')!r}"
        if not isinstance(row.get("chapter"), int) or not part[0] <= row["chapter"] <= part[1]:
            return f"chapter {row.get('chapter')!r} is outside chapters {part[0]}-{part[1]}"
        if not any(r["chapter"] == row["chapter"] and r["type"] == row.get("type") and [r["source"], r["target"]] == ends for r in self.kb.relations):
            return "matches no tie the wiki shows"
        return None

    def settle(self, row, part):
        q = find_question(self.kb.questions, row) if isinstance(row.get("id") or row.get("question"), str) else None
        if q is None:
            return f"names no question {row.get('id') or row.get('question')!r}"
        if row.get("dismiss") is True:
            return None
        if not str(row.get("answer") or "").strip():
            return "gives no answer"
        if isinstance(row.get("chapter"), int) and row["chapter"] < q["chapter"]:
            return f"chapter {row['chapter']} is before chapter {q['chapter']} raises the question"
        return self.dated(row, "chapter", part, str(row["answer"]), str(row.get("payoff") or ""))


ENTRY_PARTS = {"same_as": ("chapter", "quotes"), "type": ("chapter", "quotes"), "title": ("title_chapter", "quotes")}


def entry_pieces(row):
    why = {"why": row["why"]} if row.get("why") else {}
    for part, keys in ENTRY_PARTS.items():
        if part in row:
            yield part, {"name": row.get("name"), part: row[part], **{k: row.get(k) for k in keys}, **why}
    for group in ("fields", "drop"):
        values = row.get(group)
        for field, rows in values.items() if isinstance(values, dict) else []:
            for value in rows if isinstance(rows, list) else [rows]:
                yield group, {"name": row.get("name"), group: {field: [value]}, **why}


def pieces(kind, row):
    found = list(entry_pieces(row)) if kind == "entries" and isinstance(row, dict) else [(kind, row)]
    return found or [("nothing", row)]


PIECES = {
    "nothing": ("entries", lambda review, row, part: "proposes no change this stage can make"),
    "same_as": ("entries", Review.join),
    "type": ("entries", Review.retype),
    "title": ("entries", Review.title),
    "fields": ("entries", Review.value),
    "drop": ("entries", Review.drop),
    "relations": ("relations", Review.tie),
    "drop_relations": ("drop_relations", Review.untie),
    "questions": ("questions", Review.settle),
}


def problem(review, piece, row, part):
    kind, check = PIECES[piece]
    if not isinstance(row, dict):
        return "is not a JSON object"
    if kind == "entries" and not isinstance(row.get("name"), str):
        return "gives no name"
    return check(review, row, part)


def accepted_row(review, kind, row):
    if kind == "relations":
        target = review.entry(row["target"])
        family = relation_family(row["type"], review.readings, review.kb.entities[target]["type"])
        keep = ("source", "target", "type", "detail", "status", "chapter", "quotes", "why")
        return {**{k: row[k] for k in keep if row.get(k)}, "family": family}
    if kind == "questions":
        q = find_question(review.kb.questions, row)
        keep = ("dismiss", "why") if row.get("dismiss") is True else ("chapter", "answer", "payoff", "quotes", "why")
        return {"id": q["id"], **{k: row[k] for k in keep if row.get(k)}}
    if kind == "drop_relations":
        return {k: row[k] for k in ("source", "target", "type", "chapter", "why") if row.get(k)}
    return {k: v for k, v in row.items() if v is not None}


def reply_problem(reply):
    return None if isinstance(reply, dict) else "the reply is not one JSON object"


def proposals(reply):
    for kind in LISTS:
        rows = reply.get(kind)
        for row in rows if isinstance(rows, list) else [rows] if rows else []:
            for piece, one in pieces(kind, row):
                yield kind, piece, one


def finished_volumes(workdir, to):
    read = {int(p.stem) for p in (Path(workdir) / "state").glob("[0-9][0-9][0-9][0-9].json")}
    last = to or max(read, default=0)
    return [v for v in read_json(Path(workdir) / "volumes.json", {"volumes": []})["volumes"]
            if v["to"] <= last and set(range(v["from"], v["to"] + 1)) <= read]


def volume_view(workdir, v):
    kb = load_states(workdir, until=v["to"], ladders=True)
    profiles = read_json(Path(workdir) / "profiles.json", {"characters": {}})["characters"]
    return kb, page_profiles(workdir, kb.entities.values(), profiles)


def sessions(workdir, v, review):
    titles = {c["index"]: c["title"] for c in read_json(Path(workdir) / "chapters.json", [])}
    blocks = {n: chapter_block(workdir, n, titles.get(n, str(n))) for n in range(v["from"], v["to"] + 1)}
    parts = plan_parts([(n, tokens(text)) for n, text in blocks.items()])
    fields = ", ".join(f"{k} ({', '.join(values)})" if values else k for k, values in review.fields.items())
    for k, (first, last) in enumerate(parts, 1):
        scope = f"the whole of {v['name']}" if len(parts) == 1 else f"part {k} of {len(parts)} of {v['name']}, which runs from chapter {v['from']} to {v['to']}"
        head = HEAD.format(first=first, last=last, scope=scope, book="\n\n".join(blocks[n] for n in range(first, last + 1)))
        for s in slices(wiki_items(workdir, review.kb, review.pages, first, last)):
            prompt = head + TASK.format(first=first, last=last, title=s.title, slice=s.text, types=", ".join(review.types), fields=fields)
            yield (first, last), s, head, prompt


CHANGE_DETAIL = ("quotes", "why", "volume", "slice", "models")


def change(kb, row):
    def plain(value):
        if isinstance(value, dict):
            return tuple(sorted((k, plain(v)) for k, v in value.items() if k not in CHANGE_DETAIL))
        if isinstance(value, list):
            return tuple(plain(v) for v in value)
        return name_key(value) if isinstance(value, str) else value
    return plain({**row, **{k: kb.resolve(row[k]) or row[k] for k in ("name", "same_as", "source", "target") if isinstance(row.get(k), str)}})


def cmd_proofread(args):
    workdir = Path(args.workdir).resolve()
    started = args.started or time.strftime("%Y-%m-%dT%H:%M:%S")
    book = read_json(workdir / "book.json", {})
    settings = load_settings(workdir)
    several = isinstance(settings.models.get(PURPOSE), list)
    out = {kind: [] for kind in LISTS} | {"rejected": [], "sessions": []}
    views = []
    for v in finished_volumes(workdir, args.to):
        kb, pages = volume_view(workdir, v)
        review = Review(workdir, kb, pages, book)
        planned = list(sessions(workdir, v, review))
        log(workdir, f"proofread: {v['name']} (ch {v['from']}-{v['to']}): {len(planned)} sessions, "
                     f"about {max((tokens(p) for *_, p in planned), default=0):,} tokens each at most")
        views.append((v, review, planned))
    owners = {}
    for model in settings.models_for(PURPOSE):
        one = settings.with_model(PURPOSE, model)
        for v, review, planned in views:
            kb = review.kb
            for part, s, head, prompt in planned:
                spent = spent_since(workdir, started)
                if args.budget is not None and spent >= args.budget and cached_reply(workdir, PURPOSE, prompt, one) is None:
                    raise BudgetSpent(f"spent ${spent:,.2f} of the ${args.budget:,.2f} budget; stopping before the "
                                      f"{f'{model} ' if several else ''}proofread of {v['name']}, {s.title}")
                where = {"volume": v["name"], "chapters": list(part), "slice": s.key} | ({"model": model} if several else {})
                counts = {"accepted": 0, "rejected": 0} | ({"duplicates": 0} if several else {})
                for kind, piece, row in proposals(cached_llm(workdir, PURPOSE, prompt, check=reply_problem, chapter=part[1], settings=one, prefix=head)):
                    reason = problem(review, piece, row, part)
                    accepted = None if reason else accepted_row(review, kind, row)
                    owner = None if reason else next((owners[b] for c in claims(kb, kind, row) for b in blockers(c) if b in owners), None)
                    if owner and model in owner[0]:
                        reason = "repeats or contradicts a row accepted earlier"
                    elif owner and owner[1] != change(kb, accepted):
                        reason = f"conflicts with the row from {owner[0][0]}, listed first"
                    if reason:
                        out["rejected"].append({**where, "list": kind, "row": row, "reason": reason})
                        counts["rejected"] += 1
                    elif owner:
                        owner[0].append(model)
                        counts["duplicates"] += 1
                    else:
                        models = [model]
                        kept = {**accepted, "volume": v["name"], "slice": s.key} | ({"models": models} if several else {})
                        owners.update((c, (models, change(kb, accepted))) for c in claims(kb, kind, row))
                        out[kind].append(kept)
                        counts["accepted"] += 1
                out["sessions"].append({**where, "tokens": tokens(prompt), **counts})
                log(workdir, f"proofread: {v['name']} ch {part[0]}-{part[1]}, {s.title}{f' ({model})' if several else ''}: "
                             f"{counts['accepted']} accepted, {counts['rejected']} rejected" + (f", {counts['duplicates']} duplicates" if several else ""))
    write_json(workdir / PROOFREAD_FILE, out)
