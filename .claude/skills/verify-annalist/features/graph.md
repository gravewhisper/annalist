# Graph

The Graph page draws ties between entries as of the chosen chapter. It has these tabs:

- **Characters**: an orbit around one centre entry.
- **Connected?**: the path between two entries.
- **Storyline**: characters against chapters.
- **Matrix**: a grid of ties.
- **Factions** and **Family**: shown only when the book has the data.

A legend with switches filters the entry types and the relation kinds. A "Whole book" switch shows every type at once. Entries and ties appear only from their chapter.

## Sub-features

- `graph-tabs`: each tab opens its view, and the URL becomes `p=graph:<view>`.
- `graph-centre`: selecting a node, or using "Centre on an entry", re-centres the Characters orbit. "Open page" goes to the entry.
- `graph-filters`: the People, Groups, Places, and Things type switches, and the Close, Allies, Conflict, Belonging, and Things & places line switches.
- `graph-whole-book`: the switch shows all entry types.
- `graph-spoiler`: nodes for entries that appear later are absent at earlier chapters.
- `graph-path`: Connected? finds a chain between two chosen entries.

## How to get to it (user POV)

- Choose "Graph" in the sidebar.
- On an entry page, choose "Open in the graph" or "How is X connected to…" under Connections.

## Driving it with drive.mjs

Preconditions:

- Baseline from `README.md`, with doctor `ok`.

Steps:

- **Tabs present.** Run `node $S/drive.mjs --name graph-tabs 'goto|#n=5&p=graph' 'aria|graph-ch5' 'expect|role=tablist|Storyline' 'click|role=tablist >> role=link[name="Storyline"]' 'hash' 'shot|graph-storyline' 'click|role=tablist >> role=link[name="Matrix"]' 'hash' 'shot|graph-matrix'`. The hashes are `p=graph%3Astory` and `p=graph%3Amatrix`.
- **Centre on a node.** Run `node $S/drive.mjs --name graph-centre 'goto|#n=5&p=graph' 'absent|role=complementary[name="Legend and filters"]|Ines Varro' 'click|role=button[name="Ines Varro, character"]' 'expect|role=complementary[name="Legend and filters"]|Ines Varro' 'shot|graph-centre-ines'`. Before the click, the legend does not name Ines. After it, the legend's detail block names her as the centre.
- **Spoiler.** Run `node $S/drive.mjs --name graph-spoiler 'goto|#n=2&p=graph' 'absent|#main|Captain Fenn' 'goto|#n=3&p=graph' 'count|role=button[name="Captain Fenn, character"]'`. Fenn is absent at chapter 2. At chapter 3 he appears only if he is tied to the centre, so record the count rather than assert it.
- **Connected? path finder.** Run `node $S/drive.mjs --name graph-path 'goto|#n=5&p=graph%3Apath' 'fill|role=searchbox[name="From an entry"]|ines' 'press|Enter' 'fill|role=searchbox[name="To another entry"]|livia' 'press|Enter' 'hash' 'expect|#main|Ines Varro and Livia Hale are 2 steps apart by chapter 5' 'count|role=group[name=/^Shortest chains between Ines Varro and Livia Hale/]' 'shot|graph-path'`. The hash becomes `p=graph%3Apath%3A4e4d0079%7Ec7d047a4`, which is shareable.
- **Whole book.** Run `node $S/drive.mjs --name graph-whole-book 'goto|#n=5&p=graph' 'count|#main svg [data-gn]' 'click|role=switch[name="Whole book"]' 'hash' 'count|role=switch[name="Whole book"][checked=true]' 'count|#main svg [data-gn]' 'shot|graph-whole-book'`. The hash becomes `p=graph%3Aall`, the switch reports checked, and the node count rises from 4 to 6.
- **Type filter.** Centre on Livia, who is tied to a place, then turn on Places. Run `node $S/drive.mjs --name graph-filter 'goto|#n=5&p=graph%3Ac7d047a4' 'absent|role=button[name="Brannoc Abbey, place"]|' 'click|role=switch[name=/^Places/]' 'count|role=switch[name=/^Places/][checked=true]' 'expect|role=button[name="Brannoc Abbey, place"]|' 'aria|graph-filter-places' 'shot|graph-filter-places'`. The Brannoc Abbey node is absent before the click and present after it, and the switch reports checked.

## Gotchas

- The default centre is the main character as of the chapter. At chapter 5 in the mini book it is Bram Ostrow, so don't hard-code it in assertions.
- The Characters view shows the 20 strongest ties around the centre. Entries without a tie to the centre are not drawn even when they are visible.
- `p=graph:<entity id>` opens the Characters view centred on that entry. Bram, the default centre at chapter 5, has no place ties, so a type filter shows nothing new around him.
- Graph nodes are SVG `g` elements with `role=button`. Clicking one centres it. Pressing `O` or double-clicking opens the entry page.
- Views animate when the chapter changes. Add `wait` on a node, or take the screenshot after a `count`, rather than right after a slider step.
