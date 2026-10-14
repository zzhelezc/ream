"""
The command palette, and the only UI: Tab, type, Enter.

It drops at the pointer as in TouchDesigner (and stik), so a command that adds
something puts it where the palette was opened.  It is set as a slip of paper:
a grey caption line, a query after a ✱, a dotted rule and the matches, the
chosen one printed in solid ink.

Two kinds of entry beyond plain commands:

- a **fill** entry types into the query instead of running ("edge" fills
  "edge " so a number can follow);
- **dynamic** entries come from the query itself: "edge 14", "page 3",
  "size 10" turn into "set edge → 14" and friends, ranked first.

Matching is forgiving: a prefix beats a substring beats all-the-words beats a
subsequence, and with an empty query the commands used last come first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets

from . import style

MAX_ROWS = 13
WIDTH = 460
RECENT_KEEP = 12


@dataclass
class Command:
    title: str
    run: Callable[[], object] | None = None
    hint: str = ""                      # grey, on the right: value or shortcut
    keywords: str = ""
    fill: str = ""                      # typed into the query instead of running
    key: str = field(default="")        # stable id for the recents list

    def __post_init__(self):
        if not self.key:
            self.key = self.title


def score(query: str, command: Command) -> float | None:
    """Higher is better; None means no match."""
    q = query.lower().strip()
    if not q:
        return 0.0
    title = command.title.lower()
    haystack = f"{title} {command.keywords.lower()}"
    if title.startswith(q):
        return 1000.0 - len(title)
    at = title.find(q)
    if at >= 0:
        boundary = at == 0 or title[at - 1] in " :-/_(·"
        return 800.0 + (60.0 if boundary else 0.0) - at - len(title) * 0.1
    words = q.split()
    if all(word in haystack for word in words):
        return 600.0 - len(title) * 0.1
    points, last = 0.0, -1
    for ch in q.replace(" ", ""):
        found = title.find(ch, last + 1)
        if found < 0:
            return None
        if found == last + 1:
            points += 8.0
        if found == 0 or title[found - 1] in " :-/_(":
            points += 12.0
        last = found
    return 200.0 + points - len(title) * 0.2


_HINT = QtCore.Qt.UserRole + 1


class _Row(QtWidgets.QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QtCore.QSize(WIDTH, 24)

    def paint(self, painter, option, index):
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        rect = option.rect
        painter.save()
        if selected:
            painter.fillRect(rect, style.qc(style.INK))
        font = style.ui_font(12)
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        area = rect.adjusted(14, 0, -14, 0)
        hint = index.data(_HINT) or ""
        hint_w = metrics.horizontalAdvance(hint) + 16 if hint else 0
        painter.setPen(style.qc("#9a9a96") if selected else style.qc("#8c8b86"))
        painter.drawText(area, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, hint)
        painter.setPen(style.qc("#ffffff") if selected else style.qc(style.INK))
        room = area.adjusted(0, 0, -hint_w, 0)
        painter.drawText(room, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                         metrics.elidedText(index.data(QtCore.Qt.DisplayRole),
                                            QtCore.Qt.ElideRight, room.width()))
        painter.restore()


class _Rule(QtWidgets.QWidget):
    """The dotted rule under the query."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(5)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen(style.qc(style.INK), 1.0, QtCore.Qt.CustomDashLine)
        pen.setDashPattern([1.0, 2.5])
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(14, 2.5), QtCore.QPointF(self.width() - 14, 2.5))


QSS = f"""
#Palette {{ background: #ffffff; border: 1px solid {style.INK}; }}
#PaletteCaption {{ color: #8c8b86; padding: 10px 14px 2px 14px; background: transparent; }}
#PaletteStar {{ color: {style.INK}; padding: 0 0 0 14px; background: transparent; }}
#PaletteQuery {{ border: none; background: transparent; color: {style.INK};
                 padding: 6px 14px 6px 6px;
                 selection-background-color: {style.INK}; selection-color: #ffffff; }}
#PaletteList {{ border: none; background: transparent; outline: 0; padding: 2px 0 8px 0; }}
"""


class CommandPalette(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget, provider: Callable[[], list[Command]],
                 dynamic: Callable[[str], list[Command]] | None = None,
                 caption: Callable[[], str] | None = None,
                 recents: list[str] | None = None):
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("Palette")
        self.setStyleSheet(QSS)
        self.provider = provider
        self.dynamic = dynamic
        self.caption_text = caption
        self.recents: list[str] = list(recents or [])
        self.commands: list[Command] = []
        self.shown: list[Command] = []
        self.on_ran: Callable[[list[str]], None] | None = None

        self.caption = QtWidgets.QLabel("")
        self.caption.setObjectName("PaletteCaption")
        self.caption.setFont(style.ui_font(11))
        star = QtWidgets.QLabel("✱")
        star.setObjectName("PaletteStar")
        star.setFont(style.ui_font(15))
        self.query = QtWidgets.QLineEdit()
        self.query.setObjectName("PaletteQuery")
        self.query.setFont(style.ui_font(14))
        self.query.setPlaceholderText("")
        self.query.textChanged.connect(self._filter)
        self.query.installEventFilter(self)
        line = QtWidgets.QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        line.addWidget(star)
        line.addWidget(self.query)

        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("PaletteList")
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda _item: self._run_current())
        self.list.setItemDelegate(_Row(self.list))

        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(1, 1, 1, 1)
        column.setSpacing(0)
        column.addWidget(self.caption)
        column.addLayout(line)
        column.addWidget(_Rule())
        column.addWidget(self.list)
        self.setFixedWidth(WIDTH)

    # -- showing -----------------------------------------------------------
    def popup(self, global_pos: QtCore.QPoint, text: str = ""):
        self.commands = self.provider()
        self.caption.setText(self.caption_text() if self.caption_text else "")
        self.query.blockSignals(True)
        self.query.setText(text)
        self.query.blockSignals(False)
        self._filter(text)
        screen = QtWidgets.QApplication.screenAt(global_pos) or QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = global_pos.x() - 30
        y = global_pos.y() - self.caption.sizeHint().height() - 18
        x = max(area.left() + 4, min(area.right() - self.width() - 4, x))
        y = max(area.top() + 4, min(area.bottom() - self.height() - 4, y))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.query.setFocus(QtCore.Qt.PopupFocusReason)

    def _filter(self, text: str):
        text = text if isinstance(text, str) else self.query.text()
        extra = self.dynamic(text) if (self.dynamic and text.strip()) else []
        if text.strip():
            ranked = [(s, i, c) for i, c in enumerate(self.commands)
                      for s in [score(text, c)] if s is not None]
            ranked.sort(key=lambda entry: (-entry[0], entry[1]))
            self.shown = extra + [c for _s, _i, c in ranked]
        else:
            order = {key: n for n, key in enumerate(self.recents)}
            recent = sorted((c for c in self.commands if c.key in order),
                            key=lambda c: order[c.key])
            rest = [c for c in self.commands if c.key not in order]
            self.shown = recent + rest
        self.list.clear()
        for command in self.shown:
            item = QtWidgets.QListWidgetItem(command.title)
            item.setData(_HINT, command.hint or "")
            self.list.addItem(item)
        if self.shown:
            self.list.setCurrentRow(0)
        rows = max(1, min(MAX_ROWS, len(self.shown)))
        self.list.setFixedHeight(rows * 24 + 10)
        self.adjustSize()

    # -- keys --------------------------------------------------------------
    def eventFilter(self, watched, event):
        if watched is self.query and event.type() == QtCore.QEvent.KeyPress:
            key = event.key()
            if key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Tab):
                self._step(1)
                return True
            if key in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Backtab):
                self._step(-1)
                return True
            if key == QtCore.Qt.Key_PageDown:
                self._step(MAX_ROWS)
                return True
            if key == QtCore.Qt.Key_PageUp:
                self._step(-MAX_ROWS)
                return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._run_current()
                return True
            if key == QtCore.Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(watched, event)

    def _step(self, delta: int):
        if not self.shown:
            return
        self.list.setCurrentRow((self.list.currentRow() + delta) % len(self.shown))

    def _run_current(self):
        row = self.list.currentRow()
        if not (0 <= row < len(self.shown)):
            return
        command = self.shown[row]
        if command.fill:
            self.query.setText(command.fill)
            return
        self.hide()
        self.recents = [command.key] + [k for k in self.recents if k != command.key]
        del self.recents[RECENT_KEEP:]
        if self.on_ran:
            self.on_ran(self.recents)
        if command.run:
            # after the popup has gone, so a dialog it opens gets focus
            QtCore.QTimer.singleShot(0, command.run)
