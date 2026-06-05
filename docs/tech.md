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
| Tuning loop | Bash + `claude -p` + a local vision LLM judge (`loop/`) |

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
   ├─ engine.field.load_and_preprocess   resize to MAX_DIM=640, keep original size
   ├─ engine.field.to_luminance          BT.601 luma
   ├─ field construction (one of):
   │     build_wave_field    method=wave     (ACTIVE — the L1-diamond field the loop tunes)
   │     march.build_march_field method=march (EXPERIMENTAL — 4-connected marching-waves, see algorithm.md)
   │     build_field        method=contour  (parked baseline — simpler uniform formula)
   │     flow.trace_flow_lines method=flow   (parked experiment)
   ├─ engine.contour.extract_contours    Marching Squares at power-spaced levels
   ├─ engine.smooth.smooth_contours      Chaikin corner-cutting
   ├─ engine.contour.scale_contours      processing grid → original dimensions
   └─ engine.export.contours_to_svg_string_fast   adaptive stroke-weight SVG
   ▼
JSON { svg, stats, img/processing dims, seed } → browser renders + offers export
```

There is also `POST /thumbnail` (returns a base64 downscaled ghost overlay for
the preview canvas).

## Key design points

- **Two-grid model.** Contours are computed on a ≤640px processing grid for
  speed, then scaled back to the *original* upload dimensions for export, so SVG
  is full-resolution and plotter-accurate. Seed coordinates are in the
  processing grid.
- **Coordinate convention.** Contour points are `[row, col]` (y, x) throughout.
  All three field methods return the same `(field, min, max)` / contour-dict
  shape so they share one downstream smoothing + export path.
- **Tuning knobs are module-level constants** — the `WAVE_*` constants
  (`field.py`) for the active wave field, plus `THRESHOLD_POWER` (`contour.py`) —
  exposed deliberately so the ralph loop can edit exactly one per iteration. See
  `algorithm.md` for what each does. (`FIELD_*` belong to the parked contour baseline.)
- **Active method is `wave`** (`build_wave_field`, the L1-diamond field) — what
  `render_tick.sh` renders and the loop tunes. `contour` (`build_field`) and
  `flow` are parked; leave them unless explicitly working on them. (Note: the
  Flask API's own `method` default is still `contour`; the loop overrides it.)

## The ralph loop (`loop/`)

Self-driving improvement loop (Karpathy-style: dumb outer shell, smart inner
agent). `ralph.sh` repeatedly invokes `claude -p`; each tick reads
`loop/PROMPT.md`, edits ONE knob, renders the canonical test
(`render_tick.sh` → `/process` with baked settings), scores it
(`score_tick.sh`: pixel metrics `score.py` + visual judge `judge.py`, appended
to `loop/metrics.jsonl`), and logs to `EXPERIMENT_LOG.md`. A held-out set
(`loop/holdout/`) guards overfitting — **never read, score, or train against it.**

⚠ Judge scores are **backend-dependent** (a good render ≈ 85 on vLLM-Qwen3 vs
≈ 40–55 on llama.cpp); only compare ticks with the same `judge_backend`. See
`loop/README.md` for budgets, stop controls, and cost.

## Operational notes

- Run: `source .venv/bin/activate && python app.py` → http://127.0.0.1:5055.
  Port 5055 avoids macOS AirPlay (which holds 5000). `PORT`/`HOST`/`FLASK_DEBUG`
  override.
- Max upload 32 MB. Malformed numeric params → HTTP 400; out-of-range → clamped.
- Tests: `python -m unittest tests.test_app`; loop tests via `./loop/harness.sh`.
