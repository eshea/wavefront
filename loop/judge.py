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


LLM_BASE = os.environ.get("WAVEFRONT_LLM", "http://192.168.50.135:8000")
LLM_MODEL = os.environ.get("WAVEFRONT_LLM_MODEL", "qwen")
MAX_SIDE = 512

# Known interchangeable vision backends, in default-preference order: the vLLM
# Qwen3 box, then the llama.cpp Qwen3.5-abliterated box. resolve_backend()
# probes these and uses the first one that's live, so the judge keeps working
# when one server is down. Override the whole list with WAVEFRONT_LLM_BACKENDS
# (comma-separated). NOTE: backends score on DIFFERENT scales — every record
# stamps judge_backend, and guard_tick.sh keys its thresholds off it.
KNOWN_BACKENDS = [
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
DEFAULT_REF = REPO / "examples" / "contour_woman_post1.jpeg"
ANCHOR_HIGH = REPO / "loop" / "output" / "iter_014.png"  # humans rate 95
ANCHOR_LOW_DESC = (
    "ANCHOR_15 (not shown): a previous candidate that was nearly blank "
    "with sparse Lissajous-like noise, no face visible — humans rated 15."
)


PROMPT = """You are evaluating WAVEFRONT, a topographic-contour portrait engine.

You will see THREE images:
  1. REFERENCE — the artist's valid plotted output (photo of paper with ink). Different density variants are all valid; ignore color/paper.
  2. ANCHOR_95 — a previous engine output humans rated 95/100. This is what "good" looks like as a digital render.
  3. CANDIDATE — the engine output you are scoring.

Calibrate your 0–100 score to these reference points:
  - ANCHOR_95 means: clear contour-line portrait, concentric diamond/ring
    structure clearly emanating from a center point, eyes/nose/mouth
    visible as ridges in the contour pattern, no smudging.
  - ANCHOR_15 (not shown but for scale): nearly blank, abstract noise,
    no recognizable face, no diamond rings — score around 15.
  - REFERENCE represents the gold-standard style on paper.

CRITICAL FAILURE MODES — cap at ≤50 regardless of other features:
  - face appears as a dark SMUDGY BLOB instead of distinct lines
  - over-dense central area OBSCURES facial features
  - solid black regions where there should be linework
  - the diamond/ring structure is missing or buried

Sweet spots — earn ≥85 only if:
  - CANDIDATE matches or exceeds ANCHOR_95's clarity
  - clean linework, no smudging
  - diamond/ring structure clearly emanates from a center point
  - eyes, nose, mouth visible as ridges

Reply with ONLY one JSON object on a single line:
{"score": <int 0-100>, "notes": "<one short sentence>", "vs_95": "<better|same|worse>"}"""


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


def parse(reply: dict) -> dict:
    msg = reply["choices"][0]["message"]
    text = msg.get("content") or msg.get("reasoning") or ""
    result = {"score": -1, "notes": "", "vs_95": "?"}
    for blob in re.findall(r"\{[^{}]*\"score\"[^{}]*\}", text, re.DOTALL):
        try:
            d = json.loads(blob)
            s = int(d.get("score", -1))
            if 0 <= s <= 100:
                result["score"] = s
                result["notes"] = str(d.get("notes", "")).strip()
                result["vs_95"] = str(d.get("vs_95", "?")).strip()
                return result
        except (json.JSONDecodeError, ValueError):
            continue
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
                   help="number of independent judge calls; the reported "
                        "judge_score is the median (de-noises outlier reads). "
                        "N=1 uses temperature 0 (deterministic); N>1 draws at "
                        "a small temperature so the samples actually vary.")
    args = p.parse_args()

    for path, name in [(args.output, "output"),
                       (args.reference, "reference"),
                       (ANCHOR_HIGH, "anchor_high")]:
        if not path.exists():
            sys.stderr.write(f"judge.py: missing {name} {path}\n"); return 2

    content: list[dict] = [{"type": "text", "text": PROMPT}]
    content += labeled("REFERENCE:", args.reference)
    content += labeled("ANCHOR_95 (humans rated 95):", ANCHOR_HIGH)
    content += labeled("CANDIDATE — score this:", args.output)

    n = max(1, args.samples)
    # Single sample stays deterministic (temp 0) for backward compat; with
    # multiple samples we need genuine variation to de-noise, so draw warm.
    temperature = 0.0 if n == 1 else 0.5

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
            "vs_anchor_high": "?", "model": LLM_MODEL, "judge_backend": backend,
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
        "vs_anchor_high": rep["vs_95"],
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
