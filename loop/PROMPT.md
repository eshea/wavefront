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
| `examples/space/space-source.jpg` (astronaut helmet) | `examples/space/space-output-1.jpeg` — the artist's actual CONTOUR-V output (a CLEAN, high-res, truly MATCHED pair; flowing-wave look). The deterministic scorer compares your render to the SOURCE; this is what a ~95 looks like. | centered seed, levels 111, method=wave |

NOTE: the old `contour_woman_*` set is NOT a matched pair — the woman input and the
`contour_woman_lineart`/`post*` targets are DIFFERENT subjects, so resemblance was
unachievable. They're retained as style references / the holdout only.

The astronaut helmet is the **canonical test**, baked into `loop/render_tick.sh` +
`loop/score_tick.sh`. Also study the style references in `examples/` (the blue
VEX-LINE face, `ref_contourv_core`, Motoko, and the classical-woman lineart) with
the Read tool — they are output-only (no matched inputs), pure visual targets.

### WHAT YOU ARE TUNING NOW: the WAVE diamond field (`engine/field.py`)
The canonical render uses **`method=wave`** (`render_tick.sh`): an L1-Manhattan
**diamond** field (nested diamonds radiating from the seed) warped by a luminance
**relief** so the subject emerges as warped diamonds. This is the CONTOUR-V /
**output-4** nested-diamond aesthetic the deterministic scorer targets (its diamond
term peaks at `d_diag`≈0.53). Your knobs (all in `engine/field.py`,
`build_wave_field`):
- `WAVE_RELIEF` — warp strength (how hard the image bends the diamonds). Too low =
  stiff geometric diamonds / moiré (low `d_diamond`); too high = over-warped, the
  diamonds break up and `d_diag` falls below ~0.5. Tune toward `d_diag`≈0.53.
- `WAVE_DIAMOND` — 0..1 crisp-diamond bias: 0 = full ripple, 1 = ignore the image.
- `WAVE_SIGMA_FACE` / `WAVE_SIGMA_BG` — luminance blur near / far from the seed.
- `WAVE_FAR` — far-field ripple multiplier (how much the background warps).
- `WAVE_INNER` / `WAVE_OUTER` — relief-fade radii (seed → background).
- render params: `lum_mix`, `levels` (density; 111 = CONTOUR-V CORE's CONTOURS count).
Tune ONE per tick (see `loop/IDEAS.md` menu). `method=flow/contour/march` and their
FLOW_*/FIELD_*/MARCH_* constants are PARKED — they don't affect the wave render.

**HOLDOUT — DO NOT TOUCH:** `loop/holdout/contour_space_pre.jpg` and
`loop/holdout/contour_space_post.webp` are the held-out test set. Do
not read from `loop/holdout/`. Do not score against it. Do not use it
for any inspiration. The harness will run it separately when humans
want to check for overfitting.

## QUANTITATIVE SIGNAL (read before deciding)

After each tick, `loop/score_tick.sh` runs automatically and appends
one JSON line to `loop/metrics.jsonl`. The metric is **fully deterministic**
(`loop/dscore.py`) — no LLM, no backend, reproducible run to run:

- `d_score` (0–100, **primary metric**) — how well the render re-expresses its
  SOURCE as flowing contour lines. It compares the output to its **own source**
  (the canonical helmet, recorded in the render's `stats.json`) at a coarse
  scale. Two parts:
  - `d_fidelity` — source-fidelity: lines dense/bent where the source has edges
    and tone, clean where it's flat → the subject stays recognisable. This is
    the discriminating signal. (`d_r` = the raw source/output correlation.)
  - `d_style` — does it look like the VEX-LINE family at all: dominant line
    spacing (`d_freq_peak`, `d_peakedness`), ink band (`d_ink`), orientation.
  - **diamond term** (`d_diamond`, from `d_diag`) — a strong multiplicative factor
    that rewards the **±45° nested-diamond aesthetic** (the `examples/woman`
    output-4 look: L1 contours run diagonally) and **penalizes axis-aligned
    flowing waves**. This is why `method=flow` (horizontal carrier) now scores
    LOW — the target is diamonds. `d_diag` ≈ 0.50–0.57 is the artist band;
    ≈ 0.28 (axis-aligned) and ≈ 0.86 (over-regular moiré) are both penalised.
  Calibrated so the artist's good outputs score ~95 and degenerate output
  (blank/solid/blob/noise) ~0. Current engine attempts have real headroom.
- `ink_coverage`, `ssim`, `edge_iou`, `path_fit` — legacy pixel co-signals only;
  near-flat across good/bad, recorded but **don't chase them**.

**Before deciding what to try this tick**, run:
```
tail -10 loop/metrics.jsonl | jq -c '{iter, d_score, d_fidelity, d_style, d_ink}'
```
Look at WHICH part is low. Low `d_fidelity` → the lines don't track the source
(subject lost / density not tone-modulated) — change how the field follows the
image. Low `d_style` → it doesn't read as line art (check `d_freq_peak` ≈ 6–7,
`d_peakedness`, `d_ink`). If `d_score` has been flat or dropping across the last
3–5 ticks, your hypotheses aren't working — try something QUALITATIVELY different
(a different idea category, or revert).

Your job: raise `d_score` tick by tick toward the artist's ~95. A deterministic
guard (`loop/guard_tick.sh`) auto-commits a passing tick and auto-reverts a
regression (absolute floor + relative drop), but still `git checkout -- engine/`
your own change before exiting if you can see it made things worse.

**Include the latest score line in your log entry.** Use `tail -1
loop/metrics.jsonl` after `score_tick.sh` runs.

---

## THE GOAL: REPLICATE THE ARTIST'S EXAMPLES

The north star is always to make the canonical output **pass for one of the
artist's own output** for the canonical input — `examples/space/space-output-1.jpeg`
(the matched output for `examples/space/space-source.jpg`): flowing wave contours
that bend around the helmet, dense where the image is dark (the visor),
sparse/clean in the bright sky and desert. `d_score` measures how well the render
re-expresses the SOURCE that way; the artist's own output scores ~95 — closing the
gap to it is the job.

## BREADTH FIRST — DO NOT HILL-CLIMB

This loop's failure mode is nudging one constant up and down forever. Avoid it:
- Steer by which part of `d_score` is low (`d_fidelity` vs `d_style`), but
  explore **DIVERSE ways to close it** — not the same knob each time. E.g. if the
  gap is "no diamond / too dense", a true fix might be a new field formula, a
  different distance metric, a new `method=`, equalization, or level spacing —
  try genuinely different ones across ticks.
- Read **`loop/IDEAS.md`** (backlog of diverse directions). Each tick pick from a
  **different category than your last 2 ticks**. If the last 3 ticks were the same
  category, you MUST switch.
- Genuinely new algorithms (new field, new `method=`, hatching) and new
  **tests/metrics** are HIGH value — do them, not just parameter sweeps.
- When you have a new thought, **add it to `loop/IDEAS.md`**; mark tried ideas with
  their result. Breadth of explored ideas matters as much as the best score.

## YOUR JOB THIS TICK

Pick **ONE** of these phases based on `loop/EXPERIMENT_LOG.md` and `loop/IDEAS.md`:

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

Render the canonical test with the single render helper. It renders
IN-PROCESS via `loop/render.py` (a fresh `python` import per tick) — NO
Flask app required. This is deliberate: the long-running app never
reloaded engine edits, so the loop's changes had no effect; rendering
in-process makes each edit actually take effect. It writes all three
artifacts — `iter_NNN.svg`, `iter_NNN.png` (rasterized), and
`iter_NNN.stats.json` (the path-count stats `score.py` needs for
`path_fit`):

```
cd /Users/eshea/Projects/wavefront
source .venv/bin/activate
./loop/render_tick.sh "$(cat loop/.iter 2>/dev/null || echo 1)"
```

Always use this helper rather than hand-rolling a render — it guarantees
every tick renders identical settings (centered seed, levels 111,
method=wave) and writes the stats.json (which records the `source` the
deterministic scorer compares against).

Then view your output and the reference visually:

```
# In your prompt, use Read on both:
Read loop/output/iter_NNN.png
Read examples/space/space-output-1.jpeg
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

**Test:** canonical (helmet, centered seed, levels 111, method=wave)
- output: `loop/output/iter_NNN.svg` ({stats})
- source: `examples/space/space-source.jpg`
- visual comparison: {what you saw — be specific}

**Score:** d_score=NN (fid=0.NNN style=0.NNN) ink=0.NN
            · vs last 3 avg: d_score ΔNN

**Result:** better / same / worse · vs. reference: {closer / further /
neutral}  · vs. artist good output (~95): {N points away}

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
