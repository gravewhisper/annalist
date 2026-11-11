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

## A correction rewrites the text of the pages it affects

Corrections are part of what the wiki knows. When `render` and `export` load the run, corrections enter with the pipeline's own decisions, such as `merges.json` and `types.json`, each from its chapter. So the page summaries, the summaries as of earlier chapters, History, Personality, the infobox, relations, the Markdown wiki, and the site all reflect them. A joined page's summary and History are written again from the facts of both pages from the chapter of the link.

Before a correction's chapter, nothing reflects it. Each page keeps the text it had before, word for word: a summary as of an earlier chapter is written only from facts of that chapter or before, and a description page keeps its own summaries, History, and Personality up to the chapter of its `same_as` link.

A correction changes only the prompts of the pages it affects, so every other page reuses its cached replies:

| Correction | Prompts that change |
| --- | --- |
| `same_as` or `known_from` | The joined page's summary, its summaries at chapters from the link on, at most one per doubling of its fact count, its History for each finished arc that ends at or after the link, and its Personality when the other page brings personality evidence. |
| `type` | The entry's summaries, since the prompt names the type, and its History when it becomes a character. |
| `relations`, `drop_relations` | The History of both ends for the arc that holds the tie's chapter. |
| `title`, `fields` | None. The title renames the page from `title_chapter`, and field values go into the infobox. |

So a run with N corrections asks the model at most a few prompts per corrected page, never for a page no correction names. The `profile` stage does not read corrections: a joined page takes the other page's infobox values from the chapter of the link, and a `type` correction does not build an infobox for an entry the pipeline did not profile.

## Apply your corrections

After an edit, run `annalist build` on the run again. It sees that `corrections.json` changed and reruns `render` and `export`. `render` asks the model for the pages your corrections changed, so check the cost with `--dry-run` first and pass `--budget`:

```sh
python3 -m annalist build book.epub runs/book --dry-run
python3 -m annalist build book.epub runs/book --budget 1
```

`annalist export runs/book runs/book/site` alone also applies the corrections, but it only reads replies that `render` already has, so a rewritten page shows no summary until the next build. If the pipeline code has changed since the last build, `export` refuses to run until you rebuild. Add `--allow-stale` to export anyway. `export` warns about any correction whose quote is not in its chapter or whose name no longer matches an entry.

Later volumes keep your corrections:

- Every build reapplies them, so a rebuild or a new volume does not lose them.
- When `read` reads a new chapter, it shows the reader each correction as a note on that entry, using only values from earlier chapters. A `same_as` note appears only in chapters after its `chapter`. Chapters already read are not read again.

A value that a later rebuild produces for another chapter stays in the history next to your correction.
