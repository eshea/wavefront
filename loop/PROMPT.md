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
| `examples/woman/woman-source.jpeg` (**canonical**) | `examples/woman/woman-sample-output-2.jpeg` — the artist's dense CONTOUR-V output for that input (the "really good" target; see also the low/med/high `woman-sample-output-density-example.jpeg`). The scorer compares your render to the SOURCE. | centered seed, levels 111, method=march |
| `examples/space/space-source.jpg` (helmet) | `examples/space/space-output-1.jpeg` — flowing-wave matched pair. Now the **holdout** (generalization check). | — |
| `examples/samurai/samurai-source.jpg` | `examples/samurai/samurai-output-1.jpeg` — flowing matched pair (busy source). | — |

NOTE: the OLD `contour_woman_*` files (`.webp`/`lineart`/`post*`) are a DIFFERENT,
unmatched subject — ignore them. The matched woman pair is in `examples/woman/`.

The woman portrait (`woman-source.jpeg`) is the **canonical test**, baked into `loop/render_tick.sh` +
`loop/score_tick.sh`. Also study the style references in `examples/` (the blue
VEX-LINE face, `ref_contourv_core`, Motoko, and the classical-woman lineart) with
the Read tool — they are output-only (no matched inputs), pure visual targets.

### WHAT YOU ARE TUNING NOW: the MARCH geodesic field (`engine/march.py`)
The canonical render uses **`method=march`** (`render_tick.sh`): a 4-connected
**geodesic** (skimage MCP) where each pixel's traversal cost rises with darkness
and edges, so arrival-time contours BUNCH where the image is dark — **tone-driven
density that actually renders the image's tones** — while 4-connectivity keeps the
L1 **diamond** topology. This is what the additive wave field could NOT do (its
density followed the seed geometry, not the image; `d_tone`≈0). Your knobs (all in
`engine/march.py`, cost = `MARCH_BASE + MARCH_TONE·lum_mix·dark + MARCH_EDGE·edge`):
- `MARCH_TONE` — THE tone-fidelity lever: darkness→extra cost→denser lines in
  shadows. Higher raises `d_tone`. Too high → shadows go solid black (`d_ink`>0.85
  trips the gate). Currently 4.0.
- `MARCH_BASE` — diamond dominance / base step cost. LOW (~0.3) lets the image warp
  the diamonds organically (`d_diag`≈0.50); HIGH gives stiff diamonds (`d_diag`>0.65,
  penalised). Currently 0.3.
- `MARCH_EDGE` — edges→extra cost: defines feature boundaries (eyes/nose/jaw). 4.0.
- `MARCH_CONTRAST` / `MARCH_GAMMA` — tonal pre-shaping of the gray (contrast about
  mid, then gamma) before the cost. `MARCH_BLUR` — denoise sigma.
- render params: `lum_mix` (scales MARCH_TONE), `levels` (density; 111 = CORE's count).
Tune ONE per tick (see `loop/IDEAS.md` menu). `method=wave/flow/contour` and their
WAVE_*/FLOW_*/FIELD_* constants are PARKED — they don't affect the march render.

**HOLDOUT — DO NOT TOUCH:** `loop/holdout/contour_space_pre.jpg` and
`loop/holdout/contour_space_post.webp` are the held-out test set. Do
not read from `loop/holdout/`. Do not score against it. Do not use it
for any inspiration. The harness will run it separately when humans
want to check for overfitting.

**SCORER FIXTURES — ALSO DO NOT TOUCH:** `loop/tests/fixtures/` holds the
hard-negative corpus that gates the scorer (`dscore_calib.sh`). Do not read,
score against, or take inspiration from it — these are deliberately-bad renders
whose only job is to keep the scorer honest. Tuning toward them would defeat the
gate. They are regenerated only by a human via `make_hard_negatives.py`.

## QUANTITATIVE SIGNAL (read before deciding)

After each tick, `loop/score_tick.sh` runs automatically and appends
one JSON line to `loop/metrics.jsonl`. The metric is **fully deterministic**
(`loop/dscore.py`) — no LLM, no backend, reproducible run to run:

- `d_score` (0–100, **primary metric**) — how well the render re-expresses its
  SOURCE as flowing contour lines. It compares the output to its **own source**
  (the canonical woman portrait, recorded in the render's `stats.json`) at a coarse
  scale. Two parts:
  - `d_fidelity` — source-fidelity, dominated by **`d_tone`**: a MULTI-SCALE SSIM
    (grids 16/32/64, see `d_tone16/32/64`) between the output's local ink-density
    and the SOURCE's darkness — i.e. does the output actually render the image's
    tones (dense where the image is dark) AT EVERY SCALE, not just globally? This is
    THE discriminating signal. The march geodesic drives it positive (canonical
    `d_tone`≈0.69, artist 0.24–0.67); a field that ignores the image (the old
    additive wave) had `d_tone`≈0/negative and scores ~43. Keep `d_tone` high.
  - `d_style` — does it look like the VEX-LINE family at all: dominant line
    spacing (`d_freq_peak`, `d_peakedness`), ink band (`d_ink`), orientation.
  - **diamond term** (`d_diamond`, from `d_diag`) — a strong multiplicative factor
    that rewards the **±45° nested-diamond aesthetic** (the `examples/woman`
    output-4 look: L1 contours run diagonally) and **penalizes axis-aligned
    flowing waves**. This is why `method=flow` (horizontal carrier) now scores
    LOW — the target is diamonds. `d_diag` ≈ 0.50–0.57 is the artist band;
    ≈ 0.28 (axis-aligned) and ≈ 0.86 (over-regular moiré) are both penalised.
  Calibrated so the artist's good outputs score 85–100 (busy-source samurai ~75),
  degenerate output (blank/solid/blob/noise) ~0, and committed plausible-but-wrong
  hard negatives (`loop/tests/fixtures/hard_neg/`) ≤55 with a ≥20-point margin below
  the worst good (`dscore_calib.sh` enforces this — it's the anti-false-hill-climb
  lock). NOTE: the canonical woman render already scores ~100 on `d_tone`; the
  remaining gap to the artist is *qualitative* (line cleanliness, spacing,
  recognisability) and the metric is deliberately NOT sensitive to every such
  difference — a higher `d_score` is necessary, not sufficient. Some off-aesthetic
  renders (`loop/tests/fixtures/borderline/`) are metrically inside the legit artist
  band and intentionally NOT penalised; don't expect the score to catch those.
- `d_fine` (0–1, **the CLIMB signal now that `d_score` has saturated at 100**) —
  fine-grid tonal fidelity: SSIM of the output's local ink-density vs the SOURCE's
  darkness at grids 96/128 (FINER than `d_tone`'s 16/32/64; see `d_fine96/128`). On
  the dense canonical woman it rises monotonically as the hatch gets finer/cleaner
  and keeps tracking local tone — so it gives headroom that `d_score` (pinned at
  100) no longer does. Current baseline ≈ **0.47**; the artist's dense woman output
  (`woman-sample-output-2`) reaches ≈ **0.73** — that gap is the climb. It is
  REPORTED-ONLY (NOT folded into `d_score`): it is not discriminating across the
  whole good manifold (the SPARSE good styles — space, samurai, woman-4 diamonds —
  legitimately score low on fine-tone, so gating on it would false-reject them),
  but the loop only ever renders the dense woman, where it is valid and robust
  (negatives crushed: moire ≈0.10, tone_invert ≈−0.38). **`guard_tick.sh` reverts a
  tick that drops `d_fine` by >`GUARD_FINE_DROP` (0.04) even while `d_score` holds.**
- `ink_coverage`, `ssim`, `edge_iou`, `path_fit` — legacy pixel co-signals only;
  near-flat across good/bad, recorded but **don't chase them**.

**Before deciding what to try this tick**, run:
```
tail -10 loop/metrics.jsonl | jq -c '{iter, d_score, d_fine, d_fidelity, d_style, d_ink}'
```
`d_score` is already 100 on the canonical — **steer by `d_fine`** (raise it toward
the artist's ~0.73). Low `d_fidelity`/`d_fine` → the lines don't track the source
(subject lost / density not tone-modulated, or the hatch is too coarse to render
fine local tone) — make the hatch finer/denser or change how the field follows the
image. Low `d_style` → it doesn't read as line art (check `d_freq_peak` ≈ 6–7,
`d_peakedness`, `d_ink`). If `d_fine` has been flat or dropping across the last
3–5 ticks, your hypotheses aren't working — try something QUALITATIVELY different
(a different idea category, or revert).

Your job: keep `d_score` at 100 (don't regress the gate) while raising `d_fine`
tick by tick toward the artist's ~0.73. A deterministic guard (`loop/guard_tick.sh`)
auto-commits a passing tick and auto-reverts a regression (absolute `d_score`
floor + relative drop, AND a `d_fine` drop > `GUARD_FINE_DROP`), but still
`git checkout -- engine/` your own change before exiting if you can see it made
things worse.

**Include the latest score line in your log entry.** Use `tail -1
loop/metrics.jsonl` after `score_tick.sh` runs.

---

## THE GOAL: REPLICATE THE ARTIST'S EXAMPLES

The north star is always to make the canonical output **pass for one of the
artist's own output** for the canonical input — `examples/woman/woman-source.jpeg`
→ the dense `examples/woman/woman-sample-output-2.jpeg`: nested diamonds that warp
around the face, dense/tone-modulated in the shadows and detail, clean diamonds in
flat areas, the subject clearly recognizable. `d_score` measures how well the
render re-expresses the SOURCE that way; the artist's own output scores ~100 —
closing the gap to it is the job.

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
method=march) and writes the stats.json (which records the `source` the
deterministic scorer compares against).

Then view your output and the reference visually:

```
# In your prompt, use Read on both:
Read loop/output/iter_NNN.png
Read examples/woman/woman-sample-output-2.jpeg
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

**Test:** canonical (woman-source, centered seed, levels 111, method=march)
- output: `loop/output/iter_NNN.svg` ({stats})
- source: `examples/woman/woman-source.jpeg`
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
