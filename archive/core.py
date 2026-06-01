"""
CONTOUR-V CORE — consolidated single-file implementation.

A portrait → plotter-ready line-art generator. Converts a raster image
into a set of clean polylines suitable for pen plotters (AxiDraw, NextDraw,
Bantam) or vector workflows.

Two modes:
  * "topographic"  — marching squares on the enhanced brightness field.
                      Classic topographic-portrait look. No seed.
  * "radiating"    — weighted distance transform from a square seed, then
                      contoured at equal distance intervals. Produces the
                      VEX-LINE-style "rings radiating from a seed" look
                      with background fill. Requires a seed point.

Pipeline (both modes):
  image → grayscale → gamma/contrast → blur → local contrast enhance →
    [mode-specific field construction] → iso-contour extraction →
    Douglas-Peucker simplify → arc-length resample → Chaikin smooth →
    min-gap filtering → nearest-neighbor stroke ordering → polyline list

Dependencies: numpy, scipy, scikit-image, Pillow, matplotlib (for demo).

Usage:
    from contour import generate, render_png, save_svg
    polys, field = generate("photo.jpg", mode="radiating", seed_xy=(250, 110))
    render_png(polys, "out.png", width=500, height=650)
    save_svg(polys, "out.svg", 500, 650, width_mm=190, height_mm=247)
"""
from __future__ import annotations
import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from skimage import exposure
from skimage import measure


# =============================================================================
# IMAGE LOADING
# =============================================================================

def load_gray(path: str, max_side: int = 500) -> np.ndarray:
    """Load image, honor EXIF rotation, convert to grayscale in [0,1]."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
    arr = np.asarray(img).astype(np.float32) / 255.0
    alpha = arr[..., 3]
    rgb = arr[..., :3]
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    gray = alpha * lum + (1 - alpha) * 1.0  # transparent → white

    h, w = gray.shape
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        nw, nh = int(w * scale), int(h * scale)
        gray = np.asarray(
            Image.fromarray((gray * 255).astype(np.uint8), mode="L")
            .resize((nw, nh), Image.LANCZOS)
        ).astype(np.float32) / 255.0
    return gray


# =============================================================================
# PREPROCESSING — shared by both modes
# =============================================================================

def preprocess_field(
    gray: np.ndarray,
    *,
    invert: bool = False,
    gamma: float = 1.0,
    contrast: float = 0.3,
    local_equalize: float = 0.0,
    local_equalize_clip: float = 0.01,
    blur: float = 2.0,
    detail_sigma: float = 6.0,
    detail_amount: float = 1.5,
) -> np.ndarray:
    """
    Shared preprocessing: gamma/contrast shaping, blur, then unsharp-mask
    local contrast enhancement. This is where most of the 'artistic' tuning
    lives — these params control how the image gets turned into something
    the contour algorithm can work with well.
    """
    src = 1 - gray if invert else gray
    v = np.clip(src, 0, 1) ** gamma
    v = np.clip((v - 0.5) * (1 + contrast) + 0.5, 0, 1)
    if local_equalize > 0:
        eq = exposure.equalize_adapthist(v, clip_limit=local_equalize_clip)
        v = np.clip((1.0 - local_equalize) * v + local_equalize * eq, 0, 1)
    if blur > 0:
        v = gaussian_filter(v, sigma=blur)
    if detail_amount > 0:
        blurred = gaussian_filter(v, sigma=detail_sigma)
        v = np.clip(v + detail_amount * (v - blurred), 0, 1)
    return v


# =============================================================================
# MODE 1: TOPOGRAPHIC (marching squares on brightness field)
# =============================================================================

def topographic_field(gray: np.ndarray, **preprocess_kwargs) -> np.ndarray:
    """Just the enhanced brightness field. Contour at constant brightness."""
    return preprocess_field(gray, **preprocess_kwargs)


# =============================================================================
# MODE 2: RADIATING (weighted distance transform from seed)
# =============================================================================

def _weighted_distance(cost: np.ndarray, seed_region: np.ndarray,
                       diag_cost: float = 1.2) -> np.ndarray:
    """
    Exact weighted distance transform using grid-graph Dijkstra.
    `cost` is per-pixel traversal cost.
    `seed_region` is a bool mask (True = distance 0).
    `diag_cost` controls propagation geometry:
        1.0   — Chebyshev, square isolines (matches VEX-LINE reference)
        1.414 — Euclidean, round isolines
        1.2   — good middle ground
    """
    cost = np.asarray(cost, dtype=np.float64)
    seed_region = np.asarray(seed_region, dtype=bool)
    if cost.ndim != 2:
        raise ValueError("cost must be a 2D array")
    if seed_region.shape != cost.shape:
        raise ValueError("seed_region must have the same shape as cost")
    if not np.any(seed_region):
        raise ValueError("seed_region must contain at least one seed pixel")
    if diag_cost <= 0:
        raise ValueError("diag_cost must be positive")
    if not np.all(np.isfinite(cost)) or np.any(cost < 0):
        raise ValueError("cost must contain only finite non-negative values")

    h, w = cost.shape
    node_ids = np.arange(h * w, dtype=np.int64).reshape(h, w)

    rows = []
    cols = []
    data = []

    def add_grid_edges(a: np.ndarray, b: np.ndarray, step: float) -> None:
        weights = 0.5 * (cost.ravel()[a] + cost.ravel()[b]) * step
        rows.extend([a, b])
        cols.extend([b, a])
        data.extend([weights, weights])

    add_grid_edges(node_ids[:, :-1].ravel(), node_ids[:, 1:].ravel(), 1.0)
    add_grid_edges(node_ids[:-1, :].ravel(), node_ids[1:, :].ravel(), 1.0)
    add_grid_edges(node_ids[:-1, :-1].ravel(), node_ids[1:, 1:].ravel(), diag_cost)
    add_grid_edges(node_ids[:-1, 1:].ravel(), node_ids[1:, :-1].ravel(), diag_cost)

    n_nodes = h * w
    source = n_nodes
    seed_nodes = np.flatnonzero(seed_region.ravel()).astype(np.int64)
    rows.append(np.full(seed_nodes.shape, source, dtype=np.int64))
    cols.append(seed_nodes)
    data.append(np.zeros(seed_nodes.shape, dtype=np.float64))

    graph = coo_matrix(
        (np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n_nodes + 1, n_nodes + 1),
    ).tocsr()
    dist = dijkstra(graph, directed=True, indices=source, return_predecessors=False)
    return np.asarray(dist[:n_nodes]).reshape(h, w)


def radiating_field(
    gray: np.ndarray,
    seed_xy: tuple[int, int],
    *,
    seed_size: int = 4,
    speed_exponent: float = 2.5,
    speed_floor: float = 0.15,
    edge_amount: float = 0.0,
    edge_sigma: float = 1.0,
    field_detail_amount: float = 0.0,
    diag_cost: float = 1.2,
    **preprocess_kwargs,
) -> np.ndarray:
    """
    Enhanced brightness → speed map → weighted distance from seed.
    Dark pixels = slow wavefront = contours bunch up at features.
    Optional edge drag also slows wavefronts at local gradients, which makes
    subtle facial features perturb radiating contours more strongly.
    Square seed + Chebyshev-ish metric = characteristic radiating squares
    in the unmodulated background.
    """
    v = preprocess_field(gray, **preprocess_kwargs)
    speed = np.clip(v ** speed_exponent, speed_floor, 1.0)
    edge_feature = None
    if edge_amount > 0 or field_detail_amount > 0:
        edge_src = gaussian_filter(v, sigma=edge_sigma) if edge_sigma > 0 else v
        gy, gx = np.gradient(edge_src)
        edge_feature = np.hypot(gx, gy)
        scale = np.percentile(edge_feature, 98)
        if scale > 1e-9:
            edge_feature = np.clip(edge_feature / scale, 0, 1)
        else:
            edge_feature = None
    if edge_amount > 0 and edge_feature is not None:
        speed = np.clip(speed / (1.0 + edge_amount * edge_feature), speed_floor, 1.0)
    cost = 1.0 / speed

    h, w = gray.shape
    sx, sy = int(round(seed_xy[0])), int(round(seed_xy[1]))
    if seed_size < 0:
        raise ValueError("seed_size must be non-negative")
    if not (0 <= sx < w and 0 <= sy < h):
        raise ValueError(
            f"seed_xy {seed_xy!r} is outside image bounds "
            f"0 <= x < {w}, 0 <= y < {h}"
        )
    seed_region = np.zeros((h, w), dtype=bool)
    y0 = max(0, sy - seed_size); y1 = min(h, sy + seed_size + 1)
    x0 = max(0, sx - seed_size); x1 = min(w, sx + seed_size + 1)
    seed_region[y0:y1, x0:x1] = True

    field = _weighted_distance(cost, seed_region, diag_cost=diag_cost)
    if field_detail_amount > 0:
        dark_feature = 1.0 - v
        scale = np.percentile(dark_feature, 98)
        if scale > 1e-9:
            dark_feature = np.clip(dark_feature / scale, 0, 1)
        detail = dark_feature
        if edge_feature is not None:
            detail = np.maximum(detail, edge_feature)
        field = field + field_detail_amount * detail
    return field


# =============================================================================
# CONTOUR EXTRACTION
# =============================================================================

def extract_contours(
    field: np.ndarray,
    n_contours: int = 160,
    *,
    min_contour_length: int = 15,
) -> list[np.ndarray]:
    """Evenly-spaced iso-contours of the given scalar field."""
    finite = field[np.isfinite(field)]
    if finite.size == 0:
        return []
    lo = float(finite.min())
    hi = float(np.percentile(finite, 99))
    if hi <= lo:
        return []
    levels = np.linspace(
        lo + (hi - lo) / (n_contours + 1),
        lo + (hi - lo) * 0.98,
        n_contours,
    )

    polys: list[np.ndarray] = []
    for lvl in levels:
        for c in measure.find_contours(field, lvl):
            if len(c) < min_contour_length:
                continue
            # skimage returns (row, col); convert to (x, y)
            pts = np.column_stack([c[:, 1], c[:, 0]]).astype(np.float32)
            polys.append(pts)
    return polys


# =============================================================================
# POLYLINE POLISHING — Douglas-Peucker + resample + Chaikin
# =============================================================================

def _douglas_peucker(points: np.ndarray, eps: float) -> np.ndarray:
    """Iterative DP. Returns indices of kept points."""
    n = len(points)
    if n < 3:
        return np.arange(n)
    keep = np.zeros(n, dtype=bool)
    keep[0] = True; keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        p0, p1 = points[a], points[b]
        seg = p1 - p0
        seg_len = float(np.hypot(*seg))
        rel = points[a + 1:b] - p0
        if seg_len < 1e-9:
            d = np.hypot(rel[:, 0], rel[:, 1])
        else:
            cross = rel[:, 0] * seg[1] - rel[:, 1] * seg[0]
            d = np.abs(cross) / seg_len
        if len(d) == 0:
            continue
        mi = int(np.argmax(d))
        if d[mi] > eps:
            pivot = a + 1 + mi
            keep[pivot] = True
            stack.append((a, pivot))
            stack.append((pivot, b))
    return np.where(keep)[0]


def _arc_resample(points: np.ndarray, spacing: float) -> np.ndarray:
    """Resample a polyline to equal arc-length steps."""
    if len(points) < 2:
        return points
    segs = np.diff(points, axis=0)
    seg_lens = np.hypot(segs[:, 0], segs[:, 1])
    cum = np.concatenate([[0], np.cumsum(seg_lens)])
    total = cum[-1]
    if total < spacing:
        return points
    n_out = max(2, int(np.ceil(total / spacing)) + 1)
    targets = np.linspace(0, total, n_out)
    xs = np.interp(targets, cum, points[:, 0])
    ys = np.interp(targets, cum, points[:, 1])
    return np.column_stack([xs, ys]).astype(np.float32)


def _chaikin(points: np.ndarray, iterations: int) -> np.ndarray:
    pts = points
    for _ in range(iterations):
        if len(pts) < 3:
            return pts
        p = pts[:-1]; q = pts[1:]
        q1 = 0.75 * p + 0.25 * q
        q2 = 0.25 * p + 0.75 * q
        out = np.empty((len(p) * 2, 2), dtype=pts.dtype)
        out[0::2] = q1; out[1::2] = q2
        pts = np.vstack([pts[0:1], out, pts[-1:]])
    return pts


def polish(
    polys: list[np.ndarray],
    *,
    dp_eps: float = 0.6,
    resample_spacing: float = 3.0,
    chaikin_iters: int = 2,
) -> list[np.ndarray]:
    """Simplify → resample → smooth each polyline."""
    out = []
    for p in polys:
        if len(p) < 4:
            continue
        idx = _douglas_peucker(p, dp_eps)
        q = _arc_resample(p[idx], resample_spacing)
        q = _chaikin(q, chaikin_iters)
        if len(q) >= 3:
            out.append(q)
    return out


# =============================================================================
# PLOTTER PREP — drop near-duplicates + reorder for minimum pen-up travel
# =============================================================================

def drop_overlapping(polys: list[np.ndarray],
                      min_gap_px: float = 0.8) -> list[np.ndarray]:
    """Drop contours whose majority of points fall within min_gap of a kept contour."""
    if min_gap_px <= 0 or not polys:
        return polys
    kept = [polys[0]]
    tree = cKDTree(polys[0])
    for p in polys[1:]:
        d, _ = tree.query(p, k=1)
        if np.mean(d < min_gap_px) < 0.2:
            kept.append(p)
            if len(kept) % 20 == 0:
                tree = cKDTree(np.vstack(kept))
            else:
                # Incremental update would be cheaper; for simplicity rebuild every 20
                tree = cKDTree(np.vstack(kept))
    return kept


def reorder_for_plotter(polys: list[np.ndarray]) -> list[np.ndarray]:
    """Greedy nearest-endpoint ordering; may reverse individual polylines."""
    if len(polys) < 2:
        return polys
    remaining = list(range(len(polys)))
    ordered = []
    cur = np.array([0.0, 0.0], dtype=np.float32)
    while remaining:
        best_ri = 0; best_d = np.inf; best_rev = False
        for ri, idx in enumerate(remaining):
            p = polys[idx]
            d_s = float(np.hypot(*(p[0] - cur)))
            d_e = float(np.hypot(*(p[-1] - cur)))
            if d_s < best_d:
                best_d = d_s; best_ri = ri; best_rev = False
            if d_e < best_d:
                best_d = d_e; best_ri = ri; best_rev = True
        idx = remaining.pop(best_ri)
        p = polys[idx]
        if best_rev:
            p = p[::-1]
        ordered.append(p)
        cur = p[-1]
    return ordered


# =============================================================================
# TOP-LEVEL API
# =============================================================================

def generate(
    image_path: str,
    *,
    mode: str = "radiating",           # "radiating" | "topographic"
    seed_xy: tuple[int, int] | None = None,
    max_side: int = 500,

    # Preprocessing
    invert: bool = False,
    gamma: float = 1.0,
    contrast: float = 0.3,
    local_equalize: float = 0.0,
    local_equalize_clip: float = 0.01,
    blur: float = 2.0,
    detail_sigma: float = 6.0,
    detail_amount: float = 1.5,

    # Radiating-mode only
    seed_size: int = 4,
    speed_exponent: float = 2.5,
    speed_floor: float = 0.15,
    edge_amount: float = 0.0,
    edge_sigma: float = 1.0,
    field_detail_amount: float = 0.0,
    diag_cost: float = 1.2,

    # Contour extraction
    n_contours: int = 160,
    min_contour_length: int = 15,

    # Polishing
    dp_eps: float = 0.6,
    resample_spacing: float = 3.0,
    chaikin_iters: int = 2,

    # Plotter prep
    min_gap_px: float = 0.8,
    reorder: bool = True,
) -> tuple[list[np.ndarray], np.ndarray]:
    """
    End-to-end: image → list of polished polylines + the underlying field.

    Returns (polys, field) where polys is a list of (N,2) float32 arrays in
    image coordinates (x right, y down). `field` is the scalar field that
    was contoured, returned for visualization/debug.
    """
    gray = load_gray(image_path, max_side=max_side)
    h, w = gray.shape

    pp = dict(invert=invert, gamma=gamma, contrast=contrast,
              local_equalize=local_equalize,
              local_equalize_clip=local_equalize_clip, blur=blur,
              detail_sigma=detail_sigma, detail_amount=detail_amount)

    if mode == "topographic":
        field = topographic_field(gray, **pp)
    elif mode == "radiating":
        if seed_xy is None:
            seed_xy = (w // 2, h // 2)
        field = radiating_field(
            gray, seed_xy,
            seed_size=seed_size,
            speed_exponent=speed_exponent,
            speed_floor=speed_floor,
            edge_amount=edge_amount,
            edge_sigma=edge_sigma,
            field_detail_amount=field_detail_amount,
            diag_cost=diag_cost,
            **pp,
        )
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'topographic' or 'radiating'.")

    raw = extract_contours(field, n_contours=n_contours,
                           min_contour_length=min_contour_length)
    polys = polish(raw, dp_eps=dp_eps,
                    resample_spacing=resample_spacing,
                    chaikin_iters=chaikin_iters)
    polys = drop_overlapping(polys, min_gap_px=min_gap_px)
    if reorder:
        polys = reorder_for_plotter(polys)
    return polys, field


# =============================================================================
# RENDERING + EXPORT
# =============================================================================

def render_png(polys: list[np.ndarray], out_path: str,
               width: int, height: int,
               *,
               line_width: float = 0.55,
               color: str = "#10104a",
               dpi: int = 240) -> None:
    """Render polylines to a PNG for preview."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 8 * height / width))
    ax.set_facecolor("white")
    ax.set_xlim(0, width); ax.set_ylim(height, 0); ax.set_aspect("equal")
    for p in polys:
        ax.plot(p[:, 0], p[:, 1], color=color, linewidth=line_width,
                solid_capstyle="round")
    ax.axis("off")
    import matplotlib.pyplot as _p
    _p.tight_layout()
    _p.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    _p.close(fig)


def save_svg(polys: list[np.ndarray],
              out_path: str,
              image_width_px: int,
              image_height_px: int,
              *,
              width_mm: float = 190.0,
              height_mm: float | None = None,
              stroke_width_mm: float = 0.3,
              stroke_color: str = "#10104a") -> None:
    """
    Write an SVG with physical units (mm). Polylines map from image pixels
    to the specified paper size while preserving aspect ratio.
    """
    if image_width_px <= 0 or image_height_px <= 0:
        raise ValueError("image dimensions must be positive")
    if width_mm <= 0:
        raise ValueError("width_mm must be positive")
    if height_mm is None:
        height_mm = width_mm * image_height_px / image_width_px
    if height_mm <= 0:
        raise ValueError("height_mm must be positive")
    scale = min(width_mm / image_width_px, height_mm / image_height_px)
    draw_width_mm = image_width_px * scale
    draw_height_mm = image_height_px * scale
    tx = (width_mm - draw_width_mm) * 0.5
    ty = (height_mm - draw_height_mm) * 0.5

    lines = []
    lines.append(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width_mm}mm" height="{height_mm}mm" '
        f'viewBox="0 0 {width_mm} {height_mm}">\n'
        f'<g fill="none" stroke="{stroke_color}" '
        f'stroke-width="{stroke_width_mm}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n'
    )
    for p in polys:
        pts = " ".join(f"{x * scale + tx:.3f},{y * scale + ty:.3f}" for x, y in p)
        lines.append(f'<polyline points="{pts}"/>\n')
    lines.append('</g>\n</svg>\n')

    with open(out_path, "w") as f:
        f.writelines(lines)


# =============================================================================
# DIAGNOSTIC — print plotter-readiness stats for a generated set
# =============================================================================

def audit(polys: list[np.ndarray], image_width_px: int, image_height_px: int,
          *, paper_width_mm: float = 190.0, plot_speed_cm_per_s: float = 8.0):
    """Print plotter-readiness summary."""
    mm_per_px = paper_width_mm / image_width_px
    n = len(polys)
    if n == 0:
        print("No polylines."); return
    verts = [len(p) for p in polys]
    total_len_px = sum(float(np.sum(np.hypot(*np.diff(p, axis=0).T))) for p in polys)

    # Pen-up travel assuming starting at origin
    pen_up_px = 0.0
    cur = np.array([0.0, 0.0], dtype=np.float32)
    for p in polys:
        pen_up_px += float(np.hypot(*(p[0] - cur)))
        cur = p[-1]

    total_len_mm = total_len_px * mm_per_px
    pen_up_mm = pen_up_px * mm_per_px
    plot_minutes = total_len_mm / 10 / plot_speed_cm_per_s / 60

    print(f"Strokes: {n}")
    print(f"Vertices: total={sum(verts):,}  "
          f"median={int(np.median(verts))}  max={max(verts)}")
    print(f"Draw length @ paper scale: {total_len_mm/1000:.2f} m "
          f"(~{plot_minutes:.1f} min @ {plot_speed_cm_per_s} cm/s)")
    print(f"Pen-up travel: {pen_up_mm/1000:.2f} m")


# =============================================================================
# DEMO
# =============================================================================

if __name__ == "__main__":
    import sys
    img = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/eric_cropped.jpg"
    mode = sys.argv[2] if len(sys.argv) > 2 else "radiating"

    gray = load_gray(img, max_side=500)
    h, w = gray.shape
    seed = (w // 2, int(h * 0.22))

    polys, field = generate(img, mode=mode, seed_xy=seed, max_side=500)
    print(f"Generated {len(polys)} polylines in {mode!r} mode.")
    audit(polys, w, h)

    render_png(polys, f"/mnt/user-data/outputs/demo_{mode}.png", w, h)
    save_svg(polys, f"/mnt/user-data/outputs/demo_{mode}.svg", w, h)
    print(f"Saved PNG + SVG to /mnt/user-data/outputs/demo_{mode}.*")
