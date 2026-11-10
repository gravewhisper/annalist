import html
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .boundaries import detect_volumes
from .files import read_json, write_atomic, write_json


OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}


CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}


BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "blockquote", "tr", "section", "article", "hr"}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = []
        self.current = []
        self.title = ""
        self.in_title = False
        self.skip_depth = 0

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(self.current)).strip()
        if text:
            self.paragraphs.append(text)
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip_depth += 1
        elif tag == "title":
            self.in_title = True
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip_depth = max(0, self.skip_depth - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip_depth:
            self.current.append(data)


def html_to_text(markup):
    parser = TextExtractor()
    body = re.search(r"<body[^>]*>(.*)</body>", markup, re.S | re.I)
    head_title = re.search(r"<title[^>]*>(.*?)</title>", markup, re.S | re.I)
    parser.feed(body.group(1) if body else markup)
    parser.close()
    parser.flush()
    title = html.unescape(re.sub(r"\s+", " ", head_title.group(1))).strip() if head_title else ""
    return title, parser.paragraphs


DC_NS = {"dc": "http://purl.org/dc/elements/1.1/"}


NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}


XHTML_NS = "{http://www.w3.org/1999/xhtml}"


@dataclass(frozen=True)
class TocEntry:
    label: str
    href: str
    children: tuple


@dataclass(frozen=True)
class Package:
    title: str
    spine: tuple
    toc: tuple


def toc_href(base, href):
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href.split("#")[0])) if href else ""


def ncx_entries(node, base):
    out = []
    for point in node.findall("ncx:navPoint", NCX_NS):
        label = point.find("ncx:navLabel/ncx:text", NCX_NS)
        content = point.find("ncx:content", NCX_NS)
        out.append(TocEntry(re.sub(r"\s+", " ", label.text or "").strip() if label is not None else "",
                            toc_href(base, content.get("src") if content is not None else ""), ncx_entries(point, base)))
    return tuple(out)


def nav_entries(ol, base):
    out = []
    for li in ol.findall(f"{XHTML_NS}li"):
        link = li.find(f"{XHTML_NS}a")
        if link is None:
            link = li.find(f"{XHTML_NS}span")
        child = li.find(f"{XHTML_NS}ol")
        out.append(TocEntry(re.sub(r"\s+", " ", "".join(link.itertext())).strip() if link is not None else "",
                            toc_href(base, link.get("href") if link is not None else ""),
                            nav_entries(child, base) if child is not None else ()))
    return tuple(out)


def read_toc(zf, opf_dir, manifest):
    for item in manifest.values():
        if "nav" in (item.get("properties") or "").split():
            path = posixpath.join(opf_dir, item.get("href"))
            root = ET.fromstring(zf.read(path))
            for nav in root.iter(f"{XHTML_NS}nav"):
                kind = nav.get("{http://www.idpf.org/2007/ops}type") or "toc"
                ol = nav.find(f"{XHTML_NS}ol")
                if kind == "toc" and ol is not None:
                    return nav_entries(ol, path)
    for item in manifest.values():
        if item.get("media-type") == "application/x-dtbncx+xml":
            path = posixpath.join(opf_dir, item.get("href"))
            nav_map = ET.fromstring(zf.read(path)).find("ncx:navMap", NCX_NS)
            return ncx_entries(nav_map, path) if nav_map is not None else ()
    return ()


def read_package(zf):
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", CONTAINER_NS).get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = ET.fromstring(zf.read(opf_path))
    manifest = {item.get("id"): item for item in opf.find("opf:manifest", OPF_NS)}
    spine = []
    for itemref in opf.find("opf:spine", OPF_NS):
        if itemref.get("linear") == "no":
            continue
        item = manifest[itemref.get("idref")]
        if "nav" in (item.get("properties") or "").split():
            continue
        spine.append(posixpath.join(opf_dir, item.get("href")))
    title = opf.find("opf:metadata/dc:title", {**OPF_NS, **DC_NS})
    return Package(title=(title.text or "").strip() if title is not None else "", spine=tuple(spine),
                   toc=read_toc(zf, opf_dir, manifest))


GUTENBERG_START = re.compile(r"^\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG", re.I)


GUTENBERG_END = re.compile(r"^(?:\*{3}\s*)?END OF (?:THE |THIS )?PROJECT GUTENBERG", re.I)


ENDING_TITLE = re.compile(r"\b(?:epilogue|afterword|the end|finale)\b", re.I)


ENDING_TEXT = re.compile(r"\b(?:THE END|The End|FINIS)\W*$")


def strip_gutenberg(docs):
    flat = [(i, p) for i, (_, _, paragraphs) in enumerate(docs) for p in paragraphs]
    start = next((k for k, (_, p) in enumerate(flat) if GUTENBERG_START.match(p)), -1)
    end = next((k for k, (_, p) in enumerate(flat) if k > start and GUTENBERG_END.match(p)), None)
    kept = {}
    for i, p in flat[start + 1:end]:
        kept.setdefault(i, []).append(p)
    return [(href, title, kept.get(i, [])) for i, (href, title, _) in enumerate(docs)], end is not None


def story_end(titles, last_text):
    title = next((t for t in reversed(titles[-2:]) if ENDING_TITLE.search(t)), None)
    if title:
        return f"closing chapter titled {title!r}"
    return "the last chapter ends with The End" if ENDING_TEXT.search(last_text.strip()) else ""


@dataclass(frozen=True)
class Extraction:
    title: str
    docs: list
    chapters: list
    texts: list
    source: dict
    toc: tuple
    skipped: list


def extract_book(epub, min_words=300):
    with zipfile.ZipFile(epub) as zf:
        package = read_package(zf)
        docs = [(href, *html_to_text(zf.read(href).decode("utf-8"))) for href in package.spine]
    docs, gutenberg_end = strip_gutenberg(docs)
    chapters, texts, skipped, last = [], [], [], []
    for href, title, paragraphs in docs:
        words = sum(len(p.split()) for p in paragraphs)
        if words < min_words:
            skipped.append((href, words))
            continue
        index = len(chapters) + 1
        if not title:
            title = paragraphs[0][:80]
        texts.append("\n\n".join(paragraphs) + "\n")
        chapters.append({"index": index, "title": title, "words": words, "href": href})
        last = paragraphs
    ending = "the Project Gutenberg end marker" if gutenberg_end else story_end(
        [c["title"] for c in chapters], "\n\n".join(last))
    return Extraction(title=package.title or Path(epub).stem, docs=docs, chapters=chapters, texts=texts,
                      source={"complete": bool(ending), "complete_evidence": ending}, toc=package.toc, skipped=skipped)


def chapter_shape(chapters):
    return [(c["index"], c["title"], c["words"]) for c in chapters]


def cmd_extract(args):
    workdir = Path(args.workdir)
    book = extract_book(args.epub, args.min_words)
    for href, words in book.skipped:
        print(f"skip {href} ({words} words)")
    previous = read_json(workdir / "chapters.json", None)
    if previous is not None and chapter_shape(previous) != chapter_shape(book.chapters) and any((workdir / "state").glob("*.json")):
        sys.exit(f"{args.epub} extracts to different chapters than {workdir / 'chapters.json'}, which the read state was built "
                 "from; use a new workdir for this epub")
    for chapter, text in zip(book.chapters, book.texts):
        write_atomic(workdir / "chapters" / f"{chapter['index']:04d}.txt", text)
    write_json(workdir / "chapters.json", book.chapters)
    write_json(workdir / "source.json", book.source)
    volumes = detect_volumes(book, getattr(args, "volumes", None))
    write_json(workdir / "volumes.json", volumes)
    print(f"extracted {len(book.chapters)} chapters, {sum(c['words'] for c in book.chapters)} words; "
          f"{len(volumes['volumes'])} volume{'s' if len(volumes['volumes']) != 1 else ''} ({volumes['source']})")
