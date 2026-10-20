"""
Rendering pages: for the PDF, for PNGs, and for the distress preview.

A page is drawn straight from the model, never by grabbing the scene, so
no selection outline or canvas clutter can get in: things behind the text
(z < 0), the text, then things in front, all clipped to the page.

Clean PDFs are vector - the text stays text.  With distress on, each page is
rendered as an ink layer on transparent at the export dpi, distressed (see
distress.py), laid on paper and placed in the PDF as one image.

Distressing is the slow part, so several pages go at once (distressed_pages):
Qt draws each page's layers here, on the main thread - text layout is not
safe anywhere else - and threads distress them (numpy and OpenCV let go of
the interpreter while they work), a few pages ahead, handed back in order.
"""
from __future__ import annotations

import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterator

import numpy as np
from PyQt5 import QtCore, QtGui

from . import distress, papers


def draw_page(painter: QtGui.QPainter, sheet, index: int, ink: QtGui.QColor):
    """Draw page `index` in page points, origin at its top-left corner."""
    w, h = sheet.W, sheet.H
    clip = QtCore.QRectF(0.0, index * h, w, h)
    painter.save()
    painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                           | QtGui.QPainter.TextAntialiasing)
    painter.translate(0.0, -index * h)
    painter.setClipRect(clip)
    # its own things, and what hangs over from the facing page of its spread
    things = sheet.page_things(index)

    def things_where(test):
        for thing, dx, dy in things:
            if not test(thing.zValue()):
                continue
            painter.save()
            painter.translate(dx, dy)
            placed, _ok = thing.itemTransform(thing.parentItem())
            painter.setTransform(placed, True)
            thing.render(painter, ink)
            painter.restore()

    things_where(lambda z: z < 0)
    context = QtGui.QAbstractTextDocumentLayout.PaintContext()
    context.clip = clip
    context.cursorPosition = -1
    context.palette.setColor(QtGui.QPalette.Text, ink)
    sheet.doc.documentLayout().draw(painter, context)
    things_where(lambda z: z >= 0)
    painter.restore()


def crop_box(sheet, dpi: float, area: QtCore.QRectF | None) -> tuple[int, int, int, int]:
    """(x, y, w, h) in pixels at `dpi` covering `area` (page points), clamped
    to the page; the whole page when `area` is None."""
    scale = dpi / 72.0
    full_w, full_h = int(round(sheet.W * scale)), int(round(sheet.H * scale))
    if area is None:
        return 0, 0, full_w, full_h
    x0 = max(0, int(area.left() * scale))
    y0 = max(0, int(area.top() * scale))
    x1 = min(full_w, int(np.ceil(area.right() * scale)))
    y1 = min(full_h, int(np.ceil(area.bottom() * scale)))
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def ink_layer(sheet, index: int, dpi: float, ink: QtGui.QColor,
              box: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Page `index` without its paper: (h, w, 4) uint8 straight RGBA - the
    whole page, or just `box` (pixels at `dpi`, from crop_box)."""
    scale = dpi / 72.0
    x0, y0, width, height = box or crop_box(sheet, dpi, None)
    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.translate(-x0, -y0)
    painter.scale(scale, scale)
    draw_page(painter, sheet, index, ink)
    painter.end()
    return to_numpy(image)


def _draw_thing(painter: QtGui.QPainter, thing, ink: QtGui.QColor, dx: float = 0.0,
                dy: float = 0.0):
    painter.save()
    painter.translate(dx, dy)
    placed, _ok = thing.itemTransform(thing.parentItem())
    painter.setTransform(placed, True)
    thing.render(painter, ink)
    painter.restore()


def ink_layers(sheet, index: int, dpi: float, ink: QtGui.QColor,
               box: tuple[int, int, int, int] | None = None) -> list[distress.Layer]:
    """Page `index` (or its `box`) as separate layers, bottom to top: things
    behind the words, the words, things in front.  The words cover the whole
    canvas; each image or text block is cropped to where it is, with a
    little room for its distressed edge to spread."""
    scale = dpi / 72.0
    x0, y0, width, height = box or crop_box(sheet, dpi, None)
    page = QtCore.QRectF(0.0, index * sheet.H, sheet.W, sheet.H)
    pad = int(8 * dpi / 300.0) + 2

    def render(cx: int, cy: int, cw: int, ch: int, draw) -> np.ndarray:
        image = QtGui.QImage(cw, ch, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                               | QtGui.QPainter.TextAntialiasing)
        painter.translate(-(x0 + cx), -(y0 + cy))
        painter.scale(scale, scale)
        painter.translate(0.0, -index * sheet.H)
        painter.setClipRect(page)
        draw(painter)
        painter.end()
        return to_numpy(image)

    def words(painter):
        context = QtGui.QAbstractTextDocumentLayout.PaintContext()
        context.clip = page
        context.cursorPosition = -1
        context.palette.setColor(QtGui.QPalette.Text, ink)
        sheet.doc.documentLayout().draw(painter, context)

    def thing_layer(thing, dx=0.0, dy=0.0):
        area = thing.parent_rect().translated(dx, dy).intersected(page)
        if area.isEmpty():
            return None
        left = int(area.left() * scale) - x0 - pad
        top = int((area.top() - index * sheet.H) * scale) - y0 - pad
        right = int(np.ceil(area.right() * scale)) - x0 + pad
        bottom = int(np.ceil((area.bottom() - index * sheet.H) * scale)) - y0 + pad
        left, top = max(0, left), max(0, top)
        right, bottom = min(width, right), min(height, bottom)
        if right <= left or bottom <= top:
            return None
        rgba = render(left, top, right - left, bottom - top,
                      lambda painter, t=thing: _draw_thing(painter, t, ink, dx, dy))
        kind = "image" if getattr(thing, "kind", "image") == "image" else "text"
        return distress.Layer(rgba, top, left, kind)

    things = sheet.page_things(index)           # with the facing page's overhang
    below = [thing_layer(t, dx, dy) for t, dx, dy in things if t.zValue() < 0]
    above = [thing_layer(t, dx, dy) for t, dx, dy in things if t.zValue() >= 0]
    text = distress.Layer(render(0, 0, width, height, words), 0, 0, "text")
    # the words always come first in the list (they set the canvas size), so
    # anything behind them goes on in a separate pass below
    return [layer for layer in below if layer is not None], text, \
        [layer for layer in above if layer is not None]


def page_layers(sheet, index: int, dpi: float, ink: QtGui.QColor,
                box: tuple[int, int, int, int] | None = None) -> list[distress.Layer]:
    """ink_layers in stacking order, with a transparent full-canvas layer
    first so the canvas size is known even when things lie behind the words."""
    below, text, above = ink_layers(sheet, index, dpi, ink, box)
    h, w = text.rgba.shape[:2]
    canvas = distress.Layer(np.zeros((h, w, 4), np.uint8), 0, 0, "text")
    return [canvas] + below + [text] + above


def to_numpy(image: QtGui.QImage) -> np.ndarray:
    image = image.convertToFormat(QtGui.QImage.Format_RGBA8888)
    w, h = image.width(), image.height()
    bits = image.constBits()
    bits.setsize(image.byteCount())
    rows = np.frombuffer(bits, np.uint8).reshape(h, image.bytesPerLine())
    return rows[:, :w * 4].reshape(h, w, 4).copy()


def from_rgb(array: np.ndarray) -> QtGui.QImage:
    array = np.ascontiguousarray(array)
    h, w = array.shape[:2]
    return QtGui.QImage(array.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()


def rgb(colour: QtGui.QColor) -> tuple[int, int, int]:
    return colour.red(), colour.green(), colour.blue()


class Stock:
    """A paper stock as used for one render: which paper, how it blends,
    how much, how big."""

    def __init__(self, texture: str = "", grain: float = 0.0, blend: str = "tooth",
                 scale: float = 100.0):
        self.texture, self.grain, self.blend, self.scale = texture, grain, blend, scale

    def __bool__(self):
        return bool(self.texture) and self.grain > 0


def stock(sheet, dpi: float, box, paper: QtGui.QColor, paper_stock: Stock | None):
    """The paper to print on (tooth blend), or None for flat colour."""
    if not paper_stock or paper_stock.blend != "tooth":
        return None
    s = paper_stock
    return papers.sheet(s.texture, sheet.W, sheet.H, dpi, box, rgb(paper), s.grain, s.scale)


def over(sheet, dpi: float, box, paper_stock: Stock | None):
    """(photo, mode, amount) to blend over the page, or None."""
    if not paper_stock or paper_stock.blend == "tooth":
        return None
    s = paper_stock
    layer = papers.surface(s.texture, sheet.W, sheet.H, dpi, box, s.scale, s.blend)
    return None if layer is None else (layer, s.blend, s.grain)


WORKERS = max(1, min(4, (os.cpu_count() or 2) - 1))     # threads distressing pages at once


def distressed_pages(sheet, pages, dpi: float, settings: distress.Settings,
                     paper: QtGui.QColor, ink: QtGui.QColor, density: float = 1.0,
                     paper_stock: Stock | None = None,
                     progress: Callable[[int, int], None] | None = None,
                     workers: int | None = None) -> Iterator[tuple[int, QtGui.QImage]]:
    """(index, finished page) for each of `pages`, in order - the same
    images raster_page makes, with several pages distressed at once.  At
    most a few pages are in hand at a time, so memory stays in check."""
    pages = list(pages)
    workers = workers or WORKERS
    base = stock(sheet, dpi, None, paper, paper_stock)
    blend = over(sheet, dpi, None, paper_stock)
    colour = rgb(paper)
    pending: deque = deque()

    def ready(future_index):
        future, index = future_index
        return index, from_rgb(future.result())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, index in enumerate(pages):
            if progress:
                progress(n, len(pages))
            below, text, above = ink_layers(sheet, index, dpi, ink)
            shape = text.rgba.shape[:2]
            layers = below + [text] + above
            pending.append((pool.submit(distress.compose, layers, colour, settings, dpi,
                                        density=density, base=base, over=blend, shape=shape),
                            index))
            while len(pending) > workers:
                yield ready(pending.popleft())
        while pending:
            yield ready(pending.popleft())


def raster_page(sheet, index: int, dpi: float, settings: distress.Settings,
                paper: QtGui.QColor, ink: QtGui.QColor, density: float = 1.0,
                paper_stock: Stock | None = None) -> QtGui.QImage:
    """A finished page as an RGB image: ink, distressed when it is on, on paper."""
    layer = page_layers(sheet, index, dpi, ink)
    base = stock(sheet, dpi, None, paper, paper_stock)
    return from_rgb(distress.compose(layer, rgb(paper), settings, dpi, density=density, base=base,
                                     over=over(sheet, dpi, None, paper_stock)))


def clean_base(sheet, dpi: float, paper: QtGui.QColor, paper_stock: Stock | None):
    """The paper under a clean (vector) page: the stock, or a blended paper
    folded into the paper colour (PDF via Qt has no blend modes, so it can't
    go over the words); None for flat paper."""
    base = stock(sheet, dpi, None, paper, paper_stock)
    blended = over(sheet, dpi, None, paper_stock)
    if blended is not None:
        flat = np.empty(blended[0].shape, np.uint8)
        flat[...] = rgb(paper)
        base = papers.blend(flat, *blended)
    return base


def draw_clean_page(painter: QtGui.QPainter, target: QtCore.QRectF, sheet, index: int,
                    paper: QtGui.QColor, ink: QtGui.QColor, base):
    """A clean page into `target`: its paper, then the words and things."""
    if base is not None:
        painter.drawImage(target, from_rgb(base))
    painter.save()
    painter.translate(target.topLeft())
    painter.scale(target.width() / sheet.W, target.height() / sheet.H)
    if base is None:
        painter.fillRect(QtCore.QRectF(0, 0, sheet.W, sheet.H), paper)
    draw_page(painter, sheet, index, ink)
    painter.restore()


def final_page(sheet, index: int, dpi: float, settings: distress.Settings, paper: QtGui.QColor,
               ink: QtGui.QColor, density: float = 1.0,
               paper_stock: Stock | None = None) -> QtGui.QImage:
    """Page `index` exactly as the PDF export puts it on paper, as an image:
    distressed when distress is on, else clean - the same code either way."""
    if settings.enabled:
        return raster_page(sheet, index, dpi, settings, paper, ink, density, paper_stock)
    scale = dpi / 72.0
    image = QtGui.QImage(int(round(sheet.W * scale)), int(round(sheet.H * scale)),
                         QtGui.QImage.Format_RGB32)
    image.fill(paper)
    painter = QtGui.QPainter(image)
    painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                           | QtGui.QPainter.TextAntialiasing)
    draw_clean_page(painter, QtCore.QRectF(0, 0, image.width(), image.height()), sheet, index,
                    paper, ink, clean_base(sheet, min(dpi, 300.0), paper, paper_stock))
    painter.end()
    return image


def _units(pages: list[int], units) -> list[tuple[int, ...]]:
    """What goes on each exported page: one page, or a spread's pages side by side."""
    if units is None:
        return [(p,) for p in pages]
    return [tuple(p for p in unit if p is not None) for unit in units if any(p is not None for p in unit)]


def write_pdf(path: str, sheet, pages: list[int], *, dpi: float, settings: distress.Settings,
              paper: QtGui.QColor, ink: QtGui.QColor, title: str = "", density: float = 1.0,
              paper_stock: Stock | None = None, units=None,
              progress: Callable[[int, int], None] | None = None) -> int:
    """The pages as a PDF: clean pages as vector, distressed ones as images.
    `units`, when given, are spreads - (left, right), None for no page - each
    on one PDF page as wide as its pages; else every page on its own.
    Returns how many PDF pages were written."""
    units = _units(pages, units)
    raster = settings.enabled
    writer = QtGui.QPdfWriter(path)
    writer.setCreator("ream")
    writer.setTitle(title)

    def size(unit):
        return QtGui.QPageSize(QtCore.QSizeF(sheet.W * len(unit), sheet.H), QtGui.QPageSize.Point,
                               "", QtGui.QPageSize.ExactMatch)

    writer.setPageSize(size(units[0] if units else (0,)))
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
    writer.setResolution(int(dpi) if raster else 1200)
    painter = QtGui.QPainter(writer)
    k = writer.resolution() / 72.0
    pw, ph = sheet.W * k, sheet.H * k
    base = None if raster else clean_base(sheet, min(dpi, 300.0), paper, paper_stock)
    total, done = sum(len(u) for u in units), 0
    finished = distressed_pages(sheet, [i for u in units for i in u], dpi, settings, paper, ink,
                                density, paper_stock) if raster else None
    for n, unit in enumerate(units):
        if n:
            writer.setPageSize(size(unit))           # takes effect on the new page
            writer.newPage()
        for i, index in enumerate(unit):
            if progress:
                progress(done, total)
            done += 1
            target = QtCore.QRectF(i * pw, 0, pw, ph)
            if raster:
                _index, image = next(finished)
                painter.drawImage(target, image)
            else:
                # vector words stay words, on top of the paper
                draw_clean_page(painter, target, sheet, index, paper, ink, base)
    painter.end()
    return len(units)


def write_pngs(stem: str, sheet, pages: list[int], *, dpi: float, settings: distress.Settings,
               paper: QtGui.QColor, ink: QtGui.QColor, density: float = 1.0,
               paper_stock: Stock | None = None, units=None,
               progress: Callable[[int, int], None] | None = None) -> list[str]:
    """One PNG per page (stem_03.png), or per spread (stem_02-03.png)."""
    written = []
    units = _units(pages, units)
    total, done = sum(len(u) for u in units), 0
    finished = distressed_pages(sheet, [i for u in units for i in u], dpi, settings, paper, ink,
                                density, paper_stock) if settings.enabled else None
    for unit in units:
        images = []
        for index in unit:
            if progress:
                progress(done, total)
            done += 1
            images.append(next(finished)[1] if finished is not None else
                          final_page(sheet, index, dpi, settings, paper, ink, density, paper_stock))
        if len(images) == 1:
            image = images[0]
        else:
            image = QtGui.QImage(sum(i.width() for i in images), images[0].height(),
                                 QtGui.QImage.Format_RGB32)
            painter = QtGui.QPainter(image)
            x = 0
            for part in images:
                painter.drawImage(x, 0, part)
                x += part.width()
            painter.end()
        path = f"{stem}_{'-'.join(f'{i + 1:02d}' for i in unit)}.png"
        image.setDotsPerMeterX(int(dpi / 0.0254))
        image.setDotsPerMeterY(int(dpi / 0.0254))
        image.save(path)
        written.append(path)
    return written
