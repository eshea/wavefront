import io
import unittest
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from PIL import Image

from app import app
from engine.contour import scale_contours
from engine.field import MAX_DIM, load_and_preprocess
from engine.march import PARAM_BOUNDS, suggest_params
from engine.compose import compose_canvas, parse_aspect
from engine.color import assign_layers, default_palette, DEFAULT_PALETTE
from engine.export import (contours_to_svg_string_fast, contours_to_svg_layered)


ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / 'examples' / 'contour_woman.webp'


def image_bytes(size=(32, 24), color=(128, 96, 64), fmt='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format=fmt)
    buf.seek(0)
    return buf


def expected_processed_size(size, max_dim=MAX_DIM):  # track the live engine cap, not a frozen 640
    w, h = size
    if max(w, h) <= max_dim:
        return size
    if w >= h:
        return max_dim, int(h * max_dim / w)
    return int(w * max_dim / h), max_dim


class PreprocessTests(unittest.TestCase):
    def test_preprocess_returns_original_and_processed_dimensions_below_cap(self):
        rgb, original_size, processed_size = load_and_preprocess(
            image_bytes(size=(320, 200)),
            max_dim=640,
        )

        self.assertEqual(original_size, (320, 200))
        self.assertEqual(processed_size, (320, 200))
        self.assertEqual(rgb.shape, (200, 320, 3))

    def test_preprocess_returns_original_and_processed_dimensions_above_cap(self):
        rgb, original_size, processed_size = load_and_preprocess(
            image_bytes(size=(1000, 500)),
            max_dim=640,
        )

        self.assertEqual(original_size, (1000, 500))
        self.assertEqual(processed_size, (640, 320))
        self.assertEqual(rgb.shape, (320, 640, 3))


class GeometryTests(unittest.TestCase):
    def test_scale_contours_maps_processed_points_to_original_space(self):
        contours = [{
            'points': np.array([[0, 0], [320, 640]], dtype=np.float32),
            'threshold': 1.0,
            'normalized_t': 0.5,
        }]

        scaled = scale_contours(contours, from_size=(640, 320), to_size=(1000, 500))

        np.testing.assert_allclose(
            scaled[0]['points'],
            np.array([[0, 0], [500, 1000]], dtype=np.float32),
        )
        np.testing.assert_allclose(
            contours[0]['points'],
            np.array([[0, 0], [320, 640]], dtype=np.float32),
        )


class ProcessEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def post_example(self, **fields):
        with EXAMPLE.open('rb') as f:
            data = {'image': (f, EXAMPLE.name)}
            data.update(fields)
            return self.client.post('/process', data=data, content_type='multipart/form-data')

    def post_tiny(self, **fields):
        data = {'image': (image_bytes(), 'tiny.png')}
        data.update(fields)
        return self.client.post('/process', data=data, content_type='multipart/form-data')

    def test_process_exports_svg_at_original_dimensions_and_reports_processing_grid(self):
        with Image.open(EXAMPLE) as img:
            original_size = img.size
        processed_size = expected_processed_size(original_size)

        response = self.post_example()

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        root = ElementTree.fromstring(payload['svg'])

        self.assertEqual(payload['img_width'], original_size[0])
        self.assertEqual(payload['img_height'], original_size[1])
        self.assertEqual(payload['processing_width'], processed_size[0])
        self.assertEqual(payload['processing_height'], processed_size[1])
        self.assertEqual(root.attrib['width'], str(original_size[0]))
        self.assertEqual(root.attrib['height'], str(original_size[1]))
        self.assertEqual(root.attrib['viewBox'], f'0 0 {original_size[0]} {original_size[1]}')
        self.assertEqual(payload['stats']['grid'], f'{processed_size[0]}x{processed_size[1]}')
        self.assertEqual(
            payload['stats']['segments'],
            max(payload['stats']['total_points'] - payload['stats']['paths'], 0),
        )

    def test_malformed_numeric_form_values_return_400(self):
        bad_values = {
            'levels': 'not-an-int',
            'smooth': 'not-a-float',
            'lum_mix': 'nan',
            'wt_range': 'inf',
            'seed_x': '',
            'seed_y': '1.25',
        }

        for name, value in bad_values.items():
            with self.subTest(name=name):
                response = self.post_tiny(**{name: value})
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertIn(name, response.get_json()['error'])

    def test_missing_empty_and_corrupt_images_return_400(self):
        no_image = self.client.post('/process', data={}, content_type='multipart/form-data')
        self.assertEqual(no_image.status_code, 400)

        empty_image = self.client.post(
            '/process',
            data={'image': (io.BytesIO(b''), 'empty.png')},
            content_type='multipart/form-data',
        )
        self.assertEqual(empty_image.status_code, 400)
        self.assertIn('image', empty_image.get_json()['error'].lower())

        corrupt_image = self.client.post(
            '/process',
            data={'image': (io.BytesIO(b'not an image'), 'corrupt.png')},
            content_type='multipart/form-data',
        )
        self.assertEqual(corrupt_image.status_code, 400)
        self.assertIn('image', corrupt_image.get_json()['error'].lower())


class SuggestParamsTests(unittest.TestCase):
    def _assert_within_bounds(self, suggestion):
        for name, (lo, hi) in PARAM_BOUNDS.items():
            if name in suggestion:
                self.assertGreaterEqual(suggestion[name], lo)
                self.assertLessEqual(suggestion[name], hi)
        self.assertGreaterEqual(suggestion['levels'], 60)
        self.assertLessEqual(suggestion['levels'], 150)
        self.assertIsInstance(suggestion['levels'], int)

    def test_suggest_params_stays_within_bounds_for_extremes(self):
        for gray in (np.zeros((40, 40), dtype=np.float32),     # all black
                     np.ones((40, 40), dtype=np.float32),       # all white
                     np.full((40, 40), 0.5, dtype=np.float32)): # flat mid-grey
            with self.subTest(mean=float(gray.mean())):
                self._assert_within_bounds(suggest_params(gray))

    def test_suggest_params_on_real_sample_image(self):
        with EXAMPLE.open('rb') as f:
            rgb, _, _ = load_and_preprocess(f)
        gray = rgb.mean(axis=2).astype(np.float32) / 255.0
        self._assert_within_bounds(suggest_params(gray))

    def test_darker_image_gets_higher_floor(self):
        bright = np.full((40, 40), 0.9, dtype=np.float32)
        dark = np.full((40, 40), 0.05, dtype=np.float32)
        self.assertGreater(
            suggest_params(dark)['MARCH_FLOOR'],
            suggest_params(bright)['MARCH_FLOOR'],
        )


class AutotuneEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_autotune_returns_levels_and_in_bounds_knobs(self):
        data = {'image': (image_bytes(size=(64, 48)), 'tiny.png')}
        response = self.client.post('/autotune', data=data,
                                    content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertIn('levels', payload)
        self.assertIn('knobs', payload)
        self.assertGreaterEqual(payload['levels'], 60)
        self.assertLessEqual(payload['levels'], 150)
        for name, value in payload['knobs'].items():
            lo, hi = PARAM_BOUNDS[name]
            self.assertGreaterEqual(value, lo)
            self.assertLessEqual(value, hi)

    def test_autotune_missing_image_returns_400(self):
        response = self.client.post('/autotune', data={},
                                    content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)


def _contour(points, normalized_t=0.5, layer=None):
    c = {'points': np.asarray(points, dtype=np.float32),
         'threshold': 1.0, 'normalized_t': normalized_t}
    if layer is not None:
        c['layer'] = layer
    return c


class ParseAspectTests(unittest.TestCase):
    def test_blank_and_none_mean_source_aspect(self):
        self.assertIsNone(parse_aspect(None))
        self.assertIsNone(parse_aspect(''))
        self.assertIsNone(parse_aspect('   '))

    def test_ratio_forms(self):
        self.assertAlmostEqual(parse_aspect('2:1'), 2.0)
        self.assertAlmostEqual(parse_aspect('7:3.5'), 2.0)
        self.assertAlmostEqual(parse_aspect('84x42'), 2.0)
        self.assertAlmostEqual(parse_aspect('3,2'), 1.5)
        self.assertAlmostEqual(parse_aspect('1.85'), 1.85)

    def test_malformed_and_nonpositive_raise(self):
        for bad in ('abc', '0:1', '2:0', '-2:1', 'nan:1'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_aspect(bad)


class ComposeCanvasTests(unittest.TestCase):
    def setUp(self):
        # Portrait subject (W=60, H=100), distinct mid value so margins stand out.
        self.lum = np.full((100, 60), 120.0, dtype=np.float32)

    def test_contain_widens_to_aspect_and_centers_subject(self):
        canvas, (cw, ch), seed, rect = compose_canvas(self.lum, 2.0, fit='contain',
                                                       margin_fill='light')
        self.assertEqual((cw, ch), (200, 100))
        self.assertAlmostEqual(cw / ch, 2.0)
        self.assertEqual(rect, {'x': 70, 'y': 0, 'w': 60, 'h': 100})
        # Default seed centers on the canvas.
        self.assertEqual(seed, (100, 50))
        # Margin filled light (255); subject region keeps its value.
        self.assertEqual(canvas[50, 0], 255.0)
        self.assertEqual(canvas[50, 100], 120.0)

    def test_contain_remaps_explicit_seed_into_canvas(self):
        _, _, seed, _ = compose_canvas(self.lum, 2.0, seed=(10, 20), fit='contain')
        self.assertEqual(seed, (80, 20))   # x shifted by the left margin (70)

    def test_margin_fill_values(self):
        for fill, col0 in (('light', 255.0), ('dark', 0.0), ('mean', 120.0)):
            with self.subTest(fill=fill):
                canvas, _, _, _ = compose_canvas(self.lum, 2.0, margin_fill=fill)
                self.assertEqual(canvas[50, 0], col0)

    def test_cover_crops_to_aspect_without_margins(self):
        canvas, (cw, ch), _, rect = compose_canvas(self.lum, 2.0, fit='cover')
        self.assertEqual((cw, ch), (60, 30))
        self.assertAlmostEqual(cw / ch, 2.0)
        self.assertEqual(rect, {'x': 0, 'y': 0, 'w': 60, 'h': 30})
        self.assertEqual(canvas.shape, (30, 60))


class AssignLayersTests(unittest.TestCase):
    def test_depth_bands_by_normalized_t(self):
        cs = [_contour([[0, 0]], normalized_t=0.1),
              _contour([[0, 0]], normalized_t=0.9)]
        assign_layers(cs, 3, mode='depth')
        self.assertEqual([c['layer'] for c in cs], [0, 2])

    def test_tone_bands_dark_to_layer_zero(self):
        gray = np.zeros((10, 10), dtype=np.float32)
        gray[:, 5:] = 1.0                      # left dark, right light
        dark = _contour([[5, 1], [5, 2]])
        light = _contour([[5, 7], [5, 8]])
        assign_layers([dark, light], 2, mode='tone', gray=gray)
        self.assertEqual(dark['layer'], 0)
        self.assertEqual(light['layer'], 1)

    def test_single_color_all_layer_zero(self):
        cs = [_contour([[0, 0]], normalized_t=0.9)]
        assign_layers(cs, 1, mode='depth')
        self.assertEqual(cs[0]['layer'], 0)

    def test_default_palette_length(self):
        self.assertEqual(len(default_palette(3)), 3)
        self.assertEqual(default_palette(99), DEFAULT_PALETTE)


class LayeredExportTests(unittest.TestCase):
    def test_layered_emits_one_inkscape_layer_per_color(self):
        cs = [_contour([[0, 0], [1, 1]], layer=0),
              _contour([[2, 2], [3, 3]], layer=1)]
        svg = contours_to_svg_layered(cs, 10, 10, ['#111111', '#dddddd'])
        root = ElementTree.fromstring(svg)
        ink = '{http://www.inkscape.org/namespaces/inkscape}'
        layers = [g for g in root.iter('{http://www.w3.org/2000/svg}g')
                  if g.attrib.get(ink + 'groupmode') == 'layer']
        self.assertEqual(len(layers), 2)
        self.assertEqual({g.attrib['stroke'] for g in layers},
                         {'#111111', '#dddddd'})

    def test_physical_units_on_both_writers(self):
        cs = [_contour([[0, 0], [1, 1]], layer=0)]
        phys = {'w': 84, 'h': 42, 'units': 'in'}
        for svg in (contours_to_svg_string_fast(cs, 200, 100, phys=phys),
                    contours_to_svg_layered(cs, 200, 100, ['#000'], phys=phys)):
            root = ElementTree.fromstring(svg)
            self.assertEqual(root.attrib['width'], '84in')
            self.assertEqual(root.attrib['height'], '42in')
            self.assertEqual(root.attrib['viewBox'], '0 0 200 100')

    def test_default_fast_header_is_byte_stable(self):
        # The CORE single-ink path must not drift when phys is absent.
        cs = [_contour([[0, 0], [1, 1]])]
        svg = contours_to_svg_string_fast(cs, 320, 240)
        self.assertTrue(svg.startswith(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="320" height="240" viewBox="0 0 320 240">'))


class MuralEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def _post(self, **fields):
        data = {'image': (image_bytes(size=(120, 160)), 'tiny.png')}
        data.update(fields)
        return self.client.post('/process', data=data,
                                content_type='multipart/form-data')

    def test_defaults_unchanged_core_regression(self):
        payload = self._post().get_json()
        self.assertIsNone(payload['subject_rect'])
        self.assertEqual(payload['color_mode'], 'off')
        self.assertIsNone(payload['palette'])
        root = ElementTree.fromstring(payload['svg'])
        # No physical units, no inkscape layers on the default path.
        self.assertEqual(root.attrib['width'], str(payload['img_width']))
        self.assertNotIn('inkscape', payload['svg'])

    def test_wide_canvas_widens_output_and_reports_subject_rect(self):
        payload = self._post(canvas_aspect='2:1', margin_fill='light').get_json()
        self.assertAlmostEqual(payload['img_width'] / payload['img_height'], 2.0,
                               delta=0.02)
        self.assertIsNotNone(payload['subject_rect'])
        self.assertEqual(payload['subject_rect']['w'], 120)

    def test_color_mode_emits_layers_and_palette(self):
        payload = self._post(color_mode='depth', n_colors='4').get_json()
        self.assertEqual(payload['color_mode'], 'depth')
        self.assertEqual(len(payload['palette']), 4)
        self.assertIn('inkscape:groupmode', payload['svg'])

    def test_physical_size_in_export(self):
        payload = self._post(phys_width='84', phys_height='42',
                             phys_units='in').get_json()
        root = ElementTree.fromstring(payload['svg'])
        self.assertEqual(root.attrib['width'], '84in')

    def test_bad_canvas_aspect_returns_400(self):
        resp = self._post(canvas_aspect='not-an-aspect')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('canvas_aspect', resp.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
