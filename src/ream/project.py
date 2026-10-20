"""
Files: reading images and PDFs in, and the .ream project.

A .ream file is a zip: `ream.json` (the words, the page format, the distress
settings, the view, and where every thing sits) plus `media/`, each image or
PDF stored once under the hash of its bytes, exactly as it came in.  The
words are kept as plain text, one line per paragraph, with a form feed (\\f)
opening any paragraph that starts a new page.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile

import numpy as np
from PyQt5 import QtCore, QtGui

FORMAT = 1
SUFFIX = ".ream"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic"}
PDF_DPI = 200


def media_name(blob: bytes, ext: str) -> str:
    return f"media/{hashlib.sha1(blob).hexdigest()[:20]}{ext.lower()}"


def image_from_bytes(blob: bytes) -> QtGui.QImage | None:
    """Decode an image, phone photos turned the right way up."""
    data = QtCore.QByteArray(blob)
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.ReadOnly)
    reader = QtGui.QImageReader(buffer)
    reader.setAutoTransform(True)
    image = reader.read()
    return None if image.isNull() else image


def pdf_count(blob: bytes) -> int:
    import pypdfium2
    return len(pypdfium2.PdfDocument(blob))


def pdf_page(blob: bytes, index: int, dpi: float = PDF_DPI) -> tuple[QtGui.QImage, QtCore.QSizeF]:
    """One page on white paper, and its size in points."""
    import pypdfium2
    document = pypdfium2.PdfDocument(blob)
    page = document[index]
    w, h = page.get_size()
    scale = min(dpi / 72.0, 6000.0 / max(1.0, w, h))
    bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255), rev_byteorder=True)
    pixels = np.ascontiguousarray(bitmap.to_numpy())
    page.close()
    document.close()
    if pixels.ndim == 2:
        pixels = np.repeat(pixels[..., None], 3, axis=2)
    ph, pw = pixels.shape[:2]
    if pixels.shape[2] == 4:
        image = QtGui.QImage(pixels.data, pw, ph, 4 * pw, QtGui.QImage.Format_RGBA8888).copy()
    else:
        image = QtGui.QImage(pixels.data, pw, ph, 3 * pw, QtGui.QImage.Format_RGB888).copy()
    return image, QtCore.QSizeF(w, h)


# -- the words ---------------------------------------------------------------

def doc_to_text(doc: QtGui.QTextDocument) -> str:
    lines = []
    block = doc.begin()
    while block.isValid():
        breaks = block.blockFormat().pageBreakPolicy() & QtGui.QTextFormat.PageBreak_AlwaysBefore
        lines.append(("\f" if breaks else "") + block.text())
        block = block.next()
    return "\n".join(lines)


def text_to_doc(doc: QtGui.QTextDocument, text: str, block_format: QtGui.QTextBlockFormat):
    """Fill `doc` from plain text, outside the undo history."""
    doc.setUndoRedoEnabled(False)
    doc.clear()
    cursor = QtGui.QTextCursor(doc)
    for n, line in enumerate(text.split("\n")):
        fmt = QtGui.QTextBlockFormat(block_format)
        if line.startswith("\f"):
            fmt.setPageBreakPolicy(QtGui.QTextFormat.PageBreak_AlwaysBefore)
            line = line[1:]
        if n:
            cursor.insertBlock(fmt)
        else:
            cursor.setBlockFormat(fmt)
        cursor.insertText(line)
    doc.setUndoRedoEnabled(True)
    doc.setModified(False)


# -- the project file ---------------------------------------------------------

def save(path: str, state: dict, media: dict[str, bytes]):
    """Write atomically: a crash mid-save never eats the last good file.
    Media go in as they are - images and PDFs are compressed already, and
    squeezing a big PDF again on every autosave cost seconds for nothing."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    temp = path + ".saving"
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ream.json", json.dumps({"format": FORMAT, **state}, indent=1))
        for name, blob in media.items():
            archive.writestr(name, blob, compress_type=zipfile.ZIP_STORED)
    os.replace(temp, path)


def load(path: str) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        state = json.loads(archive.read("ream.json"))
        media = {name: archive.read(name) for name in archive.namelist()
                 if name.startswith("media/")}
    return state, media


def png_bytes(plane) -> bytes:
    """A (h, w) uint8 mask as PNG bytes."""
    import cv2
    ok, data = cv2.imencode(".png", np.ascontiguousarray(plane))
    return bytes(data) if ok else b""


def png_plane(data: bytes):
    """PNG bytes back to a (h, w) uint8 mask, or None."""
    import cv2
    if not data:
        return None
    plane = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    return plane


def png_bytes_rgba(bgra) -> bytes:
    """(h, w, 4) BGRA pixels as PNG bytes."""
    import cv2
    ok, data = cv2.imencode(".png", np.ascontiguousarray(bgra))
    return bytes(data) if ok else b""
