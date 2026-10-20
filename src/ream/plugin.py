"""
Plugins: components added to ream without touching ream.

A plugin is a Python module with a `Plugin` class:

    from ream.plugin import Plugin

    class Plugin(Plugin):
        name = "stamp"                       # unique; also the settings key

        def setup(self, host):
            host.command("stamp: date", self.stamp, hint="⌥⌘T", shortcut="Ctrl+Alt+T")

        def stamp(self):
            self.host.place_text(time.strftime("%d.%m.%Y"))

`setup(host)` is called once ream is up; `teardown()` when it closes.
`self.host` is the Host below - everything a plugin may touch:

| host.            | does |
| ---------------- | ---- |
| command(...)     | a palette entry, optionally with a shortcut |
| panel(title)     | a slider panel (ream.panel.Panel): slider, choice, toggle, links ... |
| frame(...)       | a frame on the canvas: moved by its label, resized by its corner |
| render(rect, dpi)| what is on the canvas inside a scene rect, as RGBA numpy |
| place_image(...) | put an image on the canvas (as if dropped there) |
| place_text(...)  | start a text block with some words in it |
| timer(ms, fn)    | a repeating QTimer, stopped at teardown |
| use(tool)        | make a Tool (below) the canvas tool; None: back to writing |
| visible_rect()   | the part of the canvas in sight, in scene coordinates |
| settings         | this plugin's own dict, saved between runs |
| toast(text)      | the grey line at the bottom of the window |
| window / scene / view | the Qt objects, for anything else |

Plugins are found in three places, in this order:

1. built in: modules in `ream/plugins/`;
2. yours: `.py` files (or packages) in `~/Library/Application Support/ream/plugins/`;
3. installed: Python packages declaring an entry point in the `ream.plugins`
   group, e.g. `[project.entry-points."ream.plugins"] stamp = "ream_stamp"`.

A plugin that fails to load or set up is reported in a toast and in
`host.errors`; ream carries on without it.  A plugin can be turned off with
**plugin · name** in the palette (remembered in the prefs).
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback
from pathlib import Path
from typing import Callable

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from . import style
from .panel import Panel


class Plugin:
    """Subclass this; give it a `name`, and do your work in setup()."""

    name = "plugin"
    title = ""                    # shown in the palette; defaults to the name

    def __init__(self):
        self.host: Host | None = None

    def setup(self, host: "Host"):
        pass

    def teardown(self):
        pass


class Tool:
    """A canvas tool: while it is active (host.use(tool)), presses and drags
    on the canvas come to it instead of selecting, keys come to it first,
    and it draws over the canvas in screen space.  Esc leaves it.  Override
    what you need; every handler gets scene coordinates."""

    name = "tool"
    cursor = QtCore.Qt.CrossCursor

    def press(self, at: QtCore.QPointF, mods) -> bool:
        return False                            # True: this drag is mine

    def move(self, at: QtCore.QPointF, mods):
        pass

    def release(self, at: QtCore.QPointF, mods):
        pass

    def hover(self, at: QtCore.QPointF):
        pass

    def key(self, event: QtGui.QKeyEvent) -> bool:
        return False                            # True: handled

    def paint(self, painter: QtGui.QPainter, transform: QtGui.QTransform):
        pass                                    # screen pixels: map scene points with transform

    def leave(self):
        pass                                    # another tool took over, or Esc


class Frame(QtWidgets.QGraphicsItem):
    """A labelled rectangle on the canvas that belongs to a plugin.

    The user moves it by its label or edge and resizes it by its corner;
    clicks inside go through to whatever is under it, unless the plugin
    gives the frame a `drag_out` - then dragging from inside picks up the
    image it returns (as a new image on the canvas).

    `paint_content(painter, rect)` draws inside it (rect in item coords),
    `on_change()` hears about moves and resizes."""

    EDGE_PX = 6                      # grab distance round the edge, screen px

    def __init__(self, host: "Host", label: str, size: QtCore.QSizeF, *,
                 paint_content: Callable | None = None,
                 drag_out: Callable[[QtCore.QPointF], QtGui.QImage | None] | None = None,
                 on_change: Callable[[], None] | None = None,
                 on_context: Callable[[], None] | None = None,
                 fill: bool = False):
        super().__init__()
        self.host = host
        self.on_context = on_context            # right-click: open its panel
        self.label = label
        self.w, self.h = float(size.width()), float(size.height())
        self.paint_content = paint_content
        self.drag_out = drag_out
        self.on_change = on_change
        self.fill = fill
        self.setZValue(50000)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)

    def boundingRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(0.0, 0.0, self.w, self.h)

    def scene_rect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.pos(), QtCore.QSizeF(self.w, self.h))

    def set_size(self, w: float, h: float):
        self.prepareGeometryChange()
        self.w, self.h = max(24.0, w), max(24.0, h)
        self.update()

    def paint(self, painter, option, widget=None):
        rect = self.boundingRect()
        if self.fill:
            painter.fillRect(rect, QtGui.QColor("#ffffff"))
        if self.paint_content:
            painter.save()
            painter.setClipRect(rect)
            self.paint_content(painter, rect)
            painter.restore()

    def changed(self):
        if self.on_change:
            self.on_change()
        self.update()

    # -- the parts a press can land on ----------------------------------------
    def label_rect(self, transform: QtGui.QTransform) -> QtCore.QRectF:
        """The label above the top-left corner, in view pixels."""
        corner = transform.map(self.scenePos())
        metrics = QtGui.QFontMetrics(style.ui_font(11))
        return QtCore.QRectF(corner.x(), corner.y() - 20, metrics.horizontalAdvance(self.label) + 8, 18)

    def part_at(self, view_pos: QtCore.QPointF, transform: QtGui.QTransform) -> str | None:
        """"move", "resize", "inside" or None."""
        box = transform.mapRect(self.scene_rect())
        corner = box.bottomRight()
        if QtCore.QRectF(corner.x() - 10, corner.y() - 10, 20, 20).contains(view_pos):
            return "resize"
        if self.label_rect(transform).contains(view_pos):
            return "move"
        edge = self.EDGE_PX
        if box.adjusted(-edge, -edge, edge, edge).contains(view_pos):
            if not box.adjusted(edge, edge, -edge, -edge).contains(view_pos):
                return "move"
            return "inside"
        return None

    def paint_chrome(self, painter: QtGui.QPainter, transform: QtGui.QTransform, meta: QtGui.QColor):
        """The edge, label and corner, drawn in screen space by the canvas."""
        box = transform.mapRect(self.scene_rect())
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        pen = QtGui.QPen(style.qc(style.INK), 1.0)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(box.adjusted(-1, -1, 0, 0))
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setFont(style.ui_font(11))
        painter.setPen(meta)
        painter.drawText(self.label_rect(transform).adjusted(0, 0, 0, -3),
                         QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom, self.label)
        corner = box.bottomRight()
        painter.setPen(QtGui.QPen(style.qc(style.INK), 1.0))
        painter.setBrush(style.qc("#ffffff"))
        painter.drawRect(QtCore.QRectF(corner.x() - 3.5, corner.y() - 3.5, 7, 7))
        painter.restore()


class Host:
    """What a plugin gets.  One per plugin, so settings and timers are its own."""

    def __init__(self, window, plugin: Plugin):
        self.window = window
        self.plugin = plugin
        self.frames: list[Frame] = []
        self.panels: list[Panel] = []
        self.commands: list[tuple] = []
        self.timers: list[QtCore.QTimer] = []
        self.actions: list[QtWidgets.QAction] = []
        self.tools: list[tuple] = []             # (tool, label, key, choose)
        self.contexts: list[tuple] = []          # (test(thing), open)

    def dispose(self):
        """Undo everything the plugin added (it is being turned off)."""
        for timer in self.timers:
            timer.stop()
        for panel in self.panels:
            panel.hide()
            panel.deleteLater()
        for frame in self.frames:
            if frame.scene() is not None:
                self.scene.removeItem(frame)
        for action in self.actions:
            self.window.removeAction(action)
        if self.window.active_tool in [t for t, *_rest in self.tools]:
            self.window.use_tool(None)
        self.frames.clear(), self.panels.clear(), self.commands.clear()
        self.timers.clear(), self.actions.clear(), self.tools.clear(), self.contexts.clear()

    # -- the window's parts ---------------------------------------------------
    @property
    def scene(self) -> QtWidgets.QGraphicsScene:
        return self.window.scene

    @property
    def view(self):
        return self.window.view

    @property
    def settings(self) -> dict:
        store = self.window.prefs.setdefault("plugins", {})
        return store.setdefault(self.plugin.name, {})

    def save_settings(self):
        self.window._write_prefs()

    def toast(self, text: str):
        self.window.toast(text)

    # -- adding to ream ---------------------------------------------------------
    def command(self, title: str, run: Callable[[], object], hint: str = "",
                keywords: str = "", shortcut: str | None = None):
        """A palette entry; `shortcut` like "Ctrl+Alt+K" (Ctrl is ⌘ on a Mac)."""
        self.commands.append((title, run, hint, keywords))
        if shortcut:
            action = QtWidgets.QAction(self.window)
            action.setShortcut(QtGui.QKeySequence(shortcut))
            action.setShortcutContext(QtCore.Qt.WindowShortcut)
            action.triggered.connect(lambda _checked=False: run())
            self.window.addAction(action)
            self.actions.append(action)

    def panel(self, title: str, on_close: Callable[[], None] | None = None) -> Panel:
        panel = Panel(self.window, title, on_close=on_close, on_tab=self.window.open_palette)
        self.panels.append(panel)
        return panel

    def frame(self, label: str, size: QtCore.QSizeF, at: QtCore.QPointF | None = None,
              **hooks) -> Frame:
        frame = Frame(self, label, size, **hooks)
        self.scene.addItem(frame)
        frame.setPos(at if at is not None else self.visible_rect().center())
        frame.hide()
        self.frames.append(frame)
        return frame

    def use(self, tool: "Tool | None"):
        """Make `tool` the canvas tool (None: back to writing)."""
        self.window.use_tool(tool)

    def tool(self, tool: "Tool", label: str | None = None, key: str = "",
             choose: Callable[[], None] | None = None):
        """List a tool in the tools panel.  `key`, one letter, picks it in
        design mode; `choose` is what picking it does (default: use it)."""
        self.tools.append((tool, label or tool.name, key.upper(),
                           choose or (lambda t=tool: self.use(t))))

    def context_panel(self, test: Callable[[object], bool], open_panel: Callable[[], None]):
        """Right-click on a thing for which `test(thing)` is true opens this
        plugin's panel (an image's, say).  Frames take `on_context` instead."""
        self.contexts.append((test, open_panel))

    @property
    def active_tool(self):
        return self.window.active_tool

    def timer(self, interval_ms: int, run: Callable[[], None]) -> QtCore.QTimer:
        timer = QtCore.QTimer(self.window)
        timer.setInterval(interval_ms)
        timer.timeout.connect(run)
        self.timers.append(timer)
        return timer

    # -- reading and writing the canvas ---------------------------------------
    def visible_rect(self) -> QtCore.QRectF:
        return self.view.visible_scene_rect()

    def render(self, rect: QtCore.QRectF, dpi: float, size: QtCore.QSize | None = None) -> np.ndarray:
        """Everything on the canvas inside `rect` (scene coordinates), as
        (h, w, 4) uint8 straight RGBA - images, text blocks, the page, the
        words - without any plugin frames.  Empty canvas is transparent."""
        from .export import to_numpy
        if size is None:
            scale = dpi / 72.0
            size = QtCore.QSize(max(1, int(round(rect.width() * scale))),
                                max(1, int(round(rect.height() * scale))))
        image = QtGui.QImage(size, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        hidden = [f for f in self.window.plugin_frames() if f.isVisible()]
        for frame in hidden:
            frame.setVisible(False)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
                               | QtGui.QPainter.TextAntialiasing)
        self.scene.render(painter, QtCore.QRectF(0, 0, size.width(), size.height()), rect,
                          QtCore.Qt.IgnoreAspectRatio)
        painter.end()
        for frame in hidden:
            frame.setVisible(True)
        return to_numpy(image)

    def place_image(self, image: QtGui.QImage, rect: QtCore.QRectF, name: str = "") -> object:
        """Put `image` on the canvas filling `rect` (scene coordinates); it
        pins to the page if dropped on it, like any image.  Returns the thing."""
        return self.window.place_qimage(image, rect, name or self.plugin.name)

    def place_text(self, text: str, at: QtCore.QPointF | None = None):
        note = self.window.new_note(at or self.window.pointer_scene())
        note.editor.textCursor().insertText(text)
        note.fit()
        return note


# -- finding and running plugins ------------------------------------------------

def user_folder() -> Path:
    base = os.environ.get("REAM_HOME") or os.path.expanduser("~/Library/Application Support/ream")
    return Path(base) / "plugins"


def _modules() -> list[tuple[str, object]]:
    """(where it came from, module) for every plugin module found."""
    found: list[tuple[str, object]] = []
    from . import plugins as builtin
    for info in pkgutil.iter_modules(builtin.__path__):
        if not info.name.startswith("_"):
            found.append(("built in", f"ream.plugins.{info.name}"))
    folder = user_folder()
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.name.startswith(("_", ".")):
                continue
            if path.suffix == ".py" or (path.is_dir() and (path / "__init__.py").is_file()):
                found.append(("yours", path))
    try:
        from importlib.metadata import entry_points
        group = entry_points().select(group="ream.plugins") if hasattr(entry_points(), "select") \
            else entry_points().get("ream.plugins", [])
        for entry in group:
            found.append(("installed", entry))
    except Exception:
        pass
    return found


def _load(where: str, source) -> object:
    if where == "built in":
        return importlib.import_module(source)
    if where == "yours":
        path = Path(source)
        name = f"ream_user_plugin_{path.stem}"
        target = path / "__init__.py" if path.is_dir() else path
        spec = importlib.util.spec_from_file_location(
            name, target, submodule_search_locations=[str(path)] if path.is_dir() else None)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    return source.load()


def load_all(window) -> tuple[list[tuple[Plugin, Host]], list[str]]:
    """Import and set up every plugin that is not turned off."""
    loaded: list[tuple[Plugin, Host]] = []
    errors: list[str] = []
    off = set(window.prefs.get("plugins_off", []))
    seen: set[str] = set()
    for where, source in _modules():
        label = getattr(source, "name", None) or str(source)
        try:
            module = _load(where, source)
            cls = getattr(module, "Plugin", None)
            if cls is None or not isinstance(cls, type) or not issubclass(cls, Plugin):
                continue
            plugin = cls()
            label = plugin.name
            if plugin.name in seen:
                errors.append(f"{plugin.name}: another plugin has that name")
                continue
            seen.add(plugin.name)
            host = Host(window, plugin)
            plugin.host = host
            plugin.where = where
            if plugin.name in off:
                loaded.append((plugin, host))
                plugin.active = False
                continue
            plugin.setup(host)
            plugin.active = True
            loaded.append((plugin, host))
        except Exception:
            errors.append(f"{label}: {traceback.format_exc(limit=3).strip().splitlines()[-1]}")
            print(f"ream: plugin {label} failed\n{traceback.format_exc()}", file=sys.stderr)
    return loaded, errors


def switch(window, plugin: Plugin, on: bool):
    """Turn a plugin on or off while ream runs; remembered in the prefs."""
    off = set(window.prefs.get("plugins_off", []))
    if on and not getattr(plugin, "active", False):
        host = Host(window, plugin)
        plugin.host = host
        plugin.setup(host)
        plugin.active = True
        off.discard(plugin.name)
        for i, (p, _h) in enumerate(window.plugins):
            if p is plugin:
                window.plugins[i] = (plugin, host)
    elif not on and getattr(plugin, "active", False):
        try:
            plugin.teardown()
        finally:
            plugin.host.dispose()
            plugin.active = False
        off.add(plugin.name)
    window.prefs["plugins_off"] = sorted(off)
    window._write_prefs()
