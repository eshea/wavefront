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

| Input (pre) | Reference outputs (post) | Known settings |
|---|---|---|
| `examples/contour_woman.webp` | `examples/contour_woman_post1.jpeg`, `post2.jpeg`, `post3.jpeg`, `post4.webp`, `post5.webp` | seed=(227,225), CONTOURS=111, LINE SMOOTH=0.00 (from `contour_woman_settings.webp`) |

The woman pair is the **canonical test**. Use it. The exact settings
above are baked into `loop/score_tick.sh`.

**HOLDOUT — DO NOT TOUCH:** `loop/holdout/contour_space_pre.jpg` and
`loop/holdout/contour_space_post.webp` are the held-out test set. Do
not read from `loop/holdout/`. Do not score against it. Do not use it
for any inspiration. The harness will run it separately when humans
want to check for overfitting.

## QUANTITATIVE SIGNAL (read before deciding)

After each tick, `loop/score_tick.sh` runs automatically and appends
one JSON line to `loop/metrics.jsonl` with three numbers per output:

- `judge_score` (0–100, **primary metric**) — visual judgment from a
  local Qwen3 122B vision model. This is well-aligned with human
  judgment. Higher = better.
- `ssim` (0–1, secondary) — pixel-level structural similarity. Misleading
  on its own (rewards whitespace match), useful only as a co-signal.
- `edge_iou` (0–1, secondary) — Canny edge agreement. Same caveat.
- `path_fit` (0–1) — closeness to reference path count (452). Sanity.

**Before deciding what to try this tick**, run:
```
tail -10 loop/metrics.jsonl | jq -c '{iter, judge_score, ssim, edge_iou, path_fit}'
```
to see the recent trajectory. If judge_score has been flat or dropping
across the last 3-5 ticks, your recent hypotheses aren't working — try
something qualitatively different (revert to an earlier sweet-spot
config? change a different parameter?).

**Iter 014 was the human-judged best (score 95).** Iter 001 also 92.
Later iters regressed (loop over-blurred). Your job: get back above 95
on judge_score, ideally hitting 100. Don't trust your own visual
judgment over the metric — if your change drops judge_score below the
last 3 iters' average, `git checkout --` it before exiting.

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

Then render the canonical test:

```
ITER=$(printf '%03d' $(cat loop/.iter 2>/dev/null || echo 1))
curl -s -X POST \
  -F "image=@examples/contour_woman.webp" \
  -F "levels=111" \
  -F "smooth=0.00" \
  -F "lum_mix=1.0" \
  -F "wt_range=0.0" \
  -F "seed_x=227" \
  -F "seed_y=225" \
  http://localhost:5055/process \
  | python3 -c "import json,sys; d=json.load(sys.stdin); open('loop/output/iter_${ITER}.svg','w').write(d['svg']); print('stats:', d['stats'])"
```

Rasterize to PNG using rsvg-convert (already installed on this machine
via brew). This is REQUIRED so you can use Read to view your output as
an image:

```
ITER=$(printf '%03d' $(cat loop/.iter 2>/dev/null || echo 1))
rsvg-convert -w 434 loop/output/iter_${ITER}.svg \
  -o loop/output/iter_${ITER}.png
```

Then view your output and the reference visually:

```
# In your prompt, use Read on both:
Read loop/output/iter_NNN.png
Read examples/contour_woman_post1.jpeg
```

Read returns images visually. Look at them and compare specifically:
ring shape (diamonds vs circles), facial feature definition, line
density, noise in background regions, stroke uniformity.

---

## LOG ENTRY TEMPLATE

Append to `loop/EXPERIMENT_LOG.md`:

```
## Iter NNN · YYYY-MM-DD HH:MM · {one-line summary}

**Hypothesis:** {one sentence — what you thought would help}

**Change:** {file:line summary, e.g. "engine/field.py:50 — clamp lum
contribution to top 90th percentile"}

**Test:** canonical (woman, seed 227,225, lvl 111, smooth 0.00)
- output: `loop/output/iter_NNN.svg` ({stats})
- reference: `examples/contour_woman_post1.jpeg`
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
