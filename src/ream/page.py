"""
The page, and the things that can sit on it.

There is one sheet on the canvas, at the origin.  It is a window: it clips a
*strip* behind it, and the strip holds every page of the document stacked
top to bottom, page n at y = n * H.  Showing page n means sliding the strip
up by n * H, so the sheet never moves and there is only ever one page on
screen.

The words are a single QTextDocument with its page size set, so Qt's own
layout paginates them: a line that would cross the foot of a page is moved to
the head of the next, with the margins honoured on every page.  Typing past
the end makes the document one page longer, and the strip slides to it.

A Thing is an image or a PDF page; a Note is a free block of text, started
with Cmd+click anywhere, that may lie over the page's own words.  On the
canvas either is a scene item; pinned to the page it is a child of the
strip, so it scrolls with its page, is clipped to the sheet, and goes out
with the PDF.
"""
from __future__ import annotations

import itertools
import math
from collections import OrderedDict

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

PREVIEW_MAX = 2400          # px: the on-screen copy of a big image is no larger
PREVIEW_SMALL = 900         # px: the everyday on-screen copy; bigger only when drawn bigger
DRAFT_MAX = 900             # px: while a slider is dragged, an image is reworked this big
_uids = itertools.count(1)


class _Budget:
    """Pixels kept in memory, up to `limit` bytes, the least lately used let
    go first (`drop(thing)`): a book of big pictures can't fill the machine."""

    def __init__(self, limit: int, drop):
        self.limit, self.drop = limit, drop
        self.items: OrderedDict = OrderedDict()      # id(thing) -> (thing, bytes)
        self.total = 0

    def touch(self, thing, size: int):
        old = self.items.pop(id(thing), None)
        if old is not None:
            self.total -= old[1]
        self.items[id(thing)] = (thing, size)
        self.total += size
        while self.total > self.limit and len(self.items) > 1:
            key, (other, used) = next(iter(self.items.items()))
            if other is thing:
                break
            del self.items[key]
            self.total -= used
            self.drop(other)

    def forget(self, thing):
        old = self.items.pop(id(thing), None)
        if old is not None:
            self.total -= old[1]


# an image's original can always be decoded again from its file (a PDF page
# re-rendered, an image read): past this, the least lately used are let go
ORIGINALS = _Budget(256 * 2 ** 20, lambda thing: thing._let_go())
# the bigger on-screen copies, made only while an image is drawn big
BIG_PREVIEWS = _Budget(192 * 2 ** 20, lambda thing: setattr(thing, "_big", None))


def qimage_to_bgra(image: QtGui.QImage) -> np.ndarray:
    """(h, w, 4) uint8 BGRA, straight alpha - QImage ARGB32's own byte order."""
    image = image.convertToFormat(QtGui.QImage.Format_ARGB32)
    w, h = image.width(), image.height()
    bits = image.constBits()
    bits.setsize(image.byteCount())
    rows = np.frombuffer(bits, np.uint8).reshape(h, image.bytesPerLine())
    return rows[:, :w * 4].reshape(h, w, 4).copy()


def bgra_to_qimage(bgra: np.ndarray) -> QtGui.QImage:
    bgra = np.ascontiguousarray(bgra)
    h, w = bgra.shape[:2]
    return QtGui.QImage(bgra.data, w, h, 4 * w, QtGui.QImage.Format_ARGB32).copy()


class Thing(QtWidgets.QGraphicsItem):
    """An image or a PDF page.

    Nothing is ever painted over its pixels.  It keeps the `original` and
    two masks over it: `mask`, the cut shape (holes cut out of it, or the
    shape of a cutout), and `matte`, what background removal, the wand and
    the eraser took away - so "reset mask" always brings the cut back as it
    was cut.  A sticker `border` (die-cut, from stik) and mirroring are
    properties too.  `image` is the result: what is drawn, exported and
    distressed.  Masks are numpy arrays, replaced (never edited in place),
    so undo can keep references to old ones."""

    kind = "image"

    def __init__(self, image: QtGui.QImage, size: QtCore.QSizeF, blob: bytes, ext: str,
                 pdf_page: int | None = None, name: str = "", uid: int | None = None):
        super().__init__()
        self._begin(uid)
        self.blob = blob
        self.ext = ext
        self.pdf_page = pdf_page
        self.name = name
        self.w, self.h = float(size.width()), float(size.height())
        image = image.convertToFormat(QtGui.QImage.Format_ARGB32)
        self.px_w, self.px_h = image.width(), image.height()
        self._original: QtGui.QImage | None = image
        self._image: QtGui.QImage | None = None      # the composed result; None: the original
        self._big: QtGui.QPixmap | None = None       # the bigger on-screen copy, when drawn big
        self._bgra: np.ndarray | None = None
        ORIGINALS.touch(self, image.byteCount())
        self._make_preview()
        self.setTransformOriginPoint(self.w / 2, self.h / 2)    # turns about its middle

    def _begin(self, uid: int | None):
        self.uid = uid if uid is not None else next(_uids)
        bump_uids(self.uid)
        self.alive = True
        self.mask: np.ndarray | None = None       # the cut shape, uint8 (h, w); None: all of it
        self.matte: np.ndarray | None = None      # what cleaning took away; None: nothing
        self.border: tuple | None = None          # (width px, "#rrggbb", smooth px) die-cut
        self.tear: dict | None = None             # a torn edge (see ream.wear), or None
        self.flip = (False, False)
        self.pad_px = 0                           # how far the border reaches past the art
        self.version = 0                          # bumped whenever the pixels change
        self.drafted = False                      # shown from a quick draft; recompose() pending
        self.home: int | None = None              # pinned: the page it belongs to
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)

    # -- pixels ----------------------------------------------------------------
    @property
    def original(self) -> QtGui.QImage | None:
        """The image's own pixels, decoded again from its file if they were let go."""
        if self._original is None and getattr(self, "blob", None):
            self._original = self._decode()
        if self._original is not None:
            ORIGINALS.touch(self, self._original.byteCount())
        return self._original

    @original.setter
    def original(self, value):
        self._original = value

    @property
    def image(self) -> QtGui.QImage | None:
        """What is drawn, exported and distressed: the original, or it with
        its masks, tear and border."""
        return self._image if self._image is not None else self.original

    @image.setter
    def image(self, value):
        self._image = None if value is None or value is self._original else value

    def _decode(self) -> QtGui.QImage:
        from . import project
        if self.pdf_page is not None:
            image = project.pdf_page(self.blob, self.pdf_page)[0]
        else:
            image = project.image_from_bytes(self.blob)
        return image.convertToFormat(QtGui.QImage.Format_ARGB32)

    def _let_go(self):
        """Memory is tight: forget the original's pixels (and their numpy
        copy) - they come back from the file when needed."""
        self._original = None
        self._bgra = None

    def bgra(self) -> np.ndarray:
        """The original pixels (BGRA), read once."""
        if self._bgra is None:
            self._bgra = qimage_to_bgra(self.original)
        return self._bgra

    def px_per_pt(self) -> float:
        return self.px_w / max(1e-6, self.w)

    def alpha(self) -> np.ndarray:
        """How much of each original pixel shows, after both masks: uint8."""
        a = self.bgra()[..., 3].astype(np.uint16)
        if self.mask is not None:
            a = a * self.mask // 255
        if self.matte is not None:
            a = a * self.matte // 255
        return a.astype(np.uint8)

    def set_pixels(self, draft: bool = False, **changes):
        """Change any of original / mask / matte / border / tear, then
        rebuild.  `draft`: rebuild just what is shown, from a small copy -
        quick enough to follow a slider; recompose() finishes it."""
        if "original" in changes:
            image = changes.pop("original").convertToFormat(QtGui.QImage.Format_ARGB32)
            self._original, self.px_w, self.px_h = image, image.width(), image.height()
            self._bgra = None
        for key, value in changes.items():
            setattr(self, key, value)
        if draft and max(self.px_w, self.px_h) > DRAFT_MAX:
            self._draft()
        else:
            self.recompose()

    def _draft(self):
        """What is shown, worked out at DRAFT_MAX px; `image` waits for recompose()."""
        import cv2
        from . import matting
        k = DRAFT_MAX / max(self.px_w, self.px_h)
        pixels = self.bgra().copy()
        pixels[..., 3] = self.alpha()
        small = cv2.resize(pixels, (max(1, round(pixels.shape[1] * k)), max(1, round(pixels.shape[0] * k))),
                           interpolation=cv2.INTER_AREA)
        if self.tear:
            from . import wear
            small = wear.apply_tear(small, self.tear, self.px_per_pt() * k)
        pad = 0
        if self.border is not None:
            width, colour, smooth = self.border
            c = QtGui.QColor(colour)
            grown = matting.add_outline(small, width * k, (c.red(), c.green(), c.blue()), smooth * k)
            pad = (grown.shape[1] - small.shape[1]) // 2
            small = grown
        self.prepareGeometryChange()
        self.pad_px = int(round(pad / k))
        self.preview = QtGui.QPixmap.fromImage(bgra_to_qimage(small))
        self.drafted = True
        self.update()

    def recompose(self):
        from . import matting
        self.drafted = False
        if self.mask is None and self.matte is None and self.border is None and not self.tear:
            self._image, self.pad_px = None, 0
        else:
            pixels = self.bgra().copy()
            pixels[..., 3] = self.alpha()
            if self.tear:
                from . import wear
                pixels = wear.apply_tear(pixels, self.tear, self.px_per_pt())
            pad = 0
            if self.border is not None:
                width, colour, smooth = self.border
                c = QtGui.QColor(colour)
                grown = matting.add_outline(pixels, width, (c.red(), c.green(), c.blue()), smooth)
                pad = (grown.shape[1] - pixels.shape[1]) // 2
                pixels = grown
            self._image, self.pad_px = bgra_to_qimage(pixels), pad
            self._bgra = None                        # the numpy copy is rebuilt when needed
        self.version += 1
        self.prepareGeometryChange()
        self._make_preview()
        self.update()

    def _make_preview(self):
        """The everyday on-screen copy, small; a bigger one is made in
        paint() only while the image is drawn bigger than this."""
        image = self.image
        big = max(image.width(), image.height())
        shown = image if big <= PREVIEW_SMALL else image.scaled(
            PREVIEW_SMALL, PREVIEW_SMALL, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.preview = QtGui.QPixmap.fromImage(shown)
        self._big = None
        BIG_PREVIEWS.forget(self)

    def shown_pixmap(self, painter: QtGui.QPainter) -> QtGui.QPixmap:
        """The copy to draw at the painter's scale: the small one, or a
        bigger one made (and kept, within BIG_PREVIEWS) when it is drawn big."""
        if self.drafted:
            return self.preview
        t = painter.worldTransform()
        ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
        need = max(self.w, self.h) * math.hypot(t.m11(), t.m12()) * ratio
        small = max(self.preview.width(), self.preview.height())
        full = max(self.px_w, self.px_h) + 2 * self.pad_px
        if need <= small * 1.15 or full <= small:
            return self.preview
        want = int(min(full, PREVIEW_MAX, need * 1.25))
        if self._big is None or max(self._big.width(), self._big.height()) < min(want, need) * 0.95:
            image = self.image
            self._big = QtGui.QPixmap.fromImage(image if want >= max(image.width(), image.height())
                                                else image.scaled(want, want, QtCore.Qt.KeepAspectRatio,
                                                                  QtCore.Qt.SmoothTransformation))
        BIG_PREVIEWS.touch(self, self._big.width() * self._big.height() * 4)
        return self._big

    def pad_pt(self) -> float:
        return self.pad_px / self.px_per_pt() if self.pad_px else 0.0

    def to_pixels(self, item_point: QtCore.QPointF) -> tuple[float, float]:
        """An item-coordinate point as a position on the original's pixels."""
        return (item_point.x() * self.px_w / max(1e-6, self.w),
                item_point.y() * self.px_h / max(1e-6, self.h))

    def set_flip(self, flip_x: bool, flip_y: bool):
        self.flip = (bool(flip_x), bool(flip_y))
        self._apply_flip()

    def _apply_flip(self):
        fx, fy = self.flip
        if not (fx or fy):
            self.setTransform(QtGui.QTransform())
            return
        t = QtGui.QTransform()
        t.translate(self.w / 2, self.h / 2)
        t.scale(-1.0 if fx else 1.0, -1.0 if fy else 1.0)
        t.translate(-self.w / 2, -self.h / 2)
        self.setTransform(t)

    # -- drawing -----------------------------------------------------------------
    def render(self, painter: QtGui.QPainter, ink: QtGui.QColor):
        """Draw at full quality in item coordinates (export)."""
        painter.drawImage(self.boundingRect(), self.image)

    @property
    def pinned(self) -> bool:
        return self.parentItem() is not None

    def boundingRect(self) -> QtCore.QRectF:
        p = self.pad_pt()
        return QtCore.QRectF(-p, -p, self.w + 2 * p, self.h + 2 * p)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        shown = self.shown_pixmap(painter)
        painter.drawPixmap(self.boundingRect(), shown, QtCore.QRectF(shown.rect()))

    def resize(self, w: float, h: float):
        """New size about the same middle, so a turned image stays put."""
        w, h = max(4.0, w), max(4.0, h)
        self.prepareGeometryChange()
        self.setPos(self.pos() + QtCore.QPointF((self.w - w) / 2, (self.h - h) / 2))
        self.w, self.h = w, h
        self.setTransformOriginPoint(w / 2, h / 2)
        self._apply_flip()

    def set_size(self, w: float, h: float):
        """New size with the top-left corner where it was (loading, undo)."""
        self.prepareGeometryChange()
        self.w, self.h = max(4.0, w), max(4.0, h)
        self.setTransformOriginPoint(self.w / 2, self.h / 2)
        self._apply_flip()

    def outline(self) -> QtGui.QPolygonF:
        """The four corners in scene coordinates, turned with it."""
        return self.mapToScene(self.boundingRect())

    def parent_rect(self) -> QtCore.QRectF:
        """The space it covers in its parent's coordinates, rotation included."""
        return self.mapRectToParent(self.boundingRect())

    def natural_aspect(self) -> float:
        return self.px_w / max(1, self.px_h)

    def key(self) -> tuple:
        """Everything about where and what it is - for caches, never for undo."""
        return (self.uid, self.alive, self.pinned, round(self.pos().x(), 3),
                round(self.pos().y(), 3), round(self.w, 3), round(self.h, 3), self.zValue(),
                round(self.rotation(), 3), self.version, self.flip)


LOOK = {                              # a text box's own type: key -> (low, high) or choices
    "font": None,
    "size": (5.0, 96.0),              # pt
    "line": (80.0, 300.0),            # % of the font's line height
    "align": ("left", "centre", "right", "justify"),
    "track": (-10.0, 50.0),           # % of normal letter spacing added
    "weight": ("regular", "bold"),
    "italic": (False, True),
}
WORDS = ("font", "size", "track", "weight", "italic")      # what selected words can set
ALIGN = {"left": QtCore.Qt.AlignLeft, "centre": QtCore.Qt.AlignHCenter,
         "right": QtCore.Qt.AlignRight, "justify": QtCore.Qt.AlignJustify}


# -- styled words: character formats over the box's (or document's) type -------------

def char_props(fmt: QtGui.QTextCharFormat) -> dict:
    """The type a run of words sets for itself (only what it sets)."""
    props = {}
    if fmt.hasProperty(QtGui.QTextFormat.FontFamily) and fmt.fontFamily():
        props["font"] = fmt.fontFamily()
    if fmt.hasProperty(QtGui.QTextFormat.FontPointSize):
        props["size"] = round(fmt.fontPointSize(), 2)
    if fmt.hasProperty(QtGui.QTextFormat.FontLetterSpacing):
        props["track"] = round(fmt.fontLetterSpacing() - 100.0, 2)
    if fmt.hasProperty(QtGui.QTextFormat.FontWeight) and fmt.fontWeight() >= QtGui.QFont.DemiBold:
        props["weight"] = "bold"
    if fmt.hasProperty(QtGui.QTextFormat.FontItalic) and fmt.fontItalic():
        props["italic"] = True
    return props


def set_char(fmt: QtGui.QTextCharFormat, key: str, value):
    """Set one part of a run's type; None (or "*" for key) clears it, so the
    words follow the box's type again."""
    if key == "*":
        for k in WORDS:
            set_char(fmt, k, None)
        return
    if key == "font":
        if value:
            fmt.setFontFamily(value)
        else:
            fmt.clearProperty(QtGui.QTextFormat.FontFamily)
            families = getattr(QtGui.QTextFormat, "FontFamilies", None)
            if families is not None:
                fmt.clearProperty(families)
    elif key == "size":
        if value:
            fmt.setFontPointSize(float(value))
        else:
            fmt.clearProperty(QtGui.QTextFormat.FontPointSize)
    elif key == "track":
        if value is None:
            fmt.clearProperty(QtGui.QTextFormat.FontLetterSpacing)
        else:
            if hasattr(fmt, "setFontLetterSpacingType"):
                fmt.setFontLetterSpacingType(QtGui.QFont.PercentageSpacing)
            fmt.setFontLetterSpacing(100.0 + float(value))
    elif key == "weight":
        if value == "bold":
            fmt.setFontWeight(QtGui.QFont.Bold)
        else:
            fmt.clearProperty(QtGui.QTextFormat.FontWeight)
    elif key == "italic":
        if value:
            fmt.setFontItalic(True)
        else:
            fmt.clearProperty(QtGui.QTextFormat.FontItalic)


def restyle_range(doc: QtGui.QTextDocument, start: int, end: int, key: str, value):
    """Set one part of the type on the words from `start` to `end`, keeping
    whatever else each run sets (the caller owns the undo edit block)."""
    pieces = []
    block = doc.findBlock(start)
    while block.isValid() and block.position() < end:
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                a = max(start, fragment.position())
                b = min(end, fragment.position() + fragment.length())
                if a < b:
                    pieces.append((a, b, QtGui.QTextCharFormat(fragment.charFormat())))
            it += 1
        block = block.next()
    cursor = QtGui.QTextCursor(doc)
    for a, b, fmt in pieces:
        set_char(fmt, key, value)
        cursor.setPosition(a)
        cursor.setPosition(b, QtGui.QTextCursor.KeepAnchor)
        cursor.setCharFormat(fmt)


def doc_runs(doc: QtGui.QTextDocument) -> list[list]:
    """The styled words, for saving: [[start, length, {type}], …] - only
    runs that set something of their own, neighbours with the same type joined."""
    runs: list[list] = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                props = char_props(fragment.charFormat())
                if props:
                    if runs and runs[-1][2] == props and runs[-1][0] + runs[-1][1] == fragment.position():
                        runs[-1][1] += fragment.length()
                    else:
                        runs.append([fragment.position(), fragment.length(), props])
            it += 1
        block = block.next()
    return runs


def apply_runs(doc: QtGui.QTextDocument, runs) -> None:
    """Put saved styled words back (outside the undo history)."""
    if not runs:
        return
    undo = doc.isUndoRedoEnabled()
    doc.setUndoRedoEnabled(False)
    last = doc.characterCount() - 1
    cursor = QtGui.QTextCursor(doc)
    for start, length, props in runs:
        a, b = max(0, min(int(start), last)), max(0, min(int(start) + int(length), last))
        if a >= b:
            continue
        fmt = QtGui.QTextCharFormat()
        for key, value in props.items():
            if key in WORDS:
                set_char(fmt, key, value)
        cursor.setPosition(a)
        cursor.setPosition(b, QtGui.QTextCursor.KeepAnchor)
        cursor.mergeCharFormat(fmt)
    doc.setUndoRedoEnabled(undo)


class NoteText(QtWidgets.QGraphicsTextItem):
    """The editor inside a Note: live only while the note is being written."""

    def __init__(self, controller, note):
        super().__init__(note)
        self.controller = controller
        self.note = note
        self.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)

    def paint(self, painter, option, widget=None):
        quiet = QtWidgets.QStyleOptionGraphicsItem(option)
        quiet.state &= ~(QtWidgets.QStyle.State_Selected | QtWidgets.QStyle.State_HasFocus)
        super().paint(painter, quiet, widget)

    def note_pinned(self) -> bool:
        return self.note.pinned

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self.note.fit()
        if self.controller.write_mode:
            self.controller._write_follow()
        self.controller._refresh_text_panel()
        self.controller.view.viewport().update()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.controller._refresh_text_panel()          # it shows the selected words' type

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)
        self.note.fit()

    def contextMenuEvent(self, event):
        event.ignore()

    def dragEnterEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()


class Note(Thing):
    """A block of text placed anywhere - a text box.  It wraps at `wrap`
    points (-1: one line that grows) and turns about its first corner.  Its
    type is the document's, except what its `look` sets for it alone:
    font, size, line, align, track (see LOOK)."""

    kind = "text"

    def __init__(self, controller, text: str = "", wrap: float = -1.0, uid: int | None = None):
        QtWidgets.QGraphicsItem.__init__(self)
        self._begin(uid)
        self.name = "text"
        self.blob, self.ext, self.pdf_page, self.image = b"", "", None, None
        self.original = None
        self.w, self.h = 8.0, 8.0
        self.wrap = wrap
        self.look: dict = {}                      # this box's own type; missing: the document's
        self.editor = NoteText(controller, self)
        doc = self.editor.document()
        doc.setDocumentMargin(0)
        doc.undoCommandAdded.connect(lambda: controller.push("note", self.uid))
        doc.contentsChanged.connect(self.fit)
        doc.contentsChanged.connect(controller.changed)
        self.editor.setTextWidth(wrap)
        if text:
            doc.setUndoRedoEnabled(False)
            self.editor.setPlainText(text)
            doc.setUndoRedoEnabled(True)
        self.fit()

    def text(self) -> str:
        return self.editor.toPlainText()

    def style(self, font: QtGui.QFont, block: QtGui.QTextBlockFormat, ink: QtGui.QColor):
        """Set the type (the document's, with the box's look over it); kept
        out of the note's undo."""
        self.version += 1
        doc = self.editor.document()
        doc.setUndoRedoEnabled(False)
        doc.setDefaultFont(font)
        cursor = QtGui.QTextCursor(doc)
        cursor.select(QtGui.QTextCursor.Document)
        cursor.mergeBlockFormat(block)
        doc.setUndoRedoEnabled(True)
        self.editor.setDefaultTextColor(ink)
        self.fit()

    def fit(self):
        rect = self.editor.boundingRect()
        line = QtGui.QFontMetricsF(self.editor.document().defaultFont()).height()
        self.prepareGeometryChange()
        self.w = max(8.0, rect.width())
        self.h = max(line, rect.height())
        self.setTransformOriginPoint(0.0, 0.0)          # turns about where it began

    def paint(self, painter, option, widget=None):
        pass                                             # the editor draws the words

    def set_width(self, width: float):
        self.wrap = max(24.0, width)
        self.editor.setTextWidth(self.wrap)
        self.fit()

    def resize(self, w: float, h: float):
        self.set_width(w)

    def set_size(self, w: float, h: float):
        if self.wrap > 0:
            self.set_width(w)

    def natural_aspect(self) -> float:
        return self.w / max(1.0, self.h)

    def render(self, painter: QtGui.QPainter, ink: QtGui.QColor):
        context = QtGui.QAbstractTextDocumentLayout.PaintContext()
        context.cursorPosition = -1
        context.palette.setColor(QtGui.QPalette.Text, ink)
        self.editor.document().documentLayout().draw(painter, context)


class GhostPage(QtWidgets.QGraphicsItem):
    """Another page of the document, beside the live one in the spread and
    all-pages views.  It is drawn straight from the document (vector, so it
    is sharp at any zoom), or from a distressed rendering in distress view.
    Click it and it becomes the live page."""

    def __init__(self, controller, index: int):
        super().__init__()
        self.controller = controller
        self.index = index
        self.distressed: tuple | None = None     # (key, QImage) in distress view
        self.setZValue(-10)

    def boundingRect(self) -> QtCore.QRectF:
        sheet = self.controller.sheet
        return QtCore.QRectF(0.0, 0.0, sheet.W, sheet.H)

    def paint(self, painter, option, widget=None):
        self.controller.paint_ghost(painter, self)


def bump_uids(uid: int):
    """Keep fresh ids above any loaded from a project."""
    global _uids
    current = next(_uids)
    _uids = itertools.count(max(current, uid + 1))


class PageText(QtWidgets.QGraphicsTextItem):
    """Qt's own editor (caret, selection, clipboard, input methods), minus
    the focus rectangle and the context menu."""

    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.setTextInteractionFlags(QtCore.Qt.TextEditorInteraction)

    def note_pinned(self) -> bool:
        return True

    def paint(self, painter, option, widget=None):
        quiet = QtWidgets.QStyleOptionGraphicsItem(option)
        quiet.state &= ~(QtWidgets.QStyle.State_Selected | QtWidgets.QStyle.State_HasFocus)
        super().paint(painter, quiet, widget)

    def keyPressEvent(self, event):
        # follow the caret only if it moved or the words changed - a bare
        # Cmd or Shift must not pull the view back to the caret's page
        before = (self.textCursor().position(), self.textCursor().anchor(),
                  self.document().revision())
        super().keyPressEvent(event)
        after = (self.textCursor().position(), self.textCursor().anchor(),
                 self.document().revision())
        if after != before:
            self.controller.caret_moved()

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)
        self.controller.caret_moved()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.controller.caret_moved(follow=False)

    def contextMenuEvent(self, event):
        event.ignore()

    def dragEnterEvent(self, event):
        event.ignore()

    def dropEvent(self, event):
        event.ignore()


class FacingLayer(QtWidgets.QGraphicsItem):
    """On the live page, what hangs over from the page beside it in its
    spread: a picture placed across the gutter belongs to one page but shows
    on both.  Two of these sit in the strip - behind the words and in front
    - and draw the facing page's things, shifted onto this page."""

    def __init__(self, sheet, front: bool):
        super().__init__(sheet.strip)
        self.sheet = sheet
        self.front = front
        self.setZValue(1e6 if front else -1e6)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)

    def boundingRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(-1e5, -1e5, 2e5, 1e8)      # the sheet clips it to the page

    def paint(self, painter, option, widget=None):
        paint = getattr(self.sheet.controller, "paint_facing", None)
        if paint is not None:
            paint(painter, self.front)


class StockLayer(QtWidgets.QGraphicsItem):
    """A paper photograph blended over the whole page - words, images and
    all - with one of Qt's blend modes, as a paper texture on top in
    Photoshop.  It sits above the strip and below the distress preview,
    which renders the same blend itself.  It takes no clicks."""

    MODES = {
        "multiply": QtGui.QPainter.CompositionMode_Multiply,
        "overlay": QtGui.QPainter.CompositionMode_Overlay,
        "soft light": QtGui.QPainter.CompositionMode_SoftLight,
        "screen": QtGui.QPainter.CompositionMode_Screen,
        "normal": QtGui.QPainter.CompositionMode_SourceOver,
    }

    def __init__(self, sheet):
        super().__init__(sheet)
        self.sheet = sheet
        self.image: QtGui.QImage | None = None
        self.mode = "multiply"
        self.amount = 1.0
        self.setZValue(500)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)

    def set(self, image: QtGui.QImage | None, mode: str, amount: float):
        self.image, self.mode, self.amount = image, mode, amount
        self.setVisible(image is not None)
        self.update()

    def boundingRect(self) -> QtCore.QRectF:
        return self.sheet.rect()

    def paint(self, painter, option, widget=None):
        if self.image is not None:
            draw_stock(painter, self.boundingRect(), self.image, self.mode, self.amount)


def draw_stock(painter: QtGui.QPainter, rect: QtCore.QRectF, image: QtGui.QImage, mode: str,
               amount: float):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.setCompositionMode(StockLayer.MODES.get(mode, QtGui.QPainter.CompositionMode_Multiply))
    painter.setOpacity(max(0.0, min(1.0, amount)))
    painter.drawImage(rect, image)
    painter.restore()


class Sheet(QtWidgets.QGraphicsRectItem):
    """The one page on the canvas: paper, a clip, and the strip of pages."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setFlag(QtWidgets.QGraphicsItem.ItemClipsChildrenToShape)
        self.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        self.setZValue(-10)
        self.strip = QtWidgets.QGraphicsRectItem(self)
        self.strip.setFlag(QtWidgets.QGraphicsItem.ItemHasNoContents)
        self.strip.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        self.doc = QtGui.QTextDocument()
        self.doc.documentLayout().setProperty("cursorWidth", 1)
        self.text = PageText(controller, self.strip)
        self.text.setDocument(self.doc)
        self.text.setZValue(0)
        self.offset = 0.0
        self.W, self.H = 595.0, 842.0
        self.stock = StockLayer(self)
        self.stock.setVisible(False)
        self.facing_layers = (FacingLayer(self, False), FacingLayer(self, True))

    # -- geometry ------------------------------------------------------------
    def set_geometry(self, w: float, h: float, side: float, head: float):
        self.W, self.H = w, h
        self.prepareGeometryChange()
        self.setRect(0.0, 0.0, w, h)
        self.doc.setPageSize(QtCore.QSizeF(w, h))
        self.set_margins(side, head)
        self.set_offset(self.offset)

    def set_margins(self, side: float, head: float):
        """`side` left and right, `head` top and bottom - on every page."""
        frame = self.doc.rootFrame()
        fmt = frame.frameFormat()
        fmt.setLeftMargin(side)
        fmt.setRightMargin(side)
        fmt.setTopMargin(head)
        fmt.setBottomMargin(head)
        frame.setFrameFormat(fmt)

    def set_offset(self, y: float):
        self.offset = y
        self.strip.setPos(0.0, -y)
        self.show_page(int(round(y / self.H)) if self.H else 0)

    def show_page(self, index: int):
        """Only page `index`'s own things show on the live page: a thing that
        hangs off another page's foot or head stays on its page (what hangs
        over the gutter from the facing page is drawn by the facing layers)."""
        for thing in self.pinned():
            thing.setVisible(self.page_of(thing) == index)

    def set_paper(self, colour: QtGui.QColor, surface: QtGui.QImage | None = None):
        """Flat colour, or a paper stock image drawn over the whole page."""
        self.setBrush(QtGui.QBrush(colour))
        self.surface = surface
        self.update()

    def paint(self, painter, option, widget=None):
        surface = getattr(self, "surface", None)
        if surface is None:
            super().paint(painter, option, widget)
            return
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(self.rect(), surface)

    # -- pages ---------------------------------------------------------------
    def text_pages(self) -> int:
        return max(1, self.doc.pageCount())

    def pinned(self) -> list[Thing]:
        return [c for c in self.strip.childItems() if isinstance(c, Thing)]

    def page_of(self, thing) -> int:
        """The page a pinned thing belongs to: the one it was pinned to (it may
        hang off it - bleed), or, for one that never said, the one its middle is on."""
        home = getattr(thing, "home", None)
        if home is not None:
            return home
        return max(0, int(thing.parent_rect().center().y() // self.H))

    def facing(self, index: int):
        """(page beside `index` in its spread, dx, dy): things on that page
        show on `index` moved by (dx, dy) in strip points; None for a page
        that stands alone (a cover)."""
        facing = getattr(self.controller, "facing", None)
        return facing(index) if facing is not None else None

    def page_things(self, index: int) -> list[tuple]:
        """What shows on page `index`, bottom to top: (thing, dx, dy) - its
        own things (cut at its edges), and the overhang of things on the
        facing page of its spread."""
        clip = QtCore.QRectF(0.0, index * self.H, self.W, self.H)
        things = self.pinned()
        # its own things only: what hangs off the page above or below stays there
        shown = [(t, 0.0, 0.0) for t in things
                 if self.page_of(t) == index and t.parent_rect().intersects(clip)]
        face = self.facing(index)
        if face is not None:
            other, dx, dy = face
            shown += [(t, dx, dy) for t in things
                      if self.page_of(t) == other and t.parent_rect().translated(dx, dy).intersects(clip)]
        shown.sort(key=lambda e: e[0].zValue())
        return shown

    def pages(self) -> int:
        """Pages with something on them: the text's, and each pinned thing's
        own page (the one its middle is on) - not every page it reaches, so a
        picture bleeding off a page's foot doesn't keep the next page alive."""
        count = self.text_pages()
        for thing in self.pinned():
            if thing.parent_rect().bottom() > 0:
                count = max(count, self.page_of(thing) + 1)
        return count

    def caret_span(self) -> tuple[float, float]:
        """Top and bottom of the caret's line, in strip coordinates."""
        cursor = self.text.textCursor()
        block = cursor.block()
        top = self.doc.documentLayout().blockBoundingRect(block).top()
        layout = block.layout()
        if layout is not None and layout.lineCount():
            line = layout.lineForTextPosition(cursor.position() - block.position())
            if line.isValid():
                return top + line.y(), top + line.y() + line.height()
        height = QtGui.QFontMetricsF(self.doc.defaultFont()).height()
        return top, top + height

    def caret_page(self) -> int:
        top, bottom = self.caret_span()
        return int(((top + bottom) / 2.0) // self.H)

    def scene_page_rect(self) -> QtCore.QRectF:
        return self.mapRectToScene(self.rect())
