"""
Impose: the pages laid out on printer sheets for binding, and everything
needed to print them - by yourself on a one-sided printer, or as a bundle
for someone else.

`⌥⌘I` (or **impose** in the palette) opens the panel and the imposition
preview: each sheet's front and back side by side, the pages in place, big
page numbers over them, fold and cut lines, and a how-to-print guide (G).

Styles (see ream/imposition.py): saddle stitch, perfect bound, sewn
signatures, cut & stack, and the eight-page mini zine.

The default workflow is a single-sided printer (fed short edge first, from
a tray at the back, out to you at the front): print the fronts, turn the
stack over, print the backs.  The guide draws the printer and the turn, and
a two-sided test sheet checks how your printer feeds before you use real
paper.  Duplex printers are covered too.

**export bundle…** writes a folder to hand to anyone:

    1-fronts.pdf      the fronts of every sheet, in order
    2-backs.pdf       the backs, turned and ordered for the chosen way of turning
    duplex.pdf        fronts and backs interleaved, for a duplex printer
    guide.pdf         how to print, a sheet-by-sheet page map, how to fold and bind
    test-front.pdf    a test sheet's two sides, to check the printer
    test-back.pdf
    README.txt        the same steps in words
"""
from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import replace

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import export, imposition, printing, style
from ..panel import _Link
from ..plugin import Plugin as Base

DEFAULTS = {"style": "saddle", "sheet": "a4", "fit": True, "printing": "single-long",
            "reverse": False, "marks": True, "per_signature": 4, "keep_back": True}
INK = QtGui.QColor(style.INK)
GREY = QtGui.QColor("#8c8b86")
LINE = QtGui.QColor("#2f4bd8")


# -- drawing sheets ---------------------------------------------------------------

def page_rect(cell_rect: QtCore.QRectF, page_w: float, page_h: float, align: str,
              fit: bool) -> QtCore.QRectF:
    """Where a page lands in its cell: scaled to fit (or at 100%), pushed
    to the fold side for folded styles, centred otherwise."""
    k = min(cell_rect.width() / page_w, cell_rect.height() / page_h)
    if not fit:
        k = min(1.0, k) if k < 1.0 else 1.0
    w, h = page_w * k, page_h * k
    if align == "left":
        x = cell_rect.left()
    elif align == "right":
        x = cell_rect.right() - w
    else:
        x = cell_rect.center().x() - w / 2
    return QtCore.QRectF(x, cell_rect.center().y() - h / 2, w, h)


def draw_side(painter: QtGui.QPainter, target: QtCore.QRectF, layout: imposition.Layout,
              cells: list[imposition.Cell], sheet_size: tuple[float, float],
              page_size: tuple[float, float], draw_page, *, fit: bool = True,
              turn: int = 0, numbers: bool = False, marks: bool = True, total: int = 0):
    """One side of a sheet into `target` (its own coordinates scaled to fit).
    `draw_page(painter, rect, page)` puts a page into a rect; `turn` 180
    turns the whole side (backs for a top-edge turn)."""
    sw, sh = sheet_size
    painter.save()
    painter.translate(target.topLeft())
    painter.scale(target.width() / sw, target.height() / sh)
    if turn:
        painter.translate(sw / 2, sh / 2)
        painter.rotate(turn)
        painter.translate(-sw / 2, -sh / 2)
    cw, ch = sw / layout.cols, sh / layout.rows
    for cell in cells:
        box = QtCore.QRectF(cell.col * cw, cell.row * ch, cw, ch)
        rect = page_rect(box, page_size[0], page_size[1], cell.align, fit)
        painter.save()
        painter.setClipRect(box)
        if cell.turn:
            painter.translate(box.center())
            painter.rotate(cell.turn)
            painter.translate(-box.center())
        if cell.page is not None:
            draw_page(painter, rect, cell.page)
        if numbers:
            draw_number(painter, rect, cell.page, total)
        painter.restore()
    if marks:
        draw_marks(painter, layout, sw, sh)
    painter.restore()


def draw_number(painter: QtGui.QPainter, rect: QtCore.QRectF, page: int | None, total: int):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    r = min(rect.width(), rect.height()) * 0.17
    centre = rect.center()
    painter.setPen(QtGui.QPen(INK, max(0.5, r * 0.04)))
    painter.setBrush(QtGui.QColor(255, 255, 255, 225))
    painter.drawEllipse(centre, r, r)
    font = style.ui_font(1)
    font.setPixelSize(max(1, int(r * (0.8 if page is not None else 0.42))))
    painter.setFont(font)
    painter.setPen(INK if page is not None else GREY)
    text = f"{page + 1}" if page is not None else "blank"
    painter.drawText(QtCore.QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r),
                     QtCore.Qt.AlignCenter, text)
    if page == 0 or (total and page == total - 1):
        font.setPixelSize(max(1, int(r * 0.28)))
        painter.setFont(font)
        painter.setPen(GREY)
        painter.drawText(QtCore.QRectF(centre.x() - 2 * r, centre.y() + r * 1.05, 4 * r, r * 0.6),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                         "front cover" if page == 0 else "back cover")
    painter.restore()


def outline_text(painter: QtGui.QPainter, rect: QtCore.QRectF, text: str, size: float,
                 width: float = 0.5):
    """Words as hairline outlines, centred in rect: big, but next to no ink."""
    font = style.ui_font(1)
    font.setPixelSize(max(1, int(size)))
    path = QtGui.QPainterPath()
    path.addText(0, 0, font, text)
    box = path.boundingRect()
    path.translate(rect.center() - box.center())
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(INK, width))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def draft_page(total: int):
    """A page drawer for a draft print: the page's outline, its number in
    hairline outline and a tick at its top - enough to check the order, the
    turn and the fold, for next to no ink."""
    def draw(painter: QtGui.QPainter, rect: QtCore.QRectF, page: int):
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(INK, 0.4))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect.adjusted(6, 6, -6, -6))
        side = min(rect.width(), rect.height())
        outline_text(painter, rect, f"{page + 1}", side * 0.34, 0.6)
        top = QtCore.QPointF(rect.center().x(), rect.top() + side * 0.06)
        painter.setPen(QtGui.QPen(INK, 0.6))
        _arrow(painter, top + QtCore.QPointF(0, side * 0.08), top, side * 0.025)
        words = "front cover" if page == 0 else "back cover" if total and page == total - 1 else ""
        if words:
            outline_text(painter, QtCore.QRectF(rect.left(), rect.center().y() + side * 0.22,
                                                rect.width(), side * 0.1), words, side * 0.06, 0.4)
        painter.restore()
    return draw


def draw_marks(painter: QtGui.QPainter, layout: imposition.Layout, sw: float, sh: float):
    """Fold marks (short ticks at the edges) and cut lines (dashed)."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    tick = 16.0
    painter.setPen(QtGui.QPen(GREY, 0.6))
    for kind, at in layout.folds:
        if kind == "v":
            x = at * sw
            painter.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, tick))
            painter.drawLine(QtCore.QPointF(x, sh - tick), QtCore.QPointF(x, sh))
        else:
            y = at * sh
            painter.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(tick, y))
            painter.drawLine(QtCore.QPointF(sw - tick, y), QtCore.QPointF(sw, y))
    pen = QtGui.QPen(INK, 0.7, QtCore.Qt.CustomDashLine)
    pen.setDashPattern([6, 4])
    painter.setPen(pen)
    for kind, at, a, b in layout.cuts:
        if kind == "h":
            painter.drawLine(QtCore.QPointF(a * sw, at * sh), QtCore.QPointF(b * sw, at * sh))
        else:
            painter.drawLine(QtCore.QPointF(at * sw, a * sh), QtCore.QPointF(at * sw, b * sh))
    painter.restore()


# -- the guide's drawings ------------------------------------------------------------

def _pen(painter, width=1.2, colour=INK, dash=False):
    pen = QtGui.QPen(colour, width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    if dash:
        pen.setStyle(QtCore.Qt.CustomDashLine)
        pen.setDashPattern([3, 3])
    painter.setPen(pen)


def _arrow(painter, a: QtCore.QPointF, b: QtCore.QPointF, size: float = 6.0):
    painter.drawLine(a, b)
    angle = math.atan2(b.y() - a.y(), b.x() - a.x())
    for side in (-1, 1):
        t = angle + math.pi + side * 0.45
        painter.drawLine(b, QtCore.QPointF(b.x() + size * math.cos(t), b.y() + size * math.sin(t)))


DOT = QtGui.QColor("#2f4bd8")


def _poly(*points) -> QtGui.QPolygonF:
    return QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points])


def _dot(painter: QtGui.QPainter, at: QtCore.QPointF, r: float):
    painter.save()
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(DOT)
    painter.drawEllipse(at, r, r)
    painter.restore()


def draw_facing_printer(painter: QtGui.QPainter, rect: QtCore.QRectF, *, tray: str = "",
                        tray_dot: str = "", out: str = "", out_dot: bool = False,
                        feed: bool = False, deliver: bool = False, lift: bool = False):
    """A printer as you see it standing in front of it.  The paper stands
    upright in a tray at the back and goes in short edge first; the printed
    sheets come out towards you onto the tray at the front, short edge
    first.  `tray` / `out` label the paper there ("" none); `tray_dot`
    ("bottom" / "top") and `out_dot` mark the followed edge."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    x, y, w, h = rect.left(), rect.top(), rect.width(), rect.height()
    X = lambda f: x + f * w                                  # noqa: E731
    Y = lambda f: y + f * h                                  # noqa: E731
    _pen(painter, 1.3)
    paper = QtGui.QColor("#ffffff")
    # the back tray, rising behind the printer; the paper stands in it upright
    painter.setBrush(QtGui.QColor("#f1efe9"))
    painter.drawPolygon(_poly((X(.34), Y(.36)), (X(.36), Y(.0)), (X(.64), Y(.0)), (X(.66), Y(.36))))
    if tray:
        painter.setBrush(paper)
        painter.drawPolygon(_poly((X(.38), Y(.34)), (X(.39), Y(.03)), (X(.61), Y(.03)), (X(.62), Y(.34))))
        painter.setFont(style.ui_font(max(8, int(h * .06))))
        painter.drawText(QtCore.QRectF(X(.39), Y(.05), X(.61) - X(.39), Y(.32) - Y(.05)),
                         QtCore.Qt.AlignCenter, tray)
        if tray_dot:
            _dot(painter, QtCore.QPointF(X(.5), Y(.34) if tray_dot == "bottom" else Y(.03)), h * .022)
    # the body, just wider than the paper: its top, then its front and slot
    painter.setBrush(paper)
    painter.drawPolygon(_poly((X(.20), Y(.44)), (X(.29), Y(.35)), (X(.71), Y(.35)), (X(.80), Y(.44))))
    painter.drawRoundedRect(QtCore.QRectF(X(.20), Y(.44), X(.80) - X(.20), Y(.60) - Y(.44)), 4, 4)
    painter.drawLine(QtCore.QPointF(X(.34), Y(.57)), QtCore.QPointF(X(.66), Y(.57)))
    # the front tray, reaching towards you; the paper comes out short edge first
    painter.setBrush(QtGui.QColor("#f1efe9"))
    painter.drawPolygon(_poly((X(.34), Y(.57)), (X(.66), Y(.57)), (X(.72), Y(.90)), (X(.28), Y(.90))))
    if out:
        painter.setBrush(paper)
        _pen(painter, 1.0)
        for k in (2, 1, 0):                                   # a little stack
            d = k * h * .008
            painter.drawPolygon(_poly((X(.37), Y(.58) - d), (X(.63), Y(.58) - d),
                                      (X(.68), Y(.87) - d), (X(.32), Y(.87) - d)))
        painter.setFont(style.ui_font(max(8, int(h * .06))))
        painter.drawText(QtCore.QRectF(X(.37), Y(.60), X(.63) - X(.37), Y(.85) - Y(.60)),
                         QtCore.Qt.AlignCenter, out)
        if out_dot:
            _dot(painter, QtCore.QPointF(X(.5), Y(.87)), h * .022)
    _pen(painter, 1.6, LINE)
    if feed:                                                  # into the printer at the back
        _arrow(painter, QtCore.QPointF(X(.80), Y(.02)), QtCore.QPointF(X(.69), Y(.28)), h * .04)
    if deliver:                                               # out to you at the front
        _arrow(painter, QtCore.QPointF(X(.80), Y(.62)), QtCore.QPointF(X(.86), Y(.90)), h * .04)
    if lift:                                                  # take the stack out, towards you
        _arrow(painter, QtCore.QPointF(X(.76), Y(.74)), QtCore.QPointF(X(.90), Y(.96)), h * .04)
    painter.setFont(style.ui_font(max(7, int(h * .045))))
    painter.setPen(GREY)
    painter.drawText(QtCore.QRectF(X(.67), Y(.04), X(1.0) - X(.67), h * .08),
                     QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "back")
    painter.drawText(QtCore.QRectF(x, Y(.90), w, h * .10),
                     QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, "you ↓")
    painter.restore()


def draw_stack_turn(painter: QtGui.QPainter, rect: QtCore.QRectF, edge: str):
    """The stack lying in front of you as it came out - upright, short edge
    nearest you (marked), printed side (A) up - turned over its long edge
    like a book's page (the mark stays near you) or over its short edge like
    a calendar (the mark goes to the far side)."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    w, h = rect.width(), rect.height()
    sw = min(w * .26, h * .62 / 1.414)                     # upright sheets, room between
    sh = sw * 1.414
    top = rect.top() + h * .22
    a = QtCore.QRectF(rect.left() + w * .1, top, sw, sh)
    b = QtCore.QRectF(rect.right() - w * .1 - sw, top, sw, sh)
    for sheet, label in ((a, "A"), (b, "blank")):
        _pen(painter, 1.3)
        painter.setBrush(QtGui.QColor("#ffffff"))
        for k in (2, 1, 0):
            painter.drawRect(sheet.translated(k * 2.0, -k * 2.0))
        painter.setFont(style.ui_font(max(8, int(sw * (.3 if label == "A" else .2)))))
        painter.drawText(sheet, QtCore.Qt.AlignCenter, label)
    dot_r = h * .022
    _dot(painter, QtCore.QPointF(a.center().x(), a.bottom()), dot_r)
    _dot(painter, QtCore.QPointF(b.center().x(), b.bottom() if edge == "long" else b.top()), dot_r)
    _pen(painter, 2.0, LINE)
    if edge == "long":
        painter.drawLine(a.topRight(), a.bottomRight())          # the edge it turns over
        path = QtGui.QPainterPath(QtCore.QPointF(a.center().x(), a.top() - h * .05))
        path.quadTo(QtCore.QPointF(rect.center().x(), rect.top() - h * .02),
                    QtCore.QPointF(b.center().x(), b.top() - h * .05))
    else:
        painter.drawLine(a.topLeft(), a.topRight())
        path = QtGui.QPainterPath(QtCore.QPointF(a.right() + w * .02, a.bottom()))
        path.cubicTo(QtCore.QPointF(rect.center().x() - w * .04, a.bottom() + h * .04),
                     QtCore.QPointF(rect.center().x() + w * .04, a.top() - h * .10),
                     QtCore.QPointF(b.left() - w * .02, b.top()))
    painter.setBrush(QtCore.Qt.NoBrush)
    _pen(painter, 1.4, LINE)
    painter.drawPath(path)
    _arrow(painter, path.pointAtPercent(.9), path.pointAtPercent(1.0), h * .04)
    painter.setFont(style.ui_font(max(7, int(h * .045))))
    painter.setPen(GREY)
    painter.drawText(QtCore.QRectF(rect.left(), a.bottom() + h * .04, rect.width(), h * .08),
                     QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, "you ↓")
    painter.restore()


def draw_print_steps(painter: QtGui.QPainter, rect: QtCore.QRectF, edge: str, words: QtGui.QColor,
                     backs_reversed: bool = False, only: tuple[int, ...] = (1, 2, 3, 4)):
    """The single-sided routine in four drawings, seen from in front of the
    printer: in a row when there is room, else two by two.  `only` picks
    some of them (the print card shows just the turn: 2, 3, 4)."""
    turn = "long edge, like a book's page" if edge == "long" else "short edge, like a calendar"
    panels = [
        ("1 · print 1-fronts.pdf: the paper goes in at the back and comes out to you",
         lambda r: draw_facing_printer(painter, r, tray="blank", out="A", feed=True, deliver=True)),
        ("2 · take the stack out of the front tray just as it is. ● is the edge nearest you",
         lambda r: draw_facing_printer(painter, r, out="A", out_dot=True, lift=True)),
        (f"3 · turn the whole stack over its {turn}",
         lambda r: draw_stack_turn(painter, r, edge)),
        ("4 · stand it in the back tray, blank side facing you, the edge nearest you going in "
         f"first - then print 2-backs.pdf{' (reversed)' if backs_reversed else ''}",
         lambda r: draw_facing_printer(painter, r, tray="blank", feed=True,
                                       tray_dot="bottom" if edge == "long" else "top")),
    ]
    panels = [panel for n, panel in enumerate(panels, 1) if n in only]
    cols = len(panels) if rect.width() / max(1.0, rect.height()) > 0.55 * len(panels) else 2
    rows = -(-len(panels) // cols)
    gap = 18.0
    cw = (rect.width() - gap * (cols - 1)) / cols
    ch = (rect.height() - gap * (rows - 1)) / rows
    art = ch * .7
    for i, (caption, draw) in enumerate(panels):
        cell = QtCore.QRectF(rect.left() + (i % cols) * (cw + gap),
                             rect.top() + (i // cols) * (ch + gap), cw, art)
        dw = min(cw, art * 1.15)                              # keep the drawing's proportions
        draw(QtCore.QRectF(cell.center().x() - dw / 2, cell.top(), dw, art))
        painter.save()
        painter.setFont(style.ui_font(max(8, min(11, int(ch * .055)))))
        painter.setPen(words)
        painter.drawText(QtCore.QRectF(cell.left(), cell.bottom() + 4, cw, ch - art - 4),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, caption)
        painter.restore()


def draw_binding(painter: QtGui.QPainter, rect: QtCore.QRectF, style_key: str):
    """A small drawing of how the sheets become a book."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    _pen(painter, 1.4)
    painter.setBrush(QtGui.QColor("#ffffff"))
    w, h = rect.width(), rect.height()
    c = rect.center()
    if style_key in ("saddle", "signatures", "perfect"):
        groups = {"saddle": 1, "signatures": 3, "perfect": 4}[style_key]
        for g in range(groups):
            off = (g - (groups - 1) / 2) * w * 0.07
            book = QtGui.QPolygonF([QtCore.QPointF(c.x() + off, c.y() - h * 0.28),
                                    QtCore.QPointF(c.x() + off + w * 0.28, c.y() - h * 0.2),
                                    QtCore.QPointF(c.x() + off + w * 0.28, c.y() + h * 0.28),
                                    QtCore.QPointF(c.x() + off, c.y() + h * 0.2)])
            painter.drawPolygon(book)
            mirror = QtGui.QPolygonF([QtCore.QPointF(c.x() + off, c.y() - h * 0.28),
                                      QtCore.QPointF(c.x() + off - w * 0.28, c.y() - h * 0.2),
                                      QtCore.QPointF(c.x() + off - w * 0.28, c.y() + h * 0.28),
                                      QtCore.QPointF(c.x() + off, c.y() + h * 0.2)])
            painter.drawPolygon(mirror)
        _pen(painter, 2.6, LINE)
        if style_key == "saddle":
            for t in (-0.12, 0.08):
                painter.drawLine(QtCore.QPointF(c.x(), c.y() + h * t), QtCore.QPointF(c.x(), c.y() + h * (t + 0.06)))
        else:
            painter.drawLine(QtCore.QPointF(c.x() - w * 0.12, c.y() + h * 0.24),
                             QtCore.QPointF(c.x() + w * 0.12, c.y() + h * 0.24))
    elif style_key == "cutstack":
        sheet = QtCore.QRectF(rect.left() + w * 0.06, c.y() - h * 0.22, w * 0.42, h * 0.44)
        painter.drawRect(sheet)
        _pen(painter, 1.2, LINE, dash=True)
        painter.drawLine(QtCore.QPointF(sheet.center().x(), sheet.top()),
                         QtCore.QPointF(sheet.center().x(), sheet.bottom()))
        _pen(painter, 1.4)
        for i, label in enumerate(("L", "R")):
            pile = QtCore.QRectF(rect.left() + w * (0.58 + 0.06 * i), c.y() - h * 0.22 + i * h * 0.1,
                                 w * 0.2, h * 0.34)
            painter.drawRect(pile)
            painter.drawText(pile, QtCore.Qt.AlignCenter, label)
    else:                                       # zine8
        sheet = QtCore.QRectF(c.x() - w * 0.36, c.y() - h * 0.24, w * 0.72, h * 0.48)
        painter.drawRect(sheet)
        _pen(painter, 0.8, GREY, dash=True)
        for k in (1, 2, 3):
            x = sheet.left() + sheet.width() * k / 4
            painter.drawLine(QtCore.QPointF(x, sheet.top()), QtCore.QPointF(x, sheet.bottom()))
        painter.drawLine(QtCore.QPointF(sheet.left(), sheet.center().y()),
                         QtCore.QPointF(sheet.right(), sheet.center().y()))
        _pen(painter, 2.4, LINE)
        painter.drawLine(QtCore.QPointF(sheet.left() + sheet.width() / 4, sheet.center().y()),
                         QtCore.QPointF(sheet.right() - sheet.width() / 4, sheet.center().y()))
    painter.restore()


def _caption(painter: QtGui.QPainter, rect: QtCore.QRectF, words: str):
    """A drawing's caption under it, wrapped to its width."""
    painter.setFont(style.ui_font(max(8, min(12, int(rect.height() * 0.06)))))
    painter.setPen(GREY)
    painter.drawText(QtCore.QRectF(rect.left(), rect.bottom() - rect.height() * 0.2,
                                   rect.width(), rect.height() * 0.24),
                     QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, words)


def _write(painter: QtGui.QPainter, left: float, top: float, width: float, text: str) -> float:
    """Wrapped text from (left, top); returns the y under it."""
    box = painter.boundingRect(QtCore.QRectF(left, top, width, 1000),
                               QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, text)
    painter.drawText(QtCore.QRectF(left, top, width, box.height() + 2),
                     QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, text)
    return top + box.height()


PRINT_STEPS = {
    "single": [
        "print 1-fronts.pdf: the paper goes in at the back and comes out to you at the front",
        "take the printed stack out of the front tray just as it is - don't shuffle it",
        "turn the whole stack over its {edge}",
        "stand it in the back tray: blank side facing you, the edge nearest you going in first",
        "print 2-backs.pdf",
    ],
    "duplex": ["print duplex.pdf two-sided, {flip}"],
    "one": ["print 1-fronts.pdf - one side only"],
}
BIND_STEPS = {
    "saddle": ["stack the sheets in order, sheet 1 at the bottom, fronts facing down",
               "fold the whole stack in half along the middle",
               "staple twice through the fold (a long-reach stapler, or stitch it)"],
    "perfect": ["fold each sheet in half on its own, front outside",
                "stack the folded sheets in order, sheet 1 on top",
                "square the folds into a spine, clamp, glue, add a cover"],
    "signatures": ["each group of {per} sheets is a signature: nest it in order, first sheet outside",
                   "fold each signature in half",
                   "stack the signatures in order and sew through the folds (or glue the spine)"],
    "cutstack": ["cut every sheet in half down the middle (the dashed line)",
                 "keep two piles in order, sheet 1 on top: left halves and right halves",
                 "put the right pile under the left one",
                 "bind the left edge: staples, stab-sewing or glue"],
    "zine8": ["fold the sheet in half the long way, then open it",
              "fold it in half the short way, then in half again, and open it",
              "cut along the dashed line - the middle two panels only",
              "fold the long way again, push the ends in so the cut opens into a diamond",
              "fold it flat into a booklet, page 1 on the outside"],
}


# -- the imposition view -------------------------------------------------------------

class ImposeView(QtWidgets.QWidget):
    """Full window: the current sheet's front and back, or the guide."""

    def __init__(self, plugin):
        super().__init__(plugin.host.window)
        self.plugin = plugin
        self.sheet_index = 0
        self.numbers = True
        self.guide = False
        self.thumbs: dict[tuple, QtGui.QImage] = {}
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.hide()

    def open(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        panel = self.plugin.panel
        if panel.isVisible():
            panel.raise_()
        self.setFocus()

    def thumb(self, page: int, px_w: float) -> QtGui.QImage:
        c = self.plugin.host.window
        dpi = max(48.0, min(200.0, px_w / c.sheet.W * 72.0 * self.devicePixelRatioF()))
        key = (page, round(dpi), c.doc.revision(), c.things_key(), tuple(vars(c.fmt).items()))
        if key not in self.thumbs:
            if len(self.thumbs) > 64:
                self.thumbs.clear()
            self.thumbs[key] = export.final_page(c.sheet, page, dpi, replace(c.distress, enabled=False),
                                                 c.paper(), c.ink(), c.density(), c.paper_stock())
        return self.thumbs[key]

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        c = self.plugin.host.window
        backdrop = QtGui.QColor(c.canvas_colour())
        painter.fillRect(self.rect(), backdrop)
        meta = QtGui.QColor("#b8b6b0" if backdrop.lightness() < 128 else "#77766f")
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.guide:
            self.plugin.draw_guide(painter, self.room().adjusted(40, 40, -40, -60), meta)
        else:
            self.paint_sheets(painter, meta)
        painter.setFont(style.ui_font(11))
        painter.setPen(meta)
        hint = "← → sheets  ·  N numbers  ·  G how to print  ·  Esc back to writing"
        painter.drawText(QtCore.QRectF(self.rect()).adjusted(0, 0, 0, -14),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom, hint)

    def room(self) -> QtCore.QRectF:
        """The window, less the impose panel when it stands at one side."""
        room = QtCore.QRectF(self.rect())
        panel = self.plugin.panel
        if panel.isVisible():
            box = QtCore.QRectF(panel.geometry())
            if box.center().x() > room.center().x():
                room.setRight(box.left() - 8)
            else:
                room.setLeft(box.right() + 8)
        return room

    def paint_sheets(self, painter: QtGui.QPainter, meta: QtGui.QColor):
        p = self.plugin
        layout = p.layout()
        sheets = layout.sheets
        self.sheet_index = max(0, min(self.sheet_index, len(sheets) - 1))
        sheet = sheets[self.sheet_index]
        sw, sh = imposition.SHEETS[p.s["sheet"]]
        sides = [("front · side A", sheet.front, 0)]
        if sheet.back is not None:
            sides.append(("back · side B · as it is after turning the sheet over",
                          sheet.back, 0))
        area = self.room().adjusted(40, 70, -40, -60)
        gap = 40.0
        slot_w = (area.width() - gap * (len(sides) - 1)) / len(sides)
        k = min(slot_w / sw, area.height() / sh)
        c_size = (p.host.window.sheet.W, p.host.window.sheet.H)
        total = layout.pages
        painter.setFont(style.ui_font(12))
        painter.setPen(meta)
        title = (f"sheet {sheet.number} of {len(sheets)}  ·  "
                 f"{imposition.STYLES[layout.style][0]}  ·  {p.s['sheet']}  ·  "
                 f"{layout.pages} pages" + (f" + {layout.padded - layout.pages} blank"
                                            if layout.padded > layout.pages else ""))
        painter.drawText(self.room().adjusted(0, 22, 0, 0),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, title)
        for i, (label, cells, turn) in enumerate(sides):
            x = area.left() + i * (slot_w + gap) + (slot_w - sw * k) / 2
            target = QtCore.QRectF(x, area.center().y() - sh * k / 2, sw * k, sh * k)
            painter.fillRect(target, QtGui.QColor("#ffffff"))
            draw_side(painter, target, layout, cells, (sw, sh), c_size,
                      lambda pnt, rect, page: pnt.drawImage(rect, self.thumb(page, rect.width() * pnt.worldTransform().m11())),
                      fit=p.s["fit"], turn=turn, numbers=self.numbers, marks=p.s["marks"],
                      total=total)
            painter.setPen(QtGui.QPen(INK, 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(target)
            painter.setFont(style.ui_font(11))
            painter.setPen(meta)
            painter.drawText(QtCore.QRectF(target.left(), target.top() - 22, target.width(), 18),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom, label)

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.plugin.close()
        elif key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageDown,
                     QtCore.Qt.Key_Space):
            self.sheet_index += 1
            self.guide = False
        elif key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Up, QtCore.Qt.Key_PageUp):
            self.sheet_index -= 1
            self.guide = False
        elif key == QtCore.Qt.Key_N:
            self.numbers = not self.numbers
        elif key == QtCore.Qt.Key_G:
            self.guide = not self.guide
        else:
            super().keyPressEvent(event)
            return
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()

    def wheelEvent(self, event):
        event.accept()


# -- printing step by step ----------------------------------------------------------

class PrintFlow(QtWidgets.QFrame):
    """A card that prints the job step by step: send a side, follow it
    through the printer's queue, show the turn, send the other side.

    Printing takes a while, so the card folds away (− or Esc) into a small
    "printing" panel: the step, the printer's progress, `next` and `open`
    (the card again).  Meanwhile ream is yours - write, leave the imposition
    view; the queue is still followed and the next step waits for you.
    ↵ goes on.  `stop` (or the panel's ×) ends it; jobs already sent carry
    on in the printer's queue."""

    QSS = (f"#PrintCard {{ background: #ffffff; border: 1px solid {style.INK}; }}"
           f"QLabel {{ background: transparent; color: {style.INK}; }}"
           "#PrintCaption, #PrintStatus { color: #8c8b86; }")

    def __init__(self, plugin, printer: str, steps: list[tuple], draft: bool = False):
        super().__init__(plugin.host.window)
        self.plugin, self.printer, self.steps, self.draft = plugin, printer, steps, draft
        self.at = -1
        self.job = ""
        self.printed = False
        self.minimised = False
        self.setObjectName("PrintCard")
        self.setStyleSheet(self.QSS)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(20, 16, 20, 16)
        column.setSpacing(8)
        head = QtWidgets.QHBoxLayout()
        self.caption = QtWidgets.QLabel()
        self.caption.setObjectName("PrintCaption")
        self.caption.setFont(style.ui_font(11))
        fold = _Link("−")
        fold.setToolTip("minimise to a panel (Esc)")
        fold.clicked.connect(self.minimise)
        head.addWidget(self.caption, 1)
        head.addWidget(fold)
        self.title = QtWidgets.QLabel()
        self.title.setFont(style.ui_font(15))
        self.art = QtWidgets.QWidget()
        self.art.setMinimumHeight(230)
        self.art.paintEvent = self._paint_art
        self.status = QtWidgets.QLabel()
        self.status.setObjectName("PrintStatus")
        self.status.setFont(style.ui_font(12))
        self.status.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        self.go = _Link("")
        self.go.clicked.connect(self.advance)
        small = _Link("minimise")
        small.clicked.connect(self.minimise)
        stop = _Link("stop")
        stop.clicked.connect(self.close_card)
        row.addWidget(self.go)
        row.addStretch(1)
        row.addWidget(small)
        row.addWidget(stop)
        column.addLayout(head)
        for widget in (self.title, self.art, self.status):
            column.addWidget(widget)
        column.addLayout(row)
        self.poll = QtCore.QTimer(self, interval=1500)
        self.poll.timeout.connect(self._check)
        self.hide()

    # -- where it is ---------------------------------------------------------------
    def room(self) -> QtCore.QRectF:
        view = self.plugin.view
        return view.room() if view.isVisible() else QtCore.QRectF(self.parentWidget().rect())

    def start(self):
        self.restore()
        self.advance()

    def restore(self):
        """The full card, in the middle of the free room."""
        self.minimised = False
        self.plugin.print_panel.hide()
        room = self.room()
        w, h = int(min(760, room.width() - 48)), 420
        self.setGeometry(int(room.center().x() - w / 2), int(room.center().y() - h / 2), w, h)
        self.show()
        self.raise_()
        self.setFocus()

    def minimise(self):
        """Fold into the "printing" panel, bottom right, and give ream back."""
        self.minimised = True
        self.hide()
        panel = self.plugin.print_panel
        panel.refresh()
        panel.fit_height()
        if not panel.placed:
            host = panel.parentWidget().rect()
            panel.move(host.width() - panel.width() - 20, host.height() - panel.height() - 20)
            panel.placed = True
        panel.keep_inside()
        panel.show()
        panel.raise_()
        self._give_back_focus()

    def _give_back_focus(self):
        if self.plugin.view.isVisible():
            self.plugin.view.setFocus()
        else:
            self.plugin.host.window.focus_text()

    def sync(self):
        """Tell the panel (when folded) what the card now says."""
        panel = self.plugin.print_panel
        if self.minimised and panel.isVisible():
            panel.refresh()
            panel.fit_height()
            panel.keep_inside()
        self.art.update()

    # -- the steps -------------------------------------------------------------------
    def step(self) -> tuple:
        return self.steps[self.at]

    def next_word(self) -> str:
        """What going on does now: "next", "print the backs", "done"…"""
        return self.go.text().replace(" ↵", "")

    def advance(self):
        if self.at >= len(self.steps) - 1:
            self.close_card()
            return
        self.at += 1
        self.job, self.printed = "", False
        self.poll.stop()
        kind = self.step()[0]
        sheets = len(self.plugin.layout().sheets)
        self.caption.setText(f"print{' · draft' if self.draft else ''} · {self.printer} · "
                             f"step {self.at + 1} of {len(self.steps)}")
        if kind == "send":
            _kind, what, path, sides, _label = self.step()
            self.title.setText(f"printing {what}")
            try:
                self.job = printing.send(path, self.printer, media=self.plugin.s["sheet"],
                                         sides=sides, title=f"ream · {what}", draft=self.draft)
                self.sent = (f"sent{' as job ' + self.job if self.job else ''} · "
                             f"{sheets} sheet{'s' if sheets != 1 else ''}")
                self.status.setText(f"{self.sent} · printing…")
                self.poll.start()
            except printing.PrintError as exc:
                self.status.setText(f"the printer said: {exc}")
                self.printed = True
            last = self.at == len(self.steps) - 2 and self.steps[-1][0].startswith("done")
            self.go.setText("next ↵" if not last else "done ↵")
        elif kind == "turn":
            edge = "long edge, like a book's page" if self.plugin.s["printing"] != "single-short" \
                else "short edge, like a calendar"
            self.title.setText(f"now turn the stack over its {edge}")
            self.status.setText("take it out of the front tray just as it is, turn it over and "
                                "stand it in the back tray, blank side facing you, the edge "
                                "nearest you going in first - then print the backs.")
            self.go.setText("print the backs ↵")
        else:
            self.title.setText("done")
            self.status.setText(
                "both sides should read upright, back to back. If B is upside down, choose the "
                "other edge to turn over; if it landed on the same side as A, stand the stack the "
                "other way round." if kind == "done-test" else
                "the draft is out - fold it to check the pages run in order, then print "
                "for real." if self.draft and kind == "done" else
                "all printed - now fold and bind: G shows how.")
            self.go.setText("close ↵")
        self.sync()

    def _check(self):
        if self.job and not printing.pending(self.job):
            self.poll.stop()
            self.printed = True
            self.status.setText(f"printed ✓ · {self.sent}")
            if self.minimised:
                after = self.steps[self.at + 1][0] if self.at + 1 < len(self.steps) else ""
                self.plugin.host.toast(
                    "printed ✓ · now turn the stack" if after == "turn" else "printed ✓")
            self.sync()

    def _paint_art(self, event):
        painter = QtGui.QPainter(self.art)
        rect = QtCore.QRectF(self.art.rect()).adjusted(0, 0, 0, -4)
        kind = self.step()[0] if 0 <= self.at < len(self.steps) else ""
        edge = "short" if self.plugin.s["printing"] == "single-short" else "long"
        if kind == "send":
            label = self.step()[4]
            w = min(rect.width(), rect.height() * 1.15)
            draw_facing_printer(painter, QtCore.QRectF(rect.center().x() - w / 2, rect.top(), w,
                                                       rect.height()),
                                tray="blank", out=label, feed=True, deliver=True,
                                tray_dot="bottom" if label == "B" and edge == "long" else
                                ("top" if label == "B" else ""))
        elif kind == "turn":
            draw_print_steps(painter, rect, edge, GREY, only=(2, 3, 4))
        elif kind.startswith("done"):
            w = min(rect.width() * 0.5, rect.height() * 1.6)
            draw_binding(painter, QtCore.QRectF(rect.center().x() - w / 2, rect.top(), w,
                                                rect.height()), self.plugin.s["style"])

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.advance()
        elif event.key() in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Minus):
            if self.steps[self.at][0].startswith("done"):
                self.close_card()
            else:
                self.minimise()
        else:
            super().keyPressEvent(event)

    def close_card(self):
        self.poll.stop()
        was_up = self.isVisible()
        self.hide()
        self.deleteLater()
        if self.plugin.flow is self:
            self.plugin.flow = None
        self.plugin.print_panel.hide()
        if was_up:
            self._give_back_focus()


# -- the plugin ------------------------------------------------------------------------

class Plugin(Base):
    name = "impose"
    title = "impose"

    def setup(self, host):
        self.host = host
        self.s = {**DEFAULTS, **host.settings}
        self.s["printing"] = imposition.OLD_PRINTING.get(self.s["printing"], self.s["printing"])
        self.view = ImposeView(self)
        self.flow: PrintFlow | None = None
        self.print_panel = self.build_print_panel()
        self.portrait = False            # while printing: pages upright as the paper feeds
        self.drafting = False            # while printing a draft: pages as outlines
        self.panel = self.build_panel()
        host.command("impose", self.toggle, "⌥⌘I",
                     "imposition booklet zine print binding saddle signatures", shortcut="Ctrl+Alt+I")
        host.command("impose: export bundle…", self.export_bundle, "", "imposition folder print")
        host.command("impose: test sheet…", self.export_test, "", "printer check duplex")
        host.command("impose: print", self.print_now, "", "print fronts backs printer automatic")
        host.command("impose: print test sheet", lambda: self.print_now(test=True), "",
                     "printer check draft")
        host.command("impose: printing", self.printing_status, "",
                     "print status card next step")
        host.command("impose: print draft", lambda: self.print_now(draft=True), "",
                     "printer check dummy fast light ink outline")

    def teardown(self):
        self.save()

    def save(self):
        self.host.settings.clear()
        self.host.settings.update(self.s)
        self.host.save_settings()

    # -- opening --------------------------------------------------------------------
    def toggle(self):
        if self.view.isVisible():
            self.close()
        else:
            self.open()

    def open(self):
        window = self.host.window
        if window.editing is not None:
            window.finish_editing()
        self.view.open()
        self.panel.open()
        self.panel.raise_()

    def close(self):
        if self.flow is not None and not self.flow.minimised:
            self.flow.minimise()                   # printing carries on, folded away
        self.view.hide()
        self.panel.hide()
        self.save()
        self.host.window.focus_text()

    def changed(self):
        self.view.update()
        self.panel.refresh()

    def build_print_panel(self):
        """The print card folded away: what is happening, and next / open."""
        panel = self.host.panel("printing", on_close=lambda: self.flow and self.flow.close_card())
        flow = lambda: self.flow                                     # noqa: E731
        title = QtWidgets.QLabel()
        title.setWordWrap(True)
        title.setFont(style.ui_font(12))
        title.setStyleSheet(f"color: {style.INK}; background: transparent;")
        status = QtWidgets.QLabel()
        status.setWordWrap(True)
        status.setFont(style.ui_font(11))
        status.setStyleSheet("color: #8c8b86; background: transparent;")

        def refresh():
            f = flow()
            if f is not None:
                panel.caption.setText(f.caption.text())
                title.setText(f.title.text())
                status.setText(f.status.text())

        panel.widget(title, refresh)
        panel.widget(status)
        panel.links("", [(lambda: flow().next_word() if flow() else "", lambda: flow() and flow().advance()),
                         ("open", lambda: flow() and flow().restore()),
                         ("stop", lambda: flow() and flow().close_card())])
        return panel

    def printing_status(self):
        """Back to the print card, if a print is going on."""
        if self.flow is not None:
            self.flow.restore()
        else:
            self.host.toast("print · nothing printing")

    def build_panel(self):
        panel = self.host.panel("impose", on_close=self.close)
        s = self.s

        def put(key):
            def setter(value):
                s[key] = value
                self.view.sheet_index = 0 if key == "style" else self.view.sheet_index
                self.changed()
            return setter

        panel.choice("style", lambda: list(imposition.STYLES), lambda: s["style"], put("style"))
        panel.choice("sheet", lambda: list(imposition.SHEETS), lambda: s["sheet"], put("sheet"))
        panel.toggle("pages", lambda: s["fit"], put("fit"), on="fit", off="100%")
        panel.slider("signature", 1, 8, lambda: s["per_signature"], put("per_signature"),
                     unit=" sheets", default=4)
        panel.toggle("blanks", lambda: s["keep_back"], put("keep_back"), on="before back",
                     off="at end")
        panel.section("printer")
        panel.choice("printing", lambda: list(imposition.PRINTING), lambda: s["printing"],
                     put("printing"))
        panel.toggle("backs", lambda: s["reverse"], put("reverse"), on="reversed", off="in order")
        panel.toggle("marks", lambda: s["marks"], put("marks"))
        panel.links("", [(lambda: "sheets" if self.view.guide else "[sheets]", self.show_sheets),
                         (lambda: "[how to print]" if self.view.guide else "how to print",
                          self.show_guide)])
        panel.choice("printer", lambda: ["default"] + printing.printers(),
                     lambda: s.get("printer") or "default",
                     lambda v: s.__setitem__("printer", "" if v == "default" else v))
        panel.links("", [("print", self.print_now), ("draft", lambda: self.print_now(draft=True)),
                         ("test", lambda: self.print_now(test=True))])
        panel.buttons([("export bundle…", self.export_bundle), ("test sheet…", self.export_test)])
        return panel

    def show_sheets(self):
        self.view.guide = False
        self.view.update()

    def show_guide(self):
        self.view.guide = True
        self.view.update()

    # -- the layout -------------------------------------------------------------------
    def layout(self) -> imposition.Layout:
        return imposition.impose(self.host.window.sheet.pages(), self.s["style"],
                                 int(self.s["per_signature"]), bool(self.s["keep_back"]))

    def mode(self) -> str:
        if not self.layout().two_sided:
            return "one"
        return "duplex" if self.s["printing"].startswith("duplex") else "single"

    def print_steps(self) -> list[str]:
        edge = "short edge (like a wall calendar)" if self.s["printing"] == "single-short" else \
            "long edge (like a book's page)"
        flip = "flip on long edge" if self.s["printing"] == "duplex-long" else "flip on short edge"
        steps = [t.format(edge=edge, flip=flip) for t in PRINT_STEPS[self.mode()]]
        if self.mode() == "single" and self.s["reverse"]:
            steps[-1] += " (its pages run in reverse, for printers that stack face up)"
        return steps

    def bind_steps(self) -> list[str]:
        return [t.format(per=int(self.s["per_signature"])) for t in BIND_STEPS[self.s["style"]]]

    # -- the guide -----------------------------------------------------------------------
    def draw_guide(self, painter: QtGui.QPainter, rect: QtCore.QRectF, meta: QtGui.QColor,
                   paper: bool = False):
        """How to print, then how to fold and bind - on screen (meta-coloured
        words on the canvas) or on a guide page (`paper`: ink on white)."""
        words = INK if paper else meta
        head_size, text_size = (12, 9) if paper else (13, 12)
        layout = self.layout()
        mode = self.mode()
        painter.save()
        painter.setFont(style.ui_font(head_size))
        painter.setPen(words)
        top = _write(painter, rect.left(), rect.top(), rect.width(),
                     f"how to print  ·  {imposition.STYLES[layout.style][0]}  ·  "
                     f"{len(layout.sheets)} sheet{'s' if len(layout.sheets) != 1 else ''} of "
                     f"{self.s['sheet']}") + 16
        if mode == "single":
            wide = rect.width() / max(1.0, rect.height()) > 1.2
            steps_h = min(rect.height() * (0.34 if wide else 0.46), 260 if wide else 470)
            edge = "short" if self.s["printing"] == "single-short" else "long"
            draw_print_steps(painter, QtCore.QRectF(rect.left(), top, rect.width(), steps_h), edge,
                             words, self.s["reverse"])
            top += steps_h + 10
        else:
            art_h = min(rect.height() * 0.26, 200)
            draw_facing_printer(painter, QtCore.QRectF(rect.left(), top, min(rect.width() * 0.4,
                                                                             art_h * 1.3), art_h),
                                tray="blank", out="A·B" if mode == "duplex" else "A",
                                feed=True, deliver=True)
            top += art_h + 14
        painter.setFont(style.ui_font(text_size))
        painter.setPen(words)
        for n, step in enumerate(self.print_steps(), 1):
            top = _write(painter, rect.left(), top, rect.width(), f"{n}.  {step}") + 3
        if mode == "single":
            painter.setPen(GREY)
            top = _write(painter, rect.left(), top + 4, rect.width(),
                         "first time with this printer? print test-front.pdf, turn the sheet the "
                         "same way, print test-back.pdf: both sides should read upright, back to "
                         "back. If B comes out upside down, choose the other edge to turn over; "
                         "if it lands on the same side as A, put the stack back the other side up.")
        top += 22
        painter.setFont(style.ui_font(head_size))
        painter.setPen(words)
        top = _write(painter, rect.left(), top, rect.width(), "then fold and bind") + 12
        steps = self.bind_steps()
        room = rect.bottom() - top - (text_size + 8) * 1.6 * len(steps)
        bind_h = min(160.0, room)
        if bind_h > 40:
            draw_binding(painter, QtCore.QRectF(rect.left(), top, min(rect.width() * 0.4, bind_h * 1.6),
                                                bind_h), layout.style)
            top += bind_h + 10
        painter.setFont(style.ui_font(text_size))
        painter.setPen(words)
        for n, step in enumerate(steps, 1):
            top = _write(painter, rect.left(), top, rect.width(), f"{n}.  {step}") + 3
        painter.restore()

    # -- printing it ----------------------------------------------------------------------
    def _writer(self, path: str, pages_are_images: bool) -> QtGui.QPdfWriter:
        sw, sh = imposition.SHEETS[self.s["sheet"]]
        if self.portrait:
            sw, sh = sh, sw
        writer = QtGui.QPdfWriter(path)
        writer.setCreator("ream")
        writer.setPageSize(QtGui.QPageSize(QtCore.QSizeF(sw, sh), QtGui.QPageSize.Point, "",
                                           QtGui.QPageSize.ExactMatch))
        writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
        writer.setResolution(int(self.host.window.fmt.dpi) if pages_are_images else 1200)
        return writer

    def _lay(self, painter: QtGui.QPainter, writer: QtGui.QPdfWriter) -> QtCore.QRectF:
        """Where the landscape sheet goes on the writer's page.  Printing, the
        page is the paper as it goes through the printer - upright, short
        edge first - so the sheet is turned a quarter onto it (top edge to
        the paper's right; fronts and backs alike, so they still back up)."""
        if not self.portrait:
            return QtCore.QRectF(0, 0, writer.width(), writer.height())
        painter.translate(writer.width(), 0)
        painter.rotate(90)
        return QtCore.QRectF(0, 0, writer.height(), writer.width())

    def page_drawer(self):
        """Puts a finished page into a rect: distressed as an image, clean as
        vector (words stay words) - as the PDF export does."""
        c = self.host.window
        if self.drafting:
            return draft_page(c.sheet.pages())
        paper, ink, stock = c.paper(), c.ink(), c.paper_stock()
        if c.distress.enabled:
            cache: dict[int, QtGui.QImage] = {}

            def draw(painter, rect, page):
                if page not in cache:
                    cache[page] = export.final_page(c.sheet, page, c.fmt.dpi, c.distress, paper, ink,
                                                    c.density(), stock)
                painter.drawImage(rect, cache[page])
            return draw
        base = export.clean_base(c.sheet, min(c.fmt.dpi, 300.0), paper, stock)

        def draw(painter, rect, page):
            export.draw_clean_page(painter, rect, c.sheet, page, paper, ink, base)
        return draw

    def write_sides(self, path: str, sides: list[tuple[list, int]], layout, draw):
        sw, sh = imposition.SHEETS[self.s["sheet"]]
        c = self.host.window
        writer = self._writer(path, c.distress.enabled and not self.drafting)
        painter = QtGui.QPainter(writer)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                               | QtGui.QPainter.TextAntialiasing)
        target = self._lay(painter, writer)
        for n, (cells, turn) in enumerate(sides):
            if n:
                writer.newPage()
            draw_side(painter, target, layout, cells, (sw, sh), (c.sheet.W, c.sheet.H), draw,
                      fit=self.s["fit"], turn=turn, marks=self.s["marks"], total=layout.pages)
        painter.end()

    def write_guide(self, path: str, layout):
        sw, sh = imposition.SHEETS["a4"][::-1]                 # a portrait A4 guide
        writer = QtGui.QPdfWriter(path)
        writer.setCreator("ream")
        writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
        writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
        writer.setResolution(300)
        painter = QtGui.QPainter(writer)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing)
        k = writer.width() / sw
        painter.scale(k, k)
        self.draw_guide(painter, QtCore.QRectF(48, 56, sw - 96, sh - 112), GREY, paper=True)
        # a page map: every sheet's sides with their page numbers
        writer.newPage()
        painter.setFont(style.ui_font(15))
        painter.setPen(INK)
        painter.drawText(QtCore.QRectF(48, 40, sw - 96, 24), QtCore.Qt.AlignLeft,
                         f"page map  ·  {imposition.STYLES[layout.style][0]}")
        ssw, ssh = imposition.SHEETS[self.s["sheet"]]
        cols = 2 if layout.two_sided else 3
        cell_w = (sw - 96 - 20 * (cols - 1)) / cols
        scale = cell_w / ssw
        y = 84.0
        painter.setFont(style.ui_font(9))
        for sheet in layout.sheets:
            sides = [("A", sheet.front)] + ([("B", sheet.back)] if sheet.back is not None else [])
            if layout.two_sided:
                row = [(f"sheet {sheet.number} · {label}", cells) for label, cells in sides]
            else:
                row = [(f"sheet {sheet.number}", sheet.front)]
            for i, (label, cells) in enumerate(row):
                x = 48 + i * (cell_w + 20)
                if not layout.two_sided:
                    x = 48 + ((sheet.number - 1) % cols) * (cell_w + 20)
                target = QtCore.QRectF(x, y + 14, cell_w, ssh * scale)
                if y + 14 + ssh * scale > sh - 40:
                    writer.newPage()
                    y = 40.0
                    target = QtCore.QRectF(x, y + 14, cell_w, ssh * scale)
                painter.setPen(GREY)
                painter.drawText(QtCore.QRectF(x, y, cell_w, 12), QtCore.Qt.AlignLeft, label)
                painter.setPen(QtGui.QPen(INK, 0.6))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(target)
                draw_side(painter, target, layout, cells, (ssw, ssh), (self.host.window.sheet.W,
                                                                      self.host.window.sheet.H),
                          lambda p, r, page: (p.setPen(QtGui.QPen(GREY, 0.4)), p.drawRect(r)),
                          fit=self.s["fit"], numbers=True, marks=True, total=layout.pages)
            if layout.two_sided or (sheet.number % cols == 0) or sheet is layout.sheets[-1]:
                y += 14 + ssh * scale + 18
        painter.end()

    def readme(self, layout) -> str:
        lines = [f"{self.host.window.stem()} — imposed for {imposition.STYLES[layout.style][0]}",
                 "", f"{len(layout.sheets)} sheet(s) of {self.s['sheet']}, {layout.pages} pages"
                 + (f" + {layout.padded - layout.pages} blank" if layout.padded > layout.pages else ""),
                 "", "PRINTING"]
        lines += [f"  {n}. {s}" for n, s in enumerate(self.print_steps(), 1)]
        if layout.two_sided:
            lines += ["", "  duplex.pdf has fronts and backs interleaved, for a duplex printer:",
                      "  print it two-sided, flip on short edge."]
            if self.mode() == "single":
                lines += ["  first time with a printer: print test-front.pdf, turn the sheet as above,",
                          "  print test-back.pdf - both sides should read upright, back to back."]
        lines += ["", "FOLDING AND BINDING"]
        lines += [f"  {n}. {s}" for n, s in enumerate(self.bind_steps(), 1)]
        lines += ["", "guide.pdf has the same with drawings, and a page map of every sheet."]
        return "\n".join(lines) + "\n"

    def sheet_files(self, folder: str, which=("fronts", "backs", "duplex")) -> dict[str, str]:
        """The sheets as PDFs: fronts, backs (turned and ordered for the
        chosen way of turning) and duplex (interleaved) - whichever apply."""
        layout = self.layout()
        draw = self.page_drawer()
        files = {}
        if "fronts" in which:
            files["fronts"] = os.path.join(folder, "1-fronts.pdf")
            self.write_sides(files["fronts"], [(s.front, 0) for s in layout.sheets], layout, draw)
        if not layout.two_sided:
            return files
        if "backs" in which:
            turn = imposition.back_turn(self.s["printing"]) \
                if self.s["printing"].startswith("single") else 0
            backs = [(s.back, turn) for s in layout.sheets]
            if self.s["reverse"]:
                backs.reverse()
            files["backs"] = os.path.join(folder, "2-backs.pdf")
            self.write_sides(files["backs"], backs, layout, draw)
        if "duplex" in which:
            duplex_turn = 180 if self.s["printing"] == "duplex-long" else 0
            interleaved = []
            for s in layout.sheets:
                interleaved += [(s.front, 0), (s.back, duplex_turn)]
            files["duplex"] = os.path.join(folder, "duplex.pdf")
            self.write_sides(files["duplex"], interleaved, layout, draw)
        return files

    def bundle_to(self, folder: str) -> list[str]:
        layout = self.layout()
        written = list(self.sheet_files(folder).values())
        if layout.two_sided:
            written += self.test_sheet(folder)
        out = os.path.join(folder, "guide.pdf")
        self.write_guide(out, layout)
        written.append(out)
        out = os.path.join(folder, "README.txt")
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(self.readme(layout))
        written.append(out)
        return written

    def test_sheet(self, folder: str) -> list[str]:
        """Two one-page PDFs: print the front, turn the sheet as the guide
        says, print the back; they should read upright, back to back."""
        sw, sh = imposition.SHEETS[self.s["sheet"]]
        turn = imposition.back_turn(self.s["printing"]) if self.s["printing"].startswith("single") else 0
        paths = []
        for side, label in (("front", "A · FRONT"), ("back", "B · BACK")):
            path = os.path.join(folder, f"test-{side}.pdf")
            writer = self._writer(path, False)
            painter = QtGui.QPainter(writer)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            room = self._lay(painter, writer)
            painter.scale(room.width() / sw, room.height() / sh)
            if side == "back" and turn:
                painter.translate(sw / 2, sh / 2)
                painter.rotate(turn)
                painter.translate(-sw / 2, -sh / 2)
            # outlines and hairlines only: a test should cost next to no ink
            outline_text(painter, QtCore.QRectF(0, sh * 0.3, sw, sh * 0.2), label, sh * 0.12, 0.7)
            outline_text(painter, QtCore.QRectF(0, sh * 0.06, sw, sh * 0.1), "top", sh * 0.05, 0.5)
            font = style.ui_font(1)
            font.setPixelSize(int(sh * 0.03))
            painter.setFont(font)
            painter.setPen(GREY)
            painter.drawText(QtCore.QRectF(0, sh * 0.62, sw, sh * 0.2), QtCore.Qt.AlignCenter,
                             "this side up when you read it" if side == "front" else
                             "should read upright, back to back with A")
            _pen(painter, 0.7)
            _arrow(painter, QtCore.QPointF(sw / 2, sh * 0.26), QtCore.QPointF(sw / 2, sh * 0.16), 14)
            painter.end()
            paths.append(path)
        return paths

    def printer(self) -> str | None:
        return self.s.get("printer") or printing.default()

    def print_now(self, test: bool = False, draft: bool = False):
        """Print straight to the printer: the fronts, then (after the turn,
        shown step by step) the backs - or one duplex job, or just the
        fronts for a one-sided layout.  `test`: the same with the test sheet;
        `draft`: the whole job as outlines and page numbers.  Both go at the
        printer's draft quality, black only."""
        printer = self.printer()
        if not printing.available() or not printer:
            self.host.toast("print · no printer found (System Settings › Printers & Scanners)")
            return
        if not self.view.isVisible():
            self.open()
        folder = tempfile.mkdtemp(prefix="ream-print-")
        mode = self.mode() if not test else "single"
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.portrait, self.drafting = True, draft
        light = test or draft
        try:
            if test:
                front, back = self.test_sheet(folder)
                steps = [("send", "the test sheet's front", front, None, "A"), ("turn",),
                         ("send", "the test sheet's back", back, None, "B"), ("done-test",)]
            elif mode == "duplex":
                files = self.sheet_files(folder, ("duplex",))
                sides = "two-sided-long-edge" if self.s["printing"] == "duplex-long" else \
                    "two-sided-short-edge"
                steps = [("send", "both sides", files["duplex"], sides, "A·B"), ("done",)]
            elif mode == "one":
                files = self.sheet_files(folder, ("fronts",))
                steps = [("send", "the sheets", files["fronts"], None, "A"), ("done",)]
            else:
                files = self.sheet_files(folder, ("fronts", "backs"))
                steps = [("send", "the fronts", files["fronts"], None, "A"), ("turn",),
                         ("send", "the backs", files["backs"], None, "B"), ("done",)]
        finally:
            self.portrait = self.drafting = False
            QtWidgets.QApplication.restoreOverrideCursor()
        if self.flow is not None:
            self.flow.close_card()
        self.flow = PrintFlow(self, printer, steps, draft=light)
        self.flow.start()

    def _folder(self, title: str) -> str | None:
        start = self.s.get("folder") or os.path.expanduser("~/Desktop")
        parent = QtWidgets.QFileDialog.getExistingDirectory(self.host.window, title, start)
        if not parent:
            return None
        self.s["folder"] = parent
        return parent

    def export_bundle(self, parent: str | None = None) -> str | None:
        parent = parent or self._folder("Export the imposition bundle into")
        if not parent:
            return None
        name = re.sub(r"[^\w\- ]+", "_", f"{self.host.window.stem()} imposition {self.s['style']}")
        folder = os.path.join(parent, name)
        n = 2
        while os.path.exists(folder):
            folder = os.path.join(parent, f"{name} {n}")
            n += 1
        os.makedirs(folder)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            written = self.bundle_to(folder)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.host.toast(f"imposition bundle · {len(written)} files → {folder}")
        return folder

    def export_test(self, parent: str | None = None):
        parent = parent or self._folder("Save the test sheet into")
        if parent:
            self.test_sheet(parent)
            self.host.toast(f"test sheet → {parent}")
