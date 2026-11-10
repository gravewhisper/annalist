import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from annalist.backends import ConfigError
from annalist.boundaries import detect_volumes, parse_volumes
from annalist.epub import extract_book

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tests" / "data" / "cache"
NOVELS = Path(os.environ.get("ANNALIST_NOVELS", CACHE / "novels"))
LOTM = NOVELS / "Lord of the Mysteries (No Artwork).epub"
PERFECT_RUN = NOVELS / "The Perfect Run.epub"
HOUND = CACHE / "hound.epub"

CONTAINER = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""

STORY = "The moor was dark and the hound bayed somewhere far beyond the hall."


def nav_list(entries):
    return "<ol>" + "".join(f'<li><a href="{href}">{label}</a>{nav_list(children) if children else ""}</li>'
                            for label, href, children in entries) + "</ol>"


def write_epub(path, docs, title="Synthetic Saga", toc=None):
    manifest = "".join(f'<item id="d{i}" href="d{i}.html" media-type="application/xhtml+xml"/>' for i in range(len(docs)))
    if toc is not None:
        manifest += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(len(docs)))
    opf = (f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title></metadata>'
           f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        if toc is not None:
            zf.writestr("OEBPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
                                           f'<body><nav epub:type="toc">{nav_list(toc)}</nav></body></html>')
        for i, (doc_title, paragraphs) in enumerate(docs):
            body = "".join(f"<p>{p}</p>" for p in paragraphs)
            zf.writestr(f"OEBPS/d{i}.html", f"<html><head><title>{doc_title}</title></head><body>{body}</body></html>")


def chapter(title, *extra):
    return (title, [title, STORY, *extra])


def volumes_of(docs, toc=None, override=None):
    with tempfile.TemporaryDirectory(dir=CACHE) as tmp:
        write_epub(Path(tmp) / "book.epub", docs, toc=toc)
        book = extract_book(Path(tmp) / "book.epub", min_words=5)
    found = detect_volumes(book, override)
    return found["source"], [(v["name"], v["from"], v["to"]) for v in found["volumes"]]


class DetectVolumesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CACHE.mkdir(parents=True, exist_ok=True)

    def test_toc_parts_with_chapters_become_volumes(self):
        docs = [chapter(f"Chapter {n}") for n in range(1, 7)]
        toc = [("Saga", "d0.html", [("Part One: Ash", "d0.html", [(f"Chapter {n}", f"d{n - 1}.html", []) for n in (1, 2, 3)]),
                                    ("Part Two: Ember", "d3.html", [(f"Chapter {n}", f"d{n - 1}.html", []) for n in (4, 5, 6)])])]
        self.assertEqual(volumes_of(docs, toc), ("toc", [("Part One: Ash", 1, 3), ("Part Two: Ember", 4, 6)]))

    def test_a_single_toc_wrapper_over_flat_chapters_is_one_volume(self):
        docs = [chapter(f"{n} Title") for n in range(1, 5)]
        toc = [("Synthetic Saga", "d0.html", [(f"{n} Title", f"d{n - 1}.html", []) for n in range(1, 5)])]
        self.assertEqual(volumes_of(docs, toc), ("whole-book", [("Synthetic Saga", 1, 4)]))

    def test_divider_pages_start_volumes(self):
        docs = [("Book One", ["Book One"]), chapter("Chapter 1"), chapter("Chapter 2"),
                ("Book Two", ["Book Two: The Return"]), chapter("Chapter 3"), chapter("Chapter 4")]
        self.assertEqual(volumes_of(docs), ("headings", [("Book 1", 1, 2), ("Book 2: The Return", 3, 4)]))

    def test_a_heading_inside_a_chapter_starts_a_volume_at_that_chapter(self):
        docs = [chapter("Prologue"), chapter("Chapter 1"), ("Volume II", ["Volume II - Winter", "Chapter 2", STORY]), chapter("Chapter 3")]
        self.assertEqual(volumes_of(docs), ("headings", [("Volume 1", 1, 2), ("Volume 2: Winter", 3, 4)]))

    def test_end_of_volume_markers_close_volumes(self):
        docs = [chapter("1 Dawn"), chapter("2 Morning"), chapter("3 Noon", "(End of the First Volume\u2014Daybreak)"),
                chapter("4 Dusk"), chapter("5 Evening"), chapter("6 Night", "(End of the Second Volume\u2014Nightfall)"),
                chapter("7 Coda"), chapter("8 Envoi")]
        self.assertEqual(volumes_of(docs), ("end-markers", [("Volume 1: Daybreak", 1, 3), ("Volume 2: Nightfall", 4, 6),
                                                           ("After Volume 2", 7, 8)]))

    def test_chapter_numbers_restarting_at_one_start_a_book(self):
        docs = [chapter(f"Chapter {n}") for n in (1, 2, 3, 1, 2, 3)]
        self.assertEqual(volumes_of(docs), ("numbering", [("Book 1", 1, 3), ("Book 2", 4, 6)]))

    def test_a_numbering_typo_is_not_a_restart(self):
        docs = [chapter(f"{n} Title") for n in (1, 2, 3, 4, 3, 6)]
        self.assertEqual(volumes_of(docs)[0], "whole-book")

    def test_chapters_titled_as_parts_are_not_volumes(self):
        docs = [chapter(f"Part {n}") for n in (1, 2, 3, 4)]
        self.assertEqual(volumes_of(docs), ("whole-book", [("Synthetic Saga", 1, 4)]))

    def test_no_signal_makes_one_volume_named_after_the_book(self):
        self.assertEqual(volumes_of([chapter("Opening"), chapter("Closing")]), ("whole-book", [("Synthetic Saga", 1, 2)]))

    def test_override_wins_over_detection(self):
        docs = [chapter(f"Chapter {n}") for n in (1, 2, 3, 1, 2, 3)]
        self.assertEqual(volumes_of(docs, override="1-4, Coda=5-6"), ("override", [("Volume 1", 1, 4), ("Coda", 5, 6)]))

    def test_override_must_be_ascending_ranges_inside_the_book(self):
        for spec in ("1-4,3-6", "0-2", "1-9", "one-two", ""):
            with self.subTest(spec=spec), self.assertRaises(ConfigError):
                parse_volumes(spec, 6)


class RealEpubVolumesTest(unittest.TestCase):
    def detect(self, epub):
        found = detect_volumes(extract_book(epub))
        return found["source"], [(v["name"], v["from"], v["to"]) for v in found["volumes"]]

    @unittest.skipUnless(LOTM.exists(), "Lord of the Mysteries epub not available")
    def test_lord_of_the_mysteries_volumes_end_at_their_markers(self):
        source, volumes = self.detect(LOTM)
        self.assertEqual(source, "end-markers")
        self.assertEqual(volumes[:2], [("Volume 1: Clown", 1, 213), ("Volume 2: Faceless", 214, 482)])
        self.assertEqual([v[2] for v in volumes], [213, 482, 732, 946, 1150, 1266, 1353, 1394, 1436])

    @unittest.skipUnless(PERFECT_RUN.exists(), "The Perfect Run epub not available")
    def test_the_perfect_run_is_one_volume(self):
        self.assertEqual(self.detect(PERFECT_RUN), ("whole-book", [("The Perfect Run", 1, 130)]))

    def test_mini_is_one_volume(self):
        self.assertEqual(self.detect(ROOT / "tests" / "data" / "mini.epub"), ("whole-book", [("The Salt Ledger", 1, 5)]))

    @unittest.skipUnless(HOUND.exists(), "Hound of the Baskervilles epub not available")
    def test_the_hound_is_one_volume(self):
        self.assertEqual(self.detect(HOUND), ("whole-book", [("The Hound of the Baskervilles", 1, 15)]))


if __name__ == "__main__":
    unittest.main()
