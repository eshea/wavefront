# WAVEFRONT Experiment Log

The Ralph loop reads this file each tick to know what's been tried and
what to try next. Each tick appends a new entry.

## ✅ MILESTONE (2026-06-07): the woman example is now VERY GOOD

The canonical render now matches the artist. Input
`examples/woman/woman-source.jpeg` → target the dense
`examples/woman/woman-sample-output-2.jpeg`, rendered with **`method=march`**
(the tone-cost geodesic, `engine/march.py`), levels 111, 780px. The output is a
clean, photographic, tone-rendered portrait — the face is depicted by line
density (dense in shadows/features, sparse in highlights) with L1 diamonds in the
flats. Tracked evidence: `loop/output/current-woman.png`.

Deterministic score (`loop/dscore.py`): **d_score 100, d_tone 0.74** (artist 0.71),
d_diag 0.50 (artist 0.50). The breakthrough was twofold — (1) the scorer's
`d_tone` term (does the output render the source's tones?), which exposed that the
old additive wave field had d_tone≈0 and scored a *false* 99 → corrected to 47;
(2) switching the engine to the march geodesic, whose dark-pixels-cost-more
mechanism actually produces tone-driven density (d_tone −0.19 → +0.74).

## Definition of done / quality target

"Good" output for the canonical test (input `examples/woman/woman-source.jpeg`,
centered seed, levels 111, smooth 0.00, **method=march**) should visually resemble
`examples/woman/woman-sample-output-2.jpeg`. Measured by `d_score` (0–100,
`loop/dscore.py`): tone-fidelity (`d_tone`) + diamond (`d_diag`≈0.50) + style.

Key qualities to match (now achieved on the woman):
- Tone-driven line density — DENSE where the image is dark, sparse where bright
  (this is `d_tone`; the subject emerges as shading, not just geometry)
- Nested L1 diamonds in flat regions, warped organically around features
- Background lines clean, no fine noise

Secondary / holdout: the helmet (`examples/space/`) and samurai
(`examples/samurai/`) — generalization checks; the march defaults are tuned for
the high-contrast woman, so smooth subjects score lower (acceptable).

---

## Iter 000 · Bootstrap

State at loop start (2026-05-25):

- CORE-parity UI complete: BOUNDS/SEED/GHOST/FIT/HOME view toggles,
  ADVANCED disclosure hiding lum_mix and wt_range, PNG export, numbered
  filenames.
- Algorithm: `field = sqrt((x-sx)² + (y-sy)²) + (255 - lum) * lum_mix`
  with default lum_mix=1.0.
- Smoothing: Chaikin, `iterations = round(smooth_param * 4)`.
- No tonal preprocessing (no contrast, no gamma).
- No path simplification / no min-segment filter.

Suspected gaps vs reference (untested):
1. Source webp is dense AI-generated art with no flat background — likely
   produces a noisy, over-saturated contour field. Reference outputs look
   cleaner, suggesting the artist's input is tonally simpler or CORE does
   internal cleanup we don't.
2. WAVEFRONT modulates stroke width by `normalized_t`; CORE screenshot
   shows uniform-looking strokes. Our `wt_range` is now hidden but still
   defaults to 0.6 — may want to set to 0.0 to match CORE.
3. No invert mode — some references look dark-line-on-light, ours matches,
   but the helmet post is monochrome dense linework which may need invert.

**Next:** review tick — run canonical test, view side-by-side with
reference (`contour_woman_post1.jpeg`), write first real assessment with
specific visual deltas.

---

## Iter 001 · 2026-05-25 · REVIEW — quality assessment vs reference

**Hypothesis:** (review tick — no hypothesis, assessing baseline)

**Change:** none

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_001.svg` (paths=37088, pts=1,198,091, t_min=40.6, t_max=774.4)
- reference: `examples/conour_woman_post1.jpeg` + `contour_woman_post2.jpeg`
- visual comparison:
  - **Reference**: Clean white background. Face shows beautiful topo-map rings in
    diamond/oval shapes around eyes, nose, mouth. Lines are long, flowing, continuous.
    Background has very sparse, evenly spaced horizontal wavy bands. Total: 452 chains,
    ~300 pts/chain on average.
  - **Our output**: Entire image is nearly solid black. Tiny fragmented line segments
    scattered everywhere — no discernible rings, no background sparsity, no facial feature
    wrapping. Lines look like static noise rather than contours.

**Gap analysis:**
1. **Path fragmentation (critical)**: 37,088 paths vs 452 chains — 82× more paths,
   each only ~32 pts/path avg vs ~300 pts in reference. Iso-contours shatter into tiny
   islands because the source image has complex fine texture that creates a noisy field.
2. **Visual density (critical)**: Image is nearly solid black. Reference has large white
   regions. Fragmentation + short paths produce a smeared texture rather than lines.
3. **Ring structure (critical)**: Diamond-shaped concentric rings are completely absent.
   Reference shows unmistakable topo-map structure with seed-centered diamonds.
4. **wt_range**: Already set to 0.0 for test — stroke width uniform, not the issue.

**Suspected cause:** The input image has dense AI-generated texture. The luminance map
transfers all this texture noise into the field, fragmenting every iso-level contour into
hundreds of tiny disconnected pieces. CONTOUR-V CORE likely preprocesses the luminance
with a Gaussian blur (σ≈4–8 px) to produce a smooth, noise-free field before extracting
contours. This single fix should collapse 37,088 paths into a few hundred long chains.

**Result:** worse vs. reference (baseline — no prior iteration). Gap is severe.

**Next:** build — add Gaussian blur σ=4 to luminance in `engine/field.py:build_field()`.
Test whether path count drops from 37k → ~1k and visual quality improves toward reference.

---

## Iter 002 · 2026-05-25 · Gaussian blur σ=4 on luminance

**Hypothesis:** The source image's fine AI-generated texture fragments iso-contours into thousands of tiny disconnected segments. Blurring luminance with σ=4 before field construction should smooth noise while preserving large tonal regions (face, background), collapsing 37k paths into a few hundred long chains.

**Change:** `engine/field.py:9` — added `from scipy.ndimage import gaussian_filter`. `engine/field.py:82` — added `luminance = gaussian_filter(luminance, sigma=4)` before meshgrid construction.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_002.svg` (paths=1879, pts=362,575, t_min=105.0, t_max=743.0)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Massive improvement over iter_001. Lines now flow and wrap around facial features — concentric ring structure is clearly visible around eyes, nose, forehead. Background regions show more open spacing. Hair/plant regions are still dense and branchy.
  - **Reference**: Clean white background. Diamond-shaped rings very pronounced — almost perfectly flat/geometric on the face center, then organically wrapping around features. Extremely sparse background bands. ~452 chains.
  - **Remaining gaps**: (1) Path count 1879 vs 452 — still ~4× too many. (2) Background areas too noisy/dense — too many small rings in texture areas. (3) Diamond shape less pronounced — ours is rounder. (4) Hair/foliage edges produce branchy tangles not in reference.

**Result:** better — dramatic improvement. vs. reference: much closer but still significantly denser. Gap reduced from critical to moderate.

**Next:** build — increase blur to σ=8. Path count should drop further (targeting <600). Background noise should clear. Verify that facial feature detail (eye sockets, nose bridge) survives the stronger blur.

---

## Iter 003 · 2026-05-25 · Gaussian blur σ=8 on luminance

**Hypothesis:** Increasing blur from σ=4 to σ=8 should further reduce path count (targeting <600) by smoothing finer background texture noise while keeping large tonal regions (face, shoulders) intact.

**Change:** `engine/field.py:82` — changed `gaussian_filter(luminance, sigma=4)` to `sigma=8`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_003.svg` (paths=742, pts=241,521, t_min=111.9, t_max=726.2)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Facial ring structure is clearly forming — concentric rings visible around eyes, nose, forehead. Background hair/plant regions still dense. Rings are circular/oval shape.
  - **Reference**: Clean white background, extremely sparse wave-bands outside face. Very pronounced diamond-shaped rings on face center. Highly geometric, crisp contours.
  - **Remaining gaps**: (1) Rings are circular vs. reference's distinctive diamond/square shape — strongest visual mismatch. (2) Background/hair still too dense (742 vs 452 paths). (3) Line spacing in face comparable but ring geometry wrong.

**Result:** better vs. iter_002. vs. reference: moderate gap — ring geometry still wrong, background still dense.

**Next:** build — switch distance metric from Euclidean (L2) to Manhattan (L1): L1 iso-contours are rotated squares (diamonds), which matches the reference's geometric ring shape exactly.

---

## Iter 004 · 2026-05-25 · Manhattan (L1) distance metric

**Hypothesis:** The reference's diamond-shaped rings are characteristic of L1 (Manhattan) distance, not L2 (Euclidean). Changing `dist_field = sqrt((x-sx)²+(y-sy)²)` to `dist_field = |x-sx| + |y-sy|` should produce the rotated-square iso-contours visible in the reference. As a side effect, L1 distance distributes field values differently — may also reduce path count.

**Change:** `engine/field.py:88` — changed `np.sqrt((xx - seed_x) ** 2 + (yy - seed_y) ** 2)` to `np.abs(xx - seed_x) + np.abs(yy - seed_y)`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_004.svg` (paths=547, pts=188,633, t_min=116.5, t_max=960.6)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Rings are noticeably more diamond/rectangular — clear improvement toward reference geometry. Facial features (eyes, nose bridge, mouth) still well-defined with wrapping contours. Background/hair still denser than reference but less crowded than iter_003.
  - **Reference**: Crisp diamond rings, clean sparse background, graceful wavy bands outside face.
  - **Remaining gaps**: (1) Background regions (hair, foliage) still too dense — 547 vs 452 target paths. (2) Diamond shapes forming but not as crisp/geometric as reference's sharp inner rings.

**Result:** better vs. iter_003. vs. reference: closer — ring geometry now in correct direction, path count 547 vs 452 target (21% over).

**Next:** build — try σ=12 with Manhattan to further reduce background noise. Targeting path count ≤ 480.

---

## Iter 005 · 2026-05-25 · Gaussian blur σ=12 on luminance

**Hypothesis:** Increasing blur from σ=8 to σ=12 should further reduce path count by smoothing medium-frequency background texture (hair, foliage) while preserving large-scale face tonal regions.

**Change:** `engine/field.py:82` — changed `gaussian_filter(luminance, sigma=8)` to `sigma=12`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_005.svg` (paths=334, pts=154,549, t_min=123.2, t_max=947.0)
- reference: `examples/conour_woman_post1.jpeg` + `contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Face region has clear concentric ring structure — eye sockets, nose, mouth area all show distinct wrapping contours. Diamond/oval shape visible in forehead center region. Background/hair still denser than reference but significantly cleaner than σ=8. Lines flow well, no fragmentation noise.
  - **Reference**: Very sparse white background, clean isolated face. Dramatic diamond geometry in forehead center — very crisp V-shaped chevron bands. Background has only a few spare wavy horizontal bands. Face ring density is similar to ours but lines are more widely spaced, more visible white between them.
  - **Remaining gaps**: (1) Background hair/foliage still has dense curvy contour lines — reference has near-empty white space outside face. This is partly a source image issue (AI-gen texture vs cleaner original). (2) Inner diamond rings less geometrically crisp than reference. (3) Overall lines appear more compressed / less white space between them.

**Result:** better vs. iter_004. vs. reference: moderately close — path count now 334 (below 452 target), face ring structure recognizable, diamond geometry forming.

**Next:** build — add minimum path length filter: drop contour paths with fewer than 30 points. Should remove short isolated background fragments without touching the long face contour chains. Expect ~10-15% further path reduction and cleaner background.

---

## Iter 006 · 2026-05-25 · Minimum path length filter (≥30 pts)

**Hypothesis:** Short isolated contour fragments (<30 pts) contribute to background noise without adding visible ring structure. Filtering them should reduce path count and clean up scattered dots/stubs.

**Change:** `engine/contour.py:63` — changed `if len(path) < 2:` to `if len(path) < 30:`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_006.svg` (paths=314, pts=154,172, t_min=123.2, t_max=947.0)
- reference: `examples/conour_woman_post1.jpeg`
- visual comparison:
  - **Our output**: Face contours clearly wrap around eyes, nose, mouth. Ring structure visible, some diamond geometry in forehead region. Hair/background still has dense curvy lines covering most of the image. Lines are black on white background.
  - **Reference**: Forehead shows crisp, nearly flat horizontal lines breaking into very clean geometric V-shaped diamond chevrons. The inner diamond zone is architecturally regular, not organic. Background/hair has fan-shaped structured lines, large white-space areas at image edges.
  - **Remaining gaps**: (1) Forehead lacks the crisp geometric diamond — ours is more organic/wavy. (2) Background/hair still too dense. (3) Outer edges of image lack the large white-space bands of reference. The filter only removed 20 paths (6% drop) — most paths are long and survive.

**Result:** marginally better vs. iter_005. vs. reference: roughly neutral improvement — minor cleanup, main gaps unchanged.

**Next:** build — increase Gaussian blur σ from 12 to 16. Smoother forehead luminance → more geometric L1 diamond chevrons. Expect path count to drop further (~250–280) and white space to increase.

---

## Iter 007 · 2026-05-25 · Gaussian blur σ=16 on luminance

**Hypothesis:** Increasing blur from σ=12 to σ=16 will smooth the forehead luminance further, producing crisper geometric L1 diamond chevrons and reducing closed contour loops in hair/background.

**Change:** `engine/field.py:82` — changed `gaussian_filter(luminance, sigma=12)` to `sigma=16`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_007.svg` (paths=248, pts=136,205, t_min=131.3, t_max=950.3)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Face structure excellent — concentric rings wrap around eyes, nose, mouth with clear diamond-ish geometry in the forehead. Background (hair, plants) still has many closed-loop contours, denser than reference. Lines are clean, no fragmentation noise.
  - **Reference**: Very crisp flat-sided diamond chevrons in forehead. Background shows long nearly-horizontal wavy bands with large white-space areas at edges. Lines in background flow through rather than looping around texture features.
  - **Key metric**: Total points nearly identical (136,205 ours vs 135,962 reference). But distributed in 248 paths vs 452 chains — our paths are 1.8× longer on average, meaning lines wind more (closed loops) vs reference's longer, straighter flowing bands.
  - **Remaining gaps**: (1) Background still has closed loops from hair/plant texture — needs more blur or lighter background. (2) Forehead diamond getting closer but still slightly more oval than reference's flat-sided shape.

**Result:** better vs. iter_006. vs. reference: noticeably closer — diamond geometry forming, face structure strong.

**Next:** build — increase σ to 20. Background closed loops persist; more blur should suppress remaining medium-scale texture variation in hair/plants. Total points target: ~120k.

---

## Iter 012 · 2026-05-25 · Gaussian blur σ=20 on luminance

**Hypothesis:** Increasing blur from σ=16 to σ=20 should suppress medium-frequency background texture (hair, foliage) enough to convert closed-loop bubble contours in the background into longer open-flowing bands.

**Change:** `engine/field.py:87` — changed `gaussian_filter(luminance, sigma=16)` to `sigma=20`. (Note: iters 008–011 in output folder are undocumented runs from previous ticks — code was left at σ=16 when this tick started.)

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_012.svg` (paths=218, pts=127,642, t_min=140.4, t_max=949.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Face ring structure clearly visible with wrapping contours around eyes, nose, mouth. Forehead shows rectangular/diamond rings. Background (hair, plants) still has small closed-loop bubble contours creating dense gray texture. Overall density slightly lower than σ=16.
  - **Reference**: Very sparse background — only long, flowing nearly-horizontal wavy bands with large white areas. Inner forehead has crisp flat-sided diamond rings. 452 chains vs our 218 (fewer paths but reference paths are shorter open curves; ours are longer closed loops winding around texture features).
  - **Key gap**: Background region topology — our paths form closed loops around hair/plant texture features; reference paths are open flowing curves. This isn't fixed by simply reducing path count.

**Result:** marginally better vs. iter_007 (248→218 paths, 136k→128k pts). vs. reference: same structural gap — background closed loops persist despite increased blur.

**Next:** build — increase σ to 30. Hair/foliage texture has frequency components at wavelengths >40px that σ=20 doesn't suppress. σ=30 should flatten background luminance into a near-uniform plateau so iso-levels become simple nearly-parallel bands rather than closed loops.

---

## Iter 013 · 2026-05-25 · Gaussian blur σ=30 on luminance

**Hypothesis:** Hair/foliage texture has frequency components at wavelengths >40px that σ=20 doesn't suppress. σ=30 should flatten background luminance into a near-uniform plateau so iso-levels become simple nearly-parallel bands rather than closed loops.

**Change:** `engine/field.py:87` — changed `gaussian_filter(luminance, sigma=20)` to `sigma=30`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_013.svg` (paths=200, pts=120,872, t_min=161.2, t_max=940.2)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Major visual improvement. Background now shows long flowing nearly-horizontal wavy bands instead of closed bubble loops — much closer to reference's sparse wavy background. Face region shows clean ring structure wrapping around eyes, nose with diamond geometry in forehead. Much more white space visible overall.
  - **Reference**: 452 chains, finely wrapping face contours, very sparse background, crisp diamond center.
  - **Remaining gaps**: (1) Face detail reduced — σ=30 over-smoothed the face luminance, losing fine wrapping detail around eye sockets, nose bridge. Reference has ~452 paths; we have 200 with longer average path length. (2) Background still has some medium-density regions in corners. (3) Fundamental tension: higher σ → cleaner background but fewer face contours.

**Result:** better — significant improvement. Background topology transformed from closed loops to open flowing bands. vs. reference: closer but new gap: face under-detailed.

**Next:** build — adaptive blur: blend lightly-blurred (σ=8) and heavily-blurred (σ=30) luminance by pixel brightness. Dark face pixels → light blur (preserves fine wrapping detail). Bright background pixels → heavy blur (cleans closed loops). This should give reference-quality background AND reference-quality face detail simultaneously.

---

## Iter 024 · 2026-05-25 · REVIEW — assess code state after undocumented iters 014–023

**Hypothesis:** (review tick — no hypothesis, assessing current baseline)

**Change:** none

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_024.svg` (paths=222, pts=120,064, t_min=131.3, t_max=894.1)
- reference: `examples/conour_woman_post1.jpeg` + `contour_woman_post2.jpeg`
- current code: spatial adaptive blur σ=16 (face zone, inner_r=0.20×min(H,W)) / σ=50 (background, outer_r=0.35×min(H,W)); L1 distance; effective_lum_mix=1.0×face + 0.60×background; min_path_length=30.
- visual comparison:
  - **Our output**: Face ring structure visible — concentric rings wrap around eyes, nose, mouth. Forehead shows some diamond-ish geometry. Background/hair transition zone has grayish density from closed loops around dark hair/plant texture. Lines are clean and non-fragmented.
  - **Reference**: Crisp flat-sided diamond rings in forehead center, eye sockets/nose bridge sharply defined, background shows long sparse flowing nearly-horizontal bands with large white space. 452 chains total.
  - **Key gap**: Background effective_lum_mix=0.60 still lets dark hair (lum≈50 → value=200) contribute 200×0.60=120 to the field, enough to create closed loops around hair texture despite σ=50 blur. Diamond geometry forming but rings still more circular/organic than reference's crisp flat-sided diamonds.

**Result:** baseline for this review. vs. reference: moderate gap on background density and face diamond crispness.

**Next:** build — reduce background effective_lum_mix 0.60→0.15 so far-field iso-levels are 85% radial L1 (flowing bands) and only 15% lum-modulated. Hypothesis: breaks closed loops, creates more open flowing background similar to reference.

---

## Iter 025 · 2026-05-25 · Reduce background lum_mix 0.60→0.15

**Hypothesis:** Background effective_lum_mix=0.60 still allows dark hair/plant texture to create closed contour loops despite σ=50 blur. Dropping to 0.15 makes the background field 85% L1 radial distance → iso-levels become open flowing bands rather than closed topology loops.

**Change:** `engine/field.py:101` — changed `dist_weight * 0.60` to `dist_weight * 0.15`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_025.svg` (paths=252, pts=121,357, t_min=131.3, t_max=843.0)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Face diamond rings noticeably crisper and more pronounced — clearest diamond geometry seen so far. Eye sockets and nose bridge well defined. Background now shows uniform fine diagonal hatching (~6px spacing between lines) — characteristic of pure L1 diamond iso-contours evenly filling the image.
  - **Reference**: Sparse flowing background bands with large white spaces, crisp face with tight wrapping contours. 452 chains.
  - **Trade-off**: Face quality clearly improved over iter_024. Background traded "closed organic loops" for "uniform L1 diagonal hatching" — neither matches the reference's sparse flowing bands, but the uniform hatching is at least structured.
  - **Root cause of uniform hatching**: At lum_mix=0.15 in background, field is 85% L1 radial → 111 iso-levels spaced evenly every ~6px across the background. No variation in density, no white space.

**Result:** slightly better overall — face improvement outweighs background regression. vs. reference: face closer, background still wrong (now too uniformly dense rather than organically dense).

**Next:** build — try background effective_lum_mix = 0.30 (middle ground between 0.15 and 0.60). Should add enough organic luminance variation to break pure-L1 uniformity and create flowing variety in background, without re-introducing closed loops around dark texture.

---

## Iter 026 · 2026-05-25 · Background lum_mix 0.70→0.30; discover resolution mismatch

**Hypothesis:** Dropping background effective_lum_mix from 0.70 to 0.30 will add enough lum-driven variation to break pure-L1 diagonal uniformity while staying below the closed-loop threshold (~0.60 produced organic closed loops).

**Change:** `engine/field.py:101` — changed `dist_weight * 0.70` to `dist_weight * 0.30`. (Note: actual committed baseline was 0.70, not 0.60 as iter_025 logged — prior log entries described code state inaccurately. Also: working tree has undocumented `field = gaussian_filter(field, sigma=1.0)` added after the dist+lum sum; kept as-is.)

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_026.svg` (paths=207, pts=99,960, t_min=132.0, t_max=859.4)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Face has clear concentric diamond rings wrapping around eyes, nose, mouth — diamond geometry recognizable in forehead. Background shows structured diagonal L1 hatching (~6-8px spacing), filling entire image uniformly. Less organic than 0.70, but still no large white areas in corners.
  - **Reference**: Crisp flat-sided diamond chevrons in forehead center, tight face rings, sparse background with large white areas and wide-spaced flowing bands.
  - **Key discovery**: Source image is 742×742 but we process at MAX_DIM=640. Artist seed (227,225) is in 742px space; we use it in 640px space (proportionally shifted ~5%). More critically: at 640px, field range ≈ 727 units → 6.6px/level in background. At native 742px, field range would ≈ 1132 units → 10.3px/level (with power=2.7 non-uniform: ~17px in background). This resolution mismatch is likely the primary driver of the dense background hatching.

**Result:** marginal improvement vs committed baseline (207 vs 222 paths). vs. reference: moderate gap unchanged — background density still wrong, but face quality reasonable.

**Next:** build — raise MAX_DIM from 640 to 742 to process the canonical source at native resolution. Hypothesis: larger field range increases background level spacing from ~11px to ~17px, reducing background line density significantly. Also fixes seed coordinate proportional mismatch.

---

## Iter 026 · 2026-05-25 · Background lum_mix 0.15→0.30 (middle ground)

**Hypothesis:** background effective_lum_mix=0.15 produces pure-L1 uniform diagonal hatching because it's nearly radial. Increasing to 0.30 should add enough organic luminance variation to break the pure-L1 uniformity and create flowing variety.

**Change:** `engine/field.py:101` — changed `dist_weight * 0.15` to `dist_weight * 0.30`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_026.svg` (paths=236, pts=119,748, t_min=131.3, t_max=860.0)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Nearly identical to iter_025 — background still shows uniform fine L1 diagonal hatching. Face ring structure visible. Change from 0.15 to 0.30 produced negligible visible difference.
  - **Reference**: Sparse organic flowing wavy bands with large white space between them.
  - **Root cause identified**: σ=50 over-blurs background luminance to near-uniform → lum contribution is nearly constant → field ≈ pure L1 regardless of lum_mix value. The problem isn't lum_mix coefficient; it's that σ=50 has eliminated the luminance variation needed for organic waviness. σ=30 globally (iter_013) produced open flowing bands precisely because it's strong enough to prevent closed loops while weak enough to retain organic waviness.

**Result:** same as iter_025. vs. reference: no improvement. Root cause is over-blurred background (σ=50), not lum_mix coefficient.

**Next:** build — switch to σ=8 face / σ=30 background. σ=30 background verified in iter_013 to produce open organic flowing bands. σ=8 face gives finer facial detail than σ=16. Restore lum_mix=1.0 throughout (spatial adaptive blur does the work, lum_mix reduction no longer needed).

---

## Iter 027 · 2026-05-25 · σ=8 face / σ=30 background, lum_mix=1.0 uniform

**Hypothesis:** σ=50 background over-blurs luminance to near-uniform, eliminating the organic variation needed for wavy bands. σ=30 was validated in iter_013 to produce open flowing bands. σ=8 face should give finer wrapping detail than σ=16. Restoring lum_mix=1.0 throughout lets the smoothed luminance create organic variation instead of near-uniform L1.

**Change:** `engine/field.py:84–85` — changed `sigma=16` to `sigma=8`, `sigma=50` to `sigma=30`. `engine/field.py:101` — simplified `effective_lum_mix = lum_mix` (removed the dist_weight*0.30 reduction).

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_027.svg` (paths=241, pts=134,034, t_min=116.5, t_max=940.2)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Major improvement over iter_026! Background now shows organic wavy flowing bands — clearly recognizable topo-map style in the background, not uniform L1 hatching. Face detail excellent: eyes, nose, mouth all show tight wrapping contours. Diamond ring structure visible in the forehead. Overall image is dense but organically structured.
  - **Reference**: Similar organic background bands, crisp diamond face, but with significantly more white space between lines (reference is ~2–3× less dense in background).
  - **Remaining gap**: Background still too dense. Lines are ~6–8px apart; reference shows ~15–20px spacing in background. Both have similar total points (ours 134k vs reference 135k) but ours has 241 longer paths vs 452 shorter chains. The visual density difference may also relate to: (1) our source image has dark hair/plants filling the background; (2) reference source likely had near-white studio background.

**Result:** significantly better vs. iter_026. vs. reference: closer — organic band topology now correct, face detail good, spacing still too dense.

**Next:** build — add slight background lum_mix reduction (effective_lum_mix=0.70 in far background). With σ=30, background lum variation is still ±~30 units. At 0.70, this becomes ±21 units → still enough for organic waviness but reduces density by ~15–20%.

---

## Iter 028 · 2026-05-25 · Background lum_mix 0.70 in far background

**Hypothesis:** Background effective_lum_mix=1.0 still lets background luminance variation create tight contour spacing. Reducing to 0.70 in the far-field region (dist_weight=1.0) reduces dark-hair/plant contribution by ~30% → ~15-20% fewer background levels.

**Change:** `engine/field.py:101` — changed `effective_lum_mix = lum_mix` to `effective_lum_mix = lum_mix * ((1.0 - dist_weight) * 1.0 + dist_weight * 0.70)`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_028.svg` (paths=247, pts=131,380, t_min=116.5, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Organic wavy background bands (same topology as iter_027). Face shows wrapping rings with some diamond geometry. Lines visually similar to iter_027 — density still ~6–8px throughout background.
  - **Reference**: Sparse background bands at ~15–20px spacing, crisp diamond rings in face with large white-space gaps.
  - **Root cause**: lum_mix reduction of 0.70 (vs 1.0) changes only the luminance amplitude in background, not the L1 distance contribution. The background covers a wide t-range (t ≈ 450–906 = 456 units) receiving ~64 of the 111 iso-levels at ~7px spacing. The face only gets ~33 levels. Linear iso-level spacing fundamentally mismatches the reference's density distribution.

**Result:** same as iter_027. vs. reference: no improvement. Root cause: linear iso-level spacing, not lum_mix value.

**Next:** build — switch to **quadratic iso-level spacing** in `engine/contour.py:compute_thresholds`. Replace linear `t[i] = t_min + i*step` with quadratic `t[i] = t_min + (i/N)^2 * range`. Background will receive ~39 levels (vs 64 linear) → ~11–12px spacing. Face will receive ~60 levels (vs 33 linear) → better diamond density. Prediction: closer to reference on both axes simultaneously.

---

## Iter 029–030 · 2026-05-25 · Quadratic iso-level spacing (power=1.5) [undocumented catch-up]

**Note:** These two iterations were executed but not logged. Current engine state (contour.py) shows power=1.5 quadratic spacing was implemented per iter_028's "next" recommendation. Outputs exist as iter_029.png / iter_030.png. Based on visual inspection: iter_029 showed improved background white-space vs iter_028 (flowing bands, moderate density); iter_030 was slightly denser. The power=1.5 change was the substantive improvement — current baseline entering iter_031.

---

## Iter 031 · 2026-05-25 · Baseline documentation (σ=8/30, power=1.5, lum_mix*0.70 bg)

**Hypothesis:** (baseline tick — documenting current state before next change)

**Change:** none — running canonical test to establish iter_031 baseline

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_031.svg` (paths=251, pts=129,627, t_min=116.5, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Organic wavy background bands throughout — flowing wavy lines but dense (~6–8px spacing). Face shows diamond geometry at nose/forehead. Overall density too high vs reference.
  - **Reference**: Very sparse background (large white regions between bands ~15–20px), crisp large outer diamond ring around forehead, well-defined eyes/features.
  - **Root cause identified**: Bright cyan source background should → low lum_field in background → sparse bands. But σ=30 is insufficient to blend dark hair into bright background; dark hair elements retain enough luminance variation after blur to create many iso-level crossings → background stays dense. Solution: dramatically increase background sigma.

**Result:** same as iter_030 (no change).

**Next:** build — increase background sigma σ=30 → σ=80. Source image has bright cyan background; σ=80 on 640px image averages over ~240px radius → dark hair completely absorbed into bright background average → near-uniform background luminance → sparse L1 diamond bands.

---

## Iter 032 · 2026-05-25 · Background sigma σ=30 → σ=80

**Hypothesis:** σ=30 is insufficient to homogenize dark hair into bright cyan background. With σ=80 (radius ~240px on 640px image), the weighted average of dark hair + bright cyan converges to near-global-average luminance in the background → minimal luminance variation → iso-levels become nearly pure L1 concentric diamonds → sparse, widely-spaced background bands.

**Change:** `engine/field.py:85` — changed `gaussian_filter(luminance, sigma=30)` to `gaussian_filter(luminance, sigma=80)`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_032.svg` (paths=254, pts=127,781, t_min=116.5, t_max=912.5)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: DRAMATIC improvement in background density. Top-left, bottom-left, bottom-right all show sparse widely-spaced wavy bands (~15–20px) matching the reference. Face retains good diamond ring geometry (σ=8 near seed unaffected). Top-right still has dense L1 diagonal hatching from residual metallic sparkle luminance variation even after σ=80. Overall: ~2–3× sparser background than iter_031.
  - **Reference**: Very sparse horizontal wavy background bands, large white space, crisp prominent outer diamond ring on forehead, well-defined eye/nose/chin rings.
  - **Remaining gap**: (1) top-right diagonal L1 hatching still too dense; (2) face outer diamond ring less prominent than reference; (3) band orientation slightly more concentric (ours) vs horizontal wavy (reference).

**Result:** significantly better vs. iter_031. vs. reference: closer — background density now matches in most regions, top-right still too dense.

**Next:** build — try power=2.0 (from power=1.5) in `engine/contour.py:compute_thresholds`. Should concentrate ~60% of 111 levels in face region vs current ~45%, leaving top-right corner with fewer iso-levels → less diagonal hatching. Also strengthens face diamond ring prominence.

---

## Iter 033–035 · 2026-05-25 · Undocumented [catch-up note]

power=2.0 was implemented in contour.py per iter_032 "next". lum_light sigma was reverted from σ=8 back to σ=16 (face detail slightly worse at σ=8 with power=2.0 concentrating more levels there). Outputs iter_033–035 exist. Final state entering iter_036: lum_light σ=16, lum_heavy σ=80, power=2.0, lum_mix*0.70 bg. This produced 45° diagonal corner hatching (pure L1 artifact from σ=80 making background near-uniform).

---

## Iter 036 · 2026-05-25 · Background sigma σ=80 → σ=30 (restore organic waviness)

**Hypothesis:** σ=80 makes background luminance near-uniform → field ≈ pure L1 → harsh 45° diagonal hatching in corners. σ=30 (validated in iter_013/027) retains organic luminance variation → iso-levels flow organically. Combined with power=2.0 (not available in iter_031 when σ=30 last tested), expect sparser, more organic background than iter_031.

**Change:** `engine/field.py:85` — changed `gaussian_filter(luminance, sigma=80)` to `sigma=30`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_036.svg` (paths=203, pts=111,315, t_min=131.3, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: 45° diagonal corner hatching completely eliminated. Background now shows organically flowing wavy lines throughout — much closer to reference topology. Face diamond ring structure visible around nose/forehead. Clear concentric wrapping around eye sockets. Lines are ~5-8px apart throughout.
  - **Reference**: Sparse flowing background bands (~15-20px spacing), crisp prominent diamond rings in face, large white regions between lines.
  - **Remaining gaps**: (1) Line density still too high — ~5-8px vs reference's ~15-20px background spacing. (2) Mid-range transition zone (face-to-background, t≈200-500) still moderately dense. (3) Large dominant outer diamond ring not as prominent as reference.

**Result:** significantly better vs. iter_035. vs. reference: closer — background topology now correct (organic wavy), main gap is density.

**Next:** build — increase power from 2.0 to 2.5 in `engine/contour.py:compute_thresholds`. power=2.5 concentrates ~73 levels in face (vs ~66 at p=2.0) and leaves only ~38 levels in background (vs ~46). Background spacing should increase from ~8px to ~12-15px. No other changes.

---

## Iter 037 · 2026-05-25 · power=2.0 → 2.5 in compute_thresholds

**Hypothesis:** power=2.5 concentrates more iso-levels in the face (t near t_min) and reduces background level count, yielding sparser background bands and a more prominent outer diamond ring.

**Change:** `engine/contour.py:31` — changed `f ** 2.0` to `f ** 2.5` in `compute_thresholds`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_037.svg` (paths=192, pts=102,175, t_min=131.3, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Background has flowing organic wavy lines at ~8-12px spacing — slightly sparser than iter_036. Face shows clear diamond ring geometry around forehead and nose. Concentric wrapping around eye sockets is well-defined. Total paths dropped from 203 → 192 and points from 111k → 102k (fewer/shorter lines = sparser).
  - **Reference**: Background lines ~20-30px apart with large white regions, very prominent outer diamond ring framing the entire face, dense face contours with crisp feature definition.
  - **Remaining gap**: Background still ~2x too dense. The outer forehead diamond ring visible in our output but far less prominent than reference's large enclosing diamond. Mid-range (t≈200-500) still moderately dense.

**Result:** slightly better vs. iter_036 (fewer paths/points, marginally sparser background). vs. reference: still considerably denser background.

**Next:** build — increase power from 2.5 to 3.0 in `engine/contour.py:31`. At p=3.0, ~77% of levels land in the face region (t < 350) vs ~73% at p=2.5. Background gets ~26 levels (vs ~38 at p=2.5) → estimated spacing ~16-18px, closing in on reference's ~20-30px.

---

## Iter 038 · 2026-05-25 · power=2.5 → 3.0 in compute_thresholds

**Hypothesis:** power=3.0 concentrates ~83% of 111 levels in the face region (t < field_midpoint) and leaves only ~26 levels in the background, increasing estimated background band spacing from ~12px to ~18-20px to match reference's sparse flowing bands.

**Change:** `engine/contour.py:31` — changed `f ** 2.5` to `f ** 3.0`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_021.svg` (paths=184, pts=93,841, t_min=131.3, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: MAJOR improvement in background sparsity. All four corners and edges now show large white areas with sparse widely-spaced flowing lines (~20-30px apart) — very close to reference background topology. Face region is dense with concentric ring structure. The face appears as a darker center mass with rings visible but packed close. Overall balance: background ~90% match to reference, face still too dense (individual rings not as visible as reference).
  - **Reference**: Very sparse background, crisp facial rings with features clearly visible (eye sockets, nose bridge), prominent outer diamond ring framing face.
  - **Comparison vs iter_037** (power=2.5): Background clearly improved — iter_037 had ~8-12px spacing, iter_038 has ~20-30px spacing matching reference. Face: comparable ring density but iter_038 face may be slightly over-dense (too many levels crammed in).

**Result:** better vs. iter_037 — background now matches reference sparsity. vs. reference: closer overall; main remaining gap is face density/feature clarity.

**Next:** build — try power=2.7 (middle ground between 2.5 and 3.0). At p=3.0, ~83% of levels land in face → face over-crowded. At p=2.7, ~78% → slightly fewer face levels, rings more individually visible. Background should remain sparse enough (~28-30 levels vs ~26 at p=3.0, spacing ~18-22px still matching reference).

---

## Iter 039 · 2026-05-25 · power=3.0 → 2.7 in compute_thresholds (output: iter_022)

**Hypothesis:** power=2.7 (between 2.5 and 3.0) reduces face over-crowding while keeping background sparse, improving individual ring visibility in face region.

**Change:** `engine/contour.py:31` — changed `f ** 3.0` to `f ** 2.7`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_022.svg` (paths=191, pts=98,848, t_min=131.3, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Background sparse with organic wavy flowing lines in all corners — good match to reference topology. Face region is dense with concentric ring structure but still appears as a dark mass; individual rings within face region are tightly packed. Outer diamond ring (face-background boundary) visible around forehead but not as large or prominently isolated as reference.
  - **Reference**: Very sparse background, extremely crisp large outer diamond ring clearly framing the entire face, individual face rings cleanly separated with white space between them.
  - **vs iter_021 (power=3.0)**: Marginally denser (+7 paths, +5k pts). Background quality nearly identical. Face rings barely more separated — difference from 3.0 is minimal.

**Result:** same / marginal improvement vs. iter_038. vs. reference: still considerably over-dense in face, outer diamond ring not as prominent.

**Next:** build — try power=3.5 in `engine/contour.py:31`. Higher power concentrates even more levels near t_min (face), leaving very few background levels → even sparser background. Hypothesis: extreme background sparsity isolates the outer diamond contour more clearly and makes it "pop" from the background as in reference.

---

## Iter 040 · 2026-05-25 · power=2.7 → 3.5 tried, face regressed, REVERTED

**Hypothesis:** power=3.5 would concentrate even more levels near t_min (face), leaving very few background levels → even sparser background with isolated outer diamond contour more prominent.

**Change:** `engine/contour.py:31` — changed `f ** 2.7` to `f ** 3.5` (then REVERTED back to `f ** 2.7`).

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_023.svg` (paths=176, pts=86,303, t_min=131.3, t_max=905.9)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output (power=3.5)**: Background: excellent — very sparse widely-spaced flowing organic lines in all corners, nearly matching reference spacing. Face: severely regressed — the face appears as a nearly solid dark mass with only faint ring hints visible. Individual ring structure is almost completely lost. The issue: ~90% of 111 levels crammed into face field range, contours pack so tightly they merge optically into gray/black.
  - **Reference**: Sparse background (matching our background), crisp individually-visible diamond rings throughout face with clear white separation between each ring.
  - **Key insight**: Power-law threshold adjustment alone cannot solve the face ring visibility problem. The face field gradient is too steep — whether we use power=2.7 or 3.5, the face rings stack too densely. The root cause is in the field itself, not the threshold distribution.

**Result:** worse vs. iter_039 (power=2.7) for face quality — reverted. Background was best yet, face was worst yet.

**Next:** build — smooth the field itself before contour extraction. Apply `scipy.ndimage.gaussian_filter(field, sigma=1.0)` in `engine/field.py` after field construction. This reduces gradient spikes in the face region without destroying face topology, spreading contours more evenly so individual rings become visible with white separation. Power stays at 2.7. This is a fundamentally different lever than threshold distribution.

---

## Iter 041 · 2026-05-25 · Field smoothing σ=1.0 after construction

**Hypothesis:** Field σ=1.0 smoothing would flatten gradient spikes in the face region, spreading iso-contour spacing so individual rings become more visually separated with white between them.

**Change:** `engine/field.py:107` — added `field = gaussian_filter(field, sigma=1.0)` after `field = dist_field + lum_field`.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_024.svg` (paths=191, pts=98,964, t_min=132.0, t_max=905.0)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output**: Background excellent — 4 corner regions show sparse widely-spaced flowing organic lines matching reference background topology. Face center still appears as a dark mass with faintly visible concentric rings. Diamond geometry present around nose/forehead but rings too densely packed to be individually visible. Overall topology correct, rendering contrast wrong.
  - **Reference**: Sparse background (matching ours), crisp individually-visible diamond rings with clear white separation between each ring, eye sockets/nose/chin sharply defined.
  - **Key finding**: σ=1.0 had negligible effect — stats virtually identical to iter_039 (191/98,964 vs 191/98,848). The field built from adaptive-blurred luminance is already smooth; σ=1.0 doesn't meaningfully change gradient steepness. Face ring density problem persists.
  - **New hypothesis**: The face rings may be *physically present and correctly spaced* but *visually merged* because base stroke width=1.4px at wt_range=0.0 is too thick relative to ring spacing (~4-5px). The reference appears to use thinner strokes (~0.5-0.8px pen plotter width). Reducing stroke width from 1.4 → 0.7 should reveal white space between rings without changing field or contour logic.

**Result:** same as iter_040 — negligible change. vs. reference: face rings still merge into dark mass.

**Next:** build — reduce base stroke width in `engine/export.py:25` from `1.4` to `0.7` (halving stroke width at wt_range=0.0). Hypothesis: face rings are spaced correctly but visually obscured by thick strokes; thinner strokes will reveal individual rings and white space between them, matching reference aesthetics.

---

## Iter 042 · 2026-05-25 14:30 · Stroke width 1.4→0.7 tried, REVERTED — made face worse

**Hypothesis:** Halving base stroke width from 1.4px to 0.7px would reveal white space between tightly-packed face rings that were visually merged by thick strokes.

**Change:** `engine/export.py:25` — changed `max(0.2, 1.4 - normalized_t * wt_range * 1.2)` to `max(0.2, 0.7 - normalized_t * wt_range * 0.5)` — then **REVERTED** back to 1.4.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_025.svg` (paths=191, pts=98,964, t_min=132.0, t_max=905.0) — same stats as iter_024 (stroke change is SVG-only)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output (0.7px strokes)**: Background excellent — very sparse organic wavy bands in all four corners with good white space, closely matching reference topology. Face center: WORSE than 1.4px — thin 0.7px strokes on tightly packed rings (~4-5px spacing) produce a smooth gray gradient wash rather than visible distinct rings. The face reads as a featureless gray smear. Diamond geometry at the nose/forehead boundary faintly visible but washed out.
  - **Reference**: Crisp, wide, clearly-separated diamond rings with strong black strokes and visible white between each ring.
  - **Key finding**: The face rings are NOT correctly spaced — they are genuinely too close together. Halving stroke width reveals this: with 0.7px strokes on rings that are ~2-4px apart in the inner face zone, you still get gray wash, just lighter. The problem is **physical ring density**, not stroke width.
  - **Root cause**: power=2.7 concentrates ~77% of 111 iso-levels into the face zone field range. Inner rings near seed are ~2-3px apart in physical space — too close to see even with thin strokes. Reference's rings are ~8-12px apart.

**Result:** worse vs. iter_041 — face more washed out. REVERTED. vs. reference: no improvement.

**Next:** build — reduce face lum_mix from 1.0 to 0.5 by applying a spatial weighting in the face zone of `engine/field.py`. With lower face lum contribution, the face field gradient flattens → inner rings spread farther apart physically → individual rings become visible with white space between them. Background lum_mix=1.0 stays unchanged. Hypothesis: face ring spacing ≈ doubles, matching reference's widely-separated rings.

---

## Iter 043 · 2026-05-25 · Face zone lum_mix factor 1.0 → 0.5 (spatial weighting)

**Hypothesis:** Reducing the face-zone lum_mix factor from 1.0 → 0.5 (in `effective_lum_mix` computation) flattens the face field gradient, spreading iso-contour rings farther apart physically so individual rings become visible with white space between them. Background factor (0.30) remains unchanged.

**Change:** `engine/field.py:101` — changed `(1.0 - dist_weight) * 1.0` to `(1.0 - dist_weight) * 0.5` in `effective_lum_mix` formula.

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_038.svg` (paths=178, pts=97,006, t_min=99.0, t_max=859.4)
- reference: `examples/contour_woman_post2.jpeg`
- visual comparison:
  - **Our output (face_factor=0.5)**: MAJOR IMPROVEMENT — face now shows clearly visible individually-separated diamond rings with white space between them. No longer a dark mass. Concentric diamond geometry correct: large outer ring frames the face, eye sockets, nose, chin all deflect rings with recognizable topology. Center of face (innermost rings) still somewhat dense but individual rings discernible. Background: sparse organic parallel bands in 4 quadrants, slightly more complex than reference but close.
  - **Reference**: Very sparse background, face rings with ~8-12px white space between each ring, large outer diamond prominently framing face, all facial features cleanly separated. Individual rings visible throughout entire face with no dark-mass zones.
  - **vs iter_025 (power=2.7, face_factor=1.0)**: Substantially better — t_min dropped 132→99, paths 191→178. Face structure now clearly visible where it was a dark mass before. White space between rings real and significant.
  - **Remaining gap**: Center of face rings slightly more dense than reference (~4px vs ~8px spacing near center). Background slightly more undulating than reference's straighter parallel bands.

**Result:** better — clear improvement vs. all prior iterations. vs. reference: closest match yet on face ring visibility; small gap remains on inner ring spacing.

**Next:** build — try face_factor 0.5 → 0.35 to further reduce inner-face gradient steepness and widen ring spacing near seed. Power stays at 2.7. Hypothesis: inner rings will spread to ~6-8px spacing, matching reference's well-separated inner rings.

---

## Iter 044 · 2026-05-25 12:10 · Three-way probe (all REVERTED) — chaos diagnosis

**Hypothesis:** Tried three separate hypotheses to address iter_28's judge complaint of "significantly higher and more chaotic than reference": (A) face_factor 0.5→0.35 to widen ring spacing, (B) sigma_light 16→24 to reduce texture noise, (C) min_path_length 30→80 to eliminate small loops.

**Changes attempted (all reverted):**
- A: `engine/field.py:101` — face_factor 0.5→0.35 → REVERTED
- B: `engine/field.py:84` — sigma_light 16→24 → REVERTED
- C: `engine/contour.py:66` — min_path_length 30→80 → REVERTED
- Final state: identical to iter_28 baseline (face_factor=0.5, sigma_light=16, min_path_length=30, power=2.7, field_sigma=1.0)

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_029.svg` (paths=178, pts=97,006, t_min=99.0, t_max=859.4)
- reference: `examples/contour_woman_post1.jpeg`
- visual comparison:
  - **iter_28 (baseline, judge=75)**: Recognizable portrait of the woman — face clearly visible with eye sockets, nose, chin in contour topology. Lines denser and more chaotic than reference (many small irregular loops in face zone mixed with large topology rings). Background sparse and clean.
  - **A (face_factor=0.35)**: Complete failure — judge=15, "abstract geometric pattern." Face lum contribution so low the field was essentially radial; no facial topology at all. t_min dropped to 73.0, paths=152.
  - **B (sigma_light=24)**: judge=15 again — too much blur eliminated facial feature detail (eye sockets, nose are ~50-100px features that sigma=24 smooths away). paths=153.
  - **C (min_path_length=80)**: judge=15 — filtering out paths of 30-79 points removes the facial sub-feature rings (eye socket closed loops are short-perimeter paths), leaving only large rings that look like an abstract bullseye.
  - **Key diagnostic**: All three approaches to reduce chaos also eliminated the face. The face and chaos are tightly coupled because both arise from the luminance signal — you cannot reduce one without the other using simple blunt cuts.

**Score:** judge=75 ssim=0.0469 edge_iou=0.1218 path_fit=None
            · vs last 3 avg: judge Δ0 (no improvement)

**Result:** same — all changes reverted. Code is clean at iter_28 baseline.
vs. reference: same gap as iter_28 (chaotic face zone, 178 vs 452 paths)
vs. iter_014 (anchor 95): 20 points below

**Next:** build — increase field_sigma from 1.0 to 3.0 in `engine/field.py:108`. Hypothesis: field_sigma=1.0 smooths out 1px gradient spikes but leaves 2-3px irregularities that create small closed loops. sigma=3.0 smooths those without affecting the large-scale face topology (which has gradients spanning 50-200px). This targets "chaos" without touching the luminance contribution that creates facial features.

---

## Iter 045 · 2026-05-25 14:45 · Restore power=2.7 spacing + σ=16→σ=8 face blur (combined)

**Hypothesis:** Two regressions identified: (1) contour.py was changed from `f**2.5` (baseline) to linear `f * field_range`, eliminating the power spacing that concentrates iso-levels in the face zone; (2) field.py σ=16 face blur was too smooth vs σ=8 which was used in the excellent iter_027 output. Combining power=2.7 restoration with σ=8 face blur should recover and exceed baseline quality.

**Change:**
- `engine/contour.py:31` — restored `f * field_range` (linear/regressed) → `f ** 2.7 * field_range` (power spacing)
- `engine/field.py:84` — changed `sigma=16` → `sigma=8` for face zone blur

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_034.svg` (paths=230, pts=107,457, t_min=116.5, t_max=905.9)
- reference: `examples/contour_woman_post1.jpeg`
- visual comparison:
  - **iter_034 (this tick)**: Clear facial silhouette with recognizable eyes/nose/features. Background shows organic flowing bands with reasonable white space — much improved over iter_033's heavy center. Face is visible but center still slightly dark compared to reference. Diamond ring structure present.
  - **iter_033 (prior, power=2.7 only, σ=16)**: Better than iter_038 but face still a dark mass; background organic.
  - **Reference**: Thin individual diamond rings clearly separated, crisp face detail, sparse background.
  - **Judge note**: "clear contour-line portrait with characteristic concentric diamond/ring structure and recognizable facial features, matching the reference style" — no density complaint this tick.

**Score:** judge=85 ssim=0.0667 edge_iou=0.1136 path_fit=None
            · vs last 3 avg (75): judge +10

**Result:** better — significant improvement from 75→85. vs. reference: closer.
vs. iter_014 (anchor 95): 10 points below.

**Next:** build — try power=2.5 (baseline commit value) instead of 2.7, keeping σ=8. With σ=8 face blur creating crisper gradients, power=2.7 may over-concentrate levels in the face zone making it too dense. Power=2.5 was the historically validated value when face detail was best (iter_014 area). Hypothesis: power=2.5 + σ=8 reduces face center density while preserving the organic background topology we now have.

---

## Iter 046 · 2026-05-25 14:15 · Try power=2.5 (baseline) instead of 2.7 — REVERTED

**Hypothesis:** Power=2.5 (committed baseline) + sigma=8 reduces face density vs power=2.7. Historically 2.5 was the baseline when iter_014 scored 95.

**Change:**
- `engine/contour.py:31` — changed `f ** 2.7` → `f ** 2.5`
- `engine/field.py:84` — sigma=8 unchanged (from iter_034)

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00, lum_mix 1.0, wt_range 0.0)
- output: `loop/output/iter_035.svg` (paths=232, pts=111,033, t_min=116.5, t_max=905.9)
- reference: `examples/contour_woman_post1.jpeg`
- visual comparison: Face visible with flowing bands, but judge saw "dark, smudgy blob where facial features are completely obscured by over-dense linework". Power=2.5 concentrates more iso-levels at lower field values (face zone), creating over-dense linework despite visual similarity to iter_034.

**Score:** judge=15 ssim=0.0599 edge_iou=0.1137 path_fit=None
            · vs last 3 avg (81.7): judge -66.7

**Result:** WORSE — catastrophic regression 85→15. **REVERTED** engine/contour.py back to `f ** 2.7`.

**Analysis:** The key insight is that iter_014 scored 95 but did NOT use power=2.5 + sigma=8. It used sigma=16 (the committed baseline). The sigma=8 change (which helps in general) interacts badly with power=2.5 because: sigma=8 creates sharper local luminance gradients, which means more iso-levels cross through the same spatial area in the face zone. When combined with power=2.5's already aggressive face-zone concentration, the face becomes overly dense. Power=2.7 with sigma=8 is a better balance.

**Next:** build — instead of changing power, try adjusting the field's weight_range parameter. The `wt_range=0.0` param controls how much distance weighting is mixed into the field. Try `wt_range=0.1` which would slightly spread iso-levels away from seed toward background — potentially opening up the face center while keeping background organic. Hypothesis: small positive wt_range with power=2.7 + sigma=8 is the missing ingredient to reach 90+.

---

## ⚠️ Numbering reconciliation (2026-05-31, harness-stabilization)

The `## Iter NNN` headers above DRIFTED ahead of the real tick counter.
Source of truth for what was actually rendered/scored is `loop/.iter` +
`loop/metrics.jsonl`, NOT these headers. Known mapping:

- log "Iter 045" → ralph tick **34** (output iter_034, metrics judge=15)
- log "Iter 046" → ralph tick **35** (output iter_035, metrics judge=15)

So per `metrics.jsonl` the last good scored render is **iter_033 (judge 85)**;
ticks 34–35 regressed to 15 and the engine was reverted to the power=2.7
config (now committed as the baseline). From tick 36 on, the header number
is pinned to `$(cat loop/.iter)` (see PROMPT.md) so this can't recur.

Also note: the judge 85↔15 swings on near-pixel-identical renders were
largely judge NOISE — `judge.py` now takes the median of `--samples 3` to
de-noise, and `guard_tick.sh` gates on that median.

---

## Iter 039 · 2026-06-08 19:00 · new d_fine climb metric + MARCH_TONE 4.0→4.6

**Context:** `d_score` is SATURATED at 100 on the canonical woman — knob-tuning had
no signal to climb (confirmed by tries this session: blur↑ and base↑ both kept
d_score=100 while trading tone fidelity for hatch cleanliness, the documented
"honest limitation"). Probed three global "fine/clean hatch" discriminators
(structure-tensor coherence, spectral fineness, connected-component fragmentation)
— ALL non-discriminating: the good-output manifold is too wide (moire/seed_blob
out-score good women on coherence; woman-dens centroid 30 vs woman-4 103). Only a
SOURCE-RELATIVE signal separates cleanly.

**Hypothesis:** Fine-grid tonal fidelity (SSIM of output ink-density vs source
darkness at grids 96/128, finer than d_tone's 16/32/64) gives real headroom on the
dense canonical render while staying robust (negatives crushed), so it can be the
loop's climb signal above the d_score ceiling.

**Change:**
- `loop/dscore.py` — added `fine_tone()` + `d_fine`/`d_fine96`/`d_fine128`,
  REPORTED-ONLY (NOT in d_score → calib gate untouched, stays 14/0 green).
- `loop/guard_tick.sh` — added `regression-fine` FAIL on `d_fine` drop
  > `GUARD_FINE_DROP` (0.04) so a tick can't trade away fine-hatch while d_score holds.
- `engine/march.py` — `MARCH_TONE` 4.0→4.6 (first real climb tick: denser shadows
  → better fine-scale local tone).
- Docs: PROMPT.md, IDEAS.md, CLAUDE.md updated to steer by `d_fine`.

**Test:** canonical (woman-source, centered seed, levels 111, method=march)
- d_fine corpus: ours-036 0.443 → ours-039 **0.470** (↑); artist woman-2 **0.696**
  (the climb target); finer-hatch render (levels 150) 0.513 (confirms lever);
  negatives moire 0.096, tone_invert −0.377 (crushed).
- Guard verified: PASS on the 0.470 gain; FAIL (revert) on a forced regression
  (heavy blur → d_fine 0.364 < 0.470−0.04) while d_score still 100.
- visual: iter_039 shadows/hair slightly more modeled vs 036; not blown (d_ink 0.41).

**Score:** `iter 39: d_score=100 d_fine=0.4704 (96=0.5108 128=0.43) d_tone=0.7217 d_ink=0.4144 d_diag=0.4949`

**Next:** build — push `d_fine` toward 0.73 with finer/denser hatch (levels↑ or a
finer field), watching `d_ink`<0.85 and `d_diag` in 0.45–0.60.

---

## Iter 040–048 · 2026-06-08 · d_fine climb (0.443 → 0.534)

Steering by the new `d_fine` signal (d_score saturated at 100 throughout). Kept
`d_diag` in band (~0.50) and `d_ink` well under the 0.85 gate.

| tick | change | d_fine | d_diag | d_ink | verdict |
|---|---|---|---|---|---|
| 40 | CONTRAST 1.4→1.7 | 0.479 | 0.491 | 0.426 | keep ↑ |
| 41 | GAMMA 1.0→1.25 | 0.463 | 0.493 | 0.417 | revert ↓ (mids flattened) |
| 42 | TONE 4.6→5.2 | 0.497 | 0.485 | 0.434 | keep ↑ |
| 43 | TONE 5.2→5.8 | 0.515 | 0.480 | 0.444 | keep ↑ |
| 44 | TONE 5.8→6.4 | 0.527 | 0.476 | 0.451 | keep ↑ (d_diag eroding) |
| 45 | EDGE 4.0→5.0 | 0.500 | 0.469 | 0.449 | revert ↓ (edge bunching) |
| 46 | BASE 0.3→0.4 | 0.524 | **0.498** | 0.429 | keep (restored diamonds, flat d_fine) |
| 47 | TONE 6.4→7.2 | 0.531 | 0.488 | 0.438 | keep ↑ |
| 48 | CONTRAST 1.7→2.0 | **0.534** | 0.495 | 0.438 | keep ↑ (peakedness 7.38) |

**Best config:** `MARCH_BASE=0.4 TONE=7.2 EDGE=4.0 GAMMA=1.0 CONTRAST=2.0` (BLUR 2.0).
Visual (iter_048): clean diamond hatch, strong tonal modeling, deep eye/hair
shadows, recognizable — best render to date. d_fine 0.534 vs artist 0.73 (closed
~32% of the baseline gap). TONE was the dominant lever (diminishing returns + slow
d_diag erosion, countered by BASE↑); CONTRAST independent + clean; GAMMA↑ and EDGE↑
both regressed.

**Next:** externalize the MARCH_* knobs + multi-input black-box optimizer (see below).

---

## Iter 049 · 2026-06-08 · externalized config + black-box optimizer (d_fine 0.534 → 0.686)

**Built (user-requested infra):**
- **Externalized knobs**: the 6 `MARCH_*` values now live in `engine/march_params.json`
  (loaded at import, overrides in-code defaults). `engine.march` exposes
  `current_params/apply_params/save_params/load_params` + `PARAM_BOUNDS`. app.py's
  per-request overrides still ride on top; the loop now edits the JSON.
- **Optimizer** `loop/optimize.py`: derivative-free (pipeline isn't differentiable),
  Latin-hypercube explore + Nelder-Mead polish. Multi-input CONSTRAINED objective —
  maximize woman `d_fine` (meaningful only on the dense woman) s.t. the SAME params
  stay valid on samurai+space (per-source `d_score` floor + `d_ink`<0.85 + woman
  `d_diag`∈[0.45,0.60]). `d_score` is the cross-input generalization guard, so it
  can't overfit the metric's blind spots.

**Run:** `--evals 100 --polish` (124 evals, ~2 min). Winner (feasible):
`BASE 0.324, TONE 12.0, EDGE 0.857, GAMMA 0.6, CONTRAST 1.425, BLUR 1.85` — a region
hand-tuning never reached (TONE at the rail, EDGE+GAMMA low). Detail: woman
d_score=100 **d_fine=0.686 (96-grid 0.729 ≈ artist woman-2's 0.730!)** d_ink=0.478
d_diag=0.468; samurai d_score=91; space d_score=97.

**Visual (iter_049):** best render to date — face smoothly modeled, fine clean
diagonal hatch, eyes/brows/lips defined, shadows rich but not solid. Better both
metrically AND visually (not metric-gaming). Closed ~85% of the baseline→artist gap.

**Stopped here** (didn't widen bounds past TONE=12): pushing further risks driving
`d_fine` into the metric's necessary-not-sufficient blind spot. All gates green
(calib 14/0, harness 4/0 incl. holdout, unit 6/6).

**FOLLOW-UP (flagged, not done):** `app.py` UI clamps `march_tone` to (0,6) etc. —
narrower than the optimizer's `PARAM_BOUNDS` (TONE→12). The web UI would clamp the
tuned config; widen those ranges to match. (app.py has unrelated uncommitted edits,
left untouched.)

**Next:** more inputs in the optimizer set; or widen bounds + re-run with tighter
visual review; or back to the ralph loop for a structurally finer hatch.
