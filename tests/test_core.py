"""
End-to-end checks that drive the real window headless:

    QT_QPA_PLATFORM=offscreen uv run python tests/test_core.py

They use a throwaway home folder (REAM_HOME), never yours.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

TMP = tempfile.mkdtemp(prefix="ream-test-")
os.environ["REAM_HOME"] = os.path.join(TMP, "home")
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
