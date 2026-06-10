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

**How to use this each tick:** read `loop/STATUS.md` first — it shows the LIVE knob
values + their bounds (from `engine/march_params.json` / `PARAM_BOUNDS`) and the
recent `d_fine`/`d_score`/`d_fidelity`/`d_tone`/`d_diag`/`d_ink` trend. Find the ONE
matching symptom below, then make a small bounded move FROM the current value shown in
STATUS.md (this menu gives directions, not numbers — the numbers live in the JSON so
they can't go stale). Don't nudge the same knob twice in a row — if the last 2 ticks
touched a knob and `d_fine` didn't move, pick a different symptom.

## The menu — symptom → direction (all knobs in engine/march_params.json)

| If the symptom is… | Move (one small step from the live value in STATUS.md) |
|---|---|
| Hatch too COARSE to render fine local tone (`d_fine` low/flat) | finer/denser hatch: `levels` up, or `MARCH_FLOOR` down |
| Output doesn't render the image's TONES (`d_tone` low) | `MARCH_FLOOR` down (darks bunch denser) |
| Diamonds too STIFF/geometric (`d_diag` above band) | `MARCH_BASE` down (image warps more) |
| Diamonds OVER-warped / no diamond read (`d_diag` below band) | `MARCH_BASE` up |
| Dark regions go SOLID black / muddy (`d_ink` high) | `MARCH_FLOOR` up, or `MARCH_CONTRAST` up |
| Feature boundaries (eyes/nose/jaw) not defined | `MARCH_EDGE` up |
| Subject washed out / midtones flat (`d_fidelity` low) | `MARCH_CONTRAST` up, or `MARCH_GAMMA` up |
| Background busy / noisy fine lines (`d_peakedness` low) | `MARCH_BLUR` up, or `MARCH_BASE` up |
| Output too dense / too sparse overall | `levels` (render param) down / up |

Keep moves small (one step in the suggested direction, staying inside the knob's
bounds shown in STATUS.md). If a move helped (raised `d_fine` without dropping
`d_score`), the guard keeps it; next tick address the next gap. NOTE on `d_fine`:
heavy `MARCH_BLUR` lowers it (kills fine detail); denser/finer hatch raises it — but
watch `d_ink` (too high trips the gate to 0).

**Knobs live in `engine/march_params.json`** (overrides the `march.py` defaults) —
edit that JSON to tune one per tick. **To sweep all 6 at once** (better than
one-per-tick hand-tuning), run `python loop/optimize.py --evals 100 --polish`: a
constrained black-box search that maximizes woman `d_fine` while keeping
samurai+space valid, and writes the winning JSON. The hand menu above is for
single-knob reasoning / understanding *why* a move helps; the optimizer is for
finding the joint optimum (knobs interact — e.g. `BASE`↑ recovers the `d_diag` that
`FLOOR`↓ erodes).

## ⚠️ Scorer calibration debt (2026-06-09, post-reciprocal-cost)
The first optimizer run on the reciprocal surface maximized woman `d_fine` to
0.62 — and produced a render VISUALLY WORSE than the hand defaults (stiff
diamond grain, solid darks lost; see `loop/optimize_log.jsonl`). Two causes:
(1) `d_fine` rewards uniform fine hatch over the artist's solid-ink dark
saturation; (2) the `d_diag`/diamond window + the woman `d_score` floor of 95
penalize the stronger image-warp of the artist-accurate look (the defaults
score 93 — *below the optimizer's own feasibility floor* — while matching the
artist best). Until the scorer is recalibrated against the new engine (rescore
the artist examples, re-fit the diamond window, reconsider what `d_fine`
measures), treat optimizer output as a CANDIDATE to eyeball against
`examples/`, not an auto-win. The committed `march_params.json` is the
visually-validated config, not the metric optimum.

## Notes / breadth (lower priority)
- `MARCH_FLOOR` is THE tone lever (reciprocal cost: speed floor → how dark the darks
  go; lower = solid-ink shadows). `MARCH_BASE` trades diamond-stiffness vs
  image-warp. They interact — keep moves to one per tick.
- `MARCH_CONTRAST / MARCH_GAMMA` are the CONTOUR-V STUDIO tonal controls baked into
  march's `_preprocess_gray` (percentile-normalize → contrast → gamma).
- A bounded formula tweak inside `build_march_field` / `_preprocess_gray` is allowed
  (e.g. how cost combines tone+edge) — but as ONE small copy-verbatim SEARCH/REPLACE.
- The parked methods (wave/flow/contour) and their WAVE_*/FLOW_*/FIELD_* constants do
  NOT affect the march render — don't edit them.
- Mark tried ideas with their result (✅ better / ➖ same / ❌ worse + score).
