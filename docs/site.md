# The site and its spoiler guarantee

The slider in the site header sets the chapter you are on. The site has a home page, chapter pages with synopses, volume pages, a Mysteries page, a category page for each type, and a page for each entry with its profile, facts, relations, and mysteries. A book type's category page sits under its parent's page in the breadcrumbs, and the parent's page lists it under Subcategories once it has an entry. The Factions and Places tabs count a book type of organization or place as one. The Graph page has these tabs:


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
