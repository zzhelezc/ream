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

Press **Tab** anywhere (or right-click). The palette opens in the middle of
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
| Panels | distress panel (`⌘D`), page panel (`⌘L`) |
| Export | export pdf (`⌘E`), export pdf · clean (`⇧⌘E`), export png pages |
| Distress | distress view (`⇧⌘D`), distress on/off, distress images on/off, style · …, fade texture · …, reset distress |
| Page and type | page size · a4 / letter / a5 / square, paper · white / cream / newsprint / bond, paper colour…, canvas colour…, font · … |
| Pages | pages panel (`⌥⌘P`), add page, delete page, move page, cover on/off, back cover on/off, new page, next page (`⌘→`), previous page (`⌘←`), go to page |
| Views | write mode (`⇧⌘F`), write zoom, spelling on/off (`⌘;`), spelling language · …, edit dictionary, one page (`⌘1`), spread (`⌘2`), all pages (`⌘3`), fit page (`⌘0`) |
| Look | theme · paper / white / night |
| Selection (images and text blocks) | duplicate, mirror ↔ / ↕, arrange, merge, reset mask, rotate 90° right / left, rotate, straighten, delete, bring forward (`⌘]`), send backward (`⌘[`), bring to front (`⇧⌘]`), send to back (`⇧⌘[`), unpin from page, fit to text width, natural size |
| Profiles | save profile (`⌥⌘S`), save profile as…, new profile, profile · name (`⌥⌘1`–`9`), delete profile · name |
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
| `frame(label, size, paint_content=, drag_out=, on_change=)` | a frame on the canvas. You move it by its label or edge and resize it by its corner; clicks inside go through, unless it has a `drag_out`, in which case dragging from inside picks up the image it returns |
| `render(rect, dpi)` | what is on the canvas in a rect, as RGBA numpy, without the frames |
| `place_image(image, rect)` | put an image on the canvas (it pins if dropped on the page) |
| `place_text(text)` | start a text block with some words in it |
| `timer(ms, run)` | a repeating timer, stopped when ream closes |
| `settings` / `save_settings()` | the plugin's own saved dict |
| `use(tool)` | make a `ream.plugin.Tool` the canvas tool: it gets presses, drags and keys, and draws over the canvas, until `Esc` |
| `toast`, `visible_rect`, `window`, `scene`, `view` | the rest |

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

Also in the palette: **scanner: scan / stop**, **clear result**, **result to
canvas** and **export png**. Positions, size and settings are remembered.

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
| `src/ream/pages.py` | the pages panel's strip: thumbnails in spreads, drag to reorder |
| `src/ream/canvas.py` | the infinite canvas: navigation, input routing, overlay drawing |
| `src/ream/palette.py` | the Tab command palette |
| `src/ream/panel.py` | the slider panels |
| `src/ream/distress.py` | finding the Distressor, extracting its textures, applying them |
| `src/ream/export.py` | drawing pages for the PDF, PNGs and the preview |
| `src/ream/project.py` | reading images and PDFs, the `.ream` file |
| `src/ream/plugin.py` | plugins: the API (`Plugin`, `Host`, `Frame`) and the loader |
| `src/ream/plugins/scanner.py` | the scanner plugin |
| `src/ream/plugins/stik.py` | the stik plugin: cut tools, wand, eraser, background, islands, border, export |
| `src/ream/matting.py` | stik's pixel maths: background removal, wand, islands, die-cut borders |
| `src/ream/profiles.py` | profiles: the store of named settings |
| `src/ream/papers.py` | paper stock: the papers folder, the tooth map, laying it on a page |
| `src/ream/spelling.py` | spelling: the dictionaries, UK spellings, your own words |
| `src/ream/style.py` | ink, paper, themes, page sizes, faces |
