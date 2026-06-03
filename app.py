"""
WAVEFRONT — Topographic Contour Portrait Engine
Flask web application entry point.
"""

import io
import os
import base64
import math
import traceback

from flask import Flask, render_template, request, jsonify
from PIL import Image, UnidentifiedImageError

from engine.field import (load_and_preprocess, to_luminance, build_field,
                          build_wave_field, WAVE_DIAMOND)
from engine.contour import extract_contours, scale_contours
from engine.smooth import smooth_contours
from engine.export import contours_to_svg_string_fast
from engine.flow import trace_flow_lines
from engine.march import build_march_field

METHODS = ('contour', 'wave', 'flow', 'march')  # contour = classic isolines (default)

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
        diamond = _parse_float_param('diamond', WAVE_DIAMOND, 0.0, 1.0)  # wave only

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

        # Field-construction method:
        #   contour (default) — additive Manhattan+luminance field, marching squares
        #   wave              — eikonal travel-time field (Approach 2), marching squares
        #   flow              — gradient streamlines (Approach 3), traced directly
        if method == 'flow':
            contours, stats = trace_flow_lines(luminance, sx, sy, levels, lum_mix)
        else:
            if method == 'wave':
                field, f_min, f_max = build_wave_field(luminance, sx, sy, lum_mix, diamond)
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
