# WAVEFRONT march-field knob menu (pick ONE per tick)

Canonical render is `method=march` (`engine/march.py` `build_march_field` — a
4-connected **geodesic** where dark/edge pixels cost more, so contours BUNCH where
the image is dark: tone-driven density that RENDERS the image's tones, while
4-connectivity keeps L1 **diamonds**), levels 111, lum_mix 0.8, 780px raster.
Target = the dense CONTOUR-V portrait on `examples/woman/woman-source.jpeg`
(→ `woman-sample-output-2.jpeg`). Score = deterministic `d_score` (0–100,
`loop/dscore.py`): **tone-fidelity** (`d_tone`: does the output's local ink density
reproduce the SOURCE's tones?) is the dominant term, plus a **diamond factor**
(`d_diag`≈0.50 peak) and style. With the tuned march defaults the canonical already
renders tone well (`d_tone`≈0.74, d_score ~100). Keep `d_tone` high and `d_diag`
in ~0.45–0.60 while pushing the look closer to the artist. **`d_score` is already
100 on the canonical (saturated) — the live climb signal is `d_fine`** (fine-grid
tone fidelity, baseline ≈0.47 → artist ≈0.73; see PROMPT.md). Raise `d_fine` while
keeping `d_score`=100 and `d_diag` in band.

**How to use this each tick:** read the latest metrics (`d_fine`, `d_score`,
`d_fidelity`, `d_tone`, `d_diag`, `d_ink`), find the ONE matching symptom below,
make that one bounded move. Don't nudge the same knob twice in a row — if the last
2 ticks touched a knob and `d_fine` didn't move, pick a different symptom.

## The menu — symptom → knob move (current → try), all in engine/march.py

| If the symptom is… | Change | Current → try |
|---|---|---|
| Hatch too COARSE to render fine local tone (`d_fine` low/flat) | finer/denser hatch: `levels` up, or `MARCH_TONE` up | 111→130 / 4.6→5.2 |
| Output doesn't render the image's TONES (`d_tone` low) | `MARCH_TONE` up (darks bunch denser) | 4.6 → 5.2 |
| Diamonds too STIFF/geometric (`d_diag`>0.62) | `MARCH_BASE` down (image warps more) | 0.3 → 0.2 |
| Diamonds OVER-warped / no diamond read (`d_diag`<0.45) | `MARCH_BASE` up | 0.3 → 0.5 |
| Dark regions go SOLID black / muddy (`d_ink`>0.7) | `MARCH_TONE` down, or `MARCH_CONTRAST` up | 4.6→4.0 / 1.4→1.8 |
| Feature boundaries (eyes/nose/jaw) not defined | `MARCH_EDGE` up | 4.0 → 5.0 |
| Subject washed out / midtones flat (`d_fidelity` low) | `MARCH_CONTRAST` up or `MARCH_GAMMA` >1 | 1.4→1.8 / 1.0→1.3 |
| Background busy / noisy fine lines (`d_peakedness` low) | `MARCH_BLUR` up, or `MARCH_BASE` up | 2.0→3.5 / 0.3→0.5 |
| Output too dense / too sparse overall | `levels` (render param) down / up | 111 → 90 / 130 |

Keep moves small (one step in the suggested direction). If a move helped (raised
`d_fine` without dropping `d_score`), the guard keeps it; next tick address the
next gap. NOTE on `d_fine`: heavy `MARCH_BLUR` lowers it (kills fine detail);
denser/finer hatch raises it — but watch `d_ink` (>0.85 trips the gate to 0).

## Notes / breadth (lower priority)
- `MARCH_TONE` is THE tone-fidelity lever (darkness→cost→denser lines). `MARCH_BASE`
  trades diamond-stiffness vs image-warp. They interact — keep moves to one per tick.
- `MARCH_CONTRAST / MARCH_GAMMA` are the CONTOUR-V STUDIO tonal controls baked into
  march's `_preprocess_gray` (percentile-normalize → contrast → gamma).
- A bounded formula tweak inside `build_march_field` / `_preprocess_gray` is allowed
  (e.g. how cost combines tone+edge) — but as ONE small copy-verbatim SEARCH/REPLACE.
- The parked methods (wave/flow/contour) and their WAVE_*/FLOW_*/FIELD_* constants do
  NOT affect the march render — don't edit them.
- Mark tried ideas with their result (✅ better / ➖ same / ❌ worse + score).
