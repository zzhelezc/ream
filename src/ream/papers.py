"""
Paper stock: photographed paper textures laid under the page.

ream ships no textures.  It uses whatever images are in your papers folder
(`~/Library/Application Support/ream/papers/`, or `$REAM_HOME/papers`), for
instance ones downloaded from Texturelabs for your own use.  An optional
`index.json` there names them: {"Texturelabs_Paper_237L.jpg": "Bright clean
cold press", ...}; otherwise the file name is the name.

Only the paper's *tooth* is used, never its photographed colour or light:

1. the image becomes luminance;
2. a wide blur of it is subtracted (a high-pass), which removes the uneven
   lighting and vignetting of the photograph and keeps fibres, grain and
   tooth;
3. the rest is standardised (mean 0, deviation 1) - the "detail map".

The page is then the chosen paper colour times (1 + grain × detail): the
stock stays your colour and evenly lit, and only its surface comes through.

The detail map is turned to the page's orientation and scaled to cover the
page (cropped in the middle), so the same spot of the page always gets the
same spot of the paper - at any dpi, in any crop.  That keeps the screen,
the distress preview and the exports in register.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import numpy as np

SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
GRAIN_GAIN = 0.11          # at grain 100, one deviation of tooth is ±11% of the colour
DETAIL_MAX = 3600          # px, the long side the detail map is kept at

_detail: dict[str, np.ndarray] = {}
_surfaces: dict[tuple, np.ndarray] = {}     # whole-page maps, so a grain slider is quick
_lock = threading.Lock()


def folder() -> Path:
    base = os.environ.get("REAM_HOME") or os.path.expanduser("~/Library/Application Support/ream")
    return Path(base) / "papers"


def available() -> list[tuple[str, str]]:
    """(file name, label) for every paper in the folder, sorted by label."""
    where = folder()
    if not where.is_dir():
        return []
    try:
        names = json.loads((where / "index.json").read_text())
    except (OSError, ValueError):
        names = {}
    found = []
    for path in where.iterdir():
        if path.suffix.lower() in SUFFIXES and path.is_file():
            label = names.get(path.name) or path.stem.replace("_", " ")
            found.append((path.name, label))
    return sorted(found, key=lambda entry: entry[1].lower())


def label(key: str) -> str:
    return dict(available()).get(key, key)


def detail(key: str) -> np.ndarray | None:
    """The paper's tooth as float32, mean 0, deviation 1 (see above)."""
    with _lock:
        if key in _detail:
            return _detail[key]
        import cv2
        path = folder() / key
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path.is_file() else None
        if image is None:
            return None
        h, w = image.shape
        k = min(1.0, DETAIL_MAX / max(h, w))
        if k < 1.0:
            image = cv2.resize(image, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        lum = image.astype(np.float32)
        light = cv2.GaussianBlur(lum, (0, 0), max(lum.shape) / 40.0)
        tooth = lum - light
        tooth = (tooth - float(tooth.mean())) / max(1e-3, float(tooth.std()))
        _detail[key] = np.clip(tooth, -4.0, 4.0).astype(np.float32)
        return _detail[key]


def surface(key: str, page_w: float, page_h: float, dpi: float,
            box: tuple[int, int, int, int] | None) -> np.ndarray | None:
    """The tooth laid over the page (or `box` of it) at `dpi`: float32."""
    import cv2
    whole = box is None
    cache_key = (key, round(page_w, 2), round(page_h, 2), round(dpi, 2))
    if whole and cache_key in _surfaces:
        return _surfaces[cache_key]
    tooth = detail(key)
    if tooth is None:
        return None
    portrait = page_h >= page_w
    if (tooth.shape[0] >= tooth.shape[1]) != portrait:
        tooth = np.ascontiguousarray(np.rot90(tooth))
    th, tw = tooth.shape
    full_w, full_h = page_w * dpi / 72.0, page_h * dpi / 72.0
    scale = max(full_w / tw, full_h / th)               # cover the page
    ox = (tw * scale - full_w) / 2.0                    # crop in the middle
    oy = (th * scale - full_h) / 2.0
    x0, y0, w, h = box if box else (0, 0, int(round(full_w)), int(round(full_h)))
    # output (x, y) <- source ((x + x0 + ox) / scale, (y + y0 + oy) / scale)
    matrix = np.array([[scale, 0.0, -(x0 + ox)], [0.0, scale, -(y0 + oy)]], np.float32)
    flags = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    laid = cv2.warpAffine(tooth, matrix, (w, h), flags=flags, borderMode=cv2.BORDER_REFLECT)
    if whole:
        if len(_surfaces) > 6:
            _surfaces.clear()
        _surfaces[cache_key] = laid
    return laid


def sheet(key: str, page_w: float, page_h: float, dpi: float,
          box: tuple[int, int, int, int] | None, colour: tuple[int, int, int],
          grain: float) -> np.ndarray | None:
    """The page's paper - or the `box` (x, y, w, h in px at `dpi`) of it - as
    (h, w, 3) uint8 RGB.  None when the texture is missing."""
    laid = surface(key, page_w, page_h, dpi, box)
    if laid is None:
        return None
    h, w = laid.shape
    factor = 1.0 + (grain / 100.0) * GRAIN_GAIN * laid
    out = np.empty((h, w, 3), np.float32)
    out[...] = colour
    out *= factor[..., None]
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
