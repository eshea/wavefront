#!/usr/bin/env python3
"""
loop/tests/make_hard_negatives.py — regenerate the hard-negative fixtures.

Hard negatives are PLAUSIBLE-BUT-WRONG renders: they pass the degenerate gate
(they have real line structure) but are NOT good matches for the VEX-LINE
aesthetic. They are the corpus that `loop/tests/dscore_calib.sh` asserts must
score WELL BELOW the artist outputs — the mechanism that makes the scorer's
false-hill-climbing detectable (a dscore change that inflates one of these flips
the gate red).

This is run BY A HUMAN, deliberately, to (re)build committed fixtures. It is
NOT part of the ralph loop and must never be invoked by the tuning agent — the
fixtures it produces are a fixed acceptance-gate asset (see fixtures/README.md).

Each negative renders the canonical woman source through the SAME pipeline as a
real tick (loop/render.py) but with a known-bad engine config. They are chosen to
be UNAMBIGUOUSLY worse than any artist output (a borderline "merely dense" render
is NOT a good negative — the artist style space legitimately includes dense
fine-hatching like woman-sample-output-2, so density alone is not a defect):

GATED negatives (fixtures/hard_neg/ — the calib gate asserts these score LOW with
a margin below the artist outputs). These are CLEANLY separable from real art:

  seed_blob    method=wave              -> additive seed-centric field, density
                                           follows the L1 geometry not the image
                                           (d_tone ~= 0); the original false-100.
                                           Caught by tone-fidelity.
  moire        march, MARCH_BASE high   -> diamonds barely bent by the image;
                                           over-regular stiff grid (d_diag ~0.86).
                                           Caught by the diamond factor.
  tone_invert  march, dark<->bright     -> right amount of ink, but density
                                           ANTI-correlated with source darkness
                                           (dense where bright). Caught by tone.

BORDERLINE negatives (fixtures/borderline/ — committed but deliberately NOT gated).
These are off-aesthetic but, empirically, sit INSIDE the legitimate artist manifold
on every deterministic global statistic we can compute — they cannot be pushed below
the gate without false-rejecting real artist outputs (the artist's own flowing
samurai and dense woman-2 share their tone/diamond signatures). Kept as a documented
caution: do NOT add them to the gate. See fixtures/README.md.

  muddy        march, MARCH_FLOOR ~0    -> shadows collapse to solid fill; metrically
                                           ~ the dense woman-2 artist output.
  axis_flow    method=flow              -> streamlines following the image; non-diamond
                                           aesthetic, but metrically ~ the artist's own
                                           flowing samurai output (diag ~0.39, good tone).

Usage:
    python loop/tests/make_hard_negatives.py
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

import engine.march as march          # noqa: E402  (monkeypatch its module globals)
from loop.render import render        # noqa: E402

SRC = REPO / "examples" / "woman" / "woman-source.jpeg"
FIX = REPO / "loop" / "tests" / "fixtures"

# Each config: (name, dir, render-kwargs, march-global-overrides, invert_tone?)
# dir = "hard_neg" (gated by dscore_calib.sh) or "borderline" (committed, NOT gated).
CONFIGS = [
    ("seed_blob",   "hard_neg",   {"method": "wave"},  {},                          False),
    ("moire",       "hard_neg",   {"method": "march"}, {"MARCH_BASE": 3.0,
                                                        "MARCH_FLOOR": 0.9},        False),
    ("tone_invert", "hard_neg",   {"method": "march"}, {},                          True),
    ("muddy",       "borderline", {"method": "march"}, {"MARCH_FLOOR": 0.005,
                                   "MARCH_BASE": 0.05, "MARCH_BLUR": 0.5},          False),
    ("axis_flow",   "borderline", {"method": "flow"},  {},                          False),
]


def _apply(overrides):
    """Set engine.march globals, returning the prior values for restoration."""
    prior = {k: getattr(march, k) for k in overrides}
    for k, v in overrides.items():
        setattr(march, k, v)
    return prior


def main() -> int:
    if not SRC.exists():
        sys.stderr.write(f"make_hard_negatives: source missing: {SRC}\n")
        return 2
    tmp = FIX / "_tmp"

    orig_pre = march._preprocess_gray
    for i, (name, subdir, kw, overrides, invert) in enumerate(CONFIGS):
        (FIX / subdir).mkdir(parents=True, exist_ok=True)
        prior = _apply(overrides)
        if invert:
            # Invert gray so the wave is FAST in dark and SLOW in bright,
            # producing density anti-correlated with the true source darkness.
            def _inverted(lum, _orig=orig_pre):
                gray, edge = _orig(lum)
                return 1.0 - gray, edge
            march._preprocess_gray = _inverted
        try:
            _, png_path, _, _ = render(
                i, input_path=SRC, out_dir=tmp,
                levels=111, smooth=0.0, lum_mix=0.8, png_width=780, **kw)
            dst = FIX / subdir / f"{name}.png"
            shutil.copyfile(png_path, dst)
            print(f"[make_hard_negatives] wrote {dst.relative_to(REPO)}")
        finally:
            march._preprocess_gray = orig_pre
            for k, v in prior.items():
                setattr(march, k, v)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[make_hard_negatives] done -> {FIX.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
