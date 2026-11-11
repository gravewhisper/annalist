import html
import posixpath
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
}


def spine_documents(epub_path):
    z = zipfile.ZipFile(epub_path)
    container = ET.fromstring(z.read("META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", NS).get("full-path")
    opf = ET.fromstring(z.read(opf_path))
    base = posixpath.dirname(opf_path)
    manifest = {i.get("id"): i.get("href") for i in opf.find("opf:manifest", NS)}
    for ref in opf.find("opf:spine", NS):
        href = manifest[ref.get("idref")]
        path = posixpath.normpath(posixpath.join(base, href))
        yield path, z.read(path).decode("utf-8")


def toc_anchors(epub_path):
    """{spine path: [anchor, ...]} for every TOC entry (NCX or EPUB 3 nav) that points into a document by fragment."""
    z = zipfile.ZipFile(epub_path)
    container = ET.fromstring(z.read("META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", NS).get("full-path")
    opf = ET.fromstring(z.read(opf_path))
    base = posixpath.dirname(opf_path)
    anchors = {}
    for item in opf.find("opf:manifest", NS):
        if item.get("media-type") != "application/x-dtbncx+xml" and "nav" not in (item.get("properties") or "").split():
            continue
        toc = posixpath.normpath(posixpath.join(base, item.get("href")))
        root = ET.fromstring(z.read(toc))
        if item.get("media-type") == "application/x-dtbncx+xml":
            targets = [c.get("src") for c in root.iterfind(".//{*}navMap//{*}navPoint/{*}content")]
        else:
            tocs = [n for n in root.iter("{http://www.w3.org/1999/xhtml}nav")
                    if (n.get("{http://www.idpf.org/2007/ops}type") or "toc") == "toc"][:1]
            targets = [a.get("href") for n in tocs for a in n.iter("{http://www.w3.org/1999/xhtml}a")]
        for target in targets:
            path, _, anchor = (target or "").partition("#")
            if not anchor:
                continue
            path = posixpath.normpath(posixpath.join(posixpath.dirname(toc), path))
            if anchor not in anchors.setdefault(path, []):
                anchors[path].append(anchor)
    return anchors


HEADING_WORDS = 12


GUTENBERG_END = re.compile(r"^(?:\*{3}\s*)?END OF (?:THE |THIS )?PROJECT GUTENBERG", re.I | re.M)


def document_segments(markup, anchors):
    """[(None, text before the first TOC anchor), (anchor, text up to the next TOC anchor), ...] for one document."""
    starts = []
    for a in anchors:
        m = re.search(rf'\b(?:id|name)="{re.escape(a)}"', markup)
        if m:
            starts.append((markup.rfind("<", 0, m.start()), a))
    starts.sort()
    bounds = [(0, None)] + starts + [(len(markup), None)]
    return [(anchor, html_to_text(markup[begin:end])) for (begin, anchor), (end, _) in zip(bounds, bounds[1:])]


def toc_pieces(segments):
    """Cut the way Annalist's extract cuts a document: a segment of short headings alone (a caption, a part title)
    joins the piece after it, or the last piece at the end of the document."""
    pieces, pending = {}, ""
    for anchor, text in segments:
        if all(len(p.split()) <= HEADING_WORDS for p in text.split("\n\n")):
            pending += text + "\n\n"
        else:
            pieces[anchor], pending = pending + text, ""
    if pending and pieces:
        last = list(pieces)[-1]
        pieces[last] += "\n\n" + pending
    return pieces


def book_chapters(epub_path):
    """{href: text} for each spine document, and {href#anchor: text} for each chapter of a document that holds two or
    more TOC chapters. The text such a document holds before its first chapter ends the chapter before it. Nothing
    after the Gutenberg end line counts."""
    anchors = toc_anchors(epub_path)
    out, ended = {}, False
    for path, markup in spine_documents(epub_path):
        segments = []
        for anchor, text in document_segments(markup, anchors.get(path, [])):
            m = None if ended else GUTENBERG_END.search(text)
            segments.append((anchor, "" if ended else text[:m.start()] if m else text))
            ended = ended or m is not None
        (_, prefix), pieces = segments[0], toc_pieces(segments[1:])
        if len(pieces) < 2:
            out[path] = "\n\n".join(text for _, text in segments)
            continue
        before = next((k for k in reversed(out) if out[k].strip()), None)
        if before:
            out[before] += "\n\n" + prefix
        else:
            first = next(iter(pieces))
            pieces[first] = prefix + "\n\n" + pieces[first]
        out.update((f"{path}#{anchor}", text) for anchor, text in pieces.items())
    return out


def html_to_text(markup):
    markup = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|tr)>", "\n", markup)
    markup = re.sub(r"<[^>]+>", "", markup)
    text = html.unescape(markup)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


CHAR_MAP = {
    **dict.fromkeys("\u2018\u2019\u201a\u201b\u2032`", "'"),
    **dict.fromkeys("\u201c\u201d\u201e\u201f\u2033", '"'),
    **dict.fromkeys("\u2013\u2014\u2015\u2212", "-"),
    "\u2026": "...",
}


def normalize_with_map(text):
    out, index = [], []
    for i, ch in enumerate(text):
        piece = CHAR_MAP.get(ch) or unicodedata.normalize("NFKC", ch).lower()
        if piece.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(i)
            continue
        for c in piece:
            out.append(c)
            index.append(i)
    if out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def normalize(text):
    return normalize_with_map(text)[0].strip()


if __name__ == "__main__":
    for path, markup in spine_documents(sys.argv[1]):
        text = html_to_text(markup)
        print(f"{path}\t{len(text)}\t{text[:120]!r}")
