#!/usr/bin/env python3
"""
loop/proposer.py — the CONSTRAINED-PROPOSER driver for one ralph tick.

Lesson from the free-agent driver: a weaker local model, given a free agentic
loop, over-works (edits many files, self-scores, never stops). So here the
HARNESS drives and the model does the one thing it's reliable at: propose ONE
edit. Per tick we:
  1. render the CURRENT code so the model sees the real output,
  2. give the model context (recent d_score: fidelity+style, IDEAS, the editable
     files) + the current render + the reference image,
  3. get ONE edit (HYPOTHESIS/CATEGORY/FILE/SEARCH/REPLACE) — retrying only to
     get a VALID applicable edit (max 3 calls), never to "keep going",
  4. apply it and render again (the version score_tick will grade),
  5. append a hypothesis entry to EXPERIMENT_LOG.md and exit.

ralph.sh then runs score_tick (the single official score) + guard (keep/revert).
"""
import os
import re
import io
import sys
import json
import base64
import subprocess
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompts  # noqa: E402

LLM_BASE = os.environ.get("WAVEFRONT_LLM", "http://neuromancer:8000").rstrip("/")
MODEL = os.environ.get("WAVEFRONT_LLM_MODEL", "qwen")
REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "examples" / "woman" / "woman-sample-output-2.jpeg"   # matched target for the woman-source input
EDITABLE = ["engine/march.py"]   # the tuning surface shown (the active method=march)
MAX_ATTEMPTS = 3


def sh(cmd, timeout=420):
    return subprocess.run(cmd, shell=True, cwd=str(REPO), capture_output=True,
                          text=True, timeout=timeout)


def img_data_url(path, max_side=768):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        im = im.resize((int(w*s), int(h*s)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def recent_metrics(n=6):
    p = REPO / "loop" / "metrics.jsonl"
    if not p.exists():
        return "（none yet）"
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    out = []
    for r in rows[-n:]:
        out.append(f"iter {r.get('iter')}: d_score={r.get('d_score')} "
                   f"fid={r.get('d_fidelity')} style={r.get('d_style')}")
    return "\n".join(out) or "（none yet）"


ACTIVE_NOTE = """# ACTIVE SURFACE — what actually affects the scored render
The canonical render uses **method=march** (engine/march.py build_march_field — a
4-connected FAST-MARCHING field with RECIPROCAL cost, the confirmed CONTOUR-V
model: speed = clip(gray, MARCH_FLOOR, 1), cost = MARCH_BASE + lum_mix*(1/speed-1)
+ MARCH_EDGE*edge. Isoline spacing = level spacing / cost, so whites stay open,
mids compress gently, and deep darks saturate to SOLID ink — tone-driven density
that actually RENDERS the image's tones — while 4-connectivity keeps L1 diamonds).
ONLY these module constants in engine/march.py change the output:
  - MARCH_FLOOR     speed floor (THE tone lever). LOWER => deep darks cost up to
                    1/FLOOR => solid-ink shadows => higher d_tone/d_fine.
  - MARCH_EDGE      edge magnitude -> extra cost. Usually unnecessary — tonal
                    pileup falls out of the reciprocal. Lowers d_diag (more warp).
  - MARCH_BASE      flat per-step cost = diamond dominance. LOW => image warps
                    the diamonds organically (d_diag in band); HIGH => stiff
                    diamonds (d_diag above band, the diamond factor penalises it).
  - MARCH_CONTRAST / MARCH_GAMMA  tonal pre-shaping of the gray (contrast about mid,
                    then gamma) before the cost — shapes which tones drive density.
  - MARCH_BLUR      denoise sigma (tames busy source texture).
  - the render passes levels=111, lum_mix=0.8 (111 = CONTOUR-V CORE's CONTOURS density;
    lum_mix scales the tone term). Watch d_ink: if shadows go solid black (d_ink>0.85)
    the gate zeroes the score — raise MARCH_FLOOR or raise MARCH_CONTRAST.
IGNORE the WAVE_*/FLOW_*/FIELD_* constants and build_wave_field/trace_flow_lines —
those are PARKED methods, NOT rendered now. Tune ONE MARCH_* value per tick by
editing engine/march_params.json (the externalized config that overrides the
march.py defaults), or run loop/optimize.py to sweep all 6 at once."""


def build_user_text():
    parts = [ACTIVE_NOTE, "",
             "# Recent results (d_score: fidelity + style)", recent_metrics(), ""]
    parts += ["# Idea backlog (loop/IDEAS.md)",
              (REPO / "loop" / "IDEAS.md").read_text(), ""]
    parts += ["# Editable files (copy SEARCH text VERBATIM from here)"]
    for rel in EDITABLE:
        parts.append(f"\n----- {rel} -----")
        parts.append((REPO / rel).read_text())
    parts += ["",
              "Propose ONE change now, in the exact HYPOTHESIS/CATEGORY/FILE/"
              "SEARCH/REPLACE format. The CANDIDATE render and the REFERENCE "
              "are attached."]
    return "\n".join(parts)


def call_llm(messages, timeout=300):
    payload = {"model": MODEL, "messages": messages, "temperature": 0.45,
               "max_tokens": 1500, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"{LLM_BASE}/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"].get("content") or ""


def _block(label, text):
    m = re.search(label + r":\s*```[a-zA-Z0-9_]*\n(.*?)\n```", text, re.DOTALL)
    return m.group(1) if m else None


def parse_proposal(text):
    fn = re.search(r"FILE:\s*(\S+)", text)
    search, replace = _block("SEARCH", text), _block("REPLACE", text)
    if not (fn and search is not None and replace is not None):
        return None
    hyp = re.search(r"HYPOTHESIS:\s*(.+)", text)
    cat = re.search(r"CATEGORY:\s*(\w+)", text)
    return {"file": fn.group(1).strip(), "search": search, "replace": replace,
            "hypothesis": (hyp.group(1).strip() if hyp else "(none)"),
            "category": (cat.group(1).strip() if cat else "?")}


def apply_edit(p):
    path = REPO / p["file"]
    if p["search"].strip() == "(new file)":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(p["replace"]); return None
    if not path.exists():
        return f"file not found: {p['file']}"
    txt = path.read_text()
    if p["search"] not in txt:
        return f"SEARCH block not found in {p['file']} (copy it verbatim)"
    path.write_text(txt.replace(p["search"], p["replace"], 1))
    return None


def log_entry(it, p):
    line1 = (p["replace"].strip().splitlines() or [""])[0][:80]
    entry = (f"\n## Iter {it} · proposer · {p['hypothesis']}\n"
             f"- category: {p['category']} · file: `{p['file']}`\n"
             f"- change → `{line1}`\n")
    with open(REPO / "loop" / "EXPERIMENT_LOG.md", "a") as f:
        f.write(entry)


def main():
    it = (REPO / "loop" / ".iter").read_text().strip()
    t0 = time.monotonic()

    # 1. Render current code so the model sees the true current output.
    sh(f'./loop/render_tick.sh "{it}"')
    cur_png = REPO / "loop" / "output" / f"iter_{int(it):03d}.png"

    user = [{"type": "text", "text": build_user_text()}]
    for label, path in [("REFERENCE (the target):", REFERENCE),
                        ("CANDIDATE (current render):", cur_png)]:
        if path.exists():
            user.append({"type": "text", "text": label})
            user.append({"type": "image_url", "image_url": {"url": img_data_url(path)}})

    messages = [{"role": "system", "content": prompts.load("proposer")},
                {"role": "user", "content": user}]

    applied = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            reply = call_llm(messages)
        except Exception as e:
            print(f"[proposer] LLM call failed: {e}", file=sys.stderr); break
        prop = parse_proposal(reply)
        if not prop:
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": "That was not in the required "
                          "HYPOTHESIS/CATEGORY/FILE/SEARCH/REPLACE format. Try again."}]
            print(f"[proposer] attempt {attempt}: unparseable", file=sys.stderr)
            continue
        err = apply_edit(prop)
        if err is None:
            applied = prop
            print(f"[proposer] attempt {attempt}: applied edit to {prop['file']} "
                  f"[{prop['category']}]", file=sys.stderr)
            break
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"Edit did not apply: {err}. "
                      "Re-copy the SEARCH block EXACTLY from the file shown."}]
        print(f"[proposer] attempt {attempt}: {err}", file=sys.stderr)

    if not applied:
        print(json.dumps({"driver": "proposer", "iter": it, "applied": False,
                          "elapsed_s": round(time.monotonic()-t0, 1),
                          "usage": {"input_tokens": 0, "output_tokens": 0}}))
        return 1

    # 4. Render the edited code (this is what score_tick will grade).
    r = sh(f'./loop/render_tick.sh "{it}"')
    if r.returncode != 0:
        print(f"[proposer] render after edit failed: {r.stderr[-300:]}", file=sys.stderr)
    # 5. Log the hypothesis (score is appended by ralph after score_tick).
    log_entry(it, applied)
    print(json.dumps({"driver": "proposer", "iter": it, "applied": True,
                      "file": applied["file"], "category": applied["category"],
                      "hypothesis": applied["hypothesis"],
                      "elapsed_s": round(time.monotonic()-t0, 1),
                      "usage": {"input_tokens": 0, "output_tokens": 0}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
