import difflib
import functools
import re
from pathlib import Path


QUOTE_CHARS = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'",
                             "“": '"', "”": '"', "„": '"', "″": '"',
                             "–": "-", "—": "-", "―": "-", "−": "-", " ": " ", "*": ""})


def normalize(text):
    out, mapping = [], []
    prev_space = True
    for i, ch in enumerate(text):
        piece = "..." if ch == "…" else ch.translate(QUOTE_CHARS).lower()
        for c in piece:
            if c.isspace():
                if prev_space:
                    continue
                c = " "
                prev_space = True
            else:
                prev_space = False
            out.append(c)
            mapping.append(i)
    while out and out[-1] == " ":
        out.pop()
        mapping.pop()
    return "".join(out), mapping


normalized_chapter = functools.lru_cache(maxsize=512)(normalize)


def best_window(haystack, needle):
    n = len(needle)
    if not n or not haystack:
        return 0.0, 0, 0
    if n >= len(haystack):
        return difflib.SequenceMatcher(None, needle, haystack, autojunk=False).ratio(), 0, len(haystack)
    step = max(1, n // 6)

    def score(i):
        m = difflib.SequenceMatcher(None, needle, haystack[i:i + n], autojunk=False)
        return m.ratio() if m.quick_ratio() > 0.6 else 0.0

    best_i = max(range(0, len(haystack) - n + 1, step), key=score)
    lo, hi = max(0, best_i - step), min(len(haystack) - n, best_i + step)
    best_i = max(range(lo, hi + 1), key=score)
    return score(best_i), best_i, best_i + n


def locate_quote(text, quote, threshold=0.9):
    norm_text, mapping = normalized_chapter(text)
    norm_quote, _ = normalize(quote)
    norm_quote = norm_quote.strip(" \"'")
    if not norm_quote or not norm_text:
        return {"ok": False, "ratio": 0.0, "span": None}
    segments = [norm_quote] + [s.strip(" \"'") for s in norm_quote.split("...") if len(s.strip(" \"'")) >= 12]
    spans = []
    for k, seg in enumerate(segments):
        pos = norm_text.find(seg)
        if pos >= 0:
            match = (1.0, pos, pos + len(seg))
        else:
            match = best_window(norm_text, seg)
        if k == 0 and match[0] >= threshold:
            spans = [match]
            break
        if k > 0:
            spans.append(match)
    if not spans:
        ratio = best_window(norm_text, norm_quote)[0]
        return {"ok": False, "ratio": round(ratio, 3), "span": None}
    ratio = min(s[0] for s in spans)
    start, end = mapping[min(s[1] for s in spans)], mapping[max(s[2] for s in spans) - 1] + 1
    return {"ok": ratio >= threshold, "ratio": round(ratio, 3), "span": [start, end]}


@functools.lru_cache(maxsize=64)
def chapter_text(workdir, n):
    return (Path(workdir) / "chapters" / f"{n:04d}.txt").read_text(encoding="utf-8")


STOPWORDS = set("""about above after again against being below between could didn't doesn't during every
from have having here into itself might more most never other ought should some such than that their theirs
them then there these they this those through under until very what when where which while whom whose
will with would your yours does mean really actually still something someone anything nothing whether""".split())


def distinctive_words(text):
    return [w for w in re.findall(r"[a-z][a-z'-]{4,}", text.lower()) if w not in STOPWORDS]


def check_quote(workdir, chapter, quote):
    return locate_quote(chapter_text(workdir, chapter), quote)


def verified_quotes(workdir, chapter, quotes):
    ratios = [check_quote(workdir, chapter, q)["ratio"] for q in quotes]
    kept = [(q, r) for q, r in zip(quotes, ratios) if r >= 0.9]
    dropped = [q for q, r in zip(quotes, ratios) if r < 0.9]
    return {"quotes": [q for q, _ in kept], "quote_ok": bool(kept), "quote_ratios": [r for _, r in kept],
            **({"dropped_quotes": dropped} if dropped else {})}


def text_window(text, start, end, radius):
    lo, hi = max(0, start - radius), min(len(text), end + radius)
    while lo > 0 and not text[lo - 1].isspace():
        lo -= 1
    while hi < len(text) and not text[hi].isspace():
        hi += 1
    return text[lo:hi].strip()


SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*\s+")


def widen_to(text, start, end, pattern, limit=300):
    para_lo = text.rfind("\n", 0, start) + 1
    para_hi = text.find("\n", end)
    para_hi = len(text) if para_hi < 0 else para_hi
    before = list(pattern.finditer(text, max(para_lo, end - limit), start))
    if before:
        lo = max((m.end() for m in SENTENCE_END.finditer(text, para_lo, before[-1].start())), default=para_lo)
        if end - lo <= limit:
            return text[lo:end].strip()
    after = pattern.search(text, end, min(para_hi, start + limit))
    if after:
        stop = SENTENCE_END.search(text, after.end(), para_hi)
        hi = stop.end() if stop else para_hi
        if hi - start <= limit:
            return text[start:hi].strip()
    return None


def first_named_at(text, names):
    for flags in (0, re.I):
        hits = [m for m in (re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, flags) for name in names) if m]
        if hits:
            return min(hits, key=lambda m: m.start())
    return None


def sentence_of(text, start, end):
    para_lo = text.rfind("\n", 0, start) + 1
    para_hi = text.find("\n", end)
    para_hi = len(text) if para_hi < 0 else para_hi
    lo = max((m.end() for m in SENTENCE_END.finditer(text, para_lo, start)), default=para_lo)
    stop = SENTENCE_END.search(text, end, para_hi)
    return text[lo:stop.end() if stop else para_hi]


def mention_quote(text, names, limit=300):
    hit = first_named_at(text, names)
    if not hit:
        return ""
    start, end = hit.span()
    sentence = " ".join(sentence_of(text, start, end).split())
    if len(sentence) <= limit:
        return sentence
    return " ".join(text_window(text, start, end, (limit - (end - start)) // 2 - 20).split())[:limit]
