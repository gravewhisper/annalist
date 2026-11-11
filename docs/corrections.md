# Correct a wiki

An LLM wrote the wiki, so some of it will be wrong. Build the wiki, read it, then fix what is left. Choose the fix by who the mistake affects:

- If the mistake could happen in another book, fix it in code with a test. Every later book gets the fix.
- If the mistake belongs to this one book, add it to `corrections.json` in the run directory. It costs no LLM calls.
- If the mistake is small and misleads nobody, leave it.

A correction names an entry by its title or any of its aliases, and can change its type, its page title, and its dated infobox values, or remove a wrong value:

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

An entry's `drop` removes a wrong value: one from a character's `trivia`, `appearance`, or `personality_evidence` list, or a dated infobox value. Each row gives the value's `chapter` and its text as the wiki shows it. Case and spacing do not matter:

```json
{"name": "Mira Vale", "drop": {"trivia": [{"chapter": 12, "value": "Hums when nervous"}], "status": [{"chapter": 40, "value": "dead"}]}}
```

The value leaves every page of the entry, including a page joined into it. A dropped `dead` status also leaves the volume page's deaths. `export` warns about a row that matches no value.

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

## Settle a question

A top-level `questions` list settles the wiki's open questions. Name a question by its id, such as `Q0190-02`, or by its exact text as the wiki shows it.

To answer a question the wiki left open, give the chapter that answers it, the answer, and a quote from that chapter:

```json
{"questions": [{"id": "Q0190-02", "chapter": 230, "answer": "The letter was forged by her steward.", "quotes": ["The steward's hand shook as he sealed it."]}]}
```

The site then shows the question resolved from that chapter, like an answer the pipeline found, and open before it. Your answer replaces any answer the pipeline gave, so a wrong pipeline answer no longer shows at any chapter. An optional `payoff` explains how the answer pays off the setup. An answer with no matching quote, or with a chapter before the question is raised, is skipped with a warning.

To remove a question that is not a real mystery, dismiss it:

```json
{"questions": [{"question": "What will they eat tonight?", "dismiss": true}]}
```

A dismissed question disappears from the mysteries pages and the chapter pages at every chapter, not only from some chapter on. It never was a mystery, so no chapter should list it, and hiding it partway would tell a reader that the story stopped caring about it.

The stages that look for answers, `sweep`, `answers`, and `ending`, treat a question you answered or dismissed as settled and ask the model nothing more about it. `export` warns about an id or text that matches no question.

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
| `questions` | None. `sweep`, `answers`, and `ending` ask about fewer questions. |
| `drop` | The Personality written from evidence you dropped. |

So a run with N corrections asks the model at most a few prompts per corrected page, never for a page no correction names. The `profile` stage does not read corrections: a joined page takes the other page's infobox values from the chapter of the link, and a `type` correction does not build an infobox for an entry the pipeline did not profile.

## Apply your corrections

After an edit, run `annalist build` on the run again. It sees that `corrections.json` changed and reruns `render` and `export`, and also `sweep`, `answers`, and `ending` when the `questions` list changed. `render` asks the model for the pages your corrections changed, so check the cost with `--dry-run` first and pass `--budget`:

```sh
python3 -m annalist build book.epub runs/book --dry-run
python3 -m annalist build book.epub runs/book --budget 1
```

`annalist export runs/book runs/book/site` alone also applies the corrections, but it only reads replies that `render` already has, so a rewritten page shows no summary until the next build. If the pipeline code has changed since the last build, `export` refuses to run until you rebuild. Add `--allow-stale` to export anyway. `export` warns about any correction whose quote is not in its chapter or whose name or id no longer matches an entry or a question.

Later volumes keep your corrections:

- Every build reapplies them, so a rebuild or a new volume does not lose them.
- When `read` reads a new chapter, it shows the reader each correction as a note on that entry, using only values from earlier chapters. A `same_as` note appears only in chapters after its `chapter`. Chapters already read are not read again.

A value that a later rebuild produces for another chapter stays in the history next to your correction.

## Corrections the proofread stage proposes

The `proofread` stage does the review you would do with the book in mind, once per finished volume. Each session gives the model the volume's full text and one slice of the wiki as the pipeline built it at the volume's last chapter. The model replies with rows in the formats above: `entries` rows that join two pages with `same_as`, change a `type`, set a `title`, set `fields`, or `drop` a value; `relations` and `drop_relations` rows; and `questions` rows that answer or dismiss a question. A `type` or `title` row also gives the `chapter` and `quotes` that show it.

Code checks each row the way it checks yours, and more strictly:

- Each chapter the row gives must be in the chapters that the session read. No session reads past its volume's last chapter.
- Each quote must be found in its chapter, and each name or question id must match the wiki.
- A `same_as` row must join two pages that the wiki keeps apart, from a chapter where both have appeared. A `drop` or `drop_relations` row must match a value or a tie that the wiki shows.
- An answer, value, title, or tie wording must use no word that the book first uses after the row's chapter. This stops a row from naming what only a later chapter reveals.

`proofread.json` holds the rows that pass, in the format of `corrections.json`, each marked with its `volume` and wiki `slice`. Its `rejected` list holds every row that failed, with the reason, and its `sessions` list holds one line per call. Code writes this file. Do not edit it. To overrule a row, write your own row in `corrections.json`.

`render` and `export` apply both files through the same path, so a proposed row rewrites page text the way yours does. Where both files change the same thing, your row wins and the proposed row is skipped. The same thing means the same page's `same_as`, `type`, or `title`, the same infobox field at the same chapter, the same tie, or the same question. Your `drop` and `drop_relations` rows also remove a value or a tie that a proposed row added. `sweep`, `answers`, `ending`, and `read` see only your file.

The stage reviews the pipeline's wiki without either file's corrections. So an edit to `corrections.json` never makes it ask the model again. A volume is reviewed again only when a session's prompt changes, which happens when the pipeline changes that volume's wiki.

### Several proofread models

Two models find different mistakes, so `book.json` can name a list for the stage: `"models": {"proofread": ["sonnet", "opus[1m]"]}`. A single name, the default, runs one model as before. With a list, each model runs every session. Each reply is cached under its own model, so a rerun asks neither model again. Every row passes the checks above, and the rows of all models are then combined in the order of the list:

- A row that makes the same change as an earlier model's row counts once. Two rows make the same change when they differ only in their quotes and `why`, so two answers to one question in different words are different changes.
- A row that changes the same thing as an earlier model's row in another way is a conflict. The row of the model listed first is kept, and the other goes to `rejected` with the reason `conflicts with the row from <model>, listed first`. The same thing means what it means above for your own corrections.

Each kept row has a `models` list. Its first model is the one whose quotes and `why` the row keeps, and any model that proposed the same change follows it. Each line of `rejected` and `sessions` names its `model`, and each session counts its `duplicates`.
