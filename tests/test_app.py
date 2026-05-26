import io
import unittest
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from PIL import Image

from app import app
from engine.contour import scale_contours
from engine.field import load_and_preprocess


ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / 'examples' / 'contour_woman.webp'


def image_bytes(size=(32, 24), color=(128, 96, 64), fmt='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format=fmt)
    buf.seek(0)
    return buf


def expected_processed_size(size, max_dim=640):
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


if __name__ == '__main__':
    unittest.main()
