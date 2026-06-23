# WAVEFRONT — Tech & Architecture

## Stack

| Layer | Tech |
|---|---|
| Web server | Flask (`app.py`) |
| Numerics | NumPy (vectorized field), SciPy (`gaussian_filter`) |
| Contours | scikit-image `measure.find_contours` (Marching Squares) |
| Image I/O | Pillow |
| Export | hand-built SVG strings (`engine/export.py`; `svgwrite` listed but the fast path emits strings directly) |
| Frontend | vanilla JS + HTML/CSS (`static/`, `templates/index.html`) |
| Tuning loop | Bash + `claude -p` + a deterministic image-processing scorer (`loop/dscore.py`) |

Python 3.9+. Dev deps in `requirements.txt`; run inside `.venv`.

## Request flow

```
Browser (templates/index.html)
   │  GET  /config   → method list + per-method knob registry (min/max/default) that
   │                   drives the UI sliders (one source of truth: app.py METHOD_KNOBS)
   │  POST /process  (multipart: image + levels, smooth, lum_mix, wt_range, seed_x/y,
   │                   method, + the active method's knobs e.g. wave_relief, flow_carrier…)
   │                   app.py._apply_knobs temporarily overrides the engine module
   │                   constants from those form values for the request, then restores.
   ▼
app.py  ── validates/clamps params (RequestValidationError → HTTP 400)
   │
   ├─ engine.field.load_and_preprocess   resize to MAX_DIM=800 (or per-request detail_px ≤4000), keep original size
   │     (grid area > MAX_GRID_PX → HTTP 400 before the heavy solve, so big prints can't OOM the host)
   ├─ engine.field.to_luminance          BT.601 luma
   ├─ engine.compose.compose_canvas      OPT-IN: pad to a wide mural aspect, fill margins (canvas_aspect set)
   ├─ field construction (one of):
   │     march.build_march_field method=march (ACTIVE — fast marching, reciprocal cost; darks go solid)
   │     build_wave_field    method=wave     (parked — additive L1-diamond field; d_tone≈0)
   │     build_field        method=contour  (parked baseline — simpler uniform formula)
   │     flow.trace_flow_lines method=flow   (parked experiment)
   ├─ engine.contour.extract_contours    Marching Squares at power-spaced levels (T-max clip, min-pts)
   ├─ engine.smooth.resample_contours    fixed-step arclength resample (STUDIO "STEP")
   ├─ engine.smooth.smooth_contours      Chaikin corner-cutting
   ├─ engine.smooth.decimate_contours    OPT-IN: RDP point budget for big prints (simplify_mm)
   ├─ engine.color.assign_layers         OPT-IN: tag each contour with a pen index (color_mode tone/depth)
   ├─ engine.optimize.optimize_contours  OPT-IN: layer-aware merge / nearest-sort / 2-opt to cut pen-up travel (opt_*)
   ├─ engine.contour.scale_contours      processing grid → original/canvas dimensions
   └─ engine.export.contours_to_svg_string_fast   constant-ink SVG (modulation opt-in via wt_range; physical pen via pen_mm)
        └─ …_layered (color_mode≠off): one Inkscape pen layer per color; both writers stamp physical size if phys given
   ▼
JSON { svg, stats, img/processing dims, seed, subject_rect, color_mode, palette } → browser renders + offers export
```

There is also `POST /thumbnail` (returns a base64 downscaled ghost overlay for
the preview canvas) and `POST /autotune` (image-adaptive knob suggestion for
`method=march`: analyzes the uploaded image's luminance on the same preprocessed
grid the engine sees and returns `{levels, knobs}` tuned for that image, via
`engine.march.suggest_params` — a fast heuristic, NOT the slow `loop/optimize.py`
search). The UI consumes it from the **AUTO-TUNE** button.

The web UI **re-renders live**: changing any slider/knob (or the seed) debounces
a `/process` call (~300ms) and cancels any in-flight render, so the latest
settings always win — the COMPUTE button is now a manual fallback. **RESET
DEFAULTS** restores every control to its `/config` default (core sliders from
their original values, `MARCH_*` knobs from the engine defaults); **AUTO-TUNE**
applies the per-image suggestion.

## Key design points

- **Two-grid model.** Contours are computed on a ≤800px (per-request up to 4000px)
  processing grid for speed, then scaled back to the *original* upload dimensions
  for export, so SVG is full-resolution and plotter-accurate. Seed coordinates are
  in the processing grid.
- **Large prints can't be tiled.** The `march` field is one global geodesic solve
  (`MCP.find_costs`) — arrival times propagate across the whole field, so detail is
  bounded by the largest grid one solve can hold. The levers are float32 cost (halved
  peak memory), a measured `detail_px` ceiling (~10s/~1.4GB at 4000px), and a
  `MAX_GRID_PX` env guard (default 16M px) that 400s an over-budget DETAIL × wide-canvas
  combo instead of OOMing. Raising `detail_px` above the source resolution is a no-op
  (Step 1 never upscales) — a detailed mural needs a high-res source. See
  `algorithm.md` → "Large prints".
- **Coordinate convention.** Contour points are `[row, col]` (y, x) throughout.
  All three field methods return the same `(field, min, max)` / contour-dict
  shape so they share one downstream smoothing + export path.
- **Tuning knobs are module-level constants** — the `WAVE_*` constants
  (`field.py`) for the active wave field, plus `THRESHOLD_POWER` (`contour.py`) —
  exposed deliberately so the ralph loop can edit exactly one per iteration. See
  `algorithm.md` for what each does. (`FIELD_*` belong to the parked contour baseline.)
  The 6 `MARCH_*` aesthetic knobs are additionally **externalized** to
  `engine/march_params.json` (loaded at import, overrides the in-code defaults): the
  version-controlled tuned config that `loop/optimize.py` (a constrained multi-input
  black-box tuner) writes and the loop edits. `engine.march` exposes
  `current_params/apply_params/save_params/load_params` + `PARAM_BOUNDS` as the
  search surface; `app.py`'s per-request overrides still ride on top.
- **Mural extensions are opt-in and CORE-preserving.** `engine/compose.py`
  (wide canvas), `engine/color.py` (pen-layer separation), and
  `engine/export.py:contours_to_svg_layered` + the `phys`/`detail_px` params
  extend `/process` for large-format work, as do **physical pen width** (`pen_mm` →
  constant on-wall stroke) and a **point budget** (`simplify_mm` → RDP decimation,
  `engine/smooth.py:decimate_contours`). All default off: with no canvas aspect,
  `color_mode=off`, no `phys`, and no `pen_mm`/`simplify_mm`, the output is the
  historical single-ink SVG at source aspect (guarded by a defaults-unchanged
  regression test). See `algorithm.md` → "Mural extensions" / "Large prints" for the
  stages and parameter table.
- **Active method is `march`** (`build_march_field`, fast marching with reciprocal cost) — what
  `render_tick.sh` renders and the loop tunes (`MARCH_*` knobs). `wave`
  (`build_wave_field`), `contour` (`build_field`) and `flow` are parked; leave them
  unless explicitly working on them. The Flask API and web UI now default to `march`
  with the canonical "woman output" settings (levels 111, smooth 0.0, lum_mix 0.8,
  wt_range 0.0) — the same baked settings `render_tick.sh` uses.

## The ralph loop (`loop/`)

Self-driving improvement loop (Karpathy-style: dumb outer shell, smart inner
agent). `ralph.sh` repeatedly invokes `claude -p`; each tick reads
`loop/PROMPT.md`, edits ONE knob, renders the canonical test in-process
(`render_tick.sh` → `loop/render.py`, baked settings), scores it
(`score_tick.sh`: deterministic `dscore.py` + legacy pixel co-signals `score.py`,
appended to `loop/metrics.jsonl`), gates on the result (`guard_tick.sh`), and
logs to `EXPERIMENT_LOG.md`. A held-out set (`loop/holdout/`) guards overfitting
— **never read, score, or train against it.**

**The agent's legible environment.** Following the "make the artifact legible to the
agent" principle, each tick regenerates a small set of git-ignored situational
artifacts the inner agent reads first (instead of juggling raw files or stale prose):
`STATUS.md` (`status.py`) — the **live** knob values + `PARAM_BOUNDS`, the recent
metrics trend, the best `d_fine` so far, and the prior tick's guard verdict;
`output/_latest_compare.png` (`montage.py`) — a single montage of
**source | current | best-so-far | artist target** with metrics annotated, so the
agent *sees* what changed; `EXPERIMENT_DIGEST.md` (`distill.py`) — `EXPERIMENT_LOG.md`
distilled to helped / ruled-out / open; and `.guard_feedback` — the guard's
"why kept/reverted + what to try" note, folded into `STATUS.md`. Config can't drift
because the tuning docs hold **no** `MARCH_*` numbers (they point at `STATUS.md`); a
harness test (`loop/tests/doc_freshness.sh`) fails the build if one creeps back in.
`render_tick.sh` also garbage-collects old per-tick dumps (`OUTPUT_KEEP`, default 20).

Scoring is **deterministic** (`dscore.py`, `d_score` 0–100): it compares the
output to its **own source** — source-fidelity (subject recognizable / density
tone-modulated) + style (line-spacing FFT, ink band, orientation). The dominant
term is **multi-scale tonal-structure fidelity**: SSIM between the output's
ink-density and the source's darkness across grids 16/32/64 (so getting *global*
darkness right is no longer enough — local tone must match too). No network, no
backend, reproducible. Calibrated so the artist's good outputs (`examples/space`,
`examples/woman`) score 85–100, degenerate output ~0, and committed
**plausible-but-wrong hard negatives** (`loop/tests/fixtures/hard_neg/`) score
≤55 with a ≥20-point margin below the worst good. That margin is the
**anti-false-hill-climb lock**: any change that inflates a smudgy/inverted render
flips the gate (`loop/tests/dscore_calib.sh`) red.

**Deliberately not used** (tried, measured, rejected — see the `dscore.py` module
docstring and `loop/tests/fixtures/README.md`):
PSNR and reference-output SSIM/edge-IoU (two line drawings never align pixel-wise);
a free-floating style descriptor matched to the artist *outputs* (the legit artist
style is wide enough — sparse diamonds, dense hatching, flowing waves — that a
global appearance descriptor rates off-aesthetic renders as *more* artist-like than
the artists); and FID/LPIPS (needs an Inception/VGG net + torch + hundreds of
samples, breaking the local/no-backend property — a torch perceptual co-signal is a
documented future hook only). See `loop/README.md` for budgets, stop controls, and cost.

## Operational notes

- Run: `source .venv/bin/activate && python app.py` → http://127.0.0.1:5055.
  Port 5055 avoids macOS AirPlay (which holds 5000). `PORT`/`HOST`/`FLASK_DEBUG`
  override. The dev server runs `threaded=True` so a slow mural render doesn't
  serialize other requests; for real mural traffic front it with gunicorn + a long
  `--timeout`.
- Max upload 32 MB. Malformed numeric params → HTTP 400; out-of-range → clamped.
- `MAX_GRID_PX` env (default 16,000,000) caps the processing-grid area a single
  render may attempt — a `detail_px` × wide-`canvas_aspect` combo over the budget
  returns 400 rather than OOMing. Raise it on a bigger box. The PNG download is a
  raster preview capped to ~4000px longest side (the SVG stays full-resolution vector).
- Tests: `python -m unittest tests.test_app`; loop tests via `./loop/harness.sh`.
