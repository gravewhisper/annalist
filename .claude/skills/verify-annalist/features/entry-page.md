# Entry page

Each character, place, organization, and artifact has a page. The page has a lede, an infobox with dated fields (status, age, affiliation, and so on), a Connections list grouped by kind, and three tabs: Facts (each fact with a "Show quote" disclosure), Relations, and Mysteries. Every value shows only from the chapter that states it.

## Sub-features

- `entry-infobox`: type, aliases, dated fields, first and last seen, and the fact count, as of the slider.
- `entry-status`: a status that changes in the story, such as alive to dead, shows the value for the current chapter.
- `entry-connections`: grouped ties (Close, Allies, Belonging, Things & places, and so on), with "since ch N", plus links to the graph and the path finder.
- `entry-tabs`: the Facts, Relations, and Mysteries tabs, each with a count. The tab is kept in the URL as `&tab=`.
- `entry-quotes`: "Show quote" expands the source quote under a fact.
- `entry-links`: names inside text link to their own pages at the same chapter.

## How to get to it (user POV)

- Choose a search result.
- Click a linked name anywhere: a synopsis, a fact, a mystery, a graph "Open page" link.
- Open a category page from the sidebar (Characters, Places, and so on) and choose an entry.

## Driving it with drive.mjs

Preconditions:

- Baseline from `README.md`, with doctor `ok`.

Steps:

- **Status before and after a death.** Run `node $S/drive.mjs --name entry-page-status 'goto|#n=2&p=e%3A75fbf6e4' 'expect|.infobox|Alive' 'absent|.infobox|Dead' 'click|role=button[name="Next chapter"]' 'expect|.infobox|Dead (ch 3)' 'aria|entry-page-status-ch3' 'shot|entry-page-status-ch3'`. Tomas reads Alive at chapter 2 and "Dead (ch 3)" at chapter 3.
- **Tabs.** Run `node $S/drive.mjs --name entry-page-tabs 'goto|#n=5&p=e%3A75fbf6e4' 'click|[data-tab="relations"]' 'hash' 'expect|#main|daughter' 'click|[data-tab="mysteries"]' 'hash' 'click|[data-tab="facts"]' 'expect|#main|Ch 3'`. The hash gains `&tab=relations`, then `&tab=mysteries`, and each tab's list renders.
- **Quote disclosure.** Run `node $S/drive.mjs --name entry-page-quote 'goto|#n=4&p=e%3Ac7d047a4' 'count|blockquote:visible' 'click|role=button[name="Show quote"][expanded=false]' 'count|blockquote:visible' 'count|role=button[expanded=true]' 'shot|entry-page-quote'`. The visible blockquote count goes from 0 to 1, and one disclosure button reports expanded.
- **Linked names.** Run `node $S/drive.mjs --name entry-page-links 'goto|#n=4&p=e%3Ac7d047a4' 'click|#main a:has-text("Sister Agathe")' 'expect|#main h1|Sister Agathe' 'hash'`. The hash is `#n=4&p=e%3A8b02448a`, so the chapter is kept.
- **Connections links.** Run `node $S/drive.mjs --name entry-page-graph-links 'goto|#n=3&p=e%3A75fbf6e4' 'click|role=link[name="Open in the graph"]' 'hash' 'goto|#n=3&p=e%3A75fbf6e4' 'click|role=link[name=/^How is Tomas Hale connected to/]' 'hash'`. The hashes are `#n=3&p=graph%3A75fbf6e4` and `#n=3&p=graph%3Apath%3A75fbf6e4%7E`, which is the path finder with Tomas as the start.
- **Category to entry.** Run `node $S/drive.mjs --name entry-page-from-category 'goto|#n=5&p=home' 'click|.side a:has-text("Characters")' 'expect|#main h1|Characters' 'click|#main a:has-text("Ines Varro")' 'expect|#main h1|Ines Varro'`.

## Gotchas

- Infobox fields that the book never states for an entry are left out, so don't assert that every row is present.
- Every quote is already in the DOM, inside a `hidden` panel. Count `blockquote:visible` or `[aria-expanded=true]`, never plain `blockquote`.
- "Show quote" becomes "Show N quotes" when a fact has several quotes. Match it with `role=button[name=/Show .*quote/]` when you need either form.
- The Connections panel draws small inline SVG chapter bars. Screenshot the element (`shot|name|.egobox`) when only the panel matters.
