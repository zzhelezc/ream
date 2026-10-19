"""
The window, and everything ream does.

There is no chrome.  The canvas, one page, and a palette on Tab.

- **Writing.**  The page's text editor has the keyboard unless an image is
  selected.  Typing past the foot of a page moves on to the next one; the
  strip of pages slides and the view follows the caret.
- **Pages.**  Cmd+Left and Cmd+Right turn them; the caret goes along.
  Scrolling never turns a page: it pans, over the page or not.  Pinch or
  Cmd+scroll zooms, and dragging the empty canvas pans.
- **Things.**  Images and PDF pages are dropped, pasted or browsed onto the
  canvas.  Drag one so its middle is over the page and it is pinned to that
  page: it scrolls with it and goes out with the PDF.  Drag it off to unpin.
  The corner square resizes.
- **Undo** covers words and things in one history.
- **Saving** is automatic: to the document's file once it has one, to the
  draft until then.  Starting a new document files the old draft away.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, replace
from functools import partial
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from . import __version__, distress, export, papers, plugin, profiles, project, style
from .canvas import CanvasView
from .page import GhostPage, Note, NoteText, Sheet, Thing, draw_stock
from .palette import Command, CommandPalette
from .panel import Panel

HANDLE_PX = 7
KNOB_PX = 22            # how far the rotation knob stands off the top edge
REVEAL_PX = 40          # room kept around the page when the view follows it
GRID_GAP_X, GRID_GAP_Y = 0.06, 0.11     # all-pages view: gaps as a share of the page
LAYOUTS = ("single", "spread", "all")
PREVIEW_DPI = 150
WRITE_ZOOM = 1.75        # write mode's zoom until you set your own
WRITE_LOW, WRITE_HIGH, WRITE_LINE = 0.15, 0.62, 0.42   # write mode's band, and where the line returns to
PREVIEW_MAX_DPI = 600
STOCK_SCREEN_DPI = 200   # the paper stock as drawn on the canvas
CANVAS_SWATCHES = ["#e8e7e3", "#ffffff", "#d9d6cc", "#b9b7b0", "#535353", "#2a2a2a", "#161616", "#c8d3cf"]


def home() -> Path:
    base = os.environ.get("REAM_HOME") or os.path.expanduser("~/Library/Application Support/ream")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Format:
    page: str = "a4"
    font: str = ""              # "" = the first installed of style.MONO
    size: float = 9.0           # pt
    line: float = 150.0         # % of the font's line height
    margin: float = 64.0        # pt, left and right
    head: float = 70.0          # pt, top and bottom
    para: float = 0.0           # pt of space after each paragraph
    paper: str = "white"        # a name from style.PAPERS or "#rrggbb"
    texture: str = ""           # a paper stock from the papers folder ("" = flat)
    grain: float = 60.0         # % the stock's amount: tooth strength, or blend opacity
    blend: str = "tooth"        # tooth, multiply, overlay, soft light, screen, normal
    stock_scale: float = 100.0  # % the paper's size: 100 covers the page
    ink: float = 100.0          # %: 100 is solid black, lower fades toward the paper,
                                # higher strikes heavier and packs the ink denser
    dpi: float = 300.0          # export

    @classmethod
    def from_dict(cls, data: dict | None) -> "Format":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


FORMAT_PARAMS = {"size": (5, 72), "line": (80, 300), "para": (0, 72), "margin": (0, 200),
                 "head": (0, 200), "dpi": (72, 1200), "ink": (5, 150),
                 "grain": (0, 100), "stock": (25, 400)}


@contextmanager
def busy():
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        yield
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()


class Ream(QtWidgets.QMainWindow):
    preview_ready = QtCore.pyqtSignal(int, object)      # from the preview worker
    ghost_ready = QtCore.pyqtSignal(int, object, object)  # page, key, image

    def __init__(self, paths: list[str] | None = None, theme: str | None = None):
        super().__init__()
        self.home = home()
        self.prefs = self._read_prefs()
        self.theme = theme or self.prefs.get("theme", style.DEFAULT_THEME)
        if self.theme not in style.THEMES:
            self.theme = style.DEFAULT_THEME

        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = CanvasView(self, self.scene)
        self.setCentralWidget(self.view)
        self.sheet = Sheet(self)
        self.scene.addItem(self.sheet)
        self.doc = self.sheet.doc

        self.fmt = Format()
        self.distress = distress.Settings()
        self.things: dict[int, Thing] = {}          # every thing, alive or not (undo)
        self.page = 0
        self.path: str | None = None                # None: the draft
        self.history: list[tuple[str, object]] = []
        self.future: list[tuple[str, object]] = []
        self.drag: dict | None = None
        self.preview: QtWidgets.QGraphicsPixmapItem | None = None
        self.palette_at: QtCore.QPointF | None = None
        self._loading = False
        self._ready = False                         # nothing is saved before a load
        self._undoing = False
        self._joining = False                       # a slider drag is one undo step
        self._pending_key: str | None = None
        self._preview_gen = 0
        self._ink_cache: tuple | None = None
        self._pool = ThreadPoolExecutor(max_workers=1)
        self.preview_ready.connect(self._preview_arrived)
        self.distress_panel: Panel | None = None
        self.page_panel: Panel | None = None
        self.editing: Note | None = None            # the free text being written
        self.active_tool = None                     # a plugin's canvas tool, until Esc
        self.write_mode = False
        self._before_write: tuple | None = None
        self._follow_anim = QtCore.QVariantAnimation(self)
        self._follow_anim.setDuration(180)
        self._follow_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._follow_anim.valueChanged.connect(self._follow_step)
        self.layout = self.prefs.get("layout", "single")    # single / spread / all
        if self.layout not in LAYOUTS:
            self.layout = "single"
        self.ghosts: dict[int, GhostPage] = {}
        self._profiles = profiles.load()
        self._panel_timer = QtCore.QTimer(self, singleShot=True, interval=200)
        self._panel_timer.timeout.connect(self._refresh_panels)
        self._grid_cols = 4
        self.ghost_ready.connect(self._ghost_arrived)
        self.distress_view = False                  # write on the distressed page
        self._view_from_panel = False
        self._last_edit = 0.0
        self._live_timer = QtCore.QTimer(self, singleShot=True, interval=30)
        self._live_timer.timeout.connect(lambda: self._render_live(fast=True))
        self._idle_timer = QtCore.QTimer(self, singleShot=True, interval=450)
        self._idle_timer.timeout.connect(lambda: self._render_live(fast=False))
        self._view_timer = QtCore.QTimer(self, singleShot=True, interval=160)
        self._view_timer.timeout.connect(lambda: self._render_live(fast=False))
        self._view_timer.timeout.connect(lambda: self.live() and self._render_ghosts())
        self._note_birth: tuple[int, int] | None = None

        self.save_timer = QtCore.QTimer(self, singleShot=True, interval=1200)
        self.save_timer.timeout.connect(self.autosave)
        self.anim = QtCore.QVariantAnimation(self)
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(self._animate)
        self._flip = {"from": 0.0, "to": 0.0, "pan": 0.0, "panned": 0.0}

        self.doc.contentsChanged.connect(self.changed)
        self.doc.undoCommandAdded.connect(lambda: self.push("text", None))

        self.palette = CommandPalette(self, self.commands, self.dynamic, self.caption,
                                      self.prefs.get("recents"))
        self.palette.on_ran = self._remember_recents
        self._shortcuts()

        self.setWindowTitle("ream")
        self.setMinimumSize(480, 360)
        geometry = self.prefs.get("geometry")
        if geometry:
            self.restoreGeometry(QtCore.QByteArray.fromHex(geometry.encode()))
        else:
            self.resize(1280, 860)
        self.apply_theme()

        # the textures take a few seconds to pull out of the PSDs the first time
        threading.Thread(target=distress.library, daemon=True).start()

        documents = [p for p in (paths or []) if p.lower().endswith(project.SUFFIX)]
        others = [p for p in (paths or []) if not p.lower().endswith(project.SUFFIX)]
        last = self.prefs.get("last")
        if documents:
            self.open_document(documents[0], quiet=True)
        elif last and os.path.exists(last):
            self.open_document(last, quiet=True)
        elif self.draft_path().exists():
            self.open_document(str(self.draft_path()), quiet=True)
        else:
            self.new_document(archive=False)
        if others:
            QtCore.QTimer.singleShot(0, lambda: self.add_files(others, None))
        if self.prefs.get("distress_view"):
            QtCore.QTimer.singleShot(0, lambda: self.set_distress_view(True, quiet=True))
        # plugins last, so they find ream whole
        self.plugins, self.plugin_errors = plugin.load_all(self)
        if self.plugin_errors:
            QtCore.QTimer.singleShot(400, lambda: self.toast(
                "plugin failed · " + "; ".join(self.plugin_errors)))

    # -- prefs ---------------------------------------------------------------
    def _read_prefs(self) -> dict:
        try:
            return json.loads((self.home / "prefs.json").read_text())
        except (OSError, ValueError):
            return {}

    def _write_prefs(self):
        try:
            (self.home / "prefs.json").write_text(json.dumps(self.prefs, indent=1))
        except OSError:
            pass

    def _remember_recents(self, recents: list[str]):
        self.prefs["recents"] = recents
        self._write_prefs()

    def draft_path(self) -> Path:
        return self.home / "draft.ream"

    # -- look ----------------------------------------------------------------
    def th(self) -> dict:
        return style.THEMES[self.theme]

    def ink(self) -> QtGui.QColor:
        """The ink, faded toward the paper as `ink` darkness drops."""
        k = max(0.0, min(1.0, self.fmt.ink / 100.0))
        dark, paper = style.qc(style.PAGE_INK), self.paper()
        return QtGui.QColor(*(int(round(p + (d - p) * k)) for d, p in (
            (dark.red(), paper.red()), (dark.green(), paper.green()), (dark.blue(), paper.blue()))))

    def density(self) -> float:
        """Past 100% the ink packs denser in the distress: 150% is 3×."""
        return 1.0 + max(0.0, self.fmt.ink - 100.0) / 50.0 * 2.0

    def weight(self) -> int:
        """Past 100% the type strikes heavier: regular at 100, bold at 150.
        IBM Plex Mono's weights share one width, so nothing reflows."""
        return int(round(50 + max(0.0, min(50.0, self.fmt.ink - 100.0)) / 50.0 * 25))

    def set_ink(self, value: float):
        heavier = self.weight()
        self.fmt.ink = max(5.0, min(150.0, value))
        if self.weight() != heavier:
            self.apply_format()
        self.sheet.text.setDefaultTextColor(self.ink())
        for thing in self.things.values():
            if isinstance(thing, Note):
                thing.editor.setDefaultTextColor(self.ink())
        for panel in (self.distress_panel, self.page_panel):
            if panel is not None and panel.isVisible():
                panel.refresh()             # both panels carry an ink slider
        self.changed()

    def paper(self) -> QtGui.QColor:
        value = style.PAPERS.get(self.fmt.paper, self.fmt.paper)
        colour = QtGui.QColor(value)
        return colour if colour.isValid() else style.qc("#ffffff")

    def canvas_colour(self) -> str:
        return self.prefs.get("canvas") or self.th()["canvas"]

    def apply_theme(self):
        self.view.set_background(style.qc(self.canvas_colour()))
        self.prefs["theme"] = self.theme
        self._write_prefs()

    def set_canvas(self, colour: str):
        self.prefs["canvas"] = QtGui.QColor(colour).name()
        self.apply_theme()

    def set_paper(self, colour: str):
        self.fmt.paper = colour
        self._apply_paper()
        self.set_ink(self.fmt.ink)           # faded ink fades toward the new paper

    # -- paper stock ---------------------------------------------------------
    def stock(self) -> str:
        """The paper stock in use, if its file is in the papers folder."""
        key = self.fmt.texture
        return key if key and self.fmt.grain > 0 and (papers.folder() / key).is_file() else ""

    def blend_mode(self) -> str:
        return self.fmt.blend if self.fmt.blend in papers.BLENDS else "tooth"

    def paper_stock(self) -> export.Stock:
        """The stock as one render needs it (empty when there is none)."""
        return export.Stock(self.stock(), self.fmt.grain, self.blend_mode(), self.fmt.stock_scale)

    def _apply_paper(self):
        """Tooth: a stock image painted as the page.  A blend: flat paper,
        with the photo blended over everything on it by the stock layer."""
        surface = layer = None
        key, mode = self.stock(), self.blend_mode()
        if key and mode == "tooth":
            sheet = papers.sheet(key, self.sheet.W, self.sheet.H, STOCK_SCREEN_DPI, None,
                                 export.rgb(self.paper()), self.fmt.grain, self.fmt.stock_scale)
            if sheet is not None:
                surface = export.from_rgb(sheet)
        elif key:
            photo = papers.surface(key, self.sheet.W, self.sheet.H, STOCK_SCREEN_DPI, None,
                                   self.fmt.stock_scale, mode)
            if photo is not None:
                layer = export.from_rgb(np.clip(photo * 255.0 + 0.5, 0, 255).astype(np.uint8))
        self._surface, self._stock_layer = surface, layer
        self.sheet.set_paper(self.paper(), surface)
        self.sheet.stock.set(layer, mode, self.fmt.grain / 100.0)
        for ghost in getattr(self, "ghosts", {}).values():
            ghost.update()

    def set_blend(self, mode: str):
        self.fmt.blend = mode if mode in papers.BLENDS else "tooth"
        self._apply_paper()
        self.toast(f"stock blend · {self.fmt.blend}")
        if self.page_panel is not None:
            self.page_panel.refresh()
        self.changed()

    def set_stock_scale(self, value: float):
        self.fmt.stock_scale = max(25.0, min(400.0, value))
        self._apply_paper()
        self.changed()

    def set_texture(self, key: str):
        self.fmt.texture = key
        self._apply_paper()
        self.toast(f"paper stock · {papers.label(key)}" if key else "paper stock · flat")
        if self.page_panel is not None:
            self.page_panel.refresh()
        self.changed()

    def set_grain(self, value: float):
        self.fmt.grain = max(0.0, min(100.0, value))
        self._apply_paper()
        self.changed()

    def stock_labels(self) -> list[str]:
        return ["flat"] + [label for _key, label in papers.available()]

    def stock_label(self) -> str:
        return papers.label(self.fmt.texture) if self.stock() else "flat"

    def set_stock_label(self, label: str):
        keys = {lab: key for key, lab in papers.available()}
        self.set_texture(keys.get(label, ""))

    def block_format(self) -> QtGui.QTextBlockFormat:
        fmt = QtGui.QTextBlockFormat()
        fmt.setLineHeight(self.fmt.line, QtGui.QTextBlockFormat.ProportionalHeight)
        fmt.setBottomMargin(self.fmt.para)
        return fmt

    def face(self) -> str:
        return self.fmt.font if self.fmt.font and style.installed(self.fmt.font) else style.default_face()

    def apply_format(self):
        """Page size, margins, face, paper - none of it in the undo history."""
        w, h = style.PAGE_SIZES.get(self.fmt.page, style.PAGE_SIZES["a4"])
        font = QtGui.QFont(self.face())
        font.setPointSizeF(self.fmt.size)
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setHintingPreference(QtGui.QFont.PreferNoHinting)
        font.setWeight(self.weight())
        undo = self.doc.isUndoRedoEnabled()
        loading, self._loading = self._loading, True
        steps = self.doc.availableUndoSteps()
        self.doc.setDefaultFont(font)
        self.sheet.set_geometry(w, h, self.fmt.margin, self.fmt.head)
        self.sheet.text.setDefaultTextColor(self.ink())
        self._apply_paper()
        self._loading = loading
        # a frame format change can land in Qt's undo stack; keep ours in step
        extra = self.doc.availableUndoSteps() - steps
        if undo and extra > 0:
            for _ in range(extra):
                self.history.append(("text", None))
        self.page = min(self.page, self.sheet.pages())
        self.sheet.set_offset(self.page * self.sheet.H)
        self.restyle_notes()
        self.view.viewport().update()

    def doc_font(self) -> QtGui.QFont:
        return self.doc.defaultFont()

    def restyle_notes(self):
        for thing in self.things.values():
            if isinstance(thing, Note):
                thing.style(self.doc_font(), self.block_format(), self.ink())

    def _format_edit(self, key: str, edit):
        """A layout change that Qt keeps in the words' undo stack (block and
        frame formats).  Repeats of the same change in a row - a slider being
        dragged - join one edit block, so they undo as one step."""
        join = bool(self.history) and self.history[-1] == ("text", key) \
            and self.doc.availableUndoSteps() > 0
        cursor = QtGui.QTextCursor(self.doc)
        if join:
            self._joining = True
            cursor.joinPreviousEditBlock()
        else:
            self._pending_key = key
            cursor.beginEditBlock()
        try:
            edit(cursor)
            cursor.endEditBlock()
        finally:
            self._joining = False
            self._pending_key = None
        self.changed()

    def _merge_blocks(self, fmt: QtGui.QTextBlockFormat):
        def edit(cursor):
            cursor.select(QtGui.QTextCursor.Document)
            cursor.mergeBlockFormat(fmt)
        return edit

    def set_line_height(self, value: float):
        self.fmt.line = value
        fmt = QtGui.QTextBlockFormat()
        fmt.setLineHeight(value, QtGui.QTextBlockFormat.ProportionalHeight)
        self._format_edit("line", self._merge_blocks(fmt))
        self.restyle_notes()
        self.caret_moved(follow=False)

    def set_para(self, value: float):
        self.fmt.para = value
        fmt = QtGui.QTextBlockFormat()
        fmt.setBottomMargin(value)
        self._format_edit("para", self._merge_blocks(fmt))
        self.restyle_notes()
        self.caret_moved(follow=False)

    def set_margins(self, side: float | None = None, head: float | None = None):
        if side is not None:
            self.fmt.margin = side
        if head is not None:
            self.fmt.head = head
        self._format_edit("margin:side" if head is None else "margin:head",
                          lambda cursor: self.sheet.set_margins(self.fmt.margin, self.fmt.head))
        self.caret_moved(follow=False)

    def set_size(self, value: float):
        self.fmt.size = value
        self.apply_format()
        self.changed()

    # -- overlay -------------------------------------------------------------
    def page_rect_view(self) -> QtCore.QRectF:
        return self.view.viewportTransform().mapRect(self.sheet.scene_page_rect())

    def pages_shown(self) -> int:
        return max(self.sheet.pages(), self.page + 1)

    def paint_overlay(self, painter: QtGui.QPainter):
        th = self.th()
        rect = self.page_rect_view()
        transform = self.view.viewportTransform()
        shown = [(self.page, rect)] + [(i, transform.mapRect(g.sceneBoundingRect()))
                                       for i, g in sorted(self.ghosts.items())]
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        if th["edge"]:
            pen = QtGui.QPen(style.qc(th["edge"]), 1.0)
            if th["dotted"]:
                pen.setStyle(QtCore.Qt.CustomDashLine)
                pen.setDashPattern([1.0, 3.0])
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            for _index, box in shown:
                painter.drawRect(box.adjusted(-1, -1, 0, 0))
        over = self.drag.get("over") if self.drag and self.drag.get("mode") == "move" else None
        if over:
            painter.setPen(QtGui.QPen(style.qc(style.INK if self.theme != "night" else "#ffffff"), 2.0))
            painter.drawRect(transform.mapRect(over).adjusted(-3, -3, 2, 2))

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        painter.setFont(style.ui_font(11))
        painter.setPen(style.qc(th["meta"]))
        if self.layout == "single":
            label = f"{self.page + 1:02d} / {self.pages_shown():02d}"
            if self.page >= self.sheet.pages():
                label = f"{self.page + 1:02d} / blank"
            painter.drawText(QtCore.QPointF(rect.left(), rect.bottom() + 20), label)
        else:
            for index, box in shown:
                label = f"{index + 1:02d}" if index < self.sheet.pages() else "blank"
                if index == self.page:
                    label += " ·"
                painter.drawText(QtCore.QPointF(box.left(), box.bottom() + 18), label)
        if self.write_mode:
            tag = f"write · {self.view.zoom() * 100:.0f}%"
            area = QtCore.QRectF(self.view.viewport().rect()).adjusted(18, 0, -18, -16)
            painter.drawText(area, QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom, tag)
        if self.preview is not None:
            tag = f"distress · {self.distress.style}"
            width = QtGui.QFontMetrics(painter.font()).horizontalAdvance(tag)
            painter.drawText(QtCore.QPointF(rect.right() - width, rect.bottom() + 20), tag)

        mark = style.qc(style.INK if self.canvas_is_light() else "#ffffff")
        line = QtGui.QPen(mark, 1.0, QtCore.Qt.CustomDashLine)
        line.setDashPattern([3.0, 3.0])
        for thing in self.selection():
            corners, knob, top = self._handles(thing)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(line)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPolygon(corners)
            painter.setPen(QtGui.QPen(mark, 1.0))
            painter.drawLine(top, knob)
            painter.setPen(QtGui.QPen(style.qc(style.INK), 1.0))
            painter.setBrush(style.qc("#ffffff"))
            painter.drawEllipse(knob, 4.0, 4.0)
            painter.drawRect(self._handle_rect(corners[2]))
        self._paint_live_caret(painter)
        if self.active_tool is not None:
            painter.save()
            self.active_tool.paint(painter, transform)
            painter.restore()
        meta = style.qc(self.th()["meta"])
        for frame in self.plugin_frames():
            if frame.isVisible():
                frame.paint_chrome(painter, transform, meta)
        if self.drag and self.drag.get("mode") == "rotate":
            thing = self.drag["thing"]
            painter.setPen(style.qc(self.th()["meta"]))
            painter.setFont(style.ui_font(11))
            corner = self._handles(thing)[1]
            painter.drawText(corner + QtCore.QPointF(10, -6), f"{thing.rotation() % 360:.0f}°")

    def _paint_live_caret(self, painter: QtGui.QPainter):
        """Over the live distress view the real words are hidden, so the
        caret and the selection are drawn here, on top."""
        if self.preview is None or not self.live():
            return
        if abs(self.sheet.offset - self.page * self.sheet.H) > 0.5:
            return
        focus = self.scene.focusItem()
        if focus is self.sheet.text:
            editor = focus
        elif isinstance(focus, NoteText) and self.editing is focus.note:
            editor = focus
        else:
            return
        doc, layout = editor.document(), editor.document().documentLayout()
        cursor = editor.textCursor()
        transform = self.view.viewportTransform()
        page = self.sheet.scene_page_rect()

        def to_view(rect: QtCore.QRectF) -> QtGui.QPolygonF:
            return transform.map(editor.mapToScene(rect))

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setClipRect(transform.mapRect(page) if editor.note_pinned() else
                            QtCore.QRectF(self.view.viewport().rect()))
        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            shade = QtGui.QColor(style.INK)
            shade.setAlpha(55)
            block = doc.findBlock(start)
            while block.isValid() and block.position() <= end:
                origin = layout.blockBoundingRect(block).topLeft()
                lines = block.layout()
                for i in range(lines.lineCount()):
                    line = lines.lineAt(i)
                    a = max(start, block.position() + line.textStart())
                    b = min(end, block.position() + line.textStart() + line.textLength())
                    if b < a:
                        continue
                    x0 = line.cursorToX(a - block.position())[0]
                    x1 = line.cursorToX(b - block.position())[0]
                    if b == block.position() + line.textStart() + line.textLength() and b < end:
                        x1 += 4                     # the line break is chosen too
                    rect = QtCore.QRectF(origin.x() + x0, origin.y() + line.y(),
                                         max(1.0, x1 - x0), line.height())
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(shade)
                    painter.drawPolygon(to_view(rect))
                block = block.next()
        block = cursor.block()
        origin = layout.blockBoundingRect(block).topLeft()
        lines = block.layout()
        if lines is not None and lines.lineCount():
            line = lines.lineForTextPosition(cursor.positionInBlock())
            if not line.isValid():
                line = lines.lineAt(lines.lineCount() - 1)
            x = origin.x() + line.cursorToX(cursor.positionInBlock())[0]
            y, height = origin.y() + line.y(), line.height()
        else:
            x, y = origin.x(), origin.y()
            height = QtGui.QFontMetricsF(doc.defaultFont()).height()
        caret = to_view(QtCore.QRectF(x, y, 0.0, height))
        painter.setPen(QtGui.QPen(self.ink(), max(1.5, 1.2 * self.view.zoom())))
        painter.drawLine(caret[0], caret[3])
        painter.restore()

    def paint_toast(self, painter: QtGui.QPainter, text: str):
        painter.setFont(style.ui_font(11))
        painter.setPen(style.qc(self.th()["meta"]))
        area = QtCore.QRectF(self.view.viewport().rect()).adjusted(18, 0, -18, -16)
        painter.drawText(area, QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom, text)

    def _handle_rect(self, corner: QtCore.QPointF) -> QtCore.QRectF:
        s = HANDLE_PX
        return QtCore.QRectF(corner.x() - s / 2, corner.y() - s / 2, s, s)

    def _handles(self, thing: Thing):
        """In view pixels: the turned outline, the rotation knob, and the
        middle of the top edge it hangs from."""
        transform = self.view.viewportTransform()
        corners = transform.map(thing.outline())
        top = (corners[0] + corners[1]) / 2
        middle = (corners[0] + corners[2]) / 2
        up = top - middle
        length = math.hypot(up.x(), up.y()) or 1.0
        knob = top + up * (KNOB_PX / length)
        return corners, knob, top

    def canvas_is_light(self) -> bool:
        return QtGui.QColor(self.canvas_colour()).lightness() > 110

    def toast(self, text: str):
        self.view.toast(text)

    # -- selection -----------------------------------------------------------
    def selection(self) -> list[Thing]:
        return [i for i in self.scene.selectedItems() if isinstance(i, Thing) and i.alive]

    def clear_selection(self):
        if self.scene.selectedItems():
            self.scene.clearSelection()
            self.view.viewport().update()

    def select(self, things: list[Thing]):
        self.scene.clearSelection()
        for thing in things:
            thing.setSelected(True)
        if things:
            self.sheet.text.clearFocus()
        self.view.viewport().update()

    def typing(self) -> bool:
        return not self.selection()

    def focus_text(self):
        if not self.view.hasFocus():
            self.view.setFocus(QtCore.Qt.OtherFocusReason)
        if self.scene.focusItem() is not self.sheet.text:
            self.scene.setFocusItem(self.sheet.text, QtCore.Qt.OtherFocusReason)
        self.sheet.text.setFocus()

    def thing_at(self, scene_pos: QtCore.QPointF, behind: bool = False) -> Thing | None:
        page = self.sheet.scene_page_rect()
        for item in self.scene.items(scene_pos):
            if isinstance(item, NoteText):
                item = item.note
            if not isinstance(item, Thing) or not item.alive:
                continue
            if item.pinned:
                if not page.contains(scene_pos):
                    continue
                if item.zValue() < 0 and not behind:
                    continue                # behind the words: Alt+click reaches it
            return item
        return None

    def handle_at(self, view_pos: QtCore.QPointF) -> tuple[Thing, str] | None:
        """(thing, "scale" | "rotate") under the pointer, for a selected thing."""
        for thing in self.selection():
            corners, knob, _top = self._handles(thing)
            if math.hypot(view_pos.x() - knob.x(), view_pos.y() - knob.y()) <= 8:
                return thing, "rotate"
            if self._handle_rect(corners[2]).adjusted(-5, -5, 5, 5).contains(view_pos):
                return thing, "scale"
        return None

    def use_tool(self, tool):
        """Make a plugin's canvas tool active (None: back to writing)."""
        if self.active_tool is not None and self.active_tool is not tool:
            self.active_tool.leave()
        self.active_tool = tool
        if tool is not None:
            if self.editing is not None:
                self.finish_editing()
            self.sheet.text.clearFocus()
            self.toast(f"{tool.name} · Esc to stop")
        else:
            self.focus_text()
        self.update_cursor()
        self.view.viewport().update()

    def plugin_frames(self) -> list:
        return [frame for _p, host in getattr(self, "plugins", []) for frame in host.frames]

    def frame_at(self, view_pos: QtCore.QPointF):
        """(frame, part) of the topmost shown plugin frame under the pointer."""
        transform = self.view.viewportTransform()
        for frame in sorted((f for f in self.plugin_frames() if f.isVisible()),
                            key=lambda f: -f.zValue()):
            part = frame.part_at(view_pos, transform)
            if part:
                return frame, part
        return None

    def place_qimage(self, image: QtGui.QImage, rect: QtCore.QRectF, name: str,
                     push: bool = True) -> Thing:
        """A picture made by a plugin, as an image on the canvas at `rect`
        (pinned if its middle is on a shown page).  One undo step."""
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        thing = Thing(image, rect.size(), bytes(data), ".png", None, name)
        before = self.snapshot()
        self.things[thing.uid] = thing
        self.scene.addItem(thing)
        thing.setPos(rect.topLeft())
        thing.setZValue(self.top_z() + 1.0)
        if self.live_on(rect.center()):
            self.pin(thing)
        if push:
            self.push("things", before)
            self.changed()
        return thing

    def pin(self, thing: Thing):
        if thing.pinned:
            return
        at = thing.scenePos()
        thing.setParentItem(self.sheet.strip)
        thing.setPos(self.sheet.strip.mapFromScene(at))
        front = [t.zValue() for t in self.sheet.pinned() if t is not thing and t.zValue() >= 0]
        thing.setZValue(max(front, default=0.0) + 1.0)

    def unpin(self, thing: Thing):
        if not thing.pinned:
            return
        at = thing.scenePos()
        thing.setParentItem(None)
        thing.setPos(at)

    def top_z(self) -> float:
        return max((t.zValue() for t in self.things.values() if t.alive and not t.pinned),
                   default=0.0)

    # -- mouse ---------------------------------------------------------------
    def press(self, event: QtGui.QMouseEvent) -> bool:
        self._stale()
        if event.button() != QtCore.Qt.LeftButton:
            return event.button() == QtCore.Qt.RightButton
        pos = event.localPos()
        at = self.view.mapToScene(pos.toPoint())
        mods = event.modifiers()
        if self.active_tool is not None:
            if self.editing is not None:
                self.finish_editing()
            if self.active_tool.press(at, mods):
                self.drag = {"mode": "tool"}
                self.view.viewport().update()
                return True
        if self.editing is not None:
            if self._inside(self.editing, at):
                return False                # the note's editor places the caret
            self.finish_editing()
        hit = self.frame_at(pos)
        if hit is not None:
            frame, part = hit
            if part in ("move", "resize"):
                self.drag = {"mode": "frame-" + part, "frame": frame, "start": at,
                             "from": QtCore.QPointF(frame.pos()), "w": frame.w, "h": frame.h}
                return True
            if part == "inside" and frame.drag_out is not None:
                image = frame.drag_out(at)
                if image is not None and not image.isNull():
                    # pick the picture up: a new image under the pointer, being carried
                    self.clear_selection()
                    thing = self.place_qimage(image, frame.scene_rect(), frame.label)
                    self.select([thing])
                    self.drag = {"mode": "press", "lead": thing, "start": at, "press": pos,
                                 "before": self.snapshot()}
                    return True
        if mods & QtCore.Qt.ControlModifier:
            # Cmd+click: write from here, over whatever is there
            hit = self.thing_at(at)
            if isinstance(hit, Note):
                self.start_editing(hit, at)
                return True
            self.new_note(at)
            return True
        grabbed = self.handle_at(pos)
        if grabbed is not None:
            thing, kind = grabbed
            centre = thing.mapToScene(thing.transformOriginPoint())
            self.drag = {"mode": kind, "thing": thing, "before": self.snapshot(),
                         "w": thing.w, "h": thing.h, "centre": centre,
                         "reach": max(1e-6, math.hypot(at.x() - centre.x(), at.y() - centre.y())),
                         "angle": math.degrees(math.atan2(at.y() - centre.y(), at.x() - centre.x())),
                         "rotation": thing.rotation()}
            return True
        thing = self.thing_at(at, behind=bool(mods & QtCore.Qt.AltModifier))
        if thing is not None:
            if mods & QtCore.Qt.ShiftModifier:
                thing.setSelected(not thing.isSelected())
            elif not thing.isSelected():
                self.select([thing])
            self.sheet.text.clearFocus()
            self.drag = {"mode": "press", "lead": thing, "start": at, "press": pos,
                         "before": self.snapshot(),
                         "copy": bool(mods & QtCore.Qt.AltModifier)}
            self.view.viewport().update()
            return True
        self.clear_selection()
        self.live_on(at)                    # a click on another shown page makes it live
        page = self.sheet.scene_page_rect()
        if page.contains(at):
            y = at.y() - page.top() + self.page * self.sheet.H
            if y >= self.sheet.text_pages() * self.sheet.H:
                self.write_on(int(y // self.sheet.H))
                return True
            self.focus_text()
            return False                    # the text editor places the caret
        self.view.start_pan(pos)
        return True

    def move(self, event: QtGui.QMouseEvent) -> bool:
        pos = event.localPos()
        at = self.view.mapToScene(pos.toPoint())
        drag = self.drag
        if drag is None:
            self._hover_cursor(pos, at)
            return True
        if drag["mode"] == "tool":
            self.active_tool.move(at, event.modifiers())
            self.view.viewport().update()
            return True
        if drag["mode"] in ("frame-move", "frame-resize"):
            frame, delta = drag["frame"], at - drag["start"]
            if drag["mode"] == "frame-move":
                frame.setPos(drag["from"] + delta)
            else:
                frame.set_size(drag["w"] + delta.x(), drag["h"] + delta.y())
            frame.changed()
            self.view.viewport().update()
            return True
        if drag["mode"] == "press":
            if (pos - drag["press"]).manhattanLength() < 3:
                return True
            drag["mode"] = "move"
            drag["things"] = self.selection() or [drag["lead"]]
            if drag.get("copy"):
                # Alt+drag carries copies and leaves the originals where they were
                copies = [self.duplicate(t, QtCore.QPointF(0, 0)) for t in drag["things"]]
                lead = drag["things"].index(drag["lead"]) if drag["lead"] in drag["things"] else 0
                drag["things"], drag["lead"] = copies, copies[lead]
                self.select(copies)
            for n, thing in enumerate(drag["things"]):
                self.unpin(thing)
                thing.setZValue(100000.0 + n)   # above everything while carried
            drag["from"] = [t.pos() for t in drag["things"]]
        if drag["mode"] == "move":
            delta = at - drag["start"]
            for thing, origin in zip(drag["things"], drag["from"]):
                thing.setPos(origin + delta)
            lead = drag["lead"]
            drag["over"] = self.page_rect_at(lead.sceneBoundingRect().center())
        elif drag["mode"] == "scale" and isinstance(drag["thing"], Note):
            note = drag["thing"]
            note.set_width(note.mapFromScene(at).x())
        elif drag["mode"] == "scale":
            thing, centre = drag["thing"], drag["centre"]
            factor = max(0.02, math.hypot(at.x() - centre.x(), at.y() - centre.y()) / drag["reach"])
            thing.resize(drag["w"] * factor, drag["h"] * factor)
        elif drag["mode"] == "rotate":
            thing, centre = drag["thing"], drag["centre"]
            angle = math.degrees(math.atan2(at.y() - centre.y(), at.x() - centre.x()))
            turned = drag["rotation"] + angle - drag["angle"]
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                turned = round(turned / 15.0) * 15.0
            thing.setRotation(turned % 360.0)
        self.view.viewport().update()
        return True

    def release(self, event: QtGui.QMouseEvent):
        drag, self.drag = self.drag, None
        if drag is None:
            return
        if drag["mode"] == "tool":
            if self.active_tool is not None:
                at = self.view.mapToScene(event.pos())
                self.active_tool.release(at, event.modifiers())
            self.view.viewport().update()
            return
        if drag["mode"] in ("frame-move", "frame-resize"):
            drag["frame"].changed()
            self.view.viewport().update()
            return
        if drag["mode"] == "move":
            carried = drag["things"]
            z = max((t.zValue() for t in self.things.values()
                     if t.alive and not t.pinned and t not in carried), default=0.0)
            for thing in carried:
                z += 1.0
                thing.setZValue(z)
                if self.live_on(thing.sceneBoundingRect().center()):
                    self.pin(thing)
            self.push("things", drag["before"])
            self.changed()
        elif drag["mode"] in ("scale", "rotate"):
            self.push("things", drag["before"])
            self.changed()
        self.view.viewport().update()

    def double_click(self, event: QtGui.QMouseEvent) -> bool:
        at = self.view.mapToScene(event.pos())
        hit = self.thing_at(at)
        if isinstance(hit, Note):
            if self.editing is not hit:
                self.start_editing(hit, at)
                return True
            return False                    # already writing: selects a word
        if hit is not None:
            return True
        if self.sheet.scene_page_rect().contains(at):
            return False                    # selects a word
        self.browse_files(at)
        return True

    def _hover_cursor(self, pos: QtCore.QPointF, at: QtCore.QPointF):
        viewport = self.view.viewport()
        framed = self.frame_at(pos)
        if self.active_tool is not None and not self.view.space_down:
            self.active_tool.hover(at)
            viewport.setCursor(self.active_tool.cursor)
            self.view.viewport().update()
            return
        if self.view.space_down:
            viewport.setCursor(QtCore.Qt.OpenHandCursor)
        elif framed is not None and framed[1] != "inside":
            viewport.setCursor(QtCore.Qt.SizeFDiagCursor if framed[1] == "resize"
                               else QtCore.Qt.SizeAllCursor)
        elif framed is not None and framed[0].drag_out is not None:
            viewport.setCursor(QtCore.Qt.OpenHandCursor)
        elif self.editing is not None and self._inside(self.editing, at):
            viewport.setCursor(QtCore.Qt.IBeamCursor)
        elif self.handle_at(pos) is not None:
            kind = self.handle_at(pos)[1]
            viewport.setCursor(QtCore.Qt.SizeFDiagCursor if kind == "scale"
                               else QtCore.Qt.CrossCursor)
        elif self.thing_at(at) is not None:
            viewport.setCursor(QtCore.Qt.SizeAllCursor)
        elif self.sheet.scene_page_rect().contains(at):
            viewport.setCursor(QtCore.Qt.IBeamCursor)
        else:
            viewport.setCursor(QtCore.Qt.ArrowCursor)

    def update_cursor(self):
        pos = QtCore.QPointF(self.view.mapFromGlobal(QtGui.QCursor.pos()))
        self._hover_cursor(pos, self.view.mapToScene(pos.toPoint()))

    # -- layouts: one page, a spread, all pages --------------------------------
    def spread_of(self, index: int) -> tuple[int, int | None]:
        """(left, right) of the spread holding `index`, as in a book: the
        first page alone on the right, then 2|3, 4|5 ... (zero-based: 0, then
        1|2, 3|4).  -1 on the left means no page there."""
        if index == 0:
            return -1, 0
        left = index if index % 2 == 1 else index - 1
        return left, left + 1

    def visible_pages(self) -> list[int]:
        if self.layout == "spread":
            left, right = self.spread_of(self.page)
            last = self.sheet.pages()               # the blank page after the words
            return [i for i in (left, right) if 0 <= i <= last]
        if self.layout == "all":
            return list(range(max(self.sheet.pages(), self.page + 1)))
        return [self.page]

    def slot(self, index: int) -> QtCore.QPointF:
        """Where page `index` sits on the canvas in the current layout."""
        w, h = self.sheet.W, self.sheet.H
        if self.layout == "spread":
            return QtCore.QPointF(0.0 if index % 2 == 0 else -w, 0.0)   # spine at x = 0
        if self.layout == "all":
            cols = max(1, self._grid_cols)
            gap_x, gap_y = w * GRID_GAP_X, h * GRID_GAP_Y   # room for the page numbers
            return QtCore.QPointF((index % cols) * (w + gap_x), (index // cols) * (h + gap_y))
        return QtCore.QPointF(0.0, 0.0)

    def layout_rect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF()
        for index in self.visible_pages():
            rect = rect.united(QtCore.QRectF(self.slot(index),
                                             QtCore.QSizeF(self.sheet.W, self.sheet.H)))
        return rect

    def _place_sheet(self):
        """Put the live page in its slot and draw the others round it."""
        self.anim.stop()
        self.sheet.setPos(self.slot(self.page))
        self.sheet.set_offset(self.page * self.sheet.H)
        wanted = {i for i in self.visible_pages() if i != self.page}
        for index in list(self.ghosts):
            if index not in wanted:
                self.scene.removeItem(self.ghosts.pop(index))
        for index in wanted:
            ghost = self.ghosts.get(index)
            if ghost is None:
                ghost = self.ghosts[index] = GhostPage(self, index)
                self.scene.addItem(ghost)
            ghost.prepareGeometryChange()
            ghost.setPos(self.slot(index))
            ghost.update()
        self.view.viewport().update()

    def _refresh_ghosts(self):
        if self.layout == "single":
            return
        if set(self.ghosts) | {self.page} != set(self.visible_pages()):
            self._place_sheet()
        for ghost in self.ghosts.values():
            ghost.update()
        if self.live():
            self._render_ghosts()

    def set_layout(self, layout: str):
        """⌘1 one page, ⌘2 a spread, ⌘3 all pages; asking for the layout
        you are in goes back to one page."""
        if layout == self.layout and layout != "single":
            layout = "single"
        self.layout = layout
        self.prefs["layout"] = layout
        self._write_prefs()
        self._update_grid()
        if self.editing is not None:
            self.finish_editing()
        self._drop_overlay()
        self._place_sheet()
        self.view.frame(self.layout_rect(), margin=48)
        self.toast({"single": "one page", "spread": "spread", "all": "all pages"}[layout])
        if self.live():
            self.request_preview()
            self._render_ghosts()
        self.focus_text()

    def _update_grid(self):
        """Columns for the all-pages view, so the grid roughly fills the window."""
        n = max(self.sheet.pages(), 1)
        size = self.view.viewport().size()
        aspect = (size.width() / max(1, size.height())) * (self.sheet.H / self.sheet.W)
        self._grid_cols = max(1, min(n, round(math.sqrt(n * aspect)) or 1))

    def ghost_at(self, at: QtCore.QPointF) -> GhostPage | None:
        for ghost in self.ghosts.values():
            if ghost.sceneBoundingRect().contains(at):
                return ghost
        return None

    def page_rect_at(self, at: QtCore.QPointF) -> QtCore.QRectF | None:
        """The rect of whichever shown page is under `at`."""
        if self.sheet.scene_page_rect().contains(at):
            return self.sheet.scene_page_rect()
        ghost = self.ghost_at(at)
        return ghost.sceneBoundingRect() if ghost else None

    def make_live(self, index: int):
        """Make a page shown beside the live one the live one."""
        if index == self.page:
            return
        self.page = index
        self._drop_overlay()
        self._place_sheet()
        if self.live():
            self.request_preview()
            self._render_ghosts()

    def live_on(self, at: QtCore.QPointF) -> bool:
        """If `at` is over a shown page, make that page live; True if so."""
        ghost = self.ghost_at(at)
        if ghost is not None:
            self.make_live(ghost.index)
        return self.sheet.scene_page_rect().contains(at)

    def paint_ghost(self, painter: QtGui.QPainter, ghost: GhostPage):
        rect = ghost.boundingRect()
        if getattr(self, "_surface", None) is not None:
            painter.drawImage(rect, self._surface)
        else:
            painter.fillRect(rect, self.paper())
        layer = getattr(self, "_stock_layer", None)
        if ghost.index >= self.sheet.pages():
            if layer is not None:
                draw_stock(painter, rect, layer, self.blend_mode(), self.fmt.grain / 100.0)
            return                                  # the blank page after the words
        if self.live() and ghost.distressed is not None and ghost.distressed[0] == self._ghost_key(ghost.index):
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            painter.drawImage(rect, ghost.distressed[1])    # the blend is in it already
            return
        export.draw_page(painter, self.sheet, ghost.index, self.ink())
        if layer is not None:
            draw_stock(painter, rect, layer, self.blend_mode(), self.fmt.grain / 100.0)

    def _ghost_key(self, index: int) -> tuple:
        return (index, self.doc.revision(), self.things_key(),
                tuple(asdict(self.fmt).items()), tuple(self.distress.to_dict().items()),
                tuple(t.text() for t in self.things.values() if isinstance(t, Note) and t.alive))

    def _render_ghosts(self):
        """In distress view the pages beside the live one are distressed too,
        a little softer, on the worker thread - the ones in sight only."""
        seen = self.view.visible_scene_rect()
        ratio = self.view.devicePixelRatioF() if hasattr(self.view, "devicePixelRatioF") else 1.0
        dpi = max(60.0, min(200.0, 72.0 * self.view.zoom() * ratio))
        settings = replace(self.distress, enabled=True)
        paper, density = export.rgb(self.paper()), self.density()
        paper_stock, paper_colour = self.paper_stock(), self.paper()
        for index, ghost in self.ghosts.items():
            if index >= self.sheet.pages() or not ghost.sceneBoundingRect().intersects(seen):
                continue
            key = self._ghost_key(index)
            if ghost.distressed is not None and ghost.distressed[0] == key:
                continue
            layer = export.page_layers(self.sheet, index, dpi, self.ink())

            def work(index=index, key=key, layer=layer):
                try:
                    base = export.stock(self.sheet, dpi, None, paper_colour, paper_stock)
                    out = distress.compose(layer, paper, settings, dpi, density=density, base=base,
                                           over=export.over(self.sheet, dpi, None, paper_stock))
                except Exception as exc:
                    print("ream: page preview failed:", exc, file=sys.stderr)
                    return
                self.ghost_ready.emit(index, key, out)
            self._pool.submit(work)

    def _ghost_arrived(self, index: int, key, out):
        ghost = self.ghosts.get(index)
        if ghost is not None and key == self._ghost_key(index):
            ghost.distressed = (key, export.from_rgb(out))
            ghost.update()

    # -- turning pages -------------------------------------------------------
    def turn_page(self, delta: int):
        """Cmd+Left / Cmd+Right: the previous or next page, with the caret
        moved to its first line so writing carries on there.  Past the last
        page waits a blank one; click it to start writing on it."""
        if self.layout == "spread":
            left, _right = self.spread_of(self.page)
            target = (left + 2 if left > 0 else 1) if delta > 0 else (left - 2 if left > 1 else 0)
        else:
            target = self.page + delta
        target = max(0, min(target, self.sheet.pages()))
        if target == self.page:
            return
        if self.editing is not None:
            self.finish_editing()
        self.clear_selection()
        self.flip(target, reveal="top")
        if target < self.sheet.text_pages():
            self._caret_to_page(target)

    def _caret_to_page(self, index: int):
        layout = self.doc.documentLayout()
        top_of_page = index * self.sheet.H
        block = self.doc.begin()
        while block.isValid():
            top = layout.blockBoundingRect(block).top()
            lines = block.layout()
            for i in range(lines.lineCount()):
                line = lines.lineAt(i)
                if top + line.y() + line.height() / 2 >= top_of_page:
                    cursor = QtGui.QTextCursor(self.doc)
                    cursor.setPosition(block.position() + line.textStart())
                    self.sheet.text.setTextCursor(cursor)
                    self.focus_text()
                    self.view.viewport().update()
                    return
            block = block.next()

    def flip(self, target: int, reveal: str | None = None):
        """Slide the strip to page `target`; `reveal` pans the view so the
        head ("top") or foot ("bottom") of the page is in sight."""
        target = max(0, min(int(target), self.sheet.pages()))
        self._drop_overlay()
        if self.layout != "single":
            self.page = target
            self._place_sheet()
            page = self.sheet.scene_page_rect()
            seen = self.view.visible_scene_rect()
            if not seen.contains(page):
                margin = REVEAL_PX / self.view.zoom()
                head = QtCore.QRectF(page.left(), page.top(), page.width(),
                                     min(page.height(), seen.height()))
                self.view.ensureVisible(head if reveal != "bottom" else page, int(margin), int(margin))
                self.view_changed()
            if self.live():
                self.request_preview()
                self._render_ghosts()
            return
        pan = 0.0
        if reveal:
            zoom = self.view.zoom()
            seen, page = self.view.visible_scene_rect(), self.sheet.scene_page_rect()
            margin = REVEAL_PX / zoom
            if reveal == "top" and seen.top() > page.top() - margin:
                pan = (seen.top() - (page.top() - margin)) * zoom
            elif reveal == "bottom" and seen.bottom() < page.bottom() + margin:
                pan = -((page.bottom() + margin) - seen.bottom()) * zoom
        self.page = target
        self.anim.stop()
        self._flip = {"from": self.sheet.offset, "to": target * self.sheet.H,
                      "pan": pan, "panned": 0.0}
        self.anim.start()
        self.view.viewport().update()
        if self.live():
            QtCore.QTimer.singleShot(self.anim.duration() + 20, self._refresh_live_preview)
        else:
            self.hide_preview()

    def _animate(self, t):
        t = float(t)
        f = self._flip
        self.sheet.set_offset(f["from"] + (f["to"] - f["from"]) * t)
        step = f["pan"] * t - f["panned"]
        if step:
            self.view.pan_pixels(0, step)
            f["panned"] += step
        self.view.viewport().update()

    def caret_moved(self, follow: bool = True):
        if self._loading:
            return
        page = self.sheet.caret_page()
        if page != self.page:
            self.flip(page)
        if follow:
            if self.write_mode:
                self._write_follow()
            else:
                self.keep_caret_in_view()
        self.view.viewport().update()

    # -- write mode ----------------------------------------------------------
    def write_zoom(self) -> float:
        return float(self.prefs.get("write_zoom", WRITE_ZOOM))

    def toggle_write_mode(self):
        if self.write_mode:
            self.leave_write_mode()
        else:
            self.enter_write_mode()

    def enter_write_mode(self):
        """Zoom to the writing zoom, centre the page, put the caret's line a
        little above the middle; from then on the view follows the writing."""
        if self.write_mode:
            return
        # the exact view, scroll positions and all, so leaving puts it back to the pixel
        self._before_write = (QtGui.QTransform(self.view.transform()),
                              self.view.horizontalScrollBar().value(),
                              self.view.verticalScrollBar().value())
        self.write_mode = True
        self.view.set_zoom(self.write_zoom())
        self._write_follow(force=True, animate=False)
        if self.editing is None:
            self.focus_text()
        self.toast(f"write mode · {self.write_zoom() * 100:.0f}% · ⇧⌘F or Esc to leave")

    def leave_write_mode(self):
        if not self.write_mode:
            return
        self.write_mode = False
        self._follow_anim.stop()
        if self._before_write is not None:
            transform, h, v = self._before_write
            self.view.setTransform(transform)
            self.view.horizontalScrollBar().setValue(h)
            self.view.verticalScrollBar().setValue(v)
            self.view_changed()
        self.toast("write mode off")
        self.view.viewport().update()

    def set_write_zoom(self, zoom: float):
        """The writing zoom, as a factor (1.75 is 175%); remembered."""
        zoom = max(0.5, min(6.0, zoom))
        self.prefs["write_zoom"] = round(zoom, 3)
        self._write_prefs()
        if self.write_mode:
            self.view.set_zoom(zoom)
            self._write_follow(force=True, animate=False)
        self.toast(f"write zoom {zoom * 100:.0f}%")

    def zoom_step(self, factor: float):
        """⌘= / ⌘-: in write mode these set the writing zoom."""
        if self.write_mode:
            self.set_write_zoom(self.view.zoom() * factor)
        else:
            self.view.zoom_by(factor)

    def _caret_scene(self) -> QtCore.QPointF:
        """The middle of the caret's line, in scene coordinates."""
        if self.editing is not None:
            editor = self.editing.editor
            cursor = editor.textCursor()
            block = cursor.block()
            layout = editor.document().documentLayout()
            origin = layout.blockBoundingRect(block).topLeft()
            lines = block.layout()
            y = origin.y()
            if lines is not None and lines.lineCount():
                line = lines.lineForTextPosition(cursor.positionInBlock())
                if line.isValid():
                    y += line.y() + line.height() / 2
            return editor.mapToScene(QtCore.QPointF(origin.x(), y))
        top, bottom = self.sheet.caret_span()
        page = self.sheet.scene_page_rect()
        return QtCore.QPointF(page.center().x(),
                              page.top() + (top + bottom) / 2 - self.page * self.sheet.H)

    def _write_follow(self, force: bool = False, animate: bool = True):
        """Keep the page centred across, and the line being written inside
        the band: past it, glide so the line sits a little above the middle."""
        seen = self.view.visible_scene_rect()
        caret = self._caret_scene()
        page = self.sheet.scene_page_rect()
        centre = self.view.mapToScene(self.view.viewport().rect().center())
        target = QtCore.QPointF(page.center().x(), centre.y())
        where = (caret.y() - seen.top()) / max(1e-6, seen.height())
        if force or where > WRITE_HIGH or where < WRITE_LOW:
            target.setY(caret.y() + (0.5 - WRITE_LINE) * seen.height())
        if (target - centre).manhattanLength() < 0.5:
            return
        self._follow_anim.stop()
        if not animate:
            self.view.centerOn(target)
            self.view_changed()
            return
        self._follow_anim.setStartValue(QtCore.QPointF(centre))
        self._follow_anim.setEndValue(target)
        self._follow_anim.start()

    def _follow_step(self, point):
        self.view.centerOn(point)
        self.view_changed()
        self.view.viewport().update()

    def keep_caret_in_view(self):
        top, bottom = self.sheet.caret_span()
        page = self.sheet.scene_page_rect()
        shift = self.page * self.sheet.H
        y0, y1 = page.top() + top - shift, page.top() + bottom - shift
        zoom = self.view.zoom()
        seen = self.view.visible_scene_rect()
        margin = 70 / zoom
        if y1 + margin > seen.bottom():
            self.view.pan_pixels(0, -(y1 + margin - seen.bottom()) * zoom)
        elif y0 - margin < seen.top():
            self.view.pan_pixels(0, (seen.top() - (y0 - margin)) * zoom)

    def write_on(self, index: int):
        """A click on a page past the words: break pages until the caret is
        on it."""
        breaks = min(500, index - self.sheet.text_pages() + 1)
        cursor = QtGui.QTextCursor(self.doc)
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.beginEditBlock()             # (no layout happens inside one)
        for _ in range(max(0, breaks)):
            fmt = self.block_format()
            fmt.setPageBreakPolicy(QtGui.QTextFormat.PageBreak_AlwaysBefore)
            cursor.insertBlock(fmt)
        cursor.endEditBlock()
        self.sheet.text.setTextCursor(cursor)
        self.focus_text()
        self.caret_moved()

    def new_page(self):
        self.clear_selection()
        cursor = self.sheet.text.textCursor()
        fmt = QtGui.QTextBlockFormat(cursor.blockFormat())
        fmt.setPageBreakPolicy(QtGui.QTextFormat.PageBreak_AlwaysBefore)
        cursor.insertBlock(fmt)
        self.sheet.text.setTextCursor(cursor)
        self.focus_text()
        self.caret_moved()

    # -- keys ----------------------------------------------------------------
    def key(self, event: QtGui.QKeyEvent) -> bool:
        key, mods = event.key(), event.modifiers()
        if key in (QtCore.Qt.Key_Shift, QtCore.Qt.Key_Control, QtCore.Qt.Key_Alt,
                   QtCore.Qt.Key_Meta, QtCore.Qt.Key_CapsLock, QtCore.Qt.Key_AltGr):
            return True                     # a modifier alone is not typing: keep the selection
        self._stale()
        if self.active_tool is not None and self.editing is None:
            if self.active_tool.key(event):
                self.view.viewport().update()
                return True
            if key == QtCore.Qt.Key_Escape:
                self.use_tool(None)
                return True
        if (mods & QtCore.Qt.ControlModifier and not mods & QtCore.Qt.ShiftModifier
                and key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right)):
            self.turn_page(1 if key == QtCore.Qt.Key_Right else -1)
            return True
        if self.editing is not None:
            if key == QtCore.Qt.Key_Escape:
                self.finish_editing()
                self.focus_text()
                return True
            if event.matches(QtGui.QKeySequence.Undo):
                self.undo()
                return True
            if event.matches(QtGui.QKeySequence.Redo):
                self.redo()
                return True
            if event.matches(QtGui.QKeySequence.Paste):
                text = QtWidgets.QApplication.clipboard().text()
                if text:
                    self.editing.editor.textCursor().insertText(text.replace("\r\n", "\n"))
                    self.editing.fit()
                return True
            return False                    # to the note's editor
        if event.matches(QtGui.QKeySequence.Undo):
            self.undo()
            return True
        if event.matches(QtGui.QKeySequence.Redo):
            self.redo()
            return True
        if event.matches(QtGui.QKeySequence.Paste):
            return self.paste()
        chosen = self.selection()
        if chosen:
            if key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
                self.delete_selection()
                return True
            if event.matches(QtGui.QKeySequence.Copy):
                self.copy_selection()
                return True
            if event.matches(QtGui.QKeySequence.Cut):
                self.copy_selection()
                self.delete_selection()
                return True
            arrows = {QtCore.Qt.Key_Left: (-1, 0), QtCore.Qt.Key_Right: (1, 0),
                      QtCore.Qt.Key_Up: (0, -1), QtCore.Qt.Key_Down: (0, 1)}
            if key in arrows:
                step = 10.0 if mods & QtCore.Qt.ShiftModifier else 1.0
                dx, dy = arrows[key]
                before = self.snapshot()
                for thing in chosen:
                    thing.moveBy(dx * step, dy * step)
                self.push("things", before)
                self.changed()
                self.view.viewport().update()
                return True
            if mods & QtCore.Qt.ControlModifier and key in (
                    QtCore.Qt.Key_BracketLeft, QtCore.Qt.Key_BracketRight,
                    QtCore.Qt.Key_BraceLeft, QtCore.Qt.Key_BraceRight):
                ahead = key in (QtCore.Qt.Key_BracketRight, QtCore.Qt.Key_BraceRight)
                if mods & QtCore.Qt.ShiftModifier or key in (QtCore.Qt.Key_BraceLeft,
                                                              QtCore.Qt.Key_BraceRight):
                    self.restack("front" if ahead else "back")
                else:
                    self.restack("forward" if ahead else "backward")
                return True
            if key in (QtCore.Qt.Key_BracketLeft, QtCore.Qt.Key_BracketRight):
                step = 1.0 if mods & QtCore.Qt.ShiftModifier else 15.0
                self.rotate_selected(step if key == QtCore.Qt.Key_BracketRight else -step)
                return True
            if key == QtCore.Qt.Key_Escape:
                self.clear_selection()
                self.focus_text()
                return True
            if mods & QtCore.Qt.ControlModifier:
                return True                 # no word to apply it to
            self.clear_selection()          # typing goes back to the words
        if key == QtCore.Qt.Key_Escape:
            if self.write_mode:
                self.leave_write_mode()
            return True
        self.focus_text()
        return False

    # -- history -------------------------------------------------------------
    def snapshot(self) -> dict:
        return {uid: (t.alive, t.pinned, t.pos().x(), t.pos().y(), t.w, t.h, t.zValue(),
                      t.rotation(), (t.original, t.mask, t.matte, t.border, t.flip))
                for uid, t in self.things.items()}

    def things_key(self) -> tuple:
        """Where and what every thing is, for caches (snapshot() holds arrays)."""
        return tuple(sorted(t.key() for t in self.things.values()))

    def restore(self, snap: dict):
        for uid, thing in self.things.items():
            alive, pinned, x, y, w, h, z, turn, pixels = snap.get(
                uid, (False, False, 0, 0, thing.w, thing.h, 0, 0, None))
            if not alive:
                if thing.scene() is not None:
                    thing.setSelected(False)
                    self.scene.removeItem(thing)
                thing.alive = False
                continue
            thing.alive = True
            if pinned:
                if thing.parentItem() is not self.sheet.strip:
                    thing.setParentItem(self.sheet.strip)
            else:
                if thing.parentItem() is not None:
                    thing.setParentItem(None)
                if thing.scene() is None:
                    self.scene.addItem(thing)
            thing.set_size(w, h)
            thing.setPos(x, y)
            thing.setZValue(z)
            thing.setRotation(turn)
            if pixels is not None and thing.kind == "image":
                original, mask, matte, border, flip = pixels
                if (original is not thing.original or mask is not thing.mask
                        or matte is not thing.matte or border != thing.border):
                    if original is not thing.original:
                        thing.set_pixels(original=original, mask=mask, matte=matte, border=border)
                    else:
                        thing.set_pixels(mask=mask, matte=matte, border=border)
                if flip != thing.flip:
                    thing.set_flip(*flip)
        if self.editing is not None and not self.editing.alive:
            self.editing = None
            self.focus_text()
        self.view.viewport().update()

    def push(self, kind: str, data):
        if self._loading or self._undoing or self._joining:
            return
        if kind == "text" and self._pending_key:
            data, self._pending_key = self._pending_key, None
            self._joining = True            # Qt may announce one block twice
        self.history.append((kind, data))
        del self.history[:-400]
        self.future.clear()

    def undo(self):
        if not self.history:
            self.toast("nothing to undo")
            return
        kind, data = self.history.pop()
        self._undoing = True
        try:
            if kind == "text":
                self.doc.undo()
                self.future.append(("text", None))
            elif kind == "note":
                note = self.things.get(data)
                if note is not None and note.alive:
                    note.editor.document().undo()
                self.future.append(("note", data))
            else:
                self.future.append(("things", self.snapshot()))
                self.restore(data)
        finally:
            self._undoing = False
        if kind == "text":
            self.caret_moved()
        self.changed()

    def redo(self):
        if not self.future:
            return
        kind, data = self.future.pop()
        self._undoing = True
        try:
            if kind == "text":
                self.doc.redo()
                self.history.append(("text", None))
            elif kind == "note":
                note = self.things.get(data)
                if note is not None and note.alive:
                    note.editor.document().redo()
                self.history.append(("note", data))
            else:
                self.history.append(("things", self.snapshot()))
                self.restore(data)
        finally:
            self._undoing = False
        if kind == "text":
            self.caret_moved()
        self.changed()

    # -- things --------------------------------------------------------------
    def pointer_scene(self) -> QtCore.QPointF:
        pos = self.view.mapFromGlobal(QtGui.QCursor.pos())
        if self.view.viewport().rect().contains(pos):
            return self.view.mapToScene(pos)
        return self.view.mapToScene(self.view.viewport().rect().center())

    def _read_things(self, paths: list[str]) -> list[Thing]:
        files: list[str] = []
        for path in paths:
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    full = os.path.join(path, name)
                    if os.path.isfile(full):
                        files.append(full)
            else:
                files.append(path)
        things: list[Thing] = []
        for path in files:
            ext = os.path.splitext(path)[1].lower()
            name = os.path.splitext(os.path.basename(path))[0]
            if ext == project.SUFFIX:
                self.open_document(path)
                continue
            if ext != ".pdf" and ext not in project.IMAGE_SUFFIXES:
                continue
            try:
                with open(path, "rb") as handle:
                    blob = handle.read()
            except OSError:
                continue
            things.extend(self._make_things(blob, ext, name))
        return things

    def _make_things(self, blob: bytes, ext: str, name: str) -> list[Thing]:
        out: list[Thing] = []
        if ext == ".pdf":
            try:
                count = project.pdf_count(blob)
                for index in range(count):
                    image, size = project.pdf_page(blob, index)
                    out.append(Thing(image, size, blob, ext, index, f"{name} p{index + 1}"))
            except Exception as exc:
                self.toast(f"could not open {name}.pdf ({exc})")
            return out
        image = project.image_from_bytes(blob)
        if image is None:
            self.toast(f"could not read {name}{ext}")
            return out
        dpm = image.dotsPerMeterX()
        dpi = dpm * 0.0254 if dpm else 0
        dpi = dpi if 100 <= dpi <= 1200 else 150.0
        w, h = image.width() * 72.0 / dpi, image.height() * 72.0 / dpi
        longest = 420.0
        if max(w, h) > longest:
            k = longest / max(w, h)
            w, h = w * k, h * k
        out.append(Thing(image, QtCore.QSizeF(w, h), blob, ext, None, name))
        return out

    def place(self, things: list[Thing], at: QtCore.QPointF | None):
        if not things:
            return
        at = at or self.palette_at or self.pointer_scene()
        self.palette_at = None
        before = self.snapshot()
        on_page = self.live_on(at)
        page = self.sheet.scene_page_rect()
        text_width = self.sheet.W - 2 * self.fmt.margin
        x, y, row_h = at.x(), at.y(), 0.0
        z = self.top_z()
        for n, thing in enumerate(things):
            if on_page and thing.w > text_width:
                k = text_width / thing.w
                thing.resize(thing.w * k, thing.h * k)
            if n and x - at.x() > 1600:
                x, y, row_h = at.x(), y + row_h + 24, 0.0
            if on_page and len(things) == 1:
                pos = QtCore.QPointF(at.x() - thing.w / 2, at.y() - thing.h / 2)
            else:
                pos = QtCore.QPointF(x, y)
            self.things[thing.uid] = thing
            self.scene.addItem(thing)
            thing.setPos(pos)
            z += 1.0
            thing.setZValue(z)
            if on_page:
                self.pin(thing)
            x += thing.w + 24
            row_h = max(row_h, thing.h)
        self.push("things", before)
        self.select(things)
        self.changed()
        what = "pinned to the page" if on_page else "on the canvas"
        self.toast(f"{len(things)} {'thing' if len(things) == 1 else 'things'} {what}")

    def add_files(self, paths: list[str], at: QtCore.QPointF | None):
        with busy():
            things = self._read_things(paths)
        self.place(things, at)

    def browse_files(self, at: QtCore.QPointF | None = None):
        at = at or self.palette_at or self.pointer_scene()
        start = self.prefs.get("browse_dir", os.path.expanduser("~"))
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add images or PDFs", start,
            "Images and PDFs (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp *.heic *.pdf)")
        if paths:
            self.prefs["browse_dir"] = os.path.dirname(paths[0])
            self._write_prefs()
            self.add_files(paths, at)

    def drop(self, mime: QtCore.QMimeData, at: QtCore.QPointF):
        if mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            docs = [p for p in paths if p.lower().endswith(project.SUFFIX)]
            if docs:
                self.open_document(docs[0])
                return
            self.add_files(paths, at)
        elif mime.hasImage():
            self._place_image(QtGui.QImage(mime.imageData()), at)

    def _place_image(self, image: QtGui.QImage, at: QtCore.QPointF | None):
        if image.isNull():
            return
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        self.place(self._make_things(bytes(data), ".png", "pasted"), at)

    def paste(self) -> bool:
        mime = QtWidgets.QApplication.clipboard().mimeData()
        if mime is None:
            return False
        files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []
        media = [p for p in files if os.path.splitext(p)[1].lower()
                 in project.IMAGE_SUFFIXES | {".pdf"}]
        if media:
            self.add_files(media, self.pointer_scene())
            return True
        if mime.hasImage() and not mime.hasText():
            self._place_image(QtGui.QImage(mime.imageData()), self.pointer_scene())
            return True
        if mime.hasText():
            self.clear_selection()
            self.focus_text()
            cursor = self.sheet.text.textCursor()
            cursor.insertText(mime.text().replace("\r\n", "\n").replace("\r", "\n"))
            self.sheet.text.setTextCursor(cursor)
            self.caret_moved()
            return True
        return False

    def copy_selection(self):
        chosen = self.selection()
        if chosen:
            if isinstance(chosen[0], Note):
                QtWidgets.QApplication.clipboard().setText(chosen[0].text())
            else:
                QtWidgets.QApplication.clipboard().setImage(chosen[0].image)
            self.toast("copied")

    def delete_selection(self):
        chosen = self.selection()
        if not chosen:
            return
        before = self.snapshot()
        for thing in chosen:
            thing.setSelected(False)
            thing.alive = False
            self.scene.removeItem(thing)
        self.push("things", before)
        self.focus_text()
        self.changed()

    def _each_selected(self, action):
        chosen = self.selection()
        if not chosen:
            return
        before = self.snapshot()
        for thing in chosen:
            action(thing)
        self.push("things", before)
        self.changed()
        self.view.viewport().update()

    def restack(self, how: str):
        """Move the selection in the stacking order: "forward", "backward"
        (one step, ⌘] / ⌘[), "front" or "back" (all the way, ⇧⌘] / ⇧⌘[).
        On the page, the words are one step in that order, so an image can go
        behind or over them."""
        chosen = self.selection()
        if not chosen:
            return
        before = self.snapshot()
        note = ""
        for pinned in (True, False):
            group = [t for t in chosen if t.pinned == pinned]
            if not group:
                continue
            if pinned:
                peers = sorted(self.sheet.pinned(), key=lambda t: t.zValue())
                order = [t for t in peers if t.zValue() < 0] + ["words"] + \
                    [t for t in peers if t.zValue() >= 0]
            else:
                order = sorted((t for t in self.things.values() if t.alive and not t.pinned),
                               key=lambda t: t.zValue())
            mine = [e for e in order if any(e is t for t in group)]
            rest = [e for e in order if not any(e is t for t in group)]
            if how == "front":
                order = rest + mine
            elif how == "back":
                order = mine + rest
            else:
                ahead = how == "forward"
                indices = range(len(order) - 2, -1, -1) if ahead else range(1, len(order))
                for i in indices:
                    j = i + 1 if ahead else i - 1
                    if any(order[i] is t for t in group) and not any(order[j] is t for t in group):
                        order[i], order[j] = order[j], order[i]
            if pinned:
                words = order.index("words")
                for i, entry in enumerate(order):
                    if entry != "words":
                        entry.setZValue(float(i - words))
                below = sum(1 for t in group if t.zValue() < 0)
                note = ("behind the words · Alt+click reaches it" if below == len(group)
                        else "over the words" if below == 0 else "")
            else:
                for i, entry in enumerate(order):
                    entry.setZValue(float(i + 1))
        self.push("things", before)
        self.changed()
        self.view.viewport().update()
        self.toast({"forward": "forward", "backward": "backward", "front": "to the front",
                    "back": "to the back"}[how] + (f" · {note}" if note else ""))

    def to_front(self):
        self.restack("front")

    def behind_text(self):
        self.restack("back")

    def unpin_selected(self):
        def act(thing):
            if thing.pinned:
                self.unpin(thing)
                thing.setZValue(self.top_z() + 1.0)
                page = self.sheet.scene_page_rect()
                thing.setPos(page.right() + 40, thing.scenePos().y())
        self._each_selected(act)

    def natural_size(self):
        def act(thing):
            if isinstance(thing, Note):
                return
            w = thing.image.width() * 72.0 / 150.0
            thing.resize(w, w / thing.natural_aspect())
        self._each_selected(act)

    def fit_width(self):
        def act(thing):
            w = self.sheet.W - 2 * self.fmt.margin
            thing.resize(w, w / thing.natural_aspect())
            if thing.pinned:
                thing.setPos(self.fmt.margin, thing.pos().y())
        self._each_selected(act)

    # -- free text -----------------------------------------------------------
    def _inside(self, note: Note, at: QtCore.QPointF) -> bool:
        local = note.mapFromScene(at)
        return note.boundingRect().adjusted(-4, -4, 4, 4).contains(local)

    def new_note(self, at: QtCore.QPointF) -> Note:
        """A block of text whose first line starts at `at`.  On the page it
        is pinned and wraps at the right margin; on the canvas it is one
        line that grows."""
        self.clear_selection()
        before = self.snapshot()
        on_page = self.live_on(at)
        page = self.sheet.scene_page_rect()
        wrap = -1.0
        if on_page:
            x = at.x() - page.left()
            right = self.sheet.W - self.fmt.margin
            wrap = (right - x) if right - x >= 60 else max(40.0, self.sheet.W - x - 8)
        note = Note(self, "", wrap)
        note.style(self.doc_font(), self.block_format(), self.ink())
        metrics = QtGui.QFontMetricsF(self.doc_font())
        line = metrics.height() * self.fmt.line / 100.0
        self.things[note.uid] = note
        self.scene.addItem(note)
        # the click lands on the middle of the first line, not its top
        note.setPos(at.x(), at.y() - line / 2)
        note.setZValue(self.top_z() + 1.0)
        if on_page:
            self.pin(note)
        self.push("things", before)
        self._note_birth = (note.uid, len(self.history))
        self.start_editing(note)
        return note

    def start_editing(self, note: Note, at: QtCore.QPointF | None = None):
        if self.editing is not None and self.editing is not note:
            self.finish_editing()
        self.clear_selection()
        self.editing = note
        editor = note.editor
        editor.setTextInteractionFlags(QtCore.Qt.TextEditorInteraction)
        if not self.view.hasFocus():
            self.view.setFocus(QtCore.Qt.OtherFocusReason)
        self.scene.setFocusItem(editor, QtCore.Qt.MouseFocusReason)
        editor.setFocus()
        cursor = editor.textCursor()
        if at is not None:
            local = editor.mapFromScene(at)
            hit = editor.document().documentLayout().hitTest(local, QtCore.Qt.FuzzyHit)
            cursor.setPosition(max(0, hit))
        else:
            cursor.movePosition(QtGui.QTextCursor.End)
        editor.setTextCursor(cursor)
        self.view.viewport().update()

    def finish_editing(self):
        note, self.editing = self.editing, None
        if note is None:
            return
        editor = note.editor
        cursor = editor.textCursor()
        cursor.clearSelection()
        editor.setTextCursor(cursor)
        editor.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        editor.clearFocus()
        if not note.text().strip():
            self._discard(note)
        self._note_birth = None
        self.view.viewport().update()

    def _discard(self, note: Note):
        """An empty note leaves no trace: not on the page, not in undo."""
        self.history = [e for e in self.history if e != ("note", note.uid)]
        self.future = [e for e in self.future if e != ("note", note.uid)]
        born = self._note_birth
        if born and born[0] == note.uid and len(self.history) == born[1]:
            self.history.pop()
        else:
            self.push("things", self.snapshot())
        note.setSelected(False)
        note.alive = False
        self.scene.removeItem(note)
        self.changed()

    # -- image operations (from stik) --------------------------------------------
    def images(self, things=None) -> list[Thing]:
        """The selected (or given) things that are images - not text blocks."""
        return [t for t in (things if things is not None else self.selection())
                if t.alive and t.kind == "image"]

    def _adopt(self, thing: Thing, like: Thing, z: float | None = None):
        """Register a new thing beside `like`: same parent, rotation, flip."""
        self.things[thing.uid] = thing
        if like.pinned:
            thing.setParentItem(self.sheet.strip)
        else:
            self.scene.addItem(thing)
        thing.setRotation(like.rotation())
        thing.set_flip(*like.flip)
        thing.setZValue(z if z is not None else like.zValue() + 0.5)

    def _place_over(self, piece: Thing, like: Thing, item_point: QtCore.QPointF):
        """Put `piece`'s top-left corner exactly on `item_point` of `like`
        (rotation and mirroring included)."""
        target = like.mapToParent(item_point) if like.pinned else like.mapToScene(item_point)
        here = piece.mapToParent(QtCore.QPointF(0, 0)) if piece.pinned else \
            piece.mapToScene(QtCore.QPointF(0, 0))
        piece.setPos(piece.pos() + (target - here))

    def duplicate(self, thing: Thing, offset: QtCore.QPointF = QtCore.QPointF(16, 16)) -> Thing:
        if thing.kind != "image":
            copy = Note(self, thing.text(), thing.wrap)
            copy.style(self.doc_font(), self.block_format(), self.ink())
        else:
            copy = Thing(thing.original, QtCore.QSizeF(thing.w, thing.h), thing.blob, thing.ext,
                         thing.pdf_page, thing.name)
            copy.set_pixels(mask=thing.mask, matte=thing.matte, border=thing.border)
        self._adopt(copy, thing, z=thing.zValue() + 0.5)
        copy.setPos(thing.pos() + offset)
        return copy

    def duplicate_selection(self):
        chosen = self.selection()
        if not chosen:
            return
        before = self.snapshot()
        copies = [self.duplicate(t) for t in chosen]
        self.push("things", before)
        self.select(copies)
        self.changed()

    def mirror_selection(self, horizontal: bool = True):
        def act(thing):
            fx, fy = thing.flip
            thing.set_flip(not fx if horizontal else fx, fy if horizontal else not fy)
        self._each_selected(act)

    def reset_masks(self):
        """Bring back what background removal, the wand and the eraser took;
        the cut shape stays as it was cut."""
        self._each_selected(lambda t: t.kind == "image" and t.set_pixels(matte=None))
        self.toast("mask reset · as cut")

    def set_border(self, things: list[Thing], width_pt: float, colour: str, smooth_pt: float):
        """A die-cut sticker border round each image (width 0 takes it off)."""
        before = self.snapshot()
        for thing in self.images(things):
            k = thing.px_per_pt()
            border = (width_pt * k, colour, smooth_pt * k) if width_pt > 0 else None
            thing.set_pixels(border=border)
        self.push("things", before)
        self.changed()

    def arrange_selection(self, gap: float = 16.0, row_width: float | None = None):
        """Lay the selection out in rows, by name, from its top-left corner."""
        chosen = sorted(self.selection(), key=lambda t: (t.name, t.uid))
        if not chosen:
            return
        before = self.snapshot()
        rect = QtCore.QRectF()
        for t in chosen:
            rect = rect.united(t.sceneBoundingRect())
        row_width = row_width or max(rect.width(), 600.0)
        x, y, row = rect.left(), rect.top(), 0.0
        for t in chosen:
            box = t.sceneBoundingRect()
            if x > rect.left() and x + box.width() > rect.left() + row_width:
                x, y, row = rect.left(), y + row + gap, 0.0
            t.moveBy(x - box.left(), y - box.top())
            x += box.width() + gap
            row = max(row, box.height())
        self.push("things", before)
        self.changed()
        self.view.viewport().update()

    def merge_selection(self):
        """Flatten the selected images into one, where the topmost was, at
        the finest resolution any of them is shown at."""
        chosen = self.images()
        if len(chosen) < 2:
            self.toast("merge · select two or more images")
            return
        group = [t for t in chosen if t.pinned == chosen[0].pinned]
        group.sort(key=lambda t: t.zValue())
        rect = QtCore.QRectF()
        for t in group:
            rect = rect.united(t.parent_rect() if t.pinned else t.sceneBoundingRect())
        k = min(8.0, max(t.px_per_pt() for t in group))
        size = QtCore.QSize(max(1, int(np.ceil(rect.width() * k))),
                            max(1, int(np.ceil(rect.height() * k))))
        flat = QtGui.QImage(size, QtGui.QImage.Format_ARGB32_Premultiplied)
        flat.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(flat)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        painter.scale(k, k)
        painter.translate(-rect.topLeft())
        for t in group:
            painter.save()
            placed = t.itemTransform(t.parentItem())[0] if t.pinned else t.sceneTransform()
            painter.setTransform(placed, True)
            t.render(painter, self.ink())
            painter.restore()
        painter.end()
        before = self.snapshot()
        top = group[-1]
        image = flat.convertToFormat(QtGui.QImage.Format_ARGB32)
        data = QtCore.QByteArray()
        buffer = QtCore.QBuffer(data)
        buffer.open(QtCore.QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        merged = Thing(image, rect.size(), bytes(data), ".png", None, "merged")
        self._adopt(merged, top, z=top.zValue())
        merged.setRotation(0.0)
        merged.set_flip(False, False)
        merged.setPos(rect.topLeft())
        for t in group:
            t.setSelected(False)
            t.alive = False
            self.scene.removeItem(t)
        self.push("things", before)
        self.select([merged])
        self.changed()
        self.toast(f"merged {len(group)} images")

    def cut(self, thing: Thing, polygon: QtGui.QPolygonF, copy: bool = False,
            feather_pt: float = 0.0, lift: bool = True) -> Thing | None:
        """Cut the scene-space `polygon` out of `thing`: a new image (the
        cutout) over its own hole, which stays in `thing` unless `copy`.
        The caller makes it one undo step."""
        import cv2
        h, w = thing.original.height(), thing.original.width()
        points = [thing.to_pixels(thing.mapFromScene(p)) for p in polygon]
        if len(points) < 3:
            return None
        sel = np.zeros((h, w), np.uint8)
        cv2.fillPoly(sel, [np.round(np.array(points) * 8).astype(np.int32)], 255,
                     lineType=cv2.LINE_AA, shift=3)
        if feather_pt > 0:
            sel = cv2.GaussianBlur(sel, (0, 0), max(0.3, feather_pt * thing.px_per_pt()))
        return self.cut_selection(thing, sel, copy=copy, lift=lift)

    def cut_selection(self, thing: Thing, sel: np.ndarray, copy: bool = False,
                      lift: bool = True) -> Thing | None:
        """Cut by a selection over `thing`'s original pixels ((h, w) uint8,
        255 = all of it): the cutout keeps exactly that much of each pixel,
        and the hole gives exactly that much up - together they add back up
        to the original."""
        h, w = thing.original.height(), thing.original.width()
        take = (sel.astype(np.uint16) * thing.alpha() // 255).astype(np.uint8)
        ys, xs = np.nonzero(take > 4)
        if len(ys) == 0:
            return None
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        crop = thing.bgra()[y0:y1, x0:x1]
        shape = (sel[y0:y1, x0:x1].astype(np.uint16) * (
            thing.mask[y0:y1, x0:x1] if thing.mask is not None else 255) // 255).astype(np.uint8)
        matte = thing.matte[y0:y1, x0:x1].copy() if thing.matte is not None else None
        from .page import bgra_to_qimage
        image = bgra_to_qimage(crop)
        n = 1 + sum(1 for t in self.things.values() if t.name.startswith(thing.name + "_"))
        piece = Thing(image, QtCore.QSizeF((x1 - x0) * thing.w / w, (y1 - y0) * thing.h / h),
                      project.png_bytes_rgba(crop), ".png", None, f"{thing.name or 'image'}_{n:02d}")
        piece.set_pixels(mask=shape, matte=matte, border=thing.border)
        self._adopt(piece, thing, z=thing.zValue() + 0.5)
        self._place_over(piece, thing, QtCore.QPointF(x0 * thing.w / w, y0 * thing.h / h))
        if lift:
            piece.moveBy(4.0, 4.0)
        if not copy:
            hole = (255 - sel).astype(np.uint16)
            base = thing.mask if thing.mask is not None else np.full((h, w), 255, np.uint8)
            thing.set_pixels(mask=(base.astype(np.uint16) * hole // 255).astype(np.uint8))
        return piece

    def rotate_selected(self, degrees: float):
        self._each_selected(lambda t: t.setRotation((t.rotation() + degrees) % 360.0))

    def set_rotation(self, degrees: float):
        self._each_selected(lambda t: t.setRotation(degrees % 360.0))

    # -- view ----------------------------------------------------------------
    def fit_layout(self):
        self.view.frame(self.layout_rect(), margin=48)

    def fit_page(self):
        self.view.frame(self.sheet.scene_page_rect(), margin=48)

    def fit_all(self):
        rect = self.layout_rect()
        for thing in self.things.values():
            if thing.alive and not thing.pinned:
                rect = rect.united(thing.sceneBoundingRect())
        self.view.frame(rect, margin=48)

    def actual_size(self):
        self.view.set_zoom(1.0)
        self.view.centerOn(self.sheet.scene_page_rect().center())

    # -- distress ------------------------------------------------------------
    def toggle_preview(self):
        if self.preview is not None:
            self.hide_preview()
        else:
            self.show_preview()

    def _ink(self, dpi: float, box: tuple[int, int, int, int]):
        """The current page's ink layer (or the `box` of it), rendered once
        per state of the page."""
        key = (self.page, dpi, box, self.doc.revision(), self.doc.toPlainText().__hash__(),
               self.things_key(), tuple(asdict(self.fmt).items()),
               tuple(t.text() for t in self.things.values() if isinstance(t, Note) and t.alive))
        if self._ink_cache is None or self._ink_cache[0] != key:
            self._ink_cache = (key, export.page_layers(self.sheet, self.page, dpi, self.ink(), box))
        return self._ink_cache[1]

    def _preview_area(self) -> tuple[float, QtCore.QRectF | None]:
        """The dpi that matches the screen right now (zoom × Retina), and
        the part of the page in sight, in page points.  Only that part is
        rendered, so the preview is sharp at any zoom and costs about one
        screenful of pixels."""
        ratio = self.view.devicePixelRatioF() if hasattr(self.view, "devicePixelRatioF") else 1.0
        dpi = max(72.0, min(PREVIEW_MAX_DPI, 72.0 * self.view.zoom() * ratio))
        page = self.sheet.scene_page_rect()
        seen = self.view.visible_scene_rect().intersected(page)
        if seen.isEmpty():
            return dpi, None
        pad = 120.0 / max(1e-6, self.view.zoom())     # room to pan before a re-render
        area = seen.translated(-page.topLeft()).adjusted(-pad, -pad, pad, pad)
        return dpi, area

    def _set_preview_image(self, image: QtGui.QImage, dpi: float,
                           box: tuple[int, int, int, int] = (0, 0, 0, 0)):
        if self.preview is None:
            self.preview = QtWidgets.QGraphicsPixmapItem(self.sheet)
            self.preview.setTransformationMode(QtCore.Qt.SmoothTransformation)
            self.preview.setZValue(1000)
        self.preview.setPixmap(QtGui.QPixmap.fromImage(image))
        self.preview.setScale(72.0 / dpi)
        self.preview.setPos(box[0] * 72.0 / dpi, box[1] * 72.0 / dpi)
        self.view.viewport().update()

    def show_preview(self):
        """The current page distressed, in place - rendered now."""
        self._preview_gen += 1
        dpi, area = self._preview_area()
        box = export.crop_box(self.sheet, dpi, area)
        settings = replace(self.distress, enabled=True)
        with busy():
            layer = self._ink(dpi, box)
            paper_stock = self.paper_stock()
            base = export.stock(self.sheet, dpi, box, self.paper(), paper_stock)
            out = distress.compose(layer, export.rgb(self.paper()), settings, dpi,
                                   origin=(box[1], box[0]), density=self.density(), base=base,
                                   over=export.over(self.sheet, dpi, box, paper_stock))
        self._set_preview_image(export.from_rgb(out), dpi, box)

    def request_preview(self, fast: bool = False):
        """The same, worked out on a thread: the newest request wins, and
        stale ones are dropped before they start.  `fast` (while typing or
        dragging a slider) renders at 60% of the screen's resolution."""
        self._preview_gen += 1
        gen = self._preview_gen
        dpi, area = self._preview_area()
        if area is None:
            return
        if fast:
            dpi = max(72.0, dpi * 0.6)
        box = export.crop_box(self.sheet, dpi, area)
        layer = self._ink(dpi, box)
        settings = replace(self.distress, enabled=True)
        paper = export.rgb(self.paper())
        density = self.density()
        paper_stock, paper_colour = self.paper_stock(), self.paper()

        def work():
            if gen != self._preview_gen:
                return
            try:
                base = export.stock(self.sheet, dpi, box, paper_colour, paper_stock)
                out = distress.compose(layer, paper, settings, dpi, origin=(box[1], box[0]),
                                       density=density, base=base,
                                       over=export.over(self.sheet, dpi, box, paper_stock))
            except Exception as exc:            # never let the worker die quietly
                print("ream: preview failed:", exc, file=sys.stderr)
                return
            self.preview_ready.emit(gen, (out, dpi, box))
        self._pool.submit(work)

    def _preview_arrived(self, gen: int, payload):
        if gen != self._preview_gen:
            return
        out, dpi, box = payload
        self._set_preview_image(export.from_rgb(out), dpi, box)

    def _write_zoom_moved(self):
        if self.write_mode and abs(self.view.zoom() - self.write_zoom()) > 1e-3 \
                and self._follow_anim.state() != QtCore.QAbstractAnimation.Running:
            self.prefs["write_zoom"] = round(self.view.zoom(), 3)
            self._write_prefs()

    def view_changed(self):
        """Zoomed or panned: sharpen and re-crop the live view once it rests."""
        if getattr(self, "distress_view", False):
            self._view_timer.start()
        if getattr(self, "write_mode", False):
            self._write_zoom_moved()

    def hide_preview(self):
        self._preview_gen += 1
        if self.preview is not None:
            self.scene.removeItem(self.preview)
            self.preview = None
            self.view.viewport().update()

    def live(self) -> bool:
        return self.distress_view

    def _refresh_live_preview(self, fast: bool = False):
        if self.live():
            self.request_preview(fast)

    def _stale(self):
        """Something is about to change the page.  A still preview goes; the
        live view stays and re-renders once the change has landed."""
        if not self.live():
            self.hide_preview()

    def _drop_overlay(self):
        """Take the picture off while the pages slide (the live view comes
        back when they stop)."""
        self._preview_gen += 1
        if self.preview is not None:
            self.scene.removeItem(self.preview)
            self.preview = None
            self.view.viewport().update()

    def _schedule_live(self):
        self._last_edit = time.monotonic()
        if not self._live_timer.isActive():
            self._live_timer.start()
        self._idle_timer.start()

    def _render_live(self, fast: bool):
        if not self.live() or self.anim.state() == QtCore.QAbstractAnimation.Running:
            return
        self.request_preview(fast=fast and time.monotonic() - self._last_edit < 0.45)

    def set_distress_view(self, on: bool, quiet: bool = False):
        self.distress_view = on
        self._view_from_panel = False
        self.prefs["distress_view"] = on
        self._write_prefs()
        if on:
            self.request_preview()
            self._render_ghosts()
        else:
            self.hide_preview()
        for ghost in self.ghosts.values():
            ghost.update()
        if self.distress_panel is not None:
            self.distress_panel.refresh()
        if not quiet:
            self.toast("writing on the distressed page" if on else "distress view off")

    def toggle_distress_view(self):
        self.set_distress_view(not self.distress_view)

    def distress_changed(self, fast: bool = False):
        still = self.preview is not None and not self.live()
        self.changed()
        if self.live():
            self._live_timer.stop()
            self.request_preview(fast)
            if not fast:
                self._render_ghosts()
        elif still:
            self.show_preview()

    def set_style(self, name: str):
        self.distress.style = name
        self.distress.enabled = True
        self.toast(f"distress · {name}")
        self.distress_changed()

    def set_fade_style(self, name: str):
        self.distress.fade_style = name
        self.toast(f"fade texture · {name}")
        self.distress_changed()

    def toggle_distress(self):
        self.distress.enabled = not self.distress.enabled
        self.toast("distress on" if self.distress.enabled else "distress off: exports are clean vector")
        self.changed()
        if self.distress_panel is not None:
            self.distress_panel.refresh()

    def set_distress_images(self, on: bool):
        """Distress images as well as words, or leave them clean (words on
        them are distressed either way)."""
        self.distress.images = bool(on)
        self.toast("images distressed" if on else "images clean · words still distressed")
        if self.distress_panel is not None:
            self.distress_panel.refresh()
        self.distress_changed()

    def reset_distress(self):
        keep = self.distress.enabled
        self.distress = distress.Settings(enabled=keep)
        self.toast("distress reset")
        if self.distress_panel is not None:
            self.distress_panel.refresh()
        self.distress_changed()

    def set_param(self, name: str, value: float):
        if name in distress.PARAMS:
            lo, hi, _ = distress.PARAMS[name]
            value = max(lo, min(hi, value))
            setattr(self.distress, name, value)
            self.toast(f"{name} {value:g}")
            if self.distress_panel is not None:
                self.distress_panel.refresh()
            self.distress_changed()
            return
        if name == "page":
            self.flip(int(value) - 1, reveal="top")
            return
        if name == "rotate":
            self.set_rotation(value)
            return
        lo, hi = FORMAT_PARAMS[name]
        value = max(lo, min(hi, value))
        setters = {"line": self.set_line_height, "para": self.set_para, "size": self.set_size,
                   "ink": self.set_ink, "grain": self.set_grain, "stock": self.set_stock_scale,
                   "margin": lambda v: self.set_margins(side=v),
                   "head": lambda v: self.set_margins(head=v)}
        if name in setters:
            setters[name](value)
        else:
            setattr(self.fmt, name, value)
        if self.page_panel is not None:
            self.page_panel.refresh()
        self.toast(f"{name} {value:g}")
        self.changed()

    def set_format(self, **values):
        for key, value in values.items():
            setattr(self.fmt, key, value)
        self.apply_format()
        self.changed()
        if self.page_panel is not None:
            self.page_panel.refresh()

    # -- profiles ------------------------------------------------------------
    def settings_snapshot(self) -> dict:
        """Everything a profile holds: how the page looks and comes out."""
        return {"format": asdict(self.fmt), "distress": self.distress.to_dict(),
                "theme": self.theme, "canvas": self.canvas_colour()}

    def profile_names(self) -> list[str]:
        return list(self._profiles)

    def active_profile(self) -> str | None:
        name = self.prefs.get("profile")
        return name if name in self._profiles else None

    def profile_dirty(self) -> bool:
        """True when the settings no longer match the active profile."""
        name = self.active_profile()
        if name is None:
            return False
        return json.loads(json.dumps(self.settings_snapshot())) != self._profiles[name]

    def save_profile(self, name: str | None = None):
        """Save the current settings: to `name`, else to the active profile,
        else to a new one (profile1, profile2, ...)."""
        name = (name or "").strip() or self.active_profile() or profiles.next_name(self._profiles)
        self._profiles[name] = json.loads(json.dumps(self.settings_snapshot()))
        profiles.store(self._profiles)
        self.prefs["profile"] = name
        self._write_prefs()
        self.toast(f"saved to {name}")
        self._refresh_panels()

    def new_profile(self):
        self.save_profile(profiles.next_name(self._profiles))

    def switch_profile(self, name: str):
        snap = self._profiles.get(name)
        if snap is None:
            return
        self.prefs["profile"] = name
        self._write_prefs()
        self.apply_settings(snap)
        self.toast(f"profile · {name}")

    def switch_profile_number(self, number: int):
        names = self.profile_names()
        if 1 <= number <= len(names):
            self.switch_profile(names[number - 1])

    def delete_profile(self, name: str | None = None):
        name = name or self.active_profile()
        if not name or name not in self._profiles:
            return
        del self._profiles[name]
        profiles.store(self._profiles)
        if self.prefs.get("profile") == name:
            self.prefs.pop("profile", None)
            self._write_prefs()
        self.toast(f"deleted {name}")
        self._refresh_panels()

    def _choose_profile(self, name: str):
        if name in self._profiles and name != self.active_profile():
            self.switch_profile(name)

    def apply_settings(self, snap: dict):
        """Take on a profile's settings: type, layout, paper, ink, distress,
        canvas.  Line and paragraph spacing change as one undo step."""
        old, new = self.fmt, Format.from_dict(snap.get("format"))
        self.distress = distress.Settings.from_dict(snap.get("distress"))
        if snap.get("theme") in style.THEMES:
            self.theme = snap["theme"]
        if snap.get("canvas"):
            self.prefs["canvas"] = snap["canvas"]
        self.apply_theme()
        self.fmt = new
        self.apply_format()
        if (new.line, new.para) != (old.line, old.para):
            block = QtGui.QTextBlockFormat()
            block.setLineHeight(new.line, QtGui.QTextBlockFormat.ProportionalHeight)
            block.setBottomMargin(new.para)
            self._format_edit("profile", self._merge_blocks(block))
            self.restyle_notes()
        self.caret_moved(follow=False)
        self._refresh_panels()
        self.distress_changed()

    def _profile_rows(self, panel: Panel):
        panel.choice("profile", lambda: self.profile_names() or ["none"],
                     lambda: self.active_profile() or "none", self._choose_profile)
        panel.links("", [(lambda: "save *" if self.profile_dirty() else "save", self.save_profile),
                         ("new", self.new_profile), ("delete", self.delete_profile)])

    def _refresh_panels(self):
        for panel in (self.distress_panel, self.page_panel):
            if panel is not None and panel.isVisible():
                panel.refresh()

    # -- panels --------------------------------------------------------------
    def _slider_held(self) -> bool:
        focus = QtWidgets.QApplication.focusWidget()
        return isinstance(focus, QtWidgets.QSlider) and focus.isSliderDown()

    def _distress_put(self, name: str):
        def put(value):
            setattr(self.distress, name, value)
            self.distress_changed(fast=self._slider_held())
        return put

    def build_distress_panel(self) -> Panel:
        panel = Panel(self, "distress", on_close=self._distress_panel_closed,
                      on_tab=self.open_palette)
        d = lambda: self.distress                                       # noqa: E731
        self._profile_rows(panel)
        panel.toggle("see", lambda: self.distress_view,
                     lambda v: self.set_distress_view(v, quiet=True), on="distressed", off="clean")
        panel.toggle("export", lambda: d().enabled,
                     lambda v: (setattr(d(), "enabled", v), self.changed()),
                     on="distressed", off="clean")
        panel.toggle("images", lambda: d().images, self.set_distress_images,
                     on="distressed", off="clean")
        panel.slider("ink", 5, 150, lambda: self.fmt.ink, self.set_ink, unit="%", default=100)
        panel.choice("style", distress.edge_styles, lambda: d().style,
                     lambda v: (setattr(d(), "style", v), self.distress_changed()))
        panel.choice("wear", distress.fade_styles, lambda: d().fade_style,
                     lambda v: (setattr(d(), "fade_style", v), self.distress_changed()))
        defaults = distress.Settings()
        for name, (lo, hi, _what) in distress.PARAMS.items():
            if name == "misfire":
                panel.section("ream's own")
            panel.slider(name, lo, hi, lambda n=name: getattr(d(), n), self._distress_put(name),
                         unit="%" if name == "scale" else "", default=getattr(defaults, name))
        panel.section("export")
        panel.slider("dpi", 72, 600, lambda: self.fmt.dpi,
                     lambda v: (setattr(self.fmt, "dpi", v), self.changed()), step=12, default=300)
        panel.buttons([("reset", self.reset_distress),
                       ("new seed", self._new_seed),
                       ("export pdf", self.export_pdf)])
        panel.on_release = lambda: (self._refresh_live_preview(fast=False), self._render_ghosts())
        return panel

    def _new_seed(self):
        self.distress.seed = (int(self.distress.seed) + 1) % 26
        self.distress_panel.refresh()
        self.distress_changed()

    def build_page_panel(self) -> Panel:
        panel = Panel(self, "page", on_tab=self.open_palette)
        f = lambda: self.fmt                                            # noqa: E731
        self._profile_rows(panel)
        panel.section("type")
        panel.choice("font", style.faces, self.face, lambda v: self.set_format(font=v))
        panel.slider("size", 5, 24, lambda: f().size, self.set_size, step=0.5, unit=" pt",
                     default=9)
        panel.slider("line", 80, 300, lambda: f().line, self.set_line_height, step=5, unit="%",
                     default=150)
        panel.slider("para", 0, 36, lambda: f().para, self.set_para, unit=" pt", default=0)
        panel.slider("ink", 5, 150, lambda: f().ink, self.set_ink, unit="%", default=100)
        panel.section("page")
        panel.choice("format", lambda: list(style.PAGE_SIZES), lambda: f().page,
                     lambda v: self.set_format(page=v))
        panel.slider("sides", 0, 200, lambda: f().margin, lambda v: self.set_margins(side=v),
                     unit=" pt", default=64)
        panel.slider("top/bot", 0, 200, lambda: f().head, lambda v: self.set_margins(head=v),
                     unit=" pt", default=70)
        panel.swatches("paper", list(style.PAPERS.values()) + ["#e4e1d6", "#d8d2c2"],
                       lambda: self.paper().name(), self.set_paper)
        panel.choice("stock", self.stock_labels, self.stock_label, self.set_stock_label)
        panel.choice("blend", lambda: list(papers.BLENDS), self.blend_mode, self.set_blend)
        panel.slider("amount", 0, 100, lambda: f().grain, self.set_grain, unit="%", default=60)
        panel.slider("scale", 25, 400, lambda: f().stock_scale, self.set_stock_scale, step=5,
                     unit="%", default=100)
        panel.section("write mode")
        panel.slider("zoom", 50, 400, lambda: self.write_zoom() * 100,
                     lambda v: self.set_write_zoom(v / 100.0), step=5, unit="%",
                     default=WRITE_ZOOM * 100)
        panel.section("canvas")
        panel.swatches("colour", CANVAS_SWATCHES, self.canvas_colour, self.set_canvas)
        panel.choice("edge", lambda: list(style.THEMES), lambda: self.theme, self._set_edge_theme)
        panel.buttons([("fit page", self.fit_page), ("close", panel.close_panel)])
        return panel

    def _open_beside(self, panel: Panel, other: Panel | None):
        """Open a panel; the first time, next to the other one if it is up."""
        fresh = not panel.placed
        panel.open()
        if fresh and other is not None and other.isVisible() and \
                panel.geometry().intersects(other.geometry()):
            panel.move(other.x() - panel.width() - 12, other.y())
            panel.keep_inside()

    def open_distress_panel(self):
        if self.distress_panel is None:
            self.distress_panel = self.build_distress_panel()
        self._open_beside(self.distress_panel, self.page_panel)
        if not self.distress_view:
            self.distress_view = True
            self._view_from_panel = True    # closing the panel turns it off again
            self.distress_panel.refresh()
        self.request_preview()
        self._render_ghosts()

    def _distress_panel_closed(self):
        if self._view_from_panel:
            self.distress_view = False
            self._view_from_panel = False
            self.hide_preview()
            for ghost in self.ghosts.values():
                ghost.update()

    def open_page_panel(self):
        if self.page_panel is None:
            self.page_panel = self.build_page_panel()
        self._open_beside(self.page_panel, self.distress_panel)

    def toggle_distress_panel(self):
        if self.distress_panel is not None and self.distress_panel.isVisible():
            self.distress_panel.close_panel()
        else:
            self.open_distress_panel()

    def toggle_page_panel(self):
        if self.page_panel is not None and self.page_panel.isVisible():
            self.page_panel.close_panel()
        else:
            self.open_page_panel()

    # -- export --------------------------------------------------------------
    def stem(self) -> str:
        if self.path:
            return os.path.splitext(os.path.basename(self.path))[0]
        first = self.doc.toPlainText().strip().split("\n", 1)[0][:40].strip()
        slug = re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")
        return slug or "untitled"

    def _export_target(self, title: str, suffix: str, filt: str) -> str | None:
        folder = self.prefs.get("export_dir", os.path.expanduser("~/Desktop"))
        default = os.path.join(folder, self.stem() + suffix)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, default, filt)
        if path:
            self.prefs["export_dir"] = os.path.dirname(path)
            self._write_prefs()
        return path or None

    def export_pdf(self, clean: bool = False, path: str | None = None) -> str | None:
        path = path or self._export_target("Export PDF", ".pdf", "PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        settings = replace(self.distress, enabled=self.distress.enabled and not clean)
        pages = list(range(self.sheet.pages()))
        with busy():
            export.write_pdf(path, self.sheet, pages, dpi=self.fmt.dpi, settings=settings,
                             paper=self.paper(), ink=self.ink(), title=self.stem(),
                             density=self.density(), paper_stock=self.paper_stock(),
                             progress=lambda n, total: self.toast(f"page {n + 1} of {total}"))
        how = f"distressed · {settings.style}" if settings.enabled else "clean"
        self.toast(f"{len(pages)} {'page' if len(pages) == 1 else 'pages'} {how} → {path}")
        return path

    def export_png(self, path: str | None = None) -> list[str]:
        path = path or self._export_target("Export pages as PNG", ".png", "PNG (*.png)")
        if not path:
            return []
        stem = path[:-4] if path.lower().endswith(".png") else path
        pages = list(range(self.sheet.pages()))
        with busy():
            written = export.write_pngs(stem, self.sheet, pages, dpi=self.fmt.dpi,
                                        settings=self.distress, paper=self.paper(), ink=self.ink(),
                                        density=self.density(),
                                        paper_stock=self.paper_stock(),
                                        progress=lambda n, t: self.toast(f"page {n + 1} of {t}"))
        self.toast(f"{len(written)} png → {os.path.dirname(stem)}")
        return written

    # -- documents -----------------------------------------------------------
    def state(self) -> tuple[dict, dict[str, bytes]]:
        media: dict[str, bytes] = {}
        things = []
        for thing in self.things.values():
            if not thing.alive:
                continue
            if isinstance(thing, Note):
                if thing is self.editing or thing.text().strip():
                    things.append({"uid": thing.uid, "kind": "text", "text": thing.text(),
                                   "wrap": thing.wrap, "pinned": thing.pinned,
                                   "x": thing.pos().x(), "y": thing.pos().y(),
                                   "z": thing.zValue(), "r": thing.rotation()})
                continue
            name = project.media_name(thing.blob, thing.ext)
            media[name] = thing.blob
            entry = {"uid": thing.uid, "media": name, "pdf_page": thing.pdf_page,
                     "name": thing.name, "pinned": thing.pinned,
                     "x": thing.pos().x(), "y": thing.pos().y(),
                     "w": thing.w, "h": thing.h, "z": thing.zValue(),
                     "r": thing.rotation()}
            for field in ("mask", "matte"):                  # the masks, as greyscale PNGs
                plane = getattr(thing, field)
                if plane is not None:
                    data = project.png_bytes(plane)
                    entry[field] = project.media_name(data, ".png")
                    media[entry[field]] = data
            if thing.border is not None:
                entry["border"] = list(thing.border)
            if any(thing.flip):
                entry["flip"] = list(thing.flip)
            things.append(entry)
        centre = self.view.mapToScene(self.view.viewport().rect().center())
        return {
            "app": f"ream {__version__}",
            "text": project.doc_to_text(self.doc),
            "caret": self.sheet.text.textCursor().position(),
            "format": asdict(self.fmt),
            "distress": self.distress.to_dict(),
            "page": self.page,
            "view": {"zoom": self.view.zoom(), "x": centre.x(), "y": centre.y()},
            "things": things,
        }, media

    def _clear(self):
        self.hide_preview()
        self.editing = None
        for thing in self.things.values():
            if thing.scene() is not None:
                self.scene.removeItem(thing)
        self.things.clear()
        self.history.clear()
        self.future.clear()

    def load_state(self, state: dict, media: dict[str, bytes]):
        self._loading = True
        try:
            self._clear()
            self.fmt = Format.from_dict(state.get("format"))
            self.distress = distress.Settings.from_dict(state.get("distress"))
            self.doc.setUndoRedoEnabled(False)
            project.text_to_doc(self.doc, state.get("text", ""), self.block_format())
            self.doc.setUndoRedoEnabled(False)
            self.apply_format()
            pdf_cache: dict[tuple[str, int], tuple] = {}
            for entry in state.get("things", []):
                if entry.get("kind") == "text":
                    note = Note(self, entry.get("text", ""), entry.get("wrap", -1.0),
                                uid=entry.get("uid"))
                    note.style(self.doc_font(), self.block_format(), self.ink())
                    self.things[note.uid] = note
                    if entry.get("pinned"):
                        note.setParentItem(self.sheet.strip)
                    else:
                        self.scene.addItem(note)
                    note.setPos(entry["x"], entry["y"])
                    note.setRotation(entry.get("r", 0.0))
                    note.setZValue(entry.get("z", 1.0))
                    continue
                blob = media.get(entry.get("media", ""))
                if blob is None:
                    continue
                ext = os.path.splitext(entry["media"])[1]
                index = entry.get("pdf_page")
                try:
                    if index is not None:
                        key = (entry["media"], index)
                        if key not in pdf_cache:
                            pdf_cache[key] = project.pdf_page(blob, index)
                        image = pdf_cache[key][0]
                    else:
                        image = project.image_from_bytes(blob)
                except Exception:
                    image = None
                if image is None:
                    continue
                thing = Thing(image, QtCore.QSizeF(entry["w"], entry["h"]), blob, ext, index,
                              entry.get("name", ""), uid=entry.get("uid"))
                self.things[thing.uid] = thing
                if entry.get("pinned"):
                    thing.setParentItem(self.sheet.strip)
                else:
                    self.scene.addItem(thing)
                thing.setPos(entry["x"], entry["y"])
                thing.setRotation(entry.get("r", 0.0))
                thing.setZValue(entry.get("z", 1.0))
                planes = {f: project.png_plane(media.get(entry[f], b""))
                          for f in ("mask", "matte") if entry.get(f)}
                border = tuple(entry["border"]) if entry.get("border") else None
                if planes or border:
                    thing.set_pixels(**planes, border=border)
                if entry.get("flip"):
                    thing.set_flip(*entry["flip"])
            self.page = max(0, min(int(state.get("page", 0)), self.sheet.pages()))
            self.sheet.set_offset(self.page * self.sheet.H)
            self._update_grid()
            self._place_sheet()
            cursor = QtGui.QTextCursor(self.doc)
            cursor.setPosition(max(0, min(int(state.get("caret", 0)),
                                          self.doc.characterCount() - 1)))
            self.sheet.text.setTextCursor(cursor)
        finally:
            self.doc.setUndoRedoEnabled(True)
            self._loading = False
        view = state.get("view")
        if view:
            self.view.setTransform(QtGui.QTransform.fromScale(view["zoom"], view["zoom"]))
            self.view.centerOn(view["x"], view["y"])
        else:
            QtCore.QTimer.singleShot(0, self.fit_layout)
        self.view.viewport().update()

    def open_document(self, path: str, quiet: bool = False):
        self.autosave()
        try:
            state, media = project.load(path)
        except Exception as exc:
            if not quiet:
                self.toast(f"could not open {os.path.basename(path)}: {exc}")
            self.new_document(archive=False)
            return
        self.load_state(state, media)
        draft = os.path.abspath(path) == os.path.abspath(self.draft_path())
        self.path = None if draft else os.path.abspath(path)
        self._ready = True
        self._titled()
        if not quiet:
            self.toast(f"opened {os.path.basename(path)}")
        QtCore.QTimer.singleShot(0, self.focus_text)

    def new_document(self, archive: bool = True):
        self.autosave()
        if archive and self.path is None and self.draft_path().exists() and \
                (self.doc.toPlainText().strip() or any(t.alive for t in self.things.values())):
            drafts = self.home / "drafts"
            drafts.mkdir(exist_ok=True)
            target = drafts / time.strftime("draft-%Y%m%d-%H%M%S.ream")
            os.replace(self.draft_path(), target)
            self.toast(f"old draft filed in {drafts}")
        keep_format = asdict(self.fmt) if archive else None
        self.load_state({"text": "", "format": keep_format, "distress": self.distress.to_dict()}, {})
        self.path = None
        self._ready = True
        self._titled()
        QtCore.QTimer.singleShot(0, self.fit_layout)
        QtCore.QTimer.singleShot(0, self.focus_text)

    def browse_open(self):
        start = os.path.dirname(self.path) if self.path else os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open", start, "ream (*.ream)")
        if path:
            self.open_document(path)

    def save(self):
        if self.path is None:
            self.save_as()
            return
        self.autosave()
        self.toast(f"saved {self.path}")

    def save_as(self, path: str | None = None):
        if path is None:
            start = os.path.join(self.prefs.get("export_dir", os.path.expanduser("~/Documents")),
                                 self.stem() + project.SUFFIX)
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save as", start, "ream (*.ream)")
            if not path:
                return
        if not path.lower().endswith(project.SUFFIX):
            path += project.SUFFIX
        self.path = os.path.abspath(path)
        self.autosave()
        self._titled()
        self.toast(f"saved {self.path}")

    def _titled(self):
        name = os.path.basename(self.path) if self.path else "draft"
        self.setWindowTitle(f"ream — {name}")
        self.prefs["last"] = self.path or str(self.draft_path())
        self._write_prefs()

    def changed(self):
        if self._loading:
            return
        self.save_timer.start()
        if (self.distress_panel and self.distress_panel.isVisible()) or \
                (self.page_panel and self.page_panel.isVisible()):
            self._panel_timer.start()
        self._refresh_ghosts()
        if self.live():
            self._schedule_live()
        elif self.preview is not None:
            self.hide_preview()             # never leave a stale picture over the page
        self.view.viewport().update()

    def autosave(self):
        self.save_timer.stop()
        if self._loading or not self._ready:
            return
        state, media = self.state()
        try:
            project.save(self.path or str(self.draft_path()), state, media)
        except OSError as exc:
            self.toast(f"could not save: {exc}")

    # -- palette -------------------------------------------------------------
    def open_palette(self, global_pos: QtCore.QPoint | None = None, text: str = ""):
        """The palette always opens in the middle of the window.  Things it
        adds (images, paste) still land where the pointer was."""
        pointer = self.view.mapFromGlobal(global_pos or QtGui.QCursor.pos())
        self.palette_at = (self.view.mapToScene(pointer)
                           if self.view.viewport().rect().contains(pointer) else None)
        centre = self.view.mapToGlobal(self.view.viewport().rect().center())
        self.palette.popup(centre, text, centred=True)

    def caption(self) -> str:
        words = len(self.doc.toPlainText().split())
        name = os.path.basename(self.path) if self.path else "draft"
        mark = f"distress · {self.distress.style}" if self.distress.enabled else "clean"
        profile = self.active_profile()
        if profile:
            mark += f" · {profile}{' *' if self.profile_dirty() else ''}"
        return f"{name} · page {self.page + 1} of {self.pages_shown()} · {words} words · {mark}"

    def commands(self) -> list[Command]:
        C = Command
        d, f = self.distress, self.fmt
        dot = "●"
        out = [
            C("export pdf", self.export_pdf, "⌘E", "save print distressed"),
            C("export pdf · clean", partial(self.export_pdf, True), "⇧⌘E", "vector no distress"),
            C("export png pages", self.export_png, "", "images raster"),
            C("distress panel", self.toggle_distress_panel, "⌘D", "sliders live preview dial"),
            C("page panel", self.toggle_page_panel, "⌘L",
              "sliders margins line spacing paragraph size background canvas colour paper"),
            C("distress images off" if self.distress.images else "distress images on",
              partial(self.set_distress_images, not self.distress.images),
              "on" if self.distress.images else "off", "pictures pdf clean"),
            C("distress view off" if self.distress_view else "distress view",
              self.toggle_distress_view, "⇧⌘D", "see write live preview distressed page"),
            C("ink", None, f"{self.fmt.ink:g} %", "darkness ribbon fade tone", fill="ink "),
            C("distress on" if not d.enabled else "distress off", self.toggle_distress,
              "off" if not d.enabled else "on", "toggle"),
        ]
        out += [C(f"style · {s}", partial(self.set_style, s), dot if s == d.style else "",
                  "distress texture look") for s in distress.edge_styles()]
        out += [C(f"fade texture · {s}", partial(self.set_fade_style, s),
                  dot if s == d.fade_style else "", "distress wear") for s in distress.fade_styles()]
        out += [C(name, None, f"{getattr(d, name):g}", f"distress {spec[2]}", fill=f"{name} ")
                for name, spec in distress.PARAMS.items()]
        out += [C("reset distress", self.reset_distress, "", "defaults")]
        out += [
            C("add image or pdf", self.browse_files, "⌘O", "import place insert"),
            C("new page", self.new_page, "⌘↵", "page break"),
            C("next page", partial(self.turn_page, 1), "⌘→", "turn"),
            C("previous page", partial(self.turn_page, -1), "⌘←", "turn back"),
            C("go to page", None, f"{self.page + 1}", "jump", fill="page "),
        ]
        out += [C(f"page size · {name}", partial(self.set_format, page=name),
                  dot if name == f.page else "", "paper format") for name in style.PAGE_SIZES]
        out += [C(f"paper · {name}", partial(self.set_format, paper=name),
                  dot if name == f.paper else "", "colour stock") for name in style.PAPERS]
        out += [C(f"font · {face}", partial(self.set_format, font=face),
                  dot if face == self.face() else "", "typeface") for face in style.faces()]
        out += [
            C("size", None, f"{f.size:g} pt", "font text", fill="size "),
            C("line", None, f"{f.line:g} %", "line height leading spacing", fill="line "),
            C("para", None, f"{f.para:g} pt", "paragraph spacing space after", fill="para "),
            C("margin", None, f"{f.margin:g} pt", "page sides left right", fill="margin "),
            C("head", None, f"{f.head:g} pt", "margin top bottom page", fill="head "),
            C("canvas colour…", self._pick_canvas, self.canvas_colour(), "background color"),
            C("paper colour…", self._pick_paper, self.paper().name(), "page stock color"),
            C("grain", None, f"{self.fmt.grain:g} %", "paper stock amount opacity tooth",
              fill="grain "),
            C("stock scale", None, f"{self.fmt.stock_scale:g} %", "paper texture size zoom",
              fill="stock "),
            *[C(f"stock blend · {mode}", partial(self.set_blend, mode),
                "●" if mode == self.blend_mode() else "", "paper blend mode overlay multiply")
              for mode in papers.BLENDS],
            C("paper stock · flat", partial(self.set_texture, ""),
              "●" if not self.stock() else "", "texture none plain"),
            *[C(f"paper stock · {label}", partial(self.set_texture, key),
                "●" if key == self.stock() else "", "texture texturelabs grain")
              for key, label in papers.available()],
            C("show paper folder", lambda: (papers.folder().mkdir(parents=True, exist_ok=True),
                                            QtGui.QDesktopServices.openUrl(
                                                QtCore.QUrl.fromLocalFile(str(papers.folder())))),
              "", "stock textures add your own"),
            C("dpi", None, f"{f.dpi:g}", "export resolution", fill="dpi "),
        ]
        out += [C(f"theme · {name}", partial(self._set_theme, name),
                  dot if name == self.theme else "", "canvas colour") for name in style.THEMES]
        out += [
            C("write mode off" if self.write_mode else "write mode", self.toggle_write_mode, "⇧⌘F",
              "focus typewriter zoom centre scroll follow writing"),
            C("write zoom", None, f"{self.write_zoom() * 100:.0f} %", "write mode zoom size",
              fill="write "),
            C("fit page", self.fit_layout, "⌘0", "zoom view spread all"),
            C("actual size", self.actual_size, "", "zoom 100"),
            C("one page", partial(self.set_layout, "single"), "⌘1", "single view layout"),
            C("spread", partial(self.set_layout, "spread"), "⌘2",
              "two pages book facing view layout double"),
            C("all pages", partial(self.set_layout, "all"), "⌘3",
              "expand grid overview every page view layout"),
            C("fit everything", self.fit_all, "⇧⌘0", "zoom canvas all"),
        ]
        if self.selection():
            turn = self.selection()[0].rotation()
            out += [
                C("rotate 90° right", partial(self.rotate_selected, 90), "]", "turn clockwise"),
                C("rotate 90° left", partial(self.rotate_selected, -90), "[", "turn counter"),
                C("rotate", None, f"{turn:g}°", "angle turn", fill="rotate "),
                C("straighten", partial(self.set_rotation, 0), "", "rotation reset level"),
            ]
            out += [
                C("delete selected", self.delete_selection, "⌫", "remove image"),
                C("duplicate", self.duplicate_selection, "⌥ drag", "copy clone"),
                C("mirror ↔", partial(self.mirror_selection, True), "", "flip horizontal"),
                C("mirror ↕", partial(self.mirror_selection, False), "", "flip vertical"),
                C("arrange", self.arrange_selection, "", "lay out rows grid tidy"),
                C("merge", self.merge_selection, "", "flatten combine images"),
                C("reset mask", self.reset_masks, "", "restore background removal undo"),
                C("bring forward", partial(self.restack, "forward"), "⌘]", "order raise up"),
                C("send backward", partial(self.restack, "backward"), "⌘[",
                  "order lower down behind words"),
                C("bring to front", partial(self.restack, "front"), "⇧⌘]", "order raise top"),
                C("send to back", partial(self.restack, "back"), "⇧⌘[",
                  "order lower bottom behind text words"),
                C("unpin from page", self.unpin_selected, "", "detach canvas"),
                C("fit to text width", self.fit_width, "", "size image"),
                C("natural size", self.natural_size, "", "size image reset"),
            ]
        out += [
            C("save profile", self.save_profile,
              (self.active_profile() or "new") + (" *" if self.profile_dirty() else "") + "  ⌥⌘S",
              "settings preset store keep"),
            C("save profile as…", None, "", "settings preset name", fill="save profile "),
            C("new profile", self.new_profile, "", "settings preset add"),
            *[C(f"profile · {name}", partial(self.switch_profile, name),
                ("● " if name == self.active_profile() else "") + (f"⌥⌘{n}" if n <= 9 else ""),
                "switch settings preset load")
              for n, name in enumerate(self.profile_names(), 1)],
            *[C(f"delete profile · {name}", partial(self.delete_profile, name), "", "remove preset")
              for name in self.profile_names()],
            *[C(title, run, hint, keywords) for p, host in self.plugins
              if getattr(p, "active", False) for title, run, hint, keywords in host.commands],
            *[C(f"plugin · {p.title or p.name}", partial(self.switch_plugin, p),
                "on" if getattr(p, "active", False) else "off", f"plugins {p.where}")
              for p, _host in self.plugins],
            C("show plugins folder", self._show_plugins_folder, "", "plugins add your own"),
            C("new document", self.new_document, "⌘N", "blank clear"),
            C("open…", self.browse_open, "⇧⌘O", "load project"),
            C("save", self.save, "⌘S", "project"),
            C("save as…", self.save_as, "⇧⌘S", "project"),
            C("show drafts", lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self.home))), "", "folder autosave"),
            C("word count", lambda: self.toast(
                f"{len(self.doc.toPlainText().split())} words · "
                f"{len(self.doc.toPlainText())} characters"), "", "stats"),
            C("quit", self.close, "⌘Q", "exit"),
        ]
        return out

    def dynamic(self, text: str) -> list[Command]:
        named = re.match(r"^\s*save profile\s+(\S.*?)\s*$", text, re.IGNORECASE)
        if named:
            name = named.group(1)
            hint = "replace" if name in self._profiles else "new"
            return [Command(f"save profile → {name}", partial(self.save_profile, name), hint,
                            key="save-profile-as")]
        colour = re.match(r"^\s*(canvas|background|paper)\s+(#?[0-9a-f]{3}|#?[0-9a-f]{6})\s*$",
                          text.lower())
        if colour:
            value = "#" + colour.group(2).lstrip("#")
            if QtGui.QColor(value).isValid():
                if colour.group(1) == "paper":
                    return [Command(f"paper → {value}", partial(self.set_paper, value),
                                    self.paper().name(), key="set:paper")]
                return [Command(f"canvas → {value}", partial(self.set_canvas, value),
                                self.canvas_colour(), key="set:canvas")]
        match = re.match(r"^\s*([a-z][a-z ]*?)\s*(-?\d+(?:\.\d+)?)\s*$", text.lower())
        if not match:
            return []
        word, value = match.group(1).strip(), float(match.group(2))
        out = []
        if "write".startswith(word) and len(word) >= 2:
            out.append(Command(f"write zoom → {value:g}%", partial(self.set_write_zoom, value / 100.0),
                               f"now {self.write_zoom() * 100:.0f}%", key="set:write"))
        names = list(distress.PARAMS) + list(FORMAT_PARAMS) + ["page"]
        if self.selection():
            names.append("rotate")
        for name in names:
            if not name.startswith(word):
                continue
            if name == "page":
                now = self.page + 1
            elif name == "rotate":
                now = self.selection()[0].rotation()
            elif name in distress.PARAMS:
                now = getattr(self.distress, name)
            else:
                now = getattr(self.fmt, {"stock": "stock_scale"}.get(name, name))
            out.append(Command(f"{name} → {value:g}", partial(self.set_param, name, value),
                               f"now {now:g}", key=f"set:{name}"))
        return out

    def switch_plugin(self, which):
        on = not getattr(which, "active", False)
        try:
            plugin.switch(self, which, on)
            self.toast(f"plugin · {which.title or which.name} {'on' if on else 'off'}")
        except Exception as exc:
            self.toast(f"plugin · {which.name} failed: {exc}")
        self.view.viewport().update()

    def _show_plugins_folder(self):
        folder = plugin.user_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def _set_theme(self, name: str):
        """A theme sets the canvas colour too."""
        self.theme = name
        self.prefs.pop("canvas", None)
        self.apply_theme()
        if self.page_panel is not None:
            self.page_panel.refresh()

    def _set_edge_theme(self, name: str):
        """Only the page edge and greys; the canvas colour stays."""
        self.theme = name
        self.apply_theme()

    def _pick_canvas(self):
        colour = QtWidgets.QColorDialog.getColor(style.qc(self.canvas_colour()), self, "canvas")
        if colour.isValid():
            self.set_canvas(colour.name())

    def _pick_paper(self):
        colour = QtWidgets.QColorDialog.getColor(self.paper(), self, "paper")
        if colour.isValid():
            self.set_paper(colour.name())

    def _shortcuts(self):
        bindings = [
            ("Ctrl+E", self.export_pdf), ("Ctrl+Shift+E", partial(self.export_pdf, True)),
            ("Ctrl+D", self.toggle_distress_panel), ("Ctrl+L", self.toggle_page_panel),
            ("Ctrl+Shift+D", self.toggle_distress_view),
            ("Ctrl+Alt+S", self.save_profile),
            *[(f"Ctrl+Alt+{n}", partial(self.switch_profile_number, n)) for n in range(1, 10)],
            ("Ctrl+O", self.browse_files),
            ("Ctrl+Shift+O", self.browse_open), ("Ctrl+S", self.save),
            ("Ctrl+Shift+S", self.save_as), ("Ctrl+N", self.new_document),
            ("Ctrl+0", self.fit_layout), ("Ctrl+Shift+0", self.fit_all),
            ("Ctrl+1", partial(self.set_layout, "single")),
            ("Ctrl+2", partial(self.set_layout, "spread")),
            ("Ctrl+3", partial(self.set_layout, "all")),
            ("Ctrl+Return", self.new_page),
            ("Ctrl+=", partial(self.zoom_step, 1.25)), ("Ctrl++", partial(self.zoom_step, 1.25)),
            ("Ctrl+-", partial(self.zoom_step, 0.8)), ("Ctrl+Q", self.close),
            ("Ctrl+Shift+F", self.toggle_write_mode),
        ]
        for keys, slot in bindings:
            action = QtWidgets.QAction(self)
            action.setShortcut(QtGui.QKeySequence(keys))
            action.setShortcutContext(QtCore.Qt.WindowShortcut)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            self.addAction(action)

    # -- window --------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.focus_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "write_mode", False):
            QtCore.QTimer.singleShot(0, lambda: self._write_follow(force=True, animate=False))
        for panel in (self.distress_panel, self.page_panel):
            if panel is not None and panel.isVisible():
                panel.keep_inside()

    def closeEvent(self, event):
        for which, host in getattr(self, "plugins", []):
            if getattr(which, "active", False):
                try:
                    which.teardown()
                except Exception:
                    pass
                for timer in host.timers:
                    timer.stop()
        self._pool.shutdown(wait=False)
        self.autosave()
        self.prefs["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        self.prefs["last"] = self.path or str(self.draft_path())
        self._write_prefs()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ream", description=__doc__.strip().split("\n")[0])
    parser.add_argument("paths", nargs="*", help="a .ream document, images, PDFs or folders")
    parser.add_argument("--theme", choices=sorted(style.THEMES))
    parser.add_argument("--version", action="version", version=f"ream {__version__}")
    args = parser.parse_args(argv)

    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("ream")
    window = Ream([os.path.abspath(p) for p in args.paths], theme=args.theme)
    window.show()
    window.raise_()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
