#!/usr/bin/env python3
"""
loop/distill.py — distill EXPERIMENT_LOG.md into a short, legible digest.

EXPERIMENT_LOG.md is an 800+-line flat log; the agent only ever sees the last few
entries, so hard-won "we already tried that and it didn't work" knowledge ages out
of context and gets re-attempted. Per the harness-engineering "entropy / garbage
collection" idea, this scans the structured `## Iter NNN` entries and emits
loop/EXPERIMENT_DIGEST.md grouped by outcome:

  ✅ what HELPED        (Result: better)
  ❌ what's RULED OUT   (Result: worse)
  🔁 open threads       (recent Next: hypotheses)

It's deterministic and cheap, so score_tick.sh regenerates it every tick.

Usage:
    python loop/distill.py
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "loop" / "EXPERIMENT_LOG.md"
DIGEST = REPO / "loop" / "EXPERIMENT_DIGEST.md"

HEADER_RE = re.compile(r"^##\s+Iter\s+(\d+)\b[^\n]*", re.MULTILINE)
HELPED_MAX = 14
RULED_OUT_MAX = 14
OPEN_MAX = 6


def _field(block, label):
    """First line's text after a bold **Label:** marker, trimmed."""
    m = re.search(rf"\*\*{label}:\*\*\s*(.+)", block)
    return m.group(1).strip() if m else ""


def _short(s, n=140):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _entries():
    if not LOG.exists():
        return []
    text = LOG.read_text()
    marks = list(HEADER_RE.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.start():end]
        header = m.group(0).lstrip("# ").strip()
        summary = header.split("·", 2)[-1].strip() if "·" in header else header
        out.append({
            "iter": int(m.group(1)),
            "summary": summary,
            "hypothesis": _field(block, "Hypothesis"),
            "result": _field(block, "Result"),
            "next": _field(block, "Next"),
        })
    return out


def _verdict(result):
    r = result.lower()
    if r.startswith("better") or " better" in r[:18]:
        return "helped"
    if r.startswith("worse") or " worse" in r[:18]:
        return "ruled_out"
    return "neutral"


def build():
    entries = _entries()
    helped, ruled = [], []
    for e in entries:
        v = _verdict(e["result"])
        line = f"- iter {e['iter']:03d} — {_short(e['summary'])}"
        if v == "helped":
            helped.append(line)
        elif v == "ruled_out":
            ruled.append(line)

    open_threads = [f"- iter {e['iter']:03d} → {_short(e['next'])}"
                    for e in entries if e["next"]
                    and e["next"].lower() not in ("review", "—", "-")][-OPEN_MAX:]

    parts = [
        "# Experiment digest",
        "",
        f"_Distilled from `loop/EXPERIMENT_LOG.md` ({len(entries)} entries) by "
        "`loop/distill.py`. Generated — do not edit; read the full log for detail._",
        "",
        f"## ✅ What helped (most recent {HELPED_MAX})",
        "",
        *(reversed(helped[-HELPED_MAX:]) if helped else ["- (none recorded yet)"]),
        "",
        f"## ❌ Ruled out — don't re-try without a new angle (most recent {RULED_OUT_MAX})",
        "",
        *(reversed(ruled[-RULED_OUT_MAX:]) if ruled else ["- (none recorded yet)"]),
        "",
        "## 🔁 Open threads (recent 'Next:' lines)",
        "",
        *(reversed(open_threads) if open_threads else ["- (none)"]),
        "",
    ]
    DIGEST.write_text("\n".join(str(p) for p in parts))
    return DIGEST


def main():
    try:
        out = build()
    except Exception as e:   # never break a tick
        sys.stderr.write(f"[distill] skipped: {e}\n")
        return 0
    print(f"[distill] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
