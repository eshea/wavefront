# RALPH LOOP · WAVEFRONT QUALITY ITERATION

You are one tick of an autonomous improvement loop for WAVEFRONT, a
topographic contour engine that aims to reproduce the VEX-LINE artist's
CONTOUR-V CORE output.

You are running inside `/Users/eshea/Projects/wavefront`. A bash wrapper
will invoke you again immediately after you exit. **Do not loop yourself.
Do one focused cycle and stop.**

---

## GROUND TRUTH

The `examples/` folder contains the artist's actual input → output pairs.
These are what "good" looks like. You are matching these.

| Input (pre) | Reference target | Known settings |
|---|---|---|
| `examples/contour_woman.webp` | `examples/contour_woman_lineart.png` (clean diamond line-art; also `contour_woman_post*`) | centered seed, levels 65, method=contour |

The woman is the **canonical test**, baked into `loop/render_tick.sh` +
`loop/score_tick.sh`. Also study the new style references in `examples/`
(the blue VEX-LINE face, `Screenshot ... CONTOUR-V CORE`, Motoko) with
the Read tool — they are output-only (no inputs), pure visual targets.

### WHAT YOU ARE TUNING NOW: the uniform CONTOUR field (`build_field`)
The canonical render uses **`method=contour`** (`render_tick.sh`), the
reverse-engineered formula applied UNIFORMLY:
`field = (|x-sx|+|y-sy|) + (255 - lum_pre)·lum_mix`. Concentric **diamonds**
(Manhattan dist) warped by luminance to follow the face, with EVEN line
spacing and clean white space — consistent from the seed to the image
edges (no circular zone). Your knobs:
- `engine/field.py`: `FIELD_DENOISE_SIGMA` (uniform blur — tame busy texture),
  `FIELD_SHADOW_LIFT` (raise darks so makeup/shadow don't pile into a blob).
- `engine/contour.py`: `THRESHOLD_POWER` (1.0 = linear/even; >1 densifies face).
- render params: `lum_mix` (luminance warp strength), `levels`.
Tune ONE per tick. Do NOT re-introduce an adaptive/zoned blur — the old
radial "ring" at ~20-35% was a bug (not in the real tool). `method=wave`
and `method=flow` are parked experiments; leave them.

**HOLDOUT — DO NOT TOUCH:** `loop/holdout/contour_space_pre.jpg` and
`loop/holdout/contour_space_post.webp` are the held-out test set. Do
not read from `loop/holdout/`. Do not score against it. Do not use it
for any inspiration. The harness will run it separately when humans
want to check for overfitting.

## QUANTITATIVE SIGNAL (read before deciding)

After each tick, `loop/score_tick.sh` runs automatically and appends
one JSON line to `loop/metrics.jsonl` with three numbers per output:

- `judge_score` (0–100, **primary metric**) — MEDIAN of several reads from
  a local vision model (`judge.py --samples`). Higher = better. NOTE the
  absolute scale depends on `judge_backend` (a good render is ~85 on the
  vLLM box, ~40–55 on the llama.cpp box); judge a tick only against ticks
  with the SAME `judge_backend`. Watch `judge_spread` — if it's large the
  read is noisy.
- `ink_coverage` (0–1) — non-white fraction. Density co-signal + guard
  against degenerate near-solid / near-blank output.
- `ssim`, `edge_iou` (0–1) — pixel co-signals only; near-flat, don't chase.
- `path_fit` (0–1) — closeness to reference path count (452). Sanity.

**Before deciding what to try this tick**, run:
```
tail -10 loop/metrics.jsonl | jq -c '{iter, judge_score, ssim, edge_iou, path_fit}'
```
to see the recent trajectory. If judge_score has been flat or dropping
across the last 3-5 ticks, your recent hypotheses aren't working — try
something qualitatively different (revert to an earlier sweet-spot
config? change a different parameter?).

Your job: raise the `judge_score` median toward the diamond reference,
tick by tick. Scores are RELATIVE to the current judge backend — aim to
beat the recent best on the same backend. A deterministic guard
(`loop/guard_tick.sh`) auto-commits a passing tick and auto-reverts a
regression, but still `git checkout -- engine/` your own change before
exiting if you can see it made things worse.

**Include the latest score line in your log entry.** Use `tail -1
loop/metrics.jsonl` after `score_tick.sh` runs.

---

## YOUR JOB THIS TICK

Pick **ONE** of these phases based on `loop/EXPERIMENT_LOG.md`:

### A. REVIEW (only on tick 1 or when log says "review next")
- Read the last 3 entries of EXPERIMENT_LOG.md.
- Render WAVEFRONT's current output for the canonical test (see TEST below).
- View the reference post image AND your rendered output with the Read
  tool — both are images, Read returns them visually.
- Write a Quality Assessment entry: gap, severity, suspected cause.
- Append a "next: build X" line and exit.

### B. BUILD
- Read EXPERIMENT_LOG.md to see what's queued.
- Make ONE small change. Edit one or two files. Don't refactor.
- Save the diff summary for the log.

### C. TEST
- Run TEST below. Save output to `loop/output/iter_NNN.svg` and
  `loop/output/iter_NNN.png` (rasterize via the Flask app's logic or
  ImageMagick if installed).
- View both your output and the reference with Read.
- Decide: better / same / worse vs. previous iteration AND vs. reference.

### D. DOCUMENT
- Append a complete entry to EXPERIMENT_LOG.md (template below).
- If a change made things worse, REVERT it before exiting (`git checkout`
  is safe — repo is clean apart from loop/ and examples/).

Most ticks will combine B + C + D in one cycle. A standalone REVIEW tick
is fine when you genuinely don't have a hypothesis.

---

## TEST PROCEDURE (canonical)

The Flask app should already be running on port 5055. If not, start it:

```
cd /Users/eshea/Projects/wavefront
source .venv/bin/activate
PORT=5055 python app.py &
sleep 2
```

Then render the canonical test with the single render helper. It POSTs
the exact canonical settings to `/process` and writes all three
artifacts — `iter_NNN.svg`, `iter_NNN.png` (rasterized), and
`iter_NNN.stats.json` (the path-count stats `score.py` needs for
`path_fit`):

```
./loop/render_tick.sh "$(cat loop/.iter 2>/dev/null || echo 1)"
```

Always use this helper rather than hand-rolling curl — it guarantees
every tick renders identical settings and writes the stats.json without
which `path_fit` stays null. (`PORT` defaults to 5055; override if you
started the app elsewhere.)

Then view your output and the reference visually:

```
# In your prompt, use Read on both:
Read loop/output/iter_NNN.png
Read examples/contour_woman_lineart.png
```

Read returns images visually. Look at them and compare specifically:
ring shape (diamonds vs circles), facial feature definition, line
density, noise in background regions, stroke uniformity.

---

## LOG ENTRY TEMPLATE

Append to `loop/EXPERIMENT_LOG.md`. **The header number MUST be the real
tick number** — use exactly `$(cat loop/.iter)`, do NOT invent or
increment it. (Past runs drifted the log headers ~11 ahead of the actual
`.iter`/`metrics.jsonl` counter, which made the history impossible to
audit. Render with `render_tick.sh` and the artifacts, metrics line, and
log header all share one number.)

```
## Iter NNN · YYYY-MM-DD HH:MM · {one-line summary}

**Hypothesis:** {one sentence — what you thought would help}

**Change:** {file:line summary, e.g. "engine/field.py:50 — clamp lum
contribution to top 90th percentile"}

**Test:** canonical (woman, centered seed, levels 65, method=contour)
- output: `loop/output/iter_NNN.svg` ({stats})
- reference: `examples/contour_woman_lineart.png`
- visual comparison: {what you saw — be specific}

**Score:** judge=NN ssim=0.0NNN edge_iou=0.NNNN path_fit=0.NN
            · vs last 3 avg: judge ΔNN

**Result:** better / same / worse · vs. reference: {closer / further /
neutral}  · vs. iter_014 (anchor 95): {N points away}

**Next:** {hypothesis for next tick, or "review" if unclear}
```

---

## RULES (read carefully — violations waste the budget)

1. **EXACTLY ONE cycle per invocation, then exit.** After you append ONE
   log entry to `loop/EXPERIMENT_LOG.md`, you are done. Do NOT start
   another build/test cycle. Do NOT "while I'm here, also try…". The
   shell will re-invoke you. Stopping now is the right call.

2. **EVERY invocation MUST end with one log entry** — even if you only
   reviewed, or your build failed, or you reverted. No silent ticks.
   Past runs had "undocumented iter 014–023" gaps because cycles ran
   without appending. Don't do that.

3. **Don't ask questions.** This is autonomous. Make a call and move on.

4. **If app is broken, fixing it IS the tick.** Log the fix and exit.

5. **If your change regressed quality, revert it** with
   `git checkout -- <path>` before exiting (the repo has commits now —
   checkout actually works). Log the attempt and the revert.

6. **Stay in CORE territory** for now — don't add STUDIO features unless
   the log explicitly schedules them.

7. **Never delete `examples/` or `loop/EXPERIMENT_LOG.md`.**

8. If the experiment log says "loop done", create a file `loop/STOP` and
   exit. The wrapper will halt.

You have Bash, Read, Edit, Write. Use them. Don't use sub-agents. Don't
start the Flask app if `curl http://localhost:5055/` already returns 200.
