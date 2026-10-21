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

## Version

ream follows [Semantic Versioning 2.0.0](https://semver.org): `MAJOR.MINOR.PATCH`.

- **MAJOR:** `.ream` files or the plugin API stop working as they did.
- **MINOR:** new features that keep them working.
- **PATCH:** fixes.

Until 1.0.0 anything may still change, and breaking changes are listed
under **Changed** in [CHANGELOG.md](CHANGELOG.md). The version lives in
`src/ream/__init__.py` alone, and `pyproject.toml` reads it from there.
`ream --version` prints it, and so does **about ream** in the palette. Each
saved `.ream` file records the version that wrote it.

To release, add the changes under a new heading in the changelog, set
`__version__`, and run `uv tool install --reinstall .`.

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

Blocks take the document's face, size, line height and paragraph spacing,
and change with them, unless the text panel gives a block its own type
(see below).

### Writer and design modes

ream has two modes. `⌥⌘D` switches between them (or **writer mode** /
**design mode** in the palette). The mode is remembered.

**Writer** is ream as a writing app. The page's words are always live: a
click puts the caret in them and typing goes straight in. **Write mode**
(`⇧⌘F`, the view that follows the page as you write) belongs to writer mode.
Starting it from design mode switches back to writer.

**Design** is for laying out a book, as in InDesign. The page is objects:
the main text's frame, text boxes and images. Nothing types until you choose
where.

| Do | Does |
| --- | --- |
| click | selects: an image, a text box, or the main text's frame (a click on its words) |
| drag on an empty spot | a marquee: selects what it touches (`⇧` adds to the selection) |
| double-click | writes there: in a text box, or in the main text with the caret where you clicked |
| `↵` | writes in the selected text box, or at the end of the main text |
| `T` | a new text box: click for one that wraps at the margin, or drag its width |
| `V`, `Esc` | back to selecting; `Esc` also stops writing, then clears the selection |
| `⌘`+click | writes a block right there, as in writer mode |

Outside the main text's frame, a click reaches what lies under the words,
with no `⌥` needed. Delete, nudging, rotating, `⌘[` `⌘]` stacking and undo
all work as in writer mode.

**Frame edges.** Design mode draws InDesign's frame edges. A dotted line
marks the main text's frame on each page with words, and every text box.
The selected frame is solid, and the one you are writing in is dashed. The
mode shows at the bottom right.

### Instagram mode

A third mode, for making a carousel post. `⌥⌘C` (or **instagram mode** in the
palette) puts the book away and lays out a **carousel**: Instagram-shaped
slides side by side, touching, as one wide board. `⌥⌘D` takes you back to
the book; both are kept in the same document.

**The board.** It edits like design mode: drop, paste or drag pictures onto
it, draw text boxes with `T`, stamp, cut with stik, and style text with the
text panel. Anything can sit across slides: the slide edges are dotted guides
only, so the carousel is seamless by construction. Each slide is the board
cut at an equal width. What hangs off the board's edge is cut, as on a page.

**The carousel panel.** `⌥⌘C` again, or a right-click on the board, opens it.

| Row | Does |
| --- | --- |
| shape | 4:5 (1080 × 1350), 1:1, 3:4 (1080 × 1440) or 1.91:1 (1080 × 566) |
| slides | **+ slide** adds one after the current slide (the one last clicked); **remove** takes the current one out. What is to the right moves along either way. Both undo |
| background | the board's colour |
| width, finish, full picture, format | the export: 1080, 1440 or 2160 wide, distressed or clean, the whole picture as a fitted last slide and/or `full.jpg`, JPEG or PNG |

**Swiping through.** `⇧⌘P` in instagram mode (or **swipe through**) shows
the carousel as Instagram does: one slide at a time in a phone-wide column,
the count in the corner and dots underneath.

- **Moving:** swipe with two fingers on a trackpad, drag, or use `←` `→`.
  Letting go snaps to a slide; a flick goes on to the next.
- **Seamless:** between slides you see both halves, running on into each
  other.
- `Esc` goes back to the slide you were looking at.

**export…** writes a folder with `01.jpg` and onward, plus the fitted whole
picture and `full.jpg` as you chose.

In instagram mode every export is the carousel's:

- `⌘E` opens its panel, and `⌘E` again exports;
- `⇧⌘E` exports it clean;
- the instagram plugin's `⌥⌘G` and **instagram: export…** post the board,
  not the book.

Back in writer or design mode, they are the book's again.

### Text panel

`⌘T` (or **text panel**) styles text: **font**, **size**, **line** spacing,
**align** (left, centre, right, justify), **track** (letter spacing),
**weight** (regular / bold) and **italic**. Its caption says what it is
styling.

- **Selected words:** select words while writing, in a text box or in the
  main text (in writer mode, or while writing in it in design mode). Font,
  size, track, weight and italic then apply to just those words, over their
  box's type: one bold word, a bigger first line, an italic title. Line and
  align stay per box (or per main text). **as the box** (or **as the text**)
  clears the words' own type. Bold or italic switched off goes back to
  following the box, rather than fixing "regular". Styled words keep their
  type when the document's type changes, are undone a step at a time (a
  slider's whole drag counts as one), are saved with the document (older
  files still open), and are exported and distressed like everything else.

- **Text boxes:** with boxes selected, or one being written in, the settings
  are theirs alone. Each box keeps its own type, so a heading, a caption and
  a pull quote can each have their own. Anything a box doesn't set follows
  the document. **as document** gives a box back the document's type. Each
  change is one undo step, and a slider's whole drag counts as one. A box's
  type is saved with the document, exported and distressed like everything
  else.
- **The main text:** with no box chosen and no words selected, the panel
  sets the document's own type, the same type the page panel sets.
  Alignment and track are new for the main text too. Weight and italic are
  for words and boxes: select words to make part of the main text bold or
  italic.

### Pages panel

`⌥⌘P` (or **pages panel** in the palette) opens InDesign's Pages panel, more
or less: every page as a thumbnail, in spreads, the current one outlined.

- **Going to a page:** click its thumbnail (double-click also fits it to the
  window).
- **Reordering:** drag a thumbnail. A bar shows where it will land.
- **+ page** adds an empty page after the current one; **delete page** removes
  it, with whatever is pinned to it.
- **cover** and **back cover** set how pages pair into spreads (below).
- **one page / spread / all** switch the view.

The palette has the same, plus `move page 3` to send the current page to
position 3.

**Pages become fixed when you rearrange them.** Normally the words flow: a
paragraph running past a page's foot carries on at the head of the next. The
first time you move, add or delete a page, every page boundary becomes a
fixed page break, splitting a paragraph there if it has to, and each page's
words then stay on that page, like separate text frames in InDesign.

- Images and text blocks pinned to a page go with it.
- Each move, add or delete is one undo step.

### Preview

`⇧⌘P` (or **preview** in the palette) is InDesign's presentation mode: the
screen goes full, and only the finished pages show, one after another.

- **Exactly as exported:** distressed or clean as the export will be, with
  the paper stock, its blend and the ink, drawn by the same code the PDF export
  uses.
- **Resolution:** your screen's, never under 150 dpi, so distress looks as it
  will at 300.
- **Nothing else:** no canvas, panels, edges or selection, and the pointer
  hides when it rests.
- **Spreads:** a page that stands alone (a cover, a back cover) is centred,
  at the same scale as the spreads, so nothing jumps as you go through.

| Keys | Does |
| --- | --- |
| → ↓ Space PgDn, click the right half, scroll | next |
| ← ↑ ⇧Space PgUp, click the left half | previous |
| Home / End | first / last |
| S | single pages / spreads (it starts with spreads unless you're in the one-page view) |
| B / W / G / C | black / white / grey / your canvas colour behind the pages (the canvas is the default) |
| Esc, ⇧⌘P | back to writing, on the page you were last looking at |

A distressed page takes a moment: the clean page shows at once, and the
finished one replaces it ("finishing" shows at the bottom while it works).
The pages either side are prepared in the background, so turning feels
immediate.

### Write mode

`⇧⌘F` (or **write mode** in the palette) is for writing. It:

- zooms to your writing zoom (175% to start with);
- centres the page across the window;
- puts the line you're on a little above the middle.

As you write, the view follows the way a word processor's does: nothing moves
while the line stays in the middle band of the window. When it drops below
about 60%, the page glides up so the line is back just above the middle,
across page turns too. The same goes for a ⌘-click text block being written.

- **Writing zoom:** in write mode, `⌘=` / `⌘-` or a pinch set it, and it is
  remembered for next time. Also **zoom** under *write mode* in the page panel
  (`⌘L`), or `write 200` in the palette.
- **Scrolling** around works as usual; the next line you type brings the view
  back.
- **Leaving:** `⇧⌘F` again or `Esc` leaves and puts back the view you had, to
  the pixel. A small `write · 175%` sits in the bottom-right corner while
  you're in it.

### Spelling

In write mode, words the dictionary doesn't know get a red squiggle. `⌘;` (or
**spelling on/off** in the palette) turns it off and on, and the setting is
remembered.

- **Seeing it work:** the corner tag shows the state, `write · 175% ·
  spelling ✓` when nothing on screen needs correcting and `· spelling 3` when
  three words do. Turning spelling on, or entering write mode, says the same.
- **Fixing a word:** right-click it. The palette opens with suggestions first
  (**→ chief**), then **add "word" to dictionary** and **ignore "word"** (for
  this session). A correction undoes like any edit.
- **Never flagged:** the word you're still typing, single letters, words with
  digits, ALL CAPS, and words with a capital inside (iPhone, McNamara).
- **Text blocks** are checked too.
- **The squiggles are drawn over the page, not stored in it,** so they never
  reach a PDF or the distress render, and they show over the live distress
  view.
- **Languages:** **spelling language · …** in the palette: English (UK, the
  default, which takes both British and American spellings), English (US),
  Deutsch, Français, Español, Italiano, Português, Nederlands, Русский.
- **Your dictionary** is `dictionary.txt` in ream's home folder, one word per
  line (**edit dictionary** opens it).

### Spread and all pages

| Key | View |
| --- | --- |
| `⌘1` | one page (the default) |
| `⌘2` | a **spread**: two facing pages, like an open book |
| `⌘3` | **all pages** in a grid, sized to fit the window |

Pressing the key of the view you are in goes back to one page. Each view frames
itself when you switch, and `⌘0` re-frames it.

- **Spread.** Pages pair the way a book's do. `⌘←` and `⌘→` turn a whole
  spread.
- **Across the gutter.** Drop, paste or drag a picture (or a text block)
  across the gutter and it spans the spread. It belongs to the page its
  middle is on and hangs over onto the facing page, which shows the rest.
  That holds on screen, in previews, distress, single-page and spread
  exports, and imposition, where each half prints on its own page. Click
  either half to pick it up; picked up by its overhang, its home moves to
  the page you're on, without it moving. A cover or back cover standing
  alone has no facing page, so anything hanging off it is cut at the
  edge. So is anything hanging off a page's head or foot: bleed is cut
  there and never makes or keeps an extra page.
- **All pages.** Laid out like the pages panel: one spread a row, facing
  pages touching, every spine on one line down the middle. Each page is
  numbered underneath, or beside its spread when zoomed out too far for that.
  The live page is marked with a dot.
- **Covers.** With **cover** on (the default), the first page stands alone on
  the right, then 2 | 3, 4 | 5 … With it off: 1 | 2, 3 | 4 … With **back
  cover** on, the last page stands alone on the left. Both are in the pages
  panel and the palette, and are saved with the document (and in profiles).
- **You keep writing in every view.** The page holding the caret is the live
  one. Click any other page and it becomes live, with the caret where you
  clicked. Typing past the foot of a page carries on into the next one,
  wherever it sits.
- **Pinning and ⌘-click text** work on any page you can see. Drop an image
  on the facing page and it pins to that page.
- **The other pages** are drawn straight from the document, so they are sharp
  at any zoom. In distress view they are distressed too, the ones in sight,
  and they re-render after a change.
- **Exports** are the same whichever view you are in (the export panel only
  starts on spreads when you are in a spread view).

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

**Big documents.** A dropped PDF becomes one image per page, rendered at
200 dpi. On screen each image is drawn from a small copy, and a sharper one
is made only while you zoom in on it. The full pixels are kept for the
images used most lately, up to a memory budget, and decoded again from the
file when an export, distress or a cut needs them. So a 50-page photo PDF
costs about half a gigabyte, not two, and exports come out exactly the
same.

### Pinning to the page

Drag an image so **its middle is over the page**, or so it covers at least
a quarter of itself there (a picture bleeding off the edge), and it is pinned
to that page. A heavy outline round the page while you drag says it will
pin. The image remembers its page, so bleeding off the head or foot never
moves it onto the neighbouring page. A pinned image:

- scrolls with its page and is clipped to it;
- goes out with the PDF (anything still on the canvas does not);
- unpins when dragged off again (or **unpin from page** in the palette).

Dropping or pasting straight onto the page pins at once, scaled down to the
text width if it is wider.

- **Selecting and moving:** click to select, `Shift`+click adds, drag moves,
  `Alt`+drag carries a copy,
  and the arrows nudge (`Shift` for 10 pt). The corner square resizes about
  the middle, keeping the proportions.
- **Rotating:** drag the round knob above a selected image (`Shift` snaps to
  15°). `[` and `]` turn it 15° (`Shift` for 1°). In the palette,
  `rotate 30` sets an angle, and **straighten** puts it level. Images export
  turned. `⌫` deletes, `⌘C` copies the image, `Esc` goes back to
  writing.
- **Stacking order:** `⌘]` brings the selection forward a step, `⌘[` sends it
  back a step, and `⇧⌘]` / `⇧⌘[` take it to the front or back. On the page,
  the words are one step in that order, so an image can go behind them (the
  words print over it) or over them. An image behind the words is reached
  with `Alt`+click.
- **Undo** (`⌘Z` / `⇧⌘Z`) is one history for words and images together.

## Command palette

Press **Tab** anywhere (or right-click the empty canvas). The palette opens in the middle of
the window as a slip of paper. Its top stays put while the list filters, and
anything it adds (images, paste) still lands where the pointer was. Its grey caption gives the document, the page, the word count
and the distress style. Type to filter, `Enter` runs the command, and `Esc`
closes it. Matching is forgiving, and the commands you used last come first.

**Typing a number sets a value:**

| Type | Sets |
| --- | --- |
| `page 3` | goes to page 3 |
| `size 10` | text size, pt |
| `line 140` | line height, % |
| `para 6` | space after each paragraph, pt |
| `write 200` | write mode's zoom, % |
| `grain 40` | the paper stock's amount, % (tooth strength or blend opacity) |
| `stock 200` | the paper stock's scale, % |
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
| Panels | distress panel (`⌘D`), page panel (`⌘L`), text panel (`⌘T`) |
| Modes | writer mode / design mode (`⌥⌘D`), instagram mode (`⌥⌘C`), new text box (`T` in design and instagram mode) |
| Carousel | carousel panel (`⌥⌘C` in instagram mode), carousel: + slide, remove slide, swipe through (`⇧⌘P`), export… |
| Plugins | stik (`⌥⌘K`), impose (`⌥⌘I`), wear (`⌥⌘W`), instagram (`⌥⌘G`), scanner |
| Export | export pdf (`⌘E`: the export panel, for PDF or PNG), export pdf · all pages now, export pdf · clean (`⇧⌘E`), export png pages |
| Distress | distress view (`⇧⌘D`), distress on/off, distress images on/off, style · …, fade texture · …, reset distress |
| Page and type | page size · a4 / letter / a5 / square, paper · white / cream / newsprint / bond, paper colour…, canvas colour…, font · … |
| Pages | pages panel (`⌥⌘P`), add page, delete page, move page, cover on/off, back cover on/off, new page, next page (`⌘→`), previous page (`⌘←`), go to page |
| Views | preview (`⇧⌘P`), write mode (`⇧⌘F`), write zoom, spelling on/off (`⌘;`), spelling language · …, edit dictionary, one page (`⌘1`), spread (`⌘2`), all pages (`⌘3`), fit page (`⌘0`) |
| Look | theme · paper / white / night |
| Selection (images and text blocks) | duplicate, mirror ↔ / ↕, arrange, merge, reset mask, rotate 90° right / left, rotate, straighten, delete, bring forward (`⌘]`), send backward (`⌘[`), bring to front (`⇧⌘]`), send to back (`⇧⌘[`), unpin from page, fit to text width, natural size |
| Profiles | save profile (`⌥⌘S`), save profile as…, new profile, profile · name (`⌥⌘1`–`9`), delete profile · name |
| File | new document (`⌘N`), open… (`⇧⌘O`), save (`⌘S`), save as… (`⇧⌘S`), show drafts, word count, quit |

## Panels

**Right-click** a thing to open its control panel:

| Right-click | Opens |
| --- | --- |
| a text box | the text panel, for that box |
| the main text's words | the text panel; in design mode the main text's frame is selected too |
| the page around the words (or another shown page) | the page panel |
| an image | stik's panel (cut, clean, border, export), when stik is on |
| a scanner frame | the scanner panel |
| a misspelt word | its spelling suggestions, as before |
| the empty canvas, or something with no panel | the palette, with the thing selected |

Plugins add their own: see `host.context_panel` and `on_context` under
Plugins.

**Tools panel.** `⌥⌘T` (or **tools panel**) lists every tool, the current
one inked. Click one to pick it.

- **ream's own:** **write** (writer mode), **select** (`V`) and **text box**
  (`T`), the last two in design mode.
- **Each plugin's,** under its name: stik's lasso, rectangle and ellipse
  cuts, wand and eraser (`L` `M` `O` `W` `E`).

In design mode a tool's letter picks it, as in InDesign. In writer mode
letters type, so pick tools from the panel or the palette.

A panel is a slip of paper floating top right over the canvas. Both can be
open at once; the second opens beside the first. Drag either by its caption;
close it with `Esc`, its ×, or the same shortcut. Double-click a
slider's name to put it back to its default. Each slider drag undoes as one
step.

**Page panel** (`⌘L`):

- **type:** font (‹ › or click for the list; every Iosevka family you have
  installed is offered too: Iosevka, Term, Slab, Term Slab, Aile, Etoile), size, line height, paragraph
  spacing and ink darkness;
- **page:** format, side margins, top and bottom margins, paper colour
  (swatches, or **+** for any colour), and the paper **stock** and its
  **grain** (below);
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
  **export…**.

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

## Profiles

A profile is a named set of settings you can switch between: everything
about how the page looks and comes out, nothing about what is on it.

| In a profile | Not in a profile |
| --- | --- |
| page format, font, size, line and paragraph spacing, margins | your words |
| paper colour, stock and grain, ink | images and text blocks |
| every distress setting, the export dpi | the view (one page, spread, all) |
| canvas colour and theme | |

Profiles are yours, not a document's. They live in
`~/Library/Application Support/ream/profiles.json`, and any document can take
any of them.

**The flow:**

1. Set things up, then **save** (`⌥⌘S`). With no profile active yet, that
   makes `profile1`.
2. Change things; the active profile shows a `*` (in the panels and the
   palette caption) while the settings differ from it.
3. **save** puts the changes into the active profile, or **new** saves them as
   the next `profileN`, leaving the old one as it was.
4. Switch with `⌥⌘1` … `⌥⌘9` (in the order the profiles were made), the
   **profile** chooser at the top of either panel, or **profile · name** in the
   palette.

To name a profile, type `save profile zine` in the palette (an existing name
is replaced). **delete** in a panel removes the active profile; **delete
profile · name** in the palette removes any one. Switching re-lays the page in
one step, so `⌘Z` takes back a switch's line and paragraph spacing.

## Plugins

ream takes plugins: Python files that add commands, panels and canvas frames
without touching ream itself.

**Where they come from** (in this order):

1. built in: `src/ream/plugins/` (the scanner lives here);
2. yours: `.py` files or packages in
   `~/Library/Application Support/ream/plugins/` (**show plugins folder** in
   the palette opens it);
3. installed: Python packages with an entry point in the `ream.plugins` group.

**plugin · name** in the palette turns one off or on. The choice is
remembered. If a plugin fails to load, a toast says so and ream carries on.

**Writing one.** A plugin is a `Plugin` class with a `name` and a
`setup(host)`:

```python
from ream.plugin import Plugin as Base

class Plugin(Base):
    name = "stamp"

    def setup(self, host):
        host.command("stamp: today", self.stamp, shortcut="Ctrl+Alt+T")

    def stamp(self):
        import time
        self.host.place_text(time.strftime("%d.%m.%Y"))
```

`host` is the plugin's way in; see `src/ream/plugin.py` for the full API:

| `host.` | does |
| --- | --- |
| `command(title, run, hint, keywords, shortcut)` | a palette entry, optionally with a shortcut |
| `panel(title)` | a slider panel like ream's own: `slider`, `choice`, `toggle`, `swatches`, `links`, `buttons` |
| `frame(label, size, paint_content=, drag_out=, on_change=, on_context=)` | a frame on the canvas. You move it by its label or edge and resize it by its corner; clicks inside go through, unless it has a `drag_out`, in which case dragging from inside picks up the image it returns. `on_context` is what a right-click on it does (open the plugin's panel) |
| `tool(tool, label, key, choose=)` | list a tool in the tools panel. `key` (one letter) picks it in design mode; `choose` is what picking it does (default: `use(tool)`) |
| `context_panel(test, open)` | a right-click on a thing for which `test(thing)` is true calls `open` (stik opens its panel for images) |
| `space(claim, tap)` | while `claim()` is true and nothing is being written, a tap of Space calls `tap` (the scanner plays and stops). Holding Space and dragging still pans |
| `render(rect, dpi)` | what is on the canvas in a rect, as RGBA numpy, without the frames |
| `place_image(image, rect)` | put an image on the canvas (it pins if dropped on the page) |
| `place_text(text)` | start a text block with some words in it |
| `timer(ms, run)` | a repeating timer, stopped when ream closes |
| `settings` / `save_settings()` | the plugin's own saved dict |
| `use(tool)` | make a `ream.plugin.Tool` the canvas tool: it gets presses, drags and keys, and draws over the canvas, until `Esc` |
| `toast`, `visible_rect`, `window`, `scene`, `view` | the rest |

### Impose

Imposition, as a plugin: the pages laid out on printer sheets for binding,
with everything needed to print them, by yourself on a one-sided printer or
as a bundle for someone else. `⌥⌘I` (or **impose** in the palette) opens the
panel and the imposition preview.

| Style | For |
| --- | --- |
| **saddle stitch** | booklets and zines: all sheets nested, folded together, stapled through the fold |
| **perfect bound** | each sheet folded on its own, the folded sheets stacked and glued at the spine |
| **sewn signatures** | thicker books: sheets nested in groups (1–8 sheets each), folded, sewn |
| **cut & stack** | printed 2-up, cut in half, right pile under left: the leaves come out in order |
| **mini zine · 8 pages** | the classic one-sheet zine: one side, one cut, folded |

**How the pages are placed:**

- **Gutters at the spine:** in folded styles, pages sit against the fold.
- **Upside-down cells:** the mini zine's top row is printed upside down.
- **Blank pages,** where a style needs a multiple of 4 or 8, go before the back
  cover so it stays on the outside. **blanks · at end** puts them last
  instead.

**The imposition preview:**

- each sheet's front and back side by side, pages in place;
- big page numbers on them (with front cover and back cover marked);
- fold marks at the edges and dashed cut lines;
- `←` `→` between sheets, `N` for the numbers, `G` for the how-to-print guide,
  `Esc` back to writing.

**Panel options:**

- style, sheet (A4, Letter, A3, Tabloid), pages **fit** or **100%**, sheets per
  signature, blanks before the back cover or at the end;
- **printing:** **single-sided · turn over the long edge** (the default, like a
  book's page), **single-sided · turn over the short edge** (like a calendar),
  **duplex · flip on short / long
  edge**;
- **backs** in order or **reversed** (for printers that stack face up), and
  marks on or off.

**Printing on a one-sided printer.** The guide draws it in four panels, as
you see it standing in front of the printer: paper standing upright in the
tray at the back, going in short edge first, the printed sheets coming out to
you at the front short edge first. A blue ● marks one edge of the stack and
follows it through every step.

Because the paper goes through short edge first, the landscape booklet sheets
go through sideways. Turning the paper over its long edge therefore turns the
sheet top to bottom, and ream prints the backs turned to suit, so both turns
come out right.

1. print `1-fronts.pdf`: the paper goes in at the back and comes out to you;
2. take the stack out of the front tray just as it is (● is the edge nearest
   you);
3. turn the whole stack over its long edge, like a book's page (the ● stays
   nearest you), or over its short edge like a calendar if you chose that (the
   ● goes to the far side);
4. stand it in the back tray, blank side facing you, the edge nearest you
   going in first, then print `2-backs.pdf`.

**test sheet…** writes a two-sided test page, so you can check how your
printer feeds before you use real paper. Both sides should read upright, back
to back. If B comes out upside down, choose the other edge to turn over.

**Printing straight to the printer.** Pick a **printer** in the panel
(**default** is the system's default printer), then **print** (or
**impose: print** in the palette). A card walks you through the job:

1. ream sends the fronts and follows the job through the printer's queue
   until it says **printed ✓**;
2. the card shows the turn for the edge you chose, and waits;
3. when the stack stands in the back tray, `↵` (**print the backs**) sends
   the backs;
4. done, with how to fold and bind.

On a duplex setting it is one job with both sides, flipped on the edge you
chose. A mini zine is one-sided, so only the fronts are sent.

**While it prints, ream is yours.** `Esc` (or **minimise**, or the card's
−) folds the card into a small **printing** panel at the bottom right. You
can write, leave the imposition view, do anything. The panel keeps the step
and the printer's progress up to date, and a note appears when a side has
printed. The panel's words do the rest:

| Word | Does |
| --- | --- |
| **next** / **print the backs** / **done** | the next step, straight from the panel |
| **open** | the full card again, with its drawings (also **impose: printing** in the palette) |
| **stop** / × | ends the walk-through; jobs already sent carry on in the printer's queue |

Leaving the imposition view folds the card away by itself. On the card, `↵`
goes on and **stop** ends it.

The pages are sent upright, as the paper
goes through the printer, with each landscape sheet turned a quarter onto
them, so the two pages fill the sheet whatever the printer's driver does.
(The bundle's PDFs stay landscape. Preview's print dialog turns them.)
Printing goes through the system's own
printing (CUPS `lp`), so the printer has to be set up in System Settings ›
Printers & Scanners.

**Cheap trial runs.** Two print jobs use next to no ink and print fast, at
the printer's draft quality in black only:

| Panel | Palette | Prints |
| --- | --- | --- |
| **test** | **impose: print test sheet** | one sheet: an outlined A on the front, B on the back, and a top arrow. It checks the turn |
| **draft** | **impose: print draft** | the whole job, fronts then backs, with every page as a hairline outline, its number and a top arrow. Fold it to check the order before printing for real |

Draft mode is asked for twice: once in the standard way (IPP
`print-quality=3`, `print-color-mode=monochrome`) and once in the driver's
own terms, read from its PPD file: its **Draft** quality, grayscale or black
ink, and its lowest resolution. That matters because Epson's drivers ignore
the standard names. For the ET-2810, ream sends Draft, Grayscale on, 180 dpi
and the driver's Advanced mode, which it needs before it accepts a quality
setting.

**export bundle…** writes a folder you can hand to anyone:

| File | What it is |
| --- | --- |
| `1-fronts.pdf` | the fronts of every sheet, in order |
| `2-backs.pdf` | the backs, turned and ordered for the chosen way of turning |
| `duplex.pdf` | fronts and backs interleaved, for a duplex printer |
| `guide.pdf` | how to print (with drawings), a sheet-by-sheet page map, how to fold and bind |
| `test-front.pdf`, `test-back.pdf` | the printer test |
| `README.txt` | the steps in words |

A mini zine is one-sided, so its bundle is just the fronts, the guide and the
README. Clean pages are placed as vector, so text stays text. Distressed pages
are placed exactly as they export.

### stik

The image side of [stik](../stik), as a plugin: cut stickers out of anything on
the canvas or the page, clean their backgrounds, give them die-cut borders and
export them. `⌥⌘K` (or **stik** in the palette) opens its panel.

**Tools.** Pick a tool in the panel's first row (or **cut: lasso**, **wand**
… in the palette). While a tool is on, presses on the canvas go to it, the
letter keys switch tools as in stik, and `Esc` goes back to writing.

| Key | Tool | Does |
| --- | --- | --- |
| L | lasso | draw round something; letting go cuts it out (**smooth** steadies the line) |
| M | rect | drag a box; letting go cuts (`Shift`: square) |
| O | ellipse | drag an ellipse; letting go cuts (`Shift`: circle) |
| W | wand | click a colour to take it out; `Shift`+click brings it back |
| E | eraser | rub pixels out; `Shift`+drag paints them back; `[` `]` size |

**How cutting works:**

- **It's physical, as in stik.** The cutout lands exactly over its hole,
  nudged down and right so the cut shows, and the hole stays in the image.
  **feather** softens the edge, and cutout plus hole always add back up to the
  original.
- **Copy instead:** `Alt` as you let go copies instead of cutting, or
  **keeps · copy** in the panel makes copying the default.
- **Which image:** a cut takes the selected image under the shape if there is
  one, else the topmost image with something there.

**Background.** Removes the background from the selected images with stik's
methods: border flood, gradient flood, colour key, drop white / black, GrabCut,
and rembg's AI model if installed (`uv tool install --reinstall '.[ai]'`).

- **Refining:** tolerance, softness, grow, feather, despeckle, keep largest
  only, fill holes.
- **Live preview:** the fast methods follow the sliders (a quick preview while
  dragging, full resolution a moment later). GrabCut and AI run on **apply**.

**Sheet.** **auto-cut islands** turns every separate sticker on the selected
sheet into its own cutout, soft edge included, and lays them out beside it.
**min island** skips specks. **arrange** tidies any selection into rows.

**Border.** A die-cut sticker edge (width, smoothness, colour) on the
selected images. Its enclosed holes are filled, as a real die-cut is.
**remove** takes it off.

**Export.** **export selected…** writes the selected images as PNGs, exactly as
they look (border, rotation and mirroring included). Options: **pattern**
(tokens `{name}`, `{n}`, `{w}`, `{h}`, `{date}`, e.g. `sticker-{n:02}`),
**scale**, **padding**, **trim**. Names that are taken get a number.

**Nothing is destroyed.** Every image keeps its original pixels: cuts, the
background removal, the wand and the eraser only edit its masks. **reset
mask** (panel or palette) takes away the cleaning and leaves the cut shape as
it was cut. It all undoes, and saves with the document.

### Scanner

A slit-scanner after [snitscanner.xyz](https://snitscanner.xyz). **scanner**
in the palette opens three things:

- **A · scan bed:** a frame on the canvas. Put anything in it (images, PDF
  pages, text blocks, a corner of the page) and it gets scanned.
- **B · scan result:** a frame of the same size, filled in as the scan line
  crosses the bed. **Drag out of it** to pick the scan up as a new image.
- **scanner:** a settings panel.

On every tick, the strip of canvas under the blue line is copied into the
result at the same place. Move something in the bed while the line is on it
and it smears. Resizing either frame resizes both and starts a fresh result.

| Setting | Does |
| --- | --- |
| ▶ scan / ■ stop, clear | run the line; start a fresh result |
| direction | down the bed, or across it |
| speed | 1 is a pass in eight seconds |
| loop | start again at the end (for stacked passes) |
| ink | colour, xerox (hard toner, high contrast) or dither (ordered, two-tone) |
| tone | lighter … darker |
| grain | fine … coarse: the size of noise, toner and dither cells |
| layering, blend | replace each pass, or stack passes with darken / multiply / screen |
| noise | grain over the scan |
| paper | what empty bed scans as, and what xerox and dither print on |
| dpi | the result's resolution |
| to canvas, export png | the scan as an image beside the result, or as a file |

**Space plays and stops it.** While the scanner is open and nothing is being
written, a tap of Space starts the line and another tap stops it. "Nothing
being written" means design mode, or something selected in writer mode.
Wherever you are writing, Space stays a space: in writer mode's page, in a
text box, or in the main text in design mode. Holding Space and dragging
still pans. Right-click either frame for the settings.

Also in the palette: **scanner: scan / stop**, **clear result**, **result to
canvas** and **export png**. Positions, size and settings are remembered.

### Instagram

The book as Instagram posts. `⌥⌘G` (or **instagram** in the palette) opens
a preview of the slides and the panel. The chosen pages, laid side by side,
make one long picture, and the slides are cut from it edge to edge. So in
a carousel each slide runs straight on into the next: a spread, or a
picture across the gutter, swipes as one image.

| as | Slides |
| --- | --- |
| **pages** | one slide per page, the page fitted to it |
| **spreads** | each spread across **per spread** slides (2 by default, so a page a slide), a cover alone on its own |
| **one long strip** | every page side by side, cut into as many slides as it takes |

**Shape and size:**
- **shape:** 4:5 (1080 × 1350, the most room on screen), 1:1, 3:4
  (1080 × 1440) or 1.91:1 (1080 × 566).
- **width:** 1080, 1440 or 2160.
- **pages:** all, or a range like `2-9`.

**Fitting the pages:**
- **pictures:** **fit** keeps whole pages in the slides with the background
  round them; **fill** fills the slides and crops.
- **zoom, margin, gap** (between pages in the strip), and **nudge** ←→ ↑↓
  to adjust.
- **background:** the canvas colour, the paper, white or black.
- **finish:** as distress is set, distressed, or clean.

**Moving pictures for Instagram only.** Drag any picture in the slides
preview to put it somewhere else in the carousel, off a cut between two
slides, say. The book is untouched: the move belongs to the export.

- **How it's drawn:** a moved picture is taken off its page and laid over
  the full picture where you put it, on top of the words, free of page
  edges and slide cuts. It is distressed like any image when the finish is
  distressed.
- **Putting it back:** double-click a picture, or use **put back all** in
  the panel (it shows how many are moved).
- **Remembered:** moves are kept for the document.

**Dropping slides.** Hover over a slide and click the **×** in its corner
to drop it, for example one left empty after moving pictures. It stays in
the preview, faded, and a click on its **↺** brings it back (or use **bring
back all** in the panel). The export leaves dropped slides out and numbers
the rest without gaps. The full picture, both `full.jpg` and the fitted last
slide, is the kept slides joined, so the slides on either side of a dropped
one no longer run seamlessly into each other. Drops are kept for the
document.

**The whole picture.** Instagram crops every image in a carousel to the
shape of the first one, so the long full picture can't go in as it is.
**full picture** chooses what to do with it:

| Choice | What you get |
| --- | --- |
| **last slide** (the default) | one more slide of the same shape: the whole picture scaled down to fit, the background round it |
| **last slide + file** | that, and the uncut picture as `full.jpg`, to post on its own |
| **file** | only `full.jpg` |
| **no** | neither |

**export…** writes a folder with `01.jpg`, `02.jpg` and so on. Post them in
that order; the fitted whole picture comes last. JPEG or PNG. Instagram
takes up to 20 slides a post, the fitted picture included; past that, the
preview says how many posts it takes.

### Wear

Distress for what's on the page: **torn edges** for images, and **stamps**
(stains, ink splatter, tape, dust, folds, document marks) to put down. `⌥⌘W`
(or **wear** in the palette) opens the panel.

**Torn edges.** Select images and click **tear**. Their edges tear, and the
paper's core shows along the tear.

- **edge:** **drawn** (ream tears along a fractal edge, with fibres) or a
  torn matte from your stamps folder, stretched over the image.
- **sides:** all, one, or a pair.
- **depth, rough:** how far and how raggedly it tears.
- **rim, core:** how wide the band of paper core is, and its colour (paper,
  cream, burnt, or none).

The tear is a property of the image, like its border, so the original is
never touched. With torn images selected, the sliders change the tear live,
and a whole drag undoes as one step. **new tear** tears again differently,
and **mend** takes it off. The **tear** tool (`R`) tears any image you click;
`⌥`-click mends it. Tears are saved, exported and distressed.

**Stamps.** Pick a **kind**, then a stamp in the grid, and the **stamp** tool
(`S`) is on. Each click puts the stamp down centred on the pointer, as an
image, so it moves, turns, stacks, pins to the page, undoes and is
distressed like any image.

| Row | Does |
| --- | --- |
| size | as a share of the page's width (the dashed box at the pointer shows it) |
| jitter | varies the size, stamp to stamp |
| turn | none, a little, or any way, at random |
| tint | as is, ink, brown, rust, blue, red, paper |
| strength | fades it |

A sheet of pieces (tape strips, document marks) gives a different piece
each click. `Esc` stops.

**Where stamps come from.** ream draws four itself, so it works with nothing
downloaded: **coffee ring**, **ink blot**, **specks** and **crease**. The
rest are your own textures in the stamps folder,
`~/Library/Application Support/ream/stamps/` (**stamps folder…** opens it).
Each subfolder is a kind; **torn mattes** holds the mattes that tear images.

- **Opaque images** (marks photographed on white, or on black) are keyed from
  their lightness, so the marks become the stamp and the ground disappears.
- **Images with transparency** are used as they are.
- **index.json** names them and says which to split into pieces:
  `{"tape/Texturelabs_Details_122M.png": {"label": "Masking tape", "split": 8}}`.

Like the paper stock, ream ships no textures. Texturelabs' textures are free
to use in your work but not to pass on, so they stay in your folder and are
never bundled with ream.

Stamps lie over the page with ordinary transparency, so they look the same
in a clean PDF (which has no blend modes). A dark stamp over words lightens
them a little, where a real stain would darken them.

## Paper stock

A paper stock lays a photographed paper's surface under the page, on screen,
in the distress view, on the other pages and in both PDF exports.

- **Choosing one:** **stock** in the page panel (‹ › or click for the list),
  or **paper stock · …** in the palette. **flat** turns it off.
- **blend** sets how the paper goes on (below), **amount** (0–100%) how
  strongly, and **scale** (25–400%) how big. At 100% the paper is fitted to
  cover the page; above, it is blown up; below, it repeats, mirrored at the
  seams. In the palette: **stock blend · …**, `grain 40` for the amount,
  `stock 200` for the scale.

| Blend | What it does |
| --- | --- |
| **tooth** (default) | Only the paper's surface: its tooth and fibres, without its colour or uneven lighting, laid onto your paper colour. The page stays your colour and evenly lit. |
| **multiply** | The actual paper photo over the whole page (ink, images, text blocks), levelled so its whites are white. Fibres and shadows darken; black ink stays black. |
| **overlay** | The photo as a "grey to overlay" (centred on mid-grey, detail stretched). Textures mid-tones: faded ink, greys, images. It barely shows on white paper; that is how overlay works. |
| **soft light** | A gentler overlay. |
| **screen** | The photo levelled so its blacks are black, lightening the page; dark ink lifts. |
| **normal** | The photo exactly as photographed, covering the page at the amount's opacity. It greys the ink below 100%. |

For a white page with the real paper on it, start with **multiply**. To make
faded ink take the paper, try **overlay** with `ink` below 100.
- **Distressed ink sits in the tooth.** The stock's light and shade carry
  through the ink, most visibly when the ink is faded.
- **Placement is fixed.** The texture is fitted to cover the page, turned to
  its orientation, and lands on the same spot at every resolution, so the
  preview and the export line up.
- **On screen** the blend is Qt's own (the same formulas). The distress view,
  distressed PDFs and PNGs blend in the same way, over everything on the page.
- **Clean PDFs** keep vector text: Qt's PDF output has no blend modes, so the
  paper is blended into the paper colour under the words, which go on top.
  With dark ink that looks the same; faded ink and images are not textured
  there. That's about 2 MB a page at 300 dpi.
- **Saving:** the document stores the stock's file name. Elsewhere, without
  that file, it falls back to flat paper.

**Where the papers come from.** ream ships no textures. It reads any images in
`~/Library/Application Support/ream/papers/` (**show paper folder** in the
palette opens it). Drop your own scans in there too. An optional `index.json`
in that folder names them: `{"file.jpg": "Display name"}`.

The 12 clean papers there now were downloaded from
[Texturelabs](https://texturelabs.org/?ct=666&st=667), large size, for your own
use. Texturelabs' terms allow using them in your work, commercial work
included. They do not allow redistributing them or bundling them with a tool,
so they live in your user folder and never in this repo or package. Don't
commit them or put them in a shared `.ream`.

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

**Layers.** The words, each text block and each image are distressed
separately, then stacked in their order. Words on top of a picture wear just
like words anywhere else.

- **images** (distress panel, or **distress images on/off** in the palette)
  chooses whether pictures are distressed too (worn edges, specks, fade) or
  left clean.
- Words are always distressed, on top of a picture or not.

**How it works.** Each page is rendered as layers (the words, each text block,
each pinned image) at the export dpi. The layer's alpha becomes a signed distance
field: positive inside the ink, negative outside. The edge texture moves the
boundary in where it is light and out where it is dark, so edges go ragged
rather than just thin. Bleed shifts the boundary, blur melts it, and it is cut
again with an antialiased step. The inner and fade textures then thin the ink
down. Every length is set at 300 dpi and scales with the dpi, so the
preview matches the export.

**Previewing.** The distress view (`⇧⌘D`) is the preview: it is live, and
palette changes like `edge 30` or `style · stamp` show in it straight away.

**Exporting.** A distressed PDF is made of page images at the dpi (300 by
default). A clean one is vector, so the text stays real text. The distress
settings are saved with the document.

Distressing is the slow part: about 0.3 s a page at 300 dpi, or 0.7 s with
misfire. So exports distress several pages at once on separate threads,
and work only on the ink and the margin round it that the effect can reach.
`tests/bench.py` times it.

## Export

`⌘E` opens the **export** panel: the page map, which pages to export, and
how. `⌘E` again (or **export…**) asks where to save and writes the file.

**Picking pages.** Every page is picked to begin with. Pages left out show
pale on the map.

- **The map:** click a page to take it in or leave it out. Drag across
  pages to do the same to each one. `⇧`-click takes in the run back to the
  last page you clicked.
- **pages:** **all**, **none**, **this one** (the page you are on), **odd**,
  **even**.
- **range:** type pages, such as `1-4, 7`, or `5-` for page 5 to the end. It
  follows the map, and the map follows it.

**How:**

| Row | Choices |
| --- | --- |
| **as** | **single pages**: one PDF page per page. **spreads**: facing pages side by side on one PDF page twice as wide, with a cover or back cover alone at single width, as InDesign exports spreads. A spread with any page picked goes out whole, and in spreads a click on the map takes the whole spread. It starts as you are viewing: spreads in spread or all-pages view |
| **finish** | **distressed** (page images with the distress) or **clean** (vector, the words stay words). It starts as distress is set |
| **paper** | **stock** (the paper stock, its texture and blend) or **plain** (just the paper colour) |
| **format** | **pdf**, or **png**: one image per page (`name_03.png`) or per spread (`name_02-03.png`) |
| **dpi** | for distressed pages and PNGs |

Under the options a line sums it up, for example "5 pages on 3 spreads ·
distressed · pdf". The as, paper and format choices are remembered. The
palette's **export pdf · all pages now** and **export pdf · clean** (`⇧⌘E`)
still export every page straight away.

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
| `src/ream/preview.py` | preview: the finished pages full screen, one after another |
| `src/ream/pages.py` | the pages panel's strip: thumbnails in spreads, drag to reorder; the export panel's page map for picking pages |
| `src/ream/canvas.py` | the infinite canvas: navigation, input routing, overlay drawing |
| `src/ream/palette.py` | the Tab command palette |
| `src/ream/panel.py` | the slider panels |
| `src/ream/distress.py` | finding the Distressor, extracting its textures, applying them |
| `src/ream/export.py` | drawing pages for the PDF, PNGs and the preview |
| `src/ream/project.py` | reading images and PDFs, the `.ream` file |
| `src/ream/plugin.py` | plugins: the API (`Plugin`, `Host`, `Frame`) and the loader |
| `src/ream/plugins/scanner.py` | the scanner plugin |
| `src/ream/imposition.py` | imposition: which page goes where on which side of which sheet |
| `src/ream/plugins/impose.py` | the impose plugin: panel, preview, guide drawings, bundle, print card |
| `src/ream/printing.py` | sending PDFs to a printer (CUPS `lp` / `lpstat`) |
| `src/ream/plugins/stik.py` | the stik plugin: cut tools, wand, eraser, background, islands, border, export |
| `src/ream/wear.py` | torn edges (drawn or from a matte, with a paper rim), stamps from textures, ream's own drawn stamps |
| `src/ream/plugins/wear.py` | the wear plugin: tear and stamp tools, the stamp grid |
| `src/ream/carousel.py` | instagram mode's carousel board, rendering it seamless, its export and the swipe-through preview |
| `src/ream/plugins/instagram.py` | the instagram plugin: slides from pages, spreads or one long strip, the seamless carousel, the full picture |
| `src/ream/matting.py` | stik's pixel maths: background removal, wand, islands, die-cut borders |
| `src/ream/profiles.py` | profiles: the store of named settings |
| `src/ream/papers.py` | paper stock: the papers folder, the tooth map, laying it on a page |
| `src/ream/spelling.py` | spelling: the dictionaries, UK spellings, your own words |
| `src/ream/style.py` | ink, paper, themes, page sizes, faces |
