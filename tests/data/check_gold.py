import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from epubtext import html_to_text, normalize, spine_documents

LICENSE_MARKER = "*** END OF THE PROJECT GUTENBERG"


def chapter_texts(gold, epub_path):
    docs = dict(spine_documents(epub_path))
    texts = {}
    for ch in gold["chapters"]:
        text = html_to_text(docs[ch["href"]])
        texts[ch["index"]] = normalize(text.split(LICENSE_MARKER)[0])
    return texts


def walk_quotes(node, where):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "quote" and isinstance(value, dict):
                yield where, value
            elif key == "quotes":
                for q in value:
                    yield where, q
            else:
                yield from walk_quotes(value, where + [key])
    elif isinstance(node, list):
        for i, item in enumerate(node):
            label = item.get("id") or item.get("entity") or item.get("source") if isinstance(item, dict) else None
            yield from walk_quotes(item, where + [label or str(i)])


def check(gold, texts):
    failures = []
    quotes = list(walk_quotes(gold, []))
    for where, q in quotes:
        if normalize(q["text"]) not in texts.get(q["chapter"], ""):
            failures.append(f"quote not in ch {q['chapter']}: {'/'.join(where)}: {q['text'][:90]!r}")

    ids = {e["id"] for e in gold["entities"]}
    chapters = set(texts)
    for e in gold["entities"]:
        if e["first_chapter"] not in chapters:
            failures.append(f"entity {e['id']} first_chapter out of range")

    for r in gold["relations"]:
        for side in ("source", "target"):
            if r[side] not in ids:
                failures.append(f"relation references unknown entity {r[side]}")
        if r["quote"]["chapter"] != r["first_chapter"]:
            failures.append(f"relation {r['source']}-{r['type']}-{r['target']} quote ch != first_chapter")

    for s in gold["statuses"]:
        if s["entity"] not in ids:
            failures.append(f"status references unknown entity {s['entity']}")
        for step in s["timeline"]:
            if step["quote"]["chapter"] != step["chapter"]:
                failures.append(f"status {s['entity']} ch {step['chapter']} quote from another chapter")

    for r in gold["identity_reveals"]:
        if r["entity"] not in ids:
            failures.append(f"identity reveal references unknown entity {r['entity']}")
        if r["quote"]["chapter"] != r["reveal_chapter"]:
            failures.append(f"identity reveal {r['entity']}/{r['alias']} quote ch != reveal_chapter")

    return quotes, failures


def main():
    gold_path, epub_path = sys.argv[1], sys.argv[2]
    gold = json.loads(Path(gold_path).read_text())
    texts = chapter_texts(gold, epub_path)
    quotes, failures = check(gold, texts)
    print(f"chapters={len(gold['chapters'])} entities={len(gold['entities'])} "
          f"statuses={len(gold['statuses'])} relations={len(gold['relations'])} identity_reveals={len(gold['identity_reveals'])}")
    print(f"quotes checked={len(quotes)} failed={sum(f.startswith('quote') for f in failures)}")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
