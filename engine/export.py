"""
SVG export for WAVEFRONT contour output.

Generates plotter-ready SVG with adaptive stroke weights based on
field value (low T = thick/dark near seed, high T = thin/faint at edges).
"""

import svgwrite


def compute_stroke(normalized_t, wt_range):
    """
    Compute stroke width and opacity for a contour line.

    Lines near the seed (low normalized_t) are thicker and darker.
    Lines far from the seed (high normalized_t) are thinner and lighter.

    Args:
        normalized_t: float 0–1, position in field range
        wt_range: float 0–1, weight variation strength

    Returns:
        (stroke_width, stroke_opacity) tuple of floats
    """
    width = max(0.2, 1.4 - normalized_t * wt_range * 1.2)
    opacity = max(0.35, 0.95 - normalized_t * 0.4)
    return round(width, 3), round(opacity, 3)


def contours_to_svg(contours, img_width, img_height, wt_range=0.6):
    """
    Convert contour list to SVG string using svgwrite.

    Coordinate system: contours from skimage are in (row, col) = (y, x) order.
    SVG uses x,y order. We swap on output.

    Args:
        contours: list of dicts with 'points' (N,2) [row,col] and 'normalized_t'
        img_width: int, SVG canvas width in pixels
        img_height: int, SVG canvas height in pixels
        wt_range: float, stroke weight variation

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


def contours_to_svg_string_fast(contours, img_width, img_height, wt_range=0.6):
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
