import re
from collections import Counter
from functools import cache

from .text import QUOTE_CHARS


def name_key(name):
    return re.sub(r"\s+", " ", str(name).translate(QUOTE_CHARS)).strip().lower()


def written_summary(entity):
    text = str(entity.get("summary") or "").strip()
    return "" if text.lower() == "placeholder" else text


LEADING_WORDS = {"the", "a", "an", "his", "her", "their", "its", "this", "that", "our", "my"}


ROLE_WORDS = {"captain", "inspector", "officer", "detective", "sergeant", "lieutenant", "colonel", "general",
              "doctor", "dr.", "professor", "mr.", "mrs.", "miss", "ms.", "sir", "madam", "lord", "lady", "master",
              "mister", "boss", "chief", "landlord", "landlady", "man", "woman", "gentleman", "boy", "girl", "old",
              "young", "mysterious", "stranger", "priest", "bishop", "king", "queen", "prince", "princess", "emperor",
              "father", "mother", "brother", "sister", "teacher", "mentor", "leader", "member", "servant", "maid",
              "butler", "guard", "shopkeeper", "owner", "figure", "person", "someone", "voice", "child", "elder"}


UNTYPED = ("", "uncategorized")


def content_words(alias):
    words = alias.split()
    while words and words[0].lower() in LEADING_WORDS:
        words = words[1:]
    return words


def parse_aliases(raw):
    aliases = []
    for a in raw or []:
        name, unique = (a.get("name"), a.get("unique") is True) if isinstance(a, dict) else (a, False)
        words = content_words(str(name or "").strip())
        if not words or all(w.lower() in ROLE_WORDS for w in words) or function_word_name(name):
            continue
        if unique or not all(w.lower() in ROLE_WORDS or not w[0].isupper() for w in words):
            aliases.append(str(name).strip())
    return aliases


def display_names(entities):
    written = {k: e.get("written", e["name"]) for k, e in entities.items()}
    shared = Counter(map(name_key, written.values()))
    return {k: f"{w} ({entities[k]['type']})" if shared[name_key(w)] > 1 and not f" {name_key(w)}".endswith(f" {entities[k]['type']}") else w
            for k, w in written.items()}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


FUNCTION_WORDS = {"of", "in", "the", "and", "a", "an", "with", "on", "at", "from", "to", "de", "von", "van"}


PRONOUNS = {"i", "me", "my", "mine", "myself", "you", "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself",
            "she", "her", "hers", "herself", "it", "its", "itself", "we", "us", "our", "ours", "ourselves", "they", "them",
            "their", "theirs", "themselves", "thou", "thee", "thy", "thine", "who", "whom", "whose", "what", "which",
            "this", "that", "these", "those", "someone", "something", "somebody", "anyone", "anything", "anybody",
            "everyone", "everything", "everybody", "nobody", "nothing", "none", "all", "each", "every", "some", "any",
            "here", "there", "now", "then", "yes", "no", "not"}


def function_word_name(name):
    words = [w.strip(".,;:!?\"'()").lower() for w in str(name).translate(QUOTE_CHARS).split()]
    return all(not w or w in PRONOUNS or w in FUNCTION_WORDS or w in LEADING_WORDS for w in words)


def names_of(entity):
    return [entity["name"]] + entity["aliases"]


def name_tokens(name):
    words = [re.sub(r"'s$", "", w.lower().strip(".,\"'")) for w in content_words(name.translate(QUOTE_CHARS))]
    return {w for w in words if len(w) >= 3 and w not in ROLE_WORDS and w not in FUNCTION_WORDS}


def singular(word):
    if re.search(r"(?:ss|sh|ch|x|z)es$", word):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def name_stems(name):
    return {singular(w) for w in name_tokens(name)}


def is_stub(entity):
    return any(w[0].islower() and w.lower() not in FUNCTION_WORDS for w in content_words(entity["name"]))


def edits(x, y):
    """Letters to insert, delete, change, or swap with a neighbour to turn x into y."""
    before, row = None, list(range(len(y) + 1))
    for i, a in enumerate(x, 1):
        now = [i]
        for j, b in enumerate(y, 1):
            cost = min(row[j] + 1, now[j - 1] + 1, row[j - 1] + (a != b))
            if before and i > 1 and j > 1 and a == y[j - 2] and x[i - 2] == b:
                cost = min(cost, before[j - 2] + 1)
            now.append(cost)
        before, row = row, now
    return row[-1]


def near_spelling(x, y):
    """Two spellings of one name: one letter apart, the same letters reordered, or, for words of six letters
    or more that start alike, two letters apart (Caitlyn and Catelyn)."""
    if sorted(x) == sorted(y):
        return True
    if abs(len(x) - len(y)) > 2:
        return False
    limit = 2 if min(len(x), len(y)) >= 6 and x[0] == y[0] else 1
    return edits(x, y) <= limit


@cache
def compiled_names(names):
    forms = (r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", n.strip()))) for n in sorted(names, key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + "|".join(forms) + r")(?!\w)", re.I)


def name_pattern(names):
    return compiled_names(tuple(names))


def plain_words(name):
    return [w.translate(QUOTE_CHARS).strip(".,\"'") for w in name.split()]


def possessive(word):
    return word.endswith("'s")


def character_words(kb):
    return Counter(w for e in kb.entities.values() if e["type"] == "character"
                   for w in {w for n in names_of(e) for w in plain_words(n) if not possessive(w)})


def short_names(kb, name, words=None):
    words = character_words(kb) if words is None else words
    own = [plain_words(n) for n in names_of(kb.entities[name])]
    mine = {w for names in own if not any(map(possessive, names)) for w in names if w[:1].isupper()}
    self_count = kb.entities[name]["type"] == "character"
    return [w for w in sorted(w for w in mine if words[w] <= self_count) if len(w) >= 3 and w.lower() not in ROLE_WORDS and w.lower() not in LEADING_WORDS]


def word_spans(text):
    for m in re.finditer(r"[\w'-]+", str(text).translate(QUOTE_CHARS).lower()):
        word = re.sub(r"'s$", "", m.group(0).strip("'-"))
        if word:
            yield m.start(), word


def name_words(text):
    return [w for _, w in word_spans(text)]


class NameIndex:
    def __init__(self, names_by_entity, longest=6):
        self.keys = {}
        for entity, names in names_by_entity.items():
            for n in names:
                words = tuple(name_words(n))
                if 0 < len(words) <= longest:
                    self.keys.setdefault(words, set()).add(entity)
        self.longest = max(map(len, self.keys), default=0)

    def mentions(self, text):
        spans = list(word_spans(text))
        words = [w for _, w in spans]
        return [(spans[i][0], entity) for i in range(len(words)) for k in range(1, min(self.longest, len(words) - i) + 1)
                for entity in sorted(self.keys.get(tuple(words[i:i + k]), ()))]

    def find(self, text):
        return {entity for _, entity in self.mentions(text)}
