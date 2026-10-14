"""
Rendering pages: for the PDF, for PNGs, and for the distress preview.

A page is drawn straight from the model, never by grabbing the scene, so
no selection outline or canvas clutter can get in: things behind the text
(z < 0), the text, then things in front, all clipped to the page.

Clean PDFs are vector - the text stays text.  With distress on, each page is
rendered as an ink layer on transparent at the export dpi, distressed (see
distress.py), laid on paper and placed in the PDF as one image.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from PyQt5 import QtCore, QtGui

from . import distress


def draw_page(painter: QtGui.QPainter, sheet, index: int, ink: QtGui.QColor):
    """Draw page `index` in page points, origin at its top-left corner."""
    w, h = sheet.W, sheet.H
    clip = QtCore.QRectF(0.0, index * h, w, h)
    painter.save()
    painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                           | QtGui.QPainter.TextAntialiasing)
    painter.translate(0.0, -index * h)
    painter.setClipRect(clip)
    things = sorted(sheet.pinned(), key=lambda t: t.zValue())

    def things_where(test):
        for thing in things:
            if not (test(thing.zValue()) and thing.parent_rect().intersects(clip)):
                continue
            painter.save()
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


def raster_page(sheet, index: int, dpi: float, settings: distress.Settings,
                paper: QtGui.QColor, ink: QtGui.QColor, density: float = 1.0) -> QtGui.QImage:
    """A finished page as an RGB image: ink, distressed when it is on, on paper."""
    layer = ink_layer(sheet, index, dpi, ink)
    return from_rgb(distress.compose(layer, rgb(paper), settings, dpi, density=density))


def write_pdf(path: str, sheet, pages: list[int], *, dpi: float, settings: distress.Settings,
              paper: QtGui.QColor, ink: QtGui.QColor, title: str = "", density: float = 1.0,
              progress: Callable[[int, int], None] | None = None):
    raster = settings.enabled
    writer = QtGui.QPdfWriter(path)
    writer.setCreator("ream")
    writer.setTitle(title)
    writer.setPageSize(QtGui.QPageSize(QtCore.QSizeF(sheet.W, sheet.H), QtGui.QPageSize.Point,
                                       "", QtGui.QPageSize.ExactMatch))
    writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
    writer.setResolution(int(dpi) if raster else 1200)
    painter = QtGui.QPainter(writer)
    target = QtCore.QRectF(0, 0, writer.width(), writer.height())
    for n, index in enumerate(pages):
        if progress:
            progress(n, len(pages))
        if n:
            writer.newPage()
        if raster:
            painter.drawImage(target, raster_page(sheet, index, dpi, settings, paper, ink, density))
        else:
            painter.save()
            painter.scale(writer.width() / sheet.W, writer.height() / sheet.H)
            painter.fillRect(QtCore.QRectF(0, 0, sheet.W, sheet.H), paper)
            draw_page(painter, sheet, index, ink)
            painter.restore()
    painter.end()


def write_pngs(stem: str, sheet, pages: list[int], *, dpi: float, settings: distress.Settings,
               paper: QtGui.QColor, ink: QtGui.QColor, density: float = 1.0,
               progress: Callable[[int, int], None] | None = None) -> list[str]:
    written = []
    for n, index in enumerate(pages):
        if progress:
            progress(n, len(pages))
        path = f"{stem}_{index + 1:02d}.png"
        image = raster_page(sheet, index, dpi, settings, paper, ink, density)
        image.setDotsPerMeterX(int(dpi / 0.0254))
        image.setDotsPerMeterY(int(dpi / 0.0254))
        image.save(path)
        written.append(path)
    return written
