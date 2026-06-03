#!/usr/bin/env bash
# loop/tests/march_smoke.sh — smoke test for the marching-waves field (method=march).
#
# Asserts build_march_field returns a finite, correctly-shaped scalar field and
# that a method=march render produces a non-degenerate contour set. Pure in-process
# (no Flask app needed). Exit 0=pass, 77=skip, other=fail.
set -u
cd "$(dirname "$0")/../.."

SKIP_EXIT_CODE=${LOOP_SKIP_EXIT_CODE:-77}
source .venv/bin/activate >/dev/null 2>&1

python3 - <<'PY'
import sys
sys.path.insert(0, ".")
import numpy as np

try:
    from engine.field import load_and_preprocess, to_luminance
    from engine.march import build_march_field
    from engine.contour import extract_contours
except Exception as e:
    print(f"[march_smoke] import failed: {e}", file=sys.stderr)
    sys.exit(1)

# 1. Field is finite, right shape, and a 4-connected geodesic (min at the seed).
rgb, _, proc = load_and_preprocess("examples/contour_space_pre.jpg")
lum = to_luminance(rgb)
sx, sy = proc[0] // 2, proc[1] // 2
field, fmin, fmax = build_march_field(lum, sx, sy, lum_mix=0.8)

H, W = lum.shape
assert field.shape == (H, W), f"field shape {field.shape} != {(H, W)}"
assert np.isfinite(field).all(), "field has non-finite values"
assert fmax > fmin, f"degenerate field range [{fmin}, {fmax}]"
assert field[sy, sx] <= fmin + 1e-3, "field minimum should be at the seed"

# 2. A march render yields a non-degenerate contour set.
contours, stats = extract_contours(field, 90, fmin, fmax)
paths = stats.get("paths", 0)
assert paths > 20, f"too few paths ({paths}) — degenerate render"

# 3. Sanity: a flat (uniform) cost field must be pure L1 diamonds — verify the
#    builder honors 4-connectivity by checking a uniform-image field equals |dx|+|dy|.
flat = np.full((64, 64), 128.0, dtype=np.float32)
f2, _, _ = build_march_field(flat, 32, 32, lum_mix=0.0)  # lum_mix 0 -> tone term off
ys, xs = np.mgrid[0:64, 0:64]
l1 = np.abs(ys - 32) + np.abs(xs - 32)
# MARCH_BASE scales the L1 field; check proportionality (ignore the seed cell).
import engine.march as M
expected = M.MARCH_BASE * l1
err = np.max(np.abs(f2 - expected))
assert err <= M.MARCH_BASE + 1e-3, f"flat field not L1-proportional (max err {err})"

print(f"[march_smoke] OK  paths={paths} range=[{fmin:.1f},{fmax:.1f}] L1_err={err:.3f}")
PY
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "[march_smoke] FAIL (rc=$rc)"
  exit 1
fi
exit 0
