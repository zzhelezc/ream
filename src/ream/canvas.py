"""
The infinite canvas.

A QGraphicsView over a scene two million points across with its scroll bars
hidden: panning moves them, zooming scales about the pointer, so there is no
edge.  The view only draws (the flat background, and in the foreground pass,
in screen pixels, the page edge, selection, page count and messages) and
routes input: every press, drag, wheel and key goes to the controller first,
and whatever it declines goes on to the scene, where the page's text editor
lives.
"""
from __future__ import annotations

import time

from PyQt5 import QtCore, QtGui, QtWidgets

SCENE_HALF = 1_000_000.0
ZOOM_MIN, ZOOM_MAX = 0.05, 16.0
WHEEL_STEP = 1.0016            # per 1/8 degree of wheel: one notch is about 21%


class CanvasView(QtWidgets.QGraphicsView):
    def __init__(self, controller, scene: QtWidgets.QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.controller = controller
        self.bg = QtGui.QColor("#e8e7e3")
        self.space_down = False
        self._pan_from: QtCore.QPointF | None = None
        self._to_scene = False
        self._toast = ""
        self._toast_until = 0.0
        self._toast_timer = QtCore.QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.viewport().update)

        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                            | QtGui.QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setStyleSheet("QGraphicsView { border: none; }")
        scene.setSceneRect(-SCENE_HALF, -SCENE_HALF, 2 * SCENE_HALF, 2 * SCENE_HALF)
        self.centerOn(0.0, 0.0)

    # -- drawing -------------------------------------------------------------
    def set_background(self, colour: QtGui.QColor):
        self.bg = QtGui.QColor(colour)
        self.viewport().update()

    def drawBackground(self, painter, rect):
        painter.save()
        painter.resetTransform()
        painter.fillRect(QtCore.QRectF(self.viewport().rect()), self.bg)
        painter.restore()

    def drawForeground(self, painter, rect):
        painter.save()
        painter.resetTransform()
        self.controller.paint_overlay(painter)
        if self._toast and time.monotonic() < self._toast_until:
            self.controller.paint_toast(painter, self._toast)
        painter.restore()

    def toast(self, text: str, seconds: float = 2.6):
        self._toast = text
        self._toast_until = time.monotonic() + seconds
        self._toast_timer.start(int(seconds * 1000) + 30)
        self.viewport().update()
        self.viewport().repaint()

    # -- navigation ----------------------------------------------------------
    def zoom(self) -> float:
        return float(self.transform().m11())

    def zoom_by(self, factor: float, anchor: QtCore.QPointF | None = None):
        current = self.zoom()
        target = min(ZOOM_MAX, max(ZOOM_MIN, current * factor))
        factor = target / current
        if abs(factor - 1.0) < 1e-9:
            return
        if anchor is None:
            anchor = QtCore.QPointF(self.viewport().rect().center())
        before = self.mapToScene(anchor.toPoint())
        self.scale(factor, factor)
        after = self.viewportTransform().map(before)
        self.pan_pixels(anchor.x() - after.x(), anchor.y() - after.y())

    def set_zoom(self, zoom: float, anchor: QtCore.QPointF | None = None):
        self.zoom_by(zoom / self.zoom(), anchor)

    def pan_pixels(self, dx: float, dy: float):
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(int(round(h.value() - dx)))
        v.setValue(int(round(v.value() - dy)))
        self.viewport().update()
        self.controller.view_changed()

    def frame(self, rect: QtCore.QRectF, margin: int = 56, max_zoom: float = 3.0):
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return
        size = self.viewport().size()
        zoom = min((size.width() - 2 * margin) / rect.width(),
                   (size.height() - 2 * margin) / rect.height())
        zoom = min(max_zoom, max(ZOOM_MIN, zoom))
        self.setTransform(QtGui.QTransform.fromScale(zoom, zoom))
        self.centerOn(rect.center())
        self.viewport().update()
        self.controller.view_changed()

    def visible_scene_rect(self) -> QtCore.QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    # -- input ---------------------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent):
        # the same everywhere, page or not: scrolling pans, never turns pages
        mods = event.modifiers()
        pixel = event.pixelDelta()
        trackpad = not pixel.isNull() or event.phase() != QtCore.Qt.NoScrollPhase
        if mods & QtCore.Qt.AltModifier or (trackpad and not mods & QtCore.Qt.ControlModifier):
            if pixel.isNull():
                pixel = event.angleDelta() / 2
            self.pan_pixels(pixel.x(), pixel.y())
        else:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if not delta and not pixel.isNull():
                delta = pixel.y() * 2
            self.zoom_by(WHEEL_STEP ** delta, event.posF())
        event.accept()

    def viewportEvent(self, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.NativeGesture:
            kind = event.gestureType()
            if kind == QtCore.Qt.ZoomNativeGesture:
                self.zoom_by(1.0 + event.value(), event.localPos())
                return True
            if kind == QtCore.Qt.SmartZoomNativeGesture:
                self.controller.fit_page()
                return True
        return super().viewportEvent(event)

    def start_pan(self, pos: QtCore.QPointF):
        self._pan_from = QtCore.QPointF(pos)
        self.viewport().setCursor(QtCore.Qt.ClosedHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        self.setFocus(QtCore.Qt.MouseFocusReason)
        if event.button() == QtCore.Qt.MiddleButton or (
                event.button() == QtCore.Qt.LeftButton and self.space_down):
            self.start_pan(event.localPos())
            event.accept()
            return
        if self.controller.press(event):
            event.accept()
            return
        self._to_scene = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._pan_from is not None:
            delta = event.localPos() - self._pan_from
            self._pan_from = event.localPos()
            self.pan_pixels(delta.x(), delta.y())
            event.accept()
            return
        if self._to_scene:
            super().mouseMoveEvent(event)
            return
        if not self.controller.move(event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if self._pan_from is not None:
            self._pan_from = None
            self.controller.update_cursor()
            event.accept()
            return
        if self._to_scene:
            self._to_scene = False
            super().mouseReleaseEvent(event)
            return
        self.controller.release(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        if self.controller.double_click(event):
            return
        self._to_scene = True
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        self.controller.context_menu(event.globalPos(), QtCore.QPointF(event.pos()))

    def focusNextPrevChild(self, forward: bool) -> bool:
        return False                    # Tab is the palette, never focus travel

    def event(self, event: QtCore.QEvent) -> bool:
        # QGraphicsView hands Tab to the scene before anything else (where the
        # text editor would type it); here it opens the palette instead
        if (event.type() == QtCore.QEvent.KeyPress
                and event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab)):
            self.controller.open_palette()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if (event.key() == QtCore.Qt.Key_Space and not self.controller.typing()
                and not event.isAutoRepeat()):
            self.space_down = True
            self.controller.update_cursor()
            event.accept()
            return
        if self.controller.key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key_Space and not event.isAutoRepeat() and self.space_down:
            self.space_down = False
            self.controller.update_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space_down = False
        super().focusOutEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.controller.drop(event.mimeData(), self.mapToScene(event.pos()))
        event.acceptProposedAction()
