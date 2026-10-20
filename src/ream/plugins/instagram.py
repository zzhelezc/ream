"""
instagram: the book as Instagram posts - one slide a page, a spread across
slides, or the whole book as one long picture cut into a seamless carousel.

`⌥⌘G` (or **instagram** in the palette) opens the slides preview and the
panel.  All the pages laid out side by side make one long picture (the
**full picture**); the slides are cut from it edge to edge, so swiping
through the carousel runs on without a seam.

| as              | slides |
| --------------- | ------ |
| pages           | one slide per page, each page fitted to it |
| spreads         | each spread across `slides per spread` slides (a cover alone on fewer) |
| one long strip  | every page side by side, cut into as many slides as it takes |

Shape: 4:5 (1080 x 1350, the most room), 1:1, 3:4 (1080 x 1440) or 1.91:1
(1080 x 566).  **fit** keeps whole pages in the slides with the background
round them, **fill** fills the slides and crops; **zoom**, **margin** and
**nudge** fine-tune it; the background is the canvas colour, the paper,
white or black.  Instagram takes up to 20 slides in a carousel - more, and
the preview says so.

Instagram crops every image in a carousel to the first one's shape, so the
whole picture can't go in as it is: **full picture · last slide** adds it as
one more slide of the same shape, the whole picture scaled down to fit (the
background round it).  **file** also writes it uncut, as `full.jpg`, for
posting on its own.

**Moving pictures here only.**  Drag a picture in the preview to move it
in the slides - say, off a cut between two slides - without touching the
book: the move is the export's own.  A moved picture is taken off its page
and laid over the full picture where you put it (on top of the words), free
of page edges and cuts.  Double-click it to put it back; **put back all** in
the panel puts every one back.  Moves are remembered for the document.

**Dropping slides.**  Hover over a slide and click its **×** to drop it - one
emptied by moving pictures, say.  It stays in the preview, faded; click it
again to bring it back (or **bring back all** in the panel).  The export
leaves dropped slides out and numbers the rest without gaps; the full
picture is the kept slides joined.

**export…** writes a folder: `01.jpg`, `02.jpg`, … (post them in that order,
the fitted full picture last), and `full.jpg` when asked for.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import distress, export, style
from ..plugin import Plugin as Base

SHAPES = {"4:5": 1350, "1:1": 1080, "3:4": 1440, "1.91:1": 566}     # height at 1080 wide, as Instagram has it
WIDTHS = (1080, 1440, 2160)
MODES = ("pages", "spreads", "one long strip")
BACKGROUNDS = ("canvas", "paper", "white", "black")
MAX_SLIDES = 20                  # what Instagram takes in one carousel
DEFAULTS = {"shape": "4:5", "width": 1080, "mode": "spreads", "per_spread": 2, "fit": "fit",
            "zoom": 100.0, "margin": 4.0, "gap": 0.0, "nudge_x": 0.0, "nudge_y": 0.0,
            "background": "canvas", "finish": "as set", "full": "last slide", "format": "jpg"}
FULL = ("last slide", "last slide + file", "file", "no")    # where the whole picture goes


@dataclass
class Placed:
    page: int
    rect: QtCore.QRectF          # where it goes in the full picture, pixels


@dataclass
class Plan:
    slide_w: int
    slide_h: int
    slides: int
    placed: list[Placed]
    clips: list[QtCore.QRectF]   # per page: the slides it may show in (fill crops to these)

    @property
    def width(self) -> int:
        return self.slides * self.slide_w


def slide_size(shape: str, width: int) -> tuple[int, int]:
    return int(width), int(round(width * SHAPES.get(shape, SHAPES["4:5"]) / 1080))


def plan(pages: list[int], spreads: list[tuple], page_w: float, page_h: float, s: dict) -> Plan:
    """Where every page goes: units of pages side by side (a page, a
    spread, or all of them), each given whole slides, laid one after another."""
    sw, sh = slide_size(s["shape"], s["width"])
    chosen = set(pages)
    if s["mode"] == "pages":
        units = [[p] for p in pages]
    elif s["mode"] == "spreads":
        units = [[p for p in pair if p is not None and p in chosen] for pair in spreads]
        units = [u for u in units if u]
    else:
        units = [list(pages)] if pages else []
    margin = s["margin"] / 100.0
    zoom = s["zoom"] / 100.0
    placed, clips, x0 = [], [], 0
    for unit in units:
        n = len(unit)
        gap_pt = page_w * s["gap"] / 100.0 if s["mode"] == "one long strip" else 0.0
        unit_w_pt = n * page_w + (n - 1) * gap_pt
        box_h = sh * (1 - 2 * margin)
        if s["mode"] == "pages":
            k = 1
        elif s["mode"] == "spreads":
            k = max(1, round(int(s["per_spread"]) * n / 2))
        else:
            k = None
        if k is None:
            # the long strip: as tall as the slide allows, as many slides as that takes
            scale = (box_h / page_h) * zoom if s["fit"] == "fit" else (sh / page_h) * zoom
            k = max(1, math.ceil((unit_w_pt * scale + 2 * margin * sw) / sw - 1e-6))
        else:
            box_w = k * sw * (1 - 2 * margin / k)
            fit = min(box_w / unit_w_pt, box_h / page_h)
            cover = max(k * sw / unit_w_pt, sh / page_h)
            scale = (fit if s["fit"] == "fit" else cover) * zoom
        span = QtCore.QRectF(x0, 0, k * sw, sh)
        w_px, h_px = unit_w_pt * scale, page_h * scale
        left = span.center().x() - w_px / 2 + s["nudge_x"] / 100.0 * sw
        top = span.center().y() - h_px / 2 + s["nudge_y"] / 100.0 * sh
        for i, page in enumerate(unit):
            px = left + i * (page_w + gap_pt) * scale
            placed.append(Placed(page, QtCore.QRectF(px, top, page_w * scale, h_px)))
            clips.append(span)
        x0 += k * sw
    return Plan(sw, sh, max(0, x0 // sw), placed, clips)


class InstaView(QtWidgets.QWidget):
    """Full window: the slides in a row (wrapping), cut lines and numbers."""

    def __init__(self, plugin):
        super().__init__(plugin.host.window)
        self.plugin = plugin
        self.picture: QtGui.QImage | None = None
        self.key = None
        self.cells: list[tuple[QtCore.QRectF, int]] = []   # where each slide is drawn
        self.k = 1.0                                       # preview px per full-size px
        self.dragging: tuple | None = None                 # (thing, start point, start offset)
        self.hover: int | None = None                      # the slide under the pointer
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.redo = QtCore.QTimer(self, singleShot=True, interval=120)
        self.redo.timeout.connect(self.update)
        self.hide()

    def open(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        if self.plugin.panel.isVisible():
            self.plugin.panel.raise_()
        self.setFocus()

    def room(self) -> QtCore.QRectF:
        room = QtCore.QRectF(self.rect()).adjusted(40, 50, -40, -60)
        panel = self.plugin.panel
        if panel.isVisible():
            box = QtCore.QRectF(panel.geometry())
            if box.center().x() > room.center().x():
                room.setRight(min(room.right(), box.left() - 24))
            else:
                room.setLeft(max(room.left(), box.right() + 24))
        return room

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        c = self.plugin.host.window
        backdrop = QtGui.QColor(c.canvas_colour())
        painter.fillRect(self.rect(), backdrop.darker(112) if backdrop.lightness() > 128 else backdrop.lighter(130))
        meta = QtGui.QColor("#b8b6b0" if backdrop.lightness() < 128 else "#77766f")
        p = self.plugin.plan()
        painter.setFont(style.ui_font(11))
        painter.setPen(meta)
        if not p.slides:
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "no pages to post")
            return
        room = self.room()
        dropped = self.plugin.dropped(p)
        cells = p.slides + (1 if self.plugin.full_last() and len(dropped) < p.slides else 0)
        # rows of slides, as many across as keeps them a good size
        best = None
        for across in range(1, cells + 1):
            rows = math.ceil(cells / across)
            k = min(room.width() / (across * p.slide_w), (room.height() - (rows - 1) * 26) / (rows * p.slide_h))
            if best is None or k > best[0]:
                best = (k, across)
        k, across = best
        sw, sh = p.slide_w * k, p.slide_h * k
        picture = self.plugin.picture(scale=max(0.05, min(1.0, k * self.devicePixelRatioF())))
        rows = math.ceil(cells / across)
        top0 = room.top() + (room.height() - (rows * sh + (rows - 1) * 26)) / 2
        left0 = room.left() + (room.width() - min(across, cells) * sw) / 2
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        ratio = picture.width() / max(1, p.width)
        self.cells, self.k = [], k
        number = 0
        for n in range(p.slides):
            r, col = divmod(n, across)
            target = QtCore.QRectF(left0 + col * sw, top0 + r * (sh + 26), sw, sh)
            self.cells.append((target, n))
            source = QtCore.QRectF(n * p.slide_w * ratio, 0, p.slide_w * ratio, picture.height())
            painter.drawImage(target, picture, source)
            if n in dropped:
                painter.fillRect(target, QtGui.QColor(255, 255, 255, 190))      # dropped: faded
            painter.setPen(QtGui.QPen(meta, 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(target)
            if n in dropped:
                label = "dropped · click × to bring back"
            else:
                number += 1
                label = f"{number:02d}"
            painter.drawText(QtCore.QRectF(target.left(), target.bottom() + 3, sw, 18),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, label)
            if n == self.hover or n in dropped:
                box = self.close_box(target)
                painter.fillRect(box, QtGui.QColor(style.INK) if n == self.hover else QtGui.QColor("#ffffff"))
                painter.setPen(QtGui.QColor("#ffffff") if n == self.hover else QtGui.QColor(style.INK))
                painter.drawText(box, QtCore.Qt.AlignCenter, "↺" if n in dropped else "×")
        if cells > p.slides:
            # the whole picture, fitted into one more slide of the same shape
            r, col = divmod(p.slides, across)
            target = QtCore.QRectF(left0 + col * sw, top0 + r * (sh + 26), sw, sh)
            painter.fillRect(target, self.plugin.background())
            whole = self.plugin.full_picture(picture, p)
            painter.drawImage(self.plugin.fit_rect(whole.width(), whole.height(), target), whole)
            painter.setPen(QtGui.QPen(meta, 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(target)
            painter.drawText(QtCore.QRectF(target.left(), target.bottom() + 3, sw, 18),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                             f"{self.plugin.posted(p):02d} · the whole picture")
        s = self.plugin.s
        posted = self.plugin.posted(p)
        kept = p.slides - len(dropped)
        words = [f"{posted} slide{'s' if posted != 1 else ''}" + (f" ({len(dropped)} dropped)" if dropped else ""),
                 f"{s['shape']} · {p.slide_w}×{p.slide_h}", s["mode"],
                 f"full picture {kept * p.slide_w}×{p.slide_h}"]
        if posted > MAX_SLIDES:
            words.append(f"Instagram takes {MAX_SLIDES} a post: this makes {math.ceil(posted / MAX_SLIDES)} posts")
        painter.setPen(meta)
        painter.drawText(QtCore.QRectF(self.rect()).adjusted(0, 16, 0, 0), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                         "   ·   ".join(words))
        painter.drawText(QtCore.QRectF(self.rect()).adjusted(0, 0, 0, -16),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
                         "the slides join edge to edge   ·   drag a picture to move it here only, "
                         "double-click puts it back   ·   Esc back")
        if self.dragging is not None:
            for target, n in self.cells:                 # the picture being moved, outlined
                rect = self.plugin.thing_rect(self.dragging[0], p)
                if rect is None:
                    break
                box = QtCore.QRectF(target.left() + (rect.left() - n * p.slide_w) * k,
                                    target.top() + rect.top() * k, rect.width() * k, rect.height() * k)
                painter.save()
                painter.setClipRect(target)
                pen = QtGui.QPen(QtGui.QColor(style.INK), 1, QtCore.Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(box)
                painter.restore()

    # -- dropping slides ----------------------------------------------------------------
    @staticmethod
    def close_box(target: QtCore.QRectF) -> QtCore.QRectF:
        size = max(14.0, min(22.0, target.width() * 0.09))
        return QtCore.QRectF(target.right() - size - 4, target.top() + 4, size, size)

    def slide_at(self, pos: QtCore.QPointF) -> int | None:
        for target, n in self.cells:
            if target.contains(pos):
                return n
        return None

    # -- moving pictures, here only ---------------------------------------------------
    def full_point(self, pos: QtCore.QPointF, fallback: int | None = None):
        """A point in the preview as a point on the full picture (full-size px)."""
        p = self.plugin.plan()
        for target, n in self.cells:
            if target.contains(pos) or n == fallback:
                return QtCore.QPointF(n * p.slide_w + (pos.x() - target.left()) / self.k,
                                      (pos.y() - target.top()) / self.k), n
        return None, None

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton:
            return
        pos = QtCore.QPointF(event.pos())
        for target, n in self.cells:
            if self.close_box(target).contains(pos):
                self.plugin.toggle_slide(n)                  # drop it, or bring it back
                self.update()
                return
        point, n = self.full_point(pos)
        thing = self.plugin.thing_at(point) if point is not None else None
        if thing is not None:
            self.dragging = (thing, point, tuple(self.plugin.offset(thing)), n)
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            self.update()

    def mouseMoveEvent(self, event):
        pos = QtCore.QPointF(event.pos())
        hover = self.slide_at(pos)
        if hover != self.hover:
            self.hover = hover
            self.update()
        if self.dragging is None:
            point, _n = self.full_point(pos)
            over = point is not None and self.plugin.thing_at(point) is not None
            self.setCursor(QtCore.Qt.OpenHandCursor if over else QtCore.Qt.ArrowCursor)
            return
        thing, start, offset, n = self.dragging
        point, _n = self.full_point(pos, fallback=n)
        if point is None:
            return
        k = self.plugin.thing_scale(thing)
        self.plugin.set_offset(thing, offset[0] + (point.x() - start.x()) / k,
                               offset[1] + (point.y() - start.y()) / k)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging is not None:
            self.dragging = None
            self.setCursor(QtCore.Qt.OpenHandCursor)
            self.plugin.save()
            self.plugin.panel.refresh()
            self.update()

    def mouseDoubleClickEvent(self, event):
        point, _n = self.full_point(QtCore.QPointF(event.pos()))
        thing = self.plugin.thing_at(point) if point is not None else None
        if thing is not None:
            self.plugin.put_back(thing)
            self.update()

    def leaveEvent(self, event):
        self.hover = None
        self.update()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.plugin.close()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()


class Plugin(Base):
    name = "instagram"
    title = "instagram"

    def setup(self, host):
        self.host = host
        self.s = {**DEFAULTS, **host.settings}
        if self.s["full"] not in FULL:              # older settings: on / off
            self.s["full"] = "last slide" if self.s["full"] else "no"
        self.pages_text = ""                       # "" = every page
        self._pictures: dict[tuple, QtGui.QImage] = {}
        self._layers: dict[tuple, QtGui.QImage] = {}      # moved pictures, rendered
        self.view = InstaView(self)
        self.panel = self.build_panel()
        host.command("instagram", self.toggle, "⌥⌘G", "carousel post slides square social export",
                     shortcut="Ctrl+Alt+G")
        host.command("instagram: export…", self.export, "", "carousel slides jpg folder")

    def teardown(self):
        self.save()

    def save(self):
        self.host.settings.clear()
        self.host.settings.update(self.s)
        self.host.save_settings()

    # -- opening ------------------------------------------------------------------
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
        self.view.hide()
        self.panel.hide()
        self.save()
        self.host.window.focus_text()

    def changed(self):
        self.view.update()
        self.panel.refresh()

    def build_panel(self):
        panel = self.host.panel("instagram", on_close=self.close)
        s = self.s

        def put(key, number=False):
            def setter(value):
                s[key] = int(value) if number else value
                self.changed()
            return setter

        panel.choice("shape", lambda: list(SHAPES), lambda: s["shape"], put("shape"))
        panel.choice("width", lambda: [str(w) for w in WIDTHS], lambda: str(s["width"]),
                     lambda v: put("width", True)(int(v)))
        panel.choice("as", lambda: list(MODES), lambda: s["mode"], put("mode"))
        panel.slider("per spread", 1, 4, lambda: s["per_spread"], put("per_spread", True),
                     unit=" slides", default=2)
        panel.text("pages", lambda: self.pages_text or "all", self.set_pages)
        panel.section("fit")
        panel.toggle("pictures", lambda: s["fit"] == "fit", lambda v: put("fit")("fit" if v else "fill"),
                     on="fit", off="fill")
        panel.slider("zoom", 50, 200, lambda: s["zoom"], put("zoom"), unit="%", default=100)
        panel.slider("margin", 0, 20, lambda: s["margin"], put("margin"), step=0.5, unit="%", default=4)
        panel.slider("gap", 0, 30, lambda: s["gap"], put("gap"), unit="%", default=0)
        panel.slider("nudge ←→", -50, 50, lambda: s["nudge_x"], put("nudge_x"), unit="%", default=0)
        panel.slider("nudge ↑↓", -50, 50, lambda: s["nudge_y"], put("nudge_y"), unit="%", default=0)
        panel.choice("background", lambda: list(BACKGROUNDS), lambda: s["background"], put("background"))
        panel.links("moved", [(lambda: f"put back all ({len(self.moves())})" if self.moves()
                               else "none", self.put_back_all)])
        panel.links("dropped", [(lambda: f"bring back all ({len(self.dropped())})" if self.dropped()
                                 else "none", self.bring_back_all)])
        panel.section("export")
        panel.choice("finish", lambda: ["as set", "distressed", "clean"], lambda: s["finish"],
                     put("finish"))
        panel.choice("full picture", lambda: list(FULL), lambda: s["full"], put("full"))
        panel.toggle("format", lambda: s["format"] == "jpg", lambda v: put("format")("jpg" if v else "png"),
                     on="jpg", off="png")
        panel.buttons([("export…", self.export), ("close", panel.close_panel)])
        return panel

    def set_pages(self, text: str):
        self.pages_text = "" if text.strip().lower() in ("", "all") else text
        self.view.update()

    # -- laying out -----------------------------------------------------------------
    def pages(self) -> list[int]:
        window = self.host.window
        count = window.sheet.pages()
        if not self.pages_text:
            return list(range(count))
        return sorted(window.parse_page_range(self.pages_text, count))

    def plan(self) -> Plan:
        window = self.host.window
        return plan(self.pages(), window.spreads(window.sheet.pages()), window.sheet.W,
                    window.sheet.H, self.s)

    def background(self) -> QtGui.QColor:
        window = self.host.window
        name = self.s["background"]
        if name == "canvas":
            return QtGui.QColor(window.canvas_colour())
        if name == "paper":
            return QtGui.QColor(window.paper())
        return QtGui.QColor("#ffffff" if name == "white" else "#000000")

    def settings(self):
        window = self.host.window
        finish = self.s["finish"]
        on = window.distress.enabled if finish == "as set" else finish == "distressed"
        return replace(window.distress, enabled=on)

    # -- pictures moved in the export only --------------------------------------------
    def moves(self) -> dict:
        """This document's moves: {uid: [dx, dy]} in page points."""
        window = self.host.window
        store = self.s.setdefault("moves", {})
        mine = store.setdefault(window.path or "draft", {})
        alive = {str(t.uid) for t in window.sheet.pinned() if t.alive}
        for gone in [uid for uid in mine if uid not in alive]:
            del mine[gone]
        return mine

    def offset(self, thing) -> list:
        return self.moves().get(str(thing.uid), [0.0, 0.0])

    def set_offset(self, thing, dx: float, dy: float):
        self.moves()[str(thing.uid)] = [round(dx, 2), round(dy, 2)]

    def put_back(self, thing):
        self.moves().pop(str(thing.uid), None)
        self.save()
        self.changed()

    def put_back_all(self):
        self.moves().clear()
        self.save()
        self.changed()

    # -- dropped slides ----------------------------------------------------------------
    def dropped(self, p: Plan | None = None) -> set[int]:
        """The slides left out of the carousel (this document's), by number from 0."""
        p = p or self.plan()
        store = self.s.setdefault("dropped", {})
        mine = store.setdefault(self.host.window.path or "draft", [])
        return {n for n in mine if 0 <= n < p.slides}

    def toggle_slide(self, n: int):
        store = self.s.setdefault("dropped", {})
        mine = store.setdefault(self.host.window.path or "draft", [])
        if n in mine:
            mine.remove(n)
        else:
            mine.append(n)
        self.save()
        self.changed()

    def bring_back_all(self):
        self.s.setdefault("dropped", {})[self.host.window.path or "draft"] = []
        self.save()
        self.changed()

    def kept(self, p: Plan | None = None) -> list[int]:
        p = p or self.plan()
        dropped = self.dropped(p)
        return [n for n in range(p.slides) if n not in dropped]

    def full_picture(self, picture: QtGui.QImage | None = None, p: Plan | None = None) -> QtGui.QImage:
        """The whole picture as posted: the kept slides joined (all of it
        when none is dropped)."""
        p = p or self.plan()
        picture = picture or self.picture()
        kept = self.kept(p)
        if len(kept) == p.slides:
            return picture
        step = picture.width() / max(1, p.slides)
        joined = QtGui.QImage(max(1, int(round(step * len(kept)))), picture.height(), QtGui.QImage.Format_RGB32)
        joined.fill(self.background())
        painter = QtGui.QPainter(joined)
        for i, n in enumerate(kept):
            painter.drawImage(QtCore.QRectF(i * step, 0, step, picture.height()), picture,
                              QtCore.QRectF(n * step, 0, step, picture.height()))
        painter.end()
        return joined

    def placed_at(self, p: Plan) -> dict[int, QtCore.QRectF]:
        return {pl.page: pl.rect for pl in p.placed}

    def thing_scale(self, thing, p: Plan | None = None) -> float:
        """Full-size px per page point where the thing's page is placed."""
        p = p or self.plan()
        rect = self.placed_at(p).get(self.host.window.sheet.page_of(thing))
        return rect.width() / self.host.window.sheet.W if rect is not None else 1.0

    def thing_rect(self, thing, p: Plan | None = None) -> QtCore.QRectF | None:
        """Where a picture is on the full picture (full-size px), moves included."""
        p = p or self.plan()
        sheet = self.host.window.sheet
        page = sheet.page_of(thing)
        rect = self.placed_at(p).get(page)
        if rect is None:
            return None
        k = rect.width() / sheet.W
        box = thing.parent_rect().translated(0.0, -page * sheet.H)
        dx, dy = self.offset(thing)
        return QtCore.QRectF(rect.left() + (box.left() + dx) * k, rect.top() + (box.top() + dy) * k,
                             box.width() * k, box.height() * k)

    def pictures(self, p: Plan | None = None) -> list:
        """The images on the pages that are posted, bottom to top."""
        p = p or self.plan()
        posted = set(self.placed_at(p))
        sheet = self.host.window.sheet
        return [t for t in sorted(sheet.pinned(), key=lambda t: t.zValue())
                if t.alive and t.kind == "image" and sheet.page_of(t) in posted]

    def thing_at(self, point: QtCore.QPointF):
        p = self.plan()
        for thing in reversed(self.pictures(p)):
            rect = self.thing_rect(thing, p)
            if rect is not None and rect.contains(point):
                return thing
        return None

    def moved(self, p: Plan) -> list:
        moves = self.moves()
        return [t for t in self.pictures(p) if str(t.uid) in moves]

    def moved_layer(self, thing, kk: float, settings) -> QtGui.QImage:
        """A moved picture on its own, kk px a point, distressed as an image is."""
        box = thing.parent_rect()
        w, h = max(1, int(math.ceil(box.width() * kk))), max(1, int(math.ceil(box.height() * kk)))
        image = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.Antialiasing)
        painter.scale(kk, kk)
        painter.translate(-box.left(), -box.top())
        placed, _ok = thing.itemTransform(thing.parentItem())
        painter.setTransform(placed, True)
        thing.render(painter, self.host.window.ink())
        painter.end()
        if settings.enabled and settings.images:
            rgba = distress.apply(export.to_numpy(image), settings, kk * 72.0)
            data = rgba.copy()
            image = QtGui.QImage(data.data, w, h, 4 * w, QtGui.QImage.Format_RGBA8888).copy()
        return image

    def page_images(self, p: Plan, scale: float) -> dict[int, QtGui.QImage]:
        """Every placed page, rendered as big as it is placed (x scale) -
        without the pictures moved in the export, which go on top."""
        window = self.host.window
        sheet = window.sheet
        if not p.placed:
            return {}
        px_h = max(8.0, p.placed[0].rect.height() * scale)
        dpi = max(12.0, px_h / (sheet.H / 72.0))
        settings = self.settings()
        pages = sorted({pl.page for pl in p.placed})
        args = (dpi, settings, window.paper(), window.ink(), window.density(), window.paper_stock())
        sheet.hidden = {t.uid for t in self.moved(p)}
        try:
            if settings.enabled and len(pages) > 1:
                return dict(export.distressed_pages(sheet, pages, *args))
            return {page: export.final_page(sheet, page, *args) for page in pages}
        finally:
            sheet.hidden = set()

    def picture(self, scale: float = 1.0) -> QtGui.QImage:
        """The full picture - every page in place - at `scale` of full size."""
        window = self.host.window
        p = self.plan()
        moved = self.moved(p)
        settings = self.settings()
        base_key = (round(scale, 3), tuple(sorted((k, v) for k, v in self.s.items() if k not in ("moves", "dropped", "folder"))),
                    self.pages_text, window.doc.revision(), window.things_key(),
                    tuple(vars(window.fmt).items()), tuple(window.distress.to_dict().items()),
                    window.canvas_colour(), tuple(sorted(t.uid for t in moved)))
        base = self._pictures.get(base_key)
        if base is None:
            base = self._base_picture(p, scale)
            if len(self._pictures) > 6:
                self._pictures.clear()
            self._pictures[base_key] = base
        if not moved:
            return base
        # the moved pictures over it, where they were put
        image = base.copy()
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.Antialiasing)
        painter.scale(scale, scale)
        for thing in moved:
            rect = self.thing_rect(thing, p)
            kk = self.thing_scale(thing, p) * scale
            key = (thing.uid, round(kk, 4), thing.key(), tuple(settings.to_dict().items()))
            layer = self._layers.get(key)
            if layer is None:
                layer = self.moved_layer(thing, kk, settings)
                if len(self._layers) > 48:
                    self._layers.clear()
                self._layers[key] = layer
            painter.drawImage(rect, layer)
        painter.end()
        return image

    def _base_picture(self, p: Plan, scale: float) -> QtGui.QImage:
        width, height = max(1, int(round(p.width * scale))), max(1, int(round(p.slide_h * scale)))
        image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
        image.fill(self.background())
        pages = self.page_images(p, scale)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.Antialiasing)
        painter.scale(scale, scale)
        for placed, clip in zip(p.placed, p.clips):
            painter.save()
            painter.setClipRect(clip)                 # fill crops to its own slides
            painter.drawImage(placed.rect, pages[placed.page])
            painter.restore()
        painter.end()
        return image

    def slides(self, picture: QtGui.QImage | None = None) -> list[QtGui.QImage]:
        """The carousel: the full picture cut edge to edge into slides."""
        p = self.plan()
        picture = picture or self.picture()
        return [picture.copy(n * p.slide_w, 0, p.slide_w, p.slide_h) for n in range(p.slides)]

    def full_last(self) -> bool:
        return self.s["full"] in ("last slide", "last slide + file")

    def posted(self, p: Plan | None = None) -> int:
        """How many slides the carousel has: the kept ones, and the fitted full picture."""
        p = p or self.plan()
        kept = len(self.kept(p))
        return kept + (1 if self.full_last() and kept else 0)

    def fit_rect(self, picture_w: float, picture_h: float, box: QtCore.QRectF) -> QtCore.QRectF:
        """Where the whole picture goes in a slide-shaped `box`: as big as fits."""
        margin = max(0.03, self.s["margin"] / 100.0)
        room = box.adjusted(box.width() * margin, box.height() * margin,
                            -box.width() * margin, -box.height() * margin)
        k = min(room.width() / max(1.0, picture_w), room.height() / max(1.0, picture_h))
        w, h = picture_w * k, picture_h * k
        return QtCore.QRectF(room.center().x() - w / 2, room.center().y() - h / 2, w, h)

    def full_slide(self, picture: QtGui.QImage | None = None) -> QtGui.QImage:
        """The whole picture as one more slide of the carousel's shape (which
        Instagram forces on every image), scaled down to fit."""
        p = self.plan()
        picture = self.full_picture(picture or self.picture(), p)
        slide = QtGui.QImage(p.slide_w, p.slide_h, QtGui.QImage.Format_RGB32)
        slide.fill(self.background())
        painter = QtGui.QPainter(slide)
        painter.setRenderHints(QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.Antialiasing)
        painter.drawImage(self.fit_rect(picture.width(), picture.height(),
                                        QtCore.QRectF(0, 0, p.slide_w, p.slide_h)), picture)
        painter.end()
        return slide

    def carousel(self, picture: QtGui.QImage | None = None) -> list[QtGui.QImage]:
        """Every image to post, in order: the kept slides, then the fitted whole."""
        picture = picture or self.picture()
        dropped = self.dropped()
        out = [slide for n, slide in enumerate(self.slides(picture)) if n not in dropped]
        if self.full_last() and out:
            out.append(self.full_slide(picture))
        return out

    # -- exporting --------------------------------------------------------------------
    def export(self, parent: str | None = None) -> str | None:
        if parent is None:
            start = self.s.get("folder") or os.path.expanduser("~/Desktop")
            parent = QtWidgets.QFileDialog.getExistingDirectory(self.host.window,
                                                                "Export the Instagram slides into", start)
            if not parent:
                return None
            self.s["folder"] = parent
        p = self.plan()
        if not self.kept(p):
            self.host.toast("instagram · no slides to post")
            return None
        name = re.sub(r"[^\w\- ]+", "_", f"{self.host.window.stem()} instagram {self.s['shape'].replace(':', 'x')}")
        folder = os.path.join(parent, name)
        n = 2
        while os.path.exists(folder):
            folder = os.path.join(parent, f"{name} {n}")
            n += 1
        os.makedirs(folder)
        ext = self.s["format"]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            picture = self.picture()
            for n, slide in enumerate(self.carousel(picture), 1):
                slide.save(os.path.join(folder, f"{n:02d}.{ext}"), None, 95)
            if self.s["full"] in ("last slide + file", "file"):
                self.full_picture(picture, p).save(os.path.join(folder, f"full.{ext}"), None, 95)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        count = self.posted(p)
        posts = math.ceil(count / MAX_SLIDES)
        self.host.toast(f"instagram · {count} slides{f' ({posts} posts)' if posts > 1 else ''} → {folder}")
        return folder
