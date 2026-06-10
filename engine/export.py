"""
SVG export for WAVEFRONT contour output.

Default is plotter ink: a CONSTANT full-opacity black stroke (~0.7 px on the
processing grid), matching CONTOUR-V (STUDIO shows STROKE 0.70 with STROKE MOD
off — a plotter has one pen). Weight/opacity modulation (thick/dark near seed,
thin/faint far away) is OPT-IN via wt_range > 0, the STROKE MOD equivalent.
"""

import svgwrite


# Constant stroke width in PROCESSING-GRID pixels (CONTOUR-V STUDIO: 0.70).
# Callers pass stroke_scale = original_width / grid_width so the exported SVG
# (in original-image coordinates) keeps the same visual weight.
STROKE_WIDTH = 0.75


def compute_stroke(normalized_t, wt_range):
    """
    Compute stroke width and opacity for a contour line.

    wt_range == 0 (the default): constant STROKE_WIDTH at full opacity — the
    plotter-ink look of the reference outputs. wt_range > 0 enables modulation:
    lines near the seed (low normalized_t) are thicker and darker, far lines
    thinner and lighter, scaled by wt_range.

    Args:
        normalized_t: float 0–1, position in field range
        wt_range: float 0–1, weight variation strength (0 = constant ink)

    Returns:
        (stroke_width, stroke_opacity) tuple of floats
    """
    if wt_range <= 0:
        return STROKE_WIDTH, 1.0
    width = max(0.2, 1.4 - normalized_t * wt_range * 1.2)
    opacity = max(0.35, 0.95 - normalized_t * 0.4 * wt_range)
    return round(width, 3), round(opacity, 3)


def contours_to_svg(contours, img_width, img_height, wt_range=0.0, stroke_scale=1.0):
    """
    Convert contour list to SVG string using svgwrite.

    Coordinate system: contours from skimage are in (row, col) = (y, x) order.
    SVG uses x,y order. We swap on output.

    Args:
        contours: list of dicts with 'points' (N,2) [row,col] and 'normalized_t'
        img_width: int, SVG canvas width in pixels
        img_height: int, SVG canvas height in pixels
        wt_range: float, stroke weight variation (0 = constant plotter ink)
        stroke_scale: multiply stroke widths by this (original px per grid px),
            so width keeps its processing-grid visual weight after upscaling

    Returns:
        svg_string: str, complete SVG document
    """
    dwg = svgwrite.Drawing(
        size=(f'{img_width}px', f'{img_height}px'),
        viewBox=f'0 0 {img_width} {img_height}'
    )

    dwg.add(dwg.rect(
        insert=(0, 0),
        size=(img_width, img_height),
        fill='white'
    ))

    for c in contours:
        pts = c['points']
        if len(pts) < 2:
            continue

        norm_t = c['normalized_t']
        width, opacity = compute_stroke(norm_t, wt_range)
        width = round(width * stroke_scale, 3)

        coords = [(round(float(pt[1]), 1), round(float(pt[0]), 1)) for pt in pts]

        d = f'M{coords[0][0]},{coords[0][1]}'
        d += ''.join(f'L{x},{y}' for x, y in coords[1:])

        dwg.add(dwg.path(
            d=d,
            fill='none',
            stroke=f'rgba(10,10,15,{opacity})',
            stroke_width=width,
            stroke_linecap='round',
            stroke_linejoin='round'
        ))

    return dwg.tostring()


def contours_to_svg_string_fast(contours, img_width, img_height, wt_range=0.0,
                                stroke_scale=1.0):
    """
    Fast string-building SVG export (avoids svgwrite overhead for large path counts).
    Preferred for production use.

    Args: same as contours_to_svg
    Returns: svg string
    """
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{img_width}" height="{img_height}" '
        f'viewBox="0 0 {img_width} {img_height}">',
        f'<rect width="{img_width}" height="{img_height}" fill="white"/>'
    ]

    for c in contours:
        pts = c['points']
        if len(pts) < 2:
            continue

        norm_t = c['normalized_t']
        width, opacity = compute_stroke(norm_t, wt_range)
        width = round(width * stroke_scale, 3)

        first = pts[0]
        d = f'M{first[1]:.1f},{first[0]:.1f}'
        d += ''.join(f'L{pt[1]:.1f},{pt[0]:.1f}' for pt in pts[1:])

        lines.append(
            f'<path d="{d}" fill="none" '
            f'stroke="rgba(10,10,15,{opacity})" '
            f'stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    lines.append('</svg>')
    return '\n'.join(lines)
