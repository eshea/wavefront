# WAVEFRONT Algorithm Documentation

## Pipeline Overview

  Image → Grayscale → Scalar Field → Marching Squares → Chain Linking → Smoothing → SVG

## Step 1: Image Preprocessing

  Input: RGB image (any size)

  1. Resize to max 640px on longest side (preserve aspect ratio)
     - Reduces computation while preserving visual detail
     - VEX ENGINE appears to use 427x640 or 640x438 grids

  2. Convert to grayscale luminance:
     L[x,y] = 0.299 * R + 0.587 * G + 0.114 * B
     (ITU-R BT.601 standard — matches browser canvas getImageData behavior)

## Step 2: Scalar Field Construction

  field[x,y] = dist(x, y, sx, sy) + (255 - L[x,y]) * lum_mix

  Where:
  - dist(x,y,sx,sy) = sqrt((x-sx)² + (y-sy)²)  [Euclidean distance from seed]
  - L[x,y] = luminance at pixel (x,y), range 0–255
  - (255 - L[x,y]) = inverted luminance: bright=0, dark=255
  - lum_mix = modulation strength, default 1.0

  Properties of this field:
  - Minimum: always 0 (at the seed pixel itself, if lum=255 there)
  - Maximum: max_dist + 255 * lum_mix
  - Dark pixels "raise" the field → isolines pack tightly → looks like deep crevices
  - Bright pixels "lower" the field → isolines spread out → looks like flat plains
  - Background (near-white) contributes nearly 0 luminance warp → clean parallel bands

## Step 3: Isoline Extraction (Marching Squares)

  For N levels, compute N evenly-spaced thresholds:
    step = (field_max - field_min) / (N + 1)
    thresholds[i] = field_min + i * step,  for i in 1..N

  For each threshold t, run Marching Squares:
  - Process each 2x2 pixel cell
  - Compute 4-bit index: which corners have field >= t
  - Look up edge crossings from 16-case table
  - Interpolate exact crossing position along each edge
  - Output raw line segments

  Using skimage.measure.find_contours(field, level=t) which implements
  this algorithm efficiently in C.

## Step 4: Chain Linking (Spatial Hash)

  Marching Squares outputs unordered line segments. We need polyline chains.

  Naive approach: O(n²) — check every segment against every other. Too slow.

  Spatial hash approach: O(n) average case
  1. Round each endpoint to nearest bucket (4px grid)
  2. Build hash map: bucket_key → [segment indices]
  3. For each unlinked segment, look up its endpoint's bucket
  4. Find adjacent segments in that bucket and neighboring buckets
  5. Extend chain greedily until no more connections found

  Note: skimage.find_contours already returns connected paths, so explicit
  chaining is less necessary — but fragmented paths still occur at field
  discontinuities and image boundaries.

## Step 5: Chaikin Smoothing

  Chaikin's corner-cutting algorithm applied iteratively:

  For each iteration:
    new_points = []
    for each consecutive pair (P0, P1):
      Q = 0.75 * P0 + 0.25 * P1   (1/4 point)
      R = 0.25 * P0 + 0.75 * P1   (3/4 point)
      new_points.extend([Q, R])

  Number of iterations = round(smooth_param * 4)
  - smooth=0.00 → 0 iterations (raw marching squares output)
  - smooth=0.25 → 1 iteration
  - smooth=0.50 → 2 iterations
  - smooth=0.75 → 3 iterations
  - smooth=1.00 → 4 iterations

  Each iteration doubles the point count but significantly smooths jagged lines.
  VEX ENGINE default 0.70 → 3 iterations.

## Step 6: Adaptive Stroke Weight

  Lines closer to the seed (low field value = low T) are drawn thicker.
  Lines farther away (high T) are thinner and more transparent.

  normalized_t = (t - field_min) / (field_max - field_min)  ∈ [0, 1]

  stroke_width = max(0.2,  1.4 - normalized_t * wt_range * 1.2)
  stroke_alpha = max(0.35, 0.95 - normalized_t * 0.4)

  This gives:
  - Near seed: width ~1.4px, alpha ~0.95 (bold, dark)
  - Far from seed: width ~0.2px, alpha ~0.35 (fine, faint)
  - wt_range=0: flat 1.4px everywhere
  - wt_range=1: full range from 1.4 to 0.2

## Step 7: SVG Export

  Output SVG with:
  - viewBox = "0 0 {imgW} {imgH}" (original image dimensions)
  - White background rect
  - One <path> element per chain
  - d attribute: M x0,y0 L x1,y1 L x2,y2 ... (moveto + lineto)
  - stroke: rgba(10,10,15,{alpha})
  - stroke-width: {width}
  - stroke-linecap: round
  - stroke-linejoin: round
  - fill: none
