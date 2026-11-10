import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path

from annalist.epub import cmd_extract, story_end

HOUND = Path(os.environ.get("ANNALIST_HOUND_EPUB", Path(__file__).resolve().parent / "data" / "cache" / "hound.epub"))

CONTAINER = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""


def write_epub(path, docs):
    manifest = "".join(f'<item id="d{i}" href="d{i}.html" media-type="application/xhtml+xml"/>' for i in range(len(docs)))
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(len(docs)))
    opf = (f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
           f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        for i, (title, paragraphs) in enumerate(docs):
            body = "".join(f"<p>{p}</p>" for p in paragraphs)
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
