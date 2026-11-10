# Search

The header search box finds entries by name or alias, as of the chapter on the slider. Results list the display name, the alias that matched, and the type. Choosing a result opens the entry page. A name or alias that the book has not yet given is never matched.

## Sub-features

- `search-name`: typing part of a name lists the matching entries.
- `search-alias`: typing an alias lists the entry under its display name, with the alias in brackets.
- `search-spoiler`: names and aliases from later chapters do not match. A query with nothing to match shows "No matches up to this chapter".
- `search-open`: `Enter` or a click on a result opens that entry and clears the box.
- `search-focus`: pressing `/` outside an input focuses the search box.
- `search-escape`: `Escape` clears the query and closes the results.

## How to get to it (user POV)

- Click the "Search names and aliases" box in the header.
- Press `/` anywhere outside an input.

## Driving it with drive.mjs

Preconditions:

- Baseline from `README.md`, with doctor `ok`.

Steps:

- **No match before first appearance.** Run `node $S/drive.mjs --name search-spoiler 'goto|#n=1&p=home' 'fill|#q|livia' 'expect|#results|No matches up to this chapter'`. Livia first appears in chapter 2.
- **Alias hidden before the reveal.** In the same call, add `'goto|#n=3&p=home' 'fill|#q|wren' 'expect|#results|Sister Wren' 'absent|#results|Livia'`. At chapter 3, "wren" finds only Sister Wren.
- **Alias after the reveal, opened with the keyboard.** Run `node $S/drive.mjs --name search-open 'goto|#n=4&p=home' 'press|/' 'fill|#q|wren' 'expect|#results|Livia Hale (Sister Wren)' 'shot|search-open-results' 'press|Enter' 'expect|#main h1|Livia Hale' 'hash'`. The hash becomes `#n=4&p=e%3Ac7d047a4`, and the box is empty.
- **Click a result.** Run `node $S/drive.mjs --name search-click 'goto|#n=5&p=home' 'fill|#q|oake' 'click|#results [data-res]' 'expect|#main h1|Sabine Oake'`.
- **Escape.** Run `node $S/drive.mjs --name search-escape 'goto|#n=5&p=home' 'fill|#q|tomas' 'wait|#results [data-res]' 'press|Escape' 'count|#results.open'`. The count is `0`.

## Gotchas

- `fill` fires the `input` event that runs the search. Typing with `press` key by key also works, but it is slower.
- `Enter` opens the first result, which is the one marked selected. Matches that start with the query rank first, then the entries with the most facts.
- The results box closes when you click outside `.searchwrap`. A `text|#results` after such a click still returns the old text, so check `count|#results.open` instead.
