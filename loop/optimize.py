#!/usr/bin/env python3
"""
loop/optimize.py — multi-input black-box tuner for the MARCH_* aesthetic knobs.

WHAT: searches the 6-dim MARCH_* parameter vector (engine.march.PARAM_BOUNDS) for
the config that maximizes the canonical woman render's fine-hatch quality (dscore's
d_fine) WITHOUT overfitting that one image — the same params must still produce
VALID art on the other sources (samurai, space). Writes the winner to the
externalized config engine/march_params.json.

WHY black-box (not gradient descent): the pipeline is non-differentiable (geodesic
MCP → marching squares → SSIM). With only 6 knobs and a ~5s eval, derivative-free
search (Latin-hypercube exploration + Nelder-Mead polish) sweeps the space far
better than hand-tuning one knob per tick.

THE OBJECTIVE (and why it's shaped this way):
  maximize   woman.d_fine                      # the climb signal, meaningful only
                                               #   on the DENSE woman (sparse styles
                                               #   like space/samurai score low on
                                               #   fine-tone even for the ARTIST —
                                               #   see dscore FINE_* note)
  subject to (ALL sources, hard constraints):
    d_score >= per-source floor                # calibrated good-art bar = the
                                               #   cross-input generalization guard
    d_ink   <  INK_MAX                         # no solid-black blowout
    d_diag  in DIAG_BAND  (woman only)         # keep the ±45° diamond aesthetic
A candidate that violates any constraint on any source is penalised below every
feasible one, so the search stays inside the already-validated region (it can't
hill-climb d_fine into the metric's blind spots — the documented borderline trap).

USAGE:
    python loop/optimize.py [--evals 120] [--seed 0] [--polish]
                            [--sources woman,samurai,space] [--no-write]
                            [--time-budget SECONDS]
Stop early: touch loop/STOP. Leaderboard → loop/optimize_log.jsonl. The winning
config is applied + saved to engine/march_params.json (unless --no-write).
"""
import sys
import json
import time
import argparse
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import engine.march as march          # noqa: E402  (the live tuning surface)
from loop.render import render        # noqa: E402
from loop import dscore               # noqa: E402

# ── the input set + per-source validity constraints ──────────────────────
# d_fine is maximized on `primary` only (it's meaningful only on the dense woman);
# every source must stay VALID (d_score floor + no ink blowout) so we don't overfit.
SOURCES = {
    "woman":   REPO / "examples" / "woman" / "woman-source.jpeg",
    "samurai": REPO / "examples" / "samurai" / "samurai-source.jpg",
    "space":   REPO / "examples" / "space" / "space-source.jpg",
}
PRIMARY = "woman"
DSCORE_FLOOR = {"woman": 95, "samurai": 58, "space": 80}   # calibrated good-art bars
INK_MAX = 0.85                                              # dscore's own blowout gate
DIAG_BAND = (0.45, 0.60)                                    # ±45° diamond band (woman)
PENALTY = 10.0          # per-unit constraint-violation penalty (>> any d_fine gain)

SCRATCH = REPO / "loop" / "output" / "_opt"
LOG = REPO / "loop" / "optimize_log.jsonl"
STOP = REPO / "loop" / "STOP"


def evaluate(params, sources):
    """Render+score every source with `params`; return (objective, feasible, detail).
    objective = primary d_fine − PENALTY·(total constraint violation). Feasible =
    no violations on any source."""
    march.apply_params(params)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    detail, violation = {}, 0.0
    primary_fine = -1.0
    for i, name in enumerate(sources):
        src = SOURCES[name]
        _, png, _, _ = render(900 + i, method="march", levels=111, smooth=0.0,
                              lum_mix=0.8, wt_range=0.0, input_path=src,
                              png_width=780, out_dir=SCRATCH)
        m = dscore.score(png, src)
        d_score, d_fine = m["d_score"], m.get("d_fine") or 0.0
        d_ink, d_diag = m["d_ink"], m["d_diag"]
        detail[name] = {"d_score": d_score, "d_fine": round(d_fine, 4),
                        "d_ink": d_ink, "d_diag": d_diag}
        # constraints → violation magnitude (0 when satisfied)
        violation += max(0.0, DSCORE_FLOOR[name] - d_score) / 100.0
        violation += max(0.0, d_ink - INK_MAX)
        if name == PRIMARY:
            violation += max(0.0, DIAG_BAND[0] - d_diag) + max(0.0, d_diag - DIAG_BAND[1])
            primary_fine = d_fine
    objective = primary_fine - PENALTY * violation
    return objective, (violation == 0.0), detail


def _vec_to_params(vec):
    return {n: float(v) for n, v in zip(march.PARAM_NAMES, vec)}


def _lhs(n, dim, rng):
    """Latin-hypercube samples in the unit cube (better space-filling than uniform)."""
    cut = np.linspace(0, 1, n + 1)
    pts = rng.uniform(cut[:-1], cut[1:], size=(dim, n)).T
    for j in range(dim):
        rng.shuffle(pts[:, j])
    return pts


def search(evals, seed, sources, polish, time_budget):
    rng = np.random.default_rng(seed)
    names = march.PARAM_NAMES
    lo = np.array([march.PARAM_BOUNDS[n][0] for n in names])
    hi = np.array([march.PARAM_BOUNDS[n][1] for n in names])
    t0 = time.time()
    LOG.unlink(missing_ok=True)

    incumbent = np.array([march.current_params()[n] for n in names])  # current config
    best = {"vec": incumbent, "obj": -1e9, "feasible": False, "detail": None}

    def consider(vec, phase):
        nonlocal best
        vec = np.clip(vec, lo, hi)
        obj, feas, detail = evaluate(_vec_to_params(vec), sources)
        rec = {"phase": phase, "obj": round(obj, 4), "feasible": feas,
               "params": {n: round(float(v), 4) for n, v in zip(names, vec)},
               "detail": detail, "t": round(time.time() - t0, 1)}
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        # prefer feasible over infeasible; among same feasibility, higher objective
        better = (feas, obj) > (best["feasible"], best["obj"])
        if better:
            best = {"vec": vec, "obj": obj, "feasible": feas, "detail": detail}
        flag = "✓" if feas else "·"
        star = " *BEST*" if better else ""
        wf = detail[PRIMARY]["d_fine"]
        print(f"[opt:{phase}] {flag} obj={obj:+.4f} woman.d_fine={wf:.4f}{star}")
        return obj

    def stop():
        if STOP.exists():
            print("[opt] STOP file present — halting"); return True
        if time_budget and time.time() - t0 > time_budget:
            print("[opt] time budget reached — halting"); return True
        return False

    # Phase 0: the current config (incumbent baseline).
    print(f"[opt] sources={list(sources)}  primary={PRIMARY}  evals={evals}")
    consider(incumbent, "seed")

    # Phase 1: Latin-hypercube exploration.
    explore = max(0, evals - (12 if polish else 0))
    if explore:
        unit = _lhs(explore, len(names), rng)
        for k in range(explore):
            if stop():
                break
            consider(lo + unit[k] * (hi - lo), "explore")

    # Phase 2: Nelder-Mead polish from the best feasible point (optional).
    if polish and not stop():
        try:
            from scipy.optimize import minimize
            x0 = best["vec"]
            print(f"[opt] polishing from obj={best['obj']:+.4f} …")
            minimize(lambda v: -consider(v, "polish"), x0, method="Nelder-Mead",
                     options={"maxfev": 40, "xatol": 0.05, "fatol": 0.003})
        except Exception as e:                       # noqa: BLE001
            print(f"[opt] polish skipped: {e}")

    return best, names


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--evals", type=int, default=120, help="exploration budget")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--sources", default="woman,samurai,space")
    p.add_argument("--polish", action="store_true", help="Nelder-Mead local refine")
    p.add_argument("--time-budget", type=float, default=0.0, help="seconds (0=off)")
    p.add_argument("--no-write", action="store_true", help="don't write the config")
    a = p.parse_args()

    sources = [s for s in a.sources.split(",") if s in SOURCES]
    if PRIMARY not in sources:
        sources.insert(0, PRIMARY)

    best, names = search(a.evals, a.seed, sources, a.polish, a.time_budget or None)

    winner = {n: round(float(v), 4) for n, v in zip(names, best["vec"])}
    print("\n[opt] ── result ──────────────────────────────")
    print(f"[opt] feasible={best['feasible']}  objective={best['obj']:+.4f}")
    print(f"[opt] params: {winner}")
    print(f"[opt] detail: {json.dumps(best['detail'])}")
    if best["feasible"] and not a.no_write:
        march.apply_params(winner)
        march.save_params()
        print(f"[opt] wrote {march._PARAMS_PATH}")
    elif not best["feasible"]:
        print("[opt] no feasible config found — NOT writing (constraints unmet)")
    else:
        print("[opt] --no-write set — config unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
