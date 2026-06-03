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


# --- Uniform field preprocessing knobs (the ralph loop edits these). These
# replace the old adaptive-blur "ring" that imposed an artificial circular zone
# at ~20-35% radius — an artifact NOT present in the reverse-engineered tool,
# whose field is a flat `dist + (255-lum)*k` applied UNIFORMLY across the image. ---
FIELD_DENOISE_SIGMA = 10.0   # uniform blur — suppresses busy input texture evenly
FIELD_SHADOW_LIFT = 60.0     # raise dark pixels toward this floor so heavy shadows /
                             # makeup don't pile contours into a blob (0 = off)


def build_field(luminance, seed_x, seed_y, lum_mix=1.0):
    """
    Build the scalar field used for isoline extraction — the reverse-engineered
    CONTOUR-V formula, applied UNIFORMLY (no adaptive zones):

        field[y,x] = abs(x - seed_x) + abs(y - seed_y)      # Manhattan -> diamonds
                     + (255 - lum_pre[y,x]) * lum_mix

    where lum_pre is the luminance after uniform preprocessing: a single Gaussian
    denoise (FIELD_DENOISE_SIGMA) that tames the busy source texture, then a
    shadow-lift (FIELD_SHADOW_LIFT) that compresses the dark end so heavy
    shadows/makeup don't collapse contours into a smudge. The diamond rings
    emanate from the seed and the luminance term warps them to follow the face,
    consistently from the seed all the way to the image edges.

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

    # Uniform preprocessing (same everywhere — this is the key fix vs. the old ring).
    lum_pre = gaussian_filter(luminance, sigma=FIELD_DENOISE_SIGMA)
    if FIELD_SHADOW_LIFT > 0:
        lum_pre = FIELD_SHADOW_LIFT + lum_pre * ((255.0 - FIELD_SHADOW_LIFT) / 255.0)

    xs = np.arange(W, dtype=np.float32)
    ys = np.arange(H, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    dist_field = np.abs(xx - seed_x) + np.abs(yy - seed_y)
    field = dist_field + (255.0 - lum_pre) * lum_mix

    return field.astype(np.float32), float(field.min()), float(field.max())


# --- Tunable knobs for the wave (L1-diamond) field. The ralph loop edits these
# the same way it edits engine/contour.py's power=2.7. ---
# NOTE on the zone radii: INNER/OUTER are deliberately WIDE so the relief grades
# smoothly from the seed all the way past the image corners — this dissolves the
# visible "limited circle" boundary the narrow (0.20/0.42) zone produced, giving a
# near-uniform field while still easing relief outward (a narrow zone, e.g. the
# old 0.20/0.42, made the relief fall off across a visible circle).
WAVE_DIAMOND = 0.12     # extra crisp-diamond bias: 0 = full ripple, 1 = ignore the face
WAVE_RELIEF = 0.65      # luminance ripple amplitude (× lum_mix). Low => diamonds dominate
WAVE_SIGMA_FACE = 8.0   # luminance blur near the seed (preserves feature wrap)
WAVE_SIGMA_BG = 30.0    # luminance blur far from the seed (suppresses hair/bg texture)
WAVE_FAR = 0.35         # far-field ripple multiplier (low => clean bg; raised so the
                        # background still ripples -> no abrupt circle edge)
WAVE_INNER = 0.10       # relief-fade inner radius (fraction of min(W,H)) — starts near seed
WAVE_OUTER = 0.90       # relief-fade outer radius — wide, so the fade reaches past corners


def build_wave_field(luminance, seed_x, seed_y, lum_mix=1.0, diamond=None,
                     relief=None, far=None):
    """Wave/diamond field: an L1 (Manhattan) distance dominated by geometry, with
    a GENTLE luminance relief so the diamonds ripple around features.

    Matches the VEX-LINE / CONTOUR-V signature: crisp concentric DIAMONDS
    (Manhattan distance from the seed) that stay topologically intact everywhere,
    bending — not breaking into loops — around eyes/nose/mouth. The relief is kept
    small relative to the L1 gradient (so it never creates closed loops) and is
    suppressed far from the seed (so hair/background render as clean diamonds, not
    dense texture). This is the key difference from build_field, whose full-strength
    luminance term over-densifies the face into a smudgy blob.

        field[y,x] = (|x-seed_x| + |y-seed_y|)              # L1 diamond base (px)
                     + relief * lum_mix * (1-diamond) * w[y,x] * (255 - lum_blur)

    where w fades the relief from full (face zone) to `far` (background).

    diamond (0..1) biases toward pure crisp diamonds; relief scales the ripple.
    Returns the same (field, field_min, field_max) tuple as build_field.
    """
    # Read the WAVE_* knobs from module globals at call time (NOT as default args,
    # which would freeze them at import — so editing the constants would silently
    # do nothing). Explicit caller-passed values still override.
    d = WAVE_DIAMOND if diamond is None else float(np.clip(diamond, 0.0, 1.0))
    relief = WAVE_RELIEF if relief is None else relief
    far = WAVE_FAR if far is None else far
    H, W = luminance.shape

    # Adaptive luminance blur: light near the seed (keep feature detail), heavy
    # far away (kill texture) — same idea build_field uses.
    lum_light = gaussian_filter(luminance, sigma=WAVE_SIGMA_FACE)
    lum_heavy = gaussian_filter(luminance, sigma=WAVE_SIGMA_BG)
    xs = np.arange(W, dtype=np.float32)
    ys = np.arange(H, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    dist = np.sqrt((xx - seed_x) ** 2 + (yy - seed_y) ** 2)
    inner = WAVE_INNER * min(W, H)
    outer = WAVE_OUTER * min(W, H)
    dw = np.clip((dist - inner) / (outer - inner), 0.0, 1.0).astype(np.float32)
    lum_blend = (1.0 - dw) * lum_light + dw * lum_heavy

    # L1 diamond base (pixels) dominates the gradient -> crisp global diamonds.
    l1 = np.abs(xx - seed_x) + np.abs(yy - seed_y)
    # Gentle relief, full strength in the face zone, fading to `far` in the bg.
    relief_w = (1.0 - dw) * 1.0 + dw * far
    ripple = (255.0 - lum_blend) * relief * float(lum_mix) * (1.0 - d) * relief_w

    field = (l1 + ripple).astype(np.float32)
    return field, float(field.min()), float(field.max())
