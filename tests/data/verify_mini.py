import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_gold import chapter_texts, check
from epubtext import html_to_text, normalize, spine_documents

ROOT = Path(__file__).resolve().parent
EPUB = ROOT / "mini.epub"
GOLD = ROOT / "mini-gold.json"
EXTRACTIONS = sorted((ROOT / "mini-expected-extractions").glob("ch*.json"))
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}

failures = []


def expect(ok, message):
    if not ok:
        failures.append(message)


z = zipfile.ZipFile(EPUB)
infos = z.infolist()
expect(z.testzip() is None, "zip CRC check failed")
expect(infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED, "mimetype must be first and stored")
expect(z.read("mimetype") == b"application/epub+zip", "mimetype content")
opf = ET.fromstring(z.read("OEBPS/content.opf"))
manifest = {i.get("id"): i for i in opf.find("opf:manifest", OPF_NS)}
spine_hrefs = [manifest[r.get("idref")].get("href") for r in opf.find("opf:spine", OPF_NS)]
expect(any(i.get("properties") == "nav" for i in manifest.values()), "nav item missing")
for item in manifest.values():
    expect(f"OEBPS/{item.get('href')}" in z.namelist(), f"manifest href missing from zip: {item.get('href')}")
    ET.fromstring(z.read(f"OEBPS/{item.get('href')}"))
expect(spine_hrefs[1:] != sorted(spine_hrefs[1:]), "chapter spine order should differ from file name order")

gold = json.loads(GOLD.read_text())
expect([c["href"] for c in gold["chapters"]] == [f"OEBPS/{h}" for h in spine_hrefs[1:]], "gold chapters must follow spine order")
front_text = html_to_text(dict(spine_documents(EPUB))[f"OEBPS/{spine_hrefs[0]}"])
expect("Chapter" not in front_text, "front matter must not look like a chapter")

texts = chapter_texts(gold, EPUB)
gold_quotes, gold_failures = check(gold, texts)
failures.extend(gold_failures)

docs = dict(spine_documents(EPUB))
paragraphs = {}
for c in gold["chapters"]:
    raw = docs[c["href"]]
    paragraphs[c["index"]] = [normalize(html_to_text(p)) for p in raw.split("<p>")[1:]]

known_entities, open_questions = set(), set()
extraction_quotes = 0
for path in EXTRACTIONS:
    record = json.loads(path.read_text())
    n, ext = record["chapter"], record["extraction"]
    names = {e["name"] for e in ext["entities"]}
    for e in ext["entities"]:
        names.update(a["name"] for a in e["aliases"])
    known_entities |= names
    quoted = [(f"F{i}", q) for i, f in enumerate(ext["facts"], 1) for q in f["quotes"]]
    quoted += [(f"R{i}", q) for i, r in enumerate(ext["relations"], 1) for q in r["quotes"]]
    quoted += [(f"Q{i}", q["quote"]) for i, q in enumerate(ext["questions_raised"], 1)]
    quoted += [(r["id"], r["quote"]) for r in ext["questions_resolved"]]
    for label, q in quoted:
        extraction_quotes += 1
        expect(len(q) <= 300, f"ch{n} {label} quote over 300 chars")
        expect(any(normalize(q) in p for p in paragraphs[n]), f"ch{n} {label} quote not inside one paragraph: {q[:80]!r}")
        expect(q in html_to_text(docs[record["href"]]).replace("\n", " "), f"ch{n} {label} quote not exact")
    for f in ext["facts"]:
        expect(f["entity"] in known_entities, f"ch{n} fact entity unknown: {f['entity']}")
    for r in ext["relations"]:
        expect(r["source"] in known_entities and r["target"] in known_entities, f"ch{n} relation endpoint unknown: {r['source']} -> {r['target']}")
    for r in ext["questions_resolved"]:
        expect(r["id"] in open_questions, f"ch{n} resolves unknown or not-yet-open question {r['id']}")
        open_questions.discard(r["id"])
    open_questions |= {f"Q{n:04d}-{i:02d}" for i, _ in enumerate(ext["questions_raised"], 1)}
    items = len(ext["entities"]) + len(ext["facts"]) + len(ext["relations"]) + len(ext["questions_raised"])
    expect(len(record["timelines"]["labels"]) == items, f"ch{n} timeline labels do not cover every item")

print(f"epub entries={len(infos)} spine={spine_hrefs}")
print(f"gold quotes={len(gold_quotes)} extraction quotes={extraction_quotes} extraction files={len(EXTRACTIONS)}")
print(f"questions left open at end: {sorted(open_questions) or 'none'}")
for f in failures:
    print("FAIL", f)
print("OK" if not failures else f"{len(failures)} failures")
sys.exit(1 if failures else 0)
