import html
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from epubtext import normalize_with_map

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "mini-src"
EPUB = ROOT / "mini.epub"
EXTRACTIONS_DIR = ROOT / "mini-expected-extractions"
GOLD = ROOT / "mini-gold.json"
MAX_QUOTE = 300

CHAPTER_FILES = {1: "text/part-d.xhtml", 2: "text/part-a.xhtml", 3: "text/part-e.xhtml", 4: "text/part-b.xhtml", 5: "text/part-c.xhtml"}
FRONT = "text/title.xhtml"
NAV = "nav.xhtml"
BOOK_ID = "urn:uuid:4f6c2a0e-8d1b-4c5e-9a37-2b6e0c1d9f42"


def smart_quotes(text):
    out = []
    for i, ch in enumerate(text):
        if ch == '"':
            prev = text[i - 1] if i else " "
            out.append("“" if prev.isspace() or prev in "(—" else "”")
        elif ch == "'":
            out.append("’")
        else:
            out.append(ch)
    return "".join(out)


def read_chapters():
    chapters = {}
    for n in CHAPTER_FILES:
        title, body = (SRC / f"{n:02d}.txt").read_text().split("\n", 1)
        paragraphs = [smart_quotes(re.sub(r"\s+", " ", p).strip()) for p in body.split("\n\n") if p.strip()]
        chapters[n] = {"title": title.strip(), "paragraphs": paragraphs}
    return chapters


def xhtml(title, body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">\n'
            f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title></head>\n<body>\n{body}\n</body>\n</html>\n')


def chapter_page(n, chapter):
    paras = "\n".join(f"<p>{html.escape(p, quote=False)}</p>" for p in chapter["paragraphs"])
    return xhtml(chapter["title"], f'<section epub:type="chapter">\n<h1>Chapter {n}. {html.escape(chapter["title"])}</h1>\n{paras}\n</section>')


def front_page():
    return xhtml("The Salt Ledger", '<section epub:type="titlepage">\n<h1>The Salt Ledger</h1>\n'
                 '<p>A short novel in five chapters.</p>\n<p>Annalist test fixture. Not for distribution.</p>\n</section>')


def nav_page(chapters):
    items = "\n".join(f'<li><a href="{CHAPTER_FILES[n]}">Chapter {n}. {html.escape(c["title"])}</a></li>' for n, c in chapters.items())
    return xhtml("Contents", f'<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n<li><a href="{FRONT}">Title page</a></li>\n{items}\n</ol>\n</nav>')


def opf():
    manifest_order = [5, 2, 4, 1, 3]
    items = [f'<item id="nav" href="{NAV}" media-type="application/xhtml+xml" properties="nav"/>']
    items += [f'<item id="ch{n}" href="{CHAPTER_FILES[n]}" media-type="application/xhtml+xml"/>' for n in manifest_order]
    items.append(f'<item id="front" href="{FRONT}" media-type="application/xhtml+xml"/>')
    spine = ['<itemref idref="front"/>'] + [f'<itemref idref="ch{n}"/>' for n in CHAPTER_FILES]
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">\n'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'<dc:identifier id="bookid">{BOOK_ID}</dc:identifier>\n<dc:title>The Salt Ledger</dc:title>\n'
            '<dc:creator>Annalist test fixture</dc:creator>\n<dc:language>en</dc:language>\n'
            '<meta property="dcterms:modified">2026-11-07T00:00:00Z</meta>\n</metadata>\n'
            '<manifest>\n' + "\n".join(items) + '\n</manifest>\n<spine>\n' + "\n".join(spine) + '\n</spine>\n</package>\n')


CONTAINER = ('<?xml version="1.0" encoding="utf-8"?>\n'
             '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
             '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>\n'
             '</container>\n')


def write_epub(chapters):
    with zipfile.ZipFile(EPUB, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf(), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(f"OEBPS/{NAV}", nav_page(chapters), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(f"OEBPS/{FRONT}", front_page(), compress_type=zipfile.ZIP_DEFLATED)
        for n in sorted(CHAPTER_FILES, key=lambda n: CHAPTER_FILES[n]):
            z.writestr(f"OEBPS/{CHAPTER_FILES[n]}", chapter_page(n, chapters[n]), compress_type=zipfile.ZIP_DEFLATED)


def locate(quote, paragraphs, where):
    target = normalize_with_map(quote)[0].strip()
    for p in paragraphs:
        norm, index = normalize_with_map(p)
        at = norm.find(target)
        if at >= 0:
            return p[index[at]:index[at + len(target) - 1] + 1]
    raise SystemExit(f"quote not found in one paragraph ({where}): {quote!r}")


def canonical_quotes(node, chapters, where):
    if isinstance(node, dict):
        if set(node) == {"chapter", "text"}:
            return {"chapter": node["chapter"], "text": locate(node["text"], chapters[node["chapter"]]["paragraphs"], where)}
        return {k: canonical_quotes(v, chapters, f"{where}/{k}") for k, v in node.items()}
    if isinstance(node, list):
        return [canonical_quotes(v, chapters, f"{where}[{i}]") for i, v in enumerate(node)]
    return node


def timeline_labels(extraction, timeline_id):
    labels = {}
    for prefix, key in (("E", "entities"), ("F", "facts"), ("R", "relations"), ("Q", "questions_raised")):
        for i, _ in enumerate(extraction[key], 1):
            labels[f"{prefix}{i}"] = timeline_id
    return labels


def build_extractions(chapters):
    authored = json.loads((SRC / "extractions.json").read_text())
    EXTRACTIONS_DIR.mkdir(exist_ok=True)
    for key, spec in authored.items():
        n = int(key)
        paragraphs = chapters[n]["paragraphs"]
        ext = spec["extraction"]
        for kind in ("facts", "relations"):
            for i, item in enumerate(ext[kind], 1):
                item["quotes"] = [locate(q, paragraphs, f"ch{n} {kind}[{i}]") for q in item["quotes"]]
        for kind in ("questions_raised", "questions_resolved"):
            for i, item in enumerate(ext[kind], 1):
                item["quote"] = locate(item["quote"], paragraphs, f"ch{n} {kind}[{i}]")
        timelines = {"new": spec["timelines"]["new"], "erased": spec["timelines"]["erased"],
                     "labels": timeline_labels(ext, spec["timelines"]["default"])}
        out = {"chapter": n, "title": chapters[n]["title"], "href": f"OEBPS/{CHAPTER_FILES[n]}",
               "extraction": ext, "timelines": timelines}
        (EXTRACTIONS_DIR / f"ch{n:02d}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")


def build_gold(chapters):
    gold = json.loads((SRC / "gold.json").read_text())
    gold["chapters"] = [{"index": n, "title": c["title"], "href": f"OEBPS/{CHAPTER_FILES[n]}"} for n, c in chapters.items()]
    gold["non_chapter_spine_items"] = [{"href": f"OEBPS/{FRONT}", "kind": "title_page"}]
    gold = canonical_quotes(gold, chapters, "gold")
    ordered = {k: gold[k] for k in ("schema_version", "book", "chapters", "non_chapter_spine_items")}
    ordered.update({k: v for k, v in gold.items() if k not in ordered})
    GOLD.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")


def main():
    chapters = read_chapters()
    write_epub(chapters)
    build_extractions(chapters)
    build_gold(chapters)
    print(f"wrote {EPUB.name}, {GOLD.name}, {len(list(EXTRACTIONS_DIR.glob('ch*.json')))} extraction files")


if __name__ == "__main__":
    main()
