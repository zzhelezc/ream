"""
Wear: torn edges for images, and stamps - stains, splatter, tape, dust,
folds - to put on the page.  Pure numpy / OpenCV; the wear plugin is the UI.

**Torn edges** are a property of an image (Thing.tear), applied when its
pixels are put together, like its masks and border - so they never touch the
original, change live and undo.  A tear is

    {"sides": "all" | "top" | "bottom" | "left" | "right" | "top+bottom" | "left+right",
     "depth": pt, "rough": 0..1, "rim": pt, "colour": "#rrggbb" | "",
     "seed": int, "matte": path | ""}

Drawn tears (no matte) cut each chosen side along a fractal profile, with
fibres at the pixel scale, sized in points so they look the same at any
resolution.  A matte - a black-and-white torn shape, white kept, such as
Texturelabs' torn mattes - is stretched over the image instead.  Either way
a band along the torn edge shows the paper's core (`colour`, `rim` wide,
of uneven width): the white fibrous edge of torn printed paper, or a burnt
brown one.

**Stamps** come from your stamps folder (`~/Library/Application
Support/ream/stamps/`, or `$REAM_HOME/stamps`): any image, in subfolders as
categories, named by an optional `index.json` there:

    {"tape/Texturelabs_Details_122M.png": {"label": "Masking tape", "split": 8}}

`split` cuts a sheet of pieces (strips of tape, document marks) into one
stamp per piece, joining parts closer than that many pixels; `tint` gives a
default colour; `detail` keys a whole-frame overlay (dust, folds) against
its own local lightness, so the photo's uneven light drops away.  ream ships no textures - like the paper stock, they are
yours (from Texturelabs, say: free to use, not to pass on).

A texture becomes a stamp as RGBA: one with transparency is used as it is;
an opaque one (marks photographed on white, or on black) is keyed from its
lightness - its marks become the alpha, in the stamp's colour - so stamps
lay over the page like ink, in PDFs too (which have no blend modes).

ream also draws a few stamps itself, needing no textures: coffee ring, ink
blot, specks, crease (see DRAWN).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np

SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
SIDES = ("all", "top", "bottom", "left", "right", "top+bottom", "left+right")
TINTS = {"as is": "", "ink": "#1a1917", "brown": "#6b4a2b", "rust": "#8a3b1e",
         "blue": "#23356e", "red": "#a3201b", "paper": "#f4f1ea"}
RIMS = {"paper": "#f6f3ec", "cream": "#ece2c6", "burnt": "#3b2414", "none": ""}
DEFAULT_TEAR = {"sides": "all", "depth": 9.0, "rough": 0.55, "rim": 2.2, "colour": RIMS["paper"],
                "seed": 1, "matte": ""}
DRAWN = ("coffee ring", "ink blot", "specks", "crease")
STAMP_PX = 1400                 # drawn stamps are made this big (long side)


def folder() -> Path:
    base = os.environ.get("REAM_HOME") or os.path.expanduser("~/Library/Application Support/ream")
    return Path(base) / "stamps"


def cache_folder() -> Path:
    base = os.environ.get("REAM_CACHE") or os.path.expanduser("~/Library/Caches/ream")
    return Path(base) / "stamps"


# -- torn edges ----------------------------------------------------------------------

def _profile(n: int, length_pt: float, rough: float, rng: np.random.Generator) -> np.ndarray:
    """A torn edge's line, 0..1, n samples long: big slow wanders, smaller
    bites, and fibres at the finest scale (more of them the rougher)."""
    out = np.zeros(n, np.float32)
    total, amp = 0.0, 1.0
    wavelength = 90.0                                   # pt, the biggest wander
    for _octave in range(7):
        k = max(2, int(length_pt / wavelength) + 2)
        points = rng.random(k + 1).astype(np.float32)
        out += amp * np.interp(np.linspace(0, k, n), np.arange(k + 1), points)
        total += amp
        amp *= 0.30 + 0.45 * rough
        wavelength /= 2.1
    out /= total
    out += (rng.random(n).astype(np.float32) - 0.5) * (0.06 + 0.22 * rough)   # fibres
    lo, hi = float(out.min()), float(out.max())
    return (out - lo) / max(1e-6, hi - lo)


def _sides(sides: str) -> set[str]:
    if sides == "all":
        return {"top", "bottom", "left", "right"}
    return set(sides.split("+")) & {"top", "bottom", "left", "right"}


def tear_keep(h: int, w: int, tear: dict, px_per_pt: float) -> np.ndarray:
    """What a tear keeps of an h x w image: float32 0..1."""
    matte = tear.get("matte") or ""
    if matte:
        grey = cv2.imread(matte, cv2.IMREAD_GRAYSCALE)
        if grey is not None:
            keep = cv2.resize(grey, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
            return np.clip((keep - 0.35) / 0.3, 0.0, 1.0)
    rng = np.random.default_rng(int(tear.get("seed", 1)))
    depth = max(0.5, float(tear.get("depth", 9.0)) * px_per_pt)
    rough = float(tear.get("rough", 0.55))
    keep = np.ones((h, w), np.float32)
    chosen = _sides(tear.get("sides", "all"))
    # each side only touches a strip as deep as its tear: the rest stays whole
    band = min(max(h, w), int(np.ceil(depth)) + 2)
    for side in ("top", "bottom", "left", "right"):
        if side not in chosen:
            rng.random(8)                               # same tear on the other sides either way
            continue
        n = w if side in ("top", "bottom") else h
        edge = depth * (0.15 + 0.85 * _profile(n, n / px_per_pt, rough, rng))
        if side in ("top", "bottom"):
            k = min(h, band)
            ys = np.arange(k, dtype=np.float32)[:, None]
            cut = np.clip(ys - edge[None, :] + 0.5, 0.0, 1.0)          # rows counted from the edge
            strip = keep[:k] if side == "top" else keep[h - k:][::-1]
        else:
            k = min(w, band)
            xs = np.arange(k, dtype=np.float32)[None, :]
            cut = np.clip(xs - edge[:, None] + 0.5, 0.0, 1.0)
            strip = keep[:, :k] if side == "left" else keep[:, w - k:][:, ::-1]
        np.minimum(strip, cut, out=strip)
    return keep


def tear_rim(keep: np.ndarray, tear: dict, px_per_pt: float) -> np.ndarray:
    """The band of paper core along the torn edge: float32 0..1."""
    rim = float(tear.get("rim", 0.0)) * px_per_pt
    if rim <= 0.25 or not tear.get("colour"):
        return np.zeros_like(keep)
    inside = (keep > 0.5).astype(np.uint8)
    # distance to the torn edge only - not to the image's own edges
    padded = cv2.copyMakeBorder(inside, 1, 1, 1, 1, cv2.BORDER_REPLICATE)
    dist = cv2.distanceTransform(padded, cv2.DIST_L2, 3)[1:-1, 1:-1]
    rng = np.random.default_rng(int(tear.get("seed", 1)) + 7)
    h, w = keep.shape
    small = rng.random((max(2, h // 24), max(2, w // 24))).astype(np.float32)
    fibres = rng.random((h, w))
    band = np.zeros((h, w), np.float32)
    # only pixels near the cut can be in the band: work out just those
    near = np.nonzero((dist < rim * 1.6 + 2.0) & (keep > 0.01))
    if len(near[0]):
        wide = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)[near]
        width = rim * (0.35 + 1.1 * wide)
        fibre = 0.75 + 0.25 * fibres[near].astype(np.float32)
        band[near] = np.clip((width - dist[near]) / 1.5, 0.0, 1.0) * fibre
    return band


def apply_tear(bgra: np.ndarray, tear: dict, px_per_pt: float) -> np.ndarray:
    """An image's pixels with its tear: cut, and the rim laid along the cut."""
    h, w = bgra.shape[:2]
    keep = tear_keep(h, w, tear, px_per_pt)
    out = bgra.copy()
    cut = np.nonzero(keep < 1.0)                         # just the torn strips change
    out[..., 3][cut] = (out[..., 3][cut].astype(np.float32) * keep[cut] + 0.5).astype(np.uint8)
    band = tear_rim(keep, tear, px_per_pt)
    rim = np.nonzero(band)
    if len(rim[0]):
        colour = tear["colour"].lstrip("#")
        bgr = np.array([int(colour[4:6], 16), int(colour[2:4], 16), int(colour[0:2], 16)], np.float32)
        b = band[rim][:, None]
        pixels = out[rim]
        pixels[:, :3] = (pixels[:, :3].astype(np.float32) * (1.0 - b) + bgr * b + 0.5).astype(np.uint8)
        # the core shows even where the picture itself was clear
        pixels[:, 3] = np.maximum(pixels[:, 3], (band[rim] * keep[rim] * 255).astype(np.uint8))
        out[rim] = pixels
    return out


# -- the stamps folder ------------------------------------------------------------------

def index() -> dict:
    try:
        data = json.loads((folder() / "index.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def library() -> list[dict]:
    """Every texture in the stamps folder: {path, key, label, category,
    split, tint, matte}, by category then label.  `matte` marks torn mattes
    (the "torn mattes" folder), which tear images rather than stamp."""
    where = folder()
    if not where.is_dir():
        return []
    names = index()
    found = []
    for path in sorted(where.rglob("*")):
        if path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        key = path.relative_to(where).as_posix()
        info = names.get(key, {})
        if isinstance(info, str):
            info = {"label": info}
        category = path.parent.name if path.parent != where else "stamps"
        found.append({"path": str(path), "key": key, "category": category,
                      "label": info.get("label") or path.stem.replace("_", " "),
                      "split": info.get("split"), "tint": info.get("tint", ""),
                      "detail": bool(info.get("detail")),
                      "matte": category == "torn mattes"})
    found.sort(key=lambda e: (e["category"], e["label"].lower()))
    return found


def categories(entries: list[dict] | None = None) -> list[str]:
    entries = library() if entries is None else entries
    seen = []
    for e in entries:
        if not e["matte"] and e["category"] not in seen:
            seen.append(e["category"])
    return ["drawn"] + seen


# -- making stamps ---------------------------------------------------------------------

def key_alpha(bgr: np.ndarray) -> tuple[np.ndarray, bool]:
    """An opaque photo of marks as alpha: (alpha float32 0..1, dark marks?).
    Marks on a light ground are where it is darker; on a dark ground, lighter."""
    lum = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    dark_marks = float(np.median(lum)) > 0.5
    if dark_marks:
        ground, mark = np.percentile(lum, 85), np.percentile(lum, 0.5)
        alpha = (ground - lum) / max(0.04, ground - mark)
    else:
        ground, mark = np.percentile(lum, 15), np.percentile(lum, 99.5)
        alpha = (lum - ground) / max(0.04, mark - ground)
    return np.clip(alpha, 0.0, 1.0), dark_marks


def key_detail(bgr: np.ndarray) -> np.ndarray:
    """A whole-frame overlay (dust, scratches, folds) keyed against its own
    surroundings: only marks that stand out from the local lightness count,
    so uneven light, glow and vignetting in the photo drop away.  Darker
    marks on a light ground, lighter ones (dust) on a dark ground."""
    lum = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    sigma = max(4.0, max(lum.shape) * 0.012)
    local = cv2.GaussianBlur(lum, (0, 0), sigma)
    detail = (local - lum) if float(np.median(lum)) > 0.5 else (lum - local)
    detail = np.maximum(detail, 0.0)
    top = float(np.percentile(detail, 99.7))
    level = np.clip(detail / max(0.02, top), 0.0, 1.0)
    return np.clip((level - 0.16) / 0.84, 0.0, 1.0) ** 1.1     # the paper's own grain drops out


def as_rgba(path: str, detail: bool = False) -> np.ndarray | None:
    """A texture as BGRA uint8: its own transparency, or keyed from lightness
    (`detail`: against its local lightness, for whole-frame overlays)."""
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4 and int(image[..., 3].min()) < 250:
        return image
    bgr = image[..., :3]
    if detail:
        out = np.empty(bgr.shape[:2] + (4,), np.uint8)
        out[..., :3] = 26
        out[..., 3] = (key_detail(bgr) * 255 + 0.5).astype(np.uint8)
        return out
    alpha, dark = key_alpha(bgr)
    out = np.empty(bgr.shape[:2] + (4,), np.uint8)
    # keep the photo's own colour for dark marks (a stain stays brown);
    # light marks on black are drawn in ink until tinted
    out[..., :3] = bgr if dark else 26
    if dark:
        # deepen so the keyed edges don't go grey: colour of the mark at full strength
        out[..., :3] = np.clip(bgr.astype(np.float32) * 0.85, 0, 255).astype(np.uint8)
    out[..., 3] = (alpha * 255 + 0.5).astype(np.uint8)
    return out


def split_pieces(bgra: np.ndarray, join_px: int, min_area: float = 0.002) -> list[np.ndarray]:
    """A sheet of pieces as one stamp per piece, each cropped to itself.
    Parts closer than join_px (letters of a word) stay one piece."""
    alpha = bgra[..., 3]
    solid = (alpha > 24).astype(np.uint8)
    if join_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * join_px + 1, 2 * join_px + 1))
        solid = cv2.dilate(solid, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, 8)
    h, w = alpha.shape
    pieces = []
    for n in range(1, count):
        x, y, cw, ch, area = stats[n]
        if area < min_area * h * w:
            continue
        piece = bgra[y:y + ch, x:x + cw].copy()
        piece[..., 3] = np.where(labels[y:y + ch, x:x + cw] == n, piece[..., 3], 0)
        pieces.append(piece)
    pieces.sort(key=lambda p: -p.shape[0] * p.shape[1])
    return pieces or [bgra]


def crop_to_ink(bgra: np.ndarray, pad: int = 4) -> np.ndarray:
    ys, xs = np.nonzero(bgra[..., 3] > 8)
    if len(ys) == 0:
        return bgra
    y0, y1 = max(0, ys.min() - pad), min(bgra.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(bgra.shape[1], xs.max() + pad + 1)
    return bgra[y0:y1, x0:x1]


def stamp_variants(entry: dict) -> list[np.ndarray]:
    """A library entry as its stamps (several for a split sheet), BGRA,
    cached on disk so a sheet is only cut up once."""
    path = entry["path"]
    try:
        stat = os.stat(path)
    except OSError:
        return []
    tag = hashlib.sha1(f"{path}|{stat.st_size}|{stat.st_mtime}|{entry.get('split')}|"
                       f"{entry.get('detail')}|v4"
                       .encode()).hexdigest()[:16]
    cache = cache_folder() / tag
    if cache.is_dir():
        found = sorted(cache.glob("*.png"))
        if found:
            out = [cv2.imread(str(p), cv2.IMREAD_UNCHANGED) for p in found]
            return [o for o in out if o is not None]
    rgba = as_rgba(path, bool(entry.get("detail")))
    if rgba is None:
        return []
    split = entry.get("split")
    variants = split_pieces(rgba, int(split)) if split else [crop_to_ink(rgba)]
    try:
        cache.mkdir(parents=True, exist_ok=True)
        for n, piece in enumerate(variants):
            cv2.imwrite(str(cache / f"{n:03d}.png"), piece)
    except OSError:
        pass
    return variants


def finish(bgra: np.ndarray, tint: str = "", strength: float = 1.0) -> np.ndarray:
    """A stamp ready to place: recoloured to `tint` (keeping its own light
    and shade) and at `strength` opacity."""
    out = bgra.copy()
    if tint:
        t = tint.lstrip("#")
        colour = np.array([int(t[4:6], 16), int(t[2:4], 16), int(t[0:2], 16)], np.float32)
        lum = cv2.cvtColor(bgra[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        shade = 0.75 + 0.5 * (lum - float(np.median(lum[bgra[..., 3] > 32])) if (bgra[..., 3] > 32).any()
                              else lum - 0.5)
        out[..., :3] = np.clip(colour * np.clip(shade, 0.4, 1.3)[..., None], 0, 255).astype(np.uint8)
    if strength < 0.999:
        out[..., 3] = (out[..., 3].astype(np.float32) * max(0.0, strength) + 0.5).astype(np.uint8)
    return out


# -- stamps ream draws itself --------------------------------------------------------------

def _noise(h: int, w: int, rng: np.random.Generator, cell: int) -> np.ndarray:
    small = rng.random((max(2, h // cell), max(2, w // cell))).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def drawn(kind: str, seed: int = 0, px: int = STAMP_PX) -> np.ndarray:
    """One of DRAWN as BGRA uint8, `px` on its long side."""
    rng = np.random.default_rng(seed)
    if kind == "coffee ring":
        n = px
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        c = n / 2
        angle = np.arctan2(yy - c, xx - c)
        wobble = 1.0 + 0.035 * np.sin(angle * 3 + rng.random() * 6) + 0.02 * np.sin(angle * 7 + rng.random() * 6)
        r = np.hypot(yy - c, xx - c) / (n * 0.40 * wobble)
        ring = np.exp(-((r - 1.0) / 0.018) ** 2) * 0.9 + np.exp(-((r - 0.985) / 0.05) ** 2) * 0.35
        fill = np.clip(1.0 - r, 0, 1) ** 0.4 * 0.035 * (r < 1)     # faint: it lies over words
        gap = 0.55 + 0.45 * np.clip(np.cos(angle - rng.random() * 6.28) * 1.4 + 0.6, 0, 1)
        alpha = np.clip((ring * gap + fill) * (0.75 + 0.5 * _noise(n, n, rng, 18)), 0, 1)
        colour = (30, 56, 86)                          # BGR, coffee brown
    elif kind == "ink blot":
        n = px
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        c = n / 2
        angle = np.arctan2(yy - c, xx - c)
        edge = 0.24 + 0.05 * _noise(1, 720, rng, 40)[0][((angle + np.pi) / (2 * np.pi) * 719).astype(int)]
        r = np.hypot(yy - c, xx - c) / n
        alpha = np.clip((edge - r) * 220, 0, 1)
        for _ in range(int(40 + rng.random() * 30)):       # splatter round it
            a, d = rng.random() * 6.283, 0.26 + rng.random() * 0.2
            sr = 0.004 + rng.random() ** 3 * 0.03
            cy, cx = c + np.sin(a) * d * n, c + np.cos(a) * d * n
            alpha = np.maximum(alpha, np.clip((sr * n - np.hypot(yy - cy, xx - cx)) * 0.8, 0, 1))
        colour = (24, 22, 20)
    elif kind == "specks":
        n = px
        alpha = np.zeros((n, n), np.float32)
        for _ in range(int(160 + rng.random() * 120)):
            cy, cx = rng.random(2) * n
            radius = max(1.0, (rng.random() ** 4) * n * 0.012)
            cv2.circle(alpha, (int(cx), int(cy)), int(radius), float(0.4 + 0.6 * rng.random()), -1,
                       cv2.LINE_AA)
        alpha = cv2.GaussianBlur(alpha, (0, 0), 0.8)
        colour = (30, 28, 26)
    elif kind == "crease":
        w, h = px, max(24, px // 10)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        line = h / 2 + (_noise(1, w, rng, 60)[0] - 0.5) * h * 0.25
        d = yy - line[None, :]
        alpha = np.exp(-(d / (h * 0.035)) ** 2) * 0.55 + np.clip(-d / (h * 0.5), 0, 1) * 0.10
        alpha *= np.clip(np.minimum(xx, w - xx) / (w * 0.08), 0, 1)      # fades at the ends
        alpha *= 0.7 + 0.3 * _noise(h, w, rng, 12)
        colour = (40, 38, 36)
    else:
        raise ValueError(f"unknown drawn stamp: {kind}")
    out = np.empty(alpha.shape + (4,), np.uint8)
    out[..., :3] = colour
    out[..., 3] = (np.clip(alpha, 0, 1) * 255 + 0.5).astype(np.uint8)
    return crop_to_ink(out)
