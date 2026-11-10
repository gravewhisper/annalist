# AGENTS.md

Guidance for coding agents working on Annalist. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the repository layout and [docs/pipeline.md](docs/pipeline.md) for the stages.

## Setup and tests

- Python 3.10 or later, standard library only. Do not add dependencies.
- Run `python3 -m unittest` from the repository root. It takes about two minutes and makes no LLM calls. Site tests need `node` and skip without it.
- Tests use the `fake` backend and the made-up books in `tests/data/`. Never let a test reach a real model.
- To prove a change end to end at no cost, build `tests/data/mini.epub` with the fake backend (see `tests/test_build.py` for the scripted replies).

## Rules

- **Fix wiki problems in code, with a test that fails before the fix.** Never edit run data by hand. The only hand-edited files in a run are `book.json` and `corrections.json`.
- **No rules for one book.** A fix must work on the made-up books in `tests/data/`, not only on a real novel. `tests/test_book_words.py` fails if package code uses a name from `tests/data/book-words.txt`.
- **Never leak a later chapter.** Anything shown as of chapter N may only come from chapters 1 to N. `tests/test_asof_leaks.py` must keep passing.
- **Every fact and relation needs a quote** that code can find in its chapter. Do not loosen the quote check.
- **Keep stages resumable.** A stage writes its output atomically and reruns only when its inputs or code change. Do not break the reply cache keys in `annalist/llm.py`.
- **Changing `annalist/read.py`, `annalist/state.py` `load_states`, or `annalist/files.py` `write_atomic`?** Run `python3 .claude/skills/verify-read-pipeline/check.py` and follow `.claude/skills/verify-read-pipeline/SKILL.md`.
- **Spending money.** Real builds cost money. Use `annalist build ... --dry-run` to see the cost, and pass `--budget` on any paid build.

## Commits

- One logical change per commit, with a plain message that says what changed and why.
- No AI attribution in commits or pull requests: no `Co-Authored-By` lines for AI tools, no session links, no "Generated with" footers.
- `runs/` and `.claude/worktrees/` are git-ignored. Keep build output and scratch files there.
