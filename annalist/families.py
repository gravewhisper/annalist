import re
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sys
from pathlib import Path

from .backends import load_settings
from .estimate import prompt_pricer
from .files import log, read_json, read_jsonl, write_json
from .llm import Budget, BudgetSpent, cached_llm, cached_reply, UNLIMITED
from .state import load_states, relation_key, write_derived

FAMILIES = (
    ("kin", r"nephew|niece|uncle|aunt|sons?|daughter|father|mother|brother|sister|sibling|parents?|child|children|cousin"
            r"|grand\w*|descendant|ancestor|relatives?|kin|family|heir|inherit\w*|legatee|twin"),
    ("romance", r"married|marry|husband|wife|spouse|widow\w*|suitor|lover?s?|loves|courted|courting|courtship|engaged|betrothed|fianc\w*"
                r"|girlfriend|boyfriend|dating|ex|romantic\w*|intimate|marriage"),
    ("faith", r"worship\w*|prays?|prayed|praying|devot\w*|believes in|believers?|faithful|pious|cult|cultists?|deacon"
              r"|priest\w*|cardinal|bishop|pope|clergy|cleric|saint|blessed|chosen|favou?red by|angel of|oracle|prophet\w*"
              r"|deity|god of|goddess of"),
    ("teaching", r"mentor\w*|teach\w*|taught|learn\w*|tutor\w*|instruct\w*|train\w*|coach\w*|apprentice|disciple|student"
                 r"|pupil|graduate of|studied under|stud(?:ies|ied|ying)|examiner|educat\w*|guide of|lectur\w*|recommended"),
    ("hostility", r"enem\w*|kill\w*|murder\w*|plot\w*|threat\w*|rival\w*|attack\w*|hunt\w*|target\w*|victim|arrest\w*|pursu\w*"
                  r"|schem\w*|wreck\w*|defeat\w*|captive|captor|prisoners?|abused|imprison\w*|deceived|manipulated"
                  r"|hijacks?|destroy\w*|breach\w*|haunts?|estranged|betray\w*|fights?|fought|escaped|frighten\w*"
                  r"|hostile|odds|oppos\w*|against|feud\w*|resent\w*|distrust\w*|hates?|hated|fears?|feared"
                  r"|impersonat\w*|stole|steals?|robbed|blackmail\w*|curse[ds]?|duel\w*|competes?|competitor|quarrel\w*"
                  r"|hostage|assassinat\w*"),
    ("investigation", r"investigat\w*|suspect\w*|suspicio\w*|interrogat\w*|questioned|questions|spied|spies on|spying"
                      r"|followed|shadowed|tails|tailed|surveil\w*|eavesdrop\w*|inquir\w*|probes|probed"),
    ("service", r"butler|servants?|maid\w*|housekeeper|employ\w*|works?|worked|working|assistant|agent|helper|hired|serves?"
                r"|served|serving|steward|secretary|messenger|spy|informant|physician|doctor|surgeon|archivist|mate|crew"
                r"|subordinate|sidekick|bodyguard|lieutenant|deputy|consigliere|chauffeur|driver|subcontractor|almoner"
                r"|report\w* (?:\w+ )?to|assigned to|pilot of|executor|trustee|manages|managed|manager|finances|represents"
                r"|geneticist|commands?|commanded|orders|boss|supervis\w*|superior|in charge|staff|customer|landlord|landlady"
                r"|patient|seamstress|tailor|clerk|escorts?|escorted|commission\w*|recruit\w*|hires|vassal|obeys|handler"
                r"|contact of|intelligence|underling|minion|retainer|squire"),
    ("membership", r"members?|leader|head|founder|captain|belongs?|part of|participant|rules|ruled|ruler|mayor|sheriff|president"
                   r"|chief|commander|officer|joined|joins?|leadership|successor|citizen|groupmate|team|squad|director"
                   r"|chair\w*|leads|founded|elder of|king of|queen of|emperor of|lord of|governor|applicant|candidate|enlisted|enrolled"),
    ("alliance", r"friends?|ally|allies|allied|colleague|companion|partner|confidant|acquain\w*|teammate|roommate|guest"
                 r"|host|travels with|lives with|consult\w*|client|rescuer|rescued|saved|helped|helps?|assist(?:s|ed)?|aids?"
                 r"|protect\w*|guard\w*|collaborat\w*|associate|loyal\w*|follower|supporter|supports|sworn|pledged|trusts?"
                 r"|trusted|accompan\w*|corresponds?|correspondent|letter|wrote to|sends|meets?|met|visitor of|neighbou?r"
                 r"|trades?|admir(?:es?|ed|ers?|ing|ation)|respects?|owes|indebted|benefactor|patron|sponsor\w*|backs|backed|gave|gives|offers?"
                 r"|invited"),
    ("place", r"located|lives?|lived|living|resid\w*|tenant|home|dwell\w*|stays?|staying|lodged|headquarters|near|found in"
              r"|died in|practises in|farmed in|inhabit\w*|occup\w*|born in|visits?|visited|originat\w*|capital of|borders?"
              r"|bordering|buried|stored|hidden in|travel\w* to|arrive\w*|attends?|attended|shops"),
    ("ownership", r"owns?|owned|owner|master of|keeper of|keeps|kept|possess\w*|holds?|holder|custody|bought|purchas\w*"
                  r"|creat\w*|built|builder|crafted|forged|made|makes|invent\w*|author of|written by|wrote|designed"
                  r"|developed|pilots|controls?|controlled|bonded|derives|program of|installed in|wields?|carries"
                  r"|carried|pet of|uses|used|using|consumed|drank|ate|obtained|acquired|received|gift|handed over|ingredient|formula"
                  r"|wears|wore"),
    ("kind", r"is an?|kind of|type of|form of|instance of|variant of|version of|same as|alternate name|also known as|alias"
             r"|resembles|named after|rank of|level of|tier of|grade of|stage of|\w+ \d+ of|precedes|preceded by|follows|following"
             r"|advances? to|evolves? into|next|ability of|power of|currency|worth|equivalent|interchangeable"),
)
FAMILY_PATTERNS = [(f, re.compile(rf"(?<!\w)(?:{p})(?!\w)")) for f, p in FAMILIES]


FRIENDLY = ("kin", "romance", "teaching", "alliance")
ADVERSE = ("hostility", "investigation")
NAMES = tuple(f for f, _ in FAMILIES) + ("other",)
DESCRIPTIONS = {
    "kin": "blood or legal family: parent, child, sibling, cousin, heir",
    "romance": "marriage, courtship, love, attraction, engagement, a former partner",
    "faith": "worship, belief in a deity, clergy and their church",
    "teaching": "mentor and student, teacher, instructor, apprentice",
    "hostility": "enemy, rival, attacker, killer, captor, someone who hates, hunts, or harms the other",
    "investigation": "one investigates, suspects, questions, follows, or spies on the other, without open enmity",
    "service": "employer and employee, servant, agent, client and provider, commander and subordinate",
    "membership": "member, leader, or founder of a group, citizen of a state",
    "alliance": "friend, ally, colleague, partner, companion, helper, correspondent, acquaintance",
    "place": "where someone or something is, lives, comes from, or goes",
    "ownership": "owning, holding, making, using, or wearing a thing",
    "kind": "a kind, rank, stage, or other name of something",
    "other": "none of the above",
}
FILE = "families.json"
BATCH = 40

FAMILY_PROMPT = """A wiki about a novel draws a graph of the relations between its entries and colours each line by the kind of relationship. Each line below is read as "source <wording> target", with the kind of entry at each end in brackets. Give each line the one kind that says what the relationship between source and target is.

Kinds:
{kinds}

Rules:
- Judge what the whole wording means for the relationship between source and target, not single words in it. "colleague and investigation partner of" is alliance: the two investigate together.
- Judge the wording together with the kinds of entry at its ends: the same verb toward a person, a group, or a thing can be a different kind.
- Admiration, respect, or gratitude is alliance, not romance. Grief, worry, care, or a gift is not romance either, and neither is a romance the source hopes for, arranges, or fears for someone else. Choose romance only when the wording says love, desire, courtship, marriage, sex, or a former partner between source and target themselves.
- When a wording could mean romance or something plain, such as being involved with someone, sleeping with someone, or spending the night with someone, choose romance: each such line is then checked against its quote.
- When the wording shows both a friendly tie and an adversarial or investigative one between source and target, choose the friendly kind.
- When the wording says that the source believes, suspects, or claims something about the target, choose the kind of what is believed; choose investigation only when the suspicion itself is the relationship.
- Copy each wording and the target's kind exactly as listed.

LINES:
{wordings}

Reply with one JSON object: {{"kinds": [{{"wording": "...", "target": "the target's kind", "kind": "..."}}]}}
"""

ROMANCE_PROMPT = """A wiki about a novel colours a line of its graph as romance when it shows romance between the two entries at its ends. The wording of each line below could mean romance, but it may mean something plain: being involved in an event together, a soul or avatar sleeping inside someone, grief, care, or a gift. Read each line together with its quote from the book.

Kinds:
{kinds}

LINES:
{lines}

Give romance only when the line shows love, desire, courtship, marriage, sex, or a former partner between source and target themselves. Otherwise give the one other kind that says what the relationship between source and target is.

Reply with one JSON object: {{"lines": [{{"id": "...", "kind": "..."}}]}}, one entry per line.
"""
LINE_BATCH = 20


def wording_key(rtype):
    return re.sub(r"\s+", " ", str(rtype).lower().replace("_", " ")).strip(" .,;:!?\"'")


def signals(key):
    return [f for f, pattern in FAMILY_PATTERNS if pattern.search(key)]


def terms(key):
    return {m.group(0)[:4] for _, pattern in FAMILY_PATTERNS for m in pattern.finditer(key)}


def rule_family(key):
    found = signals(key)
    friendly = [f for f in found if f in FRIENDLY]
    if friendly and any(f in ADVERSE for f in found):
        return friendly[0]
    return found[0] if found else "other"


def reading_key(key, target_type):
    return f"{key} [{target_type}]"


def relation_family(rtype, readings=None, target_type=None):
    key = wording_key(rtype)
    return (readings or {}).get(reading_key(key, target_type)) or rule_family(key)


def kind_list():
    return "\n".join(f"- {f}: {DESCRIPTIONS[f]}" for f in NAMES)


def prompt_version():
    return hashlib.sha1((FAMILY_PROMPT + ROMANCE_PROMPT + kind_list()).encode("utf-8")).hexdigest()[:12]


def read_families(workdir):
    return read_json(Path(workdir) / FILE, {"readings": {}})["readings"]


def read_lines(workdir):
    return read_json(Path(workdir) / FILE, {"lines": {}}).get("lines") or {}


def line_family(row, readings, lines, target_type):
    return lines.get(relation_key(row)) or relation_family(row["type"], readings, target_type)


def check_kinds(field):
    def check(reply):
        if not isinstance(reply.get(field), list):
            return f"no {field} list"
        unknown = [k.get("kind") for k in reply[field] if isinstance(k, dict) and k.get("kind") not in NAMES]
        return f"unknown kinds {unknown}; use only {', '.join(NAMES)}" if unknown else None
    return check


def wording_prompt(lines):
    return FAMILY_PROMPT.format(kinds=kind_list(), wordings="\n".join(f"- source [{s}] {w} target [{t}]" for w, t, s in lines))


def wording_kinds(reply, lines):
    given = {reading_key(wording_key(k.get("wording")), str(k.get("target") or "").strip().lower()): k["kind"]
             for k in reply["kinds"] if isinstance(k, dict)}
    return {reading_key(w, t): given.get(reading_key(w, t)) or rule_family(w) for w, t, _ in lines}


def line_item(row):
    detail = f" {row['detail']}" if row.get("detail") else ""
    quotes = "\n".join(f"Quote: {q}" for q in row["quotes"][:2])
    return f"id: {relation_key(row)}\nLine: \"{row['source']}\" {row['type']} \"{row['target']}\"{detail}\n{quotes}"


def line_prompt(rows):
    return ROMANCE_PROMPT.format(kinds=kind_list(), lines="\n\n".join(line_item(r) for r in rows))


def line_kinds(reply, rows):
    keys = {relation_key(r) for r in rows}
    return {str(k["id"]): k["kind"] for k in reply["lines"] if isinstance(k, dict) and str(k.get("id")) in keys}


def batches(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def ask(workdir, args, purpose, asks, field, spent):
    settings = load_settings(workdir)
    price = prompt_pricer(workdir, settings)
    misses = {p: price(purpose, p) for p, _ in asks if cached_reply(workdir, purpose, p, settings) is None}
    cost = None if None in misses.values() else sum(misses.values())
    print(f"{purpose}: {len(asks)} prompts, {len(misses)} not answered yet, price: {'unknown' if cost is None else f'${cost:,.2f}'}")
    if getattr(args, "dry_run", False):
        return None, spent
    cap = getattr(args, "budget", None)
    gate = UNLIMITED if cap is None else Budget(cap - spent, {(purpose, p): c or 0.0 for p, c in misses.items()})
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        replies = list(pool.map(lambda a: cached_llm(workdir, purpose, a[0], check=check_kinds(field), settings=settings, gate=gate), asks))
    return replies, spent + (0.0 if gate is UNLIMITED else gate.spent)


def cmd_families(args):
    workdir = Path(args.workdir).resolve()
    kb = load_states(workdir)
    write_derived(workdir, kb)
    saved = read_json(workdir / FILE, {"readings": {}})
    current = saved.get("prompt") == prompt_version()
    readings = {k: v for k, v in saved["readings"].items() if k.endswith("]")} if current else {}
    lines = dict(saved.get("lines") or {}) if current else {}
    types = {e["name"]: kb.types.kind(e["type"]) for e in read_json(workdir / "entities.json", [])}
    rows = read_jsonl(workdir / "relations.jsonl")
    ends = {}
    for r in rows:
        ends.setdefault((wording_key(r["type"]), types.get(r["target"], "")), types.get(r["source"], ""))
    unread = [(w, t, s) for (w, t), s in sorted(ends.items()) if reading_key(w, t) not in readings]

    def save():
        write_json(workdir / FILE, {"prompt": prompt_version(), "readings": dict(sorted(readings.items())), "lines": dict(sorted(lines.items()))})
    try:
        asks = [(wording_prompt(b), b) for b in batches(unread, BATCH)]
        replies, spent = ask(workdir, args, "families", asks, "kinds", 0.0)
        if replies is None:
            print("romance: the lines read as romance are priced once the wordings are read")
            return
        for reply, (_, b) in zip(replies, asks):
            readings.update(wording_kinds(reply, b))
        pink = [r for r in rows if relation_family(r["type"], readings, types.get(r["target"], "")) == "romance"]
        keys = {relation_key(r) for r in pink}
        lines = {k: v for k, v in lines.items() if k in keys}
        unchecked = [r for r in pink if relation_key(r) not in lines]
        asks = [(line_prompt(b), b) for b in batches(unchecked, LINE_BATCH)]
        replies, spent = ask(workdir, args, "romance", asks, "lines", spent)
        for reply, (_, b) in zip(replies, asks):
            lines.update(line_kinds(reply, b))
    except BudgetSpent as exc:
        save()
        sys.exit(f"annalist families: {exc}; the readings paid for are kept")
    save()
    log(workdir, f"families: {len(ends)} wordings by target kind, {len(ends) - len(unread)} read before, "
                 f"{len(unread)} read; {len(pink)} romance lines, {len(unchecked)} checked against their quotes")
