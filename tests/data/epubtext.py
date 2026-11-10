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
