---
name: verify-annalist
description: Prove Annalist behavior end to end without LLM spend. Builds the five-chapter test book (tests/data/mini.epub) with the fake backend, serves the spoiler-safe wiki site on a private port, and drives it in headless Chromium (slider, search, entry pages, mysteries, graph) plus the CLI (build --dry-run, verify, export, corrections). Use after changing annalist/site/ or any pipeline stage, before claiming a UI or build change works, or when asked to screenshot or check the wiki.
---

# Verify Annalist

Annalist turns an epub into a static wiki site. Users touch two surfaces:

1. **The site** (primary): `site/index.html` + `app.js`, served over HTTP, with a chapter slider that hides everything past the chosen chapter. Driven here with Playwright.
2. **The CLI**: `python3 -m annalist build|verify|export|...`. Driven here with plain shell commands.

Everything below runs on the fake backend against `tests/data/mini.epub` ("The Salt Ledger", 5 chapters). It costs $0 and makes no `claude` calls: `launch.sh` puts a stub `claude` that exits 1 first on `PATH`, so a call that escapes the fake backend fails loudly instead of spending.

All paths are relative to the repo root. Scripts live in `.claude/skills/verify-annalist/scripts/`; below, `$S` means that folder:

```sh
S=.claude/skills/verify-annalist/scripts
```

## Repo rules that bind every run

- Keep evidence under `runs/` (git-ignored), never only in `/tmp`. This skill writes to `runs/verify-annalist/<RUN_ID>/evidence/`.
- Run one `drive.mjs` at a time. Do not start a local model server; this skill needs none.
- **Browser.** `drive.mjs` uses only the lightweight `chrome-headless-shell` and exits 2 if it is missing.
- Never write into a real run. This skill only touches its own `runs/verify-annalist/<RUN_ID>/`.
- A wiki problem found here is fixed in code with a test, not by editing run data.

## Launch

```sh
$S/launch.sh [RUN_ID] [--epub PATH] [--no-serve]
```

- Creates `runs/verify-annalist/<RUN_ID>/` (default RUN_ID is a timestamp) and points `runs/verify-annalist/latest` at it.
- `seed.py` writes `work/run/script.json` (the scripted replies from `tests/test_build.build_script`, the same ones the test suite uses) and `work/run/book.json` with `{"backend": {"name": "fake", "script": "script.json"}}`.
- Runs `python3 -m annalist build tests/data/mini.epub work/run --yes`, with every `ANNALIST_*` variable unset. The log goes to `evidence/build.log`. This takes about 1 second.
- Serves `work/run/site` with `python3 -m http.server --bind 127.0.0.1` on a free port.
- Writes `state.env` with `RUN_ID ROOT R WORK RUN EVIDENCE BUILD_SHA PORT PID BASE`. Load it with `. runs/verify-annalist/latest/state.env`.
- Prints the run dir and exits 0 only when `BASE/data/wiki.json` answers. Exits 2 if the build failed (tail of `build.log` on stderr) and 3 if the server never answered.

Ready means the site answers, and the first `goto` step in `drive.mjs` waits until the app has rendered (`#nlab` filled). A served `wiki.json` alone does not prove the app loaded. The app can still fail in JS, and `drive.mjs` reports that under `errors`.

`--epub` builds another book, but the fake script only has replies for the mini book. Any other epub fails at the first unscripted call. Leave it on the default unless you bring your own script.

Several instances can run side by side: each one has its own RUN_ID directory and its own free port. Every script defaults to `runs/verify-annalist/latest`, the most recent launch. With more than one instance, pass the run dir explicitly: `doctor.sh runs/verify-annalist/<RUN_ID>`, `drive.mjs --run runs/verify-annalist/<RUN_ID>`, and `cleanup.sh runs/verify-annalist/<RUN_ID>`. Drive only one at a time, because of the memory rule.

## Doctor

Run this first, and again whenever anything looks off. It only reads.

```sh
$S/doctor.sh [RUN_DIR]        # default runs/verify-annalist/latest
```

It checks that:

- the site was built;
- the PID in `state.env` is our `http.server` serving our site dir on our port;
- `ss` shows that PID owns the port;
- `wiki.json` is the 5-chapter mini book;
- the served `app.js`, `app.css`, and `index.html` are byte-identical to `annalist/site/`;
- every row in `calls.jsonl` used the fake backend at no cost;
- at least 8 GB of memory is free.

It also warns when HEAD or uncommitted changes under `annalist/` differ from the build. Exits 1 on any `FAIL`.

## Drive

### Site: `drive.mjs`

Each call launches one headless shell, runs the steps in order in one page, writes `evidence/<name>.json`, prints it, and exits 1 if any step failed or the page logged a JS error.

```sh
node $S/drive.mjs [--run DIR] [--name REPORT] [--theme light|dark] [--size 1360x900] 'STEP' 'STEP' ...
```

Each step is one argument, with fields split on `|`:

| Step | Does |
| --- | --- |
| `goto\|#n=3&p=home` | full page load of `BASE/index.html#...`, then waits for render |
| `click\|SELECTOR` | clicks the first match, then records `location.hash` |
| `fill\|SELECTOR\|TEXT` | types into an input; fires `input`, so search runs |
| `press\|KEY` | keyboard press, such as `Enter`, `Escape`, `]`, `[`, `/` |
| `wait\|SELECTOR` | waits until visible (5 s) |
| `expect\|SELECTOR\|TEXT` | fails unless the matched text contains TEXT; with empty TEXT, fails unless the element exists |
| `absent\|SELECTOR\|TEXT` | fails if the matched text contains TEXT; with empty TEXT, fails if the element exists |
| `text\|SELECTOR` / `count\|SELECTOR` / `hash` | records a value in the report |
| `aria\|NAME[\|SELECTOR]` | writes `evidence/NAME.aria.yml` (default `#main`) |
| `shot\|NAME[\|SELECTOR]` | writes `evidence/NAME.png` (full page, or one element) |

Selectors are Playwright selectors. Prefer these stable handles, in this order:

- **Routes.** The page lives in the hash: `#n=<chapter>&p=<page>[&tab=<tab>][&m=<filter>]`. The pages are:
  - `home`
  - `chapters` and `ch:<n>`
  - `v:the-salt-ledger`
  - `mysteries`, filtered with `&m=open`, `&m=partial`, or `&m=resolved`
  - `cat:<type>`
  - `e:<entity id>`, with `&tab=facts`, `&tab=relations`, or `&tab=mysteries`
  - `graph`, plus `graph:path`, `graph:story`, `graph:matrix`, `graph:factions`, `graph:family`

  URL-encode `:` as `%3A`.
- **Header ids and labels.**
  - `#q` (searchbox "Search"), `#results [data-res]` (search hits), `#nlab` (current chapter number), `#n` (range slider), `#ctitle` (chapter title).
  - `role=button[name="Previous chapter"]` and `role=button[name="Next chapter"]`.
  - `role=button[name="Toggle light and dark theme"]` and `role=button[name="Menu"]`.
- **Sidebar.** `.side a` links: `Home`, `Chapters`, `Mysteries`, `Graph`, and one per volume and category.
- **Main.** `#main h1` (page title), `.infobox` (entry infobox table), `[data-tab]` (entry tabs), `[data-go]` (in-app links).
- **Graph.** `role=switch[name=...]`, `role=button[name="<Name>, character"]`, `role=searchbox[name="Centre on an entry"]`, and `role=complementary[name="Legend and filters"]`.

Mini-book ids, for direct `goto`:

| Entry | id | first chapter |
| --- | --- | --- |
| Tomas Hale | `75fbf6e4` | 1, dies in 3 |
| Ines Varro | `4e4d0079` | 1 |
| Bram Ostrow | `cd4d650f` | 1 |
| Sabine Oake, also "Master Oake" | `061039eb` | 1 |
| Livia Hale | `c7d047a4` | 2; revealed as Sister Wren in 4 |
| Sister Wren | `cecc664a` | 3; shows as Livia Hale from 4 |
| Captain Fenn | `51177f54` | 3 |
| Salt Ledger | `a4de7284` | 1 |

The ids are digests of the build. If they stop resolving, which shows as "Not yet introduced" at chapter 5, read them again with `python3 -c "import json;[print(e['id'],e['name']) for e in json.load(open('$RUN/site/data/wiki.json'))['entities']]"`.

### CLI

Run commands from the repo root with the run's stub first on `PATH`, so nothing can reach the real `claude`:

```sh
. runs/verify-annalist/latest/state.env
export PATH="$WORK/bin:$PATH"
python3 -m annalist verify "$RUN"
```

See `features/build-cli.md` for the recipes.

## Evidence

Everything goes to `runs/verify-annalist/<RUN_ID>/evidence/`:

- `build.log`
- `<name>.json`: per drive, every step with ok, error, recorded text and hash, plus page `errors` and `build` SHA
- `*.png`
- `*.aria.yml`
- any CLI transcript you `tee` there, such as `cli-verify.txt`

Proof standards:

- **Drive the real user path.** Use the slider buttons, the search box, links, and tabs. A `goto` with a hash is a fair entry point, because users share and bookmark those URLs. Don't call app functions with `page.evaluate`, and don't edit `wiki.json` to set up a state.
- **Capture the action and the result.** Record the `expect` before and after, such as the chapter-3 title and the chapter-4 title. One final screenshot is not enough.
- **Check the side effect too.** For the CLI, also inspect the files written: `wiki.json` keys, `site/text/`, `calls.jsonl`. For the site, record the hash change and the persisted chapter.
- **Every spoiler claim needs a negative check.** Use an `absent` or `expect ...|Not yet introduced` at a chapter before the fact appears, as well as a positive check after it.
- **Don't trust a dry run by its name.** `build --dry-run` is proven to write nothing by `ls`-ing the target dir afterwards (see `features/build-cli.md`).
- **The fake backend is a legitimate boundary.** It replaces the LLM at the backend layer that production also goes through. Its replies are canned, so this skill proves pipeline plumbing and site behavior, not extraction quality. Quality is `annalist eval`, which costs money.

## Cleanup

```sh
$S/cleanup.sh [RUN_DIR]       # default runs/verify-annalist/latest
```

- Kills only the PID in `state.env`, and only if its command line is our `http.server` on our site dir.
- Deletes `work/`: the build, the stub, and the server log.
- Strips `PID`, `PORT`, and `BASE` from `state.env`.
- Keeps `evidence/` and lists it.
- Refuses any dir outside `runs/verify-annalist/`.

Never `pkill python` or kill by port. The user may be serving another site from a real run.

## Gotchas

- **`build` copies `annalist/site/*` into `site/`.** After editing `app.js`, `app.css`, or `index.html`, the served copy is stale. Doctor flags this. Refresh it with `python3 -m annalist export "$RUN" "$RUN/site"`, using the stub `PATH`, which takes about 1 s. You can also relaunch. Either way, drive again.
- **Pipeline code changes need a rebuild, not just an export.** `export` refuses to run when a stage's code changed since the last build. Relaunch to rebuild.
- **The slider chapter persists in `localStorage`.** Every `drive.mjs` call is a fresh browser profile, so state never carries between calls. Within one call it does: a `goto` without `n=` uses the last chapter you set.
- **First-visit note.** At chapter 1, the home page shows a "Set the slider…" note until the slider moves. Don't mistake it for an error.
- **`]` and `[` step the chapter only when focus is outside an input.** `/` focuses search.
- **`#n` is clamped.** Values outside 1 to 5 snap to 1 or 5.
- **Opening `index.html` as a `file://` URL fails.** `fetch` can't load `data/wiki.json` that way. Always use `BASE`.
- **A `goto` timeout means the app never rendered.** That is usually a JS error during `load()` (see `errors`) or a missing `wiki.json`. Follow it with `text|#main` to read the app's own error message.

## Feature map

`features/README.md` indexes one recipe per user-facing feature. A proof of a feature covers every entry point its file lists. Keep the map current with `/pstack:maintain-verification-skill`.
