import bisect
import math
import re

from .names import names_of
from .text import chapter_text, distinctive_words


def stem(word):
    word = re.sub(r"'s?$", "", word)
    if word.endswith("ies") and len(word) >= 6:
        return word[:-3] + "y"
    for suffix in ("ings", "ing", "edly", "ed", "es", "s", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def stems(text):
    return {stem(w) for w in distinctive_words(text)}


class Corpus:
    def __init__(self, workdir, kb, size=900):
        self.last = max(kb.synopses, default=0)
        self.windows, self.window_terms, self.postings = {}, {}, {}
        self.dense, self.facts = {}, {}
        claims = {}
        for f in kb.facts:
            claims.setdefault(f["chapter"], []).append(f["claim"])
            names = " ".join(names_of(kb.entities[f["entity"]])) if f["entity"] in kb.entities else f["entity"]
            self.facts.setdefault(f["chapter"], []).append((stems(f["claim"]), stems(names)))
        for n in range(1, self.last + 1):
            paras = chapter_text(str(workdir), n).split("\n\n")
            windows, i = [], 0
            while i < len(paras):
                j, text = i, ""
                while j < len(paras) and len(text) < size:
                    text += ("\n" if text else "") + paras[j].strip()
                    j += 1
                windows.append(text)
                i = j - 1 if j - i > 1 else j
            self.windows[n] = windows
            self.window_terms[n] = [stems(w) for w in windows]
            self.dense[n] = stems(kb.synopses.get(n, "") + " " + " ".join(claims.get(n, [])))
            for term in set().union(*self.window_terms[n]):
                self.postings.setdefault(term, []).append(n)

    def idf(self, term, upto=None):
        upto = self.last if upto is None else upto
        df = bisect.bisect_right(self.postings.get(term, []), upto)
        return math.log((upto + 1) / (df + 1))

    def best_windows(self, terms, weights, n, k):
        scored = [(match_score(terms & wt, weights), i) for i, wt in enumerate(self.window_terms[n])]
        return [(s, i) for s, i in sorted(scored, key=lambda x: (-x[0], x[1]))[:k] if s > 0]


def match_score(hits, weights):
    total = sum(weights[t] for t in hits)
    return total if sum(weights[t] >= 0.5 for t in hits) > 1 else total / 2


def question_terms(q):
    return stems(q["question"] + " " + q.get("quote", ""))


def chapter_scores(corpus, q, terms, weights):
    scores = {}
    for n in range(q["chapter"] + 1, corpus.last + 1):
        best = corpus.best_windows(terms, weights, n, 1)
        if best:
            scores[n] = (best[0][0] + match_score(terms & corpus.dense[n], weights)) * (1 + 2 / (n - q["chapter"]))
    return scores
