import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .files import log, read_json, read_jsonl, write_json
from .llm import llm
from .state import load_states, write_derived

FAMILIES = (
    ("kin", r"nephew|niece|uncle|aunt|sons?|daughter|father|mother|brother|sister|sibling|parents?|child|children|cousin"
            r"|grand\w*|descendant|ancestor|relatives?|kin|family|heir|inherit\w*|legatee|twin"),
    ("romance", r"married|marry|husband|wife|spouse|widow\w*|suitor|lover?s?|loves|court\w*|engaged|betrothed|fianc\w*"
                r"|girlfriend|boyfriend|dating|ex|romantic\w*|intimate|marriage|attracted"),
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
                 r"|trades?|admires?|respects?|owes|indebted|benefactor|patron|sponsor\w*|backs|backed|gave|gives|offers?"
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
- When the wording shows both a friendly tie and an adversarial or investigative one between source and target, choose the friendly kind.
- When the wording says that the source believes, suspects, or claims something about the target, choose the kind of what is believed; choose investigation only when the suspicion itself is the relationship.
- Copy each wording and the target's kind exactly as listed.

LINES:
{wordings}

Reply with one JSON object: {{"kinds": [{{"wording": "...", "target": "the target's kind", "kind": "..."}}]}}
"""


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


def read_families(workdir):
    return read_json(Path(workdir) / FILE, {"readings": {}})["readings"]


def check_reading(reply):
    if not isinstance(reply.get("kinds"), list):
        return "no kinds list"
    unknown = [k.get("kind") for k in reply["kinds"] if isinstance(k, dict) and k.get("kind") not in NAMES]
    return f"unknown kinds {unknown}; use only {', '.join(NAMES)}" if unknown else None


def read_batch(workdir, lines):
    prompt = FAMILY_PROMPT.format(kinds="\n".join(f"- {f}: {DESCRIPTIONS[f]}" for f in NAMES),
                                  wordings="\n".join(f"- source [{s}] {w} target [{t}]" for w, t, s in lines))
    reply = llm(workdir, "families", prompt, check=check_reading)
    given = {reading_key(wording_key(k.get("wording")), str(k.get("target") or "").strip().lower()): k["kind"]
             for k in reply["kinds"] if isinstance(k, dict)}
    return {reading_key(w, t): given.get(reading_key(w, t)) or rule_family(w) for w, t, _ in lines}


def cmd_families(args):
    workdir = Path(args.workdir).resolve()
    write_derived(workdir, load_states(workdir))
    readings = {k: v for k, v in read_families(workdir).items() if k.endswith("]")}
    types = {e["name"]: e["type"] for e in read_json(workdir / "entities.json", [])}
    ends = {}
    for r in read_jsonl(workdir / "relations.jsonl"):
        ends.setdefault((wording_key(r["type"]), types.get(r["target"], "")), types.get(r["source"], ""))
    unread = [(w, t, s) for (w, t), s in sorted(ends.items()) if reading_key(w, t) not in readings and len(signals(w)) != 1]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for reading in pool.map(lambda i: read_batch(workdir, unread[i:i + BATCH]), range(0, len(unread), BATCH)):
            readings.update(reading)
    write_json(workdir / FILE, {"readings": dict(sorted(readings.items()))})
    log(workdir, f"families: {len(ends)} wordings by target kind, {len(ends) - len(unread)} settled by rules or earlier readings, "
                 f"{len(unread)} read")
