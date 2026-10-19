"""
stik: cutting stickers out of the images on the canvas (and on the page).

The image side of stik, brought into ream as tools.  `⌥⌘K` (or **stik** in
the palette) opens the panel; its first row picks a tool, and while a tool is
on, presses on the canvas go to it - Esc goes back to writing.  In a tool,
the letter keys switch tools as they do in stik.

| key | tool    | does |
| --- | ------- | ---- |
| L   | lasso   | draw round something; letting go cuts it out |
| M   | rect    | drag a box; letting go cuts |
| O   | ellipse | drag an ellipse; letting go cuts |
| W   | wand    | click a colour to take it out; Shift+click brings it back |
| E   | eraser  | rub pixels out; Shift+drag paints them back; [ ] size |

Cutting is physical, as in stik: the cutout lands exactly over its hole
(nudged down and right so you see it), and the hole stays in the image.
Alt while letting go - or **copy** in the panel - copies instead.  A cut
takes the selected image under the shape if there is one, else the topmost
image with something there.

**Background** removes the background from the selected images with stik's
methods (border flood, gradient flood, colour key, drop white / black,
GrabCut, and rembg's AI model when it is installed).  The fast ones follow
the sliders live; GrabCut and AI run on **apply**.  Nothing is lost: it all
goes into the image's matte, and **reset mask** brings it back as cut.

Also: **auto-cut islands** (every separate sticker on a sheet becomes its own
cutout, then they are arranged), **border** (a die-cut sticker edge in any
colour) and **export** (the selected images as PNGs, named by a pattern).
"""
from __future__ import annotations

import math
import os
import re
import time

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from .. import matting, style
from ..plugin import Plugin as Base, Tool

PROXY = 900                     # px: live background previews work on a copy this size
DEFAULTS = {"feather": 0.0, "smooth": 2.0, "copy": False, "lift": True,
            "tolerance_wand": 18.0, "contiguous": True, "eraser": 16.0, "hardness": 70.0,
            "method": matting.FLOOD, "tolerance": 18.0, "softness": 8.0, "grow": 0.0,
            "bg_feather": 0.0, "despeckle": 0.0, "keep_largest": False, "fill_holes": False,
            "min_island": 400.0, "border": 6.0, "border_smooth": 2.0, "border_colour": "#ffffff",
            "pattern": "{name}", "scale": 100.0, "padding": 0.0, "trim": True}
MARK = QtGui.QColor("#2f4bd8")


def _dashed(painter: QtGui.QPainter):
    pen = QtGui.QPen(QtGui.QColor(style.INK), 1.0, QtCore.Qt.CustomDashLine)
    pen.setDashPattern([4.0, 3.0])
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)


class CutTool(Tool):
    cursor = QtCore.Qt.CrossCursor

    def __init__(self, plugin, shape: str):
        self.plugin, self.shape = plugin, shape
        self.name = {"lasso": "lasso", "rect": "rectangle cut", "ellipse": "ellipse cut"}[shape]
        self.points: list[QtCore.QPointF] = []

    def press(self, at, mods) -> bool:
        self.points = [QtCore.QPointF(at), QtCore.QPointF(at)]
        return True

    def move(self, at, mods):
        if self.shape == "lasso":
            zoom = self.plugin.host.view.zoom()
            if (at - self.points[-1]).manhattanLength() * zoom >= 2:
                self.points.append(QtCore.QPointF(at))
        else:
            end = QtCore.QPointF(at)
            if mods & QtCore.Qt.ShiftModifier:           # square / circle
                d = self.points[0]
                side = max(abs(end.x() - d.x()), abs(end.y() - d.y()))
                end = QtCore.QPointF(d.x() + math.copysign(side, end.x() - d.x()),
                                     d.y() + math.copysign(side, end.y() - d.y()))
            self.points[1] = end

    def polygon(self) -> QtGui.QPolygonF:
        if self.shape == "lasso":
            pts = [(p.x(), p.y()) for p in self.points]
            sigma = self.plugin.s["smooth"]
            if sigma > 0 and len(pts) >= 3:
                pts = matting.smooth_path(pts, sigma)
            return QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])
        rect = QtCore.QRectF(self.points[0], self.points[1]).normalized()
        if self.shape == "rect":
            return QtGui.QPolygonF(rect)
        c, rx, ry = rect.center(), rect.width() / 2, rect.height() / 2
        return QtGui.QPolygonF([QtCore.QPointF(c.x() + rx * math.cos(t), c.y() + ry * math.sin(t))
                                for t in np.linspace(0, 2 * math.pi, 96, endpoint=False)])

    def release(self, at, mods):
        polygon = self.polygon()
        self.points = []
        if polygon.boundingRect().width() < 1 or polygon.boundingRect().height() < 1:
            return
        copy = self.plugin.s["copy"] != bool(mods & QtCore.Qt.AltModifier)
        self.plugin.cut(polygon, copy)

    def paint(self, painter, transform):
        if len(self.points) < 2:
            return
        _dashed(painter)
        painter.drawPolygon(transform.map(self.polygon()))

    def key(self, event) -> bool:
        return self.plugin.tool_key(event)


class WandTool(Tool):
    name = "wand"
    cursor = QtCore.Qt.PointingHandCursor

    def __init__(self, plugin):
        self.plugin = plugin

    def press(self, at, mods) -> bool:
        self.plugin.wand(at, restore=bool(mods & QtCore.Qt.ShiftModifier))
        return True

    def key(self, event) -> bool:
        return self.plugin.tool_key(event)


class EraserTool(Tool):
    name = "eraser"
    cursor = QtCore.Qt.BlankCursor

    def __init__(self, plugin):
        self.plugin = plugin
        self.at: QtCore.QPointF | None = None
        self.stroke = None

    def press(self, at, mods) -> bool:
        self.stroke = self.plugin.erase_begin(at, restore=bool(mods & QtCore.Qt.ShiftModifier))
        if self.stroke is not None:
            self.plugin.erase_to(self.stroke, at)
        return True

    def move(self, at, mods):
        self.at = QtCore.QPointF(at)
        if self.stroke is not None:
            self.plugin.erase_to(self.stroke, at)

    def release(self, at, mods):
        if self.stroke is not None:
            self.plugin.erase_end(self.stroke)
        self.stroke = None

    def hover(self, at):
        self.at = QtCore.QPointF(at)

    def paint(self, painter, transform):
        if self.at is None:
            return
        r = self.plugin.s["eraser"] / 2 * transform.m11()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor(style.INK), 1.0))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(transform.map(self.at), r, r)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.0))
        painter.drawEllipse(transform.map(self.at), r + 1, r + 1)

    def key(self, event) -> bool:
        if event.key() in (QtCore.Qt.Key_BracketLeft, QtCore.Qt.Key_BracketRight):
            k = 1.25 if event.key() == QtCore.Qt.Key_BracketRight else 0.8
            self.plugin.s["eraser"] = max(1.0, min(200.0, self.plugin.s["eraser"] * k))
            self.plugin.panel.refresh()
            return True
        return self.plugin.tool_key(event)


class Plugin(Base):
    name = "stik"
    title = "stik"

    def setup(self, host):
        self.host = host
        self.s = {**DEFAULTS, **host.settings}
        self.tools = {"lasso": CutTool(self, "lasso"), "rect": CutTool(self, "rect"),
                      "ellipse": CutTool(self, "ellipse"), "wand": WandTool(self),
                      "eraser": EraserTool(self)}
        self._bg_before = None
        self._bg_timer = QtCore.QTimer(host.window, singleShot=True, interval=380)
        self._bg_timer.timeout.connect(lambda: self.remove_background(full=True))
        self.panel = self.build_panel()
        host.command("stik", self.toggle_panel, "⌥⌘K", "cut sticker tools panel",
                     shortcut="Ctrl+Alt+K")
        for key, label in (("lasso", "cut: lasso"), ("rect", "cut: rectangle"),
                           ("ellipse", "cut: ellipse"), ("wand", "wand"), ("eraser", "eraser")):
            host.command(label, lambda k=key: self.use(k), "", "stik tool cut")
        host.command("remove background", lambda: self.remove_background(full=True), "",
                     "stik matte cut out clean")
        host.command("auto-cut islands", self.islands, "", "stik sticker sheet split")
        host.command("sticker border", self.apply_border, "", "stik die cut outline")
        host.command("export pieces…", self.export, "", "stik png save images bulk")

    def teardown(self):
        self.save()

    def save(self):
        self.host.settings.clear()
        self.host.settings.update(self.s)
        self.host.save_settings()

    @property
    def window(self):
        return self.host.window

    # -- the panel -----------------------------------------------------------------
    def toggle_panel(self):
        if self.panel.isVisible():
            self.panel.close_panel()
        else:
            self.panel.open()

    def use(self, key: str | None):
        self.host.use(self.tools[key] if key else None)
        if key and not self.panel.isVisible():
            self.panel.open()
        self.panel.refresh()

    def tool_key(self, event) -> bool:
        keys = {QtCore.Qt.Key_L: "lasso", QtCore.Qt.Key_M: "rect", QtCore.Qt.Key_O: "ellipse",
                QtCore.Qt.Key_W: "wand", QtCore.Qt.Key_E: "eraser"}
        if event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
            return False
        if event.key() in keys:
            self.use(keys[event.key()])
            return True
        return False

    def build_panel(self):
        panel = self.host.panel("stik", on_close=self._closed)
        s = self.s

        def put(key, then=None):
            def setter(value):
                s[key] = value
                if then:
                    then()
            return setter

        def tool_word(key, word):
            return lambda: f"[{word}]" if self.host.active_tool is self.tools[key] else word

        panel.links("tool", [(tool_word("lasso", "lasso"), lambda: self.use("lasso")),
                             (tool_word("rect", "rect"), lambda: self.use("rect")),
                             (tool_word("ellipse", "ellipse"), lambda: self.use("ellipse"))])
        panel.links("", [(tool_word("wand", "wand"), lambda: self.use("wand")),
                         (tool_word("eraser", "eraser"), lambda: self.use("eraser")),
                         ("done", lambda: self.use(None))])
        panel.section("cut")
        panel.slider("feather", 0, 20, lambda: s["feather"], put("feather"), step=0.5, unit=" pt",
                     default=0)
        panel.slider("smooth", 0, 20, lambda: s["smooth"], put("smooth"), step=0.5, unit=" pt",
                     default=2)
        panel.toggle("keeps", lambda: s["copy"], put("copy"), on="copy", off="cut")
        panel.section("wand · eraser")
        panel.slider("tolerance", 1, 80, lambda: s["tolerance_wand"], put("tolerance_wand"),
                     default=18)
        panel.toggle("contiguous", lambda: s["contiguous"], put("contiguous"))
        panel.slider("eraser", 1, 120, lambda: s["eraser"], put("eraser"), unit=" pt", default=16)
        panel.slider("hardness", 0, 100, lambda: s["hardness"], put("hardness"), unit="%",
                     default=70)
        panel.section("background")
        methods = [key for key, _label, _tip in matting.METHODS
                   if key != matting.AI or matting.rembg_available()]
        panel.choice("method", lambda: methods, lambda: s["method"],
                     put("method", self.background_changed))
        live = self.background_changed
        panel.slider("tolerance", 1, 80, lambda: s["tolerance"], put("tolerance", live), default=18)
        panel.slider("softness", 0, 40, lambda: s["softness"], put("softness", live), default=8)
        panel.slider("grow", -10, 10, lambda: s["grow"], put("grow", live), unit=" px", default=0)
        panel.slider("feather", 0, 10, lambda: s["bg_feather"], put("bg_feather", live),
                     step=0.5, unit=" px", default=0)
        panel.slider("despeckle", 0, 200, lambda: s["despeckle"], put("despeckle", live),
                     step=5, unit=" px", default=0)
        panel.toggle("largest", lambda: s["keep_largest"], put("keep_largest", live),
                     on="only", off="all")
        panel.toggle("holes", lambda: s["fill_holes"], put("fill_holes", live), on="filled",
                     off="open")
        panel.links("", [("apply", lambda: self.remove_background(full=True)),
                         ("reset mask", self.window.reset_masks)])
        panel.section("sheet")
        panel.slider("min island", 50, 20000, lambda: s["min_island"], put("min_island"),
                     step=50, unit=" px", default=400)
        panel.links("", [("auto-cut islands", self.islands), ("arrange", self.window.arrange_selection)])
        panel.section("border")
        panel.slider("width", 0, 40, lambda: s["border"], put("border"), step=0.5, unit=" pt",
                     default=6)
        panel.slider("smooth", 0, 20, lambda: s["border_smooth"], put("border_smooth"), step=0.5,
                     unit=" pt", default=2)
        panel.swatches("colour", ["#ffffff", "#141414", "#f4efe2", "#e53b2c", "#2f4bd8", "#e8d84a"],
                       lambda: s["border_colour"], put("border_colour"))
        panel.links("", [("apply to selection", self.apply_border),
                         ("remove", lambda: self.window.set_border(self.window.selection(), 0,
                                                                   "#ffffff", 0))])
        panel.section("export")
        panel.text("pattern", lambda: s["pattern"], put("pattern"))
        panel.slider("scale", 25, 400, lambda: s["scale"], put("scale"), step=25, unit="%",
                     default=100)
        panel.slider("padding", 0, 100, lambda: s["padding"], put("padding"), unit=" px", default=0)
        panel.toggle("trim", lambda: s["trim"], put("trim"))
        panel.buttons([("export selected…", self.export), ("done", lambda: self.use(None))])
        return panel

    def _closed(self):
        if self.host.active_tool in self.tools.values():
            self.host.use(None)
        self.save()

    # -- cutting -------------------------------------------------------------------
    def images_under(self, polygon: QtGui.QPolygonF) -> list:
        """Images the polygon touches: the selected ones first, then top down."""
        found = [item for item in self.host.scene.items(polygon)
                 if getattr(item, "kind", None) == "image" and getattr(item, "alive", False)]
        page = self.window.sheet.scene_page_rect()
        found = [t for t in found if not t.pinned or page.intersects(polygon.boundingRect())]
        chosen = [t for t in found if t.isSelected()]
        return chosen + [t for t in found if t not in chosen]

    def cut(self, polygon: QtGui.QPolygonF, copy: bool):
        window = self.window
        before = window.snapshot()
        for target in self.images_under(polygon):
            piece = window.cut(target, polygon, copy=copy, feather_pt=self.s["feather"])
            if piece is not None:
                window.push("things", before)
                window.select([piece])
                window.changed()
                self.host.toast(f"{'copied' if copy else 'cut'} · {piece.name}")
                return piece
        self.host.toast("nothing to cut there")
        return None

    def target_at(self, at: QtCore.QPointF):
        for item in self.host.scene.items(at):
            if getattr(item, "kind", None) == "image" and getattr(item, "alive", False):
                return item
        return None

    def wand(self, at: QtCore.QPointF, restore: bool = False):
        thing = self.target_at(at)
        if thing is None:
            return
        x, y = (int(v) for v in thing.to_pixels(thing.mapFromScene(at)))
        shown = thing.alpha() if not restore else (
            thing.mask if thing.mask is not None else np.full(thing.alpha().shape, 255, np.uint8))
        region = matting.wand_region(thing.bgra(), shown, x, y, self.s["tolerance_wand"],
                                     self.s["contiguous"], through_hidden=restore)
        if region is None:
            return
        before = self.window.snapshot()
        matte = thing.matte.astype(np.float32) if thing.matte is not None else \
            np.full(region.shape, 255.0, np.float32)
        matte = np.maximum(matte, region * 255.0) if restore else matte * (1.0 - region)
        thing.set_pixels(matte=np.clip(matte + 0.5, 0, 255).astype(np.uint8))
        self.window.push("things", before)
        self.window.changed()

    def erase_begin(self, at, restore: bool):
        thing = self.target_at(at)
        if thing is None:
            return None
        matte = thing.matte.astype(np.float32) if thing.matte is not None else \
            np.full((thing.original.height(), thing.original.width()), 255.0, np.float32)
        return {"thing": thing, "matte": matte, "restore": restore, "last": None,
                "before": self.window.snapshot()}

    def erase_to(self, stroke, at):
        thing = stroke["thing"]
        x, y = thing.to_pixels(thing.mapFromScene(at))
        radius = max(0.5, self.s["eraser"] / 2 * thing.px_per_pt())
        steps = [(x, y)]
        if stroke["last"] is not None:                    # fill the gap between events
            lx, ly = stroke["last"]
            n = int(max(abs(x - lx), abs(y - ly)) / max(1.0, radius / 3)) + 1
            steps = [(lx + (x - lx) * i / n, ly + (y - ly) * i / n) for i in range(1, n + 1)]
        stroke["last"] = (x, y)
        h, w = stroke["matte"].shape
        hard = self.s["hardness"] / 100.0
        for cx, cy in steps:
            r = int(math.ceil(radius)) + 1
            x0, x1 = max(0, int(cx) - r), min(w, int(cx) + r + 1)
            y0, y1 = max(0, int(cy) - r), min(h, int(cy) + r + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            d = np.hypot(xx - cx, yy - cy) / radius
            brush = np.clip((1.0 - d) / max(1e-3, 1.0 - hard), 0.0, 1.0) if hard < 1 else \
                (d <= 1.0).astype(np.float32)
            patch = stroke["matte"][y0:y1, x0:x1]
            if stroke["restore"]:
                stroke["matte"][y0:y1, x0:x1] = np.maximum(patch, brush * 255.0)
            else:
                stroke["matte"][y0:y1, x0:x1] = patch * (1.0 - brush)
        thing.set_pixels(matte=np.clip(stroke["matte"] + 0.5, 0, 255).astype(np.uint8))

    def erase_end(self, stroke):
        self.window.push("things", stroke["before"])
        self.window.changed()

    # -- background removal ------------------------------------------------------------
    def params(self) -> matting.Params:
        s = self.s
        return matting.Params(method=s["method"], tolerance=s["tolerance"], softness=s["softness"],
                              grow=int(s["grow"]), feather=s["bg_feather"],
                              despeckle=int(s["despeckle"]), keep_largest=s["keep_largest"],
                              fill_holes=s["fill_holes"])

    def background_changed(self):
        """A slider moved: preview fast methods now (on a small copy), and
        work it out at full size once the slider rests."""
        if self.s["method"] not in matting.LIVE_METHODS:
            return
        self.remove_background(full=False)
        self._bg_timer.start()

    def remove_background(self, full: bool = True):
        import cv2
        things = self.window.images()
        if not things:
            if full:
                self.host.toast("remove background · select an image")
            return
        if self._bg_before is None:
            self._bg_before = self.window.snapshot()
        params = self.params()
        if full and params.method not in matting.LIVE_METHODS:
            self.host.toast(f"remove background · {params.method}…")
            QtWidgets.QApplication.processEvents()
        for thing in things:
            pixels = thing.bgra()
            shape = thing.mask if thing.mask is not None else \
                np.full(pixels.shape[:2], 255, np.uint8)
            h, w = shape.shape
            k = 1.0 if full else min(1.0, PROXY / max(h, w))
            if k < 1.0:
                size = (max(1, int(w * k)), max(1, int(h * k)))
                small = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
                small_shape = cv2.resize(shape, size, interpolation=cv2.INTER_AREA)
                keep = matting.matte(small, small_shape, params)
                keep = cv2.resize(keep, (w, h), interpolation=cv2.INTER_LINEAR)
            else:
                keep = matting.matte(pixels, shape, params)
            thing.set_pixels(matte=keep)
        if full:
            self.window.push("things", self._bg_before)
            self._bg_before = None
            self.window.changed()

    def islands(self):
        """Every separate sticker on the selected sheet becomes its own cutout
        (its soft edge included), and they are then arranged in rows."""
        things = self.window.images()
        if len(things) != 1:
            self.host.toast("auto-cut islands · select one sheet")
            return
        sheet = things[0]
        shape = sheet.mask if sheet.mask is not None else \
            np.full(sheet.bgra().shape[:2], 255, np.uint8)
        found = matting.islands(sheet.bgra(), shape, self.params(), int(self.s["min_island"]))
        if not found:
            self.host.toast("auto-cut islands · none found")
            return
        window = self.window
        before = window.snapshot()
        pieces = []
        for x, y, patch in found:
            h, w = patch.shape
            sel = np.zeros(shape.shape, np.uint8)
            sel[y:y + h, x:x + w] = np.clip(patch * 255.0 + 0.5, 0, 255).astype(np.uint8)
            piece = window.cut_selection(sheet, sel, copy=False, lift=False)
            if piece is not None:
                pieces.append(piece)
        window.select(pieces)
        window.arrange_selection()
        # beside the sheet, as in stik, so the holes they left show
        shift = sheet.sceneBoundingRect().right() + 40 - min(
            p.sceneBoundingRect().left() for p in pieces)
        for piece in pieces:
            piece.moveBy(shift, 0)
        window.history.pop()                  # arrange's own step: one step for all of it
        window.push("things", before)
        self.host.toast(f"auto-cut · {len(pieces)} stickers")

    # -- border and export --------------------------------------------------------------
    def apply_border(self):
        things = self.window.images()
        if not things:
            self.host.toast("sticker border · select an image")
            return
        self.window.set_border(things, self.s["border"], self.s["border_colour"],
                               self.s["border_smooth"])

    def export(self):
        things = self.window.images()
        if not things:
            self.host.toast("export pieces · select images")
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.window, "Export pieces to", self.s.get("folder") or os.path.expanduser("~/Desktop"))
        if not folder:
            return
        self.s["folder"] = folder
        written = self.write(things, folder)
        self.host.toast(f"exported {len(written)} pieces → {folder}")

    def write(self, things, folder: str) -> list[str]:
        written = []
        for n, thing in enumerate(sorted(things, key=lambda t: (t.name, t.uid)), 1):
            image = self.render_piece(thing)
            name = self.name_for(thing, n, image)
            path = os.path.join(folder, name + ".png")
            k = 2
            while os.path.exists(path):
                path = os.path.join(folder, f"{name}_{k}.png")
                k += 1
            image.save(path)
            written.append(path)
        return written

    def name_for(self, thing, n: int, image: QtGui.QImage) -> str:
        tokens = {"name": thing.name or "piece", "n": n, "w": image.width(), "h": image.height(),
                  "date": time.strftime("%Y%m%d")}
        try:
            name = self.s["pattern"].format(**tokens)
        except (KeyError, ValueError, IndexError):
            name = tokens["name"]
        return re.sub(r"[^\w.\- ]+", "_", name).strip() or "piece"

    def render_piece(self, thing) -> QtGui.QImage:
        """The piece as it looks on the canvas - border, rotation, mirroring -
        at its own resolution times the export scale, trimmed and padded."""
        k = thing.px_per_pt() * self.s["scale"] / 100.0
        rect = thing.mapRectToScene(thing.boundingRect())
        pad = int(self.s["padding"])
        size = QtCore.QSize(int(math.ceil(rect.width() * k)) + 2 * pad,
                            int(math.ceil(rect.height() * k)) + 2 * pad)
        image = QtGui.QImage(size, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        painter.translate(pad, pad)
        painter.scale(k, k)
        painter.translate(-rect.topLeft())
        painter.setTransform(thing.sceneTransform(), True)
        thing.render(painter, QtGui.QColor(style.INK))
        painter.end()
        if self.s["trim"]:
            from ..export import to_numpy
            alpha = to_numpy(image)[..., 3]
            ys, xs = np.nonzero(alpha > 0)
            if len(ys):
                image = image.copy(max(0, xs.min() - pad), max(0, ys.min() - pad),
                                   xs.max() - xs.min() + 1 + 2 * pad, ys.max() - ys.min() + 1 + 2 * pad)
        return image.convertToFormat(QtGui.QImage.Format_ARGB32)
