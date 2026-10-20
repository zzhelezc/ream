"""
Timings for ream's slow paths - run it before and after a change:

    QT_QPA_PLATFORM=offscreen uv run python tests/bench.py

Uses the tests' throwaway home, never yours.
"""
import os
import sys
import time
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_core as t  # noqa: E402  (sets REAM_HOME / REAM_CACHE to a throwaway folder)

import numpy as np  # noqa: E402
from PyQt5 import QtCore, QtGui  # noqa: E402

from ream import distress, export, wear  # noqa: E402


def timed(label, run, repeat=1):
    run()                                                   # warm caches
    start = time.perf_counter()
    for _ in range(repeat):
        run()
    print(f"{label:40s} {(time.perf_counter() - start) / repeat * 1000:8.0f} ms")


w = t.fresh()
t.type_paragraphs(w, 40)
w.distress.enabled = True
layers = export.page_layers(w.sheet, 0, 300, w.ink())
timed("distress a page, 300 dpi", lambda: distress.compose(layers, (250, 248, 240), w.distress, 300), 3)
misfire = replace(w.distress, misfire=60, bleed=40)
timed("distress a page, misfire + bleed", lambda: distress.compose(layers, (250, 248, 240), misfire, 300))
timed("export 10 distressed pages (PDF)",
      lambda: w.export_pdf(path=os.path.join(t.TMP, "bench.pdf"), pages=list(range(10))))
big = np.zeros((3000, 4000, 4), np.uint8)
big[..., 3] = 255
timed("tear a 4000x3000 image", lambda: wear.apply_tear(big, dict(wear.DEFAULT_TEAR), 10.0), 3)
plugin = [p for p, _h in w.plugins if p.name == "wear"][0]
image = QtGui.QImage(4000, 3000, QtGui.QImage.Format_ARGB32)
image.fill(QtGui.QColor("#335599"))
thing = w.place_qimage(image, QtCore.QRectF(0, 0, 400, 300), "big")
w.select([thing])
plugin.tear()
timed("tear slider step (draft)", lambda: plugin.retear(draft=True), 5)
w.close()
