# Changelog

Every change to ream that you would notice, newest first.

ream uses [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
Versions are `MAJOR.MINOR.PATCH`:

- **MAJOR** goes up when `.ream` files or the plugin API stop working as
  they did.
- **MINOR** goes up for new features that keep them working.
- **PATCH** goes up for fixes.

Until 1.0.0 anything may still change, but breaking changes are listed here
under **Changed**. The version lives in `src/ream/__init__.py` alone, and
`pyproject.toml` reads it from there. `ream --version` prints it, the
palette's **about ream** shows it, and every saved `.ream` file records the
version that wrote it. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.7.0] - 2026-10-20

### Added

- **instagram: drop slides.** Hover over a slide and click its × to leave it
  out of the carousel. It stays in the preview, faded, and a click brings
  it back, as does **bring back all** in the panel.
  - The export numbers the kept slides without gaps.
  - The full picture (`full.jpg` and the fitted last slide) is the kept
    slides joined.
  - The slide count, and the 20-a-post warning, count only kept slides.
  - Drops are remembered for the document.

## [0.6.0] - 2026-10-20

### Added

- **instagram: move pictures in the export only.** Drag a picture in the
  slides preview to place it anywhere in the carousel (across a cut, out of
  the way). Its place in the book doesn't change.
  - Moved pictures are laid over the full picture where you put them,
    distressed like any image, and show on the fitted last slide too.
  - Double-click puts one back; **put back all** puts every one back.
  - Moves are remembered for the document.

## [0.5.5] - 2026-10-20

### Fixed

- **instagram: the whole picture fits in the carousel.** Instagram crops
  every image in a carousel to the first one's shape, so `full.jpg` was cut
  down when posted with the slides. **full picture** now adds it as a last
  slide of the same shape, the whole picture scaled down to fit, by
  default. You can also have the uncut file as well, the file only, or
  neither. The preview shows the extra slide and counts it towards
  Instagram's 20.

## [0.5.4] - 2026-10-20

### Fixed

- **A picture bleeding off a page's edge is pinned and exported.** An image
  pinned only if its middle was over a page. So a picture hanging off a
  page's outer edge, middle just outside, stayed on the canvas: it looked
  placed but never exported.
  - **Pinning:** an image now also pins to the page it covers most, if
    that's at least a quarter of it.
  - **Remembered page:** it remembers its page, through undo, saving and
    page moves, so a picture bleeding off the head or foot stays with its
    page rather than being taken for the next one.

  Files from before still open: things there go to the page their middle
  is on, as before.

## [0.5.3] - 2026-10-20

### Changed

- **Big PDFs take a third of the memory.** With 50 A4 photo pages, memory
  went from +1.73 GB to +0.58 GB. Drawing, dragging and saving are as quick
  as before, and exports are pixel-for-pixel the same.
  - **On-screen copies:** each image keeps a small on-screen copy (900 px).
    A bigger one is made only while it is drawn bigger (zoomed in), and the
    bigger ones share a 192 MB budget.
  - **Originals:** they share a 256 MB budget. The least lately used are let
    go and decoded again from the file when needed (about 14 ms for a PDF
    page), for exports, distress and cutting.
  - **Screen drawing:** the pages beside the live one and the pages panel's
    thumbnails draw from the on-screen copies, never the full pixels.
  - **Undo** no longer holds a copy of each original; originals never
    change.

## [0.5.2] - 2026-10-20

### Fixed

- **No more stalls with big PDFs.** With a 50-page PDF of photos (59 MB) on
  the page, every autosave froze the window for about 2 s, a second after
  every move: moving things lagged, and so did the palette. Each page carries
  the whole PDF, and each save fingerprinted it once per page, recompressed
  it into the `.ream` file, and did it all on the main thread.

  | | before | after |
  | --- | --- | --- |
  | building a save | 893 ms | 19 ms |
  | a save that blocks the window | 1.95 s | 85 ms |
  | window after letting go of a drag | frozen about 2 s | free |

  - **Fingerprints once:** a file is fingerprinted once and remembered, and
    masks are encoded once.
  - **No recompressing:** media go into the `.ream` file as they are
    (images and PDFs are compressed already). Older files open as before.
  - **Background autosave:** autosaves are written on a thread of their
    own, one at a time, with changes made meanwhile saved straight after.
    Saving, opening, new document and quitting still save at once, after
    waiting for any save under way.

## [0.5.1] - 2026-10-20

### Fixed

- **A picture bleeding off a page no longer keeps an extra page alive.**
  Before, a spread picture a little taller than the page made a third page,
  and deleting that page didn't remove it. Now:
  - a thing keeps only its own page (the one its middle is on) in being;
  - each page shows its own things, cut at its edges, plus what hangs over
    the gutter from its facing page, but nothing that hangs off the page
    above or below it, on screen or in exports.

## [0.5.0] - 2026-10-20

### Added

- **instagram** (`⌥⌘G`): the book as Instagram posts.
  - **Slides:** one slide per page, each spread across slides, or the whole
    book as one long strip.
  - **Seamless:** all are cut edge to edge from one full picture, so the
    carousel swipes seamlessly, even across a spread or a picture over the
    gutter.
  - **Shape:** 4:5, 1:1, 3:4 or 1.91:1, at 1080, 1440 or 2160 wide.
  - **Fitting:** fit or fill, with zoom, margin, gap, nudge and background
    controls.
  - **Preview:** a slide preview that warns past Instagram's 20 slides a
    post.
  - **Export:** a folder of numbered slides plus `full.jpg`, the uncut
    picture.

## [0.4.2] - 2026-10-20

### Fixed

- **A picture can be placed across a spread.** Before, it was cut off at
  the edge of whichever page its middle was on. Now it belongs to that page
  and hangs over onto the facing page of the spread, so both pages show
  their part:
  - on screen, on the live page and the page beside it;
  - in previews, distress, single-page and spread exports, and imposition.

  Either half picks it up. Covers standing alone still cut it at the edge.
  `.ream` files are unchanged: where a thing sits already said all this.

## [0.4.1] - 2026-10-20

### Changed

- **Faster distress and exports, with identical output.** Distressed pages,
  PNGs and impose bundles are pixel-for-pixel what 0.4.0 made; tests check
  this against references.

  | | 0.4.0 | 0.4.1 |
  | --- | --- | --- |
  | distress a page at 300 dpi | 571 ms | 291 ms |
  | export 10 distressed pages (PDF) | 6.6 s | 2.0 s |
  | export 3 distressed PNGs | 2.3 s | 0.95 s |
  | tear a 4000×3000 image | 480 ms | 230 ms |
  | a tear slider step on that image | 500 ms | 35–50 ms |

  - **Distress works on just the ink and the margin round it** that the
    effect can reach, not the whole page. Single-colour ink (type always
    is) skips the colour-spreading blur. Layers go onto the paper only
    where they have ink.
  - **Distressed pages are made several at once** for PDF and PNG exports
    and impose bundles. Qt draws each page on the main thread, threads
    distress them, and pages come back in order.
  - **Torn edges change only the torn strips.** While a tear slider is
    dragged, a big image is re-torn from a small copy, and the full-size
    tear follows when you let go (or a moment after you stop).
  - **The textures the document's distress uses are loaded in the
    background at startup,** so the first distressed view doesn't wait.
  - **Misfire is still the slow setting** (about 0.7 s a page). Its wide
    blur can't be cropped without changing the result.
- `tests/bench.py` times the slow paths.

### Fixed

- **A flaky wear test:** it looked for the torn edge's paper rim in a single
  column, which a thin, random rim could miss.

## [0.4.0] - 2026-10-20

### Added

- **wear** (`⌥⌘W`): distress tools for what's on the page.
  - **Torn edges for images:**
    - drawn by ream, or along a torn matte from your stamps folder;
    - any sides, with depth and roughness;
    - a rim of paper core (paper, cream or burnt).

    A tear is part of the image, like its border: the original is never
    touched, the sliders change it live, and it is undoable, saved, exported
    and distressed. There is a **tear** tool (`R`) too.
  - **Stamps,** placed with the **stamp** tool (`S`):
    - from your own textures in the stamps folder, plus coffee ring, ink
      blot, specks and crease drawn by ream;
    - size, jitter, turn, tint and strength;
    - sheets of pieces give one piece per click;
    - opaque textures are keyed from their lightness.
- **.ream files** can hold a tear on an image (older versions ignore it).

## [0.3.1] - 2026-10-20

### Changed

- **Space only plays the scanner when nothing is being written.** In writer
  mode, Space types into the page even with the scanner open. It plays and
  stops the scanner in design mode, or in writer mode with something
  selected. `host.space` claims follow the same rule.

## [0.3.0] - 2026-10-20

### Added

- **Space plays and stops the scanner** while it is open. A tap starts or
  stops the scan line, and holding Space and dragging still pans. Space
  stays a space while you write in a text box, or in the main text in
  design mode.
- **Plugin API:** `host.space(claim, tap)` claims taps of Space while
  `claim()` is true.

## [0.2.0] - 2026-10-20

### Added

- **Right-click opens the control panel** of what you click:
  - a text box, or the main text: the text panel;
  - an image: stik's panel, when stik is on;
  - the scanner's frames: the scanner panel;
  - the page around the words: the page panel.

  A misspelt word still gets its suggestions, and the empty canvas still
  gets the palette.
- **Tools panel** (`⌥⌘T`, or **tools panel** in the palette): every tool in
  one list, the current one inked. It holds ream's write, select and text
  box tools, then each plugin's (stik's lasso, rectangle and ellipse cuts,
  wand and eraser).
- **Single-letter tools in design mode:** `V` select, `T` text box, and the
  letters plugins give their tools (stik: `L` `M` `O` `W` `E`).
- **Plugin API** (additions, nothing removed):
  - `host.tool(tool, label, key, choose)` lists a tool;
  - `host.context_panel(test, open)` opens a panel when a matching thing is
    right-clicked;
  - `host.frame(..., on_context=…)` does the same for frames.
- **Versioning:** semantic versioning, this changelog, and **about ream** in
  the palette.

## [0.1.0] - 2026-10-20

Everything before versioning started.

- **The page:** one page on an infinite canvas. Words flow onto new pages,
  `⌘←` `⌘→` turn pages, and there are spread, all-pages and preview views,
  plus write mode and spelling.
- **Pages:** the pages panel (reorder, add and delete pages; cover and back
  cover), and the page panel (size, margins, type, paper stock and its
  blend, ink).
- **Objects:** images and PDFs on the canvas. Dropped on the page they are
  pinned and exported. They rotate, stack and go behind the words.
- **Writer and design modes:**
  - design mode selects, draws marquees and makes text boxes;
  - the text panel styles a text box, the main text, or selected words
    (font, size, line, align, track, weight, italic);
  - the main text gets alignment and letter spacing.
- **Distress:** the Texturelabs Distressor's textures, a live distress view,
  and the distress panel.
- **Export:** the export panel, with a page map for picking pages, single
  pages or spreads, distressed or clean, paper stock or plain, PDF or PNG,
  and dpi.
- **Profiles,** the Tab palette, themes and canvas colours.
- **Plugins:**
  - stik: cuts, wand, eraser, background removal, islands, sticker borders,
    exporting pieces;
  - scanner: a slit scanner;
  - impose: imposition for saddle stitch, perfect bound, sewn signatures,
    cut & stack and the mini zine, with printer and turn guides, an export
    bundle, and printing with a guided card that minimises to a panel,
    including draft and test prints.

[Unreleased]: #unreleased
[0.7.0]: #070---2026-10-20
[0.6.0]: #060---2026-10-20
[0.5.5]: #055---2026-10-20
[0.5.4]: #054---2026-10-20
[0.5.3]: #053---2026-10-20
[0.5.2]: #052---2026-10-20
[0.5.1]: #051---2026-10-20
[0.5.0]: #050---2026-10-20
[0.4.2]: #042---2026-10-20
[0.4.1]: #041---2026-10-20
[0.4.0]: #040---2026-10-20
[0.3.1]: #031---2026-10-20
[0.3.0]: #030---2026-10-20
[0.2.0]: #020---2026-10-20
[0.1.0]: #010---2026-10-20
