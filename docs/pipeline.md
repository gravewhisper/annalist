# How a build works

`annalist build` runs these stages in order. `STAGES` in `annalist/build.py` defines them. Each stage also exists as its own subcommand, such as `python3 -m annalist relate runs/book`.

1. `extract` splits the epub into chapter text files and writes `chapters.json`, `source.json`, and `volumes.json`.
2. `book` writes `book.json`: the power system, the power types, extra character fields, the timeline kind, and the power ladder shape.
3. `read` reads each chapter in order and writes `state/NNNN.json` with that chapter's entries, facts, relations, and open questions.
4. `timelines` labels which timeline each chapter happens in. It is skipped when `book.json` says the story is linear.
5. `wordings` splits relation wordings from older runs into a predicate and a detail.
6. `retype` checks the type each entry is filed under.
7. `discover` adds entries for names that recur in the text but that `read` never listed.
8. `resolve` merges entries that are one person, place, or thing under different names, including identities the book reveals later.
9. `relate` adds relations that each chapter shows between entries it names close together.
10. `link` adds relations that possessive names and character facts state.
11. `leads` folds a question raised again within two chapters of an open question about the same mystery into the open one, then keeps rejected answers to a question that are still useful partial leads.
12. `sweep` searches later chapters for passages that answer each open question.
13. `tiers` labels each question's scope as `series`, `arc`, or `cliffhanger`.
14. `profile` fills each character's infobox and profile from quoted facts.
15. `ladders` ranks the steps of each power ladder. It is skipped when the book has no ladder.
16. `families` sorts relation wordings into kinds, which set the graph's line colours.
17. `answers` judges, at each volume end, which open questions are answered, narrowed by leads, or based on a false premise.
18. `ending` judges the questions still open at the end of the book. It runs only when `book.json` sets `complete` and every chapter is read.
19. `volumes` divides the chapters read into story arcs and writes each finished volume's overview, arcs, and key events. Every arc but the last of the volume in progress is closed, and `arcs.json` keeps each closed arc frozen: a later build with more chapters read divides only the chapters after it, and the finished volume keeps it. Each closed arc is named and summarised from its own chapters' synopses only.
20. `render` writes page summaries, a History paragraph for each story arc in which a character has at least 5 quoted facts, and a Markdown and HTML wiki under `wiki/`.
21. `export` writes the static site to `site/`.
22. `review` writes `review.md` and `review.json`, a list of problems that code can find, such as merges across types and characters who die and then come back.

A build is resumable. If a stage fails, the build exits with status 2, and running the same command again continues from where it stopped. Five layers keep finished work:

- `read` skips every chapter that already has a `state/NNNN.json`.
- `build.json` stamps each finished stage with a digest of its input files and a digest of the code it runs. A stage reruns only when one of the two changes. `--dry-run` shows the reason, such as `run: code changed`.
- `cache/` stores every LLM reply, keyed by the step, the backend, the model, and the prompt. A rerun with the same prompt reuses the reply and costs nothing.
- `relate-replies.json` keeps each chapter's `relate` reply. A rebuild reuses it unless the chapter changed or the chapter names more than 2 new pairs of entries. Renames do not count as new pairs.
- `answers.json` keeps a question's verdict through a rebuild unless the question or its leads changed, or more than 2 of the chapters it was shown changed. Small shifts in which chapters rank highest do not ask it again.

Every LLM call is logged to `calls.jsonl` with its tokens and cost. The `--budget` check sums those costs.
