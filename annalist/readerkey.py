import difflib
import json
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .backends import load_settings
from .files import write_json
from .llm import cached_llm, spent_since
from .names import singular
from .scorecard import Item, Wiki, match_key, percent

MATCH_RATIO = 0.6
AGREEING = ("agree", "partly")
VERDICTS = AGREEING + ("disagree",)
SECTIONS = ("questions", "merges", "relations", "structure")
OUTCOMES = ("pass", "fail", "lead_only", "unmatched", "name_missing", "not_scored")

PASSES = {
    "resolved_in_volume": lambda state, verdict: state == "resolved" and verdict in AGREEING,
    "resolved_or_implied_in_volume": lambda state, verdict: state in ("resolved", "lead") and verdict in AGREEING,
    "false_premise": lambda state, verdict: state == "premise-false" or (state == "resolved" and verdict == "agree"),
    "lead_then_resolved": lambda state, verdict: state == "resolved" and verdict in AGREEING,
}

SHOWN_AS = {"resolved": "answer", "lead": "leads so far", "premise-false": "finding that the question's premise is false"}

JUDGE_PROMPT = """A reader who knows the book answered a question about it in their own words. A wiki built from the book, read up to chapter {n}, gives its own {shown} for the same question. Judge whether the wiki agrees with the reader.

Reader's question: {question}
Reader's answer: {reader}
Wiki's question: {wiki_question}
Wiki's {shown}:
{wiki}

Reply with one JSON object: {{"verdict": "agree" or "partly" or "disagree", "reasoning": "one or two sentences"}}.
- agree: the wiki states the reader's answer, in any words.
- partly: the wiki gives part of the reader's answer or points toward it, and contradicts none of it.
- disagree: the wiki gives a different answer, contradicts the reader, or says nothing that bears on the reader's answer.
"""


@dataclass(frozen=True)
class Standing:
    state: str
    chapter: int | None
    text: str
    quote: str
    leads: tuple


def standing(q, n):
    leads = tuple(sorted((l for l in q["leads"] if l["chapter"] <= n), key=lambda l: l["chapter"]))
    premise, done, ending = q.get("premise"), q.get("resolved"), q.get("ending")
    if premise and premise["chapter"] <= n:
        return Standing("premise-false", premise["chapter"], premise["explanation"],
                        next((r["quote"] for r in premise.get("quotes", [])), ""), leads)
    if done and done.get("shown", done["chapter"]) <= n:
        return Standing("resolved", done["chapter"], done["answer"], done.get("quote", ""), leads)
    if ending and ending["chapter"] <= n and ending.get("verdict") == "answered-implicitly":
        return Standing("resolved", ending["chapter"], ending.get("answer", ""),
                        next((r["quote"] for r in ending.get("quotes", [])), ""), leads)
    if leads:
        return Standing("lead", leads[-1]["chapter"], leads[-1]["text"], leads[-1]["quote"], leads)
    return Standing("open", None, "", "", ())


def wiki_says(s):
    if s.state == "lead":
        return [f"ch{l['chapter']}: {l['text']} | quote: \"{l['quote']}\"" for l in s.leads]
    return [f"ch{s.chapter}: {s.text}" + (f" | quote: \"{s.quote}\"" if s.quote else "")]


def judge_problem(reply):
    return None if reply.get("verdict") in VERDICTS else f"verdict must be one of {', '.join(VERDICTS)}"


def judge(workdir, settings, n, ask, q, s):
    prompt = JUDGE_PROMPT.format(n=n, shown=SHOWN_AS[s.state], question=ask["question"], reader=ask["reader_answer"],
                                 wiki_question=q["question"], wiki="\n".join(f"- {line}" for line in wiki_says(s)))
    reply = cached_llm(workdir, "judge", prompt, check=judge_problem, settings=settings)
    return reply["verdict"], str(reply.get("reasoning") or "").strip()


def plain(text):
    return re.sub(r"\W+", " ", str(text).lower()).strip()


def best_question(ask, questions):
    ranked = sorted(((difflib.SequenceMatcher(None, plain(ask["question"]), plain(q["question"])).ratio(), q) for q in questions),
                    key=lambda r: r[0], reverse=True)
    close = [r for r in ranked if r[0] >= MATCH_RATIO]
    raised = [r for r in close if ask.get("raised") is not None and r[1]["chapter"] == ask["raised"]]
    return (raised or close or [None])[0], (ranked or [(0.0, None)])[0]


def chapter_notes(ask, s):
    notes = []
    if ask["expect"] == "lead_then_resolved" and s.state == "resolved":
        before = [l["chapter"] for l in s.leads if l["chapter"] < s.chapter]
        notes.append(f"lead ch{before[0]} before the answer ch{s.chapter}" if before else f"no lead before the answer ch{s.chapter}")
    for field, wiki in (("lead_chapter", s.leads[0]["chapter"] if s.leads else None),
                        ("answer_chapter", s.chapter if s.state == "resolved" else None)):
        if ask.get(field) is not None:
            notes.append(f"reader {field.split('_')[0]} ch{ask[field]}, wiki " + (f"ch{wiki}" if wiki else "none")
                         + (": same" if wiki == ask[field] else ": differs"))
    return notes


def question_items(workdir, settings, wiki_data, n, asks):
    questions = [q for q in wiki_data.get("questions", []) if q["chapter"] <= n]
    items = []
    for i, ask in enumerate(asks, 1):
        iid = f"question:{i}"
        evidence = [f"reader ({ask['expect']}, {ask['confidence']}): {ask['question']}", f"reader answer: {ask['reader_answer']}"]
        match, best = best_question(ask, questions)
        if match is None:
            near = f"; closest: {best[1]['id']} \"{best[1]['question']}\"" if best[1] else ""
            items.append(Item("questions", iid, "unmatched", f"no wiki question raised by ch{n} matches; best ratio {best[0]:.2f}{near}", evidence))
            continue
        ratio, q = match
        s = standing(q, n)
        evidence.append(f"wiki {q['id']} raised ch{q['chapter']} (ratio {ratio:.2f}): {q['question']}")
        if s.state == "open":
            items.append(Item("questions", iid, "fail", f"open at ch{n}; nothing for the judge", evidence + chapter_notes(ask, s)))
            continue
        evidence += [f"wiki {SHOWN_AS[s.state]}: {line}" for line in wiki_says(s)]
        verdict, reasoning = judge(workdir, settings, n, ask, q, s)
        evidence.append(f"judge {verdict}: {reasoning}")
        if ask["confidence"] == "unsure":
            ok = bool(s.quote or any(l["quote"] for l in s.leads))
        elif ask["expect"] in PASSES:
            ok = PASSES[ask["expect"]](s.state, verdict)
        else:
            items.append(Item("questions", iid, "not_scored", f"unknown expect {ask['expect']!r}", evidence))
            continue
        items.append(Item("questions", iid, "pass" if ok else "fail", f"{s.state} ch{s.chapter}; judge {verdict}",
                          evidence + chapter_notes(ask, s)))
    return items


@dataclass(frozen=True)
class Hit:
    eid: str
    name: str
    since: int


def name_form(name):
    return re.sub(r"[\"']", "", match_key(name))


def stem_form(name):
    return " ".join(singular(w) for w in re.sub(r"['’]s\b", "", match_key(name)).replace('"', "").replace("'", "").split())


class Names:
    def __init__(self, wiki):
        self.wiki = wiki
        self.forms = []
        for eid, e in wiki.all.items():
            joined = e["merged"]["chapter"] if e.get("merged") else 0
            self.forms.append((name_form(e["name"]), Hit(eid, e["name"], joined)))
            self.forms += [(name_form(a["name"]), Hit(eid, a["name"], max(joined, a["chapter"]))) for a in e["aliases"]]

    def find(self, name):
        form = name_form(name)
        words = set(form.split())
        exact = [h for f, h in self.forms if f == form] or [h for f, h in self.forms if stem_form(f) == stem_form(name)]
        inside = [(len(set(f.split()) - words), h) for f, h in self.forms if words and words < set(f.split())]
        around = [(len(words - set(f.split())), h) for f, h in self.forms if f and set(f.split()) < words]
        rank = lambda h: (h.since, self.wiki.all[h.eid]["first"])
        if exact:
            return min(exact, key=rank)
        for found in (inside, around):
            if found:
                return min(found, key=lambda c: (c[0], rank(c[1])))[1]
        return None


def possibly_lead(wiki, a, b, n):
    for src, dst in ((a, b), (b, a)):
        for p in wiki.all[src.eid].get("possibly", []):
            if p["chapter"] <= n and wiki.page_id(p["id"], n) == wiki.page_id(dst.eid, n) and wiki.visible(wiki.page_id(p["id"], n), n):
                return p
    return None


def merge_items(wiki, names, n, merges):
    items = []
    for i, m in enumerate(merges, 1):
        iid = f"merge:{i}"
        first, second = m["names"][0], m["names"][1]
        evidence = [f"reader ({m.get('confidence', '?')}): {first} = {second}" + (f"; {m['note']}" if m.get("note") else "")]
        a, b = names.find(first), names.find(second)
        lost = [x for x, h in ((first, a), (second, b)) if h is None]
        if lost:
            items.append(Item("merges", iid, "name_missing", f"name not in wiki: {', '.join(lost)}", evidence))
            continue
        evidence += [f"\"{x}\" is \"{h.name}\" on {wiki.label(h.eid)}" for x, h in ((first, a), (second, b))]
        if wiki.root(a.eid) == wiki.root(b.eid):
            since = max(a.since, b.since)
            joined = f"one entry from ch{since}" if since else "one entry"
            ok = since <= n
            items.append(Item("merges", iid, "pass" if ok else "fail", joined + ("" if ok else f", after the scope end ch{n}"), evidence))
            continue
        lead = possibly_lead(wiki, a, b, n)
        if lead:
            outcome = "lead_only" if m.get("confidence") == "sure" else "pass"
            items.append(Item("merges", iid, outcome, f"separate entries; possibly, ch{lead['chapter']}",
                              evidence + [f"possibly quote: \"{lead['quote']}\""]))
        else:
            items.append(Item("merges", iid, "fail", f"separate entries at ch{n}, with no possibly lead", evidence))
    return items


def relation_items(wiki, names, n, relations):
    items = []
    for i, r in enumerate(relations, 1):
        iid = f"relation:{i}"
        evidence = [f"reader: {r['entry']} related to {r['related_to']}" + (f"; {r['note']}" if r.get("note") else "")]
        a, b = names.find(r["entry"]), names.find(r["related_to"])
        lost = [x for x, h in ((r["entry"], a), (r["related_to"], b)) if h is None]
        if lost:
            items.append(Item("relations", iid, "name_missing", f"name not in wiki: {', '.join(lost)}", evidence))
            continue
        pa, pb = wiki.page_id(a.eid, n), wiki.page_id(b.eid, n)
        if pa == pb:
            items.append(Item("relations", iid, "fail", f"both names are one entry at ch{n}", evidence))
            continue
        rows = [x for x in wiki.relations if {wiki.root(x["source"]), wiki.root(x["target"])} == {wiki.root(a.eid), wiki.root(b.eid)}]
        shown = [x for x in rows if x["chapter"] <= n and {wiki.page_id(x["source"], n), wiki.page_id(x["target"], n)} == {pa, pb}
                 and wiki.visible(pa, n) and wiki.visible(pb, n)]
        evidence += [f"ch{x['chapter']}: {wiki.all[x['source']]['name']} {x['type']} {wiki.all[x['target']]['name']}"
                     + (f" | \"{x['quotes'][0]}\"" if x.get("quotes") else "") for x in (shown or rows)]
        if shown:
            items.append(Item("relations", iid, "pass", f"{shown[0]['type']} from ch{shown[0]['chapter']}", evidence))
        else:
            later = f"; first shown ch{min(x['chapter'] for x in rows)}" if rows else ""
            items.append(Item("relations", iid, "fail", f"no relation between them by ch{n}{later}", evidence))
    return items


def plural(t):
    if re.search(r"[^aeiou]y$", t):
        return t[:-1] + "ies"
    return t + "es" if re.search(r"(s|x|ch|sh)$", t) else t + "s"


def ladder_steps(wiki, ladders, eid, n):
    steps = [s for l in ladders if wiki.page_id(l["group"], n) == eid for s in l["steps"]
             if s["chapter"] <= n and wiki.visible(wiki.page_id(s["id"], n), n)]
    return [f"{s['rank']} {wiki.display(s['id'], n)} ch{s['chapter']}" for s in sorted(steps, key=lambda s: s["rank"])]


def without_word(name, word):
    return re.sub(rf"\b{re.escape(name_form(word))}\b", " ", name_form(name)).split()


def typed_page(wiki, n, name, etype):
    form = without_word(name, etype)
    for eid, e in sorted(wiki.entities.items(), key=lambda p: p[1]["first"]):
        if e["type"] == etype and wiki.visible(eid, n) and any(
                without_word(x, etype) == form for x in [e["name"]] + [a["name"] for a in e["aliases"] if a["chapter"] <= n]):
            return eid
    return None


def present_check(wiki, wiki_data, names, n, s):
    ladders = wiki_data.get("ladders", [])
    groups = {wiki.page_id(l["group"], n) for l in ladders if wiki.visible(wiki.page_id(l["group"], n), n)}
    what = str(s.get("what", "")).strip().lower()
    etype = next((t for t in sorted({e["type"] for e in wiki.entities.values()}) if what in (t, plural(t))), None)
    count = sum(1 for eid, e in wiki.entities.items() if e["type"] == etype and wiki.visible(eid, n))
    evidence = [f"{count} {etype} entries at ch{n}" if etype else f"no entry type is named {what}", f"{len(groups)} ladder groups at ch{n}"]
    missing = []
    for name in s["min_expected"]:
        hit = names.find(name)
        page = (etype and typed_page(wiki, n, name, etype)) or (wiki.page_id(hit.eid, n) if hit else None)
        if page and wiki.visible(page, n) and (wiki.all[page]["type"] == etype or page in groups):
            steps = ladder_steps(wiki, ladders, page, n)
            evidence.append(f"present: {name} as \"{wiki.display(page, n)}\" [{wiki.all[page]['type']}]"
                            + (f"; ladder: {', '.join(steps)}" if steps else ""))
        else:
            missing.append(name)
    return ("fail" if missing else "pass", f"missing: {', '.join(missing)}" if missing else f"all {len(s['min_expected'])} present", evidence)


def types_check(wiki, wiki_data, names, n, s):
    wrong, evidence = [], []
    for name, allowed in s.get("expected_types", {}).items():
        hit = names.find(name)
        if hit is None:
            wrong.append(f"{name} missing")
            continue
        page = wiki.page_id(hit.eid, n)
        etype = wiki.all[page]["type"]
        ok = etype in allowed or ("any" in allowed and etype != s.get("none_of_type"))
        evidence.append(f"{name} is \"{wiki.display(page, n)}\" [{etype}]")
        if not ok:
            wrong.append(f"{name} is {etype}, expected {' or '.join(allowed)}")
    banned = s.get("none_of_type")
    left = [wiki.display(eid, n) for eid, e in wiki.entities.items() if banned and e["type"] == banned and wiki.visible(eid, n)]
    if banned:
        evidence.append(f"{len(left)} {banned} at ch{n}" + (f": {', '.join(sorted(left))}" if left else ""))
    problems = wrong + ([f"{len(left)} {banned} left"] if left else [])
    return ("fail" if problems else "pass", "; ".join(problems) or "all types as expected", evidence)


def title_check(wiki, wiki_data, names, n, s):
    hit = names.find(s["entry"])
    if hit is None:
        return "name_missing", f"name not in wiki: {s['entry']}", []
    page = wiki.page_id(hit.eid, n)
    title, first = wiki.display(page, n), wiki.first(page)
    problems = []
    if name_form(title) != name_form(s["expected_title"]):
        problems.append(f"titled \"{title}\", expected \"{s['expected_title']}\"")
    if s.get("expected_first_chapter") is not None and first != s["expected_first_chapter"]:
        problems.append(f"first ch{first}, expected ch{s['expected_first_chapter']}")
    return ("fail" if problems else "pass", "; ".join(problems) or f"titled \"{title}\" from ch{first}", [wiki.label(page)])


def one_death_check(wiki, wiki_data, names, n, s):
    deaths = {}
    for v in wiki_data.get("volumes", []):
        for d in v.get("deaths", []):
            hit = names.find(d["name"])
            if d["chapter"] <= n:
                key = (wiki.root(hit.eid) if hit else d["name"], d.get("timeline", "main"))
                deaths.setdefault(key, []).append(d["chapter"])
    twice = {k: sorted(c) for k, c in deaths.items() if len(c) > 1}
    shown = [f"{wiki.all[k[0]]['name'] if k[0] in wiki.all else k[0]} " + ", ".join(f"ch{c}" for c in chapters)
             for k, chapters in sorted(twice.items(), key=lambda t: t[1])]
    return ("fail" if twice else "pass", f"died more than once: {'; '.join(shown)}" if twice else f"{len(deaths)} deaths, one each",
            [f"{len(deaths)} characters die by ch{n}"])


TYPED_NAME = re.compile(r"^(.*?)\s*\(([^)]+)\)$")


def linked(wiki, eid, text, chapter, n):
    e = wiki.all[eid]
    common = set(e.get("common_names", []))
    for name in wiki.names(eid, n):
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text) and (name not in common or chapter in e.get("linked_chapters", [])):
            return name
    return None


def no_link_check(wiki, wiki_data, names, n, s):
    typed = TYPED_NAME.match(s["must_not_link_to"])
    target_name, target_type = typed.groups() if typed else (s["must_not_link_to"], "")
    targets = [eid for eid, e in wiki.entities.items() if (not target_type or e["type"] == target_type)
               and name_form(target_name) in map(name_form, wiki.names(eid))]
    hit = names.find(s["entry"])
    if hit is None or not targets:
        return "name_missing", f"name not in wiki: {s['entry'] if hit is None else s['must_not_link_to']}", []
    page = wiki.page_id(hit.eid, n)
    shown = [f["claim"] for f in wiki.own_facts(page, n) if f["chapter"] == s["chapter"]
             and any(plain(s["text"]) in plain(x) for x in [f["claim"]] + f.get("quotes", []))]
    if not shown:
        return "unmatched", f"no text of {s['entry']} at ch{s['chapter']} holds the passage", []
    hits = [(text, name) for text in shown for t in targets if (name := linked(wiki, t, text, s["chapter"], n))]
    evidence = [f"ch{s['chapter']}: {text}" + (f" links \"{name}\"" if name else "") for text, name in hits] or [f"ch{s['chapter']}: {t}" for t in shown]
    return ("fail", f"links {s['must_not_link_to']} in {len(hits)} text(s)", evidence) if hits else \
        ("pass", f"{s['must_not_link_to']} is not linked at ch{s['chapter']}", evidence)


CHECKS = {"present": present_check, "types": types_check, "title": title_check, "one_death": one_death_check, "no_link": no_link_check}


def structure_items(wiki, wiki_data, names, n, structure):
    items = []
    for i, s in enumerate(structure, 1):
        iid = f"structure:{i}"
        evidence = [f"reader: {s.get('what')}" + (f"; {s['note']}" if s.get("note") else "")]
        check = s.get("check") or ("present" if s.get("min_expected") else None)
        if check not in CHECKS:
            items.append(Item("structure", iid, "not_scored", f"{s.get('what')}; no check the grader knows", evidence))
            continue
        outcome, detail, more = CHECKS[check](wiki, wiki_data, names, n, s)
        items.append(Item("structure", iid, outcome, detail, evidence + more))
    return items


def scope_end(key, wiki):
    numbers = re.findall(r"\d+", str(key.get("scope") or ""))
    return int(numbers[-1]) if numbers else wiki.chapters[-1]


def grade(workdir, key, wiki_data, settings):
    wiki = Wiki(wiki_data)
    names = Names(wiki)
    n = scope_end(key, wiki)
    items = question_items(workdir, settings, wiki_data, n, key.get("items", []))
    items += merge_items(wiki, names, n, key.get("expected_merges", []))
    items += relation_items(wiki, names, n, key.get("expected_relations", []))
    items += structure_items(wiki, wiki_data, names, n, key.get("expected_structure", []))
    return n, items


def totals(items):
    out = {s: {k: sum(i.section == s and i.outcome == k for i in items) for k in OUTCOMES} for s in SECTIONS}
    out["all"] = {k: sum(out[s][k] for s in SECTIONS) for k in OUTCOMES}
    for t in out.values():
        scored = sum(v for k, v in t.items() if k != "not_scored")
        t["score"] = round(t["pass"] / scored, 3) if scored else None
    return out


def markdown(items, sums, key_path, workdir, n, spend):
    lines = [f"# Reader-key eval of {workdir}", "", f"Reader key: {key_path}", f"Graded as of ch{n}.",
             f"Judge spend: ${spend:.4f}", "",
             "| section | " + " | ".join(OUTCOMES) + " | score |", "|---|" + "---:|" * (len(OUTCOMES) + 1)]
    for section in SECTIONS + ("all",):
        t = sums[section]
        lines.append(f"| {section} | " + " | ".join(str(t[k]) for k in OUTCOMES) + f" | {percent(t['score'])} |")
    for section in SECTIONS:
        rows = [i for i in items if i.section == section]
        if rows:
            lines += ["", f"## {section}", ""]
            for i in sorted(rows, key=lambda i: i.outcome == "pass"):
                lines.append(f"- **{i.outcome}** `{i.id}`: {i.detail}")
                lines += [f"  - {e}" for e in i.evidence]
    return "\n".join(lines) + "\n"


def run_reader_eval(workdir, key_path, wiki_data, out, judge_model=None):
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    settings = load_settings(workdir)
    if judge_model:
        settings = replace(settings, models={**settings.models, "judge": judge_model})
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    n, items = grade(workdir, key, wiki_data, settings)
    spend = spent_since(workdir, started)
    sums = totals(items)
    write_json(out / "reader-eval.json", {"reader_key": str(Path(key_path).resolve()), "workdir": str(workdir), "scope_end": n,
                                          "judge_model": settings.model_for("judge"), "judge_spend_usd": spend,
                                          "totals": sums, "items": [asdict(i) for i in items]})
    (out / "reader-eval.md").write_text(markdown(items, sums, key_path, workdir, n, spend), encoding="utf-8")
    for section in SECTIONS + ("all",):
        t = sums[section]
        others = ", ".join(f"{t[k]} {k}" for k in OUTCOMES[2:] if t[k])
        print(f"  {section:<10} {t['pass']:>4} pass {t['fail']:>4} fail  {percent(t['score']):>6}" + (f"  ({others})" if others else ""))
    print(f"  judge spend ${spend:.4f}")
    print(f"wrote {out / 'reader-eval.md'} and {out / 'reader-eval.json'}")
