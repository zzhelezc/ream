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

from PyQt5 import QtCore, QtGui, QtWidgets

PREVIEW_MAX = 2400          # px: the on-screen copy of a big image is no larger
_uids = itertools.count(1)


class Thing(QtWidgets.QGraphicsItem):
    """An image or a PDF page.  Keeps its source bytes (for the project file)
    and its full-resolution pixels (for export); draws a smaller copy."""

    kind = "image"

    def __init__(self, image: QtGui.QImage, size: QtCore.QSizeF, blob: bytes, ext: str,
                 pdf_page: int | None = None, name: str = "", uid: int | None = None):
        super().__init__()
        self._begin(uid)
        self.image = image
        self.blob = blob
        self.ext = ext
        self.pdf_page = pdf_page
        self.name = name
        self.w, self.h = float(size.width()), float(size.height())
        big = max(image.width(), image.height())
        shown = image if big <= PREVIEW_MAX else image.scaled(
            PREVIEW_MAX, PREVIEW_MAX, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.preview = QtGui.QPixmap.fromImage(shown)
        self.setTransformOriginPoint(self.w / 2, self.h / 2)    # turns about its middle

    def _begin(self, uid: int | None):
        self.uid = uid if uid is not None else next(_uids)
        bump_uids(self.uid)
        self.alive = True
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)

    def render(self, painter: QtGui.QPainter, ink: QtGui.QColor):
        """Draw at full quality in item coordinates (export)."""
        painter.drawImage(self.boundingRect(), self.image)

    @property
    def pinned(self) -> bool:
        return self.parentItem() is not None

    def boundingRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(0.0, 0.0, self.w, self.h)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawPixmap(self.boundingRect(), self.preview, QtCore.QRectF(self.preview.rect()))

    def resize(self, w: float, h: float):
        """New size about the same middle, so a turned image stays put."""
        w, h = max(4.0, w), max(4.0, h)
        self.prepareGeometryChange()
        self.setPos(self.pos() + QtCore.QPointF((self.w - w) / 2, (self.h - h) / 2))
        self.w, self.h = w, h
        self.setTransformOriginPoint(w / 2, h / 2)

    def set_size(self, w: float, h: float):
        """New size with the top-left corner where it was (loading, undo)."""
        self.prepareGeometryChange()
        self.w, self.h = max(4.0, w), max(4.0, h)
        self.setTransformOriginPoint(self.w / 2, self.h / 2)

    def outline(self) -> QtGui.QPolygonF:
        """The four corners in scene coordinates, turned with it."""
        return self.mapToScene(self.boundingRect())

    def parent_rect(self) -> QtCore.QRectF:
        """The space it covers in its parent's coordinates, rotation included."""
        return self.mapRectToParent(self.boundingRect())

    def natural_aspect(self) -> float:
        return self.image.width() / max(1, self.image.height())


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
        self.controller.view.viewport().update()

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
    """A block of text placed anywhere.  It wraps at `wrap` points (-1: one
    line that grows), turns about its first corner, and takes the document's
    face, size and spacing."""

    kind = "text"

    def __init__(self, controller, text: str = "", wrap: float = -1.0, uid: int | None = None):
        QtWidgets.QGraphicsItem.__init__(self)
        self._begin(uid)
        self.name = "text"
        self.blob, self.ext, self.pdf_page, self.image = b"", "", None, None
        self.w, self.h = 8.0, 8.0
        self.wrap = wrap
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
        """Follow the document's type; kept out of the note's undo."""
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

    def set_paper(self, colour: QtGui.QColor):
        self.setBrush(QtGui.QBrush(colour))

    # -- pages ---------------------------------------------------------------
    def text_pages(self) -> int:
        return max(1, self.doc.pageCount())

    def pinned(self) -> list[Thing]:
        return [c for c in self.strip.childItems() if isinstance(c, Thing)]

    def pages(self) -> int:
        """Pages with something on them: the text's, and any a pinned thing
        reaches."""
        count = self.text_pages()
        for thing in self.pinned():
            bottom = thing.parent_rect().bottom()
            if bottom > 0:
                count = max(count, int((bottom - 0.5) // self.H) + 1)
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
