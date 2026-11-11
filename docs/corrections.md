# Correct a wiki

An LLM wrote the wiki, so some of it will be wrong. Build the wiki, read it, then fix what is left. Choose the fix by who the mistake affects:

- If the mistake could happen in another book, fix it in code with a test. Every later book gets the fix.
- If the mistake belongs to this one book, add it to `corrections.json` in the run directory. It costs no LLM calls.
- If the mistake is small and misleads nobody, leave it.

A correction names an entry by its title or any of its aliases, and can change its type, its page title, and its dated infobox values:

```json
{
  "entries": [
    {"name": "Northmarch", "type": "place"},
    {"name": "The Veiled Woman", "title": "Mira Vale", "title_chapter": 90},
    {"name": "Mira Vale", "fields": {"status": [
      {"chapter": 120, "value": "revived", "quotes": ["She rose from the grave and walked home."]}
    ]}}
  ]
}
```

`title_chapter` is the chapter that reveals the title, and the page keeps its old name before it. Each infobox value needs a quote from its chapter, and the site hides the value until the slider reaches that chapter. A value with no matching quote is skipped with a warning. A value for a chapter that already has one replaces it, and any other value is added to the history. The field names are the ones in a character's infobox, plus the `extra_fields` keys in `book.json`.

An entry merged into another page can take `"known_from": {"chapter": 40, "quotes": ["..."]}`, for when the reader knows the two are one person earlier than the wiki joined them. Two separate pages can be one person, as when a page for "the bespectacled man" is a named character the book never names in that scene. `same_as` joins them:

```json
{"name": "The Grey Stranger", "same_as": "Mira Vale", "chapter": 117, "quotes": ["He pushed his spectacles up, the way Mira's brother always did."]}
```

`chapter` is the chapter from which the reader can tell they are one person. The two stay separate pages before it, so the slider never shows the link early. From that chapter the page named by `name` becomes part of the `same_as` page, as when the wiki joins two names itself: its facts, relations, aliases, and infobox values show on one page. The quote is the clue the reader relies on. It does not need to state the link, but it must be in `chapter`, and a link with no matching quote is skipped with a warning. A `chapter` before either page first appears is also skipped with a warning. There is no way to join two pages without a quote: if you can tell they are one person, some passage told you, and its chapter is the earliest safe chapter for the link.

A top-level `relations` list adds ties the wiki missed:

```json
{"relations": [{"source": "Mira Vale", "target": "Tomas", "type": "secretly loves", "family": "romance", "status": "implied", "chapter": 12, "quotes": ["She kept his letter."]}]}
```

`status` defaults to `stated`, and `family` to `other`. Both of these changes need a quote from their chapter, like an infobox value.

A top-level `drop_relations` list removes a wrong tie. Each row gives the tie's `source`, `target`, `type`, and `chapter` exactly as the wiki has them, and `export` warns about a row that matches nothing.

After an edit, run `python3 -m annalist export runs/book runs/book/site`, which takes a few minutes for a long book. If the pipeline code has changed since the last build, `export` refuses to run until you rebuild. Add `--allow-stale` to apply corrections anyway. `annalist build` also reapplies the file whenever it changes, and `export` warns about any correction whose name no longer matches an entry.

Later volumes keep your corrections:

- Every export reapplies them, so a rebuild or a new volume does not lose them.
- When `read` reads a new chapter, it shows the reader each correction as a note on that entry, using only values from earlier chapters. A `same_as` note appears only in chapters after its `chapter`. Chapters already read are not read again.

Corrections do not change anything the LLM has already written. Page summaries and the later stages' results keep their old text, and a joined page keeps the summary of its `same_as` page. The Markdown wiki under `wiki/` applies only `same_as`, and `annalist build` renders it again when the file changes, with no LLM calls. A value that a later rebuild produces for another chapter stays in the history next to your correction.
