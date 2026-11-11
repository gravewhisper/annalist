# Contributing

## Development

Run the tests:

```sh
python3 -m unittest
```

The suite takes about two minutes and makes no LLM calls. The tests build the small books in `tests/data/` with the `fake` backend. Tests that render the site skip when `node` is not installed. Tests that need a real novel's epub skip when it is missing.

Two tests guard the rules below:

- `tests/test_book_words.py` fails when code in `annalist/` uses a word from `tests/data/book-words.txt`, a list of names and terms from the test books.
- `tests/test_asof_leaks.py` fails when any view shows a word from a later chapter.

Rules for changes:

- Fix every wiki problem in code, with a test that fails before the fix.
- Write no rule for one book. Prove a fix on the made-up books in `tests/data/`, not only on a real novel.
- Never edit run data by hand, except the settings in `book.json` and the entries in `corrections.json`. Change the code, then rebuild. The stamps rerun only the stages whose code changed.


## Repository layout

- `annalist/cli.py` defines the subcommands. `annalist/build.py` defines the stages and the stamps.
- `annalist/backends.py` holds the backends. `annalist/llm.py` holds the reply cache, retries, and the spend log.
- One module per stage, such as `annalist/read.py`, `annalist/resolve.py`, and `annalist/profile.py`.
- `annalist/export.py` writes `wiki.json`. `annalist/site/` holds the site: `index.html`, `app.js`, and `app.css`.
- `annalist/review.py` holds the review checks. `annalist/scorecard.py` and `annalist/readerkey.py` hold the evals.
- `annalist/themes/` holds site themes, matched to a book by title.
- `tests/` holds the tests. `tests/data/` holds the test books, gold files, and the book-word list.
- `docs/backends.md` documents the backends.
- `runs/` holds run directories. Git ignores it.

A run directory holds `chapters/` and `chapters.json`, `volumes.json`, `book.json`, `state/`, one JSON file per stage, `arcs.json`, `cache/`, `calls.jsonl`, `build.json`, `wiki/`, `site/`, `review.md`, and, once you add one, `corrections.json`.
