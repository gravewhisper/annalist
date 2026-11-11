import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ladder import build_extractions, read_chapters, write_epub

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "circles-src"
EPUB = ROOT / "circles.epub"
EXTRACTIONS = ROOT / "circles-extractions.json"
TITLE = "Salt and Gloam"
BOOK_ID = "urn:uuid:c3a81f5e-62d4-4b9a-9e07-5f1d2b8c4a96"


def main():
    chapters = read_chapters(SRC)
    write_epub(chapters, EPUB, TITLE, BOOK_ID)
    build_extractions(chapters, SRC, EXTRACTIONS)
    print(f"wrote {EPUB.name} and {EXTRACTIONS.name} for {len(chapters)} chapters")


if __name__ == "__main__":
    main()
