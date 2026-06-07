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
from engine.smooth import smooth_contours
from engine.export import contours_to_svg_string_fast
from engine.flow import trace_flow_lines
from engine.march import build_march_field

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
    'march': [
        ('march_base',     em, 'MARCH_BASE',     0.2, 10.0),
        ('march_tone',     em, 'MARCH_TONE',     0.0, 6.0),
        ('march_edge',     em, 'MARCH_EDGE',     0.0, 6.0),
        ('march_gamma',    em, 'MARCH_GAMMA',    0.4, 2.5),
        ('march_contrast', em, 'MARCH_CONTRAST', 0.5, 2.5),
        ('march_blur',     em, 'MARCH_BLUR',     0.0, 6.0),
        _THRESH,
    ],
    'flow': [
        ('flow_angle',        efl, 'FLOW_ANGLE',        0.0, 90.0),
        ('flow_carrier',      efl, 'FLOW_CARRIER',      0.0, 1.0),
        ('flow_carrier_mag',  efl, 'FLOW_CARRIER_MAG',  1.0, 20.0),
        ('flow_tone_density', efl, 'FLOW_TONE_DENSITY', 0.0, 1.0),
        ('flow_sigma',        efl, 'FLOW_SIGMA',        1.0, 12.0),
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
        levels = _parse_int_param('levels', 63, 10, 150)
        smooth = _parse_float_param('smooth', 0.7, 0.0, 1.0)
        lum_mix = _parse_float_param('lum_mix', 1.0, 0.0, 2.0)
        wt_range = _parse_float_param('wt_range', 0.6, 0.0, 1.0)
        seed_x = _parse_optional_int_param('seed_x')
        seed_y = _parse_optional_int_param('seed_y')
        method = request.form.get('method', 'contour').strip().lower()
        if method not in METHODS:
            method = 'contour'

        try:
            rgb_array, original_size, processed_size = load_and_preprocess(image_file)
        except (UnidentifiedImageError, OSError) as exc:
            raise RequestValidationError('Invalid or corrupt image data') from exc

        orig_w, orig_h = original_size
        img_w, img_h = processed_size
        luminance = to_luminance(rgb_array)

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
            if method == 'flow':
                contours, stats = trace_flow_lines(luminance, sx, sy, levels, lum_mix)
            else:
                if method == 'wave':
                    field, f_min, f_max = build_wave_field(luminance, sx, sy, lum_mix)
                elif method == 'march':
                    field, f_min, f_max = build_march_field(luminance, sx, sy, lum_mix)
                else:
                    field, f_min, f_max = build_field(luminance, sx, sy, lum_mix)
                contours, stats = extract_contours(field, levels, f_min, f_max)
        stats['method'] = method

        contours = smooth_contours(contours, smooth)

        total_pts = sum(len(c['points']) for c in contours)
        stats['total_points'] = total_pts
        stats['segments'] = max(total_pts - stats['paths'], 0)

        export_contours = scale_contours(contours, processed_size, original_size)
        svg_string = contours_to_svg_string_fast(export_contours, orig_w, orig_h, wt_range)

        return jsonify({
            'svg': svg_string,
            'stats': stats,
            'img_width': orig_w,
            'img_height': orig_h,
            'processing_width': img_w,
            'processing_height': img_h,
            'seed_x': sx,
            'seed_y': sy
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5055))
    host = os.environ.get('HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes', 'on'}
    print('\n  WAVEFRONT — Topographic Contour Engine')
    print(f'  http://{host}:{port}\n')
    app.run(debug=debug, host=host, port=port)
