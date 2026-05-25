#!/usr/bin/env python3
"""
loop/judge.py — visual judge using a local vision LLM.

Posts a reference image and a candidate output image to the local vLLM
server (Qwen3 122B at 192.168.50.135:8000) and asks it to rate how well
the output matches the reference's style as a contour-line portrait.

Emits one JSON line to stdout:
    {"output": "...", "reference": "...", "judge_score": 0..100,
     "judge_notes": "...", "model": "qwen", "elapsed_s": 12.3}

CLI:
    python loop/judge.py --output PATH --reference PATH [--iter N]

The judge prompt scores three axes (recognizability, line style,
overall composition) and returns one composite 0–100 number plus a
short note. Temperature=0 for run-to-run consistency.
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import urllib.request
from PIL import Image


LLM_BASE = os.environ.get("WAVEFRONT_LLM", "http://192.168.50.135:8000")
LLM_MODEL = os.environ.get("WAVEFRONT_LLM_MODEL", "qwen")
MAX_SIDE = 512  # downscale images before sending — keeps prompt cheap


PROMPT = """You are evaluating WAVEFRONT, a topographic-contour portrait engine.

You see two images:
  1. REFERENCE — the artist's known-good plotted output (photo of paper with ink)
  2. CANDIDATE — the engine's rendered output

Rate the CANDIDATE on a scale 0–100 for how well it matches the REFERENCE's STYLE as a contour-line portrait of the same subject. Be generous about color and texture differences (reference is photographed orange ink on paper; candidate is black-on-white digital). Focus on:

- Is the CANDIDATE recognizably a contour-line portrait of a face? (most important)
- Does it have concentric diamond/ring structure emanating from a center?
- Does line density / density distribution roughly match the reference?
- Are facial features (eyes, nose, mouth) discernible in the contour pattern?

Scoring guide:
  0–20  = blank, crashed, abstract noise, or unrecognizable as a portrait
  21–40 = some contour structure but face is not discernible
  41–60 = face shape visible but density/style is off
  61–80 = clear portrait, ring structure present, reasonable match
  81–100 = strong match — face clear, rings present, density similar to reference

Reply with ONLY a JSON object on a single line, no other text:
{"score": <int 0-100>, "notes": "<one short sentence>"}"""


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
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}"


def call_llm(ref_url: str, cand_url: str, *, timeout: int = 120) -> dict:
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "text", "text": "REFERENCE:"},
                    {"type": "image_url", "image_url": {"url": ref_url}},
                    {"type": "text", "text": "CANDIDATE:"},
                    {"type": "image_url", "image_url": {"url": cand_url}},
                ],
            }
        ],
        "max_tokens": 600,
        "temperature": 0,
        # Try to suppress Qwen3's thinking mode so we get content not reasoning.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        f"{LLM_BASE}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def parse_score(reply: dict) -> tuple[int, str]:
    """Extract score+notes from the model's reply. Falls back to regex if
    the model returned reasoning instead of clean JSON."""
    msg = reply["choices"][0]["message"]
    text = msg.get("content") or msg.get("reasoning") or ""

    # Direct JSON object first
    for blob in re.findall(r"\{[^{}]*\"score\"[^{}]*\}", text, re.DOTALL):
        try:
            d = json.loads(blob)
            score = int(d.get("score", -1))
            notes = str(d.get("notes", "")).strip()
            if 0 <= score <= 100:
                return score, notes
        except (json.JSONDecodeError, ValueError):
            continue

    # Fallback: find any number 0..100 near "score" keyword
    m = re.search(r"score[^0-9-]{0,12}([0-9]{1,3})", text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 100:
            return n, (text[:120].strip() or "(score parsed without JSON)")

    return -1, f"(parse-failed) {text[:200]}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--reference", required=True, type=Path)
    p.add_argument("--iter", type=int, default=None)
    args = p.parse_args()

    if not args.output.exists():
        sys.stderr.write(f"judge.py: missing {args.output}\n"); return 2
    if not args.reference.exists():
        sys.stderr.write(f"judge.py: missing {args.reference}\n"); return 2

    ref_url = img_to_data_url(args.reference)
    cand_url = img_to_data_url(args.output)

    t0 = time.monotonic()
    try:
        reply = call_llm(ref_url, cand_url)
    except Exception as e:
        sys.stderr.write(f"judge.py: LLM call failed: {e}\n")
        print(json.dumps({
            "output": str(args.output), "reference": str(args.reference),
            "judge_score": -1, "judge_notes": f"call-failed: {e}",
            "model": LLM_MODEL, "elapsed_s": round(time.monotonic() - t0, 1),
        }))
        return 1

    score, notes = parse_score(reply)
    elapsed = round(time.monotonic() - t0, 1)

    rec = {
        "iter": args.iter,
        "output": str(args.output),
        "reference": str(args.reference),
        "judge_score": score,
        "judge_notes": notes,
        "model": LLM_MODEL,
        "elapsed_s": elapsed,
    }
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
