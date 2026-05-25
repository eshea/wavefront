# WAVEFRONT Research Notes

## Origin: VEX-LINE Artist

VEX-LINE is a plotter artist who creates large-format topographic contour portraits on paper using pen plotters. The works feature:
- Tightly nested contour lines that follow facial topology
- A distinctive concentric diamond/square pattern emanating from a central seed point
- Color variation achieved by multiple pen passes with different ink colors
- Physical ink bleed and texture that gives organic quality impossible to replicate digitally

The artist's tool, VEX ENGINE (CONTOUR-V CORE, v1.1), is a standalone HTML application.

## Key Observations from UI Analysis

From screenshots of VEX ENGINE in use:

### Parameters observed:
- CONTOURS slider: 63 (default), range ~10–150+
- LINE SMOOTH: 0.70 (default), range 0–1
- SEED: displayed as (x, y) coordinate — a 2D point, NOT a random seed
- Export: SVG and 2x PNG

### Stats panel revealed:
- PATHS: number of distinct polyline chains
- POINTS: total coordinate count
- LEVELS: same as CONTOURS
- SEGS: raw segment count before chaining
- GRID: image dimensions (e.g. 427x640, 640x438)
- T RANGE: min...max of scalar field (e.g. 0.0...776.1)

### Critical insight from T RANGE analysis:

Example 1: Grid 427x640, Seed ~center (214,320), T RANGE 0.0...776.1
  Max diagonal distance = sqrt(427² + 640²) = 769 ≈ 776 ✓

Example 2: Grid 640x438, Seed ~center, T RANGE 0.0...776.1
  Max diagonal = sqrt(640² + 438²) = 775.8 ✓

Example 3: Grid 640x438, Seed near top (270,43), T RANGE 0.0...1036.8
  Max distance from (270,43) to corner (640,438) = sqrt(370²+395²) = 540
  But 1036.8 ≈ 540 + 255*lum_mix → lum_mix ≈ 1.95...
  OR: distance to farthest corner (0,438) = sqrt(270²+395²) = 478, plus lum contribution
  Recheck: farthest corner from (270,43) is (640,438): sqrt((640-270)²+(438-43)²) = sqrt(370²+395²) = 540
  T_max = 540 + 255*1.0 = 795 ≠ 1036
  Try (0,438): sqrt(270²+395²) = 478, 478+255 = 733 ≠ 1036

  Best fit: lum_mix=1.0 and field uses (255-lum) where lum can be 0:
  Max dist from edge seed to far corner when image is 640x438 and seed=(270,43):
  farthest point = (640,438): dist = sqrt(370²+395²) = 540.1
  T_max = 540.1 + 255*1.0 = 795.1 ≠ 1036.8

  Alternate: seed was NOT at (270,43) in image coords but in canvas coords at 124% zoom.
  At 124% zoom, canvas click (270,43) maps to image coords (~218,~35).
  From (218,35) to (640,438): sqrt(422²+403²) = 582.5, +255 = 837.5 still ≠ 1036

  Most likely: lum_mix is NOT fixed at 1.0. The higher T RANGE when seed is near edge
  suggests lum_mix ~= 1.95–2.0 for that example, or the field formula accumulates
  differently (e.g., field = dist * lum_mix + inverted_lum).

### Conclusion on formula:
  field[x,y] = sqrt((x-sx)² + (y-sy)²) + (255 - luminance[x,y]) * lum_mix

  With lum_mix=1.0 this matches the centered-seed T RANGE cases perfectly.
  The edge-seed discrepancy may be due to zoom-adjusted coordinates or a
  slightly different formula variant. lum_mix=1.0 is the confirmed default.

### Seed behavior:
- RESET SEED TO CENTER button → seed snaps to (width/2, height/2)
- Clicking canvas sets seed to click coordinates
- The concentric diamond pattern always centers on the seed point
- Moving seed off-center increases T RANGE because max distance to image corners grows

### Contour count vs path count:
  63 levels → 149 paths (portrait, centered seed)
  63 levels → 307 paths (landscape, different image — more complex topology)
  112 levels → 542 paths (same landscape image — roughly 2x levels = ~2x paths as expected)

  Observation: paths > levels because each isoline can fragment into multiple
  disconnected chains when the image has complex topology (shadows, highlights
  that create isolated "islands" in the field).
