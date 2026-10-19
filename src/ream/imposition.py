"""
Imposition: which page goes where on which side of which sheet.

Pure logic - no Qt.  `impose(pages, style)` lays a document's pages out on
printer sheets for a binding style, padding with blank pages where the style
needs a multiple of 4 (or 8).  Every side is described as the person holding
the sheet sees it:

- a front, face up;
- a back, after turning the sheet over its *side* (short) edge.  The paper
  goes through the printer short edge first, so how the backs must be turned
  depends on which edge of the paper you turn it over: see `back_turn`.

Each page sits in a cell of the side's grid, maybe upside down (a mini zine's
top row), pushed against the fold in folded styles so the gutter is at the
spine.  Blank pages, when the style needs them, go before the back cover so
it stays on the outside (`keep_back`), or at the end.

| style       | sheet          | how it is made |
| ----------- | -------------- | -------------- |
| saddle      | 2 up, both sides | all sheets nested, folded together, stapled through the fold |
| perfect     | 2 up, both sides | each sheet folded on its own, the folded sheets stacked, glued at the spine |
| signatures  | 2 up, both sides | sheets nested in groups (signatures), each folded, groups stacked and sewn |
| cutstack    | 2 up, both sides | printed, cut in half, the right pile put under the left: the leaves come out in order |
| zine8       | 4 x 2, one side  | one sheet, one cut, folded into an eight-page mini zine |
"""
from __future__ import annotations

from dataclasses import dataclass, field

STYLES = {
    "saddle": ("saddle stitch", "booklets and zines: sheets nested, folded, stapled through the fold"),
    "perfect": ("perfect bound", "each sheet folded on its own, stacked, glued at the spine"),
    "signatures": ("sewn signatures", "sheets nested in groups, each group folded, groups sewn"),
    "cutstack": ("cut & stack", "printed 2 up, cut in half, right pile under left: leaves in order"),
    "zine8": ("mini zine · 8 pages", "one sheet, one side, one cut, folded"),
}
SHEETS = {"a4": (841.890, 595.276), "letter": (792.0, 612.0), "a3": (1190.551, 841.890),
          "tabloid": (1224.0, 792.0)}          # landscape, points
PRINTING = {
    "single-long": "single-sided · turn over the long edge",
    "single-short": "single-sided · turn over the short edge",
    "duplex-short": "duplex · flip on short edge",
    "duplex-long": "duplex · flip on long edge",
}
OLD_PRINTING = {"single-side": "single-short", "single-top": "single-long"}   # earlier names


@dataclass
class Cell:
    page: int | None             # 0-based page, None: a blank
    col: int
    row: int
    turn: int = 0                # degrees: 180 for upside down
    align: str = "center"        # "left" / "right": pushed to that side (to the fold)


@dataclass
class Sheet:
    number: int
    front: list[Cell] = field(default_factory=list)
    back: list[Cell] | None = None        # None: printed on one side only


@dataclass
class Layout:
    style: str
    cols: int
    rows: int
    pages: int                   # the document's pages
    padded: int                  # with blanks added
    sheets: list[Sheet]
    folds: list[tuple[str, float]]        # ("v", x) / ("h", y): fractions of the sheet
    cuts: list[tuple[str, float, float, float]]   # ("h", y, x0, x1) / ("v", x, y0, y1)
    per_signature: int = 4
    keep_back: bool = True

    @property
    def two_sided(self) -> bool:
        return any(s.back is not None for s in self.sheets)


def _round_up(n: int, k: int) -> int:
    return max(k, -(-n // k) * k)


class _Slots:
    """Which page goes in each slot of the padded run.  With `keep_back` the
    blanks go before the last page, so the back cover stays on the outside
    (as booklet tools do); else they go at the end."""

    def __init__(self, pages: int, padded: int, keep_back: bool):
        self.pages, self.padded = pages, padded
        self.keep_back = keep_back and pages >= 2 and padded > pages

    def __call__(self, slot: int) -> int | None:
        if not self.keep_back:
            return slot if slot < self.pages else None
        if slot < self.pages - 1:
            return slot
        return self.pages - 1 if slot == self.padded - 1 else None


def _folio(sheet_no: int, left_front: int, right_front: int, left_back: int, right_back: int,
           page) -> Sheet:
    """A 2-up sheet folded down the middle: pages pushed against the fold."""
    return Sheet(sheet_no,
                 front=[Cell(page(left_front), 0, 0, align="right"),
                        Cell(page(right_front), 1, 0, align="left")],
                 back=[Cell(page(left_back), 0, 0, align="right"),
                       Cell(page(right_back), 1, 0, align="left")])


def impose(pages: int, style: str, per_signature: int = 4, keep_back: bool = True) -> Layout:
    pages = max(1, pages)
    if style == "zine8":
        padded = _round_up(pages, 8)
        page = _Slots(pages, padded, keep_back)
        sheets = []
        for k in range(padded // 8):
            p = [8 * k + i for i in range(8)]
            # top row upside down: 5 4 3 2; bottom row: 6 7 8 1 (back cover, front cover)
            top = [p[4], p[3], p[2], p[1]]
            bottom = [p[5], p[6], p[7], p[0]]
            cells = [Cell(page(n), c, 0, turn=180) for c, n in enumerate(top)]
            cells += [Cell(page(n), c, 1) for c, n in enumerate(bottom)]
            sheets.append(Sheet(k + 1, front=cells, back=None))
        return Layout(style, 4, 2, pages, padded, sheets,
                      folds=[("h", 0.5), ("v", 0.25), ("v", 0.5), ("v", 0.75)],
                      cuts=[("h", 0.5, 0.25, 0.75)], keep_back=keep_back)
    padded = _round_up(pages, 4)
    if style == "signatures":
        group = max(1, per_signature) * 4
        padded = _round_up(pages, group) if pages > group else _round_up(pages, 4)
    page = _Slots(pages, padded, keep_back)
    sheets: list[Sheet] = []
    if style == "saddle":
        n = padded
        for i in range(n // 4):
            sheets.append(_folio(i + 1, n - 1 - 2 * i, 2 * i, 2 * i + 1, n - 2 - 2 * i, page))
    elif style == "perfect":
        for i in range(padded // 4):
            a = 4 * i
            sheets.append(_folio(i + 1, a + 3, a, a + 1, a + 2, page))
    elif style == "signatures":
        number = 1
        for start in range(0, padded, group):
            n = min(group, padded - start)
            for i in range(n // 4):
                sheets.append(_folio(number, start + n - 1 - 2 * i, start + 2 * i,
                                     start + 2 * i + 1, start + n - 2 - 2 * i, page))
                number += 1
    elif style == "cutstack":
        half = padded // 2
        for i in range(padded // 4):
            sheets.append(Sheet(i + 1,
                                front=[Cell(page(2 * i), 0, 0),
                                       Cell(page(half + 2 * i), 1, 0)],
                                back=[Cell(page(half + 2 * i + 1), 0, 0),
                                      Cell(page(2 * i + 1), 1, 0)]))
        return Layout(style, 2, 1, pages, padded, sheets, folds=[],
                      cuts=[("v", 0.5, 0.0, 1.0)], keep_back=keep_back)
    else:
        raise ValueError(f"unknown imposition style: {style}")
    return Layout(style, 2, 1, pages, padded, sheets, folds=[("v", 0.5)], cuts=[],
                  per_signature=per_signature, keep_back=keep_back)


def back_turn(printing: str) -> int:
    """How far the backs must be turned for the way the paper is turned over.

    Printers feed paper short edge first, so these landscape sheets go
    through sideways: the paper's long edges are the sheet's top and bottom.
    Turning the paper over its long edge (like a book's page, as it lies in
    front of you) - or a duplex printer flipping on the long edge - turns the
    sheet top to bottom, so the backs are printed turned 180°.  Over the
    short edge (like a calendar), or a short-edge flip, they need nothing."""
    printing = OLD_PRINTING.get(printing, printing)
    return 180 if printing in ("single-long", "duplex-long") else 0


def reading_order(layout: Layout) -> list[int]:
    """The pages in the order they come out once the sheets are printed,
    folded (or cut) and bound - for checking an imposition."""
    style = layout.style
    if style == "zine8":
        slots = _Slots(layout.pages, layout.padded, layout.keep_back)
        return [slots(p) for p in range(layout.padded)]
    if style == "cutstack":
        left = [p for s in layout.sheets for p in (s.front[0].page, s.back[1].page)]
        right = [p for s in layout.sheets for p in (s.front[1].page, s.back[0].page)]
        return left + right
    # folded styles: within a nest (all sheets for saddle, a group for
    # signatures, one sheet for perfect), read the right halves of the fronts
    # down the nest, then the backs back up
    nests: list[list[Sheet]]
    if style == "perfect":
        nests = [[s] for s in layout.sheets]
    elif style == "saddle":
        nests = [layout.sheets]
    else:
        nests, current = [], []
        for s in layout.sheets:
            current.append(s)
            if len(current) * 4 == _nest_size(layout, len(nests)):
                nests.append(current)
                current = []
        if current:
            nests.append(current)
    order: list[int | None] = []
    for nest in nests:
        first = []
        for s in nest:
            first += [s.front[1].page, s.back[0].page]
        second = []
        for s in reversed(nest):
            second += [s.back[1].page, s.front[0].page]
        order += first + second
    return order


def _nest_size(layout: Layout, index: int) -> int:
    """Pages in signature `index` (the last may be shorter)."""
    total = layout.padded
    group = 4 * max(1, layout.per_signature)
    start = index * group
    return min(group, total - start)
