# Configure the book in book.json

The `book` stage writes `book.json`. It and `corrections.json` are the only files in a run directory meant for hand edits. For example, no flag sets `complete`. After an edit, the stages that read a changed key rerun on the next build. Changes to `backend`, `models`, `title`, and `theme` do not rerun any stage. The keys are:

- `title` is the book title shown on the site.
- `power_system` describes in prose the order the book's own fields and types belong to: a power or magic system, or else a social, military, or other order. It is empty when the book has none.
- `power_types` lists the book types: the kinds of world entries a fan wiki of the book keeps that no general type covers, such as the powers and ranks of a power system. A book without such entries has none. Each book type names its `parent`, the general type it is a kind of, and a `description`, as in `"protective item": {"parent": "artifact", "description": "a sacred object that wards off evil"}`. The parent is place, organization, artifact, event, creature, or concept, never character or deity: a class of people is an extra field, not a book type. An entry of a book type and an entry of its parent can be one entry, which keeps the book type.
  - A `book.json` written before parents existed maps each type to its description alone. Such a type takes the general type that its last word names, by type name or by label (`protective item` is an artifact, whose label is Item), and concept otherwise. No model is asked, so an old run loads the same way every time at no cost. To change a parent, set it by hand.

- `rank_word` is the book's own word for one rank of its order, such as `circle`, when the book gives each rank a name of its own, as in "Circle 3: Warden". The survey takes it from the material and is asked again until `power_types` holds a type named by it, the rank type, whose entries are the ranks themselves. A character's current rank stays an extra field. It is empty for a book without named ranks.
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
