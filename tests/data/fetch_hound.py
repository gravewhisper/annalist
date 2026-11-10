import sys
import urllib.request
from pathlib import Path

URL = "https://www.gutenberg.org/ebooks/2852.epub.noimages"
TARGET = Path(__file__).resolve().parent / "cache" / "hound.epub"

if TARGET.exists() and "--force" not in sys.argv:
    print(f"{TARGET} already present")
    sys.exit(0)
TARGET.parent.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(urllib.request.Request(URL, headers={"user-agent": "annalist-tests"}), timeout=120) as resp:
    data = resp.read()
if not data.startswith(b"PK"):
    sys.exit(f"{URL} did not return an epub")
TARGET.write_bytes(data)
print(f"wrote {TARGET} ({len(data)} bytes); check it with: python3 tests/data/check_gold.py tests/data/hound-gold.json {TARGET}")
