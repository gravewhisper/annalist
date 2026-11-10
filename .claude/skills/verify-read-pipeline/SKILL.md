---
name: verify-read-pipeline
description: Model-check the pipelined read stage of Annalist (annalist/read.py cmd_read, where chapter N+1 is extracted while chapter N's support check runs) with TLA+/TLC against every order of LLM failures and process kills. Use before committing any change to annalist/read.py, the save path in annalist/files.py, or load_states in annalist/state.py, and whenever check.py reports drift.
---

# Verify the read pipeline

`annalist read` (the `read` stage of `annalist build`) reads chapters in order. Since commit `ceb923c`, it overlaps work:

1. Chapter N+1's extract call starts as soon as chapter N's extract returns.
2. Chapter N's support check runs at the same time, on a one-worker thread pool.
3. Each chapter is saved to `state/NNNN.json` only after its check finishes.
4. Any LLM call can fail, and the process can be killed. The user then reruns the same command, possibly with a different `--to`.

`model/ReadPipeline.tla` models that loop. TLC checks every order of steps, failures and kills within the bounds below.

## The rules, and the harm if one breaks

| Rule | In plain words | Harm if broken |
| --- | --- | --- |
| `SavedInOrder` | The saved chapters are always 1..k, with no gaps. | A gap blocks every later rerun with "delete those states too". Fixing it takes hand deletion of run data and paid rereads. |
| `ReadAgainstKept` | Each saved chapter was read against exactly the earlier chapters the wiki keeps on disk: every one of them, in the saved version, and nothing later. | The wiki records facts from a reading that saw a different or missing earlier chapter, or a later one. A later chapter is a spoiler, and spoilers break the product's core promise. |
| `OnlyPreviousUnchecked` | Only the chapter just before can be shown before its check is saved. Every older chapter was shown after its check, so a claimed answer stays open until the check that accepts it is saved. | The reader treats unchecked facts and answers from older chapters as settled. Questions close on answers that were never accepted. |
| `Resumable` | A rerun never hits the "read in order" or "later chapters were read" refusals. | "Rerun the same command to resume" stops working, and a long unattended read stops partway. |
| `CleanRunFinishes` | A run with no failed call and no kill saves every chapter up to `--to`. | A clean build silently leaves chapters unread. |

## Scope, bounds and assumptions

What is verified:

- Default bounds: 5 chapters and up to 4 faults in total, across all runs. Faults are failed extracts, failed checks, and kills.
- Each rerun picks any `--to` from 1 to 5.
- That is 1,108,056 distinct states, which takes about 8 seconds.
- A pass covers the model at these bounds, not the whole system.

Assumptions, each confirmed in the code at the sync commit:

- **One pending chapter at a time.** `ThreadPoolExecutor(max_workers=1)`, and `save_checked` waits on `pending["state"].result()` before the next submit.
- **The check thread only reads shared data.** That covers the `kb` and the extraction dict `out`, which the check thread and `with_unchecked` both use.
  - `checked_state`, `label_timelines` and `clean_timelines` only read `kb.questions` and `kb.timelines`.
  - `audit_support`, `timeline_items`, `reread` and `reread_context` only read `out`.
  - `Knowledge.apply` and `Knowledge.upsert_entity`, run by `with_unchecked` on a `kb` copy, only read `out`.
  - `kb` changes only in `save_checked`, after the check has finished.

  So the model treats extract and check as separate atomic steps. These functions are in the coverage record, so a change that adds a write shows as drift.
- **A state file is whole or absent after a kill.** `files.write_atomic` writes a `.tmp` file, then calls `os.replace`.
- **A rerun loads every state file as checked** (`load_states`).
- **Every extract may return a different reply.** The model does not rely on the reply cache to repeat a reply.

Not covered:

- **Power loss.** This machine has lost power during runs twice. `write_atomic` does not `fsync` before `os.replace`, so "whole or absent" holds for a killed process, not for a power cut. After one, a state file can be empty or truncated on btrfs, and `load_states` would then crash on resume. This is the closest unverified risk.
- **Inputs `load_states` folds in besides state files:** `merges.json`, `types.json`, `discover.json`, answers, and the ending. The rule "nothing later" speaks only about state files.
- `--from` greater than 1. Only `annalist read` takes it. The `build` stage always starts at 1.
- What `kb.apply` does with the data, such as whether unchecked claims are really left open. `tests/test_read_overlap.py` covers that.
- Exceptions other than `LLMError` and `LLMUnavailable`.
- Prompt contents, LLM quality, and the other stages.

## Does my change touch the verified code?

`coverage.json`, in this folder, is the coverage record. It lists each covered function, its AST fingerprint, the model actions it maps to, and the `sync_commit` at which the model was last confirmed to describe the code:

| Code | Model |
| --- | --- |
| `annalist/read.py` `cmd_read` | `Run`, `LoopEnd`, `SkipSaved`, `RefuseOrder` (line 68), `RefuseLater` (lines 70-73), `ExtractOk`/`ExtractFails` (line 75), `NoPendingSubmit`/`SavePendingThenSubmit` (lines 76-79), `PendingCheckFailed` (lines 77, 80-81), `FinalSave`/`FinalExits` (lines 82-86) |
| `annalist/read.py` `stop_reading` | `StopSaves`, `StopExits` |
| `annalist/read.py` `with_unchecked`, `extract_chapter` | `View`, `ExtractOk`, `ExtractFails` |
| `annalist/read.py` `checked_state` | `CheckOk`, `CheckFails` |
| `annalist/read.py` `save_checked`, `annalist/files.py` `write_json` | `SaveDisk`, `SaveMem` |
| `annalist/files.py` `write_atomic` | `Killed`: a file is whole or absent |
| `annalist/state.py` `load_states` | `Loaded`: every state file is applied as checked |
| `annalist/state.py` `Knowledge.apply`, `Knowledge.upsert_entity`; `annalist/audit.py` `audit_support`, `reread`, `reread_context`; `annalist/timelines.py` `label_timelines`, `clean_timelines`, `timeline_items` | the read-only assumption that makes extract and check separate steps |

The line numbers are as of the sync commit.

You don't need to work this out by hand. `check.py` compares fingerprints and lists every covered function that changed. Fingerprints ignore comments and formatting, but not docstrings.

## Run it

From the repo root:

```sh
python3 .claude/skills/verify-read-pipeline/check.py            # drift report, then TLC at 5 chapters / 4 faults (~8 s)
python3 .claude/skills/verify-read-pipeline/check.py --mutants  # 5 broken variants, each must be caught (~3 s)
python3 .claude/skills/verify-read-pipeline/check.py --bounds 6 4   # wider bound; slower
```

It needs Java 17 or later. It uses `tla2tools.jar` TLA+ v1.7.4 (TLC 2.19), checked by sha256. It uses `$TLA2TOOLS` or a cached copy, and otherwise downloads the pinned release once. The JVM heap is capped at 2 GB and TLC runs 2 workers, to respect the repo's memory rule. Run one check at a time.

Each run writes `runs/verify-read-pipeline/<timestamp>-check/` (git-ignored), with `tlc.log`, `result.json`, and the model copy that was checked.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Pass, and the covered code matches the sync commit. |
| `1` | A rule broke, or TLC found a deadlock. It prints the rule and the shortest path as a list of model actions. With `--mutants`, it means a variant was missed. |
| `2` | Tool or model error. Read the printed tail of `tlc.log`. |
| `3` | TLC passed, but covered code changed since the sync commit. The pass says nothing about the new code until the model is brought in line. |

## Read every result with /statechart

Read every result with the pstack `/statechart` skill, run on `model/ReadPipeline.tla` and its config:

- On a violation, it gives the shortest path to the broken rule in plain words.
- On a pass, it draws how the read moves between states.

Use it to explain a result to the user. Don't paste raw TLC traces. Each action name in the path maps to code through the table above.

`model/statechart-view.mjs` gives the chart plain labels: chapters saved, the pending check, and refusals. If `/statechart` changes its view format, follow its own instructions for the view.

For a readable chart, run it on a copy of the config with `N = 2` and `MaxFaults = 1`. The default bounds go far past a chart's state budget. The tried break (`gap-check-ignores-pending`) reproduces at these small bounds. If a break does not, read the path from `check.py` and `tlc.log`.

On a violation, `/statechart` also reports `NoDeadlock` at the refusal states, because a refused run is an end state with no step out. That is a consequence of the `Resumable` break, not a separate bug. The correct model has no deadlock, and `check.py` checks for one.

## Real bug or modeling error?

When a rule breaks, take the shortest path and replay it in the code:

1. For each step, open the code in the table and check that the code can take that step from that state. Check the guards (`if pending`, `pending["n"] < n`, `state_path.exists()`), the order of calls, and which exceptions are caught.
2. **The code can take every step.** It is a real bug. Report it to the user as a numbered sequence in the code's terms, such as "chapter 3's check fails while chapter 4 is being extracted; `save_checked` raises at line 77; …", together with the rule it breaks and the harm from the table. If you can, add a failing test in the style of `tests/test_read_overlap.py`, which drives `cmd_read` with a fake `llm` and failure injection. Don't weaken the rule or the model, and don't change product code unless the user asks.
3. **The code cannot take some step.** It is a modeling error. Fix the model so that the action matches the code: a guard, an atomic step that is really two steps, or a missing exception path. Rerun. Say what you fixed and why.
4. **A TLC error that names a line in the spec**, such as "evaluating the nested expressions", is a spec bug, not a finding. TLC explores each branch of a disjunction in an action separately, so guard every branch that reads `pending.x` with `pending # None`.

## When you change the covered code on purpose

1. Mirror the change into `model/ReadPipeline.tla`. Each action carries a comment naming its lines in `read.py`. Keep one model action per indivisible step in the code. A new LLM call or thread hand-off is a new step.
2. If the change alters a promise, such as a deeper pipeline where two chapters are in flight, ask the user before you change a rule. Don't edit a rule to make it pass.
3. Run `check.py`. It must pass, or fail only on findings you report.
4. Run `check.py --mutants`. If an edit in `mutants.json` no longer applies, update its `old` text to the new model. Keep each variant mirroring the same code break.
5. Only after you have confirmed, action by action, that the model describes the code at the new commit: commit the code, then run `check.py --resync`. That rewrites the fingerprints and moves `sync_commit` to HEAD. It refuses to run while covered files have uncommitted changes. Never resync just to make drift go away.

If check.py reports drift for a change that does not affect the modeled behavior, read the diff of each listed function. Examples are a log message or a new prompt field. Confirm that no model action changes, then resync. Name the functions you checked in your reply.

## How a break is caught

`check.py` checks the model, not the code. A code change shows up first as drift (exit 3), which names the changed functions. The break is caught only after you mirror the change into the model, as above. Skipping that step leaves the change unverified. Exit 3 is never a pass.

## Broken variants the check is proven to catch

`check.py --mutants` applies each variant in `model/mutants.json` to a copy of the model. Each one must break its rule:

| Variant | Code it mirrors | Rule it breaks |
| --- | --- | --- |
| `no-unchecked-view` | `extract_chapter` uses `kb` instead of `with_unchecked(kb, pending)` | `ReadAgainstKept` |
| `no-deepcopy` | `with_unchecked` applies to `kb` without `copy.deepcopy` | `OnlyPreviousUnchecked` |
| `gap-check-ignores-pending` | line 68 loses `and not (pending and pending["n"] == n - 1)` | `Resumable` |
| `skip-failed-check` | a failed `save_checked(pending)` is caught and the loop moves on | `SavedInOrder` |
| `no-final-save` | the `if pending: save_checked(...)` after the loop is dropped | `CleanRunFinishes` |

Keep `/pstack:maintain-formal-verification-skill` in mind for changes that landed without a recheck.
