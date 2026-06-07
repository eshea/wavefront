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

- `field.py` — builds the scalar field. Three things matter:
  - `build_wave_field` (method=`wave`, the **active method — the one the loop tunes**): an L1 (Manhattan) distance base that dominates the gradient (crisp concentric **diamonds**) plus a gentle luminance relief that ripples around features and is suppressed far from the seed. Knobs: `WAVE_DIAMOND, WAVE_RELIEF, WAVE_SIGMA_FACE, WAVE_SIGMA_BG, WAVE_FAR, WAVE_INNER, WAVE_OUTER`. `WAVE_RELIEF` is the warp strength (≈2.8 — low values give a stiff diamond moiré). Shared **tonal pre-shaping** (`shape_tone`: `TONE_GAMMA, TONE_CONTRAST, TONE_INVERT` — CONTOUR-V STUDIO's "Input & Tonal Control") is applied to luminance before the field; identity at defaults, so it's an opt-in lever (gamma<1 lifts over-dense shadows). Applies to `wave` and `contour`.
  - `build_field` (method=`contour`) — the simpler reverse-engineered uniform formula `field = (|x-sx|+|y-sy|) + (255-lum_pre)·lum_mix`, kept as a **parked baseline**; `flow.py`'s `trace_flow_lines` (method=`flow`) is likewise parked. Leave both (and the `FIELD_*` constants) unless explicitly working on them. (Note: the old adaptive/zoned/radial "ring" blur was a bug — do not reintroduce it.)
  - `MAX_DIM = 640` caps the processing grid; contours are computed on the downscaled grid then scaled back to upload dimensions.
- `contour.py` — Marching Squares isoline extraction at power-spaced thresholds. `THRESHOLD_POWER` controls level distribution (1.0 = linear/even spacing matching the reference; >1 densifies near the seed). Applies to both wave and contour output.
- `smooth.py` — Chaikin corner-cutting. The `smooth` param (0–1) maps to 0–4 subdivision iterations.
- `export.py` — SVG with adaptive stroke weight/opacity (thick/dark near seed → thin/faint at edges).

**Tuning knobs are module-level constants** (`WAVE_*` in `field.py`; `THRESHOLD_POWER` in `contour.py`), deliberately exposed so the loop can edit one per iteration. The `FIELD_*` constants belong to the parked contour baseline.

Key coordinate convention: contour points are `[row, col]` (y, x) order throughout, and `build_wave_field`/`flow` return the same `(field, min, max)` / contour-dict shape as `build_field` so all three feed the identical downstream path.

## The ralph loop (`loop/`)

A self-driving improvement loop (Karpathy-style: dumb outer shell, smart inner agent). `ralph.sh` invokes `claude -p` repeatedly; each tick reads `loop/PROMPT.md`, makes ONE small change to a tuning knob, renders the canonical test, scores it, and appends to `EXPERIMENT_LOG.md`. Read `loop/README.md` and `loop/PROMPT.md` before touching anything here.

- **Canonical test render**: `loop/render_tick.sh <N>` renders `examples/space/space-source.jpg` **in-process** via `loop/render.py` (NOT the Flask app — the long-running app never reloads edited engine constants) with baked settings (centered seed, levels 111, smooth 0.0, lum_mix 0.8, method=wave, png-width 780) and writes `loop/output/iter_NNN.{svg,png,stats.json}`. The `stats.json` records the `source` so the scorer can compare against it. (levels 111 = CONTOUR-V CORE's CONTOURS density; the warped relief keeps the dense lines from aliasing into a moiré and the 780px raster resolves them.)
- **Scoring**: `loop/score_tick.sh <N>` runs the **deterministic scorer** (`dscore.py`) plus legacy pixel co-signals (`score.py`) and appends one JSON line to `loop/metrics.jsonl`. The decision signal is `d_score` (0–100): it compares the output to its **own source** (from the render's `stats.json`) at a coarse scale — **source-fidelity** (does it re-express the source as flowing lines / is the subject recognizable; the discriminating signal) + **style** (line-spacing FFT, ink band, orientation) + a **diamond factor** (`d_diamond`/`d_diag`) that rewards the ±45° nested-diamond aesthetic (the `examples/woman` output-4 / L1 `method=wave` look) and penalizes axis-aligned flowing waves — so it actively prefers diamonds over flow. Fully local, reproducible, never "offline". Calibrated so the artist's good outputs in `examples/space` + `examples/woman` score ~95 and degenerate output (blank/solid/blob/noise) ~0 — `loop/tests/dscore_calib.sh` is the acceptance gate. `loop/guard_tick.sh` gates ticks on `d_score` (absolute `GUARD_FLOOR` + relative `GUARD_DROP`). The old LLM vision judge was **removed** (backend-dependent, noisy, often offline).
- **Stop a run**: `touch loop/STOP` (graceful) or Ctrl-C. Budgets (duration/iters/tokens) backstop it.
- **Holdout** (`loop/holdout/`): the overfit test set. Do NOT read from it, score against it, or use it for inspiration in any engine work — the harness runs it separately.
- `loop/output/iter_014.png` is force-tracked despite the `.png` gitignore: it's the input image for `loop/tests/score_smoke.sh` (a runtime dependency, not a regenerable artifact).

## Reference material

`examples/` holds the artist's input→output pairs and pure-visual style targets (these define "good"). `docs/` holds the documentation set (indexed by `docs/README.md`): `vision.md`, `tech.md`, `algorithm.md`, `contour-v-core-source.md`, `research.md`, and `vex-engine-reverse-engineering.md`. `archive/` is a prior CLI implementation, kept for reference.
