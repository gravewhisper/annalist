# Evaluate a wiki

`annalist eval` scores a built wiki against a gold file, a reader key, or both:

```sh
python3 -m annalist eval runs/book gold.json
python3 -m annalist eval runs/book --reader-key reader.json
```

A gold file lists the chapters, entities, statuses, relations, identity reveals, and pairs that must not merge. Scoring against it makes no LLM calls and writes `eval.md` and `eval.json`. `tests/data/mini-gold.json` is an example. If the run's chapters do not line up with the gold file's, `eval` exits with an error and scores nothing else. A gold file that covers only the opening chapters sets `"partial": true`, and then the run may have later chapters, such as a build with `--to`.

A reader key holds a reader's own answers to the book's questions, plus the merges, relations, and structure they expect. An LLM judges whether the wiki agrees with each answer, so this mode costs money. `--judge-model` picks the judge model. It writes `reader-eval.md` and `reader-eval.json`.

`review.md`, which every build writes, is a cheaper first check. It lists problems that code can find, such as main characters with an empty status or power field, merges across types, and quotes that lack the words of their value.
