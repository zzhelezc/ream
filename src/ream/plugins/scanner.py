"""
Scanner: a slit-scanner on the canvas, after snitscanner.xyz.

"scanner" in the palette opens three things:

- **A · scan bed**, a frame on the canvas.  Put anything inside it - images,
  PDF pages, text blocks, a corner of the page - and it gets scanned.
- **B · scan result**, a frame of the same size that fills in as the scan
  line passes.  Drag out of it to pick the scan up as a new image.
- **scanner**, a panel with the settings.

How it scans: a line crosses the bed; on every tick the strip of canvas
under the line is copied into the result at the same place.  Move things in
the bed while the line is on them and they smear - that is the slit-scan.

| setting   | does |
| --------- | ---- |
| direction | down the bed, or across it |
| speed     | 1 is a pass in eight seconds |
| loop      | start again at the end |
| ink       | colour; xerox (hard toner, contrast); dither (ordered, in ink and paper) |
| tone      | lighter ... darker |
| grain     | fine ... coarse: the size of noise, toner and dither cells |
| layering  | replace each pass, or stack passes with darken / multiply / screen |
| noise     | grain over the scan |
| paper     | what empty bed scans as, and the paper xerox and dither print on |
| dpi       | the result's resolution |
"""
from __future__ import annotations

import time

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from .. import style
from ..plugin import Plugin as Base

PAPERS = {"white": "#ffffff", "cream": "#f4efe2", "newsprint": "#e8e5da",
          "recycled": "#e6e1d3", "bond": "#f7f6f1"}
TONER = np.array([0.07, 0.07, 0.08], np.float32)
BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                  np.float32) + 0.5) / 16.0
DEFAULTS = {"direction": "down", "speed": 1.0, "loop": False, "ink": "colour", "tone": 0.0,
            "grain": 2.0, "layering": "replace", "blend": "darken", "noise": 25.0,
            "paper": "white", "dpi": 150.0, "bed": [360.0, 260.0], "aspect": "free"}
# shapes for the bed (and so the result): width / height; None: free
ASPECTS = {"free": None, "1:1": 1.0, "4:5": 4 / 5, "3:4": 3 / 4, "2:3": 2 / 3, "3:2": 3 / 2,
           "4:3": 4 / 3, "16:9": 16 / 9, "9:16": 9 / 16, "A4 portrait": 1 / 2 ** 0.5,
           "A4 landscape": 2 ** 0.5, "the page": "page", "a carousel slide": "slide"}
LINE = QtGui.QColor("#2f4bd8")


class Plugin(Base):
    name = "scanner"
    title = "scanner"

    def setup(self, host):
        self.host = host
        self.s = {**DEFAULTS, **host.settings}
        self.buffer: np.ndarray | None = None
        self.image: QtGui.QImage | None = None
        self.pos = 0.0
        self.passes = 0
        self.running = False
        self._last = 0.0
        self.rng = np.random.default_rng()

        w, h = self.s["bed"]
        self.bed = host.frame("A · scan bed", QtCore.QSizeF(w, h),
                              paint_content=self.paint_bed, on_change=self.bed_changed,
                              on_context=self.open_panel)
        self.result = host.frame("B · scan result", QtCore.QSizeF(w, h),
                                 paint_content=self.paint_result, drag_out=self.take,
                                 on_change=self.result_changed, on_context=self.open_panel,
                                 fill=True)
        self.panel = self.build_panel()
        self.timer = host.timer(30, self.tick)
        # while the scanner is open, a tap of Space plays and stops it
        host.space(lambda: self.bed.isVisible(), self.space_tap)

        host.command("scanner", self.toggle, "", "snit slit scan scanner bed open")
        host.command("scanner: scan / stop", self.toggle_scan, "", "start run")
        host.command("scanner: clear result", self.clear, "", "reset")
        host.command("scanner: result to canvas", self.to_canvas, "", "place image drop")
        host.command("scanner: export png", self.export_png, "", "save image")

    def teardown(self):
        self.save()

    # -- opening ---------------------------------------------------------------
    def open_panel(self):
        """Right-click on either frame: the scanner's settings."""
        self.panel.open()
        self.panel.raise_()

    def toggle(self):
        if self.bed.isVisible():
            self.close()
        else:
            self.open()

    def open(self):
        """The bed opens where the pointer is (or where the palette was
        opened), the result beside it."""
        window = self.host.window
        seen = self.host.visible_rect()
        at = window.palette_at or window.pointer_scene()
        if at is None or not seen.contains(at):
            at = seen.center()
        gap = 40.0
        left, top = at.x() - self.bed.w / 2, at.y() - self.bed.h / 2
        self.bed.setPos(left, top)
        self.result.setPos(left + self.bed.w + gap, top)
        self.lock_aspect()
        self.bed.show()
        self.result.show()
        if self.buffer is None:
            self.clear()
        self.panel.open()
        self.host.toast("scanner · put things in the bed, then scan")

    def close(self):
        self.stop()
        self.save()
        self.bed.hide()
        self.result.hide()
        self.panel.hide()
        self.host.view.viewport().update()

    def save(self):
        self.s["bed"] = [self.bed.w, self.bed.h]
        self.s["at"] = [[self.bed.x(), self.bed.y()], [self.result.x(), self.result.y()]]
        self.host.settings.clear()
        self.host.settings.update(self.s)
        self.host.save_settings()

    # -- the panel ---------------------------------------------------------------
    def build_panel(self):
        panel = self.host.panel("scanner", on_close=self.close)
        s = self.s

        def put(key, refresh=False):
            def setter(value):
                s[key] = value
                if refresh:
                    self.clear()
            return setter

        panel.links("", [(lambda: "■ stop" if self.running else "▶ scan", self.toggle_scan),
                         ("clear", self.clear)])
        panel.toggle("direction", lambda: s["direction"] == "down",
                     lambda v: (put("direction")("down" if v else "across"), self.restart()),
                     on="↓ down", off="→ across")
        panel.slider("speed", 0.1, 5.0, lambda: s["speed"], put("speed"), step=0.1, default=1.0)
        panel.toggle("loop", lambda: s["loop"], put("loop"))
        panel.choice("ink", lambda: ["colour", "xerox", "dither"], lambda: s["ink"], put("ink"))
        panel.slider("tone", -100, 100, lambda: s["tone"], put("tone"), step=5, default=0)
        panel.slider("grain", 1, 8, lambda: s["grain"], put("grain"), default=2)
        panel.choice("layering", lambda: ["replace", "stacked"], lambda: s["layering"],
                     put("layering"))
        panel.choice("blend", lambda: ["darken", "multiply", "screen"], lambda: s["blend"],
                     put("blend"))
        panel.slider("noise", 0, 100, lambda: s["noise"], put("noise"), unit="%", default=25)
        panel.choice("paper", lambda: list(PAPERS), lambda: s["paper"], put("paper", refresh=True))
        panel.slider("dpi", 72, 300, lambda: s["dpi"], put("dpi", refresh=True), step=6,
                     default=150)
        panel.choice("shape", lambda: list(ASPECTS), lambda: s.get("aspect", "free"), self.set_aspect)
        panel.buttons([("to canvas", self.to_canvas), ("export png", self.export_png)])
        return panel

    # -- scanning ----------------------------------------------------------------
    def size_px(self) -> tuple[int, int]:
        k = self.s["dpi"] / 72.0
        return max(1, int(round(self.bed.w * k))), max(1, int(round(self.bed.h * k)))

    def length(self) -> int:
        w, h = self.size_px()
        return h if self.s["direction"] == "down" else w

    def paper(self) -> np.ndarray:
        colour = QtGui.QColor(PAPERS.get(self.s["paper"], "#ffffff"))
        return np.array([colour.red(), colour.green(), colour.blue()], np.float32) / 255.0

    def clear(self):
        w, h = self.size_px()
        self.buffer = np.empty((h, w, 3), np.uint8)
        self.buffer[...] = np.round(self.paper() * 255).astype(np.uint8)
        self.image = None
        self.pos, self.passes = 0.0, 0
        self.result.update()
        self.bed.update()

    def restart(self):
        self.pos, self.passes = 0.0, 0
        self.bed.update()

    def space_tap(self):
        self.toggle_scan()
        self.host.toast("scanning · Space to stop" if self.running else "scanner · stopped · Space goes on")

    def toggle_scan(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        if not self.bed.isVisible():
            self.open()
        if self.buffer is None or self.buffer.shape[:2] != self.size_px()[::-1]:
            self.clear()
        if self.pos >= self.length():
            self.pos = 0.0
            self.passes += 1
        self.running = True
        self._last = time.monotonic()
        self.timer.start()
        self.panel.refresh()

    def stop(self):
        self.running = False
        self.timer.stop()
        self.panel.refresh()
        self.bed.update()

    def tick(self):
        now = time.monotonic()
        dt, self._last = min(0.2, now - self._last), now
        length = self.length()
        new = min(float(length), self.pos + length * dt * self.s["speed"] / 8.0)
        a, b = int(self.pos), int(new)
        if b > a:
            self.scan_strip(a, b)
        self.pos = new
        self.bed.update()
        if self.pos >= length:
            if self.s["loop"]:
                self.pos, self.passes = 0.0, self.passes + 1
            else:
                self.stop()
                self.host.toast("scanner · done · drag the result out")

    def scan_strip(self, a: int, b: int):
        """Copy the canvas under the line, rows (or columns) a..b, into the result."""
        w, h = self.size_px()
        k = 72.0 / self.s["dpi"]
        bed = self.bed.scene_rect()
        down = self.s["direction"] == "down"
        if down:
            rect = QtCore.QRectF(bed.left(), bed.top() + a * k, bed.width(), (b - a) * k)
            size = QtCore.QSize(w, b - a)
        else:
            rect = QtCore.QRectF(bed.left() + a * k, bed.top(), (b - a) * k, bed.height())
            size = QtCore.QSize(b - a, h)
        rgba = self.host.render(rect, self.s["dpi"], size).astype(np.float32) / 255.0
        alpha = rgba[..., 3:4]
        rgb = self.paper() * (1.0 - alpha) + rgba[..., :3] * alpha
        strip = self.ink(rgb, a if down else 0, 0 if down else a)
        region = (slice(a, b), slice(None)) if down else (slice(None), slice(a, b))
        if self.s["layering"] == "stacked" and self.passes > 0:
            before = self.buffer[region].astype(np.float32) / 255.0
            mode = self.s["blend"]
            if mode == "multiply":
                strip = before * strip
            elif mode == "screen":
                strip = 1.0 - (1.0 - before) * (1.0 - strip)
            else:
                strip = np.minimum(before, strip)
        self.buffer[region] = np.clip(strip * 255.0 + 0.5, 0, 255).astype(np.uint8)
        self.image = None
        self.result.update()

    def ink(self, rgb: np.ndarray, oy: int, ox: int) -> np.ndarray:
        """Colour, xerox or dither, with tone and noise; cells sized by grain
        and placed by absolute position, so strips join seamlessly."""
        s = self.s
        h, w = rgb.shape[:2]
        cell = max(1, int(round(s["grain"])))
        gamma = 2.0 ** (s["tone"] / 100.0 * 1.4)          # darker > 1
        amount = s["noise"] / 100.0
        noise = 0.0
        if amount > 0:
            gh, gw = h // cell + 2, w // cell + 2
            grains = self.rng.standard_normal((gh, gw)).astype(np.float32)
            noise = np.repeat(np.repeat(grains, cell, 0), cell, 1)
            sy, sx = oy % cell, ox % cell
            noise = noise[sy:sy + h, sx:sx + w]
        lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
        paper = self.paper()
        if s["ink"] == "colour":
            out = np.clip(rgb, 0.0, 1.0) ** gamma
            if amount > 0:
                out = out + (noise * amount * 0.12)[..., None]
            return np.clip(out, 0.0, 1.0)
        v = np.clip(lum, 0.0, 1.0) ** gamma
        if s["ink"] == "xerox":
            v = (v - 0.5) * 3.0 + 0.5
            if amount > 0:
                v = v + noise * amount * 0.35
            v = np.clip(v, 0.0, 1.0)
            v = v * v * (3.0 - 2.0 * v)                    # toner: hard, a little soft at the edge
        else:
            if amount > 0:
                v = v + noise * amount * 0.15
            ys = ((np.arange(oy, oy + h) // cell) % 4)[:, None]
            xs = ((np.arange(ox, ox + w) // cell) % 4)[None, :]
            v = (v > BAYER[ys, xs]).astype(np.float32)
        return TONER + (paper - TONER) * v[..., None]

    # -- the frames ----------------------------------------------------------------
    def paint_bed(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        if not (self.running or 0 < self.pos < self.length()):
            return
        k = 72.0 / self.s["dpi"]
        at = self.pos * k
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        glow = QtGui.QColor(LINE)
        glow.setAlpha(36)
        pen = QtGui.QPen(LINE, 0)                         # hairline at any zoom
        if self.s["direction"] == "down":
            painter.fillRect(QtCore.QRectF(rect.left(), at - 4, rect.width(), 8), glow)
            painter.setPen(pen)
            painter.drawLine(QtCore.QPointF(rect.left(), at), QtCore.QPointF(rect.right(), at))
        else:
            painter.fillRect(QtCore.QRectF(at - 4, rect.top(), 8, rect.height()), glow)
            painter.setPen(pen)
            painter.drawLine(QtCore.QPointF(at, rect.top()), QtCore.QPointF(at, rect.bottom()))

    def qimage(self) -> QtGui.QImage | None:
        if self.buffer is None:
            return None
        if self.image is None:
            h, w = self.buffer.shape[:2]
            data = np.ascontiguousarray(self.buffer)
            self.image = QtGui.QImage(data.data, w, h, 3 * w, QtGui.QImage.Format_RGB888).copy()
        return self.image

    def paint_result(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        image = self.qimage()
        if image is not None:
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            painter.drawImage(rect, image)

    def take(self, at: QtCore.QPointF) -> QtGui.QImage | None:
        """Dragging out of the result picks up a copy of the scan."""
        return self.qimage().copy() if self.qimage() is not None else None

    # -- the bed's shape -------------------------------------------------------------
    def ratio(self) -> float | None:
        value = ASPECTS.get(self.s.get("aspect", "free"))
        window = self.host.window
        if value == "page":
            return window.sheet.W / window.sheet.H
        if value == "slide":
            return window.carousel.slide_w / window.carousel.slide_h
        return value

    def lock_aspect(self):
        """Resizing keeps the chosen shape (free: any)."""
        self.bed.aspect = self.result.aspect = self.ratio()

    def set_aspect(self, name: str):
        """The bed (and the result) to a shape, keeping about the same area."""
        self.s["aspect"] = name
        ratio = self.ratio()
        self.lock_aspect()
        if ratio:
            area = self.bed.w * self.bed.h
            w, h = (area * ratio) ** 0.5, (area / ratio) ** 0.5
            self.bed.set_size(w, h)
            self.bed_changed()
            self.s["bed"] = [self.bed.w, self.bed.h]
            self.save()
            self.host.toast(f"scanner · {name} · {self.bed.w:.0f} × {self.bed.h:.0f} pt")

    def bed_changed(self):
        if (self.result.w, self.result.h) != (self.bed.w, self.bed.h):
            self.result.set_size(self.bed.w, self.bed.h)
            self.stop()
            self.clear()

    def result_changed(self):
        if (self.result.w, self.result.h) != (self.bed.w, self.bed.h):
            self.bed.set_size(self.result.w, self.result.h)   # the two stay one size
            self.stop()
            self.clear()

    # -- getting it out --------------------------------------------------------------
    def to_canvas(self):
        image = self.qimage()
        if image is None:
            return
        spot = self.result.scene_rect().translated(self.result.w + 40, 0)
        self.host.place_image(image.copy(), spot, "scan")
        self.host.toast("scanner · the scan is on the canvas")

    def export_png(self):
        image = self.qimage()
        if image is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.host.window, "Export scan",
                                                        "scan.png", "PNG (*.png)")
        if path:
            image.save(path if path.lower().endswith(".png") else path + ".png")
            self.host.toast(f"scanner · saved {path}")
