# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WAVEFRONT is a Flask web app that turns an image into topographic contour line art, replicating and extending the VEX-LINE / CONTOUR-V plotter aesthetic. Image brightness is treated as elevation that warps a Manhattan-distance (diamond) field; isolines are extracted via Marching Squares, smoothed, scaled to original dimensions, and exported as plotter-ready SVG.

The repo has two halves: the **engine + web app** (the product) and the **`loop/` ralph harness** (a self-driving quality-iteration loop that tunes the engine against reference images).

**Replication target.** WAVEFRONT replicates **CONTOUR-V CORE** by Robert T Wilson (VEX-LINE) — a $9 standalone-HTML contour tool with two sliders (CONTOURS, LINE SMOOTH) + click-to-place seed. We match CORE behavior; its paid upgrade **CONTOUR-V STUDIO** (contrast/gamma/geometry controls) is our feature roadmap. The full target spec, verified from the artist's own product copy, demo video, and Reddit posts, is in `docs/contour-v-core-source.md` — **read it before changing the field algorithm.**

## Keep docs in sync

Treat `docs/` as a first-class deliverable, not an afterthought. When you change engine behavior, the field formula, tuning knobs, or the pipeline, **update the relevant doc in the same change** so docs never drift from code. The docs are organized by concern (see `docs/README.md`): `vision.md` (what/why), `tech.md` (stack + architecture), `algorithm.md` (the current pipeline), `contour-v-core-source.md` (the replication target), plus the reverse-engineering notes. If a doc describes removed behavior, fix or flag it rather than leaving it stale.

## Commands

```bash
# Setup / run the app
source .venv/bin/activate
pip install -r requirements.txt
python app.py                      # serves http://127.0.0.1:5055
PORT=8080 HOST=0.0.0.0 python app.py
FLASK_DEBUG=1 python app.py        # enable Flask debug/reload

# Tests
python -m unittest tests.test_app             # full app/engine test suite
python -m unittest tests.test_app.PreprocessTests.test_preprocess_returns_original_and_processed_dimensions_below_cap  # single test

# Loop harness tests (shell, exit 0=pass / 77=skip / other=fail)
./loop/harness.sh                  # run all loop/tests/*.sh
./loop/harness.sh score_smoke      # run one by basename
```

Port 5055 is the default deliberately — macOS AirPlay Receiver holds port 5000.

## Engine architecture (`engine/`)

The processing pipeline in `app.py:/process` runs in this fixed order: **field construction → contour extraction → smoothing → scale to original → SVG export**.

- `march.py` — **the active method (`method=march`, the one the loop tunes).** A 4-connected **geodesic** (skimage `MCP`) where each pixel's traversal cost rises with darkness/edges: `cost = MARCH_BASE + MARCH_TONE·lum_mix·dark + MARCH_EDGE·edge`, and the field is the accumulated arrival time. Dark pixels cost more → contours BUNCH in dark regions → **tone-driven density that actually renders the image's tones** (the deterministic scorer's dominant `d_tone` signal); 4-connectivity keeps the L1 **diamond** topology. Knobs: `MARCH_BASE` (diamond dominance; low≈0.3 = image warps the diamonds organically), `MARCH_TONE` (THE tone-fidelity lever, ≈4.0), `MARCH_EDGE` (feature definition, ≈4.0), `MARCH_CONTRAST/MARCH_GAMMA/MARCH_BLUR` (its own tonal pre-shaping in `_preprocess_gray`). This replaced `wave` because an additive field (below) can't densify flat dark interiors — only a cost/geodesic distance can.
- `field.py` — **parked** field methods:
  - `build_wave_field` (method=`wave`): an L1 distance base + gentle luminance relief (`WAVE_*` knobs; `shape_tone`'s `TONE_GAMMA/TONE_CONTRAST/TONE_INVERT` STUDIO controls apply here and to `contour`). Architecturally additive → `d_tone`≈0, so it was superseded by march; kept as a baseline.
  - `build_field` (method=`contour`) — the simpler uniform `field = (|x-sx|+|y-sy|) + (255-lum_pre)·lum_mix`; `flow.py`'s `trace_flow_lines` (method=`flow`) is likewise parked. (Note: the old adaptive/zoned "ring" blur was a bug — do not reintroduce it.)
  - `MAX_DIM = 640` (in `field.py`) caps the processing grid; contours are computed downscaled then scaled back to upload dimensions.
- `contour.py` — Marching Squares isoline extraction at power-spaced thresholds. `THRESHOLD_POWER` (1.0 = linear/even spacing) applies to every isoline method (march/wave/contour).
- `smooth.py` — Chaikin corner-cutting. The `smooth` param (0–1) maps to 0–4 subdivision iterations.
- `export.py` — SVG with adaptive stroke weight/opacity (thick/dark near seed → thin/faint at edges).

**Tuning knobs are module-level constants** (`MARCH_*` in `march.py` for the active method; `THRESHOLD_POWER` in `contour.py`), deliberately exposed so the loop can edit one per iteration. The `WAVE_*`/`FIELD_*` constants belong to the parked wave/contour fields.

Key coordinate convention: contour points are `[row, col]` (y, x) order throughout, and `build_wave_field`/`flow` return the same `(field, min, max)` / contour-dict shape as `build_field` so all three feed the identical downstream path.

## The ralph loop (`loop/`)

A self-driving improvement loop (Karpathy-style: dumb outer shell, smart inner agent). `ralph.sh` invokes `claude -p` repeatedly; each tick reads `loop/PROMPT.md`, makes ONE small change to a tuning knob, renders the canonical test, scores it, and appends to `EXPERIMENT_LOG.md`. Read `loop/README.md` and `loop/PROMPT.md` before touching anything here.

- **Canonical test render**: `loop/render_tick.sh <N>` renders `examples/woman/woman-source.jpeg` **in-process** via `loop/render.py` (NOT the Flask app — the long-running app never reloads edited engine constants) with baked settings (centered seed, levels 111, smooth 0.0, lum_mix 0.8, method=march, png-width 780) and writes `loop/output/iter_NNN.{svg,png,stats.json}`. The `stats.json` records the `source` so the scorer can compare against it. (method=march is a tone-cost geodesic: dark pixels cost more so contours bunch in dark regions — it RENDERS the image's tones, which the additive wave field could not.)
- **Scoring**: `loop/score_tick.sh <N>` runs the **deterministic scorer** (`dscore.py`) plus legacy pixel co-signals (`score.py`) and appends one JSON line to `loop/metrics.jsonl`. The decision signal is `d_score` (0–100): it compares the output to its **own source** (from the render's `stats.json`) — **source-fidelity** dominated by **multi-scale tone** (`d_tone`: SSIM of output ink-density vs source darkness across grids 16/32/64, so local tone must match, not just global darkness; the discriminating signal) + **style** (line-spacing FFT, ink band, orientation — weighted LOW because these read ~0.95+ for art *and* for smudgy negatives) + a **diamond factor** (`d_diamond`/`d_diag`) that rewards the ±45° nested-diamond aesthetic (the `examples/woman` output-4 / L1 `method=wave` look) and penalizes axis-aligned flowing waves. Fully local, reproducible, never "offline". Calibrated so the artist's good outputs (`examples/space` + `examples/woman`) score 85–100 (busy-source samurai ~75), degenerate output (blank/solid/blob/noise) ~0, and committed **plausible-but-wrong hard negatives** (`loop/tests/fixtures/hard_neg/`, made by `make_hard_negatives.py`) ≤55 with a ≥20pt margin below the worst good — the margin is the anti-false-hill-climb lock. `loop/tests/dscore_calib.sh` is the acceptance gate. **What's deliberately NOT used** (tried + measured + rejected, see the `dscore.py` docstring): PSNR / reference-output SSIM (line drawings never align pixel-wise), a free-floating style descriptor matched to artist *outputs* (the legit artist style is too wide — it rates off-aesthetic renders as *more* artist-like than the art), and FID/LPIPS (needs torch + an Inception net + hundreds of samples; a torch co-signal is a future hook only). `loop/guard_tick.sh` gates ticks on `d_score` (absolute `GUARD_FLOOR` + relative `GUARD_DROP`). The old LLM vision judge was **removed** (backend-dependent, noisy, often offline).
- **Stop a run**: `touch loop/STOP` (graceful) or Ctrl-C. Budgets (duration/iters/tokens) backstop it.
- **Holdout** (`loop/holdout/`): the overfit test set. Do NOT read from it, score against it, or use it for inspiration in any engine work — the harness runs it separately.
- **Scorer fixtures** (`loop/tests/fixtures/`): committed hard-negative renders that gate the scorer. Likewise OFF-LIMITS to the tuning loop — do not read, score against, or tune toward them. `hard_neg/` is gated (must score low); `borderline/` is committed-but-not-gated (off-aesthetic renders that are metrically inside the legit artist band — a documented caution, not a target). Regenerate only via `loop/tests/make_hard_negatives.py` (human-run).
- `loop/output/iter_014.png` is force-tracked despite the `.png` gitignore: it's the input image for `loop/tests/score_smoke.sh` (a runtime dependency, not a regenerable artifact).

## Reference material

`examples/` holds the artist's input→output pairs and pure-visual style targets (these define "good"). `docs/` holds the documentation set (indexed by `docs/README.md`): `vision.md`, `tech.md`, `algorithm.md`, `contour-v-core-source.md`, `research.md`, and `vex-engine-reverse-engineering.md`. `archive/` is a prior CLI implementation, kept for reference.
