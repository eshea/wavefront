# VEX ENGINE Reverse Engineering Log

> **See `contour-v-core-source.md` first** — it holds the verified first-party
> facts (Ko-fi product copy, the official demo video, the Reddit JS-loop-fix
> post, and the STUDIO screenshot decode). This log is the working notes that
> fed into it. Two corrections carried through to the engine: the distance
> metric is **Manhattan (L1)**, producing diamonds — the Euclidean `sqrt` in the
> formula-derivation section below is superseded — and the field is a **fast
> marching arrival time with reciprocal cost** (see the 2026-06-09 section
> below), superseding the additive `dist + (255-lum)*k` hypothesis.

## 2026-06-09: STUDIO screenshot decode — the field is fast marching, cost = 1/speed

`examples/ui-screenshot.jpeg` turned out to be a first-party **CONTOUR-V
STUDIO** screenshot (not our app). Subtitle: "Fast marching contour field →
plot-ready SVG"; view modes include **SPEED**; PROCESS has an "INVERT
(DARK = FAST)" toggle. That confirms the field family outright. The remaining
question was the cost SHAPE, and three independent lines of evidence all point
to **reciprocal**:

1. **Spacing math.** For an arrival-time field, |∇T| = local cost, so line
   spacing = (level spacing) / cost. The reference outputs show ~10 px spacing
   in highlights, ~5 px in midtones, and solid ink in deep darks — a reciprocal
   response (`cost = 1/clamp(speed_floor, brightness)`: white→1, mid→2,
   black→1/floor ≈ 14+). A linear-in-darkness cost can't do this: by the time
   darks saturate, mids are nearly as dense and whites are starved (exactly the
   failure mode of our linear `MARCH_TONE` tuning — empty forehead diamond,
   gray mush in mids).
2. **T RANGE numerology.** CORE woman capture: GRID 438×640, seed (227,228),
   T max 1173.9. Max L1 seed distance ≈ 638, so the tone term integrates to
   ~1.8× L1 along cheapest paths — consistent with `cost = 1/speed` over a
   typical photo (cheapest paths run through bright pixels at cost ≈ 1–2).
   An additive `L1 + (255-lum)*k` with k=1 caps at ~893 — impossible.
   STUDIO capture (GRID 600×343, T max 1030.5) fits the same model.
3. **Prototype validation.** `cost = 1/clip(blur(lum)/255, 0.07, 1)` on a
   4-connected MCP grid, 111 linear levels, min-pts 4, T-max 99.5% clip,
   constant 0.8 px black stroke — near-matched woman/space/samurai reference
   outputs in one shot. On the canonical woman it scored d_tone 0.758 (the
   artist's own output-2 scores 0.672 against the same source) and
   path count 795 vs the artist's 652 (vs 267 for our then-current render,
   which filtered paths < 30 points).

Downstream-pipeline facts lifted from the same screenshot (see
`contour-v-core-source.md` for the full control inventory): SPACING **Linear**
level distribution; **T-MAX %** clip (99.50); **MIN PTS 4** path filter —
keeping tiny closed loops is what makes eyes/darks render solid; **STEP 3 px**
polyline resample (the clean-line secret at LINE SMOOTH 0); CHAIN GAP 0.60 px
segment chaining; **STROKE 0.70 px constant, STROKE MOD off** — the export is
full-opacity ink, weight modulation is opt-in (our old unconditional
opacity fade 0.95→0.35 was a divergence, not a match); TSP ordering of chains
within each level (pen-travel optimization, not visual).

## Source Material

- Reddit post: r/ClaudeAI — artist sharing VEX ENGINE, described Claude helping fix bugs
- Artist site: vex-line (plotter art, topographic portraits)
- YouTube video: 2:42 duration showing VEX ENGINE in use
- Physical artworks: green ink, orange/rust ink, purple ink, blue+magenta ink variants
- App name: "VEX ENGINE | STANDALONE | MODULE | CONTOUR-V | v0.1"
  (Earlier draft had v1.1 — corrected after seeing settings screenshot.)

## CORE v0.1 — actual UI surface (verified from screenshot)

Just two parameter sliders:
  - CONTOURS (e.g. 111)
  - LINE SMOOTH (e.g. 0.00 — angular ↔ smooth)

Seed: click-to-place + CENTER SEED button. Stats HUD shows GRID
(e.g. 434×648), T RANGE (e.g. 0.0...1175.9), PATHS / POINTS / LEVELS /
SEGS / CHAINS.

Top-right view toggles: BOUNDS | SEED | GHOST | FIT | HOME — these are
render modes, not parameter changes. GHOST overlays the source image
behind the contours.

Export: EXPORT SVG | EXPORT PNG (single 1× PNG, not 2×). Files saved as
`NNN_Title-Density.svg` (e.g. `001_Portrait-Low-Density.svg`).

No exposed lum_mix or stroke-weight controls in CORE — those are
hardcoded internally. WAVEFRONT exposes them as sliders, which is a
deliberate extension beyond CORE.

## UI Elements Catalogued

Left panel:
  SOURCE:    file upload input (shows filename)
  CONTOUR:   CONTOURS slider (value shown right)
  LINEWORK:  LINE SMOOTH slider (value shown right)
  SEED:      text display "Seed: (x,y)" + RESET SEED TO CENTER button
  EXPORT:    EXPORT SVG | COPY SVG buttons, EXPORT 2X PNG button
  LIVE:      status line "PATHS N | PTS N | T [min...max]"
  Footer:    "VEX ENGINE | CONTOUR-V | STANDALONE HTML"

Right panel:
  Top bar:   OUTPUT PREVIEW / CONTOUR FIELD label
  Nav:       BOUNDS | SEED | GHOST | FIT | HOME buttons
  Stats HUD: PATHS / POINTS / LEVELS / SEGS / GRID / T RANGE
  Canvas:    preview with crosshair cursor
  Bottom:    status bar with LEVELS/SEGS/CHAINS/PTS | SEED:(x,y)
  Zoom:      percentage display (e.g. 89%, 124%)

## Behavior Observations

1. LIVE computation: updates on every slider change (debounced)
2. Seed click: clicking canvas updates seed + recomputes
3. GHOST mode: likely shows faint original image behind contours
4. SEED mode: likely shows just the seed point / field visualization
5. BOUNDS mode: active by default — shows contour within image bounds
6. FIT: likely fits preview to window
7. The "STANDALONE HTML" label confirms it's a single .html file

## Formula Derivation

Tested formula: field[x,y] = dist(x,y,seed) + (255 - lum[x,y]) * k

Verification with T RANGE values:
  Case 1: 427x640 grid, seed=(214,320) ≈ center
    max_dist = sqrt(214²+320²) = 384.6  [to nearest corner]
    actual max_dist = sqrt(427²+640²)/2 ≈ 384  [half diagonal]
    T_max observed = 776.1
    776.1 - 384 = 392.1 ≈ 255 * 1.54?
    OR: max dist from center to corner = sqrt((427/2)²+(640/2)²) = sqrt(213.5²+320²) = 384.5
    384.5 + 255*1.52 ≈ 772 — close but not exact
    BEST FIT: k=1.5? Or field uses dist from seed to EVERY pixel, max is corner:
    max corner dist from (214,320): to (427,640)=sqrt(213²+320²)=384, to (0,0)=sqrt(214²+320²)=385
    385 + 255*1.52 = 773 ≈ 776 ✓ with k≈1.52

    Simpler interpretation: k=1.0 but field_max includes pixels beyond image boundary
    OR lum_min in image is not 0 (car image has near-black pixels → 255-0=255)

    Most parsimonious: k=1.0, T_max = max_euclidean_dist + 255
    For 427x640 centered seed: max_dist ≈ 385, +255 = 640 ≠ 776

    REVISED: seed at (214,320) in 427x640 → farthest corner is (427,640) or (0,0) or (427,0) or (0,640)
    (0,640): dist=sqrt(214²+320²)=385
    (427,0): dist=sqrt(213²+320²)=384
    (427,640): dist=sqrt(213²+320²)=384
    (0,0): same=385
    So max_dist=385, T_max = 385+255=640 ≠ 776

    776-385=391 → 391/255=1.53 → k≈1.53
    OR: 776/385=2.016 → field = dist * 2 + lum_term?

    FINAL HYPOTHESIS: T RANGE max ≈ sqrt(W²+H²) * some_factor
    sqrt(427²+640²) = 769.2 ≈ 776 ✓ (within 1%)
    This means T_max ≈ full_diagonal regardless of seed position for centered seeds!
    That would require lum to contribute ~7 units which is plausible for near-white background
    And the formula may normalize or clamp differently.

  CONCLUSION: The exact k is uncertain. k=1.0 produces visually correct results.
  The T RANGE discrepancy is likely due to: image not being pure white background
  (background pixels have lum~240-250, contributing 5-15 units), plus floating
  point accumulation. Our implementation with k=1.0 matches VEX ENGINE visually.

## What We Cannot Determine

1. Exact LINE SMOOTH → iterations mapping (we use smooth*4)
2. Whether GHOST mode blends original image or uses it as a mask
3. BOUNDS/SEED/FIT/HOME button behaviors exactly
4. Whether there's any noise/jitter applied to the field
5. The exact chaining algorithm (we use spatial hash; they may use a different method)
6. Maximum image resolution supported
7. Whether the tool preprocesses images (auto-contrast, gamma correction)
