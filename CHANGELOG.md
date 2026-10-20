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
[0.2.0]: #020---2026-10-20
[0.1.0]: #010---2026-10-20
