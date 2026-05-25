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

1. **Review** the last entries in `EXPERIMENT_LOG.md`
2. **Pick one** small change to try
3. **Build** it (Edit one or two files)
4. **Test** by curl-ing `/process` with the canonical settings from
   `examples/contour_woman_settings.webp` (seed 227,225, levels 111,
   smooth 0.00) — input `examples/contour_woman.webp`, output written
   to `loop/output/iter_NNN.svg`. Rasterized via `rsvg-convert` for
   visual comparison.
5. **Document** in `EXPERIMENT_LOG.md` — hypothesis, change, result,
   next step. Revert via `git checkout` if regression.

Then exit. The shell loops back.

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
