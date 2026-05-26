"""
Scalar field construction for WAVEFRONT.

The core insight: treat image brightness as elevation warping a
Manhattan-distance field. Luminance is adaptively blurred by distance from
the seed so face detail stays legible while far-field texture is suppressed.
"""

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter


MAX_DIM = 640  # Maximum dimension for processing grid


def load_and_preprocess(image_file, max_dim=MAX_DIM):
    """
    Load image from file object and resize for processing while preserving aspect ratio.

    Args:
        image_file: file-like object (from Flask request.files)
        max_dim: maximum dimension (width or height) for the processing grid

    Returns:
        rgb_array: numpy array shape (H, W, 3), dtype uint8
        original_size: (width, height) tuple from the uploaded image
        processed_size: (width, height) tuple used for field computation
    """
    img = Image.open(image_file).convert('RGB')
    original_size = img.size
    w, h = original_size

    if max(w, h) > max_dim:
        if w >= h:
            new_w = max_dim
            new_h = int(h * max_dim / w)
        else:
            new_h = max_dim
            new_w = int(w * max_dim / h)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    return np.array(img), original_size, img.size


def to_luminance(rgb_array):
    """
    Convert RGB array to luminance using ITU-R BT.601 coefficients.
    Matches browser canvas getImageData luminance behavior.

    Returns: float32 array shape (H, W), values 0.0–255.0
    """
    r = rgb_array[:, :, 0].astype(np.float32)
    g = rgb_array[:, :, 1].astype(np.float32)
    b = rgb_array[:, :, 2].astype(np.float32)
    return 0.299 * r + 0.587 * g + 0.114 * b


def build_field(luminance, seed_x, seed_y, lum_mix=1.0):
    """
    Build the scalar field used for isoline extraction.

    field[y,x] = abs(x - seed_x) + abs(y - seed_y)
                 + (255 - blurred_luminance[y,x]) * effective_lum_mix[y,x]

    The Manhattan distance term creates concentric diamond rings from the
    seed point. The luminance term distorts those rings to follow image topology:
    - Dark areas (lum→0): contribute up to 255*lum_mix → tight rings
    - Bright areas (lum→255): contribute 0 → smooth parallel bands
    - Far from the seed, the luminance map is more heavily blurred and mixed
      with lower strength so background texture does not collapse into loops.

    Args:
        luminance: float32 array (H, W), values 0–255
        seed_x: seed x coordinate (column index)
        seed_y: seed y coordinate (row index)
        lum_mix: luminance modulation strength, default 1.0

    Returns:
        field: float32 array (H, W)
        field_min: float
        field_max: float
    """
    H, W = luminance.shape

    # Adaptive blur: pixels near the seed point (face) get light blur (σ=8, preserves
    # facial feature wrapping detail); pixels far from seed (hair, background) get heavy
    # blur (σ=30, suppresses texture noise so iso-levels become open flowing bands).
    # Brightness-based blending fails because hair/plants are also dark (same as face).
    lum_light = gaussian_filter(luminance, sigma=8)
    lum_heavy = gaussian_filter(luminance, sigma=30)
    xs = np.arange(W, dtype=np.float32)
    ys = np.arange(H, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    dist_to_seed = np.sqrt((xx - seed_x) ** 2 + (yy - seed_y) ** 2)
    # Sharp spatial transition: face zone (within inner_r) gets σ=12, background (beyond
    # outer_r) gets σ=30, with linear blend in between. Keeps hair/plants on full heavy blur.
    inner_r = 0.20 * min(W, H)  # ~128px at 640px: covers full face feature zone
    outer_r = 0.35 * min(W, H)  # ~224px at 640px: hair/plants beyond this get σ=30
    dist_weight = np.clip((dist_to_seed - inner_r) / (outer_r - inner_r), 0.0, 1.0).astype(np.float32)
    luminance = (1.0 - dist_weight) * lum_light + dist_weight * lum_heavy

    dist_field = np.abs(xx - seed_x) + np.abs(yy - seed_y)
    # Reduce luminance contribution far from seed so background iso-levels stay open/flowing
    # rather than closing into loops around hair/plant texture features. Near seed: full
    # lum_mix preserves face wrapping detail. Far background: 0.20× makes field ≈ radial.
    effective_lum_mix = lum_mix * ((1.0 - dist_weight) * 1.0 + dist_weight * 0.70)
    lum_field = (255.0 - luminance) * effective_lum_mix

    field = dist_field + lum_field

    return field, float(field.min()), float(field.max())
