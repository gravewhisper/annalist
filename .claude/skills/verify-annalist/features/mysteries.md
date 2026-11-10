# Mysteries

The Mysteries page lists the story's own open questions, the ones the book has raised by the chosen chapter. Each question shows the chapter that raised it and a quote. Once the book answers a question, the page shows the answer, the chapter that resolved it, and a quote. Filters split the questions into Open, Leads, and Resolved. An answer never shows before its chapter.

## Sub-features

- `mysteries-open`: the questions raised by the current chapter, grouped by scope (Cliffhangers, and so on).
- `mysteries-filter`: the Open (N), Leads (N), and Resolved (N) links, each kept in the URL as `&m=`.
- `mysteries-answer`: a resolved question shows "Answer · resolved in Ch N", a quote, and "Show how it pays off".
- `mysteries-spoiler`: an answer from chapter 5 is absent at chapter 3.
- `mysteries-sidebar`: the sidebar "Mysteries" count equals the open plus leads count.

## How to get to it (user POV)

- Choose "Mysteries" in the sidebar.
- Open the Mysteries tab on an entry page.

## Driving it with drive.mjs

Preconditions:

- Baseline from `README.md`, with doctor `ok`.

Steps:

- **Open at chapter 3.** Run `node $S/drive.mjs --name mysteries-ch3 'goto|#n=3&p=home' 'click|.side a:has-text("Mysteries")' 'expect|#main h1|Mysteries' 'expect|#main|Open (8)' 'expect|#main|Resolved (0)' 'absent|#main|Answer' 'aria|mysteries-ch3'`.
- **Resolved at chapter 5.** Run `node $S/drive.mjs --name mysteries-ch5 'goto|#n=5&p=mysteries' 'expect|#main|Open (0)' 'click|role=link[name="Resolved (8)"]' 'hash' 'expect|#main|Answer' 'expect|#main|S. Oake drew the master' 'aria|mysteries-ch5-resolved' 'shot|mysteries-ch5-resolved'`. The hash ends `&m=resolved`. The answer to the cut-page question names S. Oake's key.
- **Pay-off disclosure.** Append to the `mysteries-ch5` call: `'click|role=button[name="Show how it pays off"]' 'shot|mysteries-payoff'`.
- **Sidebar count.** Run `node $S/drive.mjs --name mysteries-sidebar 'goto|#n=3&p=home' 'expect|.side a:has-text("Mysteries")|8' 'goto|#n=5&p=home' 'expect|.side a:has-text("Mysteries")|0'`.

## Gotchas

- The scripted mini replies resolve every question by chapter 5, so the Leads filter is always `(0)` here. A leads journey needs a different fake script, so report it as not covered.
- The "open mysteries" number on the home page is a plain stat, not a link.
- The scope headings ("Cliffhangers (8)") are buttons that collapse the group. Clicking one hides its questions.
