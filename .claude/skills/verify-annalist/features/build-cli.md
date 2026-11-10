# Build and CLI

`python3 -m annalist build` turns an epub into a run directory with a static site. `--dry-run` prints the plan and the cost estimate and touches nothing. `verify` reports how many quotes match their chapter text. `export --public` writes a site with no chapter text and no quotes. `corrections.json` lets a user fix one book's wiki without LLM calls. Each `export` reapplies it and warns about rows that match nothing.

## Sub-features

- `cli-dry-run`: prints chapters, word counts, volumes, and stage costs, and writes no files.
- `cli-build`: runs every stage, ends with "annalist build: done", and writes `site/`, `review.md`, `calls.jsonl`, and `build.json`.
- `cli-resume`: a second `build` on a finished run reuses its stamps and the cache and makes no new calls.
- `cli-verify`: prints a quote-verification percentage for facts, relations, questions, and profiles.
- `cli-export-public`: `site-public/` has no `text/` folder and no quotes in `wiki.json`.
- `cli-corrections`: a type change is applied by `export`, and an unmatched `drop_relations` row prints a warning.

## How to get to it (user POV)

- From the repo root, run `python3 -m annalist <command> …` in a terminal. The `annalist` console script is the same entry point.

## Driving it with the shell

Preconditions:

- Baseline from `README.md`.
- In the shell: `. runs/verify-annalist/latest/state.env; export PATH="$WORK/bin:$PATH"`.

Steps:

- **Dry run writes nothing.** Run `python3 -m annalist build tests/data/mini.epub "$WORK/dry" --dry-run 2>&1 | tee "$EVIDENCE/cli-dry-run.txt"; echo "exit $?"; ls "$WORK/dry"`. The exit code is `0`. The output starts with `annalist build: mini.epub ->` and lists `chapters 1-5 of 5, 3,896 words` and a `total` line. `ls` fails with "No such file or directory".
- **Build.** `launch.sh` already ran this. Its proof is `$EVIDENCE/build.log`, which ends with `annalist build: done, $0.00 spent`, together with `ls "$RUN/site/data/wiki.json" "$RUN/review.md"`.
- **Resume makes no calls.** Run `wc -l < "$RUN/calls.jsonl"`, then `python3 -m annalist build tests/data/mini.epub "$RUN" --yes > "$EVIDENCE/cli-resume.txt" 2>&1; echo "exit $?"; grep 'annalist build: done' "$EVIDENCE/cli-resume.txt"`, then `wc -l < "$RUN/calls.jsonl"` again. The exit code is `0`, the grep finds `annalist build: done, $0.00 spent`, and both counts match (79 on the current code).
- **Verify.** Run `python3 -m annalist verify "$RUN" | tee "$EVIDENCE/cli-verify.txt"`. The exit code is `0`, and the output has lines starting with `facts:`, `relations:`, `questions:`, and `profiles:`, each with a percentage.
- **Public export.** Run `python3 -m annalist export --public "$RUN" "$WORK/site-public" | tee "$EVIDENCE/cli-export-public.txt"`, then `python3 -c "import json;w=json.load(open('$WORK/site-public/data/wiki.json'));print(w['book']['text'], sum(len(f.get('quotes',[])) for f in w['facts']))"` and `ls "$WORK/site-public"`. The output ends with `(public, …)`, the check prints `False 0`, and there is no `text` folder.
- **Corrections.** Run `echo '{"entries":[{"name":"Corvel Quay","type":"organization"}],"drop_relations":[{"source":"Nobody","target":"Ghost","type":"haunts","chapter":1}]}' > "$RUN/corrections.json"`, then `python3 -m annalist export "$RUN" "$RUN/site" 2>&1 | tee "$EVIDENCE/cli-corrections.txt"`. Output has `warning: corrections.json names 'Nobody -> Ghost: haunts (ch 1)', which matches no entry`. In `wiki.json`, Corvel Quay has type `organization`. To see it in the site, run `node $S/drive.mjs --name cli-corrections 'goto|#n=1&p=cat%3Aorganization' 'expect|#main|Corvel Quay'`. Restore the run with `rm "$RUN/corrections.json"`, then export again with the same command.

## Gotchas

- Without the stub `PATH`, a real `claude` on `PATH` could be called if the fake script runs out of replies. With the stub, that fails with `verify-annalist: real claude call blocked`.
- `export` refuses to run when the stage code changed since the last build. After you edit a stage, relaunch rather than export.
- `build` prints the review summary after its "done" line, so `tail` misses it. Grep for it instead.
- `build` without `--yes` and without a TTY stops before spending. Always pass `--yes` or `--dry-run` in scripts.
- The dry run reports `backend claude-cli`, because a new directory has no `book.json` yet. That is expected, and it still makes no calls.
