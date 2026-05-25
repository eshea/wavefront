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
| `examples/contour_space_pre.jpg` | `examples/contour_space_post.webp` | unknown — infer |
| `examples/contour_woman.webp` | `examples/contour_woman_post1.jpeg`, `post2.jpeg`, `post3.jpeg`, `post4.webp`, `post5.webp` | seed=(227,225), CONTOURS=111, LINE SMOOTH=0.00 (from `contour_woman_settings.webp`) |

The woman pair is the **canonical test** because we know the artist's
exact CORE settings. Use it unless you have a specific reason to use the
helmet pair.

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

**Result:** better / same / worse · vs. reference: {closer / further /
neutral}

**Next:** {hypothesis for next tick, or "review" if unclear}
```

---

## RULES

1. **Don't ask questions.** This is autonomous. Make a call and move on.
2. **One change per tick.** Three small wins beat one giant unfinished rewrite.
3. **If app is broken, fixing it IS the tick.** Document and exit.
4. **If you ran a worse change, revert it** with `git checkout -- path`
   before exiting. Don't leave the codebase regressed.
5. **Stay in CORE territory** for now — don't add STUDIO features unless
   the log explicitly schedules them.
6. **Never delete `examples/` or `loop/EXPERIMENT_LOG.md`.**
7. If the experiment log says "loop done", create a file `loop/STOP` and
   exit. The wrapper will halt.

You have Bash, Read, Edit, Write. Use them. Don't use sub-agents.
