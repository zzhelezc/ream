# ream

One page on an infinite canvas. Write on it; when it fills, the next page
slides in. Images and PDFs sit on the canvas around it. Whatever you drag
onto the page goes out with the PDF, and the export can be worn down with the
textures from your Texturelabs Distressor plugin.

There is no interface beyond the page. **Tab** opens a command palette, and
everything else is in there. Two small panels of sliders are there for things you
dial in by eye: **distress** (`⌘D`) and **page** (`⌘L`). Both can be open at
once. **Distress view** (`⇧⌘D`) lets you write on the distressed page itself.

A sibling of `stik`: the same infinite canvas, Tab palette and uv install.

## Install

```bash
uv tool install .
```

That puts `ream` on your PATH. After changing the code:

```bash
uv tool install --reinstall .
```

## Run it

```bash
ream
```

```bash
ream notes.ream refs/ scan.pdf photo.jpg
```

With no arguments it reopens whatever you had open last. Images, PDFs and
folders given on the command line land on the canvas, and a `.ream` file is
opened. From a checkout, `uv run ream` works without installing.

The end-to-end checks drive the real window headless:

```bash
QT_QPA_PLATFORM=offscreen uv run python tests/test_core.py
```

They use a throwaway home folder (`REAM_HOME`), never yours.

## The page

There is one sheet, centred on the canvas, and only ever one page on screen.

- **Typing past the foot of a page** moves the words on to the next one. The
  pages slide up and the view follows the caret.
- **`⌘←` and `⌘→` turn pages.** The caret goes to the first line of the new
  page, so you can carry on writing there.
- **Scrolling never turns a page.** Over the page it pans, the same as
  anywhere else.
- **Three views:** `⌘1` one page, `⌘2` a spread, `⌘3` all pages (below).
- **A blank page** waits after the last one. Click on it to start writing
  there; the page breaks go in for you.
- **New page** (`⌘↵`) breaks the page at the caret.
- The page count sits under the page in grey: `02 / 05`.

### Writing anywhere

**`⌘`+click** anywhere starts a block of text right there, overlapping the
page's own words or anything else.

- **On the page** it is pinned, like an image. It wraps at the right margin
  (or at the page edge when you click in the margin), scrolls with its page
  and goes out with the PDF, distress included.
- **On the canvas** it is one line that grows, a note to yourself that is
  never exported. Drag it onto the page to pin it.
- **Finishing:** `Esc` or a click elsewhere. An empty block disappears
  without a trace, and `⌘Z` steps back through its typing and then the block
  itself.
- **Editing:** **double-click** a block, or **`⌘`+click** it, to write in it
  again, with the caret where you clicked.
- **As an object:** a plain click selects it, so it moves, nudges, rotates
  (about its first letter) and deletes like an image. The corner square
  re-wraps it to a new width.

Blocks always take the document's face, size, line height and paragraph
spacing, and change with them.

### Spread and all pages

| Key | View |
| --- | --- |
| `⌘1` | one page (the default) |
| `⌘2` | a **spread**: two facing pages, like an open book |
| `⌘3` | **all pages** in a grid, sized to fit the window |

Pressing the key of the view you are in goes back to one page. Each view frames
itself when you switch, and `⌘0` re-frames it.

- **Spread.** Pages pair the way a book's do: the first page alone on the
  right, then 2 | 3, 4 | 5 and so on. `⌘←` and `⌘→` turn a whole spread.
- **All pages.** Every page is numbered underneath; the live one is marked
  with a dot.
- **You keep writing in every view.** The page holding the caret is the live
  one. Click any other page and it becomes live, with the caret where you
  clicked. Typing past the foot of a page carries on into the next one,
  wherever it sits.
- **Pinning and ⌘-click text** work on any page you can see. Drop an image
  on the facing page and it pins to that page.
- **The other pages** are drawn straight from the document, so they are sharp
  at any zoom. In distress view they are distressed too, the ones in sight,
  and they re-render after a change.
- **Exports** are the same whichever view you are in.

The text is plain: one face, one size, one line height and one paragraph
spacing for the whole document, set from the page panel or the palette. The default face is the first installed of
IBM Plex Mono, Iosevka, JetBrains Mono, Roboto Mono, Space Mono, Departure
Mono, SF Mono or Menlo, at 9 pt with 150% leading on A4.

## The canvas

- **Moving around:** scrolling pans, over the page or off it, and so does
  dragging the empty canvas. Pinch or `⌘`+scroll zooms at the pointer, and `Alt`+scroll
  pans anywhere. `Space`+drag and middle-drag pan too, while an image is
  selected.
- **Zoom shortcuts:** `⌘0` fits the page (or the spread, or all pages),
  `⇧⌘0` fits everything. **actual size** in the palette goes to 100%.
- **Adding images and PDFs:** drop them, paste them (`⌘V`), browse with `⌘O`,
  or double-click the empty canvas. They land where you drop or click. Phone
  photos come in the right way up. Each page of a PDF becomes its own image,
  laid out in a row.

### Pinning to the page

Drag an image so **its middle is over the page** and it is pinned to that
page. A heavy outline round the page while you drag says it will pin. A pinned
image:

- scrolls with its page and is clipped to it;
- goes out with the PDF (anything still on the canvas does not);
- unpins when dragged off again (or **unpin from page** in the palette).

Dropping or pasting straight onto the page pins at once, scaled down to the
text width if it is wider.

- **Selecting and moving:** click to select, `Shift`+click adds, drag moves,
  and the arrows nudge (`Shift` for 10 pt). The corner square resizes about
  the middle, keeping the proportions.
- **Rotating:** drag the round knob above a selected image (`Shift` snaps to
  15°). `[` and `]` turn it 15° (`Shift` for 1°). In the palette,
  `rotate 30` sets an angle, and **straighten** puts it level. Images export
  turned. `⌫` deletes, `⌘C` copies the image, `Esc` goes back to
  writing.
- **Images behind the words:** **send behind text** puts a pinned image
  behind the words, so they print over it. `Alt`+click reaches it there.
- **Undo** (`⌘Z` / `⇧⌘Z`) is one history for words and images together.

## Command palette

Press **Tab** anywhere (or right-click). The palette opens at the pointer as a
slip of paper. Its grey caption gives the document, the page, the word count
and the distress style. Type to filter, `Enter` runs the command, and `Esc`
closes it. Matching is forgiving, and the commands you used last come first.

**Typing a number sets a value:**

| Type | Sets |
| --- | --- |
| `page 3` | goes to page 3 |
| `size 10` | text size, pt |
| `line 140` | line height, % |
| `para 6` | space after each paragraph, pt |
| `ink 70`, `ink 130` | ink darkness, %: below 100 fades, above 100 strikes heavier |
| `margin 72` | left and right margins, pt |
| `head 80` | top and bottom margins, pt |
| `rotate 30` | the selected image's angle |
| `canvas #333`, `paper #f4efe2` | canvas or paper colour |
| `dpi 600` | export resolution |
| `edge 20`, `fade 40`, … | any distress control (below) |

Choosing `edge` (or any value) from the list types `edge ` for you, so just add
the number.

**Everything else:**

| Group | Commands |
| --- | --- |
| Panels | distress panel (`⌘D`), page panel (`⌘L`) |
| Export | export pdf (`⌘E`), export pdf · clean (`⇧⌘E`), export png pages |
| Distress | distress view (`⇧⌘D`), distress on/off, style · …, fade texture · …, reset distress |
| Page and type | page size · a4 / letter / a5 / square, paper · white / cream / newsprint / bond, paper colour…, canvas colour…, font · … |
| Pages | new page, next page (`⌘→`), previous page (`⌘←`), go to page |
| Views | one page (`⌘1`), spread (`⌘2`), all pages (`⌘3`), fit page (`⌘0`) |
| Look | theme · paper / white / night |
| Selection (images and text blocks) | rotate 90° right / left, rotate, straighten, delete, bring to front, send behind text, unpin from page, fit to text width, natural size |
| File | new document (`⌘N`), open… (`⇧⌘O`), save (`⌘S`), save as… (`⇧⌘S`), show drafts, word count, quit |

## Panels

A panel is a slip of paper floating top right over the canvas. Both can be
open at once; the second opens beside the first. Drag either by its caption;
close it with `Esc`, its ×, or the same shortcut. Double-click a
slider's name to put it back to its default. Each slider drag undoes as one
step.

**Page panel** (`⌘L`):

- **type:** font (‹ › or click for the list; every Iosevka family you have
  installed is offered too: Iosevka, Term, Slab, Term Slab, Aile, Etoile), size, line height, paragraph
  spacing and ink darkness;
- **page:** format, side margins, top and bottom margins, and paper colour
  (swatches, or **+** for any colour);
- **canvas:** the background colour (swatches or **+**), and the edge style
  (paper / white / night) on its own, without changing the colour.

The canvas colour is remembered between runs. Paper colour and layout are
saved with the document.

**Distress panel** (`⌘D`):

- opening it turns on the distress view (below), and closing it turns the
  view off again, unless you had it on already;
- **see** switches the page between distressed and clean;
- **export** chooses whether the PDF is distressed or clean;
- **ink** sets the ink darkness;
- every slider and chooser re-renders on a background thread, at lower
  resolution while a slider is held and full resolution on release, so the
  sliders never stall;
- below the controls are the export dpi, **reset**, **new seed** and
  **export pdf**.

### Writing on the distressed page

**Distress view** (`⇧⌘D`, or **see · distressed** in the panel) shows the page
as it will export, and you keep writing on it.

- Every change re-renders it by itself: typing, spacing, margins, ink, images,
  text blocks.
- It renders only the part of the page in sight, at your screen's own
  resolution (zoom × Retina), so it is as sharp as the page itself.
  Zooming or panning sharpens and re-crops it a moment after you stop.
- While you type or hold a slider, it renders at 60% of that resolution to keep
  up, then sharpens when you pause.
- The texture sits on the same spot of the page at every resolution, so what
  you see is exactly what the 300 dpi export prints.
- Your caret and selection are drawn on top. New letters appear distressed a
  moment after you type them.
- It steps aside while pages slide and comes back when they stop.
- It stays on until you turn it off, and is remembered between runs.

### Ink darkness

`ink` (page panel, distress panel, or `ink 70` in the palette) runs from 5% to
150%:

- **100%** is solid black.
- **Below 100%** the ink fades toward the paper colour, like a worn ribbon.
- **Above 100%** the type strikes heavier, from regular at 100% to bold at
  150%. IBM Plex Mono's weights share one width, so nothing reflows. The
  distressed ink also packs denser, so worn edges and fade fill back in. Use
  it when the distress eats too much.

It is saved with the document and applies to clean and distressed exports
alike. Images are not changed.

## Distress

ream reads the textures straight out of your installed **Texturelabs
Distressor** (the Photoshop UXP plugin). It finds the plugin under
`~/Library/Application Support/Adobe/UXP/Plugins/External`, pulls the pattern
out of each of its PSDs (with psd-tools) and caches them as PNGs in
`~/Library/Caches/ream/distressor/`. That happens once, in the background, at
the first launch. Point `REAM_DISTRESSOR` at the plugin folder if it lives
somewhere else. Without the plugin, procedural noise stands in, so everything
still works.

The controls are the panel's own, with the same ranges and defaults:

| Control | Range | Default | Does |
| --- | --- | --- | --- |
| style | 14 looks | rough | stamp, copier, halftone, grainy, inked, news, perlin, press, rolled, spray, vintage, weather, block |
| scale | 25–300 | 100 | texture size, % |
| edge | 0–100 | 10 | how far the texture eats into the edge of the ink |
| bleed | −20–20 | 0 | ink spread: positive fattens, negative starves |
| blur | 0–100 | 50 | melts the shape before it is cut, rounding corners |
| inner | 0–100 | 50 | specks knocked out of solid ink |
| refill | 0–100 | 25 | how much ink comes back into those specks |
| fade | 0–100 | 25 | uneven wear across the ink, from the fade texture |
| fade texture | 5 | grain | grain, dust, grunge, paint, print |
| seed | 0–25 | 0 | where the textures land |

ream adds two controls of its own:

| Control | Range | Default | Does |
| --- | --- | --- | --- |
| misfire | 0–100 | 0 | the type wobbles off its line, like a bad platen |
| paper | 0–100 | 0 | the sheet itself picks up the fade texture and warms |

**How it works.** Each page is rendered as an ink layer (the words and the
pinned images) at the export dpi. The layer's alpha becomes a signed distance
field: positive inside the ink, negative outside. The edge texture moves the
boundary in where it is light and out where it is dark, so edges go ragged
rather than just thin. Bleed shifts the boundary, blur melts it, and it is cut
again with an antialiased step. The inner and fade textures then thin the ink
down. Every length is set at 300 dpi and scales with the dpi, so the
preview matches the export.

**Previewing.** The distress view (`⇧⌘D`) is the preview: it is live, and
palette changes like `edge 30` or `style · stamp` show in it straight away.

**Exporting.** With distress on, `⌘E` writes a PDF of page images at the dpi
(300 by default). With it off, or with **export pdf · clean**, the PDF is
vector and the text stays real text. The distress settings are saved with the
document.

## Files and saving

Saving is automatic. Until a document has a name it lives in the draft,
`~/Library/Application Support/ream/draft.ream`. **save as…** gives it a file,
and from then on it saves there. **new document** files the old draft away in
`drafts/` with a timestamp, so nothing is lost.

A `.ream` file is a zip:

- `ream.json` holds the words (plain text, a form feed opening each paragraph
  that starts a page), the page format, the distress settings, the view, and
  where every image sits.
- `media/` holds each image and PDF exactly as it came in, once per file.

## Themes

| Theme | Canvas | Page edge |
| --- | --- | --- |
| **paper** (default) | warm light grey | black hairline |
| **white** | white | dotted, as on a pinboard page |
| **night** | near black | none |

Choosing a theme sets its canvas colour. Any colour from the page panel or
`canvas #hex` overrides it. The page itself stays paper-coloured in every theme.

## Files in the code

| File | What's in it |
| --- | --- |
| `src/ream/app.py` | the window: input, page turning, pinning, undo, palette commands, saving, export |
| `src/ream/page.py` | the sheet, the strip of pages behind it, the text editor, images |
| `src/ream/canvas.py` | the infinite canvas: navigation, input routing, overlay drawing |
| `src/ream/palette.py` | the Tab command palette |
| `src/ream/panel.py` | the slider panels |
| `src/ream/distress.py` | finding the Distressor, extracting its textures, applying them |
| `src/ream/export.py` | drawing pages for the PDF, PNGs and the preview |
| `src/ream/project.py` | reading images and PDFs, the `.ream` file |
| `src/ream/style.py` | ink, paper, themes, page sizes, faces |
