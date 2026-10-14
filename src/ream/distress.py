"""
Distress: the Texturelabs Distressor, redone on a rendered page.

The Distressor is a Photoshop panel.  Its looks come from greyscale texture
patterns stored in the PSDs it ships (patterns/<style>.psd): an "outer"
texture that roughens the edge of a shape and an "inner" one that knocks
specks out of it, plus a few "fade" textures that wear the ink unevenly.
ream reads those patterns straight out of the installed plugin (with
psd-tools), caches them as PNGs, and applies them with the same controls the
panel has:

| control | range    | does |
| ------- | -------- | ---- |
| style   | 14 looks | which outer / inner texture pair |
| scale   | 25..300  | texture size, % |
| edge    | 0..100   | how far the texture eats into the edge |
| bleed   | -20..20  | ink spread: positive fattens, negative starves |
| blur    | 0..100   | melts the shape before it is cut, rounding corners |
| inner   | 0..100   | specks knocked out of solid ink |
| refill  | 0..100   | how much ink comes back into those specks |
| fade    | 0..100   | uneven wear across the ink |
| seed    | 0..25    | where the textures land |

plus two of ream's own: **misfire** (the type wobbles off its line, like a
bad platen) and **paper** (the sheet itself picks up the fade texture).

The method: the ink's alpha becomes a signed distance field (pixels inside
the edge are positive).  The edge texture pushes that boundary inward by up
to `edge` pixels, bleed moves it out, blur smooths it, and the result is
re-cut with a half-pixel antialiased step.  Inner and fade textures then
multiply the coverage down.  Every length is given at 300 dpi and scaled to
the dpi in use, so the preview and the export match.

Without the plugin, procedural noise stands in for every style.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import zlib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np

EDGE_STYLES = ["rough", "stamp", "copier", "halftone", "grainy", "inked", "news",
               "perlin", "press", "rolled", "spray", "vintage", "weather", "block"]
FADE_STYLES = ["grain", "dust", "grunge", "paint", "print"]

# name: (low, high, what it does) - also the palette's "<name> <number>" verbs
PARAMS = {
    "scale": (25, 300, "texture size %"),
    "edge": (0, 100, "edge roughness"),
    "bleed": (-20, 20, "ink spread"),
    "blur": (0, 100, "melt before cutting"),
    "inner": (0, 100, "specks in solid ink"),
    "refill": (0, 100, "ink back in the specks"),
    "fade": (0, 100, "uneven wear"),
    "seed": (0, 25, "texture placement"),
    "misfire": (0, 100, "type off its line"),
    "paper": (0, 100, "aged paper"),
}


@dataclass
class Settings:
    enabled: bool = True
    style: str = "rough"
    fade_style: str = "grain"
    scale: float = 100
    edge: float = 10
    bleed: float = 0
    blur: float = 50
    inner: float = 50
    refill: float = 25
    fade: float = 25
    seed: float = 0
    misfire: float = 0
    paper: float = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# -- the plugin's textures --------------------------------------------------

def _cache_root() -> Path:
    base = os.environ.get("REAM_CACHE") or os.path.expanduser("~/Library/Caches/ream")
    return Path(base) / "distressor"


def plugin_dir() -> Path | None:
    """The installed Distressor's folder, wherever Creative Cloud put it."""
    env = os.environ.get("REAM_DISTRESSOR")
    if env:
        return Path(env) if (Path(env) / "patterns").is_dir() else None
    roots = [
        "~/Library/Application Support/Adobe/UXP/Plugins/External",
        "~/Library/Application Support/Adobe/UXP/PluginsStorage",
        "/Library/Application Support/Adobe/UXP/Plugins/External",
        "~/AppData/Roaming/Adobe/UXP/Plugins/External",
    ]
    for root in roots:
        for manifest in sorted(glob.glob(os.path.join(os.path.expanduser(root), "*", "manifest.json"))):
            try:
                with open(manifest, encoding="utf-8") as handle:
                    name = json.load(handle).get("name", "")
            except (OSError, ValueError):
                continue
            folder = Path(manifest).parent
            if "distressor" in name.lower() and (folder / "patterns").is_dir():
                return folder
    return None


def _extract(folder: Path, out: Path) -> dict:
    """Pull every pattern out of the plugin's PSDs into greyscale PNGs.  An
    edge style with two patterns has an Outer and an Inner one."""
    from psd_tools import PSDImage
    from psd_tools.api.pil_io import convert_pattern_to_pil
    from psd_tools.constants import Tag

    out.mkdir(parents=True, exist_ok=True)
    index: dict = {"edge": {}, "fade": {}}
    for psd_path in sorted((folder / "patterns").glob("*.psd")):
        name = psd_path.stem.lower()
        try:
            psd = PSDImage.open(psd_path)
            blocks = psd._record.layer_and_mask_information.tagged_blocks
            patterns = list(blocks.get_data(Tag.PATTERNS1) or [])
            groups = [layer.name for layer in psd]
        except Exception:
            continue
        files = []
        for n, pattern in enumerate(patterns):
            try:
                image = convert_pattern_to_pil(pattern).convert("L")
            except Exception:
                continue
            file = out / f"{name}_{n}.png"
            image.save(file)
            files.append((str(pattern.name).lower(), file.name))
        if not files:
            continue
        if any("fade" in g.lower() for g in groups):
            index["fade"][name] = files[0][1]
            continue
        outer = next((f for label, f in files if "outer" in label), files[0][1])
        inner = next((f for label, f in files if "inner" in label),
                     files[1][1] if len(files) > 1 else files[0][1])
        index["edge"][name] = {"outer": outer, "inner": inner}
    (out / "index.json").write_text(json.dumps(index, indent=1))
    return index


_index: dict | None = None
_textures: dict[str, np.ndarray] = {}
_lock = threading.Lock()        # the app warms the library up in a thread


def library() -> dict:
    """{"edge": {style: {"outer": png, "inner": png}}, "fade": {style: png},
    "source": "Distressor 1.0.7" | "procedural"}"""
    with _lock:
        return _library()


def _library() -> dict:
    global _index
    if _index is not None:
        return _index
    folder = plugin_dir()
    if folder is None:
        _index = {"edge": {}, "fade": {}, "source": "procedural"}
        return _index
    version = folder.name
    out = _cache_root() / version
    try:
        index = json.loads((out / "index.json").read_text())
    except (OSError, ValueError):
        try:
            index = _extract(folder, out)
        except Exception:
            index = {"edge": {}, "fade": {}}
    index["dir"] = str(out)
    index["source"] = f"Distressor {version.split('_')[-1]}" if index["edge"] else "procedural"
    _index = index
    return _index


def edge_styles() -> list[str]:
    known = library()["edge"]
    return [s for s in EDGE_STYLES if s in known] + sorted(set(known) - set(EDGE_STYLES)) \
        or list(EDGE_STYLES)


def fade_styles() -> list[str]:
    known = library()["fade"]
    return [s for s in FADE_STYLES if s in known] + sorted(set(known) - set(FADE_STYLES)) \
        or list(FADE_STYLES)


def _procedural(key: str) -> np.ndarray:
    """fBm noise, 1024 px square and seamless, standing in for a texture."""
    import cv2
    rng = np.random.default_rng(zlib.crc32(key.encode()))
    size, total = 1024, np.zeros((1024, 1024), np.float32)
    for octave, cells in enumerate((8, 16, 32, 64, 128, 256)):
        grid = rng.standard_normal((cells, cells)).astype(np.float32)
        tiled = np.tile(grid, (3, 3))
        up = cv2.resize(tiled, (size * 3, size * 3), interpolation=cv2.INTER_CUBIC)
        total += up[size:2 * size, size:2 * size] * (0.62 ** octave)
    return total


def _texture(kind: str, style: str, part: str = "outer") -> np.ndarray:
    """A texture as float32, standardised: mean 0, standard deviation 1."""
    key = f"{kind}:{style}:{part}"
    if key in _textures:
        return _textures[key]
    import cv2
    lib = library()
    file = None
    if kind == "edge" and style in lib["edge"]:
        file = lib["edge"][style][part]
    elif kind == "fade" and style in lib["fade"]:
        file = lib["fade"][style]
    tex = None
    if file:
        tex = cv2.imread(os.path.join(lib["dir"], file), cv2.IMREAD_GRAYSCALE)
    tex = tex.astype(np.float32) if tex is not None else _procedural(key)
    tex = (tex - float(tex.mean())) / max(1e-3, float(tex.std()))
    _textures[key] = tex
    return tex


_scaled: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


def _field(tex: np.ndarray, shape: tuple[int, int], scale: float,
           rng: np.random.Generator, origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """Tile a texture over `shape` at `scale`, turned and shifted by rng.

    `origin` is where `shape` sits on the whole page, in pixels, so a crop
    gets exactly the texture the whole page would have there.  The shift is
    drawn as a fraction of the tile, so the texture lands on the same spot of
    the page at any dpi - the preview matches the export."""
    import cv2
    turn = int(rng.integers(0, 8))
    fy, fx = float(rng.random()), float(rng.random())
    key = (id(tex), turn, round(scale, 4))
    cached = _scaled.get(key)
    t = cached[1] if cached is not None and cached[0] is tex else None   # ids get reused
    if t is None:
        t = np.rot90(tex, turn % 4)
        if turn >= 4:
            t = t[:, ::-1]
        if abs(scale - 1.0) > 1e-3:
            h, w = t.shape
            size = (max(4, int(round(w * scale))), max(4, int(round(h * scale))))
            t = cv2.resize(np.ascontiguousarray(t), size,
                           interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        t = np.ascontiguousarray(t)
        if len(_scaled) > 24:
            _scaled.clear()
        _scaled[key] = (tex, t)
    th, tw = t.shape
    rows = (np.arange(origin[0], origin[0] + shape[0]) + int(fy * th)) % th
    cols = (np.arange(origin[1], origin[1] + shape[1]) + int(fx * tw)) % tw
    return t[np.ix_(rows, cols)]


EDGE_PX, EDGE_BIAS, EDGE_GAIN = 1.0, 0.2, 0.8      # tuned against 300 dpi type
MELT_PX = 1.2


def _smoothstep(lo, hi, x):
    t = np.clip((x - lo) / max(1e-6, hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# -- applying it -------------------------------------------------------------

def apply(rgba: np.ndarray, s: Settings, dpi: float, origin: tuple[int, int] = (0, 0),
          density: float = 1.0) -> np.ndarray:
    """Distress a layer: (h, w, 4) uint8 straight RGBA in, the same out.  Only
    the alpha is reshaped; colour is carried out to wherever ink spreads.

    `origin` places a crop on the page (pixels, row then column).  `density`
    above 1 packs the ink denser: worn and antialiased edges fill back in."""
    import cv2
    h, w = rgba.shape[:2]
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    if alpha.max() <= 0.0:
        return rgba.copy()
    r = dpi / 300.0
    rng = np.random.default_rng(7919 + int(s.seed) * 104729)
    tex_scale = (s.scale / 100.0) * r
    outer = _field(_texture("edge", s.style, "outer"), (h, w), tex_scale, rng, origin)
    inner = _field(_texture("edge", s.style, "inner"), (h, w), tex_scale, rng, origin)
    wear = _field(_texture("fade", s.fade_style), (h, w), tex_scale, rng, origin)

    # signed distance to the ink's edge, positive inside, boundary at 0
    solid = (alpha > 0.5).astype(np.uint8)
    inside = cv2.distanceTransform(solid, cv2.DIST_L2, 5)
    outside = cv2.distanceTransform(1 - solid, cv2.DIST_L2, 5)
    dist = np.where(solid > 0, inside - 0.5, 0.5 - outside).astype(np.float32)

    shift = None
    if s.misfire > 0:
        # a slow wobble: each line of type sits a little off where it should
        amp = s.misfire / 100.0 * 4.0 * r
        lo = cv2.GaussianBlur(outer, (0, 0), 40 * r + 1)
        lo2 = cv2.GaussianBlur(inner, (0, 0), 40 * r + 1)
        norm = max(1e-3, float(lo.std()))
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        shift = (xs + lo / norm * amp, ys + lo2 / norm * amp * 0.6)
        dist = cv2.remap(dist, shift[0], shift[1], cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)

    melt = s.blur / 100.0 * MELT_PX * r
    if melt > 0.15:
        dist = cv2.GaussianBlur(dist, (0, 0), melt)

    # the texture moves the edge both ways: in where it is light, out where
    # it is dark, so edges go ragged rather than just thinner
    erode = s.edge / 10.0 * EDGE_PX * r * (EDGE_BIAS + EDGE_GAIN * outer)
    grow = s.bleed * 0.12 * r
    aa = max(0.5, 0.6 * r)
    cover = _smoothstep(-aa, aa, dist + grow - erode)

    if s.inner > 0:
        thr = 2.7 - 2.3 * (s.inner / 100.0)
        holes = _smoothstep(thr, thr + 0.6, inner)
        cover *= 1.0 - holes * (1.0 - s.refill / 100.0)
    if s.fade > 0:
        cover *= 1.0 - (s.fade / 100.0) * np.clip(0.5 + 0.4 * wear, 0.0, 1.0)
    if density > 1.0:
        cover = 1.0 - (1.0 - np.clip(cover, 0.0, 1.0)) ** density

    # semi-transparent ink stays semi-transparent; the distressed shape may
    # reach past the original only as far as it grew
    spread = max(0.0, grow) + s.edge / 10.0 * EDGE_PX * r * max(0.0, 2.5 * EDGE_GAIN - EDGE_BIAS)
    reach = int(2 * spread + (8 * r if shift is not None else 0)) * 2 + 3
    kept = cv2.dilate(alpha, np.ones((reach, reach), np.uint8))
    cover = np.clip(cover * kept, 0.0, 1.0)

    rgb = rgba[..., :3].astype(np.float32)
    if spread > 0 or shift is not None:
        # carry colour outward (normalised blur) so spread ink has a colour
        sigma = 2.0 * r + 1.0
        num = cv2.GaussianBlur(rgb * alpha[..., None], (0, 0), sigma)
        den = cv2.GaussianBlur(alpha, (0, 0), sigma)[..., None]
        carried = num / np.maximum(den, 1e-4)
        rgb = np.where(alpha[..., None] > 0.5, rgb, carried)
    out = np.empty_like(rgba)
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(cover * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def paper(shape: tuple[int, int], colour: tuple[int, int, int], s: Settings,
          dpi: float, origin: tuple[int, int] = (0, 0)) -> np.ndarray:
    """The sheet: (h, w, 3) uint8, aged by the fade texture when `paper` > 0."""
    h, w = shape
    sheet = np.empty((h, w, 3), np.float32)
    sheet[...] = colour
    if s.enabled and s.paper > 0:
        rng = np.random.default_rng(31337 + int(s.seed) * 7)
        wear = _field(_texture("fade", s.fade_style), (h, w), (s.scale / 100.0) * dpi / 300.0,
                      rng, origin)
        tone = 1.0 - (s.paper / 100.0) * 0.22 * np.clip(0.45 - 0.4 * wear, 0.0, 1.0)
        warm = np.array([1.0, 0.985, 0.95], np.float32)
        sheet *= (tone[..., None] * (1.0 - (1.0 - warm) * s.paper / 100.0))
    return np.clip(sheet, 0, 255).astype(np.uint8)


def compose(layer: np.ndarray, colour: tuple[int, int, int], s: Settings,
            dpi: float, origin: tuple[int, int] = (0, 0), density: float = 1.0) -> np.ndarray:
    """Distress a page's ink layer (straight RGBA) and lay it on paper:
    (h, w, 3) uint8 RGB.  `origin` places a crop on the page."""
    ink = apply(layer, s, dpi, origin, density) if s.enabled else layer
    sheet = paper(layer.shape[:2], colour, s, dpi, origin).astype(np.float32)
    a = ink[..., 3:4].astype(np.float32) / 255.0
    out = sheet * (1.0 - a) + ink[..., :3].astype(np.float32) * a
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
