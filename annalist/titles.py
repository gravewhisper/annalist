import re

from .names import content_words, is_stub, name_stems, plain_words, ROLE_WORDS, singular

WORD = r"[A-Z][\w'’-]+"
POSSESSIVE = re.compile(r"['’]s\b")
LONGER = rf"(?:\s(?:of|and|for|de)\s(?:the\s)?{WORD}(?:\s{WORD})*)+"


def close_spelling(x, y):
    if x == y:
        return True
    if len(x) < 5 or len(y) < 5 or x[0] != y[0] or abs(len(x) - len(y)) > 2:
        return False
    row = list(range(len(y) + 1))
    for i, a in enumerate(x, 1):
        prev, row[0] = row[0], i
        for j, b in enumerate(y, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (a != b))
    return row[-1] <= 2


def spelling_variant(x, y):
    wx, wy = content_words(x.lower()), content_words(y.lower())
    return (len(wx) == len(wy) and list(map(singular, wx)) != list(map(singular, wy))
            and all(close_spelling(a, b) for a, b in zip(wx, wy)))


def fuller(x, than):
    proper = not POSSESSIVE.search(x) and (is_stub({"name": than}) or not is_stub({"name": x}))
    return proper and name_stems(x) > name_stems(than)


def longer_forms(name, own_texts):
    pattern = re.compile(r"(?<![\w])" + re.escape(name) + LONGER)
    return {m.group(0) for text in own_texts for m in pattern.finditer(text)}


def uses(forms, texts):
    pattern = re.compile(r"(?<![\w])(" + "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)) + r")(?![\w])")
    found = {f: [] for f in forms}
    for n in sorted(texts):
        if any(f in texts[n] for f in forms):
            for m in pattern.finditer(texts[n]):
                found[m.group(1)].append(n)
    return found


COMMON_SHARE = 10


def name_parts(name):
    return [t for w in plain_words(name) if not {w.lower(), f"{w.lower()}."} & ROLE_WORDS for t in re.findall(r"\w+", w)]


def personal_part(part, words):
    return words[part] > COMMON_SHARE * words[part.lower()]


def personal_name(name, words):
    return not is_stub({"name": name}) and not POSSESSIVE.search(name) and any(personal_part(p, words) for p in name_parts(name))


def extends_with_names(alias, name, words):
    added = [p for p in name_parts(alias) if p.lower() not in map(str.lower, name_parts(name))]
    return name_stems(alias) > name_stems(name) and bool(added) and all(personal_part(p, words) for p in added)


def revealed_name(name, aliases, words):
    personal = personal_name(name, words)
    found = [a for a in aliases if personal_name(a["name"], words) and (not personal or extends_with_names(a["name"], name, words))]
    return min(found, default=None, key=lambda a: (-len(name_stems(a["name"])), a["chapter"],
                                                   any(w.lower() in ROLE_WORDS for w in plain_words(a["name"]))))


def page_title(name, aliases, own_texts, texts, share=0.1):
    forms = {name, *aliases} | {x for f in [name, *aliases] for x in longer_forms(f, own_texts)}
    family = {f for f in forms if f == name or fuller(f, name) or spelling_variant(f, name)}
    seen = uses(family, texts)
    total = sum(len(v) for v in seen.values())
    regular = [f for f in family if len(set(seen[f])) >= 2 and len(seen[f]) >= share * total]
    title = max((f for f in regular if f == name or fuller(f, name)), key=lambda f: (len(name_stems(f)), len(seen[f])), default=name)
    title = max((f for f in regular if f == title or spelling_variant(f, title)), key=lambda f: len(seen[f]), default=title)
    first = {f: min(seen[f]) for f in family if seen[f]}
    return title, first
