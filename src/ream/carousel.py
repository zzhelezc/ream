"""
The carousel: instagram mode's board.

In instagram mode the book is put away and the canvas holds a carousel - a
row of Instagram-shaped slides touching edge to edge, as one wide board.
Pictures, text boxes and stamps go on it as on a page (dropped, pasted,
drawn with T), anywhere, across slides: the slide edges are guides only,
so the carousel is seamless by construction - the slides are the board cut
in equal widths.

| shape   | a slide (Instagram, at 1080 wide) |
| ------- | --------------------------------- |
| 4:5     | 1080 x 1350 - the most room on screen |
| 1:1     | 1080 x 1080 |
| 3:4     | 1080 x 1440 |
| 1.91:1  | 1080 x 566 |

On the board a slide is SLIDE_W points wide, so type and pictures size like
they do on a page; the export scales it to the chosen width in pixels.

`render()` lays the board out as one picture (clean, or distressed like a
page: each picture and text block its own layer); `slides()` cuts it;
`full_slide()` fits the whole picture into one more slide of the same shape
(Instagram makes every image in a carousel the first one's shape).
`CarouselPreview` swipes through the slides the way Instagram does.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import replace

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from . import distress, export, style

SHAPES = {"4:5": 1350, "1:1": 1080, "3:4": 1440, "1.91:1": 566}     # height at 1080 wide
SLIDE_W = 420.0                  # points: a slide on the board
WIDTHS = (1080, 1440, 2160)
FULL = ("last slide", "last slide + file", "file", "no")
BACKGROUNDS = ["#ffffff", "#f4f1ea", "#e4e1d6", "#d8d2c2", "#141414", "#e53b2c", "#2f4bd8"]
DEFAULT = {"shape": "4:5", "slides": 3, "background": "#ffffff", "width": 1080,
           "finish": "as set", "full": "last slide", "format": "jpg"}
MAX_SLIDES = 20


class Carousel(QtWidgets.QGraphicsRectItem):
    """The board: `slides` slides of `shape`, side by side; what is pinned to
    it are its children, clipped to it (what is cut off doesn't export)."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.s = dict(DEFAULT)
        self.current = 0                       # the slide last clicked: + slide / remove act on it
        self.setFlag(QtWidgets.QGraphicsItem.ItemClipsChildrenToShape)
        self.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        self.setZValue(-10)
        self.apply()

    # -- shape --------------------------------------------------------------------
    @property
    def slide_w(self) -> float:
        return SLIDE_W

    @property
    def slide_h(self) -> float:
        return SLIDE_W * SHAPES.get(self.s["shape"], 1350) / 1080.0

    @property
    def slides(self) -> int:
        return max(1, int(self.s["slides"]))

    def apply(self):
        self.prepareGeometryChange()
        self.setRect(0.0, 0.0, self.slides * self.slide_w, self.slide_h)
        self.setBrush(QtGui.QBrush(QtGui.QColor(self.s["background"])))
        self.update()

    def state(self) -> dict:
        return dict(self.s)

    def set_state(self, state: dict | None):
        self.s = {**DEFAULT, **{k: v for k, v in (state or {}).items() if k in DEFAULT}}
        self.current = min(self.current, self.slides - 1)
        self.apply()

    def things(self) -> list:
        return [c for c in self.childItems() if getattr(c, "alive", False)]

    def slide_at(self, scene_point: QtCore.QPointF) -> int | None:
        local = self.mapFromScene(scene_point)
        if not self.rect().contains(local):
            return None
        return max(0, min(self.slides - 1, int(local.x() // self.slide_w)))

    def slide_rect(self, n: int) -> QtCore.QRectF:
        """Slide `n` in scene coordinates."""
        return self.mapRectToScene(QtCore.QRectF(n * self.slide_w, 0.0, self.slide_w, self.slide_h))

    # -- slides in and out (the things right of the change move with it) ---------
    def insert_after(self, n: int):
        edge = (n + 1) * self.slide_w
        for thing in self.things():
            if thing.mapRectToParent(thing.boundingRect()).center().x() > edge:
                thing.moveBy(self.slide_w, 0.0)
        self.s["slides"] = self.slides + 1
        self.current = n + 1
        self.apply()

    def remove(self, n: int):
        if self.slides <= 1:
            return
        edge = (n + 1) * self.slide_w
        for thing in self.things():
            if thing.mapRectToParent(thing.boundingRect()).center().x() > edge:
                thing.moveBy(-self.slide_w, 0.0)
        self.s["slides"] = self.slides - 1
        self.current = max(0, min(n, self.slides - 1))
        self.apply()


# -- the picture ---------------------------------------------------------------------

def _draw(painter: QtGui.QPainter, board: Carousel, thing, ink: QtGui.QColor):
    painter.save()
    placed, _ok = thing.itemTransform(board)
    painter.setTransform(placed, True)
    thing.render(painter, ink)
    painter.restore()


def render(board: Carousel, k: float, settings: distress.Settings, ink: QtGui.QColor,
           density: float = 1.0) -> QtGui.QImage:
    """The whole board as one picture, k pixels a point: clean, or (settings
    enabled) distressed the way a page is - each picture and text block its
    own layer, laid on the background in order."""
    w = max(1, int(round(board.rect().width() * k)))
    h = max(1, int(round(board.rect().height() * k)))
    things = sorted(board.things(), key=lambda t: t.zValue())
    background = QtGui.QColor(board.s["background"])
    if not settings.enabled:
        image = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)
        image.fill(background)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                               | QtGui.QPainter.TextAntialiasing)
        painter.scale(k, k)
        painter.setClipRect(board.rect())
        for thing in things:
            _draw(painter, board, thing, ink)
        painter.end()
        return image
    pad = int(8 * k * 72 / 300) + 2
    layers = []
    for thing in things:
        box = thing.mapRectToParent(thing.boundingRect()).intersected(board.rect())
        if box.isEmpty():
            continue
        x0, y0 = max(0, int(box.left() * k) - pad), max(0, int(box.top() * k) - pad)
        x1, y1 = min(w, int(math.ceil(box.right() * k)) + pad), min(h, int(math.ceil(box.bottom() * k)) + pad)
        if x1 <= x0 or y1 <= y0:
            continue
        layer = QtGui.QImage(x1 - x0, y1 - y0, QtGui.QImage.Format_ARGB32_Premultiplied)
        layer.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(layer)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                               | QtGui.QPainter.TextAntialiasing)
        painter.translate(-x0, -y0)
        painter.scale(k, k)
        painter.setClipRect(board.rect())
        _draw(painter, board, thing, ink)
        painter.end()
        kind = "image" if getattr(thing, "kind", "image") == "image" else "text"
        layers.append(distress.Layer(export.to_numpy(layer), y0, x0, kind))
    colour = (background.red(), background.green(), background.blue())
    out = distress.compose(layers, colour, settings, k * 72.0, density=density, shape=(h, w))
    return export.from_rgb(out)


def slides(picture: QtGui.QImage, count: int) -> list[QtGui.QImage]:
    """The picture cut edge to edge into `count` slides."""
    step = picture.width() / max(1, count)
    return [picture.copy(int(round(n * step)), 0, int(round((n + 1) * step)) - int(round(n * step)),
                         picture.height()) for n in range(count)]


def fit(picture_w: float, picture_h: float, box: QtCore.QRectF, margin: float = 0.04) -> QtCore.QRectF:
    room = box.adjusted(box.width() * margin, box.height() * margin,
                        -box.width() * margin, -box.height() * margin)
    s = min(room.width() / max(1.0, picture_w), room.height() / max(1.0, picture_h))
    return QtCore.QRectF(room.center().x() - picture_w * s / 2, room.center().y() - picture_h * s / 2,
                         picture_w * s, picture_h * s)


def full_slide(picture: QtGui.QImage, size: QtCore.QSize, background: QtGui.QColor) -> QtGui.QImage:
    """The whole picture as one more slide of the carousel's shape, scaled to fit."""
    slide = QtGui.QImage(size, QtGui.QImage.Format_RGB32)
    slide.fill(background)
    painter = QtGui.QPainter(slide)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.drawImage(fit(picture.width(), picture.height(), QtCore.QRectF(0, 0, size.width(), size.height())),
                      picture)
    painter.end()
    return slide


def export_folder(controller, parent: str) -> str | None:
    """Write the carousel: 01.jpg, 02.jpg, ... (the fitted whole picture last,
    when asked for) and full.jpg (when asked for).  Returns the folder."""
    board = controller.carousel
    s = board.s
    k = int(s["width"]) / board.slide_w
    on = controller.distress.enabled if s["finish"] == "as set" else s["finish"] == "distressed"
    picture = render(board, k, replace(controller.distress, enabled=on), controller.ink(), controller.density())
    cut = slides(picture, board.slides)
    if s["full"] in ("last slide", "last slide + file"):
        cut.append(full_slide(picture, cut[0].size(), QtGui.QColor(s["background"])))
    name = re.sub(r"[^\w\- ]+", "_", f"{controller.stem()} carousel {s['shape'].replace(':', 'x')}")
    folder = os.path.join(parent, name)
    n = 2
    while os.path.exists(folder):
        folder = os.path.join(parent, f"{name} {n}")
        n += 1
    os.makedirs(folder)
    ext = s["format"]
    for n, slide in enumerate(cut, 1):
        slide.save(os.path.join(folder, f"{n:02d}.{ext}"), None, 95)
    if s["full"] in ("last slide + file", "file"):
        picture.save(os.path.join(folder, f"full.{ext}"), None, 95)
    return folder


# -- the preview: swiping through, as on Instagram ---------------------------------------

class CarouselPreview(QtWidgets.QWidget):
    """Full window: one slide at a time in a phone-wide column, swiped,
    scrolled or arrowed through and snapping to each slide - the picture
    running on between them as it will on Instagram.  Dots under it, the
    count in its corner.  Esc goes back."""

    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.at = 0.0                        # in slides: 1.5 is halfway from the second to the third
        self.picture: QtGui.QImage | None = None
        self.key = None
        self._drag: tuple | None = None
        self._wheel_idle = QtCore.QTimer(self, singleShot=True, interval=140)
        self._wheel_idle.timeout.connect(self.snap)
        self.anim = QtCore.QVariantAnimation(self)
        self.anim.setDuration(240)
        self.anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._moved)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.hide()

    def start(self, slide: int = 0):
        self.setGeometry(self.parentWidget().rect())
        self.at = float(max(0, min(slide, self.count() - 1)))
        self.key = None
        self.show()
        self.raise_()
        self.setFocus()

    def count(self) -> int:
        return self.c.carousel.slides

    def column(self) -> QtCore.QRectF:
        """Where the slide shows: as tall as the window allows, a phone wide."""
        board = self.c.carousel
        h = max(60.0, self.height() - 140.0)
        w = h * board.slide_w / board.slide_h
        if w > self.width() - 80:
            w = self.width() - 80.0
            h = w * board.slide_h / board.slide_w
        return QtCore.QRectF((self.width() - w) / 2, (self.height() - h) / 2 - 10, w, h)

    def ensure_picture(self, column: QtCore.QRectF) -> QtGui.QImage:
        c = self.c
        ratio = self.devicePixelRatioF()
        k = column.width() * ratio / c.carousel.slide_w
        key = (round(k, 3), c.things_key(), tuple(sorted(c.carousel.s.items())),
               tuple(c.distress.to_dict().items()), tuple(vars(c.fmt).items()))
        if key != self.key or self.picture is None:
            s = c.carousel.s
            on = c.distress.enabled if s["finish"] == "as set" else s["finish"] == "distressed"
            self.picture = render(c.carousel, k, replace(c.distress, enabled=on), c.ink(), c.density())
            self.key = key
        return self.picture

    # -- moving -------------------------------------------------------------------------
    def go(self, target: float):
        target = float(max(0, min(self.count() - 1, round(target))))
        self.anim.stop()
        self.anim.setStartValue(float(self.at))
        self.anim.setEndValue(target)
        self.anim.start()

    def _moved(self, value):
        self.at = float(value)
        self.update()

    def snap(self, lean: float = 0.0):
        """To the nearest slide - or, flicked, on to the next one that way."""
        self.go(self.at + lean if lean else self.at)

    # -- drawing ------------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        backdrop = QtGui.QColor("#101010")
        painter.fillRect(self.rect(), backdrop)
        column = self.column()
        picture = self.ensure_picture(column)
        n = self.count()
        step = picture.width() / max(1, n)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.save()
        painter.setClipRect(column)
        source = QtCore.QRectF(self.at * step, 0, step, picture.height())
        painter.drawImage(column, picture, source)
        painter.restore()
        # the count, top right, and the dots underneath - as Instagram has them
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setFont(style.ui_font(11))
        tag = f"{int(round(self.at)) + 1}/{n}"
        pill = QtCore.QRectF(column.right() - 54, column.top() + 12, 42, 22)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 150))
        painter.drawRoundedRect(pill, 11, 11)
        painter.setPen(QtGui.QColor("#ffffff"))
        painter.drawText(pill, QtCore.Qt.AlignCenter, tag)
        dots = min(n, 20)
        gap = 12.0
        left = column.center().x() - (dots - 1) * gap / 2
        for i in range(dots):
            near = abs(i - self.at) < 0.5
            painter.setBrush(QtGui.QColor("#3897f0") if near else QtGui.QColor("#7a7a7a"))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(left + i * gap, column.bottom() + 22), 3.2, 3.2)
        painter.setPen(QtGui.QColor("#8c8b86"))
        painter.drawText(QtCore.QRectF(self.rect()).adjusted(0, 0, 0, -14),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
                         "swipe, scroll or ← → through the slides   ·   Esc back")

    # -- input --------------------------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.c.leave_carousel_preview()
        elif key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Space, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageDown):
            self.go(round(self.at) + 1)
        elif key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Up, QtCore.Qt.Key_PageUp):
            self.go(round(self.at) - 1)
        elif key == QtCore.Qt.Key_Home:
            self.go(0)
        elif key == QtCore.Qt.Key_End:
            self.go(self.count() - 1)
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """Two fingers on a trackpad move the slides with them; letting go snaps."""
        self.anim.stop()
        pixel = event.pixelDelta()
        if not pixel.isNull():
            delta = pixel.x() or pixel.y()
        else:
            delta = (event.angleDelta().x() or event.angleDelta().y()) / 4
        width = max(1.0, self.column().width())
        self.at = max(-0.25, min(self.count() - 0.75, self.at - delta / width))
        self.update()
        self._wheel_idle.start()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.anim.stop()
            self._drag = (event.pos().x(), self.at, QtCore.QElapsedTimer())
            self._drag[2].start()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            x0, at0, _t = self._drag
            self.at = max(-0.25, min(self.count() - 0.75, at0 - (event.pos().x() - x0) / self.column().width()))
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        x0, at0, clock = self._drag
        self._drag = None
        moved = event.pos().x() - x0
        if abs(moved) < 4:                   # a click: the half it is on says which way
            self.go(round(self.at) + (1 if event.pos().x() > self.width() / 2 else -1))
            return
        speed = moved / max(1, clock.elapsed())
        lean = -1 if speed > 0.6 else (1 if speed < -0.6 else 0)
        self.go(round(at0) + lean if lean else self.at)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.key = None
