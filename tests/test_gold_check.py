import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_epub import extract, write_epub

sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))
from check_gold import chapter_texts, check  # noqa: E402
from epubtext import normalize  # noqa: E402

TAIL = "Livia Hale climbed the last stair of the lighthouse while the gulls wheeled over the quay below her."
CAPTION = "The lamp at dusk."
SECOND = "Bram Ostrow counted the crates on the quay twice and found one missing from the Gannet Guild stores."
PAGE_TWO = "Sister Wren watched him from the chapel door and said nothing about the missing crate at all."
THIRD = "Tomas Hale lit the lamp at the top of the tower and the whole harbour turned gold beneath it."


def gold(hrefs, quotes):
    return {"chapters": [{"index": n, "title": "", "href": h} for n, h in enumerate(hrefs, 1)],
            "entities": [{"id": "livia", "name": "Livia Hale", "type": "character", "aliases": [], "first_chapter": 1}],
            "statuses": [{"entity": "livia", "timeline": [{"chapter": n, "status": "alive", "quote": {"chapter": n, "text": q}}]}
                         for n, q in quotes],
            "relations": [], "identity_reveals": []}


class FragmentChapterTest(unittest.TestCase):
    def test_a_gold_key_finds_quotes_in_chapters_that_share_a_document_and_cuts_them_like_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            write_epub(epub, [
                ("Cover", ["A Test Book"]),
                ("One", [("c1", "Chapter 1"), "The keeper's daughter woke before the bell rang over the harbour town."]),
                ("Two", [TAIL, ("cap", CAPTION), ("c2", "Chapter 2"), SECOND, ("pg2", PAGE_TWO), ("c3", "Chapter 3"), THIRD]),
            ], toc=[("One", "d1.html#c1", []), ("The lamp", "d2.html#cap", []), ("Two", "d2.html#c2", []), ("Three", "d2.html#c3", [])])
            chapters, texts, _ = extract(epub, Path(tmp) / "work")
            hrefs = [c["href"] for c in chapters]
            self.assertEqual(hrefs, ["OEBPS/d1.html", "OEBPS/d2.html#c2", "OEBPS/d2.html#c3"])
            key = gold(hrefs, [(1, TAIL), (2, CAPTION), (2, PAGE_TWO), (3, THIRD)])
            found = chapter_texts(key, epub)
            _, failures = check(key, found)
            self.assertEqual(failures, [])
            self.assertEqual([found[n] for n in (1, 2, 3)], [normalize(t) for t in texts])
            _, failures = check(gold(hrefs, [(1, SECOND), (3, PAGE_TWO)]), found)
            self.assertEqual(len(failures), 2)


if __name__ == "__main__":
    unittest.main()
