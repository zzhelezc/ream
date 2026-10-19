"""
Background removal, and the other pixel maths behind the cutouts.

(From stik, unchanged in its workings: ream's image editing uses the same
methods, so a cutout made here behaves as it does there.)

Nothing here knows about Qt.  Images arrive as (h, w, 4) uint8 BGRA - the byte
order QImage's ARGB32 and OpenCV both use - with a separate (h, w) uint8 mask,
and every function hands back a new mask rather than touching its input, so the
caller decides what is undoable.

The heuristics, cheapest first:

    flood     the colour(s) touching the cutout's edge, removed only where they
              connect back to that edge.  An enclosed patch of the same colour
              (the eye of a white cat on white paper) survives.
    gradient  a flood that compares each pixel with its neighbour instead of
              with the edge colour, so it follows a smooth gradient, vignette
              or uneven lighting all the way in - and stops at a crisp edge.
    key       one colour removed everywhere, connected or not - picked by hand,
              or the edge's most common colour.  Reaches the inside of an O.
    white /   key with the key fixed to paper white / black: scans, screenshots
    black     and line art.
    grabcut   graph-cut segmentation.  Colour models are learned from the edge
              (background) and the middle (foreground), then refined; good on
              busy or gradient backgrounds where no single colour is "the
              background".  Too slow to preview live.
    ai        rembg's neural matting, when it is installed.

Colour distances are measured in CIE Lab, so the tolerance reads roughly as
"how different does it look" (delta E) rather than raw channel values.

Every method feeds the same refinement: keep only the largest piece, remove
specks, fill holes, grow or shrink the edge, feather it.
"""
from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass

import cv2
import numpy as np

FLOOD, GRADIENT, KEY, WHITE, BLACK, GRABCUT, AI = (
    "flood", "gradient", "key", "white", "black", "grabcut", "ai")

METHODS = (
    (FLOOD, "Border flood",
     "Removes the colours touching the cutout's edge, but only where they connect "
     "back to the edge - an enclosed patch of the same colour survives."),
    (GRADIENT, "Gradient flood",
     "Floods in from the edge comparing each pixel with its neighbour, so it follows "
     "gradients, vignettes and uneven light, and stops at a crisp edge.  Soft or "
     "blurry edges can leak - lower the tolerance."),
    (KEY, "Colour key",
     "Removes one colour everywhere, connected or not: the picked key, or the "
     "edge's most common colour.  Reaches enclosed holes the flood cannot."),
    (WHITE, "Drop white",
     "Colour key fixed to white - scans, screenshots and line art on paper."),
    (BLACK, "Drop black",
     "Colour key fixed to black."),
    (GRABCUT, "GrabCut",
     "Graph-cut segmentation: learns what the edge (background) and the middle "
     "(foreground) look like and splits between them.  Best on busy or gradient "
     "backgrounds.  Slower, so it runs on APPLY rather than live."),
    (AI, "AI model (rembg)",
     "rembg's neural network finds the subject.  Needs `uv tool install "
     "'ream[ai]'`; the first run downloads its model."),
)
METHOD_LABELS = {key: label for key, label, _tip in METHODS}
LIVE_METHODS = {FLOOD, GRADIENT, KEY, WHITE, BLACK}      # fast enough to preview per slider tick

VISIBLE = 8                    # alpha below this counts as already transparent
GRABCUT_PIXELS = 900_000       # grabcut runs on a copy scaled down to about this


@dataclass(frozen=True)
class Params:
    method: str = FLOOD
    tolerance: float = 18.0            # delta E below which a pixel is background
    softness: float = 8.0              # delta E ramp above it: a soft edge
    key_color: tuple | None = None     # (r, g, b); None = the edge's own colour
    grow: int = 0                      # px; negative shrinks (eats halos)
    feather: float = 0.0               # px of blur on the final edge
    despeckle: int = 0                 # specks and pinholes smaller than this (px)
    keep_largest: bool = False
    fill_holes: bool = False


def rembg_available() -> bool:
    return importlib.util.find_spec("rembg") is not None


# ---------------------------------------------------------------- helpers
def to_lab(bgr: np.ndarray) -> np.ndarray:
    """uint8 BGR -> float32 Lab with L in 0..100, a/b roughly -128..127."""
    return cv2.cvtColor(bgr.astype(np.float32) * (1.0 / 255.0), cv2.COLOR_BGR2Lab)


def rgb_to_lab(rgb) -> np.ndarray:
    r, g, b = (int(c) for c in rgb[:3])
    return to_lab(np.array([[[b, g, r]]], np.uint8))[0, 0]


def visible_alpha(bgra: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return ((bgra[:, :, 3].astype(np.uint16) * mask + 127) // 255).astype(np.uint8)


def _kernel(radius: int) -> np.ndarray:
    size = 2 * max(1, int(radius)) + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def edge_of(visible: np.ndarray, width: int = 1) -> np.ndarray:
    """The rim of the visible region, including the image border: where the
    background of a cutout is found."""
    inner = cv2.erode(visible.astype(np.uint8), _kernel(width),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)
    return visible & ~inner.astype(bool)


def edge_colours(lab: np.ndarray, seeds: np.ndarray, clusters: int = 3) -> np.ndarray | None:
    """The background colour(s) along the rim.

    Clustered rather than averaged, so a two-tone background (a table and a
    wall) gives two keys instead of a muddy mean of both.  Clusters holding a
    small share of the rim are dropped: that is usually the subject itself,
    touching the edge where the selection was drawn tight.
    """
    points = lab[seeds]
    if len(points) == 0:
        return None
    if len(points) > 6000:
        rng = np.random.default_rng(7)
        points = points[rng.choice(len(points), 6000, replace=False)]
    k = int(min(clusters, len(points)))
    if k <= 1:
        return points.mean(axis=0, keepdims=True).astype(np.float32)
    cv2.setRNGSeed(7)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _compact, labels, centres = cv2.kmeans(points.astype(np.float32), k, None, criteria,
                                           3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    keep = counts >= 0.18 * len(points)
    keep[int(np.argmax(counts))] = True
    return centres[keep].astype(np.float32)


def distance_to(lab: np.ndarray, colours: np.ndarray) -> np.ndarray:
    """Per-pixel delta E to the nearest of `colours`."""
    best = None
    for colour in np.asarray(colours, np.float32).reshape(-1, 3):
        d = np.sqrt(((lab - colour) ** 2).sum(axis=2))
        best = d if best is None else np.minimum(best, d)
    return best


def _ramp(d: np.ndarray, tolerance: float, softness: float) -> np.ndarray:
    """0 at or below the tolerance, 255 once `softness` above it."""
    if softness <= 0:
        return np.where(d < tolerance, 0, 255).astype(np.uint8)
    return (np.clip((d - tolerance) / softness, 0.0, 1.0) * 255.0).astype(np.uint8)


def trim_box(alpha: np.ndarray, threshold: int = 0):
    """(x0, y0, x1, y1) of the pixels above `threshold`, or None."""
    rows = np.flatnonzero((alpha > threshold).any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero((alpha > threshold).any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


# ---------------------------------------------------------------- the methods
def _keys(params: Params, lab: np.ndarray, seeds: np.ndarray):
    if params.method == WHITE:
        return rgb_to_lab((255, 255, 255))[None]
    if params.method == BLACK:
        return rgb_to_lab((0, 0, 0))[None]
    if params.key_color is not None:
        return rgb_to_lab(params.key_color)[None]
    return edge_colours(lab, seeds)


def _flood(bgra, visible, params: Params) -> np.ndarray:
    lab = to_lab(bgra[:, :, :3])
    seeds = edge_of(visible)
    keys = _keys(params, lab, seeds)
    if keys is None:
        return np.full(visible.shape, 255, np.uint8)
    d = distance_to(lab, keys)
    candidate = (visible & (d < params.tolerance)).astype(np.uint8)
    count, labels = cv2.connectedComponents(candidate, connectivity=8)
    touching = np.unique(labels[seeds & candidate.astype(bool)])
    lut = np.zeros(count, bool)
    lut[touching[touching > 0]] = True
    background = lut[labels]
    keep = np.where(background, 0, 255).astype(np.uint8)
    if params.softness > 0:
        # the colour ramp only applies in a thin band against the flooded region,
        # or every slightly-similar pixel in the subject would go translucent
        band = (cv2.dilate(background.astype(np.uint8), _kernel(2)).astype(bool)
                & ~background & (d < params.tolerance + params.softness))
        keep[band] = _ramp(d[band], params.tolerance, params.softness)
    return keep


def _gradient_flood(bgra, visible, params: Params) -> np.ndarray:
    """Floating-range flood from every rim pixel.  Each step may change by the
    tolerance, so a slow drift across the whole image is followed, while a
    sharp step - the subject's edge - stops it."""
    h, w = visible.shape
    lab = cv2.cvtColor(np.ascontiguousarray(bgra[:, :, :3]), cv2.COLOR_BGR2Lab)
    lab = cv2.GaussianBlur(lab, (0, 0), 1.0)           # JPEG noise would halt it
    step = max(1.0, params.tolerance / 5.0)
    diff = (step, step, step)
    fill = np.zeros((h + 2, w + 2), np.uint8)
    fill[1:-1, 1:-1][~visible] = 1                     # nonzero = a wall
    seeds = edge_of(visible)
    ys, xs = np.nonzero(seeds)
    stride = max(1, len(ys) // 4000)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    for y, x in zip(ys[::stride], xs[::stride]):
        if fill[y + 1, x + 1] == 0:
            cv2.floodFill(lab, fill, (int(x), int(y)), 0, diff, diff, flags)
    background = fill[1:-1, 1:-1] == 255
    soft = cv2.GaussianBlur(background.astype(np.float32), (0, 0), 0.7)
    return ((1.0 - np.maximum(soft, background)) * 255.0).astype(np.uint8)


def _key(bgra, visible, params: Params) -> np.ndarray:
    lab = to_lab(bgra[:, :, :3])
    keys = _keys(params, lab, edge_of(visible))
    if keys is None:
        return np.full(visible.shape, 255, np.uint8)
    return _ramp(distance_to(lab, keys), params.tolerance, params.softness)


def _grabcut(bgra, visible, params: Params) -> np.ndarray:
    h, w = visible.shape
    scale = min(1.0, (GRABCUT_PIXELS / float(h * w)) ** 0.5)
    if scale < 1.0:
        size = (max(8, int(w * scale)), max(8, int(h * scale)))
        bgr = cv2.resize(bgra[:, :, :3], size, interpolation=cv2.INTER_AREA)
        vis = cv2.resize(visible.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    else:
        bgr, vis = np.ascontiguousarray(bgra[:, :, :3]), visible
    sh, sw = vis.shape

    gc = np.full((sh, sw), cv2.GC_PR_FGD, np.uint8)
    band = max(2, int(round(0.025 * min(sh, sw))))
    gc[edge_of(vis, band)] = cv2.GC_PR_BGD
    # the floods' opinion is a strong hint: anything either would call
    # background starts on that side, and grabcut is free to disagree
    small = np.dstack([bgr, np.full((sh, sw), 255, np.uint8)])
    flood = (_flood(small, vis, params) < 128) | (_gradient_flood(small, vis, params) < 128)
    gc[flood & vis] = cv2.GC_PR_BGD
    gc[~vis] = cv2.GC_BGD
    fg_seed = (gc == cv2.GC_PR_FGD)
    if not fg_seed.any():
        # the flood took everything: seed the middle instead
        gc[sh // 4: 3 * sh // 4, sw // 4: 3 * sw // 4] = cv2.GC_PR_FGD
        gc[~vis] = cv2.GC_BGD
    if not ((gc == cv2.GC_BGD) | (gc == cv2.GC_PR_BGD)).any():
        gc[0, :] = gc[-1, :] = gc[:, 0] = gc[:, -1] = cv2.GC_PR_BGD
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, gc, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    fg = ((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)).astype(np.float32)
    if scale < 1.0:
        fg = cv2.resize(fg, (w, h), interpolation=cv2.INTER_LINEAR)
        # upsampled edges are soft by a pixel or so; that is the right amount
    return (np.clip(fg, 0.0, 1.0) * 255.0).astype(np.uint8)


def _ai(bgra, visible, params: Params) -> np.ndarray:
    from PIL import Image          # rembg depends on pillow
    from rembg import remove

    rgb = np.ascontiguousarray(bgra[:, :, 2::-1])
    matte = remove(Image.fromarray(rgb), only_mask=True)
    keep = np.asarray(matte, dtype=np.uint8)
    if keep.shape != visible.shape:
        keep = cv2.resize(keep, (visible.shape[1], visible.shape[0]))
    return keep


_METHOD_FUNCS = {FLOOD: _flood, GRADIENT: _gradient_flood, KEY: _key, WHITE: _key, BLACK: _key,
                 GRABCUT: _grabcut, AI: _ai}


# ---------------------------------------------------------------- refinement
def refine(keep: np.ndarray, visible: np.ndarray, params: Params) -> np.ndarray:
    keep = keep.copy()
    keep[~visible] = 0
    if params.keep_largest or params.despeckle > 0 or params.fill_holes:
        solid = keep >= 128
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            solid.astype(np.uint8), connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA]
        drop = np.zeros(count, bool)
        if params.keep_largest and count > 2:
            drop[1:] = True
            drop[1 + int(np.argmax(areas[1:]))] = False
        if params.despeckle > 0 and count > 1:
            drop[1:] |= areas[1:] < params.despeckle
        if drop.any():
            keep[drop[labels]] = 0
            solid = keep >= 128
        if params.fill_holes or params.despeckle > 0:
            # a hole is empty space that cannot reach the outside - the image
            # border or anywhere already transparent
            empty = (~solid).astype(np.uint8)
            count, labels, stats, _ = cv2.connectedComponentsWithStats(empty, connectivity=4)
            outside = ~visible.copy()
            outside[0, :] = outside[-1, :] = True
            outside[:, 0] = outside[:, -1] = True
            open_labels = np.unique(labels[outside & empty.astype(bool)])
            fill = np.ones(count, bool)
            fill[0] = False
            fill[open_labels] = False
            if not params.fill_holes:
                fill &= stats[:, cv2.CC_STAT_AREA] < params.despeckle
            if fill.any():
                keep[fill[labels]] = 255
    if params.grow > 0:
        keep = cv2.dilate(keep, _kernel(params.grow))
    elif params.grow < 0:
        keep = cv2.erode(keep, _kernel(-params.grow),
                         borderType=cv2.BORDER_CONSTANT, borderValue=0)
    if params.feather > 0:
        keep = cv2.GaussianBlur(keep, (0, 0), sigmaX=float(params.feather) * 0.5)
    keep[~visible] = 0
    return keep


def matte(bgra: np.ndarray, mask: np.ndarray, params: Params) -> np.ndarray:
    """How much of each pixel to keep (0-255), after refinement."""
    visible = visible_alpha(bgra, mask) >= VISIBLE
    if not visible.any():
        return np.zeros(mask.shape, np.uint8)
    keep = _METHOD_FUNCS[params.method](bgra, visible, params)
    return refine(keep, visible, params)


def remove_background(bgra: np.ndarray, mask: np.ndarray, params: Params) -> np.ndarray:
    """The new mask: `mask` with the background taken out of it."""
    keep = matte(bgra, mask, params)
    return ((mask.astype(np.uint16) * keep + 127) // 255).astype(np.uint8)


# ---------------------------------------------------------------- wand + islands
def wand_region(bgra: np.ndarray, mask: np.ndarray, x: int, y: int, tolerance: float,
                contiguous: bool = True, through_hidden: bool = False) -> np.ndarray | None:
    """The magic wand: pixels that look like the one at (x, y).  Returns a float
    0..1 selection with a half-pixel soft edge, or None when nothing matched.

    `through_hidden` lets the region run across pixels that are already
    transparent - what restoring needs, since those are the ones to bring back.
    """
    h, w = mask.shape
    if not (0 <= x < w and 0 <= y < h):
        return None
    lab = to_lab(bgra[:, :, :3])
    d = distance_to(lab, lab[y, x][None])
    candidate = d < tolerance
    if not through_hidden:
        candidate &= visible_alpha(bgra, mask) >= VISIBLE
    if not candidate[y, x]:
        return None
    if contiguous:
        _count, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=8)
        region = labels == labels[y, x]
    else:
        region = candidate
    soft = cv2.GaussianBlur(region.astype(np.float32), (0, 0), 0.6)
    return np.maximum(soft, region.astype(np.float32))


def islands(bgra: np.ndarray, mask: np.ndarray, params: Params, min_area: int = 400):
    """Split a sheet into its separate stickers.

    The background is found with `params` (a flood, normally), and every
    separate island left over that is at least `min_area` pixels becomes one
    cutout.  Returns [(x, y, keep)] with `keep` a float 0..1 patch whose top
    left is at (x, y), soft edge included.
    """
    keep = matte(bgra, mask, params)
    solid = (keep >= 128).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(solid, connectivity=8)
    h, w = keep.shape
    margin = int(max(2, np.ceil(params.feather)) + max(params.grow, 0) + 2)
    found = []
    order = sorted(range(1, count), key=lambda i: (stats[i, cv2.CC_STAT_TOP] // 32,
                                                   stats[i, cv2.CC_STAT_LEFT]))
    for index in order:
        if stats[index, cv2.CC_STAT_AREA] < min_area:
            continue
        x0 = max(0, stats[index, cv2.CC_STAT_LEFT] - margin)
        y0 = max(0, stats[index, cv2.CC_STAT_TOP] - margin)
        x1 = min(w, stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH] + margin)
        y1 = min(h, stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] + margin)
        own = (labels[y0:y1, x0:x1] == index).astype(np.uint8)
        # the soft edge pixels sit just outside the solid island; claim the ones
        # next to this island and no other
        reach = cv2.dilate(own, _kernel(margin)).astype(bool)
        others = (labels[y0:y1, x0:x1] > 0) & ~own.astype(bool)
        patch = keep[y0:y1, x0:x1].astype(np.float32) / 255.0
        patch[~reach | others] = 0.0
        found.append((int(x0), int(y0), patch))
    return found


# ---------------------------------------------------------------- export helpers
def premultiplied_resize(bgra: np.ndarray, factor: float) -> np.ndarray:
    """Resize without the dark fringe a straight resize of RGBA leaves."""
    if abs(factor - 1.0) < 1e-6:
        return bgra
    h, w = bgra.shape[:2]
    size = (max(1, int(round(w * factor))), max(1, int(round(h * factor))))
    alpha = bgra[:, :, 3:4].astype(np.float32) / 255.0
    pre = np.dstack([bgra[:, :, :3].astype(np.float32) * alpha, alpha[:, :, 0] * 255.0])
    interp = cv2.INTER_AREA if factor < 1.0 else cv2.INTER_CUBIC
    out = cv2.resize(pre, size, interpolation=interp)
    a = np.clip(out[:, :, 3], 0.0, 255.0)
    rgb = out[:, :, :3] / np.maximum(a[:, :, None] / 255.0, 1e-6)
    return np.dstack([np.clip(rgb, 0, 255), a]).astype(np.uint8)


def orient(bgra: np.ndarray, rotation: float, flip_x: bool, flip_y: bool) -> np.ndarray:
    """Mirror, then rotate clockwise by `rotation` degrees - the order the canvas
    applies them in - growing the image to fit the turned corners."""
    if flip_x:
        bgra = bgra[:, ::-1]
    if flip_y:
        bgra = bgra[::-1]
    bgra = np.ascontiguousarray(bgra)
    angle = ((rotation + 180.0) % 360.0) - 180.0
    if abs(angle) < 0.01:
        return bgra
    right = {90.0: cv2.ROTATE_90_CLOCKWISE, -90.0: cv2.ROTATE_90_COUNTERCLOCKWISE,
             -180.0: cv2.ROTATE_180, 180.0: cv2.ROTATE_180}
    for exact, code in right.items():
        if abs(angle - exact) < 0.01:
            return cv2.rotate(bgra, code)               # lossless for right angles
    h, w = bgra.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    out_w, out_h = int(np.ceil(h * sin + w * cos)), int(np.ceil(h * cos + w * sin))
    matrix[0, 2] += out_w / 2.0 - w / 2.0
    matrix[1, 2] += out_h / 2.0 - h / 2.0
    alpha = bgra[:, :, 3:4].astype(np.float32) / 255.0
    pre = np.dstack([bgra[:, :, :3].astype(np.float32) * alpha, alpha[:, :, 0] * 255.0])
    turned = cv2.warpAffine(pre, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = np.clip(turned[:, :, 3], 0.0, 255.0)
    rgb = turned[:, :, :3] / np.maximum(a[:, :, None] / 255.0, 1e-6)
    return np.dstack([np.clip(rgb, 0, 255), a]).astype(np.uint8)


def die_cut(alpha: np.ndarray, width: float, smooth: float = 0.0) -> tuple[np.ndarray, int]:
    """The die line of a sticker: everything within `width` px of the art,
    with its enclosed holes filled (a die cuts round the outside) and, with
    `smooth`, its notches and corners rounded off.

    Returns the border's alpha - larger than `alpha` by `pad` on every side -
    and that pad.  Built from a distance field, so a 100 px border costs the
    same as a 2 px one.
    """
    width = max(0.0, float(width))
    smooth = max(0.0, float(smooth))
    pad = int(math.ceil(width + 2.0 * smooth)) + 3
    art = cv2.copyMakeBorder((alpha >= 128).astype(np.uint8), pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=0)
    distance = cv2.distanceTransform((1 - art).astype(np.uint8), cv2.DIST_L2, 5)
    hard = (distance <= width).astype(np.uint8)
    # fill whatever the outside cannot reach: the inside of an O is not cut
    outside = hard.copy()
    flood = np.zeros((outside.shape[0] + 2, outside.shape[1] + 2), np.uint8)
    cv2.floodFill(outside, flood, (0, 0), 2)
    hard[outside == 0] = 1
    if smooth > 0:
        # blur and re-threshold: small notches and sharp corners round off,
        # long straight edges stay where they were
        soft = cv2.GaussianBlur(hard.astype(np.float32), (0, 0), smooth)
        hard = (soft >= 0.5).astype(np.uint8)
        # never let the rounding uncover the art itself
        hard |= (distance <= min(width, 1.5)).astype(np.uint8)
        edge = cv2.GaussianBlur(hard.astype(np.float32), (0, 0), 0.7)   # antialiased
        border = np.where(hard > 0, np.maximum(edge, 0.5 + edge / 2.0), edge)
    else:
        # antialias straight off the distance field: exact and cheap
        border = np.clip(width + 0.5 - distance, 0.0, 1.0)
        border[hard > 0] = np.maximum(border[hard > 0], 1.0)
    return (np.clip(border, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), pad


def add_outline(bgra: np.ndarray, width: float, colour_rgb=(255, 255, 255),
                smooth: float = 0.0, alpha: int = 255) -> np.ndarray:
    """A die-cut sticker border under the art (see die_cut).  The image grows
    by the border's pad on every side."""
    if width <= 0:
        return bgra
    border, pad = die_cut(bgra[:, :, 3], width, smooth)
    padded = cv2.copyMakeBorder(bgra, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    base = np.zeros_like(padded)
    r, g, b = (int(c) for c in colour_rgb[:3])
    base[:, :, 0], base[:, :, 1], base[:, :, 2] = b, g, r
    base[:, :, 3] = (border.astype(np.uint16) * alpha // 255).astype(np.uint8)
    # art over border, straight alpha "over"
    fa = padded[:, :, 3:4].astype(np.float32) / 255.0
    ba = base[:, :, 3:4].astype(np.float32) / 255.0
    out_a = fa + ba * (1.0 - fa)
    rgb = (padded[:, :, :3] * fa + base[:, :, :3] * ba * (1.0 - fa)) / np.maximum(out_a, 1e-6)
    return np.dstack([np.clip(rgb, 0, 255), out_a * 255.0]).astype(np.uint8)


def smooth_path(points, sigma: float):
    """A closed path with the jitter taken out: resampled evenly, then a
    Gaussian run round the loop.  Rounds a polygon's corners to about
    `sigma`, and turns a shaky freehand line into a clean one."""
    if sigma <= 0 or len(points) < 3:
        return list(points)
    pts = np.asarray(points, np.float64)
    loop = np.vstack([pts, pts[:1]])
    seg = np.hypot(*np.diff(loop, axis=0).T)
    total = float(seg.sum())
    if total <= 0:
        return list(points)
    step = max(0.5, sigma / 4.0)
    count = max(12, int(total / step))
    at = np.concatenate([[0.0], np.cumsum(seg)])
    even = np.linspace(0.0, total, count, endpoint=False)
    xs = np.interp(even, at, loop[:, 0])
    ys = np.interp(even, at, loop[:, 1])
    reach = sigma / (total / count)                  # sigma in samples
    half = int(math.ceil(reach * 3))
    if half < 1:
        return list(zip(xs, ys))
    offsets = np.arange(-half, half + 1)
    weights = np.exp(-0.5 * (offsets / reach) ** 2)
    weights /= weights.sum()
    def run(values):
        wrapped = np.concatenate([values[-half:], values, values[:half]])
        return np.convolve(wrapped, weights, mode="valid")
    return list(zip(run(xs), run(ys)))
