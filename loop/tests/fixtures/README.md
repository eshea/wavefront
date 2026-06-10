# Calibration fixtures

Committed test images for `loop/tests/dscore_calib.sh` (the deterministic
scorer's acceptance gate). Regenerate with:

```bash
python loop/tests/make_hard_negatives.py
```

These are a **fixed acceptance-gate asset**, not loop inputs. The ralph tuning
agent must **never** read, score against, or take inspiration from them, and they
must never be deleted — they exist to keep `dscore.py` honest. (This is distinct
from `loop/holdout/`, the overfit-generalization set; fixtures live here under
`loop/tests/` because they gate the scorer, not the engine.)

All are rendered from the canonical `examples/woman/woman-source.jpeg` through the
real pipeline (`loop/render.py`) with deliberately-wrong engine configs.

## `hard_neg/` — GATED (must score LOW, with a margin below the artist outputs)

Failure modes that are **cleanly separable** from real art by a deterministic
metric. The gate asserts each scores `<= NEG_MAX`, and that the worst artist
output beats the best of these by `>= MARGIN`.

| file | config | why it's bad | caught by |
|---|---|---|---|
| `seed_blob.png` | `method=wave` | additive seed-centric field; density follows the L1 geometry, not the image (`d_tone ≈ 0`). The original false-100. | tone-fidelity |
| `tone_invert.png` | march, dark↔bright swapped | right amount of ink, but density **anti-correlated** with source darkness (dense where bright). | tone-fidelity (negative) |
| `moire.png` | march, `MARCH_BASE=3.0` | diamonds barely bent by the image; over-regular stiff grid (`d_diag ≈ 0.83`). | diamond factor |

## `borderline/` — COMMITTED but deliberately NOT gated

Off-aesthetic renders that are nonetheless **metrically inside the legitimate
artist manifold** on every deterministic global statistic we can compute. They
cannot be pushed below a gate threshold without also false-rejecting genuine
artist outputs, so gating on them would force the scorer to overfit.

| file | config | why it can't be gated |
|---|---|---|
| `muddy.png` | march, `MARCH_TONE=48` | shadows collapse to solid fill, but its tone/ink/edge stats are ~ the **dense `woman-sample-output-2`** artist output (ink ≈ 0.48, multi-scale tone ≈ 0.8). |
| `axis_flow.png` | `method=flow` | non-diamond streamline aesthetic, but its diamond signature (`d_diag ≈ 0.39`, good tone) is ~ the **artist's own flowing `samurai-output-1`**. |

**Why this matters:** the artist's good outputs span sparse-clean diamonds
(`woman-4`), dense fine-hatching (`woman-1/2`), and busy flowing waves
(`samurai`). That manifold is wide enough that "plausible-but-off" renders fall
inside it. We gate the failures we *can* separate and document the ones we can't,
rather than tuning the scorer to reject art it should accept. If you think you've
found a metric that separates a borderline case from `woman-2`/`samurai`, verify
it does **not** drop those two below their thresholds before moving it to `hard_neg/`.
