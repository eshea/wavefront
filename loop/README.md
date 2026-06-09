# Ralph Wiggum Loop — WAVEFRONT

Self-driving improvement loop. Each tick is one `claude -p` invocation
that reads `PROMPT.md`, makes a small change, tests it against the
reference images in `../examples/`, and appends to `EXPERIMENT_LOG.md`.

Inspired by Karpathy's autoresearch pattern: dumb outer loop, smart
inner agent, persistent memory in a flat log.

## Start

```
cd /Users/eshea/Projects/wavefront
./loop/ralph.sh
```

Defaults: 90 min wall-clock, max 200 iters, 6M token cap, Sonnet 4.6,
12 s between ticks. Override via env vars (see below).

## Stop

```
touch loop/STOP        # graceful — loop notices at next tick
```

Or Ctrl-C (trapped) or just wait — the duration / token budgets
backstop. If you really want it dead now: `pkill -f ralph.sh`.

## Tunables

| Env var | Default | Notes |
|---|---|---|
| `DURATION_SEC` | 5400 (90 min) | wall clock |
| `MAX_ITERS` | 200 | hard cap |
| `TOKEN_BUDGET` | 6_000_000 | cum input+output |
| `MODEL` | claude-sonnet-4-6 | use `claude-opus-4-7` for harder changes |
| `SLEEP_BETWEEN` | 12 | seconds between ticks |

Example: 2-hour Opus run capped at 4M tokens:

```
DURATION_SEC=7200 MODEL=claude-opus-4-7 TOKEN_BUDGET=4000000 \
  ./loop/ralph.sh
```

## Watch live

```
# loop's own status
./loop/ralph.sh                            # foreground
# or background:
./loop/ralph.sh > loop/log/run.log 2>&1 &

tail -f loop/log/run.log                   # script-level
tail -f loop/EXPERIMENT_LOG.md             # what claude appends
ls -lt loop/output/                        # generated SVG/PNG per iter
```

Per-iteration JSON (with full usage data):

```
ls loop/log/iter_*.json
jq '.usage' loop/log/iter_005.json
```

## Cost / usage monitoring

Each tick's JSON response includes `.usage.input_tokens`,
`.usage.output_tokens`, and `.usage.cache_read_input_tokens`. The loop
sums these and stops at `TOKEN_BUDGET`. Cumulative tally:

```
jq -s '
  { in:         (map(.usage.input_tokens // 0)         | add),
    out:        (map(.usage.output_tokens // 0)        | add),
    cache_read: (map(.usage.cache_read_input_tokens // 0) | add) }
' loop/log/iter_*.json
```

Sonnet 4.6 pricing (approx): $3/M input, $15/M output, $0.30/M cache
read. A typical iter here is ~50–200k cache-read + ~5–20k input +
~3–10k output ≈ $0.10–$0.40 per tick. 90 min × ~120 ticks ≈ $15–$50.
Opus is ~5× more.

## What it does each tick

`PROMPT.md` (read by each invocation) tells Claude to:

1. **Orient** — read `STATUS.md` (the generated start-of-tick view: live knob
   values + bounds, recent metrics trend, best `d_fine`, and why the last tick was
   kept/reverted) and `Read loop/output/_latest_compare.png` (the montage).
2. **Pick one** small change to try (from `IDEAS.md`, a different category than the
   last 2 ticks).
3. **Build** it — edit `engine/march_params.json` (the live knobs) or one engine file.
4. **Test** — `./loop/render_tick.sh <iter>` renders the canonical woman IN-PROCESS
   (method=march, levels 111; NOT via the Flask app, so engine edits take effect),
   writing `loop/output/iter_NNN.{svg,png,stats.json}`.
5. **Document** in `EXPERIMENT_LOG.md` — hypothesis, change, result, next step.

Then exit. The shell loops back, scoring (`score_tick.sh`) and guarding
(`guard_tick.sh`) the tick automatically.

## Per-tick generated artifacts (git-ignored; the agent's "legible environment")

The harness assembles these every tick so the inner agent reasons from one live,
self-consistent view instead of stale prose — and so config can't silently drift:

| Artifact | Written by | What it is |
|---|---|---|
| `STATUS.md` | `score_tick.sh` → `status.py` | Live knobs+bounds, metrics trend, best `d_fine`, last guard verdict. **Read first each tick.** |
| `output/_latest_compare.png` | `render_tick.sh` → `montage.py` | Montage: source \| current \| best-so-far \| artist target, metrics annotated. |
| `output/_best.png` / `_best.json` | `guard_tick.sh` | Snapshot of the highest-`d_fine` tick so the montage can show current-vs-best. |
| `.guard_feedback` | `guard_tick.sh` | One-line "why kept/reverted + what to try" — folded into `STATUS.md` for the next tick. |
| `EXPERIMENT_DIGEST.md` | `score_tick.sh` → `distill.py` | `EXPERIMENT_LOG.md` distilled to ✅ helped / ❌ ruled out / 🔁 open. |

`loop/tests/doc_freshness.sh` (in the harness) fails the build if the tuning docs
(`CLAUDE.md`, `PROMPT.md`, `IDEAS.md`) ever pin a `MARCH_*` value — those live ONLY
in `engine/march_params.json` (mirrored into `STATUS.md`), so they can't go stale.
`render_tick.sh` also garbage-collects old `iter_NNN.*` dumps (keeps the most recent
`OUTPUT_KEEP`, default 20).

## Pre-flight checklist

- Flask app reachable at `http://localhost:5055` (start with
  `PORT=5055 python app.py &` in the venv).
- `rsvg-convert` on PATH (`brew install librsvg` if missing).
- `jq` on PATH.
- `git status` clean-ish — the loop will git-checkout failed iterations,
  so unrelated unstaged changes could be lost. Commit or stash first.

## Safety notes

- Uses `--dangerously-skip-permissions` so Claude can run Bash / Edit /
  Write without prompting. That's required for autonomy. Don't run with
  secrets in env, and don't run untrusted prompts.
- The prompt instructs each iteration to revert via `git checkout --` if
  its change regressed quality. This works only for tracked files in the
  current repo.
- The 90-minute default cap is the primary backstop. Don't crank past
  3-4 hours without understanding your Claude subscription's rolling
  rate limit.
