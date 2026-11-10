import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "annalist"
WORDS = ROOT / "tests" / "data" / "book-words.txt"


def word_pattern(word):
    flags = 0 if word[0].isupper() else re.IGNORECASE
    return word, re.compile(rf"(?<![\w-]){re.escape(word)}(?:e?s)?(?![\w-])", flags)


def package_files():
    for path in sorted(PACKAGE.rglob("*")):
        parts = path.relative_to(PACKAGE).parts
        if path.is_file() and not any(p == "__pycache__" or p.startswith(".") for p in parts):
            yield path


class BookWordsTest(unittest.TestCase):
    def test_package_names_no_words_from_the_test_books(self):
        patterns = [word_pattern(w) for w in WORDS.read_text(encoding="utf-8").splitlines() if w.strip()]
        hits = []
        for path in package_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                hits += [f"{path.relative_to(ROOT)}:{number}:{word}" for word, pattern in patterns if pattern.search(line)]
        if hits:
            self.fail("package names words from the test books:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
