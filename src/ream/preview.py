"""
Preview: the pages as they will come out, one after another, full screen -
InDesign's presentation mode.

Nothing but the finished page: distressed or clean as the export is, with
the paper stock, its blend and the ink - drawn by the same code the PDF
export uses (export.final_page), at the screen's own resolution.  No canvas,
no panels, no edges, no selection; the pointer hides when it rests.

| keys                          | does |
| ----------------------------- | ---- |
| → ↓ Space PgDn, click right   | next |
| ← ↑ ⇧Space PgUp, click left   | previous |
| Home / End                    | first / last |
| S                             | single pages / spreads |
| B / W / G / C                 | black / white / grey / the canvas colour behind |
| Esc, ⇧⌘P                      | back to writing, on the page you were looking at |

A distressed page takes a moment: the clean page shows at once and the
finished one replaces it.  The pages either side are worked out in the
background, so turning feels immediate.
"""
from __future__ import annotations

import sys
from dataclasses import replace

from PyQt5 import QtCore, QtGui, QtWidgets

from . import distress, export, style

BACKGROUNDS = {"black": "#000000", "grey": "#2b2b2b", "white": "#ffffff"}   # and "canvas"
MARGIN = 28                       # px round the page(s)


class Preview(QtWidgets.QWidget):
    ready = QtCore.pyqtSignal(object, object, object)      # key, page, image

    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.units: list[tuple] = []
        self.at = 0
        self.spread = False
        self.background = "canvas"
        self.cache: dict[tuple, QtGui.QImage] = {}
        self.pending: set[tuple] = set()
        self._wheel = 0
        self._label_until = 0.0
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent)
        self.ready.connect(self._arrived)
        self.idle = QtCore.QTimer(self, singleShot=True, interval=1400)
        self.idle.timeout.connect(lambda: self.setCursor(QtCore.Qt.BlankCursor))
        self.label_timer = QtCore.QTimer(self, singleShot=True, interval=1600)
        self.label_timer.timeout.connect(self.update)
        self.hide()

    # -- what is shown -----------------------------------------------------------
    def start(self, page: int, spread: bool):
        self.spread = spread
        self.cache.clear()
        self.pending.clear()
        self._layout(page)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus(QtCore.Qt.OtherFocusReason)
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.idle.start()
        self._show_label()
        self._prepare()

    def _layout(self, page: int):
        count = self.c.sheet.pages()
        if self.spread:
            # a page standing alone (a cover, a back cover) is centred, not
            # left beside an empty half
            self.units = [tuple(p for p in pair if p is not None) for pair in self.c.spreads(count)]
        else:
            self.units = [(i,) for i in range(count)]
        self.at = next((k for k, unit in enumerate(self.units) if page in unit), 0)

    def current_page(self) -> int:
        return next((p for p in self.units[self.at] if p is not None), 0)

    def go(self, k: int):
        k = max(0, min(k, len(self.units) - 1))
        if k != self.at:
            self.at = k
            self._show_label()
            self._prepare()
            self.update()

    def toggle_spread(self):
        page = self.current_page()
        self.spread = not self.spread
        self._layout(page)
        self._show_label()
        self._prepare()
        self.update()

    # -- sizes --------------------------------------------------------------------
    def ratio(self) -> float:
        return self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0

    def fit(self) -> float:
        """Points to screen pixels: the unit (page or spread) fills the screen."""
        w, h = self.c.sheet.W, self.c.sheet.H
        slots = 2 if self.spread else 1          # one scale for covers and spreads alike
        return max(0.05, min((self.width() - 2 * MARGIN) / (slots * w),
                             (self.height() - 2 * MARGIN) / h))

    def dpi(self) -> float:
        """The screen's resolution, but never under 150 dpi: distress worked
        out much coarser than that stops looking like the 300 dpi export."""
        return max(150.0, min(600.0, 72.0 * self.fit() * self.ratio()))

    def rects(self) -> list[tuple[int | None, QtCore.QRectF]]:
        unit = self.units[self.at] if self.units else ()
        k = self.fit()
        pw, ph = self.c.sheet.W * k, self.c.sheet.H * k
        left = (self.width() - pw * len(unit)) / 2
        top = (self.height() - ph) / 2
        return [(page, QtCore.QRectF(left + i * pw, top, pw, ph)) for i, page in enumerate(unit)]

    # -- rendering -------------------------------------------------------------------
    def key(self, page: int, dpi: float, finished: bool) -> tuple:
        c = self.c
        return (page, round(dpi, 1), finished, c.doc.revision(), c.things_key(),
                tuple(vars(c.fmt).items()), tuple(c.distress.to_dict().items()))

    def clean(self, page: int, dpi: float) -> QtGui.QImage:
        key = self.key(page, dpi, False)
        if key not in self.cache:
            c = self.c
            self.cache[key] = export.final_page(c.sheet, page, dpi, replace(c.distress, enabled=False),
                                                c.paper(), c.ink(), c.density(), c.paper_stock())
        return self.cache[key]

    def finished(self, page: int, dpi: float) -> QtGui.QImage | None:
        """The page as exported - None while it is still being worked out."""
        if not self.c.distress.enabled:
            return self.clean(page, dpi)
        return self.cache.get(self.key(page, dpi, True))

    def request(self, page: int, dpi: float):
        c = self.c
        if not c.distress.enabled:
            self.clean(page, dpi)
            return
        key = self.key(page, dpi, True)
        if key in self.cache or key in self.pending:
            return
        self.pending.add(key)
        layers = export.page_layers(c.sheet, page, dpi, c.ink())
        settings, paper, density = replace(c.distress), c.paper(), c.density()
        stock = c.paper_stock()
        sheet = c.sheet

        def work():
            try:
                base = export.stock(sheet, dpi, None, paper, stock)
                out = distress.compose(layers, export.rgb(paper), settings, dpi, density=density,
                                       base=base, over=export.over(sheet, dpi, None, stock))
                self.ready.emit(key, page, export.from_rgb(out))
            except Exception as exc:
                print("ream: preview failed:", exc, file=sys.stderr)
        c._pool.submit(work)

    def _arrived(self, key, page, image):
        self.pending.discard(key)
        self.cache[key] = image
        if len(self.cache) > 24:                          # keep memory in check
            for old in list(self.cache)[:8]:
                self.cache.pop(old, None)
        self.update()

    def _prepare(self):
        """This unit first, then the ones either side."""
        if not self.units:
            return
        dpi = self.dpi()
        for k in (self.at, self.at + 1, self.at - 1):
            if 0 <= k < len(self.units):
                for page in self.units[k]:
                    if page is not None:
                        self.request(page, dpi)

    # -- drawing ------------------------------------------------------------------------
    def _show_label(self):
        self._label_until = QtCore.QTime.currentTime().msecsSinceStartOfDay() + 1600
        self.label_timer.start()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        backdrop = self.backdrop()
        painter.fillRect(self.rect(), backdrop)
        if not self.units:
            return
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        dpi = self.dpi()
        waiting = False
        for page, rect in self.rects():
            if page is None:
                continue
            image = self.finished(page, dpi)
            if image is None:
                image, waiting = self.clean(page, dpi), True
            painter.drawImage(rect, image)
        now = QtCore.QTime.currentTime().msecsSinceStartOfDay()
        if now < self._label_until or waiting:
            pages = [p + 1 for p in self.units[self.at] if p is not None]
            text = "–".join(f"{p:02d}" for p in pages) + f" / {self.c.sheet.pages():02d}"
            if waiting:
                text += " · finishing"
            painter.setFont(style.ui_font(11))
            dark = backdrop.lightness() < 128
            painter.setPen(QtGui.QColor("#8c8b86" if dark else "#77766f"))
            painter.drawText(self.rect().adjusted(0, 0, 0, -10),
                             QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom, text)

    def backdrop(self) -> QtGui.QColor:
        if self.background == "canvas":
            return QtGui.QColor(self.c.canvas_colour())
        return QtGui.QColor(BACKGROUNDS[self.background])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._prepare()

    # -- input ---------------------------------------------------------------------------
    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        ahead = (QtCore.Qt.Key_Right, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageDown)
        back = (QtCore.Qt.Key_Left, QtCore.Qt.Key_Up, QtCore.Qt.Key_PageUp)
        if key == QtCore.Qt.Key_Escape:
            self.c.leave_preview()
        elif key in ahead or (key == QtCore.Qt.Key_Space and not mods & QtCore.Qt.ShiftModifier):
            self.go(self.at + 1)
        elif key in back or key == QtCore.Qt.Key_Space:
            self.go(self.at - 1)
        elif key == QtCore.Qt.Key_Home:
            self.go(0)
        elif key == QtCore.Qt.Key_End:
            self.go(len(self.units) - 1)
        elif key == QtCore.Qt.Key_S:
            self.toggle_spread()
        elif key in (QtCore.Qt.Key_B, QtCore.Qt.Key_W, QtCore.Qt.Key_G, QtCore.Qt.Key_C):
            self.background = {QtCore.Qt.Key_B: "black", QtCore.Qt.Key_W: "white",
                               QtCore.Qt.Key_G: "grey", QtCore.Qt.Key_C: "canvas"}[key]
            self.update()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.idle.start()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.go(self.at + (1 if event.pos().x() > self.width() / 2 else -1))

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y() or -event.pixelDelta().y() * 2
        if abs(self._wheel) >= 120:
            self.go(self.at + (1 if self._wheel < 0 else -1))
            self._wheel = 0
        event.accept()

    def contextMenuEvent(self, event):
        event.accept()
