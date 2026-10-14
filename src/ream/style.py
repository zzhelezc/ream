"""
The look: one ink, one paper, one monospace face - after typewritten
manifestos photocopied for a mailing list.

Nothing here is chrome.  The canvas is a flat field, the page is a white
sheet with a hairline edge, and the only text outside the page is small grey
metadata, set like the caption under a pinned image.
"""
from __future__ import annotations

from PyQt5 import QtGui

INK = "#141414"            # the interface
PAGE_INK = "#000000"       # the words on the page, at 100%

# canvas colour, page edge (None = no edge), dotted edge, metadata grey
THEMES = {
    "paper": {"canvas": "#e8e7e3", "edge": "#1a1a1a", "dotted": False, "meta": "#8c8b86"},
    "white": {"canvas": "#ffffff", "edge": "#1a1a1a", "dotted": True, "meta": "#9b9b9b"},
    "night": {"canvas": "#161616", "edge": None, "dotted": False, "meta": "#77766f"},
}
DEFAULT_THEME = "paper"

PAPERS = {
    "white": "#ffffff",
    "cream": "#f4efe2",
    "newsprint": "#e8e5da",
    "bond": "#f7f6f1",
}

# in points
PAGE_SIZES = {
    "a4": (595.276, 841.890),
    "letter": (612.0, 792.0),
    "a5": (419.528, 595.276),
    "square": (595.276, 595.276),
}

# the first one installed is the default face
MONO = ["IBM Plex Mono", "Iosevka", "Iosevka Term", "Iosevka Slab", "Iosevka Term Slab",
        "Iosevka Aile", "Iosevka Etoile", "JetBrains Mono", "Roboto Mono", "Space Mono",
        "Departure Mono", "SF Mono", "Menlo", "Courier New", "Courier"]

_families: set[str] | None = None


def installed(family: str) -> bool:
    global _families
    if _families is None:
        _families = set(QtGui.QFontDatabase().families())
    return family in _families


def faces() -> list[str]:
    return [f for f in MONO if installed(f)] or ["Courier"]


def default_face() -> str:
    return faces()[0]


def ui_font(px: float, bold: bool = False) -> QtGui.QFont:
    font = QtGui.QFont(default_face())
    font.setPixelSize(max(1, int(round(px))))
    font.setBold(bold)
    font.setStyleHint(QtGui.QFont.Monospace)
    return font


def qc(value: str, alpha: int | None = None) -> QtGui.QColor:
    colour = QtGui.QColor(value)
    if alpha is not None:
        colour.setAlpha(alpha)
    return colour
