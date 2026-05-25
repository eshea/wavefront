"""
WAVEFRONT — Topographic Contour Portrait Engine
Flask web application entry point.
"""

import io
import os
import base64
import traceback

from flask import Flask, render_template, request, jsonify
from PIL import Image

from engine.field import load_and_preprocess, to_luminance, build_field
from engine.contour import extract_contours
from engine.smooth import smooth_contours
from engine.export import contours_to_svg_string_fast

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max upload


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
        img_width: int
        img_height: int
        seed_x: int
        seed_y: int
    """
    try:
        levels = int(request.form.get('levels', 63))
        smooth = float(request.form.get('smooth', 0.7))
        lum_mix = float(request.form.get('lum_mix', 1.0))
        wt_range = float(request.form.get('wt_range', 0.6))
        seed_x = request.form.get('seed_x')
        seed_y = request.form.get('seed_y')

        levels = max(5, min(200, levels))
        smooth = max(0.0, min(1.0, smooth))
        lum_mix = max(0.0, min(3.0, lum_mix))
        wt_range = max(0.0, min(1.0, wt_range))

        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400

        image_file = request.files['image']
        if image_file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        rgb_array, (img_w, img_h) = load_and_preprocess(image_file)
        luminance = to_luminance(rgb_array)

        sx = int(seed_x) if seed_x is not None else img_w // 2
        sy = int(seed_y) if seed_y is not None else img_h // 2
        sx = max(0, min(img_w - 1, sx))
        sy = max(0, min(img_h - 1, sy))

        field, f_min, f_max = build_field(luminance, sx, sy, lum_mix)

        contours, stats = extract_contours(field, levels, f_min, f_max)

        contours = smooth_contours(contours, smooth)

        svg_string = contours_to_svg_string_fast(contours, img_w, img_h, wt_range)

        total_pts = sum(len(c['points']) for c in contours)
        stats['total_points'] = total_pts

        return jsonify({
            'svg': svg_string,
            'stats': stats,
            'img_width': img_w,
            'img_height': img_h,
            'seed_x': sx,
            'seed_y': sy
        })

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
        if 'image' not in request.files:
            return jsonify({'error': 'No image'}), 400

        image_file = request.files['image']
        rgb_array, (w, h) = load_and_preprocess(image_file, max_dim=640)

        img = Image.fromarray(rgb_array)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=80)
        buf.seek(0)

        b64 = base64.b64encode(buf.read()).decode('utf-8')
        data_url = f'data:image/jpeg;base64,{b64}'

        return jsonify({'data_url': data_url, 'width': w, 'height': h})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5055))
    print('\n  WAVEFRONT — Topographic Contour Engine')
    print(f'  http://localhost:{port}\n')
    app.run(debug=True, host='0.0.0.0', port=port)
