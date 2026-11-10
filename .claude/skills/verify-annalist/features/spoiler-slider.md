# Spoiler slider

The reader sets the chapter they have just finished, and every page then shows only what the book has told them by that chapter. Entries from later chapters read "Not yet introduced", and a secret identity appears only from the chapter that reveals it. The chosen chapter lives in the URL and is remembered between visits.

## Sub-features

- `slider-step`: the `‹` and `›` buttons move one chapter and update the number, the chapter title, and the URL.
- `slider-keys`: the `[` and `]` keys step the chapter when focus is not in an input.
- `slider-range`: dragging the range input sets any chapter from 1 to 5.
- `slider-url`: `#n=<chapter>` in a shared link opens the site at that chapter. Values outside 1 to 5 clamp.
- `slider-hidden`: an entry that first appears after the chosen chapter shows "Not yet introduced".
- `slider-reveal`: a page merged by a reveal keeps its old name before the reveal chapter and shows the revealed name from that chapter on.
- `slider-counts`: home-page counts (entries, facts, open mysteries) grow with the chapter.

## How to get to it (user POV)

- The header shows "I'm on chapter" with the `‹` button, the number, the `›` button, and a range slider, followed by the chapter title.
- Press `[` or `]` anywhere outside the search box.
- Open a link that carries `#n=…`.

## Driving it with drive.mjs

Preconditions:

- Baseline from `README.md`, with doctor `ok`.

Steps:

- **Hidden before first appearance.** Open Captain Fenn at chapter 2. Run `node $S/drive.mjs --name spoiler-slider-hidden 'goto|#n=2&p=e%3A51177f54' 'expect|#main|Not yet introduced' 'absent|#main h1|Captain Fenn'`. The page reads "Not yet introduced" and gives no name heading.
- **Step forward reveals it.** In the same call, add `'click|role=button[name="Next chapter"]' 'expect|#nlab|3' 'expect|#main h1|Captain Fenn' 'hash'`. The hash becomes `#n=3&p=e%3A51177f54`.
- **Identity reveal.** Run `node $S/drive.mjs --name spoiler-slider-reveal 'goto|#n=3&p=e%3Acecc664a' 'expect|#main h1|Sister Wren' 'absent|#main|Livia' 'aria|spoiler-slider-reveal-ch3' 'click|role=button[name="Next chapter"]' 'expect|#nlab|4' 'expect|#ctitle|Two Names' 'expect|#main h1|Livia Hale' 'expect|.infobox|Sister Wren' 'aria|spoiler-slider-reveal-ch4' 'shot|spoiler-slider-reveal-ch4'`. At chapter 3 the page is Sister Wren and does not mention Livia. At chapter 4 the page is Livia Hale, with Sister Wren as an alias.
- **Keys.** Run `node $S/drive.mjs --name spoiler-slider-keys 'goto|#n=2&p=home' 'press|]' 'expect|#nlab|3' 'hash' 'press|[' 'press|[' 'expect|#nlab|1'`. Each key press moves one chapter, and the hash follows.
- **Counts grow.** Run `node $S/drive.mjs --name spoiler-slider-counts 'goto|#n=1&p=home' 'text|.stats' 'goto|#n=5&p=home' 'text|.stats'`. The chapter-5 stats show more entries and facts than the chapter-1 stats, and 0 open mysteries.
- **Range input.** Run `node $S/drive.mjs --name spoiler-slider-range 'goto|#n=1&p=home' 'fill|#n|4' 'expect|#nlab|4' 'expect|#ctitle|Two Names' 'hash'`. The hash becomes `#n=4&p=home`.
- **Clamp.** Run `node $S/drive.mjs --name spoiler-slider-clamp 'goto|#n=99&p=home' 'expect|#nlab|5'`.

## Gotchas

- `press|]` does nothing while focus is in `#q`. Run a `goto` or click the page body first.
- Within one `drive.mjs` call, a `goto` without `n=` reuses the last chapter, which is stored in `localStorage`. Always pass `n=`.
- The chapter-1 home page shows a first-visit note ("Set the slider…") until the chapter changes. That is expected.
- The ids in this file come from the mini build. If "Not yet introduced" appears at chapter 5, the ids have changed. Read them again as `SKILL.md` describes.
