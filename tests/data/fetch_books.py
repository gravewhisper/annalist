import sys
import urllib.request
from pathlib import Path

BOOKS = {
    "hound": 2852,
    "pride": 1342,
    "women": 514,
    "crime": 2554,
    "dracula": 345,
    "eyre": 1260,
    "cristo": 1184,
}
CACHE = Path(__file__).resolve().parent / "cache"


def fetch(name, force=False):
    target = CACHE / f"{name}.epub"
    if target.exists() and not force:
        print(f"{target} already present")
        return
    url = f"https://www.gutenberg.org/ebooks/{BOOKS[name]}.epub.noimages"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "annalist-tests"}), timeout=120) as resp:
        data = resp.read()
    if not data.startswith(b"PK"):
        sys.exit(f"{url} did not return an epub")
    CACHE.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes); check it with: python3 tests/data/check_gold.py tests/data/{name}-gold.json {target}")


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or list(BOOKS)
    for name in names:
        fetch(name, "--force" in sys.argv)
