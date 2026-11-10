import re

from .backends import ConfigError


ORDINALS = ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
            "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth").split()


CARDINALS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
             "eighteen nineteen twenty").split()


ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


KINDS = "volume|book|part"


HEADING = re.compile(rf"^({KINDS})\s+([\w]+)\b\s*[:.,\-–—]?\s*(.*)$", re.I)


END_MARKER = re.compile(rf"^\(?\s*end of (?:the )?(?:(\w+)\s+)?({KINDS})(?:\s+(\w+))?\s*[:,.\-–—]*\s*(.*?)\s*\)?\W*$", re.I)


CHAPTER_NUMBER = re.compile(r"^(?:chapter|ch\.?)?\s*(\d+)\b", re.I)


def number(token):
    token = (token or "").lower()
    if token.isdigit():
        return int(token)
    if token in CARDINALS:
        return CARDINALS.index(token) + 1
    if token in ORDINALS:
        return ORDINALS.index(token) + 1
    if token and all(ch in ROMAN for ch in token):
        values = [ROMAN[ch] for ch in token]
        return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))
    return None


def volume_name(kind, n, subtitle=""):
    subtitle = re.sub(r"^chapter\b.*$", "", subtitle.strip(), flags=re.I).strip(" :.-–—")
    return f"{kind.capitalize()} {n}" + (f": {subtitle}" if subtitle else "")


def spans(starts, last):
    starts = sorted({s: name for s, name in starts if 1 <= s <= last}.items())
    if not starts:
        return []
    starts[0] = (1, starts[0][1])
    ends = [s - 1 for s, _ in starts[1:]] + [last]
    return [{"name": name, "from": s, "to": e} for (s, name), e in zip(starts, ends)]


def plausible(volumes, last):
    return len(volumes) >= 2 and len(volumes) * 2 <= last


def doc_chapters(book):
    by_href = {c["href"]: c["index"] for c in book.chapters}
    following, out = len(book.chapters) + 1, []
    for href, title, paragraphs in reversed(book.docs):
        following = by_href.get(href, following)
        out.append((following, href in by_href, title, paragraphs))
    return out[::-1]


def toc_chapters(entry, by_href):
    found = {by_href[entry.href]} if entry.href in by_href else set()
    for child in entry.children:
        found |= toc_chapters(child, by_href)
    return found


def from_toc(book):
    by_href = {c["href"]: c["index"] for c in book.chapters}
    level = book.toc
    while True:
        groups = [(e, toc_chapters(e, by_href)) for e in level if e.children]
        groups = [(e, found) for e, found in groups if found]
        if len(groups) != 1:
            break
        level = groups[0][0].children
    return spans([(min(found), e.label or f"Volume {k}") for k, (e, found) in enumerate(groups, 1)], len(book.chapters))


def from_headings(book):
    starts, current = [], None
    for chapter, is_chapter, title, paragraphs in doc_chapters(book):
        lines = [title] + [p for p in paragraphs[:2] if len(p.split()) <= 12]
        found = [(m, number(m.group(2))) for line in lines if (m := HEADING.match(line.strip())) and number(m.group(2))]
        if not found or found[0][1] == current:
            continue
        n = found[0][1]
        if current is not None and n < current:
            return []
        m = max((m for m, k in found if k == n), key=lambda m: len(m.group(3)))
        current = n
        starts.append((chapter, volume_name(m.group(1), n, m.group(3))))
    first = starts and HEADING.match(starts[0][1])
    if first and starts[0][0] > 1 and number(first.group(2)) > 1:
        starts.insert(0, (1, volume_name(first.group(1), number(first.group(2)) - 1)))
    return spans(starts, len(book.chapters))


def from_end_markers(book):
    starts, last_kind, last_n = [(1, None)], "volume", 0
    for chapter, text in zip(book.chapters, book.texts):
        for paragraph in text.strip().split("\n\n")[-3:]:
            m = END_MARKER.match(paragraph.strip())
            n = m and (number(m.group(1)) or number(m.group(3)))
            if n:
                starts[-1] = (starts[-1][0], volume_name(m.group(2), n, m.group(4)))
                starts.append((chapter["index"] + 1, None))
                last_kind, last_n = m.group(2), n
                break
    if len(starts) == 1:
        return []
    starts[-1] = (starts[-1][0], f"After {volume_name(last_kind, last_n)}")
    return spans(starts, len(book.chapters))


def from_numbering(book):
    numbers = [number(m.group(1)) if (m := CHAPTER_NUMBER.match(c["title"].strip())) else None for c in book.chapters]
    starts = [(1, "Book 1")]
    for i, n in enumerate(numbers):
        if n == 1 and i and (numbers[i - 1] or 0) > 1 and (i + 1 == len(numbers) or numbers[i + 1] == 2):
            starts.append((i + 1, f"Book {len(starts) + 1}"))
    return spans(starts, len(book.chapters)) if len(starts) > 1 else []


DETECTORS = (("toc", from_toc), ("headings", from_headings), ("end-markers", from_end_markers), ("numbering", from_numbering))


def parse_volumes(spec, last):
    volumes = []
    for k, part in enumerate(p.strip() for p in spec.split(",") if p.strip()):
        name, _, span = part.rpartition("=")
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", span.strip())
        if not m:
            raise ConfigError(f"--volumes part {part!r} is not FROM-TO or NAME=FROM-TO")
        lo, hi = int(m.group(1)), int(m.group(2))
        if not (1 <= lo <= hi <= last) or (volumes and lo <= volumes[-1]["to"]):
            raise ConfigError(f"--volumes part {part!r} must be ascending, not overlap, and lie within chapters 1 to {last}")
        volumes.append({"name": name.strip() or f"Volume {k + 1}", "from": lo, "to": hi})
    if not volumes:
        raise ConfigError("--volumes names no chapter ranges")
    return volumes


def detect_volumes(book, override=None):
    last = len(book.chapters)
    if override:
        return {"source": "override", "volumes": parse_volumes(override, last)}
    for source, detector in DETECTORS:
        volumes = detector(book)
        if plausible(volumes, last):
            return {"source": source, "volumes": volumes}
    return {"source": "whole-book", "volumes": [{"name": book.title, "from": 1, "to": last}] if last else []}
