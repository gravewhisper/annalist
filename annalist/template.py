import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EntityType:
    name: str
    label: str
    description: str


ENTITY_TYPES = {t.name: t for t in (
    EntityType("character", "Character", "one specific person or individual being, whatever class, species, or rank the story gives them"),
    EntityType("place", "Place", "a location: a city, building, region, world, or room"),
    EntityType("organization", "Organization", "a group with members: a gang, church, company, family business, or team"),
    EntityType("artifact", "Item", "one specific object: a weapon, relic, document, vehicle, or possession"),
    EntityType("event", "Event", "something that happened at a time: a battle, festival, disaster, or meeting"),
    EntityType("deity", "Deity", "a god or godlike being worshipped in the story"),
    EntityType("creature", "Creature", "a kind, species, or race of non-human being, such as a monster, beast, or spirit, or one such "
                                       "being the story never names; one with a name of its own, or one who speaks, is a character; "
                                       "one god is a deity, and a kind or class of gods is a concept"),
    EntityType("concept", "Concept", "an idea, rule, custom, or phenomenon of the story's world"),
)}


UNCATEGORIZED = "uncategorized"


BASE_TYPES = set(ENTITY_TYPES) | {UNCATEGORIZED}


INDIVIDUALS = ("character", "deity")


PARENT_TYPES = tuple(t for t in ENTITY_TYPES if t not in INDIVIDUALS)


DEFAULT_PARENT = "concept"


DEFAULT_POWER_TYPES = {"ability": {"parent": "concept", "description": "a specific power or technique"}}


def inferred_parent(name):
    head = (name.split() or [""])[-1]
    return next((t.name for t in ENTITY_TYPES.values() if t.name in PARENT_TYPES and head in (t.name, t.label.lower())), DEFAULT_PARENT)


def book_type(name, raw):
    spec = raw if isinstance(raw, dict) else {"description": raw}
    parent = str(spec.get("parent") or "").strip().lower()
    label = str(spec.get("label") or "").strip()
    return {"parent": parent if parent in PARENT_TYPES else inferred_parent(name), "description": str(spec.get("description") or "").strip(),
            **({"label": label} if label else {})}


def book_types(raw):
    return {k: book_type(k, v) for k, v in (raw or {}).items() if k not in BASE_TYPES}


def type_parents(raw):
    return {k: spec["parent"] for k, spec in book_types(raw).items()}


def singular(word):
    word = word.lower()
    if re.search(r"[^aeiou]ies$", word):
        return word[:-3] + "y"
    if re.search(r"(?:ss|x|ch|sh)es$", word):
        return word[:-2]
    return word[:-1] if re.search(r"[^su]s$", word) else word


def name_forms(name):
    words = re.findall(r"[\w'’-]+", str(name).lower())
    words = words[1:] if words[:1] == ["the"] and len(words) > 1 else words
    return {" ".join(words), " ".join(words[:-1] + [singular(words[-1])])} if words else set()


def written(phrase, text):
    return any(re.search(r"(?<![\w-])" + re.escape(form).replace(r"\ ", r"\s+") + r"(?:e?s)?(?![\w-])", text, re.I) for form in name_forms(phrase))


LEAD_STOP = {"of", "in", "within", "inside", "with", "without", "that", "which", "who", "whose", "where", "when", "for", "from", "to", "by",
             "on", "at", "under", "into", "such", "as", "or", "and", "like", "than"}


def lead_words(description):
    words = []
    for word in re.findall(r"[\w'’-]+|[^\w\s]", re.sub(r"\([^)]*\)", " ", str(description).lower())):
        if not words and word in ("a", "an", "the", "one", "any"):
            continue
        if word in LEAD_STOP or not re.match(r"\w", word):
            break
        words.append(singular(word))
    return words


def head_word(name):
    words = str(name).lower().split()
    return singular(words[-1]) if words else ""


def category_problems(types, names):
    """Problems with the subcategories in types ({type: {parent, description, label}}) given the book's entries ({name: type}):
    two subcategories of one parent that overlap, and a subcategory named like one entry of the book. A concept entry, or an entry
    filed under the category itself, may share the category's name, since it is the idea the category groups."""
    problems = []
    keys = list(types)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if types[a]["parent"] != types[b]["parent"]:
                continue
            words_a, words_b = set(map(singular, a.split())), set(map(singular, b.split()))
            labels = [min(name_forms(types[t].get("label") or t), key=len) for t in (a, b)]
            kinds = [(x, y) for x, y in ((a, b), (b, a)) if head_word(y) in lead_words(types[x]["description"]) and head_word(x) != head_word(y)]
            if not (words_a <= words_b or words_b <= words_a or labels[0] == labels[1] or kinds):
                continue
            why = (f'"{kinds[0][0]}" is described as a kind of {head_word(kinds[0][1])} ("{types[kinds[0][0]]["description"]}")' if kinds
                   else "their names cover the same entries")
            problems.append(f'the {types[a]["parent"]} subcategories "{a}" and "{b}" overlap: {why}. Subcategories of one general type '
                            f"must not overlap; keep one, or describe each so that no entry fits both.")
    entries = {}
    for name, etype in sorted(names.items()):
        for form in name_forms(name):
            entries.setdefault(form, []).append((name, etype))
    for t, spec in types.items():
        forms = sorted(set().union(*(name_forms(word) for word in (t, spec.get("label") or ""))))
        hit = next((hit for f in forms for hit in entries.get(f, []) if hit[1] not in ("concept", t)), None)
        if hit:
            problems.append(f'the subcategory "{spec.get("label") or t}" is named like the {hit[1]} "{hit[0]}", one entry of the book, so a reader '
                            f"cannot tell the category from that entry; name the category by another word the book uses for these entries.")
    return problems


class Types:
    def __init__(self, parents):
        self.parents = dict(parents)

    def kind(self, etype):
        return self.parents.get(etype, etype)

    def refines(self, etype, parent):
        return self.parents.get(etype) == parent

    def kin(self, a, b):
        return a == b or self.refines(a, b) or self.refines(b, a)

    def is_a(self, etype, kinds):
        return self.kind(etype) in kinds or etype in kinds


STATUS_VALUES = ("alive", "dead", "missing", "revived", "unknown")


STORY_TIMELINE_KINDS = ("loop", "flashback", "linear")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    aliases: tuple = ()
    values: tuple = ()
    kind: str = "text"
    hint: str = ""


CHARACTER_FIELDS = {f.key: f for f in (
    Field("full_name", "Full name", ("name", "real_name", "birth_name", "true_name"), kind="name"),
    Field("sex", "Sex", ("gender",)),
    Field("age", "Age"),
    Field("birthdate", "Birthdate", ("birthday", "date_of_birth", "born")),
    Field("height", "Height"),
    Field("marital_status", "Marital status", ("spouse", "married", "marriage")),
    Field("status", "Status", ("alive", "life_status", "alive_or_dead", "vital_status", "condition", "living_status"),
          STATUS_VALUES),
    Field("affiliation", "Affiliation", ("faction", "allegiance", "organization", "group", "employer", "team", "affiliations"),
          hint="an organization, faction, or employer the character belongs to"),
    Field("occupation", "Occupation", ("job", "profession", "title_of_office", "office", "role", "position", "trade", "vocation",
                                       "career", "occupations"),
          hint="their job, profession, office, or trade"),
    Field("residence", "Residence", ("home", "lives_in", "address", "abode", "dwelling", "lodgings", "domicile", "residences"),
          hint="where they live, naming the place as the book does"),
)}


CHARACTER_LISTS = {f.key: f for f in (
    Field("appearance", "Appearance", ("looks", "physical_description", "description")),
    Field("personality_evidence", "Personality", ("personality", "traits", "personality_traits")),
    Field("trivia", "Trivia", ("quirks", "habits")),
)}


ENTITY_FIELDS = {f.key: f for f in (
    Field("aliases", "Also known as", ("alias", "nicknames", "other_names", "codename", "code_name")),
)}


PROFILE_FIELDS = {k: f.label for k, f in CHARACTER_FIELDS.items()}


PROFILE_LISTS = {k: f.label for k, f in CHARACTER_LISTS.items()}


SECTIONS = {"facts": "Facts", "relations": "Relations", "erased": "In erased timelines"}


RELATION_TYPES = ("sister of", "member of", "mentor of", "enemy of", "located in")


AFFILIATION_RELATIONS = ("member of", "leader of", "founder of", "employed by", "works for", "part of")


def field_key(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def base_field(name):
    key = field_key(name)
    for f in (*CHARACTER_FIELDS.values(), *CHARACTER_LISTS.values(), *ENTITY_FIELDS.values()):
        if key in (f.key, field_key(f.label), *f.aliases):
            return f
    return None


LISTED_VALUES = re.compile(r"\bone of:?\s+((?:[\w'-]+(?: [\w'-]+)?,\s+)*[\w'-]+(?: [\w'-]+)?,?\s+or\s+[\w'-]+(?: [\w'-]+)?)", re.I)


def listed_values(description):
    m = LISTED_VALUES.search(description)
    if not m:
        return []
    return [v.strip() for v in re.split(r",\s*(?:or\s+)?|\s+or\s+", m.group(1)) if v.strip()]


def extra_field(raw):
    if isinstance(raw, dict):
        description = str(raw.get("description") or "").strip()
        values = [str(v).strip() for v in raw.get("values") or [] if str(v or "").strip()]
        return description, values or listed_values(description)
    description = str(raw or "").strip()
    return description, listed_values(description)


def overlapping(a, spec_a, b, spec_b):
    words_a, words_b = set(field_key(a).split("_")), set(field_key(b).split("_"))
    (desc_a, values_a), (desc_b, values_b) = extra_field(spec_a), extra_field(spec_b)
    named = any(re.search(rf"(?<!\w){re.escape(v)}(?!\w)", desc, re.I) for v, desc in
                [(v, desc_b) for v in values_a] + [(v, desc_a) for v in values_b])
    return words_a <= words_b or words_b <= words_a or bool({v.lower() for v in values_a} & {v.lower() for v in values_b}) or named


def distinct_fields(specs):
    kept = {}
    for key, spec in specs.items():
        first = next((k for k in kept if overlapping(k, kept[k], key, spec)), None)
        if first is None:
            kept[key] = spec
        elif not extra_field(kept[first])[1] and extra_field(spec)[1]:
            kept[first] = {"description": extra_field(kept[first])[0], "values": extra_field(spec)[1]}
    return kept


def overlapping_pairs(specs):
    keys = list(specs)
    return [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:] if overlapping(a, specs[a], b, specs[b])]


def book_additions(raw):
    power_types = book_types(raw.get("power_types"))
    extra, values = {}, {}
    for key, spec in distinct_fields(raw.get("extra_fields") or {}).items():
        if base_field(key) is None:
            extra[key], values[key] = extra_field(spec)
    return power_types, extra, values


def class_names(book, key):
    return tuple(book.get("field_values", {}).get(key) or ())
