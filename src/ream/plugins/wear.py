"""
wear: distress for the things on the page - torn edges for images, and
stamps (stains, splatter, tape, dust, folds, marks) to place.

`⌥⌘W` (or **wear** in the palette) opens the panel.

**Tear edges.** Select images and **tear**: their edges are torn - drawn by
ream, or along a torn matte from your stamps folder - with the paper's core
showing along the tear (white, cream or burnt).  It is a property of the
image, never baked in: the sliders change it live, **new tear** tears it
differently, **mend** takes it off, undo steps back.  The **tear** tool (`R`)
tears whatever image you click; `⌥`-click mends it.

**Stamps.** Pick one in the grid and the **stamp** tool (`S`) is on: each
click puts it down, centred on the pointer, as an image (so it moves,
turns, stacks, pins to the page and is distressed like one).  Size is a share
of the page's width; **jitter** varies it, **turn** turns each one a little
or any way, **tint** recolours it, **strength** fades it.  Sheets of pieces
(tape, document marks) give a different piece each click.  Esc stops.

Stamps are your textures (see ream.wear for the folder and its index) plus
the few ream draws itself: coffee ring, ink blot, specks, crease.
"""
from __future__ import annotations

import random

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import style, wear
from ..page import bgra_to_qimage
from ..plugin import Plugin as Base, Tool

DEFAULTS = {**wear.DEFAULT_TEAR, "rim_name": "paper", "category": "drawn", "stamp": "drawn:coffee ring",
            "size": 28.0, "jitter": 15.0, "turn": "a little", "tint": "as is", "strength": 100.0}
TURNS = {"none": 0.0, "a little": 14.0, "any": 180.0}
CELL = 70                        # px, a stamp's square in the grid


class StampTool(Tool):
    name = "stamp"
    cursor = QtCore.Qt.CrossCursor

    def __init__(self, plugin):
        self.plugin = plugin
        self.at: QtCore.QPointF | None = None

    def press(self, at, mods) -> bool:
        self.plugin.stamp_at(at)
        return True

    def hover(self, at):
        self.at = at

    def key(self, event) -> bool:
        return self.plugin.tool_key(event)

    def paint(self, painter, transform):
        if self.at is None:
            return
        w, h = self.plugin.next_size()
        rect = transform.mapRect(QtCore.QRectF(self.at.x() - w / 2, self.at.y() - h / 2, w, h))
        pen = QtGui.QPen(QtGui.QColor(style.INK), 1.0, QtCore.Qt.CustomDashLine)
        pen.setDashPattern([3.0, 3.0])
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(rect)


class TearTool(Tool):
    name = "tear"
    cursor = QtCore.Qt.PointingHandCursor

    def __init__(self, plugin):
        self.plugin = plugin

    def press(self, at, mods) -> bool:
        thing = self.plugin.window.thing_at(at, behind=True)
        if thing is None or thing.kind != "image":
            return True
        if mods & QtCore.Qt.AltModifier:
            self.plugin.mend([thing])
        else:
            self.plugin.tear([thing], fresh=True)
        return True

    def key(self, event) -> bool:
        return self.plugin.tool_key(event)


class StampGrid(QtWidgets.QWidget):
    """The stamps of one category as thumbnails; click one to stamp with it."""

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.entries: list[dict] = []
        self.thumbs: dict[str, QtGui.QImage] = {}
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(CELL)

    def refresh(self):
        self.entries = self.plugin.entries_in(self.plugin.s["category"])
        cols = max(1, (self.width() or 290) // CELL)
        rows = max(1, -(-len(self.entries) // cols))
        self.setFixedHeight(rows * (CELL + 14) + 2)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def thumb(self, entry: dict) -> QtGui.QImage | None:
        key = entry["id"]
        if key not in self.thumbs:
            pixels = self.plugin.sample(entry)
            if pixels is None:
                return None
            image = bgra_to_qimage(pixels)
            self.thumbs[key] = image.scaled(CELL - 10, CELL - 10, QtCore.Qt.KeepAspectRatio,
                                            QtCore.Qt.SmoothTransformation)
        return self.thumbs[key]

    def cell(self, n: int) -> QtCore.QRect:
        cols = max(1, self.width() // CELL)
        return QtCore.QRect((n % cols) * CELL, (n // cols) * (CELL + 14), CELL - 4, CELL - 4)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setFont(style.ui_font(9))
        chosen = self.plugin.s["stamp"]
        if not self.entries:
            painter.setPen(QtGui.QColor("#8c8b86"))
            painter.drawText(self.rect(), QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap,
                             "no stamps here yet: put textures in the stamps folder")
            return
        for n, entry in enumerate(self.entries):
            box = self.cell(n)
            painter.fillRect(box, QtGui.QColor("#f4f1ea"))
            image = self.thumb(entry)
            if image is not None:
                spot = QtCore.QRect(0, 0, image.width(), image.height())
                spot.moveCenter(box.center())
                painter.drawImage(spot, image)
            painter.setPen(QtGui.QPen(QtGui.QColor(style.INK), 2 if entry["id"] == chosen else 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(box.adjusted(0, 0, -1, -1) if entry["id"] != chosen else box.adjusted(1, 1, -1, -1))
            painter.setPen(QtGui.QColor(style.INK if entry["id"] == chosen else "#8c8b86"))
            label = QtGui.QFontMetrics(painter.font()).elidedText(entry["label"], QtCore.Qt.ElideRight,
                                                                   CELL - 4)
            painter.drawText(QtCore.QRect(box.left(), box.bottom() + 1, CELL - 4, 13),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, label)

    def mousePressEvent(self, event):
        for n, entry in enumerate(self.entries):
            if self.cell(n).contains(event.pos()):
                self.plugin.choose_stamp(entry["id"])
                self.update()
                return


class Plugin(Base):
    name = "wear"
    title = "wear"

    def setup(self, host):
        self.host = host
        self.s = {**DEFAULTS, **host.settings}
        self.rng = random.Random()
        self.variants: dict[str, list] = {}
        self._tear_before = None
        self._next = None                         # the stamp the next click puts down
        self._drafted: list = []                  # torn while a slider moves: finish at full size
        self._finish = QtCore.QTimer(host.window, singleShot=True, interval=350)
        self._finish.timeout.connect(self.finish_tears)
        self.stamp_tool = StampTool(self)
        self.tear_tool = TearTool(self)
        self.grid = StampGrid(self)
        self.panel = self.build_panel()
        host.command("wear", self.toggle_panel, "⌥⌘W", "distress tools stamps torn tear stains tape",
                     shortcut="Ctrl+Alt+W")
        host.command("tear edges", lambda: self.tear(None, fresh=False), "", "wear torn rip images")
        host.command("mend edges", lambda: self.mend(None), "", "wear untear torn")
        host.command("stamp", self.arm, "", "wear stain splatter tape dust place")
        host.command("open stamps folder", self.open_folder, "", "wear textures texturelabs")
        host.tool(self.stamp_tool, "stamp", "S", choose=self.arm)
        host.tool(self.tear_tool, "tear", "R", choose=lambda: self.use(self.tear_tool))

    def teardown(self):
        self.save()

    def save(self):
        self.host.settings.clear()
        self.host.settings.update(self.s)
        self.host.save_settings()

    @property
    def window(self):
        return self.host.window

    # -- the panel ------------------------------------------------------------------
    def toggle_panel(self):
        if self.panel.isVisible():
            self.panel.close_panel()
        else:
            self.open_panel()

    def open_panel(self):
        self.panel.open()
        self.panel.raise_()
        self.grid.refresh()
        self.panel.fit_height()

    def use(self, tool):
        self.host.use(tool)
        if tool is not None and not self.panel.isVisible():
            self.open_panel()

    def tool_key(self, event) -> bool:
        if event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
            return False
        if event.key() == QtCore.Qt.Key_S:
            self.arm()
            return True
        if event.key() == QtCore.Qt.Key_R:
            self.use(self.tear_tool)
            return True
        return False

    def build_panel(self):
        panel = self.host.panel("wear", on_close=self._closed)
        s = self.s

        def put(key, then=None):
            def setter(value):
                s[key] = value
                if then:
                    then()
            return setter

        live = self.retear

        def drag():                               # sliders: a quick draft while they move
            self.retear(draft=True)
        panel.section("tear edges")
        panel.choice("edge", self.edge_names, self.edge_name, self.set_edge)
        panel.choice("sides", lambda: list(wear.SIDES), lambda: s["sides"], put("sides", live))
        panel.slider("depth", 1, 40, lambda: s["depth"], put("depth", drag), step=0.5, unit=" pt",
                     default=wear.DEFAULT_TEAR["depth"])
        panel.slider("rough", 0, 100, lambda: s["rough"] * 100, lambda v: put("rough", drag)(v / 100),
                     unit="%", default=55)
        panel.slider("rim", 0, 8, lambda: s["rim"], put("rim", drag), step=0.1, unit=" pt",
                     default=wear.DEFAULT_TEAR["rim"])
        panel.choice("core", lambda: list(wear.RIMS), lambda: s["rim_name"], self.set_rim)
        panel.links("", [("tear", lambda: self.tear(None, fresh=False)),
                         ("new tear", lambda: self.tear(None, fresh=True)),
                         ("mend", lambda: self.mend(None)),
                         (lambda: "[tear tool]" if self.host.active_tool is self.tear_tool
                          else "tear tool", lambda: self.use(self.tear_tool))])
        panel.section("stamps")
        panel.choice("kind", self.category_names, lambda: s["category"], self.set_category)
        panel.widget(self.grid, self.grid.refresh)
        panel.slider("size", 3, 120, lambda: s["size"], put("size"), unit="%", default=28)
        panel.slider("jitter", 0, 60, lambda: s["jitter"], put("jitter"), unit="%", default=15)
        panel.choice("turn", lambda: list(TURNS), lambda: s["turn"], put("turn"))
        panel.choice("tint", lambda: list(wear.TINTS), lambda: s["tint"], put("tint"))
        panel.slider("strength", 5, 100, lambda: s["strength"], put("strength"), unit="%",
                     default=100)
        panel.links("", [(lambda: "[stamp tool]" if self.host.active_tool is self.stamp_tool
                          else "stamp tool", self.arm),
                         ("stamps folder…", self.open_folder)])
        panel.on_release = self._released
        panel.buttons([("done", lambda: self.host.use(None)), ("close", panel.close_panel)])
        return panel

    def _closed(self):
        if self.host.active_tool in (self.stamp_tool, self.tear_tool):
            self.host.use(None)
        self.save()

    def _released(self):
        self._tear_before = None
        self.finish_tears()

    def finish_tears(self):
        """The full-size tear for images drafted while a slider moved."""
        self._finish.stop()
        drafted, self._drafted = self._drafted, []
        for thing in drafted:
            if thing.alive and thing.drafted:
                thing.recompose()
        if drafted:
            self.window.changed()

    # -- tearing --------------------------------------------------------------------
    def mattes(self) -> list[dict]:
        return [e for e in wear.library() if e["matte"]]

    def edge_names(self) -> list[str]:
        return ["drawn"] + [m["label"] for m in self.mattes()]

    def edge_name(self) -> str:
        for m in self.mattes():
            if m["path"] == self.s["matte"]:
                return m["label"]
        return "drawn"

    def set_edge(self, label: str):
        self.s["matte"] = next((m["path"] for m in self.mattes() if m["label"] == label), "")
        self.retear()

    def set_rim(self, name: str):
        self.s["rim_name"] = name
        self.s["colour"] = wear.RIMS.get(name, "")
        self.retear()

    def tear_settings(self, seed: int | None = None) -> dict:
        tear = {k: self.s[k] for k in wear.DEFAULT_TEAR}
        if seed is not None:
            tear["seed"] = seed
        return tear

    def tear(self, things=None, fresh: bool = False):
        """Tear the images (the selected ones): a new tear each, or `fresh`
        tears them again differently."""
        images = self.window.images(things)
        if not images:
            self.host.toast("tear · select an image first")
            return
        before = self.window.snapshot()
        for thing in images:
            seed = self.rng.randrange(1, 10 ** 6) if fresh or not thing.tear else thing.tear["seed"]
            thing.set_pixels(tear=self.tear_settings(seed))
        self.window.push("things", before)
        self.window.changed()

    def mend(self, things=None):
        images = [t for t in self.window.images(things) if t.tear]
        if not images:
            return
        before = self.window.snapshot()
        for thing in images:
            thing.set_pixels(tear=None)
        self.window.push("things", before)
        self.window.changed()

    def retear(self, draft: bool = False):
        """The settings change: torn images that are selected follow, one
        undo step a drag.  `draft` (a slider moving): from a small copy, the
        full-size tear when it is let go, or a moment after it stops."""
        images = [t for t in self.window.images() if t.tear]
        if not images:
            return
        fresh = self._tear_before is None
        if fresh:
            self._tear_before = self.window.snapshot()
        for thing in images:
            thing.set_pixels(tear=self.tear_settings(thing.tear["seed"]), draft=draft)
            if draft and thing.drafted and thing not in self._drafted:
                self._drafted.append(thing)
        if fresh:
            self.window.push("things", self._tear_before)
        if draft and self._drafted:
            self._finish.start()
        else:
            self.window.changed()

    # -- stamps ---------------------------------------------------------------------
    def category_names(self) -> list[str]:
        return wear.categories()

    def set_category(self, name: str):
        self.s["category"] = name
        self.panel.refresh()                      # the kind row, and the grid
        self.panel.fit_height()

    def entries_in(self, category: str) -> list[dict]:
        if category == "drawn":
            return [{"id": f"drawn:{k}", "label": k, "drawn": k} for k in wear.DRAWN]
        return [{**e, "id": e["key"]} for e in wear.library()
                if e["category"] == category and not e["matte"]]

    def entry(self, stamp_id: str) -> dict | None:
        if stamp_id.startswith("drawn:"):
            kind = stamp_id.split(":", 1)[1]
            return {"id": stamp_id, "label": kind, "drawn": kind} if kind in wear.DRAWN else None
        return next(({**e, "id": e["key"]} for e in wear.library() if e["key"] == stamp_id), None)

    def sample(self, entry: dict):
        """A stamp's look, for its thumbnail."""
        if entry.get("drawn"):
            return wear.drawn(entry["drawn"], seed=3, px=220)
        variants = self.pieces(entry)
        return variants[0] if variants else None

    def pieces(self, entry: dict) -> list:
        if entry["id"] not in self.variants:
            self.variants[entry["id"]] = wear.stamp_variants(entry)
        return self.variants[entry["id"]]

    def choose_stamp(self, stamp_id: str):
        self.s["stamp"] = stamp_id
        entry = self.entry(stamp_id)
        if entry and entry.get("tint") and entry["tint"] in wear.TINTS:
            self.s["tint"] = entry["tint"]
        self._next = None
        self.arm()
        self.panel.refresh()

    def arm(self):
        """The stamp tool on, with the chosen stamp."""
        if self.entry(self.s["stamp"]) is None:
            self.s["stamp"] = "drawn:coffee ring"
        self._next = None
        self.use(self.stamp_tool)
        self.panel.refresh()

    def _pick(self) -> tuple:
        """The next stamp to put down: (pixels, label, scale jitter, turn)."""
        entry = self.entry(self.s["stamp"]) or self.entry("drawn:coffee ring")
        if entry.get("drawn"):
            pixels = wear.drawn(entry["drawn"], seed=self.rng.randrange(10 ** 6))
        else:
            variants = self.pieces(entry)
            if not variants:
                pixels = wear.drawn("ink blot", seed=1)
            else:
                pixels = variants[self.rng.randrange(len(variants))]
        jitter = self.s["jitter"] / 100.0
        scale = 1.0 + self.rng.uniform(-jitter, jitter)
        spread = TURNS.get(self.s["turn"], 0.0)
        turn = self.rng.uniform(-spread, spread) if spread else 0.0
        return pixels, entry["label"], scale, turn

    def next_size(self) -> tuple[float, float]:
        """The size (pt) of the stamp the next click puts down."""
        if getattr(self, "_next", None) is None:
            self._next = self._pick()
        pixels, _label, scale, _turn = self._next
        w = self.window.sheet.W * self.s["size"] / 100.0 * scale
        h = w * pixels.shape[0] / max(1, pixels.shape[1])
        return w, h

    def stamp_at(self, at: QtCore.QPointF):
        """Put a stamp down, centred on `at`."""
        w, h = self.next_size()
        pixels, label, _scale, turn = self._next
        self._next = None
        tint = wear.TINTS.get(self.s["tint"], "")
        image = bgra_to_qimage(wear.finish(pixels, tint, self.s["strength"] / 100.0))
        rect = QtCore.QRectF(at.x() - w / 2, at.y() - h / 2, w, h)
        thing = self.host.place_image(image, rect, f"stamp · {label}")
        if turn:
            thing.setRotation(turn % 360.0)
        self.window.view.viewport().update()
        return thing

    def open_folder(self):
        where = wear.folder()
        where.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(where)))
        self.host.toast(f"stamps folder · {where}")
