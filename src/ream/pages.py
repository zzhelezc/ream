"""
The pages panel's strip: every page as a thumbnail, in spreads, as in
InDesign's Pages panel.

Click a page to go to it.  Drag one to move it: a bar shows where it will
land.  Facing pages touch; with a cover the first page stands alone on the
right, with a back cover the last alone on the left (see Ream.spreads).
"""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from . import export, style

THUMB_W = 58                    # px, one page's thumbnail
ROW_GAP = 22                    # px between spreads, room for the numbers


class PageStrip(QtWidgets.QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.cache: dict[int, tuple] = {}
        self.pressed: int | None = None
        self.press_at = QtCore.QPoint()
        self.dragging = False
        self.drop: int | None = None              # insert before this page (n = at the end)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    # -- geometry ------------------------------------------------------------------
    def thumb_h(self) -> int:
        sheet = self.controller.sheet
        return int(round(THUMB_W * sheet.H / sheet.W))

    def spreads(self):
        return self.controller.spreads(self.controller.sheet.pages())

    def rects(self) -> dict[int, QtCore.QRect]:
        """Each page's thumbnail rect, spreads one under another, spine centred."""
        out = {}
        centre = self.width() // 2
        th = self.thumb_h()
        for row, (left, right) in enumerate(self.spreads()):
            y = 6 + row * (th + ROW_GAP)
            if left is not None:
                out[left] = QtCore.QRect(centre - THUMB_W, y, THUMB_W, th)
            if right is not None:
                out[right] = QtCore.QRect(centre, y, THUMB_W, th)
        return out

    def sizeHint(self) -> QtCore.QSize:
        rows = max(1, len(self.spreads()))
        return QtCore.QSize(260, 12 + rows * (self.thumb_h() + ROW_GAP))

    def refresh(self):
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()
        self.update()

    # -- thumbnails ------------------------------------------------------------------
    def thumbnail(self, index: int) -> QtGui.QImage:
        c = self.controller
        key = (c.doc.revision(), c.things_key(), tuple(sorted(vars(c.fmt).items())), index,
               c.doc.pageCount())
        hit = self.cache.get(index)
        if hit and hit[0] == key:
            return hit[1]
        ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        w, h = int(THUMB_W * ratio), int(self.thumb_h() * ratio)
        image = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(c.paper())
        painter = QtGui.QPainter(image)
        if getattr(c, "_surface", None) is not None:
            painter.drawImage(QtCore.QRectF(0, 0, w, h), c._surface)
        painter.scale(w / c.sheet.W, h / c.sheet.H)
        export.draw_page(painter, c.sheet, index, c.ink())
        painter.end()
        image.setDevicePixelRatio(ratio)
        self.cache[index] = (key, image)
        return image

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setFont(style.ui_font(10))
        current = self.controller.page
        rects = self.rects()
        for index, rect in rects.items():
            painter.drawImage(rect, self.thumbnail(index))
            painter.setPen(QtGui.QPen(style.qc(style.INK), 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            if index == current:
                painter.setPen(QtGui.QPen(style.qc(style.INK), 2))
                painter.drawRect(rect.adjusted(-2, -2, 1, 1))
            painter.setPen(style.qc("#8c8b86"))
            label = QtCore.QRect(rect.left(), rect.bottom() + 2, rect.width(), 14)
            painter.drawText(label, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, f"{index + 1:02d}")
        if self.dragging and self.drop is not None:
            bar = self.drop_bar(rects)
            if bar is not None:
                painter.fillRect(bar, style.qc(style.INK))

    # -- dragging ------------------------------------------------------------------------
    def page_at(self, pos: QtCore.QPoint) -> int | None:
        for index, rect in self.rects().items():
            if rect.adjusted(-2, -2, 2, 2).contains(pos):
                return index
        return None

    def drop_index(self, pos: QtCore.QPoint) -> int:
        """Where a dragged page would go: before the page under the pointer,
        or after it on its right half."""
        rects = self.rects()
        best, gap = len(rects), None
        for index, rect in rects.items():
            for spot, x in ((index, rect.left()), (index + 1, rect.right())):
                d = abs(pos.x() - x) + 3 * abs(pos.y() - rect.center().y())
                if gap is None or d < gap:
                    best, gap = spot, d
        return best

    def drop_bar(self, rects) -> QtCore.QRect | None:
        if not rects:
            return None
        n = len(rects)
        if self.drop < n:
            r = rects[self.drop]
            return QtCore.QRect(r.left() - 2, r.top() - 3, 3, r.height() + 6)
        r = rects[n - 1]
        return QtCore.QRect(r.right() - 1, r.top() - 3, 3, r.height() + 6)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.pressed = self.page_at(event.pos())
            self.press_at = event.pos()
            self.dragging = False

    def mouseMoveEvent(self, event):
        if self.pressed is None:
            return
        if not self.dragging and (event.pos() - self.press_at).manhattanLength() > 4:
            self.dragging = True
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        if self.dragging:
            self.drop = self.drop_index(event.pos())
            self.update()

    def mouseReleaseEvent(self, event):
        source, self.pressed = self.pressed, None
        self.setCursor(QtCore.Qt.PointingHandCursor)
        if source is None:
            return
        if self.dragging:
            self.dragging = False
            drop, self.drop = self.drop_index(event.pos()), None
            target = drop - 1 if drop > source else drop
            if target != source:
                self.controller.move_page(source, target)
            self.update()
            return
        self.controller.go_to_page(source)
        self.update()

    def mouseDoubleClickEvent(self, event):
        index = self.page_at(event.pos())
        if index is not None:
            self.controller.go_to_page(index)
            self.controller.fit_page()
