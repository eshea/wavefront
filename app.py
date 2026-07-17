"""
WAVEFRONT — Topographic Contour Portrait Engine
Flask web application entry point.
"""

import io
import os
import math
import base64
import traceback
import contextlib

from flask import Flask, render_template, request, jsonify
from PIL import Image, UnidentifiedImageError

import engine.field as ef
import engine.contour as ec
import engine.flow as efl
import engine.march as em
from engine.field import load_and_preprocess, to_luminance, build_field, build_wave_field
from engine.contour import extract_contours, scale_contours
from engine.smooth import resample_contours, smooth_contours, decimate_contours
from engine.export import (contours_to_svg_string_fast, contours_to_svg_layered,
                           UNITS_TO_MM)
from engine.flow import trace_flow_lines
from engine.march import build_march_field
from engine.compose import (compose_canvas, compose_rgb_canvas, parse_aspect,
                            MARGIN_FILLS)
from engine.color import (assign_layers, default_palette, separate_channels,
                          cmyk_palette)
from engine.crosshatch import crosshatch_pass
from engine.optimize import optimize_contours

METHODS = ('contour', 'wave', 'flow', 'march')  # contour = classic isolines (default)

# Per-method tuning knobs exposed to the UI. Each entry:
#   (form_field, module, ATTR, min, max)
# The engine reads these as module-level constants, so we temporarily override the
# constants for the duration of a request (see _apply_knobs) — no engine signature
# churn, and it mirrors exactly what the ralph loop tunes. THRESHOLD_POWER (level
# spacing) applies to every isoline method (contour/wave/march) but not flow.
_THRESH = ('threshold_power', ec, 'THRESHOLD_POWER', 0.6, 3.0)
# Shared tonal pre-shaping (CONTOUR-V STUDIO "Input & Tonal Control"). Identity at
# defaults; shapes which tones get contour density. Applies to wave + contour.
_TONE = [
    ('tone_gamma',    ef, 'TONE_GAMMA',    0.4, 2.5),
    ('tone_contrast', ef, 'TONE_CONTRAST', 0.5, 2.5),
    ('tone_invert',   ef, 'TONE_INVERT',   0.0, 1.0),
]
METHOD_KNOBS = {
    'contour': [
        ('field_denoise_sigma', ef, 'FIELD_DENOISE_SIGMA', 0.0, 25.0),
        ('field_shadow_lift',   ef, 'FIELD_SHADOW_LIFT',   0.0, 150.0),
        *_TONE,
        _THRESH,
    ],
    'wave': [
        ('wave_diamond',     ef, 'WAVE_DIAMOND',     0.0, 1.0),
        ('wave_relief',      ef, 'WAVE_RELIEF',      0.0, 6.0),
        ('wave_far',         ef, 'WAVE_FAR',         0.0, 1.0),
        ('wave_sigma_face',  ef, 'WAVE_SIGMA_FACE',  2.0, 20.0),
        ('wave_sigma_bg',    ef, 'WAVE_SIGMA_BG',    5.0, 50.0),
        ('wave_inner',       ef, 'WAVE_INNER',       0.0, 0.5),
        ('wave_outer',       ef, 'WAVE_OUTER',       0.3, 1.3),
        *_TONE,
        _THRESH,
    ],
    # march knobs + ranges come straight from engine.march.PARAM_BOUNDS — single
    # source of truth, so the UI sliders match the optimizer's search/clamp box and
    # the tuned march_params.json defaults render without being
    # silently clamped by a stale UI range.
    'march': [(name.lower(), em, name, lo, hi)
              for name, (lo, hi) in em.PARAM_BOUNDS.items()] + [_THRESH],
    'flow': [
        ('flow_angle',        efl, 'FLOW_ANGLE',        0.0, 90.0),
        ('flow_carrier',      efl, 'FLOW_CARRIER',      0.0, 1.0),
        ('flow_carrier_mag',  efl, 'FLOW_CARRIER_MAG',  1.0, 20.0),
        ('flow_tone_density', efl, 'FLOW_TONE_DENSITY', 0.0, 1.0),
        ('flow_sigma',        efl, 'FLOW_SIGMA',        1.0, 12.0),
        # Edge-Tangent-Flow coherence smoothing (Kang et al.); 0 = off (default).
        ('flow_etf',          efl, 'FLOW_ETF',          0.0, 1.0),
        ('flow_etf_radius',   efl, 'FLOW_ETF_RADIUS',   1.0, 8.0),
        ('flow_etf_iters',    efl, 'FLOW_ETF_ITERS',    0.0, 4.0),
    ],
}


@contextlib.contextmanager
def _apply_knobs(method):
    """Temporarily override the active method's engine constants from request form
    values (clamped to each knob's range), restoring them afterward. Keeps the
    engine's module-global tuning surface intact while letting the UI drive it."""
    saved = []
    try:
        for field, module, attr, lo, hi in METHOD_KNOBS.get(method, ()):
            raw = request.form.get(field)
            if raw is None or raw.strip() == '':
                continue
            try:
                val = float(raw)
            except ValueError as exc:
                raise RequestValidationError(f'{field} must be a number') from exc
            if not math.isfinite(val):
                raise RequestValidationError(f'{field} must be finite')
            val = max(lo, min(hi, val))
            saved.append((module, attr, getattr(module, attr)))
            setattr(module, attr, val)
        yield
    finally:
        for module, attr, prev in reversed(saved):
            setattr(module, attr, prev)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max upload

# Largest processing grid (width*height, px) a single render may attempt. The
# march field is one global geodesic solve that cannot be tiled, so peak memory
# (cost + meshgrid + MCP scratch) scales with grid area; this guard returns a
# clean 400 instead of letting a big DETAIL × wide-canvas combination OOM the
# host. Default sized for a modest homelab box (~4000² square); override via env.
MAX_GRID_PX = int(os.environ.get('MAX_GRID_PX', 16_000_000))


class RequestValidationError(ValueError):
    """Raised for client-correctable form input errors."""


def _parse_int_param(name, default, min_value, max_value):
    raw = request.form.get(name)
    if raw is None:
        value = default
    else:
        raw = raw.strip()
        if raw == '':
            raise RequestValidationError(f'{name} must be an integer')
        try:
            value = int(raw)
        except ValueError as exc:
            raise RequestValidationError(f'{name} must be an integer') from exc

    return max(min_value, min(max_value, value))


def _parse_float_param(name, default, min_value, max_value):
    raw = request.form.get(name)
    if raw is None:
        value = default
    else:
        raw = raw.strip()
        if raw == '':
            raise RequestValidationError(f'{name} must be a number')
        try:
            value = float(raw)
        except ValueError as exc:
            raise RequestValidationError(f'{name} must be a number') from exc
        if not math.isfinite(value):
            raise RequestValidationError(f'{name} must be a finite number')

    return max(min_value, min(max_value, value))


def _parse_optional_int_param(name):
    raw = request.form.get(name)
    if raw is None:
        return None

    raw = raw.strip()
    if raw == '':
        raise RequestValidationError(f'{name} must be an integer')
    try:
        return int(raw)
    except ValueError as exc:
        raise RequestValidationError(f'{name} must be an integer') from exc


def _parse_optional_float_param(name, min_value=None):
    """Parse an optional positive-ish float form field. None when absent; raises
    RequestValidationError on a present-but-malformed value."""
    raw = request.form.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if raw == '':
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise RequestValidationError(f'{name} must be a number') from exc
    if not math.isfinite(value):
        raise RequestValidationError(f'{name} must be a finite number')
    if min_value is not None and value < min_value:
        raise RequestValidationError(f'{name} must be >= {min_value}')
    return value


def _parse_palette(raw, n_colors):
    """Comma/space-separated CSS colors -> list. Falls back to the default ramp.
    Pads to n_colors by repeating the default so a layer always has a color."""
    colors = []
    if raw:
        for tok in raw.replace(' ', ',').split(','):
            tok = tok.strip()
            if tok:
                colors.append(tok if tok.startswith('#') else f'#{tok}')
    base = default_palette(n_colors)
    if not colors:
        return base
    # Keep user colors; backfill any shortfall from the default ramp.
    for i in range(len(colors), n_colors):
        colors.append(base[i % len(base)])
    return colors[:n_colors]


def _parse_angles(raw):
    """Comma/space-separated per-layer screen angles (degrees) -> list, or None to
    use the default SCREEN_ANGLES."""
    if not raw:
        return None
    vals = []
    for tok in raw.replace(' ', ',').split(','):
        tok = tok.strip()
        if tok:
            try:
                vals.append(float(tok))
            except ValueError as exc:
                raise RequestValidationError('sep_angles must be numbers') from exc
    return vals or None


def _required_image_file():
    if 'image' not in request.files:
        raise RequestValidationError('No image provided')

    image_file = request.files['image']
    if image_file.filename == '':
        raise RequestValidationError('No image provided')

    return image_file


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True})


@app.route('/config')
def config():
    """Knob registry for the UI — one source of truth so the sliders always match
    the backend. Each knob: field name, range, and the engine's current default."""
    knobs = {
        method: [
            {'field': field, 'min': lo, 'max': hi, 'default': float(getattr(module, attr))}
            for field, module, attr, lo, hi in specs
        ]
        for method, specs in METHOD_KNOBS.items()
    }
    return jsonify({'methods': list(METHODS), 'knobs': knobs})


@app.route('/process', methods=['POST'])
def process():
    """
    Main processing endpoint.

    Accepts multipart form data with:
        image: file upload
        levels: int (10–150)
        smooth: float (0–1)
        lum_mix: float (0–2)
        wt_range: float (0–1)
        seed_x: int (pixel x coordinate)
        seed_y: int (pixel y coordinate)

    Returns JSON:
        svg: string — complete SVG document
        stats: dict — paths, points, levels, t_min, t_max, grid
        img_width/img_height: original uploaded image dimensions
        processing_width/processing_height: capped dimensions used for computation
        seed_x/seed_y: processing-grid seed coordinates
    """
    try:
        image_file = _required_image_file()
        levels = _parse_int_param('levels', 111, 10, 150)
        smooth = _parse_float_param('smooth', 0.0, 0.0, 1.0)
        lum_mix = _parse_float_param('lum_mix', 0.8, 0.0, 2.0)
        wt_range = _parse_float_param('wt_range', 0.0, 0.0, 1.0)
        seed_x = _parse_optional_int_param('seed_x')
        seed_y = _parse_optional_int_param('seed_y')
        method = request.form.get('method', 'march').strip().lower()
        if method not in METHODS:
            method = 'march'

        # --- mural extensions (all opt-in; absent => CORE behavior) ---
        # Upper bound is the measured practical ceiling for one geodesic solve
        # (~10s / ~1.4GB at 4000px); MAX_GRID_PX still backstops wide canvases.
        detail_px = _parse_int_param('detail_px', ef.MAX_DIM, 400, 4000)
        canvas_fit = (request.form.get('canvas_fit') or 'contain').strip().lower()
        if canvas_fit not in ('contain', 'cover'):
            canvas_fit = 'contain'
        margin_fill = (request.form.get('margin_fill') or 'light').strip().lower()
        if margin_fill not in MARGIN_FILLS:
            margin_fill = 'light'
        try:
            canvas_aspect = parse_aspect(request.form.get('canvas_aspect'))
        except ValueError as exc:
            raise RequestValidationError('canvas_aspect must look like "2:1"') from exc
        color_mode = (request.form.get('color_mode') or 'off').strip().lower()
        if color_mode not in ('off', 'tone', 'depth', 'cmyk', 'lum'):
            color_mode = 'off'
        n_colors = _parse_int_param('n_colors', 2, 1, 6)
        if color_mode == 'cmyk':
            n_colors = 4   # fixed C/M/Y/K channel set
        raw_palette = request.form.get('palette')
        if color_mode == 'cmyk' and not raw_palette:
            palette = cmyk_palette()
        else:
            palette = _parse_palette(raw_palette, n_colors)
        # Channel-separation tuning (cmyk/lum): per-layer screen angles + the
        # channel-presence cutoff. Absent ⇒ default SCREEN_ANGLES / 0.12.
        sep_angles = _parse_angles(request.form.get('sep_angles'))
        sep_threshold = _parse_float_param('sep_threshold', 0.12, 0.0, 1.0)
        phys_w = _parse_optional_float_param('phys_width', min_value=0.0)
        phys_h = _parse_optional_float_param('phys_height', min_value=0.0)
        phys_units = (request.form.get('phys_units') or 'in').strip().lower()
        if phys_units not in ('in', 'mm', 'cm'):
            phys_units = 'in'
        phys = ({'w': phys_w, 'h': phys_h, 'units': phys_units}
                if (phys_w and phys_h) else None)
        # Plotter pen width (mm) — constant physical stroke, needs phys to resolve.
        pen_mm = _parse_optional_float_param('pen_mm', min_value=0.0)
        # Point-budget simplify tolerance (mm) — RDP decimation for big prints,
        # converted to grid px below once the processing size is known.
        simplify_mm = _parse_optional_float_param('simplify_mm', min_value=0.0)
        # Crosshatch second-direction depth layer (opt-in; off => no extra lines).
        # Adds a rotated diamond pass clipped to dark regions so deep shadows get
        # cross-hatched depth instead of a single direction smearing into a blob.
        crosshatch = (request.form.get('crosshatch') or '').strip().lower() \
            in ('1', 'true', 'on', 'yes')
        hatch_threshold = _parse_float_param('hatch_threshold', 0.0, 0.0, 1.0)
        hatch_levels = _parse_int_param('hatch_levels', 0, 0, 150)
        hatch_angle = _parse_float_param('hatch_angle', 45.0, 0.0, 90.0)
        # Plotter path optimization (opt-in; all default off => byte-stable export).
        # Cut pen lifts (merge), shorten pen-up travel (reorder + 2-opt), drop stubs.
        opt_merge_gap = _parse_float_param('opt_merge_gap', 0.0, 0.0, 10.0)
        opt_min_seg = _parse_float_param('opt_min_seg', 0.0, 0.0, 50.0)
        opt_two_opt = _parse_int_param('opt_two_opt', 0, 0, 10)
        opt_reorder = (request.form.get('opt_reorder') or '').strip().lower() \
            in ('1', 'true', 'on', 'yes')

        try:
            rgb_array, original_size, processed_size = load_and_preprocess(
                image_file, max_dim=detail_px)
        except (UnidentifiedImageError, OSError) as exc:
            raise RequestValidationError('Invalid or corrupt image data') from exc

        luminance = to_luminance(rgb_array)

        # Mural canvas: pad the subject into a wide target aspect; the diamond field
        # fills the margins. Export at the canvas size (vector — phys sets print size).
        subject_rect = None
        if canvas_aspect is not None:
            luminance, processed_size, _, subject_rect = compose_canvas(
                luminance, canvas_aspect, seed=None, fit=canvas_fit,
                margin_fill=margin_fill)
            original_size = processed_size
            # Register RGB to the same canvas so CMYK channel separation stays
            # aligned to the subject (not stretched across the whole frame).
            if color_mode == 'cmyk':
                rgb_array = compose_rgb_canvas(rgb_array, canvas_aspect,
                                               fit=canvas_fit)

        orig_w, orig_h = original_size
        img_w, img_h = processed_size

        # Guard the heavy global geodesic solve: a large DETAIL × wide canvas can
        # allocate gigabytes (cost + meshgrid + MCP scratch all scale with grid
        # area). Reject cleanly instead of OOMing the (single-threaded) server.
        if img_w * img_h > MAX_GRID_PX:
            raise RequestValidationError(
                f'Processing grid {img_w}×{img_h} ({img_w * img_h:,}px) exceeds '
                f'the {MAX_GRID_PX:,}px limit — reduce DETAIL or canvas size '
                f'(or raise MAX_GRID_PX on the server).')

        # Seed lives in processing-grid (canvas) space; default = grid center.
        sx = seed_x if seed_x is not None else img_w // 2
        sy = seed_y if seed_y is not None else img_h // 2
        sx = max(0, min(img_w - 1, sx))
        sy = max(0, min(img_h - 1, sy))

        # Field-construction method (each reads its own module-constant knobs, which
        # _apply_knobs temporarily overrides from the request form):
        #   contour — uniform Manhattan+luminance field, marching squares
        #   wave    — L1-diamond field with luminance relief, marching squares
        #   march   — 4-connected weighted-distance (marching waves), marching squares
        #   flow    — gradient streamlines with a directional carrier, traced directly
        with _apply_knobs(method):
            if color_mode in ('cmyk', 'lum'):
                # Multi-pen channel separation REPLACES the single-field build: each
                # channel/tier gets its own rotated diamond field + pen layer.
                contours = separate_channels(
                    luminance, rgb_array, sx, sy, levels, lum_mix,
                    mode=color_mode, n_colors=n_colors,
                    angles=sep_angles, threshold=sep_threshold)
                stats = {'paths': len(contours), 'levels': levels, 't_min': 0.0,
                         't_max': 0.0, 'grid': f'{img_w}x{img_h}'}
            elif method == 'flow':
                contours, stats = trace_flow_lines(luminance, sx, sy, levels, lum_mix)
            else:
                if method == 'wave':
                    field, f_min, f_max = build_wave_field(luminance, sx, sy, lum_mix)
                elif method == 'march':
                    field, f_min, f_max = build_march_field(luminance, sx, sy, lum_mix)
                else:
                    field, f_min, f_max = build_field(luminance, sx, sy, lum_mix)
                contours, stats = extract_contours(field, levels, f_min, f_max)
                # Fixed-step resample (STUDIO "STEP"): de-jitters raw marching-
                # squares points before smoothing. Flow traces its own step.
                contours = resample_contours(contours)
            # Crosshatch overlay (opt-in): a rotated diamond pass clipped to dark
            # regions, deepening shadows without smearing. Runs inside _apply_knobs
            # so it shares the tone knobs; returns [] when off => contours untouched.
            if crosshatch and hatch_levels > 0:
                hatch = crosshatch_pass(
                    luminance, sx, sy, hatch_levels, lum_mix,
                    threshold=hatch_threshold, angle=hatch_angle)
                # cmyk/lum skip assign_layers, so tag the shadow hatch with the
                # darkest pen (K / darkest tier). tone/depth let assign_layers band
                # it by darkness below; off needs no layer.
                if color_mode == 'cmyk':
                    for c in hatch:
                        c['layer'] = 3
                elif color_mode == 'lum':
                    for c in hatch:
                        c['layer'] = n_colors - 1
                contours = contours + hatch
                stats['paths'] = len(contours)
        stats['method'] = method

        contours = smooth_contours(contours, smooth)

        # Point budget for big prints: RDP-decimate by a physical tolerance,
        # converted to grid px from the print width (needs phys to be meaningful).
        if simplify_mm and phys:
            phys_w_mm = phys['w'] * UNITS_TO_MM.get(phys['units'], 25.4)
            if phys_w_mm > 0:
                contours = decimate_contours(contours, simplify_mm / phys_w_mm * img_w)

        # Color layers (mural color mode): tag each contour with a pen index on the
        # PROCESSING grid (so the tone reference and points share coordinates),
        # before scaling to export space. 'layer' survives scale_contours. cmyk/lum
        # already carry per-channel layers from separate_channels.
        if color_mode in ('tone', 'depth'):
            gray_ref = ((luminance / 255.0).astype('float32')
                        if color_mode == 'tone' else None)
            assign_layers(contours, n_colors, mode=color_mode, gray=gray_ref)

        # Plotter path optimization — runs AFTER layer assignment so merge/reorder
        # stay within each pen's set, and on the processing grid before scaling.
        contours = optimize_contours(
            contours, merge_gap=opt_merge_gap, reorder=opt_reorder,
            two_opt_passes=opt_two_opt, min_seg=opt_min_seg)
        stats['paths'] = len(contours)

        total_pts = sum(len(c['points']) for c in contours)
        stats['total_points'] = total_pts
        stats['segments'] = max(total_pts - stats['paths'], 0)

        export_contours = scale_contours(contours, processed_size, original_size)
        stroke_scale = orig_w / img_w
        if color_mode != 'off':
            svg_string = contours_to_svg_layered(
                export_contours, orig_w, orig_h, palette,
                wt_range=wt_range, stroke_scale=stroke_scale, phys=phys, pen_mm=pen_mm)
        else:
            svg_string = contours_to_svg_string_fast(
                export_contours, orig_w, orig_h, wt_range,
                stroke_scale=stroke_scale, phys=phys, pen_mm=pen_mm)

        # Report only the pens that actually drew ink: a grayscale CMYK source
        # yields only the K layer even though the palette lists four, so the UI
        # shouldn't prompt for pen swaps that never touch the page.
        if color_mode != 'off':
            present = sorted({int(c.get('layer', 0)) for c in contours})
            report_palette = [palette[i % len(palette)] for i in present]
        else:
            report_palette = None

        return jsonify({
            'svg': svg_string,
            'stats': stats,
            'img_width': orig_w,
            'img_height': orig_h,
            'processing_width': img_w,
            'processing_height': img_h,
            'seed_x': sx,
            'seed_y': sy,
            'subject_rect': subject_rect,
            'color_mode': color_mode,
            'palette': report_palette
        })

    except RequestValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/thumbnail', methods=['POST'])
def thumbnail():
    """
    Returns a base64-encoded downscaled version of the uploaded image
    for use as ghost overlay in the preview canvas.

    Accepts: multipart form with 'image' file
    Returns JSON: { data_url: 'data:image/jpeg;base64,...', width: N, height: N }
    """
    try:
        image_file = _required_image_file()
        try:
            rgb_array, _, (w, h) = load_and_preprocess(image_file, max_dim=640)
        except (UnidentifiedImageError, OSError) as exc:
            raise RequestValidationError('Invalid or corrupt image data') from exc

        img = Image.fromarray(rgb_array)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=80)
        buf.seek(0)

        b64 = base64.b64encode(buf.read()).decode('utf-8')
        data_url = f'data:image/jpeg;base64,{b64}'

        return jsonify({'data_url': data_url, 'width': w, 'height': h})

    except RequestValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/autotune', methods=['POST'])
def autotune():
    """
    Image-adaptive knob suggestion for method=march ("AUTO-TUNE" button).

    Analyzes the uploaded image's luminance on the same preprocessed grid the
    engine sees, then returns MARCH_* knobs + levels tuned for THAT image (fast
    heuristic, not the slow black-box optimizer — see engine.march.suggest_params).

    Accepts: multipart form with 'image' file
    Returns JSON: { levels: int, knobs: { MARCH_FLOOR: float, ... } }
    """
    try:
        image_file = _required_image_file()
        try:
            rgb_array, _, _ = load_and_preprocess(image_file)
        except (UnidentifiedImageError, OSError) as exc:
            raise RequestValidationError('Invalid or corrupt image data') from exc

        gray = to_luminance(rgb_array).astype('float32') / 255.0
        suggestion = em.suggest_params(gray)
        levels = suggestion.pop('levels')
        return jsonify({'levels': levels, 'knobs': suggestion})

    except RequestValidationError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5055))
    host = os.environ.get('HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes', 'on'}
    print('\n  WAVEFRONT — Topographic Contour Engine')
    print(f'  http://{host}:{port}\n')
    # threaded=True so a slow large-print render doesn't serialize every other
    # request on the dev server (numpy/skimage release the GIL during the heavy
    # solve). For real mural traffic, front this with gunicorn + a long --timeout.
    app.run(debug=debug, host=host, port=port, threaded=True)
