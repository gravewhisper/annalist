import copy
import json
import re
from pathlib import Path

from .book import ladder_types
from .corrections import correct_pages, known_from, load_corrections, PAGES, PROOFREAD, PROOFREAD_FILE, QUESTIONS, settle_questions, with_proofread
from .files import read_json, read_jsonl, write_json, write_jsonl
from .names import function_word_name, LEADING_WORDS, name_key, name_pattern, names_of, parse_aliases, UNTYPED, written_summary
from .ranks import joined_ladders, stated_ladders
from .template import INDIVIDUALS, type_parents, Types
from .text import distinctive_words, QUOTE_CHARS
from .wordings import read_wordings, worded


UNRESOLVED = ("open", "partial")


def add_lead(q, lead):
    if q["status"] in UNRESOLVED and not any(l["chapter"] == lead["chapter"] and l["quote"] == lead["quote"] for l in q["leads"]):
        q["leads"].append(lead)
        q["status"] = "partial"


def settle(q, status, **fields):
    if q["status"] in UNRESOLVED:
        q.update(status=status, **fields)


ENDING_VERDICTS = ("answered-implicitly", "left-open", "dropped-thread", "unclear")


def unfinished(decision):
    return decision.get("verdict") == "error" or (decision.get("verdict") == "answered-implicitly" and "reread" not in decision)


def parse_sourcing(raw):
    quotes = raw.get("quotes") if isinstance(raw.get("quotes"), list) else [raw.get("quotes")]
    status = raw.get("status") if raw.get("status") in ("stated", "implied", "belief") else "stated"
    return {"quotes": [str(q).strip() for q in quotes if str(q or "").strip()][:3],
            "asserted_by": str(raw.get("asserted_by") or "narrator").strip(), "status": status}


MAIN_TIMELINE = {"id": "main", "kind": "main", "label": "Main story", "period": "", "started": 1, "erased": None}


TIMELINE_KINDS = {
    "run": "one pass of a time loop; a restart erases it and undoes its events",
    "flashback": "a scene set in the past; true about the past, not the present",
    "vision": "a dream, vision, illusion, or simulation; not real events",
    "alternate": "an alternate reality or branch that is not the story's main line",
}


def timeline_role(timeline, until):
    if timeline is None or timeline["kind"] == "main":
        return "current"
    if timeline["erased"] is not None and timeline["erased"] <= until:
        return "erased"
    return "current" if timeline["kind"] == "run" else "aside"


def timeline_tag(timelines, tid, until):
    t = timelines.get(tid)
    role = timeline_role(t, until)
    if role == "erased":
        return f"erased timeline: {t['label'] or t['id']}, undone in ch{t['erased']}"
    if role == "aside":
        return f"{t['kind']}: {t['label'] or t['id']}" + (f", {t['period']}" if t["period"] else "")
    return ""


def timeline_line(t):
    if t["kind"] == "main":
        return "main [main]: the story's present and everything that holds across timelines"
    period = f" ({t['period']})" if t.get("period") else ""
    erased = f", erased in ch{t['erased']}" if t["erased"] is not None else ""
    return f"{t['id']} [{t['kind']}]: {t['label']}{period}, from ch{t['started']}{erased}"


def lead_key(qid, chapter):
    return f"{qid}@{chapter}"


def qualified(name, etype):
    return f"{name} ({etype})"


STANCES = {"suspects", "suspected", "thinks", "thought", "believes", "believed", "claims", "claimed", "assumes", "guesses",
           "imagines", "says", "said", "rumours", "rumors", "teases"}


IMPERSONATES = re.compile(r"(?:is |was )?(?:impersonat(?:es|ed|ing)|(?:pos|masquerad|disguis)(?:es|ed|ing)(?: (?:him|her|it)self)? as"
                          r"|pretend(?:s|ed|ing) to be)")


def quotes_match(pattern, row):
    return any(pattern.search(q.translate(QUOTE_CHARS)) for q in row["quotes"])


def wearer(claims, row):
    known = [c for c in claims if c["chapter"] <= row["chapter"] and c["timeline"] in ("main", row["timeline"])]
    latest = max((c["chapter"] for c in known), default=None)
    people = {c["source"] for c in known if c["chapter"] == latest}
    return people.pop() if len(people) == 1 else None


def name_within(a, b):
    a, b = name_key(a), name_key(b)
    return f" {a} " in f" {b} " or f" {b} " in f" {a} "


class Knowledge:
    def __init__(self, ladder=None, wordings=None, power_types=None):
        self.wordings = wordings or {}
        self.types = Types(type_parents(power_types))
        self.power_types = set(self.types.parents)
        self.spec = ladder or {}
        self.ladder = set(ladder_types(ladder))
        self.step_type = self.spec.get("step_type")
        self.group_type = self.spec.get("group_type")
        self.ladder_rows = []
        self.rank_name = re.compile(rf"{re.escape(ladder['step_type'])}\s*\d+") if ladder and ladder.get("rank") == "number" else None
        self.laddered = False
        self.entities = {}
        self.index = {}
        self.facts = []
        self.relations = []
        self.questions = {}
        self.synopses = {}
        self.leads = {}
        self.timelines = {"main": dict(MAIN_TIMELINE)}
        self.summary_log = {}
        self.repeats = {}
        self.corrections = None
        self.problems = []

    def bare_rank(self, name):
        return bool(self.rank_name and self.rank_name.fullmatch(name_key(name)))

    def resolve(self, name, etype=""):
        holder = self.index.get(name_key(name))
        if holder and self.splits(self.entities[holder]["type"], name_key(etype)):
            return self.index.get(name_key(qualified(name, name_key(etype))))
        return holder

    def splits(self, a, b):
        return a != b and {a, b} == self.ladder

    def same_kind(self, a, b):
        return a in UNTYPED or b in UNTYPED or self.types.kin(a, b)

    def upsert_entity(self, entity, chapter, timeline="main"):
        name = str(entity.get("name") or "").strip()
        if function_word_name(name) or self.bare_rank(name):
            return None
        etype = name_key(entity.get("type") or "")
        aliases = [a for a in parse_aliases(entity.get("aliases")) if not self.bare_rank(a)]
        holder = self.index.get(name_key(name))
        canonical = holder if holder and name_key(holder) == name_key(name) else None
        split = canonical is not None and self.splits(self.entities[canonical]["type"], etype)
        if split:
            canonical = self.index.get(name_key(qualified(name, etype)))
        elif holder and canonical is None and not self.same_kind(self.entities[holder]["type"], etype):
            self.drop_alias(holder, name)
        keys = [name_key(k) for k in [name] + aliases]
        matches = [m for m in dict.fromkeys([canonical] + [self.index[k] for k in keys if k in self.index])
                   if m and self.same_kind(self.entities[m]["type"], etype)]
        canonical = canonical or (matches[0] if matches else None)
        for other in matches:
            if other != canonical and self.same_kind(self.entities[other]["type"], self.entities[canonical]["type"]):
                self.merge(other, canonical, None if name_within(other, canonical) else chapter)
        if canonical is None:
            canonical = qualified(name, etype) if split else name
            self.entities[canonical] = {"name": canonical, "type": "", "aliases": [], "summary": "",
                                        "first_chapter": chapter, "last_chapter": chapter, **({"written": name} if split else {})}
            self.index[name_key(canonical)] = canonical
        record = self.entities[canonical]
        if etype and (record["type"] in UNTYPED or self.types.refines(etype, record["type"])):
            record["type"] = etype
        if not record["type"]:
            record["type"] = "uncategorized"
        for alias in [name] + aliases:
            holder = self.index.get(name_key(alias))
            if holder in (None, canonical):
                self.index[name_key(alias)] = canonical
            elif self.same_kind(self.entities[holder]["type"], record["type"]):
                continue
            if name_key(alias) != name_key(canonical) and name_key(alias) not in map(name_key, record["aliases"]):
                record["aliases"].append(alias)
        summary = written_summary(entity)
        if summary:
            self.summary_log.setdefault(canonical, []).append((chapter, timeline, summary))
            record["summary"] = self.summary_log[canonical][-1][2]
        record["last_chapter"] = chapter
        return canonical

    def drop_alias(self, holder, alias):
        record = self.entities[holder]
        record["aliases"] = [a for a in record["aliases"] if name_key(a) != name_key(alias)]
        del self.index[name_key(alias)]

    def merge(self, other, canonical, chapter=None):
        gone = self.entities.pop(other)
        record = self.entities[canonical]
        absorbed = [{**a, "chapter": max(a["chapter"], chapter or 0)} for a in gone.pop("absorbed", [])]
        if chapter is not None and gone["first_chapter"] < chapter:
            absorbed.append({"name": other, "aliases": list(gone["aliases"]), "first_chapter": gone["first_chapter"],
                             "chapter": chapter})
        if absorbed:
            record["absorbed"] = record.get("absorbed", []) + absorbed
        if self.types.refines(gone["type"], record["type"]):
            record["type"] = gone["type"]
        for alias in [gone["name"]] + gone["aliases"]:
            if name_key(alias) != name_key(canonical) and name_key(alias) not in map(name_key, record["aliases"]):
                record["aliases"].append(alias)
        record["first_chapter"] = min(record["first_chapter"], gone["first_chapter"])
        for k, v in self.index.items():
            if v == other:
                self.index[k] = canonical
        log = sorted(self.summary_log.pop(other, []) + self.summary_log.get(canonical, []), key=lambda x: x[0])
        if log:
            self.summary_log[canonical] = log
        for f in self.facts:
            if f["entity"] == other:
                f["entity"] = canonical
                if chapter is not None:
                    f.setdefault("filed", other)
        for r in self.relations:
            for end in ("source", "target"):
                if r[end] == other:
                    r[end] = canonical
                    if chapter is not None:
                        r.setdefault("filed", {}).setdefault(end, other)

    def bare_entities(self):
        used = {f["entity"] for f in self.facts} | {r[end] for r in self.relations for end in ("source", "target")}
        return [name for name in self.entities if name not in used]

    def asked_before(self, qid):
        earlier = self.repeats.get(qid)
        while earlier in self.repeats and earlier not in self.questions:
            earlier = self.repeats[earlier]
        return self.questions.get(earlier)

    def open_questions(self):
        return [q for q in self.questions.values() if q["status"] in UNRESOLVED]

    def relevant_entities(self, text, recent):
        lower = text.lower()
        named = {k for k, e in self.entities.items()
                 if any(re.search(r"(?<!\w)" + re.escape(a.lower()) + r"(?!\w)", lower) for a in [e["name"]] + e["aliases"])}
        latest = sorted(self.entities, key=lambda k: self.entities[k]["last_chapter"], reverse=True)[:recent]
        return [k for k in self.entities if k in named or k in latest]

    def relevant_questions(self, text, recent, matched):
        opens = sorted(self.open_questions(), key=lambda q: q["id"], reverse=True)
        words = set(distinctive_words(text))
        overlap = {q["id"]: len(words & set(distinctive_words(q["question"]))) for q in opens[recent:]}
        hits = sorted((q for q in opens[recent:] if overlap[q["id"]] >= 3), key=lambda q: -overlap[q["id"]])[:matched]
        return sorted(opens[:recent] + hits, key=lambda q: q["id"])

    def compact_view(self, text, view, notes=None):
        notes = notes or {}
        shown = self.relevant_entities(text, view["recent_entities"])
        lines = []
        if len(self.timelines) > 1:
            lines += ["TIMELINES so far (id [kind]: label, chapters). Events of an erased timeline were undone and are no longer true "
                      "in the story's present; a flashback is the past. Summaries below describe the present:"]
            lines += [f"- {timeline_line(t)}" for t in self.timelines.values()] + [""]
        lines += [f"ENTITY REGISTRY, {len(shown)} of {len(self.entities)} entities: those named in this chapter and "
                 "the most recently active (name [type] (aliases): summary). Others exist; reuse a name exactly if you know it:"]
        for k in shown:
            e = self.entities[k]
            aka = f" (aka {', '.join(e['aliases'])})" if e["aliases"] else ""
            corrected = f" (Confirmed correction, {notes[k]})" if k in notes else ""
            lines.append(f"- {e['name']} [{e['type']}]{aka}: {e['summary']}{corrected}")
        if not shown:
            lines.append("(empty: this is the first chapter)")
        questions = self.relevant_questions(text, view["recent_questions"], view["matched_questions"])
        lines += ["", f"OPEN QUESTIONS, {len(questions)} of {len(self.open_questions())}: the most recent and those "
                  "related to this chapter (id: question):"]
        lines.extend(f"- {q['id']}: {q['question']}" for q in questions)
        if not questions:
            lines.append("(none)")
        return "\n".join(lines)

    def third_party(self, words, ends):
        for i in range(1, len(words)):
            for j in range(min(len(words), i + 6), i, -1):
                span = re.sub(r"['’]s$", "", " ".join(words[i:j]))
                key = self.index.get(name_key(span))
                if key and key not in ends and not function_word_name(span):
                    return key, i, j
        return None

    def about(self, row):
        words = f"{row['type']} {row['detail']}".split()
        lower = [w.lower() for w in words]
        if row["status"] != "belief" and lower[:1] and lower[0] not in STANCES:
            return row
        found = self.third_party(words, (row["source"], row["target"]))
        if not found:
            return row
        key, i, j = found
        if lower[i - 1] == "between" and lower[j:j + 1] == ["and"]:
            label = words[:i - 1] + ["with"] + words[j + 1:]
        elif lower[i - 1] in STANCES:
            label = words[j:]
        else:
            return row
        while label and (label[0].lower() in STANCES or label[0].lower() in LEADING_WORDS):
            label = label[1:]
        if not label:
            return row
        moved = {k: v for k, v in row.items() if k != "filed"}
        return {**moved, "source": key, "type": " ".join(label), "detail": "", "status": "belief", "asserted_by": row["source"],
                "original": {"source": row["source"], "type": row["type"], "detail": row["detail"]}}

    def resolve_or_stub(self, name, chapter, listed=None):
        canonical = (listed or {}).get(name_key(name)) or self.resolve(name) or self.upsert_entity({"name": name, "type": "uncategorized"}, chapter)
        if canonical:
            self.entities[canonical]["last_chapter"] = chapter
        return canonical

    def apply_timelines(self, n, sidecar):
        for t in sidecar.get("new") or []:
            if t["kind"] == "run":
                for other in self.timelines.values():
                    if other["kind"] == "run" and other["erased"] is None:
                        other["erased"] = n
            self.timelines[t["id"]] = {"id": t["id"], "kind": t["kind"], "label": t.get("label", ""),
                                       "period": t.get("period", ""), "started": n, "erased": None}
        for tid in sidecar.get("erased") or []:
            t = self.timelines.get(tid)
            if t and t["kind"] != "main" and t["erased"] is None:
                t["erased"] = n
        labels = sidecar.get("labels") or {}
        return lambda iid: labels[iid] if labels.get(iid) in self.timelines else "main"

    def refresh_summaries(self, until):
        for name, log in self.summary_log.items():
            if name in self.entities:
                current = [text for _, tid, text in log if timeline_role(self.timelines.get(tid), until) == "current"]
                erased = timeline_role(self.timelines.get(log[-1][1]), until) == "erased"
                self.entities[name]["summary"] = current[-1] if current else ("In an erased timeline: " if erased else "") + log[-1][2]

    def apply(self, state):
        n = state["chapter"]
        out = state["extraction"]
        label = self.apply_timelines(n, state.get("timelines") or {})
        self.synopses[n] = str(out.get("synopsis") or "").strip()
        listed = {}
        for i, entity in enumerate(out.get("entities") or [], 1):
            if isinstance(entity, dict):
                canonical = self.upsert_entity(entity, n, label(f"E{i}"))
                if canonical and "written" in self.entities[canonical]:
                    listed[name_key(self.entities[canonical]["written"])] = canonical
        new_facts, slot = [], 0
        support = state.get("support") or {}
        for i, fact in enumerate(out.get("facts") or [], 1):
            audit = support.get(f"F{i}") or {}
            if not isinstance(fact, dict) or not fact.get("claim") or not fact.get("entity") or audit.get("verdict") == "unsupported":
                continue
            claim, trimmed = str(fact["claim"]).strip(), str(audit.get("claim") or "").strip()
            slot += 1
            entity = self.resolve_or_stub(fact["entity"], n, listed)
            if not entity:
                continue
            record = {"id": f"F{n:04d}-{slot:03d}", "chapter": n,
                      "entity": entity, "claim": claim, **parse_sourcing(fact),
                      "support": audit.get("verdict") or "unaudited", "timeline": label(f"F{i}")}
            if audit.get("verdict") == "trim" and trimmed:
                record.update(claim=trimmed, original_claim=claim)
            new_facts.append(record)
        self.facts.extend(new_facts)
        new_relations, slot = [], 0
        for i, rel in enumerate(out.get("relations") or [], 1):
            audit = support.get(f"R{i}") or {}
            if not isinstance(rel, dict) or not all(str(rel.get(k) or "").strip() for k in ("source", "target", "type")):
                continue
            if audit.get("verdict") == "unsupported":
                continue
            slot += 1
            wording = worded(rel, self.wordings)
            if not wording["type"]:
                continue
            source, target = (self.resolve_or_stub(str(rel[end]).strip(), n, listed) for end in ("source", "target"))
            if not (source and target):
                continue
            new_relations.append(self.about({"id": f"R{n:04d}-{slot:03d}", "chapter": n, "source": source, "target": target,
                                             **wording, **parse_sourcing(rel), "timeline": label(f"R{i}")}))
        self.relations.extend(new_relations)
        raised = 0
        for i, q in enumerate(out.get("questions_raised") or [], 1):
            if not isinstance(q, dict) or not q.get("question"):
                continue
            raised += 1
            qid = f"Q{n:04d}-{raised:02d}"
            earlier = self.asked_before(qid)
            if earlier and earlier["status"] in UNRESOLVED:
                earlier.setdefault("again", []).append({"chapter": n, "question": str(q["question"]).strip(),
                                                        "quote": str(q.get("quote") or "").strip()})
                continue
            self.questions[qid] = {"id": qid, "chapter": n, "question": str(q["question"]).strip(),
                                   "quote": str(q.get("quote") or "").strip(), "status": "open", "rejected": [], "leads": [],
                                   "timeline": label(f"Q{i}")}
        for r in out.get("questions_resolved") or []:
            claimed = str(r.get("id")) if isinstance(r, dict) else ""
            q = self.questions.get(claimed) or self.asked_before(claimed)
            if not q or q["status"] not in UNRESOLVED or q["chapter"] == n:
                continue
            reread = (state.get("rereads") or {}).get(claimed) or {}
            attempt = {"chapter": n, "answer": str(r.get("answer") or "").strip(), "quote": str(r.get("quote") or "").strip()}
            if reread.get("verdict") == "accept":
                settle(q, "resolved", resolved_chapter=n, answer=attempt["answer"], resolve_quote=attempt["quote"],
                       payoff=str(reread.get("payoff") or "").strip(), context_found=reread.get("context_found", True))
            else:
                attempt["reason"] = str(reread.get("payoff") or reread.get("error") or "no reread").strip()
                lead = self.leads.get(lead_key(q["id"], n)) or {}
                if lead.get("partial") and lead.get("lead"):
                    attempt["lead"] = lead["lead"]
                    add_lead(q, {"chapter": n, "text": lead["lead"], "quote": attempt["quote"], "by": "read"})
                q["rejected"].append(attempt)
        self.refresh_summaries(n)
        return new_facts

    def apply_events(self, n, events):
        for kind, qid, data in events:
            q = self.questions.get(qid)
            if not q or q["chapter"] > n:
                continue
            if kind == "lead":
                add_lead(q, data)
            elif kind == "premise":
                settle(q, "premise-false", premise=data)
            else:
                settle(q, "resolved", resolved_chapter=data["chapter"], resolved_shown=n, answer=data["answer"],
                       resolve_quote=data["quote"], payoff=data.get("payoff", ""), found_by=data["by"])

    def apply_ending(self, decisions, last):
        for qid, d in decisions.items():
            q = self.questions.get(qid)
            if q and q["status"] in UNRESOLVED and d["verdict"] in ENDING_VERDICTS and not unfinished(d):
                q["ending"] = {"verdict": d["verdict"], "chapter": last,
                               **{k: d[k] for k in ("answer", "quotes", "reason") if d.get(k)}}

    def apply_retypes(self, decisions):
        for d in decisions:
            canonical = self.resolve(d["name"])
            if canonical and self.entities[canonical]["type"] == d["from"] and not (d["from"] in self.ladder and d["to"] in INDIVIDUALS):
                self.entities[canonical]["type"] = d["to"]

    def apply_filled(self, chapters, until, prefix):
        for n, entry in sorted(chapters.items(), key=lambda c: int(c[0])):
            if until is not None and int(n) > until:
                break
            for k, row in enumerate(entry["relations"], 1):
                ends = {end: self.resolve(row[end]) for end in ("source", "target")}
                wording = worded(row, self.wordings)
                if None in ends.values() or ends["source"] == ends["target"] or not wording["type"]:
                    continue
                filed = {end: a["name"] for end in ends for a in self.entities[ends[end]].get("absorbed", [])
                         if name_key(row[end]) in map(name_key, [a["name"]] + a["aliases"])}
                self.relations.append(self.about({**row, **wording, **ends, "id": f"{prefix}{int(n):04d}-{k:03d}",
                                                  **({"filed": filed} if filed else {})}))

    def apply_disguises(self):
        worn = {}
        for r in self.relations:
            if IMPERSONATES.fullmatch(name_key(r["type"])) and {self.entities[r[end]]["type"] for end in ("source", "target")} == {"character"}:
                worn.setdefault(r["target"], []).append(r)
        for name, claims in worn.items():
            pattern = name_pattern([n.translate(QUOTE_CHARS) for n in names_of(self.entities[name])]).pattern
            wrapped = re.compile(rf"(?<!\w)([\"']){pattern}\1(?!\w)", re.I)
            for f in self.facts:
                who = wearer(claims, f) if f["entity"] == name and quotes_match(wrapped, f) else None
                if who:
                    f.update(entity=who, worn={"entity": name})
            for r in self.relations:
                for end, other in (("source", "target"), ("target", "source")):
                    who = wearer(claims, r) if r[end] == name and quotes_match(wrapped, r) else None
                    if who and who != r[other]:
                        r.update({end: who, "worn": {end: name}})

    def apply_ladders(self, ladders, until=None):
        self.laddered = True
        made = 0
        for row in ladders:
            steps = [(s, self.ladder_step(s)) for s in row["steps"] if until is None or s["chapter"] <= until]
            steps = [(s, key) for s, key in steps if key]
            if not steps or row["group"] is None:
                continue
            group = self.resolve(row["group"], row["group_type"])
            if group is None or self.entities[group]["type"] in UNTYPED:
                group = self.upsert_entity({"name": row["group"], "type": row["group_type"]}, min(s["chapter"] for s, _ in steps))
            if not group or self.entities[group]["type"] != row["group_type"]:
                continue
            for s, key in steps:
                made += 1
                self.relations.append({"id": f"RG{s['chapter']:04d}-{made:03d}", "chapter": s["chapter"], "source": key, "target": group,
                                       "type": f"{self.entities[key]['type']} {s['rank']} of", "detail": "", "quotes": [s["quote"]],
                                       "asserted_by": "narrator", "status": "stated", "timeline": "main"})

    def ladder_step(self, s):
        key = self.resolve(s["entry"], self.step_type)
        if key is None and s.get("new"):
            key = self.upsert_entity({"name": s["entry"], "type": self.step_type}, s["chapter"])
        return key

    def person_and_power(self, a, b):
        kinds = {self.entities[a]["type"], self.entities[b]["type"]}
        return bool(kinds & set(INDIVIDUALS)) and bool(kinds & self.power_types)

    def apply_merges(self, decisions, until=None, known=None):
        for d in decisions:
            revealed = d.get("revealed") or {"basis": "legacy", "chapter": None}
            if not d.get("same") or revealed["basis"] == "unverified":
                continue
            canonical = self.resolve(d["canonical"])
            other = self.resolve(d["b"] if name_key(d["canonical"]) == name_key(d["a"]) else d["a"])
            chapter = revealed["chapter"]
            if chapter is not None and other and known:
                chapter = min([chapter] + [known[k] for k in map(name_key, names_of(self.entities[other])) if k in known])
            if until is not None and chapter is not None and chapter > until:
                continue
            if canonical and other and canonical != other and not self.person_and_power(canonical, other):
                self.merge(other, canonical, chapter)
        self.relations = [r for r in self.relations if r["source"] != r["target"]]
        for d in decisions:
            lead = d.get("possibly")
            if not lead or (until is not None and lead["chapter"] > until):
                continue
            holder, target = self.resolve(d["a"]), self.resolve(d["b"])
            if holder and target and holder != target:
                self.entities[holder].setdefault("possibly", []).append({"name": target, **lead})


def answer_events(decision):
    if decision.get("lead"):
        yield decision["lead"]["chapter"], "lead", {**decision["lead"], "by": "answers"}
    if decision.get("verdict") == "answered":
        yield decision["answer"]["chapter"], "answer", {**decision["answer"], "by": "answers"}
    if decision.get("verdict") == "premise-false":
        yield decision["premise"]["chapter"], "premise", decision["premise"]


def question_events(workdir, answers_before=None):
    events = {}
    for qid, s in read_json(Path(workdir) / "sweep.json", {"questions": {}})["questions"].items():
        if s.get("verdict") == "accept":
            events.setdefault(max([s["chapter"], s.get("shown", 0), *s.get("candidates", [])]), []).append(("answer", qid, {**s, "by": "sweep"}))
    for qid, d in read_json(Path(workdir) / "ending.json", {"questions": {}})["questions"].items():
        if d.get("verdict") == "answered":
            events.setdefault(d["chapter"], []).append(("answer", qid, {**d, "by": "ending"}))
    for boundary, entry in read_json(Path(workdir) / "answers.json", {"boundaries": {}})["boundaries"].items():
        if answers_before is None or int(boundary) < answers_before:
            for qid, d in entry["questions"].items():
                for n, kind, data in answer_events(d):
                    events.setdefault(n, []).append((kind, qid, data))
    return events


FILLED = {"relate.json": "RF", "link.json": "RL"}


def load_states(workdir, until=None, merges=True, retypes=True, filled=tuple(FILLED), discovered=True, answers_before=None, ladders=False,
                repeats=True, corrections=()):
    book = read_json(Path(workdir) / "book.json", {})
    kb = Knowledge(book.get("ladder"), read_wordings(workdir), book.get("power_types") or ())
    kb.corrections = load_corrections(workdir) if corrections else None
    leads = read_json(Path(workdir) / "leads.json", {"leads": {}})
    kb.leads = leads["leads"]
    for pair in sorted(leads.get("repeats", []) if repeats else [], key=lambda p: p["earlier"]):
        if pair["same"]:
            kb.repeats.setdefault(pair["later"], pair["earlier"])
    events = question_events(workdir, answers_before)
    ending = read_json(Path(workdir) / "ending.json", {"last": None, "questions": {}})
    discovered_at = {}
    for e in read_json(Path(workdir) / "discover.json", {"entities": []})["entities"] if discovered else []:
        discovered_at.setdefault(e["chapter"], []).append(e)
    paths = sorted((Path(workdir) / "state").glob("[0-9][0-9][0-9][0-9].json"))
    for path in paths:
        state = json.loads(path.read_text(encoding="utf-8"))
        if until is not None and state["chapter"] > until:
            break
        kb.apply(state)
        kb.apply_events(state["chapter"], events.get(state["chapter"], []))
        for e in discovered_at.get(state["chapter"], []):
            if kb.resolve(e["name"], e.get("type") or "") is None:
                kb.upsert_entity(e, state["chapter"])
    if ending["last"] is not None and max(kb.synopses, default=0) >= ending["last"]:
        kb.apply_ending(ending["questions"], ending["last"])
    if retypes:
        kb.apply_retypes(read_json(Path(workdir) / "types.json", {"entities": []})["entities"])
    if merges:
        kb.apply_merges(read_json(Path(workdir) / "merges.json", {"pairs": []})["pairs"], until,
                        known_from(kb.corrections) if PAGES in corrections else None)
    for name in filled:
        kb.apply_filled(read_json(Path(workdir) / name, {"chapters": {}})["chapters"], until, FILLED[name])
    if merges:
        kb.apply_disguises()
    if ladders:
        kb.ladder_rows = read_json(Path(workdir) / "ladders.json", [])
        kb.apply_ladders(kb.ladder_rows, until)
    if kb.corrections:
        if PROOFREAD in corrections:
            kb.corrections = with_proofread(kb, kb.corrections, load_corrections(workdir, PROOFREAD_FILE))
        reach = until if until is not None else max(kb.synopses, default=0)
        kb.problems = (kb.corrections.problems + (correct_pages(kb, kb.corrections, reach) if PAGES in corrections else [])
                       + (settle_questions(kb, kb.corrections, reach) if QUESTIONS in corrections else []))
    if ladders:
        stated = stated_ladders(kb, book.get("rank_word"), kb.ladder_rows)
        kb.apply_ladders(stated, until)
        kb.ladder_rows = joined_ladders(kb, kb.ladder_rows, stated)
    return kb


def carry_quote_checks(path, rows):
    checked = {r["id"]: r for r in read_jsonl(path) if "quote_ok" in r}
    out = []
    for r in rows:
        old = checked.get(r["id"])
        if old and sorted(old["quotes"] + old.get("dropped_quotes", [])) == sorted(r["quotes"]) and old["chapter"] == r["chapter"]:
            r = {**r, **{k: old[k] for k in ("quotes", "quote_ok", "quote_ratios", "dropped_quotes") if k in old}}
        out.append(r)
    write_jsonl(path, out)


def write_derived(workdir, kb):
    ladders = [] if kb.laddered else read_json(Path(workdir) / "ladders.json", [])
    if ladders:
        kb = copy.deepcopy(kb)
        kb.apply_ladders(ladders)
    carry_quote_checks(Path(workdir) / "facts.jsonl", kb.facts)
    carry_quote_checks(Path(workdir) / "relations.jsonl", kb.relations)
    write_jsonl(Path(workdir) / "questions.jsonl", list(kb.questions.values()))
    write_json(Path(workdir) / "entities.json", list(kb.entities.values()))
    write_json(Path(workdir) / "timelines.json", list(kb.timelines.values()))
