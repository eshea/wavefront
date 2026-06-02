# WAVEFRONT idea backlog — explore for BREADTH (don't hill-climb)

The loop must NOT just nudge one constant up and down. Each tick, pick an idea
from a DIFFERENT category than the last 2 ticks. Prefer ideas that are
qualitatively different over micro-tweaks. When you exhaust a category or have a
genuinely new thought, ADD it here. Mark tried ideas with their result
(✅ better / ➖ same / ❌ worse + score).

Ground truth: `examples/contour_woman_lineart.png` (clean diamond target) and the
artist outputs `examples/contour_woman_post*`. Canonical render is `method=contour`
(uniform `build_field`), centered seed, levels 65. Judge = local vLLM.

## A. Field formula (engine/field.py)
- [ ] True relief: treat luminance as a smooth height/depth map (strong low-freq,
      bounded) so lines displace without bunching. Frequency-split: keep low freq,
      drop high freq before adding to the distance term.
- [ ] Histogram equalization / CLAHE on luminance before the field.
- [ ] Bilateral / edge-preserving denoise instead of plain Gaussian.
- [ ] Gamma / tone-curve on (255-lum) so mids drive the warp, darks are clamped.
- [ ] Euclidean vs Manhattan distance base (RE doc shows T-range fits Manhattan;
      try a blend to round the diamonds slightly).
- [ ] Clamp the luminance term to a percentile so a few black pixels don't blow up.

## B. Level spacing (engine/contour.py THRESHOLD_POWER)
- [ ] Equal-arc-length spacing: place levels so LINE SPACING is even (not value-even).
- [ ] Adaptive level count by field range.

## C. Preprocessing (the input is a BUSY AI image)
- [ ] Stronger/smarter denoise of gold-splash/sparkle texture.
- [ ] Background/foreground separation (luminance threshold) to calm the bg.

## D. New methods (whole new algorithms — high value for breadth)
- [ ] Refine `method=flow` (evenly-spaced streamlines) — suppress small loops,
      longer continuous lines (engine/flow.py).
- [ ] Hybrid: diamonds near seed → flowing lines outward.
- [ ] Hatching / engraving style (parallel lines displaced by brightness).

## E. Tests & metrics (add real tests — anti-overfit, anti-regression)
- [ ] A test asserting NO circular "zone" artifact (radial density should be smooth).
- [ ] A metric for line-spacing evenness (variance of nearest-line distance).
- [ ] A test that the field is monotonic enough that contours don't form tiny islands
      (cap on closed-loop count) — guards the smudge failure mode.
- [ ] Golden-image regression test for the canonical render stats.

## F. Stroke / export (engine/export.py)
- [ ] Stroke weight by local curvature or feature, not just distance.
- [ ] Vary line color/opacity to read as the multi-pen ink look.
