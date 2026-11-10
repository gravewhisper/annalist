# Configure the book in book.json

The `book` stage writes `book.json`. It and `corrections.json` are the only files in a run directory meant for hand edits. For example, no flag sets `complete`. After an edit, the stages that read a changed key rerun on the next build. Changes to `backend`, `models`, `title`, and `theme` do not rerun any stage. The keys are:

- `title` is the book title shown on the site.
- `power_system` describes the book's power or magic system in prose.
- `power_types` lists the kinds of power-system entries the wiki keeps.
- `extra_fields` lists the extra infobox fields for characters, such as a class or a rank.
- `power_keywords` lists words that mark power-system text.
- `timeline_kind` is `linear`, `loop`, or `flashback`. `timeline_note` explains it to the `timelines` stage.
- `ladder` describes the power ladder: `group_type`, `step_type`, `rank`, `direction`, and `note`. Set it to `null` for a book without one.
- `complete` marks the book as finished. Only then does the `ending` stage run.
- `backend` and `models` choose the backend and the per-step models.
- `public_domain` lets `export --public` keep quotes.
- `theme` sets the site's fonts and colours.

Volume ranges are not in `book.json`. They live in `volumes.json`, which `extract` writes from `--volumes` or from the epub.
