import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ladder import build_extractions, read_chapters, write_epub

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "cultivation-src"
EPUB = ROOT / "cultivation.epub"
EXTRACTIONS = ROOT / "cultivation-extractions.json"
TITLE = "The Reed Valley"
BOOK_ID = "urn:uuid:4e2a9c18-7b3d-4f60-a1c5-2d8e9f0b6a73"


def main():
    chapters = read_chapters(SRC)
    write_epub(chapters, EPUB, TITLE, BOOK_ID)
    build_extractions(chapters, SRC, EXTRACTIONS)
    print(f"wrote {EPUB.name} and {EXTRACTIONS.name} for {len(chapters)} chapters")


if __name__ == "__main__":
    main()
