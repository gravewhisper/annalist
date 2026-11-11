# Configure the book in book.json

The `book` stage writes `book.json`. It and `corrections.json` are the only files in a run directory meant for hand edits. For example, no flag sets `complete`. After an edit, the stages that read a changed key rerun on the next build. Changes to `backend`, `models`, `title`, and `theme` do not rerun any stage. The keys are:

- `title` is the book title shown on the site.
- `power_system` describes in prose the order the book's own fields and types belong to: a power or magic system, or else a social, military, or other order. It is empty when the book has none.
- `power_types` lists the kinds of world entries a fan wiki of the book keeps that no general type covers, such as the powers and ranks of a power system. A book without such entries has none.
- `extra_fields` lists the extra infobox fields for characters, such as a power class, a cultivation stage, a noble title, a civil-service rank, or a species.
- `power_keywords` lists words that mark a passage about the extra fields or the entries of `power_types`. It is empty only when both are empty.
- `timeline_kind` is `linear`, `loop`, or `flashback`. `timeline_note` explains it to the `timelines` stage.
- `ladder` describes the power ladder in one of two shapes. Set it to `null` for a book without one.
  - A grouped ladder has named groups that each rank their own steps, such as schools with circles: `group_type`, `step_type`, `rank`, `direction`, and `note`.
  - A shared ladder is one series of steps that everyone climbs, such as cultivation realms: `"shape": "shared"`, `step_type`, `rank`, `direction`, and `note`. The `ladders` stage also lists each step's sub-stages in order, such as numbered layers or early, middle and late. Groups such as sects stay ordinary power types.
- `complete` marks the book as finished. Only then does the `ending` stage run.
- `backend` and `models` choose the backend and the per-step models.
- `public_domain` lets `export --public` keep quotes.
- `theme` sets the site's fonts and colours.

Volume ranges are not in `book.json`. They live in `volumes.json`, which `extract` writes from `--volumes` or from the epub.
