"""
End-to-end checks that drive the real window headless:

    QT_QPA_PLATFORM=offscreen uv run python tests/test_core.py

They use a throwaway home folder (REAM_HOME), never yours.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import traceback

TMP = tempfile.mkdtemp(prefix="ream-test-")
os.environ["REAM_HOME"] = os.path.join(TMP, "home")
os.environ["REAM_CACHE"] = os.path.join(TMP, "cache")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PyQt5 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

from ream import distress, export, project  # noqa: E402
from ream.app import Ream  # noqa: E402
from ream.page import Note  # noqa: E402

from PyQt5 import sip  # noqa: E402

sip.setdestroyonexit(False)
app = QtWidgets.QApplication([])
PARA = ("The refusal to labour is a weapon; a page is where it is written down. "
        "Each line is fed through the platen and struck in one pass. ") * 3


def pump(seconds: float = 0.35):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def fresh() -> Ream:
    for name in ("draft.ream", "prefs.json"):
        try:
            os.remove(os.path.join(os.environ["REAM_HOME"], name))
        except OSError:
            pass
    window = Ream([])
    window.layout = "single"
    window._place_sheet()
    window.resize(1100, 820)
    window.show()
    pump(0.1)
    window.fit_page()
    pump(0.05)
    return window


def type_paragraphs(window: Ream, count: int):
    cursor = window.sheet.text.textCursor()
    for n in range(count):
        cursor.insertText(f"{n + 1:02d}. {PARA}\n")
    window.sheet.text.setTextCursor(cursor)
    window.caret_moved()
    pump()


def view_point(window: Ream, scene_point: QtCore.QPointF) -> QtCore.QPoint:
    return window.view.mapFromScene(scene_point)


def wheel(window: Ream, at: QtCore.QPoint, dy: int, phase):
    event = QtGui.QWheelEvent(QtCore.QPointF(at), QtCore.QPointF(window.view.viewport().mapToGlobal(at)),
                              QtCore.QPoint(0, dy), QtCore.QPoint(0, dy * 2), QtCore.Qt.NoButton,
                              QtCore.Qt.NoModifier, phase, False)
    QtWidgets.QApplication.sendEvent(window.view.viewport(), event)


def drag(window: Ream, start: QtCore.QPoint, end: QtCore.QPoint):
    viewport = window.view.viewport()
    QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, start)
    for k in range(1, 9):
        p = start + (end - start) * (k / 8.0)
        QtWidgets.QApplication.sendEvent(viewport, QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove, QtCore.QPointF(p), QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, end)
    pump(0.05)


def make_png(path: str, colour: str = "#c33") -> str:
    image = QtGui.QImage(300, 200, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor(colour))
    image.save(path)
    return path


# -- the checks ---------------------------------------------------------------

def test_typing_turns_pages():
    w = fresh()
    assert w.sheet.text_pages() == 1
    type_paragraphs(w, 30)
    assert w.sheet.text_pages() >= 3, w.sheet.text_pages()
    assert w.page == w.sheet.caret_page() == w.sheet.text_pages() - 1
    # the strip shows exactly that page
    assert abs(w.sheet.offset - w.page * w.sheet.H) < 0.5
    # every line sits inside one page's margins: none straddles a page foot
    block = w.doc.begin()
    while block.isValid():
        top = w.doc.documentLayout().blockBoundingRect(block).top()
        layout = block.layout()
        for i in range(layout.lineCount()):
            line = layout.lineAt(i)
            y0, y1 = top + line.y(), top + line.y() + line.height()
            assert int(y0 // w.sheet.H) == int((y1 - 0.01) // w.sheet.H), (y0, y1)
        block = block.next()
    w.close()


def test_scrolling_pans_and_cmd_arrows_turn_pages():
    w = fresh()
    type_paragraphs(w, 30)
    w.flip(0)
    pump()
    w.view.set_zoom(2.0)
    w.view.centerOn(w.sheet.scene_page_rect().center())
    pump(0.05)
    centre = view_point(w, w.sheet.scene_page_rect().center())
    # a long scroll over the page pans the view and never turns it
    before = w.view.visible_scene_rect().center()
    wheel(w, centre, -40, QtCore.Qt.ScrollBegin)
    for _ in range(40):
        wheel(w, centre, -40, QtCore.Qt.ScrollUpdate)
    wheel(w, centre, 0, QtCore.Qt.ScrollEnd)
    pump()
    assert w.page == 0 and abs(w.sheet.offset) < 0.01
    assert w.view.visible_scene_rect().center().y() > before.y() + 100
    # Cmd+Right turns, and the caret comes to the new page's first line
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Right, QtCore.Qt.ControlModifier)
    pump()
    assert w.page == 1 and abs(w.sheet.offset - w.sheet.H) < 0.5
    assert w.sheet.caret_page() == 1
    QtTest.QTest.keyClicks(w.view, "here")             # writes on page 2, stays there
    pump()
    assert w.page == 1
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Left, QtCore.Qt.ControlModifier)
    pump()
    assert w.page == 0 and w.sheet.caret_page() == 0
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Left, QtCore.Qt.ControlModifier)
    assert w.page == 0                                # nothing before the first
    # past the last page waits a blank one, and no further
    for _ in range(w.sheet.pages() + 3):
        QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Right, QtCore.Qt.ControlModifier)
    pump()
    assert w.page == w.sheet.pages()
    # Iosevka is offered when installed
    from ream import style
    if style.installed("Iosevka"):
        assert "Iosevka" in style.faces()
        w.set_format(font="Iosevka")
        assert w.doc.defaultFont().family() == "Iosevka"
    w.close()

def test_drag_onto_page_pins_and_off_unpins_with_undo():
    w = fresh()
    page = w.sheet.scene_page_rect()
    png = make_png(os.path.join(TMP, "a.png"))
    w.add_files([png], QtCore.QPointF(page.right() + 300, page.center().y()))
    (thing,) = [t for t in w.things.values() if t.alive]
    assert not thing.pinned
    start = view_point(w, thing.sceneBoundingRect().center())
    end = view_point(w, page.center())
    drag(w, start, end)
    assert thing.pinned, "dropped on the page should pin it"
    assert thing.parentItem() is w.sheet.strip
    assert w.sheet.scene_page_rect().contains(thing.sceneBoundingRect().center())
    # off again
    drag(w, view_point(w, thing.sceneBoundingRect().center()),
         view_point(w, QtCore.QPointF(page.left() - 400, page.top() + 100)))
    assert not thing.pinned
    w.undo()
    assert thing.pinned
    w.redo()
    assert not thing.pinned
    w.close()


def test_pinned_things_ride_their_page():
    w = fresh()
    type_paragraphs(w, 30)
    w.flip(1)
    pump()
    page = w.sheet.scene_page_rect()
    w.add_files([make_png(os.path.join(TMP, "b.png"), "#36c")], page.center())
    (thing,) = [t for t in w.things.values() if t.alive]
    assert thing.pinned
    assert 1.0 * w.sheet.H <= thing.pos().y() < 2.0 * w.sheet.H, thing.pos().y()
    w.flip(0)
    pump()
    # not on the page shown: clipped away, and not clickable
    assert w.thing_at(page.center()) is None
    w.close()


def test_delete_and_mixed_undo():
    w = fresh()
    type_paragraphs(w, 2)
    page = w.sheet.scene_page_rect()
    w.add_files([make_png(os.path.join(TMP, "c.png"))], page.center())
    (thing,) = [t for t in w.things.values() if t.alive]
    w.select([thing])
    w.delete_selection()
    assert not thing.alive and thing.scene() is None
    w.focus_text()
    cursor = w.sheet.text.textCursor()
    cursor.movePosition(QtGui.QTextCursor.End)
    cursor.insertText("tail")
    w.sheet.text.setTextCursor(cursor)
    assert w.doc.toPlainText().endswith("tail")
    w.undo()                                    # the typing
    assert not w.doc.toPlainText().endswith("tail")
    assert not thing.alive
    w.undo()                                    # the delete
    assert thing.alive and thing.pinned and thing.scene() is w.scene
    w.close()


def test_click_past_the_words_starts_that_page():
    w = fresh()
    type_paragraphs(w, 1)
    assert w.sheet.text_pages() == 1
    w.flip(1)                                   # the blank page after the last
    pump()
    centre = view_point(w, w.sheet.scene_page_rect().center())
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, centre)
    pump()
    assert w.sheet.text_pages() == 2
    assert w.sheet.caret_page() == 1 and w.page == 1
    w.undo()
    assert w.sheet.text_pages() == 1
    w.close()


def test_project_round_trip():
    w = fresh()
    type_paragraphs(w, 12)
    w.new_page()
    w.sheet.text.textCursor().insertText("after the break")
    page = w.sheet.scene_page_rect()
    w.add_files([make_png(os.path.join(TMP, "d.png"))], page.center())
    w.add_files([make_png(os.path.join(TMP, "e.png"), "#3a3")],
                QtCore.QPointF(page.right() + 200, page.top()))
    w.distress.style = "stamp"
    w.distress.edge = 22
    path = os.path.join(TMP, "doc.ream")
    w.save_as(path)
    text = w.doc.toPlainText()
    pages = w.sheet.pages()
    w.close()
    w2 = Ream([path])
    pump(0.1)
    assert w2.doc.toPlainText() == text
    assert w2.sheet.pages() == pages
    assert "\f" in project.doc_to_text(w2.doc)
    alive = [t for t in w2.things.values() if t.alive]
    assert sorted(t.pinned for t in alive) == [False, True]
    assert w2.distress.style == "stamp" and w2.distress.edge == 22
    assert w2.path == os.path.abspath(path)
    w2.close()


def test_export_pdf():
    import pypdfium2
    w = fresh()
    type_paragraphs(w, 20)
    w.add_files([make_png(os.path.join(TMP, "f.png"))], w.sheet.scene_page_rect().center())
    rough = w.export_pdf(path=os.path.join(TMP, "rough.pdf"))
    clean = w.export_pdf(clean=True, path=os.path.join(TMP, "clean.pdf"))
    for path in (rough, clean):
        document = pypdfium2.PdfDocument(path)
        assert len(document) == w.sheet.pages(), (path, len(document))
        width, height = document[0].get_size()
        assert abs(width - w.sheet.W) < 1.5 and abs(height - w.sheet.H) < 1.5
    words = pypdfium2.PdfDocument(clean)[0].get_textpage().get_text_range()
    assert "refusal to labour" in words, words[:120]
    # the distressed one is pictures of pages, with ink on them
    page = pypdfium2.PdfDocument(rough)[0].render(scale=1).to_numpy()
    assert page.min() < 80 and page.max() > 240
    pngs = w.export_png(path=os.path.join(TMP, "pages.png"))
    assert len(pngs) == w.sheet.pages() and all(os.path.exists(p) for p in pngs)
    w.close()


def test_distress_changes_the_ink_and_keeps_its_place():
    w = fresh()
    type_paragraphs(w, 3)
    layer = export.ink_layer(w.sheet, 0, 150, w.ink())
    s = distress.Settings()
    out = distress.apply(layer, s, 150)
    a0, a1 = layer[..., 3] > 127, out[..., 3] > 127
    assert a0.sum() > 1000
    overlap = (a0 & a1).sum() / max(1, (a0 | a1).sum())
    assert 0.3 < overlap < 0.97, overlap      # changed, but still the same words
    for style_name in distress.edge_styles():
        distress.apply(layer[:200, :300], distress.Settings(style=style_name, misfire=40), 150)
    sheet = distress.compose(layer, (255, 255, 255), distress.Settings(paper=60), 150)
    assert sheet.shape == layer.shape[:2] + (3,)
    w.close()


def test_procedural_textures_without_the_plugin():
    saved = (distress._index, dict(distress._textures), os.environ.get("REAM_DISTRESSOR"))
    try:
        os.environ["REAM_DISTRESSOR"] = os.path.join(TMP, "nowhere")
        distress._index = None
        distress._textures.clear()
        assert distress.library()["source"] == "procedural"
        layer = np.zeros((120, 200, 4), np.uint8)
        layer[40:80, 20:180] = (20, 20, 20, 255)
        out = distress.apply(layer, distress.Settings(), 300)
        assert out[..., 3].max() > 180 and out[..., 3].mean() > 20
    finally:
        distress._index, textures, env = saved
        distress._textures.clear()
        distress._textures.update(textures)
        if env is None:
            os.environ.pop("REAM_DISTRESSOR", None)
        else:
            os.environ["REAM_DISTRESSOR"] = env


def test_palette():
    w = fresh()
    titles = [c.title for c in w.commands()]
    assert "export pdf" in titles and "distress view" in titles
    assert any(t.startswith("style · ") for t in titles)
    (edge,) = [c for c in w.dynamic("edge 14")]
    edge.run()
    assert w.distress.edge == 14
    page_cmds = w.dynamic("page 1")
    assert any(c.title.startswith("page →") for c in page_cmds)
    w.dynamic("size 11")[0].run()
    assert w.fmt.size == 11 and abs(w.doc.defaultFont().pointSizeF() - 11) < 1e-6
    w.dynamic("line 180")[0].run()
    assert w.doc.begin().blockFormat().lineHeight() == 180
    w.open_palette(w.view.mapToGlobal(w.view.viewport().rect().center()))
    pump(0.05)
    assert w.palette.isVisible() and w.palette.shown
    w.palette.query.setText("edge 9")
    assert w.palette.shown[0].title == "edge → 9"
    w.palette.query.setText("rbg")       # forgiving match still returns something
    w.palette.hide()
    # Tab from the canvas opens it
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Tab)
    pump(0.05)
    assert w.palette.isVisible()
    w.palette.hide()
    w.show_preview()
    assert w.preview is not None
    w.set_param("edge", 30)                 # re-renders while shown
    assert w.preview is not None
    w.hide_preview()
    w.close()


def test_rotate_with_the_knob_and_scale_about_the_middle():
    w = fresh()
    page = w.sheet.scene_page_rect()
    w.add_files([make_png(os.path.join(TMP, "r.png"))], page.center())
    (thing,) = [t for t in w.things.values() if t.alive]
    w.select([thing])
    pump(0.05)
    centre = thing.mapToScene(QtCore.QPointF(thing.w / 2, thing.h / 2))
    _corners, knob, _top = w._handles(thing)
    # drag the knob a quarter turn clockwise round the middle
    c = view_point(w, centre)
    radius = (knob - QtCore.QPointF(c)).manhattanLength()
    drag(w, knob.toPoint(), QtCore.QPoint(int(c.x() + radius), c.y()))
    assert abs(((thing.rotation() + 180) % 360) - 270) < 6, thing.rotation()
    after = thing.mapToScene(QtCore.QPointF(thing.w / 2, thing.h / 2))
    assert (after - centre).manhattanLength() < 1.0
    # the corner handle scales about the middle, even turned
    corners = w._handles(thing)[0]
    w0 = thing.w
    drag(w, corners[2].toPoint(), (corners[2] + (corners[2] - QtCore.QPointF(c)) * 0.5).toPoint())
    assert thing.w > w0 * 1.3, (w0, thing.w)
    middle = thing.mapToScene(QtCore.QPointF(thing.w / 2, thing.h / 2))
    assert (middle - centre).manhattanLength() < 1.5
    w.undo()
    assert abs(thing.w - w0) < 0.01
    w.undo()
    assert abs(thing.rotation()) < 0.01
    w.select([thing])
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_BracketRight)
    assert abs(thing.rotation() - 15) < 0.01
    w.dynamic("rotate 30")[0].run()
    assert abs(thing.rotation() - 30) < 0.01
    # it goes out turned, and comes back turned
    path = os.path.join(TMP, "turned.ream")
    w.save_as(path)
    w.export_pdf(clean=True, path=os.path.join(TMP, "turned.pdf"))
    w.close()
    w2 = Ream([path])
    (back,) = [t for t in w2.things.values() if t.alive]
    assert abs(back.rotation() - 30) < 0.01 and back.pinned
    w2.close()


def test_layout_sliders_undo_as_one_step():
    w = fresh()
    type_paragraphs(w, 6)
    text = w.doc.toPlainText()
    lines_before = w.sheet.caret_span()
    for value in (160, 170, 180, 190, 200):     # a slider being dragged
        w.set_line_height(value)
    assert w.doc.begin().blockFormat().lineHeight() == 200
    for value in (4, 8, 12):
        w.set_para(value)
    assert w.doc.begin().blockFormat().bottomMargin() == 12
    for value in (80, 100, 120):
        w.set_margins(side=value)
    assert w.doc.rootFrame().frameFormat().leftMargin() == 120
    w.set_margins(head=30)
    assert w.doc.rootFrame().frameFormat().topMargin() == 30
    w.undo()                                    # head
    assert w.doc.rootFrame().frameFormat().topMargin() == 70
    w.undo()                                    # sides
    assert w.doc.rootFrame().frameFormat().leftMargin() == 64
    w.undo()                                    # paragraph spacing
    assert w.doc.begin().blockFormat().bottomMargin() == 0
    w.undo()                                    # line height
    assert w.doc.begin().blockFormat().lineHeight() == 150
    assert w.doc.toPlainText() == text          # and the words are untouched
    assert w.sheet.caret_span() == lines_before
    # new paragraphs take the spacing
    w.set_para(10)
    cursor = w.sheet.text.textCursor()
    cursor.movePosition(QtGui.QTextCursor.End)
    cursor.insertText("\nnew")
    assert w.doc.lastBlock().blockFormat().bottomMargin() == 10
    w.close()


def test_colours():
    w = fresh()
    w.set_canvas("#2a2a2a")
    assert w.view.bg.name() == "#2a2a2a"
    assert not w.canvas_is_light()
    w.dynamic("canvas #e8e7e3")[0].run()
    assert w.view.bg.name() == "#e8e7e3"
    w.set_paper("#f0e6d0")
    assert w.sheet.brush().color().name() == "#f0e6d0"
    w._set_theme("night")
    assert w.view.bg.name() == "#161616"
    w._set_theme("paper")
    w.close()


def test_distress_panel_live_preview():
    w = fresh()
    type_paragraphs(w, 4)
    w.open_distress_panel()
    panel = w.distress_panel
    assert panel.isVisible() and w.live()
    pump(1.0)
    assert w.preview is not None, "the panel opens with the page previewed"
    first = w.preview.pixmap().toImage()
    sliders = panel.findChildren(QtWidgets.QSlider)
    assert len(sliders) == len(distress.PARAMS) + 2         # + ink, dpi
    edge = sliders[1 + list(distress.PARAMS).index("edge")]
    edge.setValue(60)
    assert w.distress.edge == 60
    pump(1.0)
    assert w.preview is not None and w.preview.pixmap().toImage() != first
    # both panels at once, side by side
    w.open_page_panel()
    assert panel.isVisible() and w.page_panel.isVisible()
    assert not panel.geometry().intersects(w.page_panel.geometry())
    # closing the distress panel ends the view it started
    panel.close_panel()
    assert w.preview is None and not w.live()
    w.page_panel.close_panel()
    w.close()


def test_write_on_the_distressed_page():
    w = fresh()
    type_paragraphs(w, 2)
    w.set_distress_view(True)
    pump(1.0)
    assert w.preview is not None
    before = w.preview.pixmap().toImage()
    w.focus_text()
    QtTest.QTest.keyClicks(w.view, "WORDS TYPED ON TOP")
    assert w.preview is not None            # stays up while writing
    pump(1.0)
    assert w.preview.pixmap().toImage() != before, "re-rendered with the new words"
    assert w.sheet.text.textCursor().position() > 0
    w.grab()                                # the caret is drawn over it without trouble
    # a format change re-renders too
    shown = w.preview.pixmap().toImage()
    w.set_line_height(260)
    pump(1.0)
    assert w.preview.pixmap().toImage() != shown
    w.set_distress_view(False)
    assert w.preview is None
    w.close()


def test_still_preview_never_hides_a_change():
    w = fresh()
    type_paragraphs(w, 3)
    w.show_preview()
    assert w.preview is not None
    w.set_line_height(220)                  # e.g. from the page panel
    assert w.preview is None, "a still picture must not sit over a changed page"
    w.close()


def test_ink_darkness():
    w = fresh()
    type_paragraphs(w, 2)
    dark = export.ink_layer(w.sheet, 0, 100, w.ink())
    w.set_ink(40)
    assert w.sheet.text.defaultTextColor().lightness() > 120
    light = export.ink_layer(w.sheet, 0, 100, w.ink())
    solid = dark[..., 3] > 200
    assert light[..., :3][solid].mean() > dark[..., :3][solid].mean() + 60
    w.dynamic("ink 100")[0].run()
    assert w.fmt.ink == 100 and w.ink().name() == "#000000"
    w.set_paper("#f4efe2")
    w.set_ink(50)
    c = w.ink()
    assert c.red() > c.blue()               # fades toward the cream, not grey
    w.close()

def test_cmd_click_writes_anywhere():
    w = fresh()
    type_paragraphs(w, 3)
    page = w.sheet.scene_page_rect()
    spot = QtCore.QPointF(page.left() + 200, page.top() + 140)     # over the words
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.ControlModifier,
                            view_point(w, spot))
    pump(0.05)
    note = w.editing
    assert note is not None and note.pinned
    assert abs(note.scenePos().x() - spot.x()) < 1.0
    QtTest.QTest.keyClicks(w.view, "over the top")
    assert note.text() == "over the top"
    assert "over the top" not in w.doc.toPlainText()       # the page's words are untouched
    # it wraps at the right margin
    QtTest.QTest.keyClicks(w.view, " and on and on" * 6)
    right = page.left() + w.sheet.W - w.fmt.margin
    assert note.sceneBoundingRect().right() <= right + 1.0, (note.sceneBoundingRect(), right)
    assert note.h > 20
    # Esc finishes; the words get the keys back
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert w.editing is None
    QtTest.QTest.keyClicks(w.view, "Z")
    assert w.doc.toPlainText().endswith("Z") or "Z" in w.doc.toPlainText()
    # undo takes the typing back, then the note
    w.undo()                                    # the Z
    w.undo()
    assert note.text() != "over the top" + " and on and on" * 6 or note.text() == ""
    while w.history and note.alive:
        w.undo()
    assert not note.alive
    w.redo()
    assert note.alive
    w.close()


def test_design_mode_selects_instead_of_typing():
    w = fresh()
    w.show()
    type_paragraphs(w, 3)
    assert w.mode == "writer"
    words = w.doc.toPlainText()
    page = w.sheet.scene_page_rect()
    viewport = w.view.viewport()
    # ⌥⌘D: design mode - remembered
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_D, QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
    assert w.mode == "design" and w.prefs["mode"] == "design"
    # a click on the page, away from the words, writes nothing and types nothing
    corner = QtCore.QPointF(page.left() + 20, page.bottom() - 20)
    QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, view_point(w, corner))
    QtTest.QTest.keyClicks(w.view, "qq")   # (not tool letters)
    assert w.doc.toPlainText() == words and w.editing is None and not w.story_editing
    # a click on the words selects the main text's frame; typing still does nothing
    over = QtCore.QPointF(page.left() + w.fmt.margin + 40, page.top() + w.fmt.head + 8)
    QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, view_point(w, over))
    assert w.story_selected and not w.story_editing
    QtTest.QTest.keyClicks(w.view, "qq")   # (not tool letters)
    assert w.doc.toPlainText() == words
    w.view.grab()
    # double-click writes there; Esc stops, leaving the frame selected
    QtTest.QTest.mouseDClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, view_point(w, over))
    assert w.story_editing
    QtTest.QTest.keyClicks(w.view, "XY")
    assert "XY" in w.doc.toPlainText() and w.doc.toPlainText().index("XY") < 20
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert not w.story_editing and w.story_selected
    QtTest.QTest.keyClicks(w.view, "qq")   # (not tool letters)
    assert "qq" not in w.doc.toPlainText()
    # ↵ on the selected frame writes at the end
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Return)
    assert w.story_editing
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert not w.story_selected
    # T, then drag: a text box that wide, written in at once
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_T)
    assert w.text_tool
    a = QtCore.QPointF(page.left() + 100, page.top() + 400)
    b = QtCore.QPointF(page.left() + 340, page.top() + 440)
    drag(w, view_point(w, a), view_point(w, b))
    note = w.editing
    assert note is not None and note.pinned and not w.text_tool
    assert abs(note.wrap - 240) < 3, note.wrap
    assert abs(note.scenePos().x() - a.x()) < 2 and abs(note.scenePos().y() - a.y()) < 2
    QtTest.QTest.keyClicks(w.view, "A Heading")
    assert note.text() == "A Heading" and "Heading" not in w.doc.toPlainText()
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert w.editing is None
    # click selects it; the text panel styles it alone
    QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            view_point(w, note.sceneBoundingRect().center()))
    assert w.selection() == [note]
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_T, QtCore.Qt.ControlModifier)
    panel = w.text_panel
    assert panel.isVisible() and "1 box" in panel.caption.text()
    size_before = w.fmt.size
    h_before = note.h
    w.set_text_value("size", 24.0, slider=True)
    w.set_text_value("size", 28.0, slider=True)          # one drag: one undo step
    panel.on_release()
    w.set_text_value("align", "centre")
    w.set_text_value("font", w.face())
    assert note.look["size"] == 28.0 and note.look["align"] == "centre"
    assert note.editor.document().defaultFont().pointSizeF() == 28.0 and note.h > h_before * 2
    assert w.fmt.size == size_before, "the main text keeps its type"
    w.undo()                                             # the font
    w.undo()                                             # the align
    assert "align" not in note.look and note.look["size"] == 28.0
    w.undo()                                             # the whole size drag
    assert "size" not in note.look
    w.redo()
    w.redo()
    assert note.look["size"] == 28.0 and note.look["align"] == "centre"
    # nothing chosen: the panel styles the main text (the document's type)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert w.text_targets() == "story" and "main text" in panel.caption.text()
    w.set_text_value("track", 10.0)
    w.set_text_value("align", "justify")
    assert w.fmt.track == 10.0 and w.fmt.align == "justify"
    assert w.doc.begin().blockFormat().alignment() & QtCore.Qt.AlignJustify
    # a box with no look of its own follows the document; with one, keeps it
    assert note.look["align"] == "centre"
    # marquee: drag round the box from an empty spot
    w.clear_selection()
    box = note.sceneBoundingRect()
    start = QtCore.QPointF(page.left() + 8, box.top() - 6)
    end = QtCore.QPointF(box.right() + 6, box.bottom() + 6)
    drag(w, view_point(w, start), view_point(w, end))
    assert note in w.selection()
    # the look is saved, and exported
    state, media = w.state()
    entry = [t for t in state["things"] if t.get("kind") == "text"][0]
    assert entry["look"]["size"] == 28.0
    w.load_state(state, media)
    reloaded = [t for t in w.things.values() if isinstance(t, Note) and t.alive][0]
    assert reloaded.look == {"size": 28.0, "align": "centre"}       # (the font step stayed undone)
    assert reloaded.editor.document().defaultFont().pointSizeF() == 28.0
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "design.pdf"))
    import pypdfium2
    text = pypdfium2.PdfDocument(pdf)[0].get_textpage().get_text_range()
    assert "A Heading" in text and "XY" in text
    # write mode is writing: it takes you back to writer mode
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_F, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    assert w.mode == "writer" and w.write_mode
    w.leave_write_mode()
    # writer mode as ever: a click on the page puts the caret in the words
    QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, view_point(w, over))
    QtTest.QTest.keyClicks(w.view, "Q")
    assert "Q" in w.doc.toPlainText()
    w.close()


def test_style_selected_words():
    import pypdfium2
    from ream.page import char_props, doc_runs
    w = fresh()
    w.show()
    w.distress.enabled = False
    cursor = w.sheet.text.textCursor()
    cursor.insertText("plain words then LOUD words then plain again")
    w.sheet.text.setTextCursor(cursor)
    pump(0.05)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_T, QtCore.Qt.ControlModifier)
    panel = w.text_panel
    assert "main text" in panel.caption.text() and w.words_target() is None
    # writer mode: select "LOUD" in the main text - the panel styles just it
    start = w.doc.toPlainText().index("LOUD")
    cursor.setPosition(start)
    cursor.setPosition(start + 4, QtGui.QTextCursor.KeepAnchor)
    w.sheet.text.setTextCursor(cursor)
    w.caret_moved(follow=False)
    assert w.words_target() == "story" and "words in the main text" in panel.caption.text()
    steps = len(w.history)
    w.set_text_value("weight", "bold")
    w.set_text_value("size", 14.0, slider=True)
    w.set_text_value("size", 18.0, slider=True)          # one drag: one step
    w._text_panel_released()
    assert len(w.history) == steps + 2, w.history[steps:]
    assert w.text_value("weight") == "bold" and w.text_value("size") == 18.0
    probe = QtGui.QTextCursor(w.doc)
    probe.setPosition(start + 2)
    assert char_props(probe.charFormat()) == {"weight": "bold", "size": 18.0}
    probe.setPosition(3)
    assert char_props(probe.charFormat()) == {}, "the rest keeps the document's type"
    assert w.fmt.size == 9.0
    # the document's type changing leaves the styled words their own
    w.set_size(10)
    probe.setPosition(start + 2)
    assert char_props(probe.charFormat())["size"] == 18.0
    w.set_size(9)
    # undo: the size drag, then the bold
    w.undo()
    w.undo()        # (the two set_size calls)
    w.undo()
    probe.setPosition(start + 2)
    assert char_props(probe.charFormat()) == {"weight": "bold"}, char_props(probe.charFormat())
    w.redo()
    probe.setPosition(start + 2)
    assert char_props(probe.charFormat()) == {"weight": "bold", "size": 18.0}
    # bold off again means "as the text": the property goes, not "regular" set
    cursor.setPosition(start)
    cursor.setPosition(start + 4, QtGui.QTextCursor.KeepAnchor)
    w.sheet.text.setTextCursor(cursor)
    w.set_text_value("italic", True)
    w.set_text_value("italic", False)
    probe.setPosition(start + 2)
    assert "italic" not in char_props(probe.charFormat())
    # nothing selected: weight on the main text is refused politely
    cursor.clearSelection()
    w.sheet.text.setTextCursor(cursor)
    w.set_text_value("weight", "bold")
    assert not w.doc.begin().charFormat().hasProperty(QtGui.QTextFormat.FontWeight)
    # design mode: words inside a text box
    w.set_mode("design")
    page = w.sheet.scene_page_rect()
    note = w.new_note(QtCore.QPointF(page.left() + 80, page.top() + 300), wrap=300.0, top=True)
    QtTest.QTest.keyClicks(w.view, "a title with one word big")
    ed = note.editor.textCursor()
    at = note.text().index("big")
    ed.setPosition(at)
    ed.setPosition(at + 3, QtGui.QTextCursor.KeepAnchor)
    note.editor.setTextCursor(ed)
    w._refresh_text_panel()
    assert w.words_target() is note and "words in a box" in panel.caption.text()
    h = note.h
    w.set_text_value("size", 36.0)
    w.set_text_value("font", w.face())
    assert note.h > h * 2 and not note.look, "the box's own type is untouched"
    assert doc_runs(note.editor.document())[0][:2] == [at, 3]
    w.undo()                                           # the font
    assert doc_runs(note.editor.document()) == [[at, 3, {"size": 36.0}]]
    # "as the box" clears the selected words' own type
    w.set_text_value("track", 20.0)
    w.reset_look()
    assert doc_runs(note.editor.document()) == []
    w.undo()
    assert doc_runs(note.editor.document()) == [[at, 3, {"size": 36.0, "track": 20.0}]]
    # box-level bold and italic
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    w.select([note])
    w.set_text_value("weight", "bold")
    w.set_text_value("italic", True)
    assert note.look == {"weight": "bold", "italic": True}
    assert note.editor.document().defaultFont().bold() and note.editor.document().defaultFont().italic()
    # saved, loaded, exported
    state, media = w.state()
    assert state["runs"] == doc_runs(w.doc) and state["runs"]
    w.load_state(state, media)
    assert doc_runs(w.doc) == state["runs"]
    again = [t for t in w.things.values() if isinstance(t, Note) and t.alive][0]
    assert doc_runs(again.editor.document()) == [[at, 3, {"size": 36.0, "track": 20.0}]]
    assert again.look == {"weight": "bold", "italic": True}
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "words.pdf"))
    text = pypdfium2.PdfDocument(pdf)[0].get_textpage().get_text_range()
    assert "LOUD" in text and "big" in text
    # an older file (no runs) still loads
    state.pop("runs")
    w.load_state(state, media)
    assert doc_runs(w.doc) == [] and "LOUD" in w.doc.toPlainText()
    w.close()


def test_empty_note_leaves_nothing_and_notes_survive():
    w = fresh()
    page = w.sheet.scene_page_rect()
    steps = len(w.history)
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.ControlModifier,
                            view_point(w, page.center()))
    note = w.editing
    # clicking away with nothing typed removes it, and leaves no undo step
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            view_point(w, page.topLeft() + QtCore.QPointF(100, 100)))
    assert w.editing is None and not note.alive and len(w.history) == steps
    # one on the canvas, one on the page; both round-trip, only the page one exports
    canvas_spot = QtCore.QPointF(page.right() + 200, page.top() + 50)
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.ControlModifier,
                            view_point(w, canvas_spot))
    QtTest.QTest.keyClicks(w.view, "loose")
    assert not w.editing.pinned and w.editing.wrap < 0
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.ControlModifier,
                            view_point(w, page.center()))
    QtTest.QTest.keyClicks(w.view, "PINNED WORDS")
    w.editing.setRotation(12)
    w.finish_editing()
    path = os.path.join(TMP, "notes.ream")
    w.save_as(path)
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "notes.pdf"))
    w.close()
    import pypdfium2
    words = pypdfium2.PdfDocument(pdf)[0].get_textpage().get_text_range()
    assert "PINNED" in words and "loose" not in words, words
    w2 = Ream([path])
    notes = sorted((t for t in w2.things.values() if isinstance(t, Note) and t.alive),
                   key=lambda t: t.pinned)
    assert [n.text() for n in notes] == ["loose", "PINNED WORDS"]
    assert abs(notes[1].rotation() - 12) < 0.01 and notes[1].pinned
    # double-click edits again, at the click
    w2.fit_page()
    pump(0.05)
    target = notes[1].mapToScene(QtCore.QPointF(2, notes[1].h / 2))
    QtTest.QTest.mouseDClick(w2.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                             view_point(w2, target))
    assert w2.editing is notes[1]
    w2.close()


def test_spread_and_all_pages():
    w = fresh()
    type_paragraphs(w, 40)
    pages = w.sheet.pages()
    assert pages >= 5
    w.flip(0)
    pump()
    # spread: a book - the first page alone on the right, then 2|3, 4|5
    w.set_layout("spread")
    pump(0.1)
    assert w.layout == "spread" and w.visible_pages() == [0] and not w.ghosts
    assert w.sheet.pos() == QtCore.QPointF(0, 0)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Right, QtCore.Qt.ControlModifier)
    pump(0.1)
    assert w.page == 1 and w.visible_pages() == [1, 2] and list(w.ghosts) == [2]
    assert w.sheet.pos().x() == -w.sheet.W and w.ghosts[2].pos().x() == 0
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Right, QtCore.Qt.ControlModifier)
    pump(0.1)
    assert w.page == 3 and w.visible_pages() == [3, 4]
    # clicking the facing page makes it live, with the caret where you clicked
    right = w.ghosts[4].sceneBoundingRect()
    spot = QtCore.QPointF(right.left() + w.fmt.margin + 30, right.top() + w.fmt.head + 20)
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            view_point(w, spot))
    pump(0.1)
    assert w.page == 4 and 3 in w.ghosts and w.sheet.caret_page() == 4
    QtTest.QTest.keyClicks(w.view, "on the right")
    assert w.page == 4
    # a picture dropped on the facing page pins to that page
    left = w.ghosts[3].sceneBoundingRect()
    w.add_files([make_png(os.path.join(TMP, "s.png"))], left.center())
    (thing,) = [t for t in w.things.values() if t.alive]
    assert thing.pinned and w.page == 3
    assert 3 * w.sheet.H <= thing.pos().y() < 4 * w.sheet.H
    # the facing page draws without trouble (vector), and in distress view
    w.grab()
    w.set_distress_view(True)
    pump(1.2)
    assert all(g.distressed is not None for i, g in w.ghosts.items() if i < w.sheet.pages())
    w.set_distress_view(False)
    # all pages: every page, in a grid; the same shortcut again goes back
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_3, QtCore.Qt.ControlModifier)
    pump(0.1)
    assert w.layout == "all" and len(w.ghosts) == w.sheet.pages() - 1
    xs = {round(g.pos().x()) for g in w.ghosts.values()} | {round(w.sheet.pos().x())}
    ys = {round(g.pos().y()) for g in w.ghosts.values()} | {round(w.sheet.pos().y())}
    W = round(w.sheet.W)
    assert xs <= {-W, 0}, xs                              # left or right of one spine
    assert len(ys) == len(w.spreads()), (ys, w.spreads())  # one spread a row
    seen = w.view.visible_scene_rect()
    assert seen.contains(w.layout_rect()), "the whole grid is framed"
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_3, QtCore.Qt.ControlModifier)
    pump(0.1)
    assert w.layout == "single" and not w.ghosts and w.sheet.pos() == QtCore.QPointF(0, 0)
    # exports are the same in any layout
    w.set_layout("all")
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "layout.pdf"))
    import pypdfium2
    assert len(pypdfium2.PdfDocument(pdf)) == w.sheet.pages()
    w.set_layout("single")
    w.close()


def test_paper_stock():
    import cv2
    import pypdfium2
    from ream import papers
    folder = papers.folder()
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3)
    grain = cv2.GaussianBlur(rng.normal(0, 1, (900, 1300)).astype(np.float32), (0, 0), 2)
    light = np.linspace(150, 210, 1300, dtype=np.float32)[None, :]     # uneven lighting
    photo = np.clip(light + grain * 25, 0, 255).astype(np.uint8)
    cv2.imwrite(str(folder / "test_stock.jpg"), photo)
    (folder / "index.json").write_text('{"test_stock.jpg": "Test stock"}')
    w = fresh()
    type_paragraphs(w, 3)
    assert "Test stock" in w.stock_labels()
    w.set_paper("#f4efe2")
    w.set_texture("test_stock.jpg")
    assert w.stock() == "test_stock.jpg" and w._surface is not None
    screen = export.to_numpy(w._surface)[..., :3].astype(float)
    # the stock keeps the chosen colour, evenly lit - only its tooth shows
    mean = screen.reshape(-1, 3).mean(0)
    assert np.abs(mean - np.array([0xf4, 0xef, 0xe2])).max() < 6, mean
    halves = screen[:, : screen.shape[1] // 2].mean(), screen[:, screen.shape[1] // 2:].mean()
    assert abs(halves[0] - halves[1]) < 3, halves                    # lighting removed
    assert screen[..., 0].std() > 2                                  # tooth is there
    flat_before = w.grab()
    w.set_grain(0)
    assert w._surface is None and w.stock() == ""
    w.set_grain(80)
    # exports carry it: clean (stock under vector words) and distressed
    clean = w.export_pdf(clean=True, path=os.path.join(TMP, "stock_clean.pdf"))
    doc = pypdfium2.PdfDocument(clean)
    assert "refusal to labour" in doc[0].get_textpage().get_text_range()
    blank = doc[0].render(scale=1).to_numpy()[700:800, 60:200, :3].astype(float)
    assert blank.std() > 1.5, "the clean PDF prints on the stock"
    rough = w.export_pdf(path=os.path.join(TMP, "stock_rough.pdf"))
    page = pypdfium2.PdfDocument(rough)[0].render(scale=1).to_numpy()[700:800, 60:200, :3].astype(float)
    assert page.std() > 1.5
    # the live preview and the other pages use it too
    w.set_distress_view(True)
    pump(1.2)
    assert w.preview is not None
    w.set_distress_view(False)
    # a document whose stock is missing falls back to flat paper
    (folder / "test_stock.jpg").unlink()
    papers._detail.clear()
    papers._surfaces.clear()
    w._apply_paper()
    assert w.stock() == "" and w._surface is None
    w.close()


def test_profiles():
    from ream import profiles
    try:
        profiles.path().unlink()
    except OSError:
        pass
    w = fresh()
    type_paragraphs(w, 6)
    text = w.doc.toPlainText()
    # profile1: the defaults, slightly changed
    w.set_size(10)
    w.distress.edge = 22
    w.save_profile()
    assert w.active_profile() == "profile1" and not w.profile_dirty()
    # change a lot, and it shows as unsaved
    w.set_size(12)
    w.set_line_height(210)
    w.set_para(8)
    w.set_margins(side=40, head=50)
    w.set_ink(130)
    w.set_paper("#f4efe2")
    w.set_canvas("#2a2a2a")
    w.distress.style = "stamp"
    w.distress.edge = 40
    assert w.profile_dirty()
    assert "*" in w.caption()
    # save as a new profile, then switch back and forth
    w.new_profile()
    assert w.active_profile() == "profile2" and w.profile_names() == ["profile1", "profile2"]
    w.switch_profile("profile1")
    assert w.fmt.size == 10 and w.fmt.line == 150 and w.fmt.para == 0 and w.fmt.margin == 64
    assert w.fmt.ink == 100 and w.distress.style == "rough" and w.distress.edge == 22
    assert w.doc.begin().blockFormat().lineHeight() == 150
    assert abs(w.doc.defaultFont().pointSizeF() - 10) < 1e-6
    assert w.view.bg.name() != "#2a2a2a"
    assert not w.profile_dirty()
    w.switch_profile("profile2")
    assert w.fmt.size == 12 and w.fmt.line == 210 and w.fmt.para == 8 and w.fmt.margin == 40
    assert w.doc.begin().blockFormat().lineHeight() == 210
    assert w.doc.begin().blockFormat().bottomMargin() == 8
    assert w.distress.style == "stamp" and w.view.bg.name() == "#2a2a2a"
    assert w.doc.toPlainText() == text, "profiles never touch the words"
    # shortcuts: Cmd+Alt+1 goes to the first profile
    w.switch_profile_number(1)
    assert w.active_profile() == "profile1" and w.fmt.size == 10
    # the palette saves under a typed name
    (named,) = w.dynamic("save profile zine")
    named.run()
    assert "zine" in w.profile_names() and w.active_profile() == "zine"
    # both panels carry the profile rows
    w.open_page_panel()
    w.open_distress_panel()
    w.page_panel.refresh()
    w.close()
    # they outlive the window
    w2 = Ream([])
    assert w2.profile_names() == ["profile1", "profile2", "zine"]
    w2.delete_profile("zine")
    assert w2.profile_names() == ["profile1", "profile2"] and w2.active_profile() is None
    w2.close()


def test_paper_blend_modes_and_scale():
    import cv2
    import pypdfium2
    from ream import papers
    folder = papers.folder()
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(5)
    noise = cv2.GaussianBlur(rng.normal(0, 1, (900, 1300)).astype(np.float32), (0, 0), 3)
    photo = np.clip(185 + noise * 30, 0, 255).astype(np.uint8)
    cv2.imwrite(str(folder / "blend_stock.png"), cv2.merge([photo - 6, photo, photo + 4]))
    papers._photos.clear()
    papers._surfaces.clear()
    w = fresh()
    type_paragraphs(w, 3)
    w.set_texture("blend_stock.png")
    w.set_grain(100)
    flat = export.raster_page(w.sheet, 0, 60, distress.Settings(enabled=False), w.paper(), w.ink())
    flat = export.to_numpy(flat)[..., :3].astype(float)
    means = {}
    for mode in ("multiply", "overlay", "soft light", "screen", "normal"):
        w.set_blend(mode)
        assert w.sheet.stock.isVisible() and w._surface is None, mode
        page = export.raster_page(w.sheet, 0, 60, distress.Settings(enabled=False), w.paper(),
                                  w.ink(), paper_stock=w.paper_stock())
        means[mode] = export.to_numpy(page)[..., :3].astype(float)[400:, :].mean()
        w.grab()                                        # draws with Qt's blend mode
    paper_mean = flat[400:, :].mean()
    assert means["multiply"] < paper_mean - 10          # the paper darkens a white page
    assert means["normal"] < paper_mean - 30            # the photo as photographed
    assert abs(means["overlay"] - paper_mean) < 8       # overlay barely moves white
    assert means["screen"] >= paper_mean - 1
    # tooth is the old behaviour: the stock painted as the page, no layer
    w.set_blend("tooth")
    assert not w.sheet.stock.isVisible() and w._surface is not None
    # scale sizes the paper
    w.set_blend("multiply")
    a = papers.surface("blend_stock.png", w.sheet.W, w.sheet.H, 40, None, 100, "multiply")
    w.dynamic("stock 250")[0].run()
    assert w.fmt.stock_scale == 250
    b = papers.surface("blend_stock.png", w.sheet.W, w.sheet.H, 40, None, 250, "multiply")
    assert a.shape == b.shape and not np.allclose(a, b)
    # exports: the distressed one blends over the page, the clean one keeps words
    rough = w.export_pdf(path=os.path.join(TMP, "blend_rough.pdf"))
    clean = w.export_pdf(clean=True, path=os.path.join(TMP, "blend_clean.pdf"))
    assert "refusal to labour" in pypdfium2.PdfDocument(clean)[0].get_textpage().get_text_range()
    for path in (rough, clean):
        corner = pypdfium2.PdfDocument(path)[0].render(scale=1).to_numpy()[760:820, 20:120, :3]
        assert corner.mean() < 250, path                 # blank paper is 255: the paper is in both
    # profiles carry the blend and scale
    w.save_profile("multiplied")
    w.set_blend("tooth")
    w.switch_profile("multiplied")
    assert w.blend_mode() == "multiply" and w.fmt.stock_scale == 250
    w.close()


def test_palette_opens_centred():
    w = fresh()
    centre = w.view.mapToGlobal(w.view.viewport().rect().center())
    for corner in (QtCore.QPoint(20, 20), QtCore.QPoint(900, 700)):
        QtGui.QCursor.setPos(w.view.mapToGlobal(corner))
        w.open_palette(w.view.mapToGlobal(corner))
        pump(0.05)
        middle = w.palette.geometry().center().x()
        assert abs(middle - centre.x()) <= 2, (middle, centre.x())
        top = w.palette.geometry().top()
        w.palette.query.setText("zzzz-nothing")        # a short list keeps the same top
        assert w.palette.geometry().top() == top
        w.palette.hide()
    w.close()


def test_words_on_images_are_distressed_and_stacking():
    w = fresh()
    type_paragraphs(w, 4)
    w.flip(0)
    pump()
    page = w.sheet.scene_page_rect()
    grey = os.path.join(TMP, "grey.png")
    image = QtGui.QImage(500, 300, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("#c8c8c8"))
    image.save(grey)
    # an opaque picture right under the first lines of words
    w.add_files([grey], page.topLeft() + QtCore.QPointF(page.width() / 2, 110))
    (thing,) = [t for t in w.things.values() if t.alive]
    w.select([thing])
    w.restack("back")
    assert thing.zValue() < 0
    dpi = 150
    clean = export.raster_page(w.sheet, 0, dpi, distress.Settings(enabled=False), w.paper(), w.ink())
    rough = export.raster_page(w.sheet, 0, dpi, distress.Settings(), w.paper(), w.ink())
    clean, rough = (export.to_numpy(i)[..., :3].astype(int) for i in (clean, rough))
    r = thing.parent_rect()
    k = dpi / 72.0
    y0, y1 = int(r.top() * k) + 6, int(r.bottom() * k) - 6
    x0, x1 = int(r.left() * k) + 6, int(r.right() * k) - 6
    inside_clean, inside_rough = clean[y0:y1, x0:x1], rough[y0:y1, x0:x1]
    ink = inside_clean.mean(axis=2) < 80                     # the words on the picture
    assert ink.sum() > 200
    changed = (np.abs(inside_rough - inside_clean).max(axis=2) > 60)[ink].mean()
    assert changed > 0.08, f"words on the picture should be distressed ({changed:.3f})"
    # with images clean, the picture away from the words is untouched
    no_images = distress.Settings(images=False)
    plain = export.to_numpy(export.raster_page(w.sheet, 0, dpi, no_images, w.paper(),
                                               w.ink()))[..., :3].astype(int)
    picture = ~ink & (inside_clean.mean(axis=2) > 150)
    near = cv2_dilate(ink)
    calm = picture & ~near
    assert np.abs(plain[y0:y1, x0:x1] - inside_clean)[calm].max() <= 2
    assert np.abs(inside_rough - inside_clean)[calm].max() > 30   # distressed when on
    # and the words on it are still distressed
    assert (np.abs(plain[y0:y1, x0:x1] - inside_clean).max(axis=2) > 60)[ink].mean() > 0.08
    # stacking: Cmd+] brings it over the words, Cmd+[ back, Shift for all the way
    w.select([thing])
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_BracketRight, QtCore.Qt.ControlModifier)
    assert thing.zValue() > 0
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_BracketLeft, QtCore.Qt.ControlModifier)
    assert thing.zValue() < 0
    second = os.path.join(TMP, "second.png")
    make_png(second, "#36c")
    w.add_files([second], thing.sceneBoundingRect().center())
    other = [t for t in w.things.values() if t.alive and t is not thing][0]
    assert other.zValue() > 0
    w.select([thing])
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_BracketRight,
                          QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    assert thing.zValue() > other.zValue() > 0
    w.select([thing])
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_BracketLeft,
                          QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    assert thing.zValue() < 0 < other.zValue()
    w.undo()
    assert thing.zValue() > other.zValue()
    w.close()


def cv2_dilate(mask: np.ndarray, px: int = 4) -> np.ndarray:
    import cv2
    return cv2.dilate(mask.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)) > 0


def test_write_mode():
    w = fresh()
    w.prefs.pop("write_zoom", None)
    type_paragraphs(w, 1)
    w.fit_page()
    pump(0.05)
    before_zoom = w.view.zoom()
    before_centre = w.view.mapToScene(w.view.viewport().rect().center())
    w.focus_text()
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_F, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    pump(0.05)
    assert w.write_mode and abs(w.view.zoom() - 1.75) < 1e-6

    def band() -> float:
        seen = w.view.visible_scene_rect()
        return (w._caret_scene().y() - seen.top()) / seen.height()

    def centred() -> bool:
        centre = w.view.mapToScene(w.view.viewport().rect().center())
        return abs(centre.x() - w.sheet.scene_page_rect().center().x()) < 1.0

    assert centred() and abs(band() - 0.42) < 0.02
    # write a few pages: the line stays in the band, the view scrolls down,
    # the page stays centred
    start = w.view.mapToScene(w.view.viewport().rect().center()).y()
    for n in range(40):
        QtTest.QTest.keyClicks(w.view, f"{n:02d} words on the page and then some more of them")
        QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Return)
        pump(0.01)
        pump(0.25)
        assert 0.1 <= band() <= 0.7, (n, band())
    assert w.page >= 1, "the writing ran onto another page"
    assert centred()
    # within a page the view moved down to follow
    w.flip(0)
    pump()
    # Cmd+= adjusts the writing zoom and it is remembered
    zoom = w.view.zoom()
    w.zoom_step(1.25)
    assert abs(w.view.zoom() - zoom * 1.25) < 1e-6 and abs(w.write_zoom() - zoom * 1.25) < 1e-3
    w.dynamic("write 200")[0].run()
    assert abs(w.view.zoom() - 2.0) < 1e-6 and w.prefs["write_zoom"] == 2.0
    # Esc leaves and the old view comes back
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert not w.write_mode
    assert abs(w.view.zoom() - before_zoom) < 1e-6
    back = w.view.mapToScene(w.view.viewport().rect().center())
    assert (back - before_centre).manhattanLength() < 2.0
    # next time it opens at the zoom you set
    w.toggle_write_mode()
    assert abs(w.view.zoom() - 2.0) < 1e-6
    w.toggle_write_mode()
    w.close()


def test_plugins_load_and_switch():
    from ream import plugin
    folder = plugin.user_folder()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "hello.py").write_text(
        "from ream.plugin import Plugin as Base\n"
        "class Plugin(Base):\n"
        "    name = 'hello'\n"
        "    def setup(self, host):\n"
        "        self.calls = 0\n"
        "        host.command('hello: wave', self.wave, keywords='greet')\n"
        "    def wave(self):\n"
        "        self.calls += 1\n")
    (folder / "broken.py").write_text("raise RuntimeError('nope')\n")
    w = fresh()
    names = {p.name: p for p, _h in w.plugins}
    assert "scanner" in names and "hello" in names
    assert any("broken" in e for e in w.plugin_errors)
    titles = [c.title for c in w.commands()]
    assert "scanner" in titles and "hello: wave" in titles and "plugin · hello" in titles
    [c for c in w.commands() if c.title == "hello: wave"][0].run()
    assert names["hello"].calls == 1
    # off: its commands go, and it stays off next time
    w.switch_plugin(names["hello"])
    assert "hello: wave" not in [c.title for c in w.commands()]
    assert "hello" in w.prefs["plugins_off"]
    w.switch_plugin(names["hello"])
    assert "hello: wave" in [c.title for c in w.commands()]
    w.close()
    (folder / "hello.py").unlink()
    (folder / "broken.py").unlink()


def scanner_of(w):
    return [p for p, _h in w.plugins if p.name == "scanner"][0]


def run_scan(scanner, steps: int = 400):
    """Drive the scan without waiting for real time."""
    scanner.start()
    for _ in range(steps):
        if not scanner.running:
            break
        scanner._last -= 0.2                  # pretend 0.2 s went by
        scanner.tick()


def test_scanner_scans_smears_and_drags_out():
    w = fresh()
    sc = scanner_of(w)
    sc.s.update({"speed": 5.0, "ink": "colour", "noise": 0.0, "tone": 0.0, "dpi": 72.0,
                 "direction": "down", "layering": "replace", "paper": "white", "loop": False})
    sc.open()
    pump(0.05)
    assert sc.bed.isVisible() and sc.result.isVisible() and sc.panel.isVisible()
    page = w.sheet.scene_page_rect()
    sc.bed.setPos(page.right() + 120, page.top())          # on bare canvas
    sc.result.setPos(page.right() + 120 + sc.bed.w + 40, page.top())
    w.view.frame(sc.bed.scene_rect().united(sc.result.scene_rect()).adjusted(0, -40, 0, 300))
    pump(0.05)
    bed = sc.bed.scene_rect()
    red = os.path.join(TMP, "red.png")
    image = QtGui.QImage(100, 60, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("#e01010"))
    image.save(red)
    w.add_files([red], QtCore.QPointF(bed.left() + 90, bed.top() + 70))
    (thing,) = [t for t in w.things.values() if t.alive]
    thing.resize(100, 60)
    thing.setPos(bed.left() + 40, bed.top() + 40)
    w.clear_selection()
    sc.clear()
    run_scan(sc)
    assert not sc.running and sc.pos >= sc.length()
    buf = sc.buffer.astype(int)
    assert buf.shape[:2] == (round(bed.height()), round(bed.width()))
    inside = buf[50:90, 50:130]
    assert inside[..., 0].mean() > 180 and inside[..., 1].mean() < 60, "the red picture is scanned"
    assert buf[5:30, 5:30].min() > 245, "empty bed scans as paper"
    still = buf.copy()
    # smear: halfway through, the picture moves; the bottom half of it lands elsewhere
    sc.clear()
    sc.start()
    while sc.pos < 70:
        sc._last -= 0.05
        sc.tick()
    thing.moveBy(120, 0)
    run_scan(sc)
    smeared = sc.buffer.astype(int)
    assert np.abs(smeared[40:65, 40:140] - still[40:65, 40:140]).max() < 20   # top: as it was
    assert smeared[80:95, 50:130, 1].mean() > 200                               # bottom: moved away
    assert smeared[80:95, 170:250, 0].mean() > 180 and smeared[80:95, 170:250, 1].mean() < 60
    # xerox and dither
    for ink in ("xerox", "dither"):
        sc.s["ink"] = ink
        sc.clear()
        run_scan(sc)
        tones = np.unique(sc.buffer.reshape(-1, 3), axis=0)
        if ink == "dither":
            assert len(tones) <= 2, tones
        else:
            grey = sc.buffer.mean(axis=2)
            assert ((grey < 40) | (grey > 200)).mean() > 0.9
    # dragging out of the result picks the scan up as a new image
    before = len([t for t in w.things.values() if t.alive])
    result = sc.result.scene_rect()
    start = view_point(w, result.center())
    drag(w, start, start + QtCore.QPoint(0, int(result.height() * w.view.zoom()) + 40))
    alive = [t for t in w.things.values() if t.alive]
    assert len(alive) == before + 1
    scan = [t for t in alive if t is not thing][0]
    assert abs(scan.w - result.width()) < 0.5 and scan.image.width() == sc.buffer.shape[1]
    assert scan.sceneBoundingRect().top() > result.bottom()
    # frames: moved by the label, resized by the corner - both frames together
    label = sc.bed.label_rect(w.view.viewportTransform()).center()
    drag(w, label.toPoint(), label.toPoint() + QtCore.QPoint(-50, 0))
    assert sc.bed.scene_rect().left() < bed.left() - 10
    corner = w.view.viewportTransform().map(sc.bed.scene_rect().bottomRight())
    drag(w, corner.toPoint(), corner.toPoint() + QtCore.QPoint(60, 30))
    assert sc.result.w == sc.bed.w > bed.width() and sc.buffer.shape[1] == round(sc.bed.w)
    sc.close()
    assert not sc.bed.isVisible()
    w.close()


def stik_of(w):
    return [p for p, _h in w.plugins if p.name == "stik"][0]


def sticker_png(path: str) -> str:
    """Two red discs on a white sheet: something to cut and clean."""
    image = QtGui.QImage(400, 240, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("#ffffff"))
    p = QtGui.QPainter(image)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#d22a1e"))
    p.drawEllipse(30, 40, 140, 140)
    p.setBrush(QtGui.QColor("#1e44d2"))
    p.drawEllipse(230, 50, 130, 130)
    p.end()
    image.save(path)
    return path


def canvas_sheet(w):
    page = w.sheet.scene_page_rect()
    w.add_files([sticker_png(os.path.join(TMP, "sheet.png"))],
                QtCore.QPointF(page.right() + 400, page.top() + 200))
    (sheet,) = [t for t in w.things.values() if t.alive]
    sheet.resize(400, 240)          # 1 px = 1 pt, to keep the arithmetic plain
    w.view.frame(sheet.sceneBoundingRect().adjusted(-60, -60, 260, 260))
    pump(0.05)
    return sheet


def test_stik_cut_clean_and_undo():
    w = fresh()
    st = stik_of(w)
    sheet = canvas_sheet(w)
    origin = sheet.scenePos()
    # a rectangle cut round the red disc
    st.use("rect")
    assert w.active_tool is st.tools["rect"]
    a = view_point(w, origin + QtCore.QPointF(20, 30))
    b = view_point(w, origin + QtCore.QPointF(185, 195))
    drag(w, a, b)
    alive = [t for t in w.things.values() if t.alive]
    assert len(alive) == 2
    piece = [t for t in alive if t is not sheet][0]
    assert piece.name.startswith("sheet_") and piece.isSelected()
    assert sheet.alpha()[100, 100] == 0, "the hole is real"
    assert sheet.alpha()[100, 300] == 255, "the rest of the sheet is untouched"
    assert 160 <= piece.original.width() <= 170
    # cutout plus hole add back up to the original
    assert piece.alpha().max() == 255
    # undo brings the sheet back whole and the piece goes
    w.undo()
    assert not piece.alive and sheet.alpha()[100, 100] == 255
    w.redo()
    assert piece.alive and sheet.alpha()[100, 100] == 0
    # background removal on the cutout: the white goes, the disc stays
    w.use_tool(None)
    w.select([piece])
    st.s.update({"method": "flood", "tolerance": 18.0})
    st.remove_background(full=True)
    a = piece.alpha()
    assert a[3, 3] == 0 and a[a.shape[0] // 2, a.shape[1] // 2] == 255
    assert piece.matte is not None and piece.mask is not None
    w.reset_masks()
    assert piece.matte is None and piece.alpha()[3, 3] == 255
    w.undo()
    assert piece.matte is not None
    # the wand takes the white out of the sheet
    w.select([sheet])
    st.wand(sheet.mapToScene(QtCore.QPointF(5, 5)))
    assert sheet.alpha()[5, 5] == 0 and sheet.alpha()[110, 300] == 255
    st.wand(sheet.mapToScene(QtCore.QPointF(5, 5)), restore=True)
    assert sheet.alpha()[5, 5] == 255
    # the eraser rubs a stroke out of the blue disc, and shift paints it back
    st.s["eraser"], st.s["hardness"] = 20.0, 100.0
    st.use("eraser")
    drag(w, view_point(w, origin + QtCore.QPointF(260, 115)),
         view_point(w, origin + QtCore.QPointF(330, 115)))
    assert sheet.alpha()[115, 295] == 0 and sheet.alpha()[60, 295] == 255
    w.undo()
    assert sheet.alpha()[115, 295] == 255
    w.use_tool(None)
    w.close()


def test_stik_islands_border_mirror_merge_export_and_save():
    w = fresh()
    st = stik_of(w)
    sheet = canvas_sheet(w)
    w.select([sheet])
    st.s.update({"method": "flood", "tolerance": 18.0, "min_island": 400.0})
    st.islands()
    stickers = [t for t in w.things.values() if t.alive and t is not sheet]
    assert len(stickers) == 2, len(stickers)
    for t in stickers:
        a = t.alpha()
        assert a[0, 0] == 0 and a[a.shape[0] // 2, a.shape[1] // 2] == 255
    assert sheet.alpha()[110, 100] == 0 and sheet.alpha()[110, 295] == 0
    # a die-cut border grows each sticker by its width
    w.select(stickers)
    before = [t.sceneBoundingRect().width() for t in stickers]
    st.s.update({"border": 8.0, "border_smooth": 2.0, "border_colour": "#ffffff"})
    st.apply_border()
    for t, b in zip(stickers, before):
        assert t.border is not None and t.sceneBoundingRect().width() > b + 14
    # mirror, duplicate (Alt+drag), merge
    w.select([stickers[0]])
    w.mirror_selection(True)
    assert stickers[0].flip == (True, False)
    start = view_point(w, stickers[0].sceneBoundingRect().center())
    viewport = w.view.viewport()
    QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, QtCore.Qt.AltModifier, start)
    for k in range(1, 6):
        QtWidgets.QApplication.sendEvent(viewport, QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove, QtCore.QPointF(start + QtCore.QPoint(30 * k, 0)),
            QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.AltModifier))
    QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, QtCore.Qt.AltModifier,
                              start + QtCore.QPoint(150, 0))
    alive = [t for t in w.things.values() if t.alive]
    assert len(alive) == 4, "Alt+drag leaves the original and carries a copy"
    copy = [t for t in alive if t not in stickers and t is not sheet][0]
    assert copy.flip == (True, False) and copy.border == stickers[0].border
    w.select(stickers)
    w.merge_selection()
    merged = [t for t in w.things.values() if t.alive and t.name == "merged"]
    assert len(merged) == 1 and not any(t.alive for t in stickers)
    w.undo()
    assert all(t.alive for t in stickers) and not merged[0].alive
    # export pieces: one PNG each, named by the pattern, trimmed
    out = os.path.join(TMP, "pieces")
    os.makedirs(out, exist_ok=True)
    st.s.update({"pattern": "sticker-{n:02}", "scale": 100.0, "padding": 0.0, "trim": True})
    written = st.write(stickers, out)
    assert [os.path.basename(p) for p in written] == ["sticker-01.png", "sticker-02.png"]
    first = QtGui.QImage(written[0])
    assert first.hasAlphaChannel() and first.width() < 200
    # cut shapes, mattes, borders and mirroring are saved and come back
    path = os.path.join(TMP, "stik.ream")
    w.save_as(path)
    w.close()
    w2 = Ream([path])
    by_name = {t.name: t for t in w2.things.values() if t.alive}
    for t in stickers + [copy, sheet]:
        back = by_name[t.name] if list(by_name).count(t.name) == 1 else None
        if back is None:
            continue
        assert np.array_equal(back.alpha(), t.alpha()), t.name
        assert back.border == t.border and back.flip == t.flip
    w2.close()


def test_spelling_in_write_mode():
    try:
        os.remove(os.path.join(os.environ["REAM_HOME"], "dictionary.txt"))
    except OSError:
        pass
    w = fresh()
    w.prefs["spelling"] = True
    w.prefs["spelling_language"] = "en-gb"
    cursor = w.sheet.text.textCursor()
    cursor.insertText("The colour of teh page is writting itself. Zhulien was here.\n")
    w.sheet.text.setTextCursor(cursor)
    assert w.spelling_marks() == [], "only in write mode"
    w.enter_write_mode()
    pump(0.3)
    words = sorted(m[3] for m in w.spelling_marks())
    assert words == ["Zhulien", "teh", "writting"], words
    assert w.spelling_summary().startswith("3 words to check")
    w.grab()                                            # draws the squiggles
    # the word being typed is left alone until it is finished
    QtTest.QTest.keyClicks(w.view, "mispeled")
    assert "mispeled" not in [m[3] for m in w.spelling_marks()]
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert "mispeled" in [m[3] for m in w.spelling_marks()]
    # right-click on a flagged word: suggestions first; one replaces the word
    mark = [m for m in w.spelling_marks() if m[3] == "writting"][0]
    p0, p1 = mark[4][0]
    spot = QtCore.QPointF((p0.x() + p1.x()) / 2, p0.y() - 4)
    w.context_menu(w.view.viewport().mapToGlobal(spot.toPoint()), spot)
    pump(0.05)
    assert w.palette.isVisible() and w.palette.shown[0].title == "→ writing"
    w.palette.hide()
    w.palette.shown[0].run()
    assert "is writing itself" in w.doc.toPlainText()
    w.undo()
    assert "writting" in w.doc.toPlainText()
    # add to the dictionary: gone now, and for good
    w.speller().add("Zhulien")
    assert "Zhulien" not in [m[3] for m in w.spelling_marks()]
    assert "Zhulien" in open(os.path.join(os.environ["REAM_HOME"], "dictionary.txt")).read()
    assert spelling_known_fresh("Zhulien")
    # text blocks are checked too
    page = w.sheet.scene_page_rect()
    note = w.new_note(QtCore.QPointF(page.left() + 120, page.top() + 300))
    note.editor.textCursor().insertText("an exampel")
    w.finish_editing()
    w.focus_text()
    assert "exampel" in [m[3] for m in w.spelling_marks()]
    # Cmd+; turns it off (and on)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Semicolon, QtCore.Qt.ControlModifier)
    assert not w.spelling_on() and w.spelling_marks() == []
    w.toggle_spelling()
    assert w.spelling_on()
    w.leave_write_mode()
    assert w.spelling_marks() == []
    w.close()
    # a page with nothing wrong says so, rather than showing nothing
    clean = fresh()
    clean.prefs["spelling"] = True
    clean.sheet.text.textCursor().insertText("Every word here is spelled right.")
    clean.enter_write_mode()
    pump(0.2)
    assert clean.spelling_marks() == [] and clean.spelling_summary() == "nothing to correct on screen"
    clean.close()


def spelling_known_fresh(word: str) -> bool:
    from ream import spelling
    return spelling.Speller("en-gb").known(word)


def page_heads(w) -> list[str]:
    """The first few words of each page."""
    heads = []
    for index in range(w.sheet.text_pages()):
        pos = w._first_position_on(index)
        if pos is None:
            heads.append("")
            continue
        block = w.doc.findBlock(pos)
        heads.append(block.text()[pos - block.position():][:12])
    return heads


def test_pages_move_add_delete():
    w = fresh()
    type_paragraphs(w, 30)
    w.flip(0)
    pump()
    pages = w.sheet.pages()
    assert pages >= 4
    heads = page_heads(w)
    words = sorted(w.doc.toPlainText().split())
    # an image pinned to page 2
    w.flip(1)
    pump()
    w.add_files([make_png(os.path.join(TMP, "p2.png"))], w.sheet.scene_page_rect().center())
    (picture,) = [t for t in w.things.values() if t.alive]
    assert w._page_of(picture) == 1
    # move page 2 to the end
    w.move_page(1, pages - 1)
    after = page_heads(w)
    assert w.sheet.pages() == pages
    assert after[pages - 1] == heads[1], (after, heads)
    assert after[1] == heads[2]
    assert w._page_of(picture) == pages - 1, "pinned things go with their page"
    assert sorted(w.doc.toPlainText().split()) == words, "no word lost"
    # one undo puts the words and the picture back
    w.undo()
    assert page_heads(w)[1] == heads[1] and w._page_of(picture) == 1
    w.redo()
    assert page_heads(w)[pages - 1] == heads[1] and w._page_of(picture) == pages - 1
    w.undo()
    # a new page after the first: everything after moves down one
    w.add_page(0)
    assert w.sheet.pages() == pages + 1
    assert page_heads(w)[2] == heads[1] and w._page_of(picture) == 2
    assert w.page == 1
    w.undo()
    assert w.sheet.pages() == pages and w._page_of(picture) == 1
    # deleting page 2 takes its words and its picture
    w.delete_page(1)
    assert w.sheet.pages() == pages - 1 and not picture.alive
    assert page_heads(w)[1] == heads[2]
    w.undo()
    assert picture.alive and page_heads(w)[1] == heads[1]
    w.close()


def test_spreads_covers_and_pages_panel():
    w = fresh()
    w.fmt.cover, w.fmt.back_cover = True, False
    assert w.spreads(6) == [(None, 0), (1, 2), (3, 4), (5, None)]
    assert w.spreads(5) == [(None, 0), (1, 2), (3, 4)]
    w.fmt.back_cover = True
    assert w.spreads(5) == [(None, 0), (1, 2), (3, None), (4, None)]
    assert w.spreads(6) == [(None, 0), (1, 2), (3, 4), (5, None)]
    w.fmt.cover = False
    assert w.spreads(5) == [(0, 1), (2, 3), (4, None)]
    w.fmt.back_cover = False
    assert w.spreads(4) == [(0, 1), (2, 3)]
    w.set_covers(cover=True, back=False)
    type_paragraphs(w, 30)
    w.set_layout("all")
    pump(0.1)
    W = w.sheet.W
    assert abs(w.slot(0).x()) < 0.01, "the cover stands on the right of the spine"
    assert abs(w.slot(1).x() + W) < 0.01 and abs(w.slot(2).x()) < 0.01, "facing pages touch"
    assert w.slot(1).y() == w.slot(2).y() > w.slot(0).y(), "one spread a row, like the panel"
    assert w.slot(3).y() > w.slot(1).y()
    w.set_layout("single")
    # the pages panel: a thumbnail per page; dragging page 1 after page 3 moves it
    w.toggle_pages_panel()
    pump(0.1)
    strip = w.page_strip
    assert w.pages_panel.isVisible() and len(strip.rects()) == w.sheet.pages()
    heads = page_heads(w)
    rects = strip.rects()
    start = rects[0].center()
    end = QtCore.QPoint(rects[2].right() - 2, rects[2].center().y())
    QtTest.QTest.mousePress(strip, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, start)
    for k in range(1, 9):
        p = start + (end - start) * (k / 8.0)
        QtWidgets.QApplication.sendEvent(strip, QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove, QtCore.QPointF(p), QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
    QtTest.QTest.mouseRelease(strip, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, end)
    pump(0.1)
    assert page_heads(w)[2] == heads[0] and page_heads(w)[0] == heads[1]
    # clicking a thumbnail goes to that page
    QtTest.QTest.mouseClick(strip, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            strip.rects()[3].center())
    pump()
    assert w.page == 3
    w.grab()
    w.close()


def test_preview_mode():
    import pypdfium2
    w = fresh()
    type_paragraphs(w, 20)
    w.flip(1)
    pump()
    w.add_files([make_png(os.path.join(TMP, "pv.png"), "#2050d0")], w.sheet.scene_page_rect().center())
    w.clear_selection()
    w.flip(0)
    pump()
    w.distress.enabled = True
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_P, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    pump(0.1)
    pv = w.previewing
    assert w.in_preview() and pv.geometry() == w.rect()
    assert pv.units == [(i,) for i in range(w.sheet.pages())] and pv.at == 0
    # the finished page arrives, distressed, and matches the PDF export's page
    deadline = time.monotonic() + 15
    while pv.finished(0, pv.dpi()) is None and time.monotonic() < deadline:
        pump(0.1)
    shown = pv.finished(0, pv.dpi())
    assert shown is not None and shown.width() == round(w.sheet.W * pv.dpi() / 72)
    exported = export.final_page(w.sheet, 0, pv.dpi(), w.distress, w.paper(), w.ink(),
                                 w.density(), w.paper_stock())
    a = export.to_numpy(shown)[..., :3].astype(int)
    b = export.to_numpy(exported)[..., :3].astype(int)
    assert np.abs(a - b).mean() < 1.0, "the preview is the export"
    w.grab()
    # next page with the arrow key: the picture is on it
    QtTest.QTest.keyClick(pv, QtCore.Qt.Key_Right)
    assert pv.current_page() == 1
    deadline = time.monotonic() + 15
    while pv.finished(1, pv.dpi()) is None and time.monotonic() < deadline:
        pump(0.1)
    page2 = export.to_numpy(pv.finished(1, pv.dpi()))[..., :3].astype(int)
    blue = (page2[..., 2] > 150) & (page2[..., 0] < 90)
    assert blue.sum() > 100, "the pinned picture is in the preview"
    # spreads, background, end, and back out on the page last seen
    QtTest.QTest.keyClick(pv, QtCore.Qt.Key_S)
    assert pv.spread and pv.units[0] == (0,) and 1 in pv.units[pv.at]
    # a cover stands in the middle, at the same scale as the spreads
    pv.go(0)
    (_page, cover), = pv.rects()
    assert abs(cover.center().x() - pv.width() / 2) < 1.0
    pv.go(1)
    left, right = pv.rects()
    assert abs(left[1].width() - cover.width()) < 0.5 and abs(left[1].right() - right[1].left()) < 0.5
    # the background is the canvas colour unless asked otherwise
    assert pv.background == "canvas" and pv.backdrop().name() == QtGui.QColor(w.canvas_colour()).name()
    QtTest.QTest.keyClick(pv, QtCore.Qt.Key_W)
    assert pv.background == "white"
    QtTest.QTest.keyClick(pv, QtCore.Qt.Key_C)
    assert pv.background == "canvas"
    QtTest.QTest.keyClick(pv, QtCore.Qt.Key_End)
    last = pv.current_page()
    QtTest.QTest.keyClick(pv, QtCore.Qt.Key_Escape)
    pump()
    assert not w.in_preview() and w.page == last
    # clean exports preview clean: the same as the clean PDF's page
    w.distress.enabled = False
    w.enter_preview()
    pump(0.1)
    clean = w.previewing.finished(w.previewing.current_page(), w.previewing.dpi())
    assert clean is not None
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "pv.pdf"))
    assert len(pypdfium2.PdfDocument(pdf)) == w.sheet.pages()
    w.leave_preview()
    w.close()


def test_imposition_orders():
    from ream import imposition
    for style in imposition.STYLES:
        for n in (1, 2, 5, 8, 13, 24, 31):
            for per in (1, 3):
                layout = imposition.impose(n, style, per_signature=per, keep_back=False)
                order = imposition.reading_order(layout)
                assert order == list(range(n)) + [None] * (layout.padded - n), (style, n, per)
                # by default the blanks go before the back cover, which stays outside
                kept = imposition.reading_order(imposition.impose(n, style, per_signature=per))
                assert sorted(p for p in kept if p is not None) == list(range(n))
                if n >= 2:
                    assert kept[-1] == n - 1, (style, n, kept)
    six = imposition.impose(6, "saddle").sheets[0]
    assert [c.page for c in six.front] == [5, 0], "the back cover wraps the front cover"
    saddle = imposition.impose(8, "saddle")
    assert [[c.page for c in saddle.sheets[0].front], [c.page for c in saddle.sheets[0].back]] == \
        [[7, 0], [1, 6]]
    zine = imposition.impose(8, "zine8").sheets[0].front
    assert [c.page for c in zine if c.row == 0] == [4, 3, 2, 1] and all(c.turn == 180 for c in zine[:4])
    assert [c.page for c in zine if c.row == 1] == [5, 6, 7, 0]
    assert imposition.back_turn("single-long") == 180 and imposition.back_turn("single-short") == 0
    assert imposition.back_turn("single-top") == 180, "earlier names still work"


def test_export_panel_pick_and_spreads():
    import pypdfium2
    w = fresh()
    w.distress.enabled = False
    type_paragraphs(w, 40)
    w.set_covers(cover=True, back=False)
    n = w.sheet.pages()
    assert n >= 6, n
    # page ranges, both ways
    assert w.page_range_text([0, 1, 2, 3, 6]) == "1-4, 7"
    assert w.parse_page_range("1-4, 7", n) == {0, 1, 2, 3, 6}
    assert w.parse_page_range("", n) == set(range(n)) == w.parse_page_range("all", n)
    assert w.parse_page_range(f"{n - 1}-", n) == {n - 2, n - 1}
    assert w.parse_page_range("2 5 99", n) == {1, 4}
    # ⌘E opens the panel; every page is picked to begin with
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_E, QtCore.Qt.ControlModifier)
    pump(0.1)
    panel, strip = w.export_panel, w.export_strip
    assert panel.isVisible() and w.export_pages() == list(range(n))
    # click page 2 on the map: left out; drag from 4 across 5: left out too
    rects = strip.rects()
    w.set_export_option("spreads", False)
    QtTest.QTest.mouseClick(strip, QtCore.Qt.LeftButton, pos=rects[1].center())
    assert w.export_pages() == [p for p in range(n) if p != 1]
    QtTest.QTest.mousePress(strip, QtCore.Qt.LeftButton, pos=rects[3].center())
    move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(rects[4].center()),
                             QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
    app.sendEvent(strip, move)
    QtTest.QTest.mouseRelease(strip, QtCore.Qt.LeftButton, pos=rects[4].center())
    assert 3 not in w.export_pages() and 4 not in w.export_pages()
    # ⇧-click takes in the run from the last one
    QtTest.QTest.mouseClick(strip, QtCore.Qt.LeftButton, QtCore.Qt.ShiftModifier, rects[0].center())
    assert w.export_pages()[:4] == [0, 1, 2, 3] and 4 not in w.export_pages()   # back to page 4
    # the range field picks too
    field = [f for f in panel.findChildren(QtWidgets.QLineEdit)][0]
    field.setFocus()
    field.clear()
    QtTest.QTest.keyClicks(field, "1, 3-4")
    assert w.export_pages() == [0, 2, 3]
    assert "3 pages" in w.export_summary()
    # single pages, clean: three PDF pages, words still words
    path = w.export_now(os.path.join(TMP, "picked.pdf"))
    doc = pypdfium2.PdfDocument(path)
    assert len(doc) == 3
    assert abs(doc[0].get_size()[0] - w.sheet.W) < 1
    assert doc[1].get_textpage().get_text_range().strip(), "clean pages keep their words"
    # spreads: the cover alone, then whole spreads, twice as wide
    w.set_export_option("spreads", True)
    assert w.export_units([0, 2, 3]) == [(0,), (1, 2), (3, 4)]
    doc = pypdfium2.PdfDocument(w.export_now(os.path.join(TMP, "spreads.pdf")))
    assert len(doc) == 3
    assert abs(doc[0].get_size()[0] - w.sheet.W) < 1
    assert abs(doc[1].get_size()[0] - 2 * w.sheet.W) < 1 and abs(doc[1].get_size()[1] - w.sheet.H) < 1
    # in spreads, a click on the map takes the whole spread
    w.set_export_pages(set())
    QtTest.QTest.mouseClick(strip, QtCore.Qt.LeftButton, pos=strip.rects()[5].center())
    assert set(w.export_pages()) == set(w.export_units([5])[0])
    # distressed: pages are images (no words to pick out)
    w.set_export_pages({0})
    w.set_export_option("spreads", False)
    w.set_export_distressed(True)
    assert "distressed" in w.export_summary()
    doc = pypdfium2.PdfDocument(w.export_now(os.path.join(TMP, "rough_pick.pdf")))
    assert len(doc) == 1 and not doc[0].get_textpage().get_text_range().strip()
    # png spreads: one image per spread, named for its pages
    w.set_export_distressed(False)
    w.set_export_option("format", "png")
    w.set_export_option("spreads", True)
    w.set_export_pages({1})
    written = w.export_now(os.path.join(TMP, "pick.png"))
    assert [os.path.basename(p) for p in written] == ["pick_02-03.png"], written
    image = QtGui.QImage(written[0])
    assert image.width() > 1.9 * image.height() * w.sheet.W / w.sheet.H
    # nothing picked: nothing written
    w.set_export_option("format", "pdf")
    w.set_export_pages(set())
    assert w.export_now(os.path.join(TMP, "none.pdf")) is None
    assert not os.path.exists(os.path.join(TMP, "none.pdf"))
    # ⌘E with the panel open exports
    w.set_export_pages({0})
    w.set_export_option("spreads", False)
    target = os.path.join(TMP, "again.pdf")
    w._export_target = lambda *a: target
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_E, QtCore.Qt.ControlModifier)
    assert len(pypdfium2.PdfDocument(target)) == 1
    w.close()


def impose_of(w):
    return [p for p, _h in w.plugins if p.name == "impose"][0]


def test_impose_preview_and_bundle():
    import pypdfium2
    w = fresh()
    w.distress.enabled = False
    type_paragraphs(w, 28)                     # several pages
    pages = w.sheet.pages()
    heads = page_heads(w)
    imp = impose_of(w)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_I, QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
    pump(0.1)
    assert imp.view.isVisible() and imp.panel.isVisible()
    for key in imposition_styles():
        imp.s["style"] = key
        imp.view.guide = False
        imp.view.grab()
        imp.view.guide = True
        imp.view.grab()
    imp.view.guide = False
    QtTest.QTest.keyClick(imp.view, QtCore.Qt.Key_Right)
    assert imp.view.sheet_index == 1
    # a saddle-stitched booklet, single-sided printer, turned over the long edge
    imp.s.update({"style": "saddle", "sheet": "a4", "fit": True, "printing": "single-long",
                  "reverse": False, "marks": True})
    folder = imp.export_bundle(TMP)
    names = sorted(os.listdir(folder))
    assert names == ["1-fronts.pdf", "2-backs.pdf", "README.txt", "duplex.pdf", "guide.pdf",
                     "test-back.pdf", "test-front.pdf"], names
    layout = imp.layout()
    fronts = pypdfium2.PdfDocument(os.path.join(folder, "1-fronts.pdf"))
    assert len(fronts) == len(layout.sheets) == layout.padded // 4
    width, height = fronts[0].get_size()
    assert abs(width - 841.9) < 1 and abs(height - 595.3) < 1, "A4 landscape sheets"
    assert len(pypdfium2.PdfDocument(os.path.join(folder, "duplex.pdf"))) == 2 * len(layout.sheets)
    # sheet 1's front: the last page on the left, page 1 on the right
    text = fronts[0].get_textpage()
    right = text.get_text_bounded(left=width / 2, bottom=0, right=width, top=height)
    assert heads[0][:8] in right.replace("\r", "").replace("\n", " "), (heads[0], right[:80])
    readme = open(os.path.join(folder, "README.txt")).read()
    assert "turn the whole stack over its long edge" in readme and "staple" in readme
    assert len(pypdfium2.PdfDocument(os.path.join(folder, "guide.pdf"))) >= 2
    # long-edge backs are the short-edge backs turned 180° (the paper goes
    # through short edge first, so these landscape sheets go sideways)
    imp.s["printing"] = "single-short"
    short = imp.export_bundle(TMP)
    long_page = pypdfium2.PdfDocument(os.path.join(folder, "2-backs.pdf"))[0].render(scale=0.5).to_numpy()
    short_page = pypdfium2.PdfDocument(os.path.join(short, "2-backs.pdf"))[0].render(scale=0.5).to_numpy()
    turned = np.abs(long_page.astype(int) - np.rot90(short_page, 2).astype(int)).mean()
    plain = np.abs(long_page.astype(int) - short_page.astype(int)).mean()
    assert turned < 6 and plain > 3 * turned, (turned, plain)   # (antialiasing differs a little)
    # the backs reversed for printers that stack face up
    imp.s["reverse"] = True
    folder2 = imp.export_bundle(TMP)
    backs = pypdfium2.PdfDocument(os.path.join(folder2, "2-backs.pdf"))
    first_back = backs[0].get_textpage().get_text_range()
    last_sheet = layout.sheets[-1].back
    assert heads[last_sheet[0].page][:8] in first_back.replace("\r", "").replace("\n", " ") \
        or heads[last_sheet[1].page][:8] in first_back.replace("\r", "").replace("\n", " ")
    # a mini zine: one side, no backs or test sheet
    imp.s.update({"style": "zine8", "reverse": False})
    folder3 = imp.export_bundle(TMP)
    assert sorted(os.listdir(folder3)) == ["1-fronts.pdf", "README.txt", "guide.pdf"]
    assert len(pypdfium2.PdfDocument(os.path.join(folder3, "1-fronts.pdf"))) == \
        imp.layout().padded // 8
    QtTest.QTest.keyClick(imp.view, QtCore.Qt.Key_Escape)
    assert not imp.view.isVisible()
    w.close()


class FakePrinter:
    """Stands in for `lp` / `lpstat`: records what would have been printed;
    a job stays queued until `finish()`."""

    def __init__(self):
        self.jobs: list[list[str]] = []
        self.queued: list[str] = []

    def __call__(self, command, **kwargs):
        import subprocess
        out = ""
        if command[0] == "lp":
            self.jobs.append(command)
            job = f"EPSON-{len(self.jobs)}"
            self.queued.append(job)
            out = f"request id is {job} (1 file(s))\n"
        elif command[:2] == ["lpstat", "-a"]:
            out = "EPSON accepting requests since now\nOther accepting requests since now\n"
        elif command[:2] == ["lpstat", "-d"]:
            out = "system default destination: EPSON\n"
        elif command[:2] == ["lpstat", "-o"]:
            out = "".join(f"{job} zz 1024 now\n" for job in self.queued)
        return subprocess.CompletedProcess(command, 0, out, "")

    def finish(self):
        self.queued.clear()


def test_impose_prints_fronts_then_backs():
    from ream import printing
    fake = FakePrinter()
    real_run, real_available = printing.RUN, printing.available
    printing.RUN, printing.available = fake, (lambda: True)
    try:
        assert printing.printers() == ["EPSON", "Other"] and printing.default() == "EPSON"
        w = fresh()
        w.distress.enabled = False
        type_paragraphs(w, 20)
        imp = impose_of(w)
        imp.s.update({"style": "saddle", "sheet": "a4", "printing": "single-long",
                      "reverse": False, "printer": ""})
        imp.print_now()
        pump(0.1)
        flow = imp.flow
        assert flow is not None and flow.isVisible() and imp.view.isVisible()
        # step 1: only the fronts have gone, on the default printer, A4, one-sided
        assert len(fake.jobs) == 1
        lp = fake.jobs[0]
        assert lp[:3] == ["lp", "-d", "EPSON"] and "media=A4" in lp and "sides=one-sided" in lp
        assert lp[-1].endswith("1-fronts.pdf") and os.path.exists(lp[-1])
        # sent upright, as the A4 goes through the printer, the landscape
        # sheet turned a quarter onto it (the bundle's sheets stay landscape)
        import numpy as np
        import pypdfium2
        sent = pypdfium2.PdfDocument(lp[-1])
        width, height = sent[0].get_size()
        assert abs(width - 595.3) < 1 and abs(height - 841.9) < 1, (width, height)
        land = pypdfium2.PdfDocument(os.path.join(imp.export_bundle(TMP), "1-fronts.pdf"))
        assert land[0].get_size()[0] > land[0].get_size()[1]
        for k in range(len(sent)):
            upright = sent[k].render(scale=0.4).to_numpy().astype(int)
            turned = np.rot90(land[k].render(scale=0.4).to_numpy(), -1).astype(int)
            h, w_ = min(upright.shape[0], turned.shape[0]), min(upright.shape[1], turned.shape[1])
            same = np.abs(upright[:h, :w_] - turned[:h, :w_]).mean()
            other = np.abs(upright[:h, :w_] - np.rot90(turned, 2)[:h, :w_]).mean()
            assert same < 8 and other > 1.5 * same, (k, same, other)
        assert "printing" in flow.status.text()
        fake.finish()
        flow._check()
        assert flow.printed and "printed" in flow.status.text()
        flow.grab()
        # step 2: the turn - nothing more is sent until you say so
        QtTest.QTest.keyClick(flow, QtCore.Qt.Key_Return)
        assert flow.step()[0] == "turn" and len(fake.jobs) == 1
        assert "long edge" in flow.title.text()
        flow.grab()
        # step 3: the backs
        QtTest.QTest.keyClick(flow, QtCore.Qt.Key_Return)
        assert len(fake.jobs) == 2 and fake.jobs[1][-1].endswith("2-backs.pdf")
        sheets = len(imp.layout().sheets)
        assert len(pypdfium2.PdfDocument(fake.jobs[1][-1])) == sheets
        QtTest.QTest.keyClick(flow, QtCore.Qt.Key_Return)
        assert flow.step()[0] == "done"
        flow.grab()
        QtTest.QTest.keyClick(flow, QtCore.Qt.Key_Return)
        pump(0.05)
        assert imp.flow is None
        # a duplex printer: one job, both sides, flipped on the chosen edge
        imp.s.update({"printing": "duplex-short", "printer": "Other"})
        imp.print_now()
        assert len(fake.jobs) == 3
        lp = fake.jobs[2]
        assert lp[:3] == ["lp", "-d", "Other"] and "sides=two-sided-short-edge" in lp
        assert lp[-1].endswith("duplex.pdf")
        assert len(pypdfium2.PdfDocument(lp[-1])) == 2 * sheets
        imp.flow.close_card()
        pump(0.05)
        assert imp.flow is None
        # printing takes a while: fold the card into the "printing" panel,
        # go back to writing, and take the next steps from the panel
        from ream.panel import _Link
        imp.s.update({"printing": "single-long", "printer": ""})
        w.show()
        imp.print_now()
        flow, panel = imp.flow, imp.print_panel
        assert flow.isVisible() and not panel.isVisible()
        QtTest.QTest.keyClick(flow, QtCore.Qt.Key_Escape)       # Esc folds it, not stops it
        pump(0.05)
        assert imp.flow is flow and flow.minimised and not flow.isVisible() and panel.isVisible()
        assert "step 1 of 4" in panel.caption.text()
        imp.close()                                              # back to writing
        pump(0.05)
        assert not imp.view.isVisible() and panel.isVisible() and imp.flow is flow

        def panel_text():
            return " ".join(label.text() for label in panel.findChildren(QtWidgets.QLabel))

        def click(word):
            link = [l for l in panel.findChildren(_Link) if l.text() == word][0]
            QtTest.QTest.mouseClick(link, QtCore.Qt.LeftButton)
            pump(0.02)

        assert "printing the fronts" in panel_text() and "printing…" in panel_text()
        fake.finish()
        flow._check()                                            # the queue is still followed
        assert "printed ✓" in panel_text()
        jobs = len(fake.jobs)
        click("next")
        assert flow.step()[0] == "turn" and flow.minimised and len(fake.jobs) == jobs
        assert "turn the stack" in panel_text()
        click("print the backs")
        assert len(fake.jobs) == jobs + 1 and fake.jobs[-1][-1].endswith("2-backs.pdf")
        assert flow.minimised and "printing the backs" in panel_text()
        click("open")                                            # the card again
        assert flow.isVisible() and not flow.minimised and not panel.isVisible()
        flow.minimise()
        click("stop")
        pump(0.05)
        assert imp.flow is None and not panel.isVisible()
        # the palette command brings the card back
        imp.print_now()
        imp.flow.minimise()
        imp.printing_status()
        assert imp.flow.isVisible()
        imp.flow.close_card()
        # a mini zine: one side only, so just the fronts
        imp.s.update({"style": "zine8", "printing": "single-long", "printer": ""})
        before = len(fake.jobs)
        imp.print_now()
        assert len(fake.jobs) == before + 1 and fake.jobs[-1][-1].endswith("1-fronts.pdf")
        assert [step[0] for step in imp.flow.steps] == ["send", "done"]
        imp.flow.close_card()
        # the test sheet: its front, the turn, its back
        imp.s.update({"style": "saddle"})
        imp.print_now(test=True)
        assert fake.jobs[before + 1][-1].endswith("test-front.pdf")
        QtTest.QTest.keyClick(imp.flow, QtCore.Qt.Key_Return)
        QtTest.QTest.keyClick(imp.flow, QtCore.Qt.Key_Return)
        assert fake.jobs[before + 2][-1].endswith("test-back.pdf") and len(fake.jobs) == before + 3
        imp.flow.close_card()
        # a draft: the whole job as outlines and numbers, at the printer's
        # draft quality, black only - in standard words and the driver's own
        ppd_dir = os.path.join(TMP, "ppd")
        os.makedirs(ppd_dir, exist_ok=True)
        with open(os.path.join(ppd_dir, "EPSON.ppd"), "w") as f:
            f.write("""*OpenUI *EPIJ_Ink_/Grayscale: PickOne
*DefaultEPIJ_Ink_: 1
*EPIJ_Ink_ 1/Off: ""
*EPIJ_Ink_ 0/On: ""
*CloseUI: *EPIJ_Ink_
*OpenUI *EPIJ_Mode/Mode: PickOne
*EPIJ_Mode 0/Automatic: ""
*EPIJ_Mode 3/Advanced: ""
*CloseUI: *EPIJ_Mode
*OpenUI *EPIJ_Qual/Print Quality: PickOne
*DefaultEPIJ_Qual: 303
*EPIJ_Qual 308/Draft: ""
*EPIJ_Qual 303/Normal: ""
*EPIJ_Qual 307/Best Quality: ""
*CloseUI: *EPIJ_Qual
*OpenUI *ColorModel/ColorModel: PickOne
*ColorModel RGB/Color: ""
*ColorModel Mono/Grayscale: ""
*CloseUI: *ColorModel
*OpenUI *Resolution/Resolution: PickOne
*Resolution 360x360dpi/360 dpi: ""
*Resolution 180x180dpi/180 dpi: ""
*CloseUI: *Resolution
""")
        real_ppd, printing.PPD_DIR = printing.PPD_DIR, ppd_dir
        try:
            options = printing.draft_options("EPSON")
            for wanted in ("print-quality=3", "print-color-mode=monochrome", "EPIJ_Qual=308",
                           "EPIJ_Ink_=0", "EPIJ_Mode=3", "ColorModel=Mono", "Resolution=180x180dpi"):
                assert wanted in options, (wanted, options)
            assert printing.draft_options("nowhere") == ["-o", "print-quality=3", "-o",
                                                         "print-color-mode=monochrome"]

            def ink(path):                     # at about a draft print's 180 dpi
                doc = pypdfium2.PdfDocument(path)
                return np.mean([255 - doc[k].render(scale=2.5, grayscale=True).to_numpy().mean()
                                for k in range(len(doc))])

            imp.s.update({"style": "saddle", "printing": "single-long", "printer": ""})
            done = len(fake.jobs)
            imp.print_now()
            full = fake.jobs[done][-1]
            assert "EPIJ_Qual=308" not in fake.jobs[done], "a real print is not a draft"
            imp.flow.close_card()
            imp.print_now(draft=True)
            assert "draft" in imp.flow.caption.text()
            lp = fake.jobs[done + 1]
            assert "EPIJ_Qual=308" in lp and "print-quality=3" in lp and lp[-1].endswith("1-fronts.pdf")
            assert len(pypdfium2.PdfDocument(lp[-1])) == sheets
            assert ink(lp[-1]) < 0.4 * ink(full), (ink(lp[-1]), ink(full))
            QtTest.QTest.keyClick(imp.flow, QtCore.Qt.Key_Return)
            QtTest.QTest.keyClick(imp.flow, QtCore.Qt.Key_Return)
            assert "EPIJ_Qual=308" in fake.jobs[done + 2] and fake.jobs[done + 2][-1].endswith("2-backs.pdf")
            imp.flow.close_card()
            # the test sheet goes as a draft too, and is mostly paper
            imp.print_now(test=True)
            lp = fake.jobs[done + 3]
            assert "EPIJ_Qual=308" in lp and ink(lp[-1]) < 1.0, ink(lp[-1])
            imp.flow.close_card()
        finally:
            printing.PPD_DIR = real_ppd
        # a printer that refuses: said on the card, nothing breaks
        fake_fail = lambda command, **kw: __import__("subprocess").CompletedProcess(   # noqa: E731
            command, 1, "", "lp: The printer or class does not exist.") \
            if command[0] == "lp" else fake(command, **kw)
        printing.RUN = fake_fail
        imp.print_now()
        assert "does not exist" in imp.flow.status.text()
        imp.flow.close_card()
        w.close()
    finally:
        printing.RUN, printing.available = real_run, real_available


def right_click(w, scene_point: QtCore.QPointF):
    at = view_point(w, scene_point)
    viewport = w.view.viewport()
    QtTest.QTest.mousePress(viewport, QtCore.Qt.RightButton, QtCore.Qt.NoModifier, at)
    QtTest.QTest.mouseRelease(viewport, QtCore.Qt.RightButton, QtCore.Qt.NoModifier, at)
    event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, at, viewport.mapToGlobal(at))
    app.sendEvent(viewport, event)
    pump(0.05)


def test_right_click_opens_panels_and_tools_panel():
    w = fresh()
    w.show()
    w.distress.enabled = False
    type_paragraphs(w, 2)
    page = w.sheet.scene_page_rect()
    # a text box: the text panel, for it
    note = w.new_note(QtCore.QPointF(page.left() + 100, page.top() + 500), wrap=200.0, top=True)
    QtTest.QTest.keyClicks(w.view, "a box")
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    right_click(w, note.sceneBoundingRect().center())
    assert w.text_panel is not None and w.text_panel.isVisible()
    assert w.selection() == [note] and "1 box" in w.text_panel.caption.text()
    w.text_panel.close_panel()
    # an image: stik's panel
    qimage = QtGui.QImage(60, 40, QtGui.QImage.Format_ARGB32)
    qimage.fill(QtGui.QColor("#c33"))
    image = w.place_qimage(qimage, QtCore.QRectF(page.left() - 300, page.top(), 60, 40), "red")
    stik = stik_of(w)
    assert not stik.panel.isVisible()
    right_click(w, image.sceneBoundingRect().center())
    assert stik.panel.isVisible() and w.selection() == [image]
    stik.panel.close_panel()
    # the page round the words: the page panel; the words: the text panel
    right_click(w, QtCore.QPointF(page.left() + 12, page.bottom() - 12))
    assert w.page_panel is not None and w.page_panel.isVisible()
    w.page_panel.close_panel()
    w.set_mode("design")
    right_click(w, QtCore.QPointF(page.left() + w.fmt.margin + 30, page.top() + w.fmt.head + 6))
    assert w.text_panel.isVisible() and w.story_selected and "main text" in w.text_panel.caption.text()
    w.text_panel.close_panel()
    # the scanner's frames: its panel
    scanner = scanner_of(w)
    scanner.open()
    scanner.panel.hide()                 # (closing it would close the scanner too)
    right_click(w, scanner.bed.scene_rect().center())
    assert scanner.panel.isVisible()
    scanner.close()
    # the empty canvas: the palette, as before
    right_click(w, page.topLeft() - QtCore.QPointF(400, 300))
    assert w.palette.isVisible()
    w.palette.hide()
    # the tools panel: every tool, the current one inked
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_T, QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
    tools = w.tools_panel
    assert tools.isVisible()
    labels = [e["label"] for e in w.tool_entries()]
    for label in ("write", "select", "text box", "lasso cut", "rectangle cut", "ellipse cut",
                  "wand", "eraser"):
        assert label in labels, labels
    assert w.active_tool_id() == "select"
    w.choose_tool("text box")
    assert w.design() and w.text_tool and w.active_tool_id() == "text box"
    lasso = [e for e in w.tool_entries() if e["label"] == "lasso cut"][0]
    w.choose_tool(lasso["id"])
    assert w.active_tool is stik.tools["lasso"] and not w.text_tool
    assert w.active_tool_id() == lasso["id"]
    # clicking a row in the panel picks it
    from ream.panel import _Menu
    menu = tools.findChild(_Menu)
    row = [n for n, r in enumerate(menu.rows) if r[1] == "select"][0]
    QtTest.QTest.mouseClick(menu, QtCore.Qt.LeftButton, pos=QtCore.QPoint(20, row * menu.ROW + 10))
    assert w.active_tool is None and w.design() and not w.text_tool
    # design mode: a tool's letter picks it
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_W)
    assert w.active_tool is stik.tools["wand"]
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    assert w.active_tool is None
    w.choose_tool("write")
    assert w.mode == "writer" and w.active_tool_id() == "write"
    stik.panel.close_panel()
    w.close()


def test_version_is_semver_and_in_the_changelog():
    import re
    import contextlib
    import io
    import ream
    from ream import app as ream_app
    semver = (r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
              r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
              r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")
    assert re.match(semver, ream.__version__), ream.__version__
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyproject = open(os.path.join(root, "pyproject.toml")).read()
    assert 'dynamic = ["version"]' in pyproject and 'path = "src/ream/__init__.py"' in pyproject
    assert not re.search(r"^version\s*=", pyproject, re.M), "one place only"
    changelog = open(os.path.join(root, "CHANGELOG.md")).read()
    assert f"## [{ream.__version__}] - " in changelog and "Semantic Versioning 2.0.0" in changelog
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            ream_app.main(["--version"])
        except SystemExit:
            pass
    assert out.getvalue().strip() == f"ream {ream.__version__}"


def test_space_plays_and_stops_the_scanner():
    w = fresh()
    w.show()
    type_paragraphs(w, 1)
    words = w.doc.toPlainText()
    scanner = scanner_of(w)
    # closed: Space is a space, as ever
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert w.doc.toPlainText() == words + " "
    w.undo()
    words = w.doc.toPlainText()
    scanner.open()
    pump(0.05)
    w.view.setFocus()
    # open, in writer mode: the page is being written, so Space is still a space
    w.focus_text()
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert not scanner.running and w.doc.toPlainText() == words + " "
    w.undo()
    words = w.doc.toPlainText()
    # design mode, nothing being written: a tap plays, another stops - types nothing
    w.set_mode("design", quiet=True)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert scanner.running
    pump(0.1)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert not scanner.running and scanner.pos > 0
    assert w.doc.toPlainText() == words
    # holding Space and dragging still pans, and doesn't play
    viewport = w.view.viewport()
    before = w.view.horizontalScrollBar().value()
    QtTest.QTest.keyPress(w.view, QtCore.Qt.Key_Space)
    start = QtCore.QPoint(300, 300)
    QtTest.QTest.mousePress(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, start)
    app.sendEvent(viewport, QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(200, 300),
                                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                                              QtCore.Qt.NoModifier))
    QtTest.QTest.mouseRelease(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(200, 300))
    QtTest.QTest.keyRelease(w.view, QtCore.Qt.Key_Space)
    assert w.view.horizontalScrollBar().value() != before and not scanner.running
    # writing in a text box: Space is a space there
    page = w.sheet.scene_page_rect()
    note = w.new_note(QtCore.QPointF(page.left() + 80, page.top() + 400))
    QtTest.QTest.keyClicks(w.view, "two words")
    assert note.text() == "two words" and not scanner.running
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    # writing in the main text in design mode: a space too
    w.start_story_editing()
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert not scanner.running and w.doc.toPlainText().endswith(" ")
    w.leave_story_editing(select=False)
    w.undo()
    # writer mode with something selected (nothing being written): it plays
    w.set_mode("writer", quiet=True)
    w.select([note])
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert scanner.running
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert not scanner.running
    w.clear_selection()
    # closed again: Space types once more
    scanner.close()
    w.focus_text()
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Space)
    assert not scanner.running and w.doc.toPlainText().endswith(" ")
    w.close()


def make_stamp_textures():
    """A stamps folder like a downloaded one, made here: a tape sheet (three
    pieces on clear), a stain photographed on white, dust on black, a torn matte."""
    import cv2
    from ream import wear
    root = wear.folder()
    for sub in ("tape", "stains", "dust", "torn mattes"):
        os.makedirs(root / sub, exist_ok=True)
    sheet = np.zeros((300, 600, 4), np.uint8)
    for n in range(3):
        sheet[60:120, 40 + n * 190:200 + n * 190] = (120, 190, 220, 255)
    cv2.imwrite(str(root / "tape" / "tape_sheet.png"), sheet)
    stain = np.full((400, 400, 3), 245, np.uint8)
    cv2.circle(stain, (200, 200), 120, (60, 90, 120), 18)
    cv2.imwrite(str(root / "stains" / "stain.jpg"), stain)
    dust = np.zeros((300, 300, 3), np.uint8)
    for x, y in ((40, 50), (200, 90), (120, 240)):
        cv2.circle(dust, (x, y), 6, (230, 230, 230), -1)
    cv2.imwrite(str(root / "dust" / "dust.jpg"), dust)
    matte = np.zeros((300, 400), np.uint8)
    cv2.rectangle(matte, (30, 25), (370, 275), 255, -1)
    cv2.imwrite(str(root / "torn mattes" / "torn_rect.jpg"), matte)
    (root / "index.json").write_text(json.dumps({
        "tape/tape_sheet.png": {"label": "Masking tape", "split": 6},
        "stains/stain.jpg": {"label": "Ring stain", "tint": "brown"},
        "torn mattes/torn_rect.jpg": {"label": "Torn rectangle"}}))
    return root


def test_wear_tears_edges_and_places_stamps():
    import json as _json  # noqa: F401
    from ream import wear
    make_stamp_textures()
    # the library: categories from the folders, mattes kept apart, sheets split
    entries = wear.library()
    assert {e["category"] for e in entries} == {"tape", "stains", "dust", "torn mattes"}
    assert wear.categories(entries) == ["drawn", "dust", "stains", "tape"]
    tape = [e for e in entries if e["label"] == "Masking tape"][0]
    assert len(wear.stamp_variants(tape)) == 3
    stain = wear.as_rgba([e for e in entries if e["label"] == "Ring stain"][0]["path"])
    assert stain[200, 200, 3] < 30 and stain[200, 80, 3] > 200, "dark marks on white become the ink"
    dust = wear.as_rgba([e for e in entries if e["category"] == "dust"][0]["path"])
    assert dust[50, 40, 3] > 200 and dust[5, 5, 3] < 30, "light marks on black too"
    for kind in wear.DRAWN:
        art = wear.drawn(kind, seed=2, px=300)
        assert art.shape[2] == 4 and art[..., 3].max() > 100
    w = fresh()
    w.show()
    plugin = [p for p, _h in w.plugins if p.name == "wear"][0]
    page = w.sheet.scene_page_rect()
    qimage = QtGui.QImage(400, 300, QtGui.QImage.Format_ARGB32)
    qimage.fill(QtGui.QColor("#3355aa"))
    image = w.place_qimage(qimage, QtCore.QRectF(page.left() + 60, page.top() + 80, 200, 150), "photo")
    w.select([image])
    # ⌥⌘W: the panel
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_W, QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
    assert plugin.panel.isVisible()
    # tear: the edges go, the middle stays, a paper rim along the cut
    steps = len(w.history)
    plugin.tear()
    assert image.tear and image.tear["sides"] == "all" and len(w.history) == steps + 1
    alpha = image.image.convertToFormat(QtGui.QImage.Format_ARGB32)
    corner, middle = QtGui.QColor(alpha.pixelColor(1, 1)), QtGui.QColor(alpha.pixelColor(200, 150))
    assert corner.alpha() < 40 and middle.alpha() == 255 and middle.blue() > 150
    # somewhere along the top edge the paper's white core shows (the tear is random)
    rim = [QtGui.QColor(alpha.pixelColor(x, y)) for x in range(20, 380, 6) for y in range(0, 40)]
    assert any(c.alpha() > 200 and c.red() > 200 and c.green() > 200 for c in rim), "the paper core"
    assert image.original.pixelColor(1, 1).alpha() == 255, "the original is untouched"
    # the sliders follow live, one undo step a drag
    plugin.panel.refresh()
    plugin.s["depth"] = 20.0
    plugin.retear()
    plugin.s["depth"] = 25.0
    plugin.retear()
    plugin._released()
    assert image.tear["depth"] == 25.0 and len(w.history) == steps + 2
    w.undo()
    assert image.tear["depth"] == wear.DEFAULT_TEAR["depth"]
    # one side only, a torn matte, mend, undo
    plugin.s["sides"] = "bottom"
    plugin.tear(fresh=True)
    edge = image.image.convertToFormat(QtGui.QImage.Format_ARGB32)
    assert edge.pixelColor(200, 1).alpha() == 255 and edge.pixelColor(200, 298).alpha() < 40
    plugin.set_edge("Torn rectangle")
    plugin.tear()
    assert image.tear["matte"].endswith("torn_rect.jpg")
    plugin.mend()
    assert image.tear is None and image.image.pixelColor(1, 1).alpha() == 255
    w.undo()
    assert image.tear and image.tear["matte"]
    # saved and loaded with it
    state, media = w.state()
    entry = [t for t in state["things"] if t.get("name") == "photo"][0]
    assert entry["tear"]["matte"].endswith("torn_rect.jpg")
    # stamps: a drawn coffee ring, sized as a share of the page
    plugin.choose_stamp("drawn:coffee ring")
    assert w.active_tool is plugin.stamp_tool
    plugin.s.update({"size": 30.0, "jitter": 0.0, "turn": "none", "tint": "as is", "strength": 100.0})
    plugin._next = None
    spot = QtCore.QPointF(page.left() + 300, page.top() + 500)
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            view_point(w, spot))
    stamps = [t for t in w.things.values() if t.alive and t.name.startswith("stamp")]
    assert len(stamps) == 1 and stamps[0].pinned and stamps[0].name == "stamp · coffee ring"
    assert abs(stamps[0].w - w.sheet.W * 0.30) < 1.0
    assert stamps[0].sceneBoundingRect().contains(spot)
    # the tape sheet: a piece a click, tinted, faded
    plugin.set_category("tape")
    assert len(plugin.grid.entries) == 1 and plugin.grid.entries[0]["label"] == "Masking tape"
    plugin.choose_stamp(tape["key"])
    plugin.s.update({"tint": "red", "strength": 50.0, "turn": "any"})
    for n in range(4):
        plugin.stamp_at(QtCore.QPointF(page.left() + 100 + n * 60, page.top() + 650))
    taped = [t for t in w.things.values() if t.alive and t.name == "stamp · Masking tape"]
    assert len(taped) == 4
    pixel = taped[0].image.convertToFormat(QtGui.QImage.Format_ARGB32)
    solid = [QtGui.QColor(pixel.pixelColor(x, pixel.height() // 2)) for x in range(pixel.width())]
    strong = max(solid, key=lambda c: c.alpha())
    assert 100 < strong.alpha() < 150 and strong.red() > strong.blue(), (strong.getRgb(),)
    # undo takes a stamp back
    w.undo()
    assert len([t for t in w.things.values() if t.alive and t.name == "stamp · Masking tape"]) == 3
    # the tools panel lists the tools; in design mode their letters pick them
    labels = [e["label"] for e in w.tool_entries()]
    assert "stamp" in labels and "tear" in labels
    w.use_tool(None)
    w.set_mode("design", quiet=True)
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_R)
    assert w.active_tool is plugin.tear_tool
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_S)
    assert w.active_tool is plugin.stamp_tool
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_Escape)
    # stamps and tears go out with the PDF
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "wear.pdf"))
    import pypdfium2
    rendered = pypdfium2.PdfDocument(pdf)[0].render(scale=0.5).to_numpy()
    assert rendered.std() > 5
    plugin.panel.close_panel()
    w.close()


def test_faster_distress_is_the_same():
    from dataclasses import replace
    from ream import distress
    w = fresh()
    type_paragraphs(w, 6)
    w.distress.enabled = True
    below, text, above = export.ink_layers(w.sheet, 0, 150, w.ink())
    # the cropped kernel gives exactly what working on the whole layer gives
    for change in ({}, {"misfire": 70, "bleed": 50, "blur": 90}, {"edge": 40, "inner": 90}):
        s = replace(w.distress, **change)
        whole = distress._apply(text.rgba, s, 150, (0, 0), 1.0)
        cropped = distress.apply(text.rgba, s, 150)
        assert (whole[..., 3] == cropped[..., 3]).all(), change
        inked = whole[..., 3] > 0
        assert (whole[..., :3][inked] == cropped[..., :3][inked]).all(), change
    # pages distressed in parallel are the pages raster_page makes
    pages = list(range(min(3, w.sheet.pages())))
    got = dict(export.distressed_pages(w.sheet, pages, 150, w.distress, w.paper(), w.ink(),
                                       w.density(), w.paper_stock(), workers=3))
    for index in pages:
        assert got[index] == export.raster_page(w.sheet, index, 150, w.distress, w.paper(), w.ink(),
                                                w.density(), w.paper_stock()), index
    # a distressed PDF still has every page, in order
    import pypdfium2
    pdf = w.export_pdf(path=os.path.join(TMP, "parallel.pdf"))
    assert len(pypdfium2.PdfDocument(pdf)) == w.sheet.pages()
    # a big image follows a tear slider from a small draft, then is finished
    plugin = [p for p, _h in w.plugins if p.name == "wear"][0]
    page = w.sheet.scene_page_rect()
    big = QtGui.QImage(3000, 2200, QtGui.QImage.Format_ARGB32)
    big.fill(QtGui.QColor("#336699"))
    thing = w.place_qimage(big, QtCore.QRectF(page.left() + 40, page.top() + 60, 300, 220), "big")
    w.select([thing])
    plugin.tear()
    before = thing.image
    steps = len(w.history)
    plugin.s["depth"] = 24.0
    plugin.retear(draft=True)
    plugin.s["depth"] = 28.0
    plugin.retear(draft=True)
    assert thing.drafted and thing.image is before and thing.preview.width() <= 1000
    assert thing.tear["depth"] == 28.0 and len(w.history) == steps + 1
    plugin._released()
    assert not thing.drafted and thing.image is not before
    assert thing.image.width() == 3000
    # the finished tear is the one a direct tear makes
    direct = thing.image
    thing.set_pixels(tear=dict(thing.tear))
    assert thing.image == direct
    # or a moment after the slider stops, without letting go
    plugin.s["depth"] = 12.0
    plugin.retear(draft=True)
    assert thing.drafted
    pump(0.5)
    assert not thing.drafted
    w.close()


def test_a_picture_across_a_spread():
    import pypdfium2
    w = fresh()
    w.show()
    w.distress.enabled = False
    type_paragraphs(w, 30)
    w.set_covers(cover=True, back=False)              # spreads: 1 | 2-3 | 4-5 ...
    w.set_layout("spread")
    w.go_to_page(1)                                   # page 2, the left of a spread
    pump(0.1)
    assert w.facing(1) == (2, w.sheet.W, -w.sheet.H) and w.facing(2) == (1, -w.sheet.W, w.sheet.H)
    assert w.facing(0) is None, "the cover stands alone"
    page = w.sheet.scene_page_rect()
    red = QtGui.QImage(300, 200, QtGui.QImage.Format_ARGB32)
    red.fill(QtGui.QColor("#dd2211"))
    # across the gutter, its middle a little on the left page
    thing = w.place_qimage(red, QtCore.QRectF(page.right() - 180, page.top() + 300, 300, 200), "wide")
    assert thing.pinned and w.sheet.page_of(thing) == 1
    # page 2 shows its left part, page 3 its right part (the overhang)
    def strip(index, dpi=36):
        image = export.final_page(w.sheet, index, dpi, w.distress, w.paper(), w.ink())
        return image.convertToFormat(QtGui.QImage.Format_RGB32)
    left, right = strip(1), strip(2)
    k = 36 / 72.0
    y = int((300 + 100) * k)
    assert QtGui.QColor(left.pixel(left.width() - 3, y)).red() > 200 > QtGui.QColor(left.pixel(left.width() - 3, y)).green()
    reach = int((300 - 180) * k)                       # how far it reaches onto page 3
    assert QtGui.QColor(right.pixel(2, y)).red() > 200 > QtGui.QColor(right.pixel(2, y)).green()
    assert QtGui.QColor(right.pixel(reach - 3, y)).green() < 100
    assert QtGui.QColor(right.pixel(reach + 6, y)).green() > 200, "and no further"
    # the page beside it on screen shows the overhang too (drawn from the document)
    ghost = w.ghosts[2]
    shot = w.view.grab().toImage()
    over = w.view.mapFromScene(ghost.sceneBoundingRect().left() + 20, page.top() + 400)
    assert QtGui.QColor(shot.pixel(over)).red() > 200 > QtGui.QColor(shot.pixel(over)).green()
    # it can be picked up by its overhang, on the facing page
    w.clear_selection()
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, over)
    assert w.selection() == [thing]
    # ...and a thing on page 3 hanging back over page 2 shows and picks up there
    w.clear_selection()
    blue = QtGui.QImage(200, 100, QtGui.QImage.Format_ARGB32)
    blue.fill(QtGui.QColor("#1133dd"))
    w.make_live(2)
    pump(0.05)
    right_page = w.sheet.scene_page_rect()
    other = w.place_qimage(blue, QtCore.QRectF(right_page.left() - 60, right_page.top() + 600, 200, 100),
                           "blue")
    assert w.sheet.page_of(other) == 2
    w.make_live(1)
    pump(0.05)
    live = w.sheet.scene_page_rect()
    spot = QtCore.QPointF(live.right() - 30, live.top() + 650)
    shot = w.view.grab().toImage()
    pixel = QtGui.QColor(shot.pixel(w.view.mapFromScene(spot)))
    assert pixel.blue() > 200 > pixel.red(), pixel.getRgb()       # drawn on the live page
    QtTest.QTest.mouseClick(w.view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            view_point(w, spot))
    assert w.selection() == [other] and w.sheet.page_of(other) == 1, "its home is the live page now"
    seen = other.sceneBoundingRect()                  # ...but it is where it was seen
    assert seen.contains(spot) and seen.right() > live.right() + 100
    assert abs(seen.left() - (live.right() - 60)) < 1.0
    # exported as spreads: one picture, unbroken across the gutter
    w.set_export_option("spreads", True)
    pdf = w.export_pdf(clean=True, path=os.path.join(TMP, "across.pdf"), pages=[1, 2], spreads=True)
    sheet_image = pypdfium2.PdfDocument(pdf)[0].render(scale=0.5).to_numpy()
    row = sheet_image[int(400 * 0.5)]
    middle = sheet_image.shape[1] // 2
    reds = [(c[2] > 200 and c[1] < 100) for c in row[middle - 40: middle + 40]]      # (BGR)
    assert all(reds), "across the spine without a break"
    w.close()


def test_instagram_slides_and_seamless_carousel():
    from ream.plugins import instagram as ig
    w = fresh()
    w.show()
    w.distress.enabled = False
    type_paragraphs(w, 30)
    w.set_covers(cover=True, back=False)
    n = w.sheet.pages()
    plugin = [p for p, _h in w.plugins if p.name == "instagram"][0]
    # ⌥⌘G: the slides and the panel
    QtTest.QTest.keyClick(w.view, QtCore.Qt.Key_G, QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)
    assert plugin.view.isVisible() and plugin.panel.isVisible()
    assert ig.slide_size("4:5", 1080) == (1080, 1350) and ig.slide_size("1.91:1", 1080) == (1080, 566)
    # how many slides each way
    plugin.s.update({"mode": "pages"})
    assert plugin.plan().slides == n
    plugin.s.update({"mode": "spreads", "per_spread": 2})
    spreads = w.spreads(n)
    expected = sum(max(1, round(2 * len([p for p in pair if p is not None]) / 2)) for pair in spreads)
    assert plugin.plan().slides == expected
    plugin.s.update({"mode": "one long strip", "fit": "fit", "margin": 0.0, "zoom": 100.0, "gap": 0.0})
    p = plugin.plan()
    page_px = w.sheet.W * (1350 / w.sheet.H)
    assert p.slides == math.ceil(n * page_px / 1080 - 1e-6)
    # the pages run on without a gap in the strip, centred in the slides
    xs = sorted(pl.rect.left() for pl in p.placed)
    assert all(abs((b - a) - page_px) < 0.01 for a, b in zip(xs, xs[1:]))
    # the slides are the full picture cut edge to edge: nothing lost, nothing doubled
    full = plugin.picture()
    assert full.width() == p.slides * 1080 and full.height() == 1350
    cut = plugin.slides(full)
    assert len(cut) == p.slides and all(c.width() == 1080 and c.height() == 1350 for c in cut)
    for k in range(len(cut) - 1):
        a = cut[k].pixel(1079, 700)
        b = cut[k + 1].pixel(0, 700)
        assert a == full.pixel(k * 1080 + 1079, 700) and b == full.pixel((k + 1) * 1080, 700)
    # fit leaves the background round the pages; fill covers the slides
    plugin.s.update({"mode": "pages", "fit": "fit", "margin": 10.0, "background": "black"})
    one = plugin.slides()[1]
    assert QtGui.QColor(one.pixel(5, 5)) == QtGui.QColor("#000000")
    plugin.s.update({"fit": "fill"})
    one = plugin.slides()[1]
    assert QtGui.QColor(one.pixel(5, 5)) != QtGui.QColor("#000000"), "filled to the edge"
    # zoom and nudge move the pages
    plugin.s.update({"fit": "fit", "margin": 0.0, "zoom": 80.0, "nudge_x": 10.0})
    pl = plugin.plan().placed[0].rect
    assert abs(pl.height() - 1350 * 0.8) < 0.5 and pl.center().x() > 540 + 100
    plugin.s.update({"zoom": 100.0, "nudge_x": 0.0, "margin": 4.0})
    # a page range
    plugin.set_pages("2-3")
    plugin.s.update({"mode": "spreads"})
    assert sorted(pl.page for pl in plugin.plan().placed) == [1, 2] and plugin.plan().slides == 2
    plugin.set_pages("all")
    # export: numbered slides, then the whole picture fitted into one more slide
    # of the same shape (Instagram crops every image to the first one's shape)
    plugin.s.update({"mode": "spreads", "format": "jpg", "full": "last slide + file",
                     "background": "black"})
    folder = plugin.export(TMP)
    names = sorted(os.listdir(folder))
    count = plugin.plan().slides
    assert plugin.posted() == count + 1
    assert names == [f"{k:02d}.jpg" for k in range(1, count + 2)] + ["full.jpg"], names
    sizes = {(lambda i: (i.width(), i.height()))(QtGui.QImage(os.path.join(folder, f"{k:02d}.jpg")))
             for k in range(1, count + 2)}
    assert sizes == {(1080, 1350)}, "every image the carousel's shape"
    assert QtGui.QImage(os.path.join(folder, "full.jpg")).size() == QtCore.QSize(count * 1080, 1350)
    last = QtGui.QImage(os.path.join(folder, f"{count + 1:02d}.jpg"))
    fitted = plugin.fit_rect(count * 1080, 1350, QtCore.QRectF(0, 0, 1080, 1350))
    assert abs(fitted.width() / fitted.height() - count * 1080 / 1350) < 0.01, "the whole picture, not cropped"
    assert fitted.width() <= 1080 and fitted.height() < 1350 / 2
    assert QtGui.QColor(last.pixel(540, 20)).lightness() < 20, "background above it"
    assert QtGui.QColor(last.pixel(540, 1330)).lightness() < 20, "and below"
    assert QtGui.QColor(last.pixel(540, 675)).lightness() > 60, "the picture in the middle"
    # the other choices
    for full, extra, file in (("last slide", 1, False), ("file", 0, True), ("no", 0, False)):
        plugin.s["full"] = full
        names = sorted(os.listdir(plugin.export(TMP)))
        assert names == [f"{k:02d}.jpg" for k in range(1, count + 1 + extra)] + (["full.jpg"] if file else []), (full, names)
    plugin.s["full"] = "last slide"
    plugin.view.grab()
    # more than Instagram takes in one post: said in the preview
    plugin.s.update({"mode": "pages", "shape": "1.91:1"})
    w.view.grab()
    plugin.view.grab()
    plugin.s.update({"shape": "4:5"})
    QtTest.QTest.keyClick(plugin.view, QtCore.Qt.Key_Escape)
    assert not plugin.view.isVisible()
    w.close()


def test_a_bleeding_spread_picture_keeps_no_extra_page():
    w = fresh()
    w.show()
    w.distress.enabled = False
    w.set_mode("design", quiet=True)
    w.set_covers(cover=False, back=False)
    w.add_page()                                      # a spread: pages 1-2
    w.set_layout("spread")
    w.go_to_page(0)
    pump(0.05)
    page = w.sheet.scene_page_rect()
    red = QtGui.QImage(600, 300, QtGui.QImage.Format_ARGB32)
    red.fill(QtGui.QColor("#dd2211"))
    # over the whole spread, bleeding off every edge
    pic = w.place_qimage(red, QtCore.QRectF(page.left() - 9, page.top() - 9, 2 * w.sheet.W + 18,
                                            w.sheet.H + 18), "spread")
    assert w.sheet.pages() == 2, "the bleed doesn't make a third page"
    # a real third page, then deleted: gone, and the picture stays
    w.add_page(1)
    assert w.sheet.pages() == 3
    w.delete_page(2)
    assert w.sheet.pages() == 2 and pic.alive
    # what hangs off a page's foot shows on no other page
    w.add_page(1)
    third = export.final_page(w.sheet, 2, 36, w.distress, w.paper(), w.ink())
    top = QtGui.QColor(third.pixel(third.width() // 2, 1))
    assert top.green() > 200, "no red at the head of page 3"
    w.delete_page(2)
    assert w.sheet.pages() == 2
    # both pages of the spread show their half
    for index in (0, 1):
        image = export.final_page(w.sheet, index, 36, w.distress, w.paper(), w.ink())
        middle = QtGui.QColor(image.pixel(image.width() // 2, image.height() // 2))
        assert middle.red() > 200 > middle.green(), index
    w.close()


def test_saving_big_media_never_stalls():
    import zipfile
    from ream import project
    w = fresh()
    w.show()
    w._ready = True
    # a PDF of many pages: every page shares the whole file
    pdf = os.path.join(TMP, "many.pdf")
    writer = QtGui.QPdfWriter(pdf)
    painter = QtGui.QPainter(writer)
    for n in range(12):
        if n:
            writer.newPage()
        painter.fillRect(QtCore.QRectF(0, 0, writer.width(), writer.height() / 3),
                         QtGui.QColor.fromHsv(n * 30, 200, 200))
    painter.end()
    page = w.sheet.scene_page_rect()
    hashed = []
    real = project.media_name
    project.media_name = lambda blob, ext: (hashed.append(len(blob)), real(blob, ext))[1]
    try:
        w.add_files([pdf], page.center())
        assert len([t for t in w.things.values() if t.alive]) == 12
        w.state()
        w.state()
        assert len(hashed) == 1, "the PDF is hashed once, not per page per save"
    finally:
        project.media_name = real
    # the timer's saves go on a thread; a second one while it runs is folded in
    target = str(w.draft_path())
    w.autosave(background=True)
    w.autosave(background=True)
    assert w._save_again
    w.wait_for_save()
    pump(0.3)                                         # the follow-up save comes round
    w.wait_for_save()
    assert not w._save_again and os.path.exists(target)
    # media are stored as they are (no squeezing a PDF again)
    with zipfile.ZipFile(target) as archive:
        kinds = {i.filename.rsplit(".", 1)[-1]: i.compress_type for i in archive.infolist()
                 if i.filename.startswith("media/")}
    assert kinds.get("pdf") == zipfile.ZIP_STORED, kinds
    state, media = project.load(target)
    assert len([t for t in state["things"] if t.get("pdf_page") is not None]) == 12
    # an explicit save waits for one under way, then writes at once
    w.autosave(background=True)
    w.save_as(os.path.join(TMP, "big.ream"))
    assert w._saving.done() and os.path.exists(os.path.join(TMP, "big.ream"))
    w.close()


def test_big_pdfs_stay_light_on_memory():
    from ream import page as P
    w = fresh()
    w.show()
    w.distress.enabled = False
    pdf = os.path.join(TMP, "light.pdf")
    writer = QtGui.QPdfWriter(pdf)
    writer.setResolution(150)
    painter = QtGui.QPainter(writer)
    for n in range(8):
        if n:
            writer.newPage()
        painter.fillRect(QtCore.QRectF(0, 0, writer.width(), writer.height() / 2),
                         QtGui.QColor.fromHsv(n * 40, 200, 210))
        painter.drawText(QtCore.QRectF(0, 0, writer.width(), writer.height()), QtCore.Qt.AlignCenter, str(n))
    painter.end()
    limit = P.ORIGINALS.limit
    try:
        P.ORIGINALS.limit = 40 * 2 ** 20                  # room for only a few pages' originals
        w.add_files([pdf], w.sheet.scene_page_rect().center())
        things = [t for t in w.things.values() if t.alive]
        assert len(things) == 8
        held = [t for t in things if t._original is not None]
        assert len(held) < 8 and P.ORIGINALS.total <= P.ORIGINALS.limit + things[0].px_w * things[0].px_h * 4
        # the on-screen copies are small; the pixels are let go, not lost
        assert all(max(t.preview.width(), t.preview.height()) <= P.PREVIEW_SMALL for t in things)
        gone = [t for t in things if t._original is None][0]
        again = gone.original
        reference = gone._decode()
        assert again is not None and again == reference, "decoded again, the same pixels"
        assert gone.px_w == again.width() and gone.px_h == again.height()
        # drawing the pages beside the live one, and the thumbnails, decode nothing
        decoded = []
        real = P.Thing._decode
        P.Thing._decode = lambda self: (decoded.append(self.uid), real(self))[1]
        try:
            for t in things:
                t._let_go()
            w.set_layout("spread")
            w.fit_layout()
            pump(0.1)
            w.view.viewport().repaint()
            w.toggle_pages_panel()
            pump(0.1)
            w.pages_panel.grab()
            assert decoded == [], decoded
            # an export does (each page as it goes)
            w.export_pdf(clean=True, path=os.path.join(TMP, "light-out.pdf"))
            assert decoded
        finally:
            P.Thing._decode = real
        # undo keeps no copy of the original, and still works after it was let go
        target = things[0]
        target._let_go()
        w.set_border([target], 6.0, "#ffffff", 2.0)
        assert target.border is not None
        target._let_go()
        w.undo()
        assert target.border is None and target.image.size() == QtCore.QSize(target.px_w, target.px_h)
        # drawn big, an image gets a bigger copy; drawn small, the small one
        image = QtGui.QImage(100, 100, QtGui.QImage.Format_ARGB32)
        p = QtGui.QPainter(image)
        assert target.shown_pixmap(p) is target.preview
        p.scale(6.0, 6.0)
        big = target.shown_pixmap(p)
        p.end()
        assert big is not target.preview and big.width() > target.preview.width()
        assert P.BIG_PREVIEWS.total > 0
    finally:
        P.ORIGINALS.limit = limit
    w.close()


def test_an_image_hanging_off_a_page_still_pins_and_exports():
    w = fresh()
    w.show()
    w.distress.enabled = False
    type_paragraphs(w, 12)
    w.set_covers(cover=False, back=False)            # spreads 1-2, 3-4
    w.set_layout("spread")
    w.go_to_page(0)
    pump(0.3)
    page = w.sheet.scene_page_rect()                  # page 1, the left of its spread
    red = QtGui.QImage(240, 160, QtGui.QImage.Format_ARGB32)
    red.fill(QtGui.QColor("#dd2211"))
    # hanging off the outer edge: its middle off the page, half of it on
    out = w.place_qimage(red, QtCore.QRectF(page.left() - 150, page.top() + 300, 240, 160), "bleed")
    assert out.pinned and out.home == 0, "pinned to the page it covers"
    image = export.final_page(w.sheet, 0, 36, w.distress, w.paper(), w.ink())
    k = 36 / 72.0
    pixel = QtGui.QColor(image.pixel(int(40 * k), int(380 * k)))
    assert pixel.red() > 200 > pixel.green(), "and exported, cut at the edge"
    # barely touching a page: stays on the canvas
    far = w.place_qimage(red, QtCore.QRectF(page.left() - 230, page.top() + 600, 240, 160), "touch")
    assert not far.pinned
    # bleeding off the head: still its page's, not the page above's
    w.go_to_page(2)
    pump(0.3)
    third = w.sheet.scene_page_rect()
    top = w.place_qimage(red, QtCore.QRectF(third.left() + 100, third.top() - 110, 240, 160), "head")
    assert top.pinned and top.home == 2 and w.sheet.page_of(top) == 2
    shown = {i: [t for t, _dx, _dy in w.sheet.page_things(i)] for i in range(w.sheet.pages())}
    assert top in shown[2] and top not in shown[1], "it shows on its own page only"
    # undo / redo, save / load keep where it belongs
    w.undo()
    assert not top.alive
    w.redo()
    assert top.alive and top.home == 2
    state, media = w.state()
    entry = [t for t in state["things"] if t.get("name") == "head"][0]
    assert entry["home"] == 2
    w.load_state(state, media)
    again = [t for t in w.things.values() if t.alive and t.name == "head"][0]
    assert again.home == 2 and w.sheet.page_of(again) == 2
    # deleting a page before it moves it along
    w.delete_page(0)
    assert again.home == 1 and w.sheet.page_of(again) == 1
    w.close()


def imposition_styles():
    from ream import imposition
    return list(imposition.STYLES)


def main() -> int:
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        started = time.monotonic()
        try:
            fn()
            print(f"ok    {name}  ({time.monotonic() - started:.1f}s)")
        except Exception:
            failed += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
