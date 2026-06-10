#!/usr/bin/env python3
"""
loop/montage.py — assemble ONE legible comparison image for the loop agent.

Why: each tick the agent otherwise has to issue three separate Read calls (source,
its output, the artist reference) and diff them in its head. Per the harness-
engineering principle "make the artifact legible to the agent", we compose a single
captioned montage it Reads at a STABLE path, with the live metrics drawn on:

    [ source | current output | best-so-far | artist target ]

Output: loop/output/_latest_compare.png  (overwritten every tick).

Inputs are discovered, not required — any missing panel renders as a labelled
placeholder so this NEVER blocks a tick. Call it after render.py succeeds.

Usage:
    python loop/montage.py <iter_number>
"""
import sys
import json
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "loop" / "output"
METRICS = REPO / "loop" / "metrics.jsonl"
REFERENCE = REPO / "examples" / "woman" / "woman-sample-output-2.jpeg"

PANEL_H = 380          # each panel resized to this height (aspect preserved)
CAPTION_H = 26         # caption bar under each panel
STRIP_H = 40           # full-width metrics strip on top
PAD = 12               # gutter between panels / around edges
BG = (250, 250, 250)
FG = (24, 24, 24)
MUTED = (120, 120, 120)


def _font(size):
    """A truetype font if one is findable, else PIL's bitmap default."""
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _metrics_for(iter_num):
    """Latest metrics record for iter_num (fall back to the last line)."""
    if not METRICS.exists():
        return {}
    rows = []
    for line in METRICS.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not rows:
        return {}
    cur = next((r for r in reversed(rows) if r.get("iter") == iter_num), None)
    return cur or rows[-1]


def _load_panel(path):
    """Resize an image to PANEL_H preserving aspect; None if unreadable."""
    try:
        im = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        return None
    w = max(1, round(im.width * PANEL_H / im.height))
    return im.resize((w, PANEL_H), Image.LANCZOS)


def _placeholder(label):
    """A neutral panel standing in for a missing input."""
    im = Image.new("RGB", (round(PANEL_H * 0.72), PANEL_H), (230, 230, 230))
    d = ImageDraw.Draw(im)
    d.text((im.width // 2, PANEL_H // 2), "(none)", fill=MUTED,
           font=_font(18), anchor="mm")
    return im


def build(iter_num, out_path=OUT_DIR / "_latest_compare.png"):
    iter_pad = f"{int(iter_num):03d}"
    m = _metrics_for(int(iter_num))

    # Source the tick actually rendered (recorded by render.py in stats.json).
    stats_path = OUT_DIR / f"iter_{iter_pad}.stats.json"
    src = None
    if stats_path.exists():
        try:
            src = json.loads(stats_path.read_text()).get("source")
        except (OSError, ValueError):
            src = None

    best_json = OUT_DIR / "_best.json"
    best_iter = None
    if best_json.exists():
        try:
            best_iter = json.loads(best_json.read_text()).get("iter")
        except (OSError, ValueError):
            best_iter = None
    best_cap = f"best d_fine (iter {best_iter:03d})" if isinstance(best_iter, int) \
        else "best d_fine"

    panels = [
        ("source", src),
        (f"current · iter {iter_pad}", OUT_DIR / f"iter_{iter_pad}.png"),
        (best_cap, OUT_DIR / "_best.png"),
        ("artist target", REFERENCE),
    ]

    imgs, caps = [], []
    for cap, path in panels:
        im = _load_panel(path) if path else None
        imgs.append(im or _placeholder(cap))
        caps.append(cap)

    total_w = sum(im.width for im in imgs) + PAD * (len(imgs) + 1)
    total_h = STRIP_H + PAD + PANEL_H + CAPTION_H + PAD
    canvas = Image.new("RGB", (total_w, total_h), BG)
    draw = ImageDraw.Draw(canvas)

    # Top metrics strip — the live numbers the agent steers by.
    def g(k, fmt="{}"):
        v = m.get(k)
        return fmt.format(v) if isinstance(v, (int, float)) else "?"
    strip = (f"iter {m.get('iter','?')}   "
             f"d_score={g('d_score')}   d_fine={g('d_fine','{:.3f}')}   "
             f"d_fidelity={g('d_fidelity','{:.3f}')}   d_diag={g('d_diag','{:.3f}')}   "
             f"d_ink={g('d_ink','{:.3f}')}")
    draw.text((PAD, STRIP_H // 2), strip, fill=FG, font=_font(20), anchor="lm")

    x = PAD
    y = STRIP_H + PAD
    for im, cap in zip(imgs, caps):
        canvas.paste(im, (x, y))
        draw.text((x + im.width // 2, y + PANEL_H + CAPTION_H // 2),
                  cap, fill=FG, font=_font(15), anchor="mm")
        x += im.width + PAD

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("iter", help="iteration number")
    p.add_argument("--out", type=Path, default=OUT_DIR / "_latest_compare.png")
    a = p.parse_args()
    try:
        out = build(a.iter, a.out)
    except Exception as e:  # montage is best-effort: never break a tick
        sys.stderr.write(f"[montage] skipped: {e}\n")
        return 0
    print(f"[montage] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
