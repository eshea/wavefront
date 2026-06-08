#!/usr/bin/env python3
"""
loop/render.py — render the canonical test IN-PROCESS for one tick.

Why in-process: the loop edits engine constants (e.g. WAVE_RELIEF in
engine/field.py) and then needs to render with the NEW values. The long-running
Flask app imports the engine once at startup and never reloads it, so POSTing to
it renders STALE code every tick — the loop's edits would have no effect. Running
the pipeline here, in a fresh `python` process per tick, re-imports the engine so
each edit actually takes effect.

This mirrors app.py's /process pipeline exactly (same engine functions, same
method dispatch) and writes the same three artifacts score_tick.sh consumes:
    loop/output/iter_NNN.svg
    loop/output/iter_NNN.png   (rasterized via rsvg-convert)
    loop/output/iter_NNN.stats.json

Usage:
    python loop/render.py <iter_number> [--method wave] [--levels 90]
                          [--smooth 0.0] [--lum-mix 0.8] [--wt-range 0.0]
                          [--seed-x N --seed-y N] [--input PATH]
                          [--png-width 780] [--out-dir loop/output]

Defaults match loop/render_tick.sh's canonical settings. Seed defaults to the
processing-grid center (same as app.py when no seed is provided).
"""
import sys
import json
import argparse
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from engine.field import (load_and_preprocess, to_luminance, build_field,  # noqa: E402
                          build_wave_field)
from engine.contour import extract_contours, scale_contours  # noqa: E402
from engine.smooth import smooth_contours  # noqa: E402
from engine.export import contours_to_svg_string_fast  # noqa: E402
from engine.flow import trace_flow_lines  # noqa: E402
from engine.march import build_march_field  # noqa: E402

METHODS = ("contour", "wave", "flow", "march")


def render(iter_num, method="wave", levels=111, smooth=0.0, lum_mix=0.8,
           wt_range=0.0, seed_x=None, seed_y=None,
           input_path=REPO / "examples" / "woman" / "woman-source.jpeg",
           png_width=780, out_dir=REPO / "loop" / "output"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    method = method if method in METHODS else "contour"

    rgb, original_size, processed_size = load_and_preprocess(str(input_path))
    orig_w, orig_h = original_size
    img_w, img_h = processed_size
    luminance = to_luminance(rgb)

    sx = img_w // 2 if seed_x is None else max(0, min(img_w - 1, seed_x))
    sy = img_h // 2 if seed_y is None else max(0, min(img_h - 1, seed_y))

    # Same dispatch as app.py /process.
    if method == "flow":
        contours, stats = trace_flow_lines(luminance, sx, sy, levels, lum_mix)
    else:
        if method == "wave":
            field, f_min, f_max = build_wave_field(luminance, sx, sy, lum_mix)
        elif method == "march":
            field, f_min, f_max = build_march_field(luminance, sx, sy, lum_mix)
        else:
            field, f_min, f_max = build_field(luminance, sx, sy, lum_mix)
        contours, stats = extract_contours(field, levels, f_min, f_max)
    stats["method"] = method
    stats["source"] = str(input_path)   # so score_tick can score against the source

    contours = smooth_contours(contours, smooth)
    total_pts = sum(len(c["points"]) for c in contours)
    stats["total_points"] = total_pts
    stats["segments"] = max(total_pts - stats.get("paths", 0), 0)

    export_contours = scale_contours(contours, processed_size, original_size)
    svg = contours_to_svg_string_fast(export_contours, orig_w, orig_h, wt_range)

    base = out_dir / f"iter_{int(iter_num):03d}"
    svg_path, png_path, stats_path = (base.with_suffix(".svg"),
                                      base.with_suffix(".png"),
                                      base.with_suffix(".stats.json"))
    svg_path.write_text(svg)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True))
    subprocess.run(["rsvg-convert", "-w", str(png_width), str(svg_path),
                    "-o", str(png_path)], check=True)
    return svg_path, png_path, stats_path, stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("iter", help="iteration number (used to name artifacts)")
    p.add_argument("--method", default="wave", choices=METHODS)
    p.add_argument("--levels", type=int, default=111)
    p.add_argument("--smooth", type=float, default=0.0)
    p.add_argument("--lum-mix", type=float, default=0.8)
    p.add_argument("--wt-range", type=float, default=0.0)
    p.add_argument("--seed-x", type=int, default=None)
    p.add_argument("--seed-y", type=int, default=None)
    p.add_argument("--input", type=Path,
                   default=REPO / "examples" / "woman" / "woman-source.jpeg")
    p.add_argument("--png-width", type=int, default=780)
    p.add_argument("--out-dir", type=Path, default=REPO / "loop" / "output")
    a = p.parse_args()

    if not Path(a.input).exists():
        sys.stderr.write(f"[render] input not found: {a.input}\n")
        return 1

    svg_path, png_path, stats_path, stats = render(
        a.iter, method=a.method, levels=a.levels, smooth=a.smooth,
        lum_mix=a.lum_mix, wt_range=a.wt_range, seed_x=a.seed_x, seed_y=a.seed_y,
        input_path=a.input, png_width=a.png_width, out_dir=a.out_dir)

    print(f"[render] stats: method={stats.get('method')} paths={stats.get('paths')} "
          f"total_points={stats.get('total_points')} levels={stats.get('levels')} "
          f"grid={stats.get('grid')} t=[{stats.get('t_min')},{stats.get('t_max')}]")
    print(f"[render] wrote {svg_path}, {png_path}, {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
