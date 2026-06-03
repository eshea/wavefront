#!/usr/bin/env python3
"""
loop/judge.py — visual judge using a local vision LLM.

Scores a candidate WAVEFRONT output by comparing it to ONE reference
plus ONE calibration anchor per call. Uses 3 images per request (well
within what the local vLLM tolerates — 6 crashes it).

To exploit multi-reference scoring without overloading the server,
multiple calls can be chained (e.g. against post1, post2, post4) and
the max score taken. By default, one call is made against post1.jpeg
(the medium-density reference that matches our test settings).

Calibration anchors are baked into the prompt with explicit
human-rated scores so the judge is forced to place the candidate
on the same scale as known outputs.

Emits one JSON line:
    {"output":..., "judge_score": 0..100, "judge_notes":...,
     "vs_anchor_high":..., "model":..., "elapsed_s":...}

Backend (OpenAI-compatible /v1/chat/completions) — AUTO-FALLBACK:
    The judge probes known vision backends and uses the first one that's live,
    so it keeps working when a box is down:
        1. http://192.168.50.135:8000  (vLLM Qwen3)
        2. http://192.168.50.135:5002  (llama.cpp Qwen3.5-abliterated)
    WAVEFRONT_LLM           moves a base URL to the front of the probe order.
    WAVEFRONT_LLM_BACKENDS  comma-separated list to REPLACE the candidates.
    WAVEFRONT_LLM_MODEL     model field (default "qwen"; llama.cpp ignores it).
    The vLLM-only `chat_template_kwargs` we send is ignored harmlessly elsewhere.
    ⚠ SCALE WARNING: backends do NOT score on the same scale (a good render is
      ~85 on vLLM-Qwen3 but ~40 on llama.cpp-Qwen3.5-abl). Every record carries
      `judge_backend`; guard_tick.sh keys its floor off it and only compares
      within the same backend, so a fallback can't trigger a false regression.

CLI:
    python loop/judge.py --output PATH [--reference PATH] [--iter N] [--samples N]
"""

import argparse
import base64
import io
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import urllib.request
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompts  # noqa: E402  (loop/prompts.py — externalized prompt loader)


LLM_BASE = os.environ.get("WAVEFRONT_LLM", "http://neuromancer:8000")
LLM_MODEL = os.environ.get("WAVEFRONT_LLM_MODEL", "qwen")
MAX_SIDE = 512

# Known interchangeable vision backends, in default-preference order: the vLLM
# Qwen3 box, then the llama.cpp Qwen3.5-abliterated box. resolve_backend()
# probes these and uses the first one that's live, so the judge keeps working
# when one server is down. Override the whole list with WAVEFRONT_LLM_BACKENDS
# (comma-separated). NOTE: backends score on DIFFERENT scales — every record
# stamps judge_backend, and guard_tick.sh keys its thresholds off it.
KNOWN_BACKENDS = [
    "http://neuromancer:8000",      # vLLM Qwen3.5-122B (INT4, vision) — primary
    "http://192.168.50.135:8000",   # vLLM Qwen3
    "http://192.168.50.135:5002",   # llama.cpp Qwen3.5-abliterated
]


def _candidate_backends() -> list[str]:
    """Ordered, de-duplicated list of backends to try."""
    raw = os.environ.get("WAVEFRONT_LLM_BACKENDS")
    if raw:
        cands = [b.strip().rstrip("/") for b in raw.split(",") if b.strip()]
    else:
        # Primary (WAVEFRONT_LLM / default vLLM) first, then any other known box.
        primary = LLM_BASE.rstrip("/")
        cands = [primary] + [b for b in KNOWN_BACKENDS if b.rstrip("/") != primary]
    seen, ordered = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); ordered.append(c)
    return ordered


def _is_live(base: str, timeout: float = 3.0) -> bool:
    """Quick liveness probe — GET /v1/models (both vLLM and llama.cpp serve it)."""
    try:
        req = urllib.request.Request(f"{base}/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def resolve_backend() -> str:
    """Return the first live backend (probed in preference order).

    Falls back to the first candidate if none answer, so the subsequent
    call_llm fails with a clear error rather than silently doing nothing.
    """
    cands = _candidate_backends()
    if len(cands) == 1:
        return cands[0]                      # nothing to fall back to; skip probes
    for base in cands:
        if _is_live(base):
            sys.stderr.write(f"judge.py: using backend {base}\n")
            return base
    sys.stderr.write(
        f"judge.py: no backend live among {cands}; trying {cands[0]} anyway\n")
    return cands[0]

REPO = Path(__file__).resolve().parent.parent
DEFAULT_REF = REPO / "examples" / "contour_woman_lineart.png"  # clean line-art
# (cropped from the CONTOUR-V CORE screenshot — same woman, clean diamond geometry,
#  a sharper target than the ink-on-photo contour_woman_post1.jpeg)
ANCHOR_HIGH = REPO / "examples" / "contour_woman_post1.jpeg"  # the ARTIST's real
# plotted output — the ground-truth "good" (was a synthetic WAVEFRONT render).
ANCHOR_LOW_DESC = (
    "ANCHOR_15 (not shown): a previous candidate that was nearly blank "
    "with sparse Lissajous-like noise, no face visible — humans rated 15."
)


# The judge rubric lives in loop/prompts/judge.md (load() reloads it live in dev,
# caches in prod) so it can be prompt-engineered without touching code.


def img_to_data_url(path: Path, max_side: int = MAX_SIDE) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_side:
        if w >= h:
            img = img.resize((max_side, int(h * max_side / w)), Image.LANCZOS)
        else:
            img = img.resize((int(w * max_side / h), max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


def labeled(text: str, path: Path) -> list[dict]:
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": img_to_data_url(path)}},
    ]


def call_llm(content: list[dict], timeout: int = 45,
             temperature: float = 0.0, base: str = LLM_BASE) -> dict:
    # 45s, not the old 180s: a healthy judge replies in ~2s, and with
    # --samples making N calls a long per-call timeout would stall the
    # loop for minutes whenever the vLLM box is offline.
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 400,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# Reference-replication rubric (loop/prompts/judge.md): the model rates two graded
# dimensions 0-10 — diamond_match (same nested-diamond lattice as the reference) and
# resemblance (could pass as the artist's own output) — plus a face gate. The score
# is derived deterministically so it's reproducible at temp 0. This is deliberately
# HARSH and reference-calibrated: a real artist output scores ~85-100, current
# attempts ~0-25, so there is real headroom and the loop has a gradient to climb
# (the old saturating checklist rated every decent render ~92-100, which was useless).
_DIM_KEYS = ("diamond_match", "resemblance")
_FACE_CAP = 25   # no real face -> score can't exceed this (kills faceless lattices)


def _as_bool(v):
    """Coerce a JSON value to bool; return None if it isn't clearly boolean."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "y", "1"):
            return True
        if s in ("false", "no", "n", "0"):
            return False
    return None


def _as_unit10(v):
    """Coerce to an int in [0, 10]; None if not a number."""
    try:
        return max(0, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


def score_from_checks(checks: dict):
    """Deterministic score from the reference-replication dims (loop/prompts/judge.md).

    score = (diamond_match + resemblance) / 20 * 100, then capped at _FACE_CAP when
    no real face is present. Returns None if a dimension is missing (caller falls
    back to any raw model score).
    """
    dm = checks.get("diamond_match")
    rs = checks.get("resemblance")
    if dm is None or rs is None:
        return None
    score = int(round((dm + rs) / 20.0 * 100.0))
    if checks.get("face") is False:
        score = min(score, _FACE_CAP)
    return max(0, min(100, score))


def parse(reply: dict) -> dict:
    msg = reply["choices"][0]["message"]
    text = msg.get("content") or msg.get("reasoning") or ""
    result = {"score": -1, "notes": "", "gap": "", "checks": {}}
    # Match any flat JSON object that carries one of our dimension keys.
    for blob in re.findall(r"\{[^{}]*(?:diamond_match|resemblance|score)[^{}]*\}", text, re.DOTALL):
        try:
            d = json.loads(blob)
        except json.JSONDecodeError:
            continue
        checks = {k: _as_unit10(d.get(k)) for k in _DIM_KEYS}
        checks["face"] = _as_bool(d.get("face"))
        derived = score_from_checks(checks)
        if derived is not None:                 # rubric dims present -> authoritative
            result["score"] = derived
        else:                                   # no dims -> fall back to a raw model score
            try:
                s = int(d.get("score", -1))
            except (TypeError, ValueError):
                continue
            if not (0 <= s <= 100):
                continue
            result["score"] = s
        result["checks"] = checks
        result["notes"] = str(d.get("notes", "")).strip()
        result["gap"] = str(d.get("biggest_gap", "")).strip()
        return result
    m = re.search(r"score[^0-9-]{0,12}([0-9]{1,3})", text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 100:
            result["score"] = n
            result["notes"] = f"(score parsed without JSON) {text[:120].strip()}"
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--reference", type=Path, default=DEFAULT_REF)
    p.add_argument("--iter", type=int, default=None)
    p.add_argument("--samples", type=int, default=1,
                   help="number of judge calls (median reported). DEFAULT 1 is a "
                        "single temperature-0 read: the rubric score "
                        "(score_from_checks) is DETERMINISTIC, so one read is "
                        "stable and reproducible. N>1 draws at temp>0 and only "
                        "INJECTS noise (the ratings drift between draws) — "
                        "leave it at 1 unless debugging.")
    args = p.parse_args()

    for path, name in [(args.output, "output"),
                       (args.reference, "reference")]:
        if not path.exists():
            sys.stderr.write(f"judge.py: missing {name} {path}\n"); return 2

    # Two images only: the rubric is a DIRECT candidate-vs-reference comparison.
    # (Adding a third "example" image diluted the comparison and wasn't needed —
    # real artist outputs still score 85-100 against the reference alone.)
    content: list[dict] = [{"type": "text", "text": prompts.load("judge")}]
    content += labeled("REFERENCE (the target to replicate):", args.reference)
    content += labeled("CANDIDATE (score this):", args.output)

    n = max(1, args.samples)
    # temp 0 = deterministic. The checklist score is computed from the booleans,
    # which the model returns deterministically at temp 0 (verified: 5/5 identical
    # on the same image). So the default single read is stable AND reproducible.
    # Multi-sampling warms to temp>0, which makes the boolean checks flip between
    # draws — i.e. it ADDS the noise the median was meant to remove. Only use N>1
    # to debug; the median then papers over self-inflicted variance.
    temperature = 0.0 if n == 1 else float(os.environ.get("WAVEFRONT_JUDGE_TEMP", 0.25))

    # Pick a live backend once, up front, and use it for every sample (never
    # switch mid-scoring — that would mix scales within one judge_score).
    backend = resolve_backend()

    t0 = time.monotonic()
    samples: list[dict] = []  # successful parses only
    last_err = None
    for _ in range(n):
        try:
            parsed = parse(call_llm(content, temperature=temperature, base=backend))
        except Exception as e:  # network/HTTP blip — skip this draw
            last_err = e
            sys.stderr.write(f"judge.py: LLM call failed: {e}\n")
            continue
        if parsed["score"] >= 0:
            samples.append(parsed)
    elapsed = round(time.monotonic() - t0, 1)

    if not samples:
        print(json.dumps({
            "iter": args.iter, "output": str(args.output),
            "judge_score": -1, "judge_notes": f"all {n} call(s) failed: {last_err}",
            "judge_gap": "", "model": LLM_MODEL, "judge_backend": backend,
            "samples": n, "elapsed_s": elapsed,
        }))
        return 1

    scores = [s["score"] for s in samples]
    median = int(round(statistics.median(scores)))
    # Notes come from the sample closest to the median (representative read).
    rep = min(samples, key=lambda s: abs(s["score"] - median))
    rec = {
        "iter": args.iter,
        "output": str(args.output),
        "reference": str(args.reference),
        "judge_score": median,
        "judge_notes": rep["notes"],
        "judge_gap": rep["gap"],             # biggest difference from the reference
        "judge_checks": rep.get("checks", {}),  # face/diamond/even_white/clean (audit)
        "judge_samples": scores,             # raw scores for audit
        "judge_spread": max(scores) - min(scores),  # 0 == fully agreed
        "samples": len(samples),             # successful draws
        "model": LLM_MODEL,
        "judge_backend": backend,            # which server scored this — scores
                                             # from different backends are NOT on
                                             # the same scale; don't compare them
        "elapsed_s": elapsed,
    }
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
