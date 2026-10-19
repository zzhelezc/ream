"""
Panels: a slip of paper with sliders, for dialling something in by hand.

Set like the palette: a grey caption, hairline rules, solid-ink handles.  A
panel floats over the canvas, top right until you drag it by its caption,
and closes with Esc or its ×.  Rows are built from getters and setters, so
the panel never holds state of its own: `refresh()` re-reads everything.

Row kinds: a slider (double-click its name for the default), a chooser
(‹ name ›, or click the name for the list), colour swatches (+ opens a
picker), a two-way toggle and a row of text buttons.
"""
from __future__ import annotations

from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets

from . import style

WIDTH = 330

QSS = f"""
#Panel {{ background: #ffffff; border: 1px solid {style.INK}; }}
#PanelCaption {{ color: #8c8b86; background: transparent; }}
#PanelClose {{ color: {style.INK}; background: transparent; }}
#PanelName {{ color: {style.INK}; background: transparent; }}
#PanelValue {{ color: #8c8b86; background: transparent; }}
#PanelLink {{ color: {style.INK}; background: transparent; }}
#PanelLink:hover {{ color: #ffffff; background: {style.INK}; }}
#PanelSection {{ color: #8c8b86; background: transparent; padding-top: 6px; }}
#PanelScroll, #PanelBody {{ background: transparent; }}
QScrollBar:vertical {{ width: 5px; background: transparent; margin: 0; }}
QScrollBar::handle:vertical {{ background: {style.INK}; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QSlider {{ background: transparent; min-height: 16px; }}
QSlider::groove:horizontal {{ height: 1px; background: {style.INK}; margin: 0 4px; }}
QSlider::sub-page:horizontal {{ height: 3px; background: {style.INK}; margin: 0 0 0 4px; }}
QSlider::handle:horizontal {{ width: 9px; height: 9px; margin: -5px -4px; background: {style.INK};
                              border: 1px solid {style.INK}; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
"""


class _Link(QtWidgets.QLabel):
    """A word that is a button."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("PanelLink")
        self.setFont(style.ui_font(12))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setContentsMargins(4, 1, 4, 1)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()


class _Swatch(QtWidgets.QWidget):
    clicked = QtCore.pyqtSignal()

    def __init__(self, colour: str | None):
        super().__init__()
        self.colour = colour          # None: the "+" that opens a picker
        self.chosen = False
        self.setFixedSize(18, 18)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        box = QtCore.QRectF(2.5, 2.5, 13, 13)
        ink = style.qc(style.INK)
        if self.colour is None:
            painter.setPen(QtGui.QPen(ink, 1))
            painter.drawLine(QtCore.QPointF(9, 4), QtCore.QPointF(9, 14))
            painter.drawLine(QtCore.QPointF(4, 9), QtCore.QPointF(14, 9))
            return
        painter.fillRect(box, style.qc(self.colour))
        painter.setPen(QtGui.QPen(ink, 1))
        painter.drawRect(box)
        if self.chosen:
            painter.setPen(QtGui.QPen(ink, 1.5))
            painter.drawRect(QtCore.QRectF(0.75, 0.75, 16.5, 16.5))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()


class Panel(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget, title: str,
                 on_close: Callable[[], None] | None = None,
                 on_tab: Callable[[], None] | None = None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setStyleSheet(QSS)
        self.setFixedWidth(WIDTH)
        self.on_close = on_close
        self.on_tab = on_tab
        self.on_release: Callable[[], None] | None = None
        self._refreshers: list[Callable[[], None]] = []
        self._drag_from: QtCore.QPoint | None = None
        self.placed = False

        self.column = QtWidgets.QVBoxLayout(self)
        self.column.setContentsMargins(14, 10, 14, 12)
        self.column.setSpacing(4)
        head = QtWidgets.QHBoxLayout()
        self.caption = QtWidgets.QLabel(title)
        self.caption.setObjectName("PanelCaption")
        self.caption.setFont(style.ui_font(11))
        close = _Link("×")
        close.setObjectName("PanelClose")
        close.clicked.connect(self.close_panel)
        head.addWidget(self.caption, 1)
        head.addWidget(close)
        self.column.addLayout(head)
        self.column.addWidget(self._rule())
        # the rows live in a scroll area, so a tall panel still fits a short window
        self.body = QtWidgets.QWidget()
        self.body.setObjectName("PanelBody")
        self.grid = QtWidgets.QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 9, 0)          # room for the scroll bar
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(5)
        self.grid.setColumnMinimumWidth(0, 62)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnMinimumWidth(2, 44)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("PanelScroll")
        self.scroll.setWidget(self.body)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.column.addWidget(self.scroll)
        self.hide()

    # -- building ------------------------------------------------------------
    def _rule(self) -> QtWidgets.QWidget:
        rule = QtWidgets.QWidget()
        rule.setFixedHeight(7)

        def paint(event, widget=rule):
            painter = QtGui.QPainter(widget)
            pen = QtGui.QPen(style.qc(style.INK), 1.0, QtCore.Qt.CustomDashLine)
            pen.setDashPattern([1.0, 2.5])
            painter.setPen(pen)
            painter.drawLine(QtCore.QPointF(0, 3.5), QtCore.QPointF(widget.width(), 3.5))
        rule.paintEvent = paint
        return rule

    def _name(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("PanelName")
        label.setFont(style.ui_font(12))
        return label

    def _row(self) -> int:
        return self.grid.rowCount()

    def section(self, text: str):
        label = QtWidgets.QLabel(text)
        label.setObjectName("PanelSection")
        label.setFont(style.ui_font(11))
        self.grid.addWidget(label, self._row(), 0, 1, 3)

    def slider(self, name: str, lo: float, hi: float, get: Callable[[], float],
               put: Callable[[float], None], step: float = 1.0, unit: str = "",
               default: float | None = None) -> QtWidgets.QSlider:
        row = self._row()
        label = self._name(name)
        bar = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        bar.setRange(int(round(lo / step)), int(round(hi / step)))
        bar.setFocusPolicy(QtCore.Qt.ClickFocus)
        value = QtWidgets.QLabel()
        value.setObjectName("PanelValue")
        value.setFont(style.ui_font(12))
        value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        def shown(v: float):
            value.setText(f"{v:g}{unit}")

        def moved(n: int):
            v = round(n * step, 4)
            shown(v)
            put(v)

        def refresh():
            v = get()
            bar.blockSignals(True)
            bar.setValue(int(round(v / step)))
            bar.blockSignals(False)
            shown(round(v, 4))

        bar.valueChanged.connect(moved)
        bar.sliderReleased.connect(lambda: self.on_release and self.on_release())
        if default is not None:
            label.setToolTip(f"double-click: back to {default:g}{unit}")

            def reset(event, d=default):
                bar.setValue(int(round(d / step)))
            label.mouseDoubleClickEvent = reset
        self.grid.addWidget(label, row, 0)
        self.grid.addWidget(bar, row, 1)
        self.grid.addWidget(value, row, 2)
        self._refreshers.append(refresh)
        return bar

    def choice(self, name: str, options: Callable[[], list[str]], get: Callable[[], str],
               put: Callable[[str], None]):
        row = self._row()
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(2)
        back, ahead, current = _Link("‹"), _Link("›"), _Link("")

        def step(delta: int):
            names = options()
            here = names.index(get()) if get() in names else 0
            put(names[(here + delta) % len(names)])
            refresh()

        def menu():
            pick = QtWidgets.QMenu(self)
            pick.setFont(style.ui_font(12))
            for option in options():
                action = pick.addAction(("● " if option == get() else "   ") + option)
                action.triggered.connect(lambda _c=False, o=option: (put(o), refresh()))
            pick.exec_(current.mapToGlobal(QtCore.QPoint(0, current.height())))

        def refresh():
            current.setText(get())

        back.clicked.connect(lambda: step(-1))
        ahead.clicked.connect(lambda: step(1))
        current.clicked.connect(menu)
        box.addWidget(back)
        box.addWidget(current, 1, QtCore.Qt.AlignCenter)
        box.addWidget(ahead)
        self.grid.addWidget(self._name(name), row, 0)
        self.grid.addLayout(box, row, 1, 1, 2)
        self._refreshers.append(refresh)

    def swatches(self, name: str, colours: list[str], get: Callable[[], str],
                 put: Callable[[str], None]):
        row = self._row()
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(3)
        chips = [_Swatch(c) for c in colours]
        more = _Swatch(None)
        more.setToolTip("any colour")

        def refresh():
            now = QtGui.QColor(get()).name()
            for chip in chips:
                chip.chosen = QtGui.QColor(chip.colour).name() == now
                chip.update()

        def pick_custom():
            colour = QtWidgets.QColorDialog.getColor(QtGui.QColor(get()), self.window(), name)
            if colour.isValid():
                put(colour.name())
                refresh()

        for chip in chips:
            chip.clicked.connect(lambda c=chip.colour: (put(c), refresh()))
            box.addWidget(chip)
        more.clicked.connect(pick_custom)
        box.addWidget(more)
        box.addStretch(1)
        self.grid.addWidget(self._name(name), row, 0)
        self.grid.addLayout(box, row, 1, 1, 2)
        self._refreshers.append(refresh)

    def toggle(self, name: str, get: Callable[[], bool], put: Callable[[bool], None],
               on: str = "on", off: str = "off"):
        row = self._row()
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(6)
        yes, no = _Link(on), _Link(off)

        def refresh():
            for link, state in ((yes, True), (no, False)):
                chosen = get() == state
                link.setStyleSheet(f"color: #ffffff; background: {style.INK};" if chosen else "")

        yes.clicked.connect(lambda: (put(True), refresh()))
        no.clicked.connect(lambda: (put(False), refresh()))
        box.addWidget(yes)
        box.addWidget(no)
        box.addStretch(1)
        self.grid.addWidget(self._name(name), row, 0)
        self.grid.addLayout(box, row, 1, 1, 2)
        self._refreshers.append(refresh)

    def text(self, name: str, get: Callable[[], str], put: Callable[[str], None]):
        """A line of text (a file-name pattern, say), set as you type."""
        row = self._row()
        field = QtWidgets.QLineEdit()
        field.setFont(style.ui_font(12))
        field.setStyleSheet(f"QLineEdit {{ border: none; border-bottom: 1px solid {style.INK};"
                            f" background: transparent; color: {style.INK}; padding: 1px 0; }}")
        field.textEdited.connect(put)

        def refresh():
            if not field.hasFocus():
                field.setText(get())

        self.grid.addWidget(self._name(name), row, 0)
        self.grid.addWidget(field, row, 1, 1, 2)
        self._refreshers.append(refresh)
        return field

    def widget(self, widget: QtWidgets.QWidget, refresh: Callable[[], None] | None = None):
        """Any widget, the panel's full width (a page strip, say)."""
        self.grid.addWidget(widget, self._row(), 0, 1, 3)
        if refresh:
            self._refreshers.append(refresh)
        return widget

    def links(self, name: str, entries: list[tuple[str | Callable[[], str], Callable[[], None]]]):
        """A row of words that are buttons; a word may be a function, so it
        can change ("save" becomes "save *" when there is something to save)."""
        row = self._row()
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(4)
        made = []
        for text, run in entries:
            link = _Link(text() if callable(text) else text)
            link.clicked.connect(lambda r=run: (r(), self.refresh()))
            box.addWidget(link)
            made.append((link, text))
        box.addStretch(1)

        def refresh():
            for link, text in made:
                if callable(text):
                    link.setText(text())

        self.grid.addWidget(self._name(name), row, 0)
        self.grid.addLayout(box, row, 1, 1, 2)
        self._refreshers.append(refresh)

    def buttons(self, entries: list[tuple[str, Callable[[], None]]]):
        self.column.addSpacing(4)
        self.column.addWidget(self._rule())
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(4)
        for text, run in entries:
            link = _Link(text)
            link.clicked.connect(run)
            box.addWidget(link)
        box.addStretch(1)
        self.column.addLayout(box)

    # -- using ---------------------------------------------------------------
    def refresh(self):
        for refresh in self._refreshers:
            refresh()

    def fit_height(self):
        """As tall as the rows need, or as the window allows - then it scrolls."""
        need = self.body.sizeHint().height() + 2
        host = self.parentWidget().rect().height()
        chrome = self.sizeHint().height() - self.scroll.sizeHint().height()
        room = max(120, host - 24 - chrome)
        self.scroll.setFixedHeight(min(need, room))
        self.adjustSize()

    def open(self):
        self.refresh()
        self.fit_height()
        if not self.placed:
            host = self.parentWidget().rect()
            self.move(host.width() - self.width() - 20, 20)
            self.placed = True
        self.keep_inside()
        self.show()
        self.raise_()

    def keep_inside(self):
        self.fit_height()
        host = self.parentWidget().rect()
        x = max(4, min(self.x(), host.width() - self.width() - 4))
        y = max(4, min(self.y(), host.height() - self.height() - 4))
        self.move(x, y)

    def close_panel(self):
        self.hide()
        if self.on_close:
            self.on_close()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and event.pos().y() < 34:
            self._drag_from = event.globalPos() - self.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            self.move(event.globalPos() - self._drag_from)
            self.keep_inside()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        event.accept()

    def wheelEvent(self, event):
        event.accept()                  # never falls through to the canvas

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close_panel()
            return
        if event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab) and self.on_tab:
            self.on_tab()
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, forward: bool) -> bool:
        if self.on_tab:
            self.on_tab()
        return True
