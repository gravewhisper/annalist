# Evaluate a wiki

`annalist eval` scores a built wiki against a gold file, a reader key, or both:

```sh
python3 -m annalist eval runs/book gold.json
python3 -m annalist eval runs/book --reader-key reader.json
```

A gold file lists the chapters, entities, statuses, relations, identity reveals, and pairs that must not merge. Scoring against it makes no LLM calls and writes `eval.md` and `eval.json`. `tests/data/mini-gold.json` is an example. If the run's chapters do not line up with the gold file's, `eval` exits with an error and scores nothing else. A gold file that covers only the opening chapters sets `"partial": true`, and then the run may have later chapters, such as a build with `--to`.

Gold relations measure recall only: a missing relation fails, but a wrong relation the wiki adds is never counted. `--relation-sample N` measures precision. It picks N of the wiki's relations and asks an LLM judge whether each one is correct as worded, given its quotes and about 700 characters of chapter text around each quote. The judge answers `correct`, `wrong` (a different tie, the reverse direction, or a contradiction), or `unsupported` (the passage neither shows nor contradicts it), with a reason. This costs money, so it runs only with the flag, and it needs a gold file:

```sh
python3 -m annalist eval runs/book gold.json --relation-sample 40
```

The result is the `relation_precision` section of `eval.md` and `eval.json`. In `eval.json` it holds `totals` (`relations` in the wiki, `sampled`, `correct`, `wrong`, `unsupported`, and `precision`, which is correct over sampled), `judge_model`, `judge_spend_usd`, and one row per sampled relation with its `key`, chapter, ends, wording, quotes, `verdict`, and `reason`. A relation is keyed by its chapter, source name, wording, and target name, such as `ch3 Ana Holt | aunt of | Pell Holt`. The sample is the N keys with the lowest hash under a fixed seed, so a rerun on an unchanged wiki judges the same rows, and a rebuild that adds or drops a few relations keeps the rest of the sample. Replies are cached in the run's `cache/`, so a rerun is free. The gold sections stay free and deterministic.

A reader key holds a reader's own answers to the book's questions, plus the merges, relations, and structure they expect. An LLM judges whether the wiki agrees with each answer, so this mode costs money. `--judge-model` picks the judge model for this mode and for `--relation-sample`. It writes `reader-eval.md` and `reader-eval.json`.

`review.md`, which every build writes, is a cheaper first check. It lists problems that code can find, such as main characters with an empty status or power field, merges across types, and quotes that lack the words of their value.

## Genre benchmark

`tests/data/bench.py` scores Annalist on six public-domain novels that each stress a different problem: a mystery with false names, four sisters who share one form of address, Russian name forms, a story told in journals and letters, a first-person narrator, and prisoners known by numbers. Each book has a gold file, `tests/data/<name>-gold.json`, for its opening chapters. Every quote in a gold file is checked against the epub by `tests/data/check_gold.py`.

```sh
python3 tests/data/bench.py fetch      # download the epubs from Project Gutenberg
python3 tests/data/bench.py build      # build each book's scoped chapters into runs/bench-<name>; costs money
python3 tests/data/bench.py score      # score every built run and print one table
```

Pass book names to work on some of them, such as `bench.py build crime`. `bench.py score --relation-sample 40` passes the flag to each eval and adds a relation precision column; it costs money. A change that fixes one book must not lower the others.
