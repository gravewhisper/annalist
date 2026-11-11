import html
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_mini import chapter_page, CONTAINER, locate, smart_quotes, xhtml

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "ladder-src"
EPUB = ROOT / "ladder.epub"
EXTRACTIONS = ROOT / "ladder-extractions.json"
TITLE = "The Ash Gate"
BOOK_ID = "urn:uuid:9b1f7d52-3c4a-4e8b-b6d2-71a0c5e8f310"


def read_chapters(src=SRC):
    chapters = {}
    for path in sorted(src.glob("[0-9][0-9].txt")):
        title, body = path.read_text().split("\n", 1)
        paragraphs = [smart_quotes(re.sub(r"\s+", " ", p).strip()) for p in body.split("\n\n") if p.strip()]
        chapters[int(path.stem)] = {"title": title.strip(), "paragraphs": paragraphs}
    return chapters


def href(n):
    return f"text/chapter-{n:02d}.xhtml"


def nav_page(chapters):
    items = "\n".join(f'<li><a href="{href(n)}">Chapter {n}. {html.escape(c["title"])}</a></li>' for n, c in chapters.items())
    return xhtml("Contents", f'<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n{items}\n</ol>\n</nav>')


def opf(chapters, title=TITLE, book_id=BOOK_ID):
    items = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
    items += [f'<item id="ch{n}" href="{href(n)}" media-type="application/xhtml+xml"/>' for n in chapters]
    spine = [f'<itemref idref="ch{n}"/>' for n in chapters]
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'<dc:identifier id="bookid">{book_id}</dc:identifier>\n<dc:title>{title}</dc:title>\n'
            '<dc:creator>Annalist test fixture</dc:creator>\n<dc:language>en</dc:language>\n'
            '<meta property="dcterms:modified">2026-11-08T00:00:00Z</meta>\n</metadata>\n'
            '<manifest>\n' + "\n".join(items) + '\n</manifest>\n<spine>\n' + "\n".join(spine) + '\n</spine>\n</package>\n')


def write_epub(chapters, epub=EPUB, title=TITLE, book_id=BOOK_ID):
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf(chapters, title, book_id), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", nav_page(chapters), compress_type=zipfile.ZIP_DEFLATED)
        for n, chapter in chapters.items():
            z.writestr(f"OEBPS/{href(n)}", chapter_page(n, chapter), compress_type=zipfile.ZIP_DEFLATED)


def build_extractions(chapters, src=SRC, out=EXTRACTIONS):
    authored = json.loads((src / "extractions.json").read_text())
    for key, ext in authored.items():
        n = int(key)
        for kind in ("facts", "relations"):
            for i, item in enumerate(ext[kind], 1):
                item["quotes"] = [locate(q, chapters[n]["paragraphs"], f"ch{n} {kind}[{i}]") for q in item["quotes"]]
    out.write_text(json.dumps(authored, ensure_ascii=False, indent=2) + "\n")


def main():
    chapters = read_chapters()
    write_epub(chapters)
    build_extractions(chapters)
    print(f"wrote {EPUB.name} and {EXTRACTIONS.name} for {len(chapters)} chapters")


if __name__ == "__main__":
    main()
