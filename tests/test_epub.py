import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path

from annalist.boundaries import from_toc
from annalist.epub import cmd_extract, extract_book, story_end

HOUND = Path(os.environ.get("ANNALIST_HOUND_EPUB", Path(__file__).resolve().parent / "data" / "cache" / "hound.epub"))

CONTAINER = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""


def nav_list(toc):
    return "<ol>" + "".join(f'<li><a href="{href}">{label}</a>{nav_list(children) if children else ""}</li>'
                            for label, href, children in toc) + "</ol>"


def write_epub(path, docs, toc=None):
    """docs: (title, paragraphs); a paragraph given as (anchor, text) carries that id.
    toc: nested (label, href, children) entries, written as an EPUB 3 nav document."""
    manifest = "".join(f'<item id="d{i}" href="d{i}.html" media-type="application/xhtml+xml"/>' for i in range(len(docs)))
    if toc is not None:
        manifest += '<item id="nav" href="nav.html" media-type="application/xhtml+xml" properties="nav"/>'
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(len(docs)))
    opf = (f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
           f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        if toc is not None:
            zf.writestr("OEBPS/nav.html", '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
                        f'<body><nav epub:type="toc">{nav_list(toc)}</nav></body></html>')
        for i, (title, paragraphs) in enumerate(docs):
            body = "".join(f'<p id="{p[0]}">{p[1]}</p>' if isinstance(p, tuple) else f"<p>{p}</p>" for p in paragraphs)
            zf.writestr(f"OEBPS/d{i}.html", f"<html><head><title>{title}</title></head><body>{body}</body></html>")


def extract(epub, workdir, min_words=5):
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_extract(Namespace(epub=str(epub), workdir=str(workdir), min_words=min_words))
    chapters = json.loads((Path(workdir) / "chapters.json").read_text(encoding="utf-8"))
    texts = [(Path(workdir) / "chapters" / f"{c['index']:04d}.txt").read_text(encoding="utf-8") for c in chapters]
    return chapters, texts, json.loads((Path(workdir) / "source.json").read_text(encoding="utf-8"))


STORY = "The moor was dark and the hound bayed somewhere far beyond the hall."


class GutenbergTest(unittest.TestCase):
    def test_header_and_license_are_stripped_and_the_story_counts_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_epub(Path(tmp) / "book.epub", [
                ("Front", ["The Project Gutenberg eBook of A Test", "This ebook is for the use of anyone anywhere in the "
                           "United States and most other parts of the world.", "*** START OF THE PROJECT GUTENBERG EBOOK A TEST ***",
                           "Chapter 1. Opening", STORY]),
                ("Chapter 2", ["Chapter 2. Ending", STORY, "THE END", "*** END OF THE PROJECT GUTENBERG EBOOK A TEST ***",
                               "THE FULL PROJECT GUTENBERG LICENSE", "Section 1. General Terms of Use and Redistributing "
                               "Project Gutenberg electronic works"]),
                ("License", ["1.E. Unless you have removed all references to Project Gutenberg, you must comply with these terms."]),
            ])
            chapters, texts, source = extract(Path(tmp) / "book.epub", Path(tmp) / "work")
        self.assertEqual(len(chapters), 2)
        self.assertTrue(texts[0].startswith("Chapter 1. Opening"))
        self.assertTrue(texts[1].rstrip().endswith("THE END"))
        self.assertFalse(any("gutenberg" in t.lower() for t in texts))
        self.assertEqual(source, {"complete": True, "complete_evidence": "the Project Gutenberg end marker"})

    def test_books_without_markers_keep_every_paragraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_epub(Path(tmp) / "book.epub", [("One", ["Chapter 1", STORY]), ("Two", ["Chapter 2", STORY])])
            chapters, texts, source = extract(Path(tmp) / "book.epub", Path(tmp) / "work")
        self.assertEqual([t.split("\n\n")[0] for t in texts], ["Chapter 1", "Chapter 2"])
        self.assertFalse(source["complete"])

    @unittest.skipUnless(HOUND.exists(), "Hound of the Baskervilles epub not available")
    def test_hound_of_the_baskervilles(self):
        with tempfile.TemporaryDirectory() as tmp:
            chapters, texts, source = extract(HOUND, Path(tmp) / "work", min_words=300)
        self.assertEqual(len(chapters), 15)
        self.assertEqual(chapters[0]["title"], "Chapter 1. Mr. Sherlock Holmes")
        self.assertFalse([c["index"] for c, t in zip(chapters, texts) if "gutenberg" in t.lower() or "license" in t.lower()])
        self.assertTrue(texts[-1].rstrip().endswith("THE END"))
        self.assertTrue(source["complete"])


class FrontMatterTest(unittest.TestCase):
    def test_prefaces_and_contents_pages_are_not_chapters_but_a_prologue_is(self):
        contents = ["THE TEST NOVEL", "by A. Writer", "Contents"] + [f"Chapter {i}. A Title Here" for i in range(1, 12)]
        with tempfile.TemporaryDirectory() as tmp:
            write_epub(Path(tmp) / "book.epub", [
                ("Title", contents),
                ("Preface", ["TRANSLATOR’S PREFACE", "A few words about the author may help the English reader. " * 3]),
                ("Foreword", ["Foreword", "The author thanks the public for the indulgent ear it has lent. " * 3]),
                ("Prologue", ["Prologue", STORY]),
                ("One", ["Chapter 1", STORY]),
                ("Two", ["Chapter 2", STORY]),
            ])
            chapters, texts, _ = extract(Path(tmp) / "book.epub", Path(tmp) / "work")
        self.assertEqual([t.split("\n\n")[0] for t in texts], ["Prologue", "Chapter 1", "Chapter 2"])
        self.assertEqual([c["index"] for c in chapters], [1, 2, 3])


class TocAnchorTest(unittest.TestCase):
    def test_a_document_holding_several_toc_chapters_splits_at_their_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_epub(Path(tmp) / "book.epub", [
                ("Opening", [("p1", "Part One"), ("c1", "Chapter 1"), STORY]),
                ("Middle", ["The end of the first chapter spills over here.", ("p2", "Part Two"), ("c2", "Chapter 2"), STORY,
                            ("c3", "Chapter 3"), STORY]),
                ("Closing", [("p3", "Part Three"), ("c4", "Chapter 4"), STORY]),
            ], toc=[("Part One", "d0.html#p1", [("One", "d0.html#c1", [])]),
                    ("Part Two", "d1.html#p2", [("Two", "d1.html#c2", []), ("Three", "d1.html#c3", [])]),
                    ("Part Three", "d2.html#p3", [("Four", "d2.html#c4", [])])])
            chapters, texts, _ = extract(Path(tmp) / "book.epub", Path(tmp) / "work")
            volumes = from_toc(extract_book(Path(tmp) / "book.epub", min_words=5))
        self.assertEqual([(c["title"], c["href"]) for c in chapters], [
            ("Opening", "OEBPS/d0.html"), ("Two", "OEBPS/d1.html#c2"), ("Three", "OEBPS/d1.html#c3"), ("Closing", "OEBPS/d2.html")])
        self.assertTrue(texts[0].rstrip().endswith("spills over here."))
        self.assertEqual([t.rstrip().split("\n\n")[:2] for t in texts[1:3]], [["Part Two", "Chapter 2"], ["Chapter 3", STORY]])
        self.assertEqual([c["words"] for c in chapters], [len(t.split()) for t in texts])
        self.assertEqual([(v["from"], v["to"]) for v in volumes], [(1, 1), (2, 3), (4, 4)])

    def test_text_before_the_first_anchor_joins_the_first_piece_when_no_chapter_precedes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_epub(Path(tmp) / "book.epub", [
                ("Whole", ["A few opening words before any chapter.", ("c1", "Chapter 1"), STORY, ("c2", "Chapter 2"), STORY]),
            ], toc=[("One", "d0.html#c1", []), ("Two", "d0.html#c2", [])])
            chapters, texts, _ = extract(Path(tmp) / "book.epub", Path(tmp) / "work")
        self.assertEqual([c["href"] for c in chapters], ["OEBPS/d0.html#c1", "OEBPS/d0.html#c2"])
        self.assertTrue(texts[0].startswith("A few opening words before any chapter.\n\nChapter 1"))

    def test_a_chapter_that_starts_late_in_one_document_keeps_its_rest_from_the_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            opening = "It began on a grey morning when nobody in the house was awake yet."
            write_epub(Path(tmp) / "book.epub", [
                ("First", [("c1", "Chapter 1"), STORY, STORY, ("c2", "Chapter 2"), opening]),
                ("Second", [STORY, STORY, ("c3", "Chapter 3"), STORY, STORY, ("c4", "Chapter 4"), STORY, STORY]),
            ], toc=[(n, f"d{(n - 1) // 2}.html#c{n}", []) for n in range(1, 5)])
            chapters, texts, _ = extract(Path(tmp) / "book.epub", Path(tmp) / "work", min_words=20)
        self.assertEqual([c["href"] for c in chapters], [f"OEBPS/d{(n - 1) // 2}.html#c{n}" for n in range(1, 5)])
        self.assertEqual(texts[1], f"Chapter 2\n\n{opening}\n\n{STORY}\n\n{STORY}\n")


class ReextractTest(unittest.TestCase):
    def test_extracting_a_different_epub_over_read_state_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_epub(Path(tmp) / "a.epub", [("One", ["Chapter 1", STORY]), ("Two", ["Chapter 2", STORY])])
            write_epub(Path(tmp) / "b.epub", [("One", ["Chapter 1", STORY])])
            extract(Path(tmp) / "a.epub", Path(tmp) / "work")
            extract(Path(tmp) / "a.epub", Path(tmp) / "work")
            (Path(tmp) / "work" / "state").mkdir()
            (Path(tmp) / "work" / "state" / "0001.json").write_text("{}", encoding="utf-8")
            extract(Path(tmp) / "a.epub", Path(tmp) / "work")
            with self.assertRaises(SystemExit) as stopped:
                extract(Path(tmp) / "b.epub", Path(tmp) / "work")
            self.assertIn("extracts to different chapters", str(stopped.exception))
            self.assertEqual(len(json.loads((Path(tmp) / "work" / "chapters.json").read_text(encoding="utf-8"))), 2)


class StoryEndTest(unittest.TestCase):
    def test_ending_signals(self):
        self.assertTrue(story_end(["Chapter 40", "Epilogue"], "and so it ended."))
        self.assertTrue(story_end(["Chapter 1", "Chapter 2"], "They went home.\n\nTHE END"))
        self.assertEqual(story_end(["Chapter 1", "Chapter 2"], "To be continued."), "")
        self.assertEqual(story_end(["Fin the Dragon", "Chapter 2"], "He flew."), "")


if __name__ == "__main__":
    unittest.main()
