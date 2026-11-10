# Annalist verification map

This directory is the maintained source for verifying what Annalist users see and do. Read this index before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- `S=.claude/skills/verify-annalist/scripts`, run from the repo root.
- `$S/launch.sh` has built `tests/data/mini.epub` ("The Salt Ledger", chapters 1 to 5) with the fake backend, and it is serving the site.
- `$S/doctor.sh` exits 0. Every check reads `ok`, and the served site files match `annalist/site/`.
- `. runs/verify-annalist/latest/state.env` gives `BASE`, `RUN`, `WORK`, and `EVIDENCE`.
- Never drive an instance that this run's `launch.sh` did not start. That includes a site the user is serving from a real run.

## Story facts the recipes rely on

These come from the mini book's scripted replies, so they are stable:

- Chapter titles: 1 The Missing Page, 2 Nine Winters Ago, 3 The Abbey Stair, 4 Two Names, 5 The Salt Ledger.
- Livia Hale (`c7d047a4`) first appears in chapter 2.
- Sister Wren (`cecc664a`) appears in chapter 3. Chapter 4 reveals that she is Livia Hale, so from chapter 4 her page shows as Livia Hale.
- Tomas Hale (`75fbf6e4`) is alive through chapter 2 and dead from chapter 3.
- Captain Fenn (`51177f54`) first appears in chapter 3.
- At chapter 3 there are 8 open mysteries. At chapter 5 all 8 are resolved.

## Driving conventions

- Run site actions through `node $S/drive.mjs --name <feature>-<step> 'STEP' ...`, and run one call at a time.
- Run CLI actions from the repo root with `PATH="$WORK/bin:$PATH"`, so the stub `claude` blocks any real call.
- Prefer roles, accessible names, and ids (`#q`, `#nlab`, `[data-tab]`) over CSS classes or DOM position.
- Each `drive.mjs` call starts with a fresh browser profile. Start every journey with a `goto` that sets `n=`.
- After a CLI command that changes the run, such as an export with corrections, restore the run by removing the change and exporting again.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final screen. Pair `expect` steps before and after the action.
- UI proof is the drive report JSON, plus at least one `aria` snapshot and one `shot` of the resulting state.
- CLI proof is the command, stdout and stderr (`tee` them into `$EVIDENCE`), the exit code, and a read of the files the command wrote.
- Each spoiler claim needs a negative check at an earlier chapter as well as a positive check at the later one.
- Name every artifact after its feature file, such as `spoiler-slider-reveal.png`.
- When a path can't be reached, report the step that was tried and the precondition that failed. Never report a skipped entry point as verified through a different one.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections, in this order:

1. `Sub-features`
2. `How to get to it (user POV)`
3. `Driving it with <harness>`
4. `Gotchas`

## Features

- [Spoiler slider](./spoiler-slider.md): the chapter slider, step buttons, `[` and `]` keys, URL chapter, "Not yet introduced", and identity reveals.
- [Search](./search.md): header search by name or alias, keyboard open with `/` and `Enter`, and spoiler-safe matches.
- [Entry page](./entry-page.md): infobox, dated status, connections, the Facts, Relations, and Mysteries tabs, and quotes.
- [Mysteries](./mysteries.md): open, leads, and resolved filters, the answers, and how they change with the chapter.
- [Graph](./graph.md): the Characters, Connected?, Storyline, Matrix, Factions, and Family tabs, the legend switches, and re-centring.
- [Build and CLI](./build-cli.md): `build --dry-run`, `build`, `verify`, `export --public`, and `corrections.json`.

Not yet mapped: the Chapters list and chapter pages (`p=chapters`, `p=ch:N`), the volume page (`p=v:the-salt-ledger`), category pages (`p=cat:<type>`), the theme toggle, the mobile menu, `annalist eval`, and `review.md`.
