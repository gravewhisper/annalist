"""Genre benchmark: public-domain novels with gold keys for their opening chapters.

    python3 tests/data/bench.py fetch            download the epubs into tests/data/cache
    python3 tests/data/bench.py build [names]    build each book's scoped chapters into runs/bench-<name> (costs money)
    python3 tests/data/bench.py score [names]    score each built run against its gold and print a table

Books that are not public domain stay out of the repo: runs/bench-private.json maps each name to
{"epub": path, "to": last chapter, "stresses": text}, and its gold file is runs/bench-private/<name>-gold.json.
A book whose epub is missing is skipped.
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent
ROOT = DATA.parent.parent
CACHE = DATA / "cache"
BUDGET = 8

BOOKS = {
    "hound": {"gutenberg": 2852, "to": 15, "stresses": "mystery, false names, a wife passed off as a sister"},
    "women": {"gutenberg": 514, "to": 12, "stresses": "four sisters who share 'Miss March', nicknames, club pen names"},
    "crime": {"gutenberg": 2554, "to": 10, "stresses": "Russian name forms, shared patronymics, murders"},
    "dracula": {"gutenberg": 345, "to": 10, "stresses": "journals and letters by several narrators"},
    "eyre": {"gutenberg": 1260, "to": 13, "stresses": "first-person narrator, a stranger named later"},
    "cristo": {"gutenberg": 1184, "to": 16, "stresses": "prisoner numbers as names, a father under another surname"},
    "pride": {"gutenberg": 1342, "to": 12, "stresses": "sisters who share 'Miss Bennet', titles, marriages"},
}


PRIVATE = ROOT / "runs" / "bench-private.json"
if PRIVATE.exists():
    BOOKS.update({n: {**b, "private": True} for n, b in json.loads(PRIVATE.read_text(encoding="utf-8")).items()})


def epub(name):
    return Path(BOOKS[name]["epub"]) if BOOKS[name].get("private") else CACHE / f"{name}.epub"


def gold(name):
    return ROOT / "runs" / "bench-private" / f"{name}-gold.json" if BOOKS[name].get("private") else DATA / f"{name}-gold.json"


def workdir(name):
    return ROOT / "runs" / f"bench-{name}"


def fetch(name):
    if epub(name).exists():
        return print(f"{epub(name)} already present")
    url = f"https://www.gutenberg.org/ebooks/{BOOKS[name]['gutenberg']}.epub.noimages"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "annalist-tests"}), timeout=120) as resp:
        data = resp.read()
    if not data.startswith(b"PK"):
        sys.exit(f"{url} did not return an epub")
    CACHE.mkdir(parents=True, exist_ok=True)
    epub(name).write_bytes(data)
    print(f"wrote {epub(name)} ({len(data)} bytes)")


def build(name):
    subprocess.run([sys.executable, "-m", "annalist", "build", str(epub(name)), str(workdir(name)),
                    "--to", str(BOOKS[name]["to"]), "--yes", "--budget", str(BUDGET)], cwd=ROOT, check=True)


def score(name):
    out = subprocess.run([sys.executable, "-m", "annalist", "eval", str(workdir(name)), str(gold(name))],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        return None
    return json.loads((workdir(name) / "eval.json").read_text(encoding="utf-8"))["totals"]


def table(names):
    rows = {n: score(n) for n in names}
    sections = next((list(t) for t in rows.values() if t), [])
    print("| book | " + " | ".join(sections) + " |")
    print("|---|" + "---:|" * len(sections))
    for n, totals in rows.items():
        cells = [f"{totals[s]['score'] * 100:.0f}%" if totals and totals[s]["score"] is not None else "n/a" for s in sections]
        print(f"| {n} | " + " | ".join(cells) + " |" if totals else f"| {n} | not built |")


def main():
    command, names = (sys.argv[1] if len(sys.argv) > 1 else "score"), sys.argv[2:] or list(BOOKS)
    if command == "fetch":
        for n in names:
            if not BOOKS[n].get("private"):
                fetch(n)
    elif command == "build":
        for n in names:
            if epub(n).exists():
                build(n)
            else:
                print(f"skip {n}: {epub(n)} is missing")
    elif command == "score":
        table(names)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
