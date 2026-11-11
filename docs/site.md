# The site and its spoiler guarantee

The slider in the site header sets the chapter you are on. The site has a home page, chapter pages with synopses, volume pages, a Mysteries page, a category page for each type, and a page for each entry with its profile, facts, relations, and mysteries. A book type's category page sits under its parent's page in the breadcrumbs, and the parent's page lists it under Subcategories once it has an entry. The Factions and Places tabs count a book type of organization or place as one.

A category page shows its entries as a table. Select a column heading to sort by it and select it again to reverse the order. The sort stays in the address while the slider moves. Each type gets the columns its entries have data for: characters show status, affiliation, occupation, first and last seen, and the chapters they are present in; organizations show their members; places show the place they lie in and the people there; ladder steps show their group and rank. The List switch shows each entry's summary instead, and minor mentions stay listed under the table.

The search box matches the names and aliases known by the slider's chapter. It groups the matches by type, puts the group with the best match first, and shows each entry's first chapter. Enter opens the best match. Every search box on the site, including the graph's, uses the same fuzzy matcher. It ignores case, accents, and punctuation, so "dantes" finds "Dantès" and "oneil" finds "O'Neil". It ranks matches in this order:

1. The whole name or alias.
2. The start of the name.
3. The start of a word in the name.
4. Every query word starts a word in the name, in any order ("moretti klein").
5. The query's letters appear in order, first without gaps, then with gaps ("kln mrt").
6. A small typo: one edit for a query of 4 to 7 letters, two edits for 8 or more. A query under 4 letters must match without typos.

A match through an alias shows the alias next to the entry's name. An alias the book has not used yet by the slider's chapter never matches.

A long entry page, one with five or more sections, lists them under its title: the summary, connections, the profile sections, and the Facts, Relations, and Mysteries tabs. A link to a section on another tab opens that tab first.

The Graph page has these tabs:


- Characters shows each character's strongest ties.
- Connected? finds the path between two entries.
- Storyline shows characters against chapters.
- Matrix shows ties between characters as a grid.
- Factions, Power ladder, Family, and Places appear only when the book has data for them.

A Whole book switch next to the tabs shows every entry type at once.

The site never shows anything from a chapter past the slider. Annalist enforces this in four places:

- Every entry, alias, fact, relation, question, and answer records the chapter where the book first shows it. The site hides each one until the slider reaches that chapter. An entry that appears later shows "Not yet introduced".
- Every quote is checked against the text of its chapter. A quote that matches less than 90% is dropped, and a fact or relation with no matching quote is marked as unverified.
- Text that an LLM writes for a page, such as a summary, is generated as of a chapter from facts up to that chapter. A character's History paragraph for a story arc uses only facts and relations from that arc and shows once the slider reaches the arc's last chapter, so the arc in progress shows none. The arc's name comes only from that arc's chapters. A volume still being read gets History for its closed arcs but no volume page until it ends. A merge of two names, such as a secret identity, shows only from the chapter that reveals it.
- `tests/test_asof_leaks.py` runs a full build with a fake backend that copies every word of each prompt into its reply. It then renders every site view and every Markdown page as of each chapter N and fails if one shows a word that the book first uses after chapter N.

The filtering happens in the browser. `site/data/wiki.json` holds everything the build read, and the site hides what is past the slider. The site also links to the chapter text under `site/text/`. To write a site without chapter text, and without quotes unless `book.json` sets `public_domain`, export it with `--public`:

```sh
python3 -m annalist export --public runs/book runs/book/site-public
```

`export` refuses to run when a stage's code changed since the last build. Run `build` again first.

## Light and dark

The button at the right of the header switches between light and dark. In light mode every book gets the same reading surfaces: a warm frame around a softer reading area, white cards, and ink-blue underlined links. A theme in `annalist/themes/` sets the book's fonts and dark palette, but only `accent` and `heading` for light mode. The accent marks the book's identity, such as the header rule, the infobox title band, and the sidebar labels, and is never a link colour. `tests/test_theme_contrast.py` checks every text colour at 4.5:1 and every mark at 3:1.
