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

**export…** writes a folder: `01.jpg`, `02.jpg`, … (post them in that order,
the fitted full picture last), and `full.jpg` when asked for.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import export, style
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
        cells = self.plugin.posted(p)
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
        for n in range(p.slides):
            r, col = divmod(n, across)
            target = QtCore.QRectF(left0 + col * sw, top0 + r * (sh + 26), sw, sh)
            source = QtCore.QRectF(n * p.slide_w * ratio, 0, p.slide_w * ratio, picture.height())
            painter.drawImage(target, picture, source)
            painter.setPen(QtGui.QPen(meta, 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(target)
            painter.drawText(QtCore.QRectF(target.left(), target.bottom() + 3, sw, 18),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, f"{n + 1:02d}")
        if cells > p.slides:
            # the whole picture, fitted into one more slide of the same shape
            r, col = divmod(p.slides, across)
            target = QtCore.QRectF(left0 + col * sw, top0 + r * (sh + 26), sw, sh)
            painter.fillRect(target, self.plugin.background())
            painter.drawImage(self.plugin.fit_rect(picture.width(), picture.height(), target), picture)
            painter.setPen(QtGui.QPen(meta, 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(target)
            painter.drawText(QtCore.QRectF(target.left(), target.bottom() + 3, sw, 18),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, f"{cells:02d} · the whole picture")
        s = self.plugin.s
        words = [f"{cells} slide{'s' if cells != 1 else ''}", f"{s['shape']} · {p.slide_w}×{p.slide_h}",
                 s["mode"], f"full picture {p.width}×{p.slide_h}"]
        if cells > MAX_SLIDES:
            words.append(f"Instagram takes {MAX_SLIDES} a post: this makes {math.ceil(cells / MAX_SLIDES)} posts")
        painter.setPen(meta)
        painter.drawText(QtCore.QRectF(self.rect()).adjusted(0, 16, 0, 0), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                         "   ·   ".join(words))
        painter.drawText(QtCore.QRectF(self.rect()).adjusted(0, 0, 0, -16),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
                         "the slides join edge to edge: swipe through them as one picture   ·   Esc back")

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

    def page_images(self, p: Plan, scale: float) -> dict[int, QtGui.QImage]:
        """Every placed page, rendered as big as it is placed (x scale)."""
        window = self.host.window
        sheet = window.sheet
        if not p.placed:
            return {}
        px_h = max(8.0, p.placed[0].rect.height() * scale)
        dpi = max(12.0, px_h / (sheet.H / 72.0))
        settings = self.settings()
        pages = sorted({pl.page for pl in p.placed})
        args = (dpi, settings, window.paper(), window.ink(), window.density(), window.paper_stock())
        if settings.enabled and len(pages) > 1:
            return dict(export.distressed_pages(sheet, pages, *args))
        return {page: export.final_page(sheet, page, *args) for page in pages}

    def picture(self, scale: float = 1.0) -> QtGui.QImage:
        """The full picture - every page in place - at `scale` of full size."""
        window = self.host.window
        p = self.plan()
        key = (round(scale, 3), tuple(sorted(self.s.items())), self.pages_text, window.doc.revision(),
               window.things_key(), tuple(vars(window.fmt).items()),
               tuple(window.distress.to_dict().items()), window.canvas_colour())
        if key in self._pictures:
            return self._pictures[key]
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
        if len(self._pictures) > 6:
            self._pictures.clear()
        self._pictures[key] = image
        return image

    def slides(self, picture: QtGui.QImage | None = None) -> list[QtGui.QImage]:
        """The carousel: the full picture cut edge to edge into slides."""
        p = self.plan()
        picture = picture or self.picture()
        return [picture.copy(n * p.slide_w, 0, p.slide_w, p.slide_h) for n in range(p.slides)]

    def full_last(self) -> bool:
        return self.s["full"] in ("last slide", "last slide + file")

    def posted(self, p: Plan | None = None) -> int:
        """How many slides the carousel has: the cut ones, and the fitted full picture."""
        p = p or self.plan()
        return p.slides + (1 if self.full_last() and p.slides else 0)

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
        picture = picture or self.picture()
        slide = QtGui.QImage(p.slide_w, p.slide_h, QtGui.QImage.Format_RGB32)
        slide.fill(self.background())
        painter = QtGui.QPainter(slide)
        painter.setRenderHints(QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.Antialiasing)
        painter.drawImage(self.fit_rect(picture.width(), picture.height(),
                                        QtCore.QRectF(0, 0, p.slide_w, p.slide_h)), picture)
        painter.end()
        return slide

    def carousel(self, picture: QtGui.QImage | None = None) -> list[QtGui.QImage]:
        """Every image to post, in order."""
        picture = picture or self.picture()
        out = self.slides(picture)
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
        if not p.slides:
            self.host.toast("instagram · no pages to post")
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
                picture.save(os.path.join(folder, f"full.{ext}"), None, 95)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        count = self.posted(p)
        posts = math.ceil(count / MAX_SLIDES)
        self.host.toast(f"instagram · {count} slides{f' ({posts} posts)' if posts > 1 else ''} → {folder}")
        return folder
