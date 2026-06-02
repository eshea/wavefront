"""
loop/prompts.py — load prompts from markdown files in loop/prompts/.

Externalizing prompts to .md makes prompt-engineering easy: edit the file, no
code change. Reload behavior is controlled by WAVEFRONT_ENV:
  - dev (default): re-read from disk on EVERY call, so edits take effect live.
  - prod: cache after first read (no disk I/O per call).

    from loop.prompts import load
    rubric = load("judge")          # -> loop/prompts/judge.md
"""
import os
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "prompts"
_cache: dict[str, str] = {}


def _is_prod() -> bool:
    return os.environ.get("WAVEFRONT_ENV", "dev").strip().lower() == "prod"


def load(name: str) -> str:
    """Return the text of loop/prompts/<name>.md (dev reloads, prod caches)."""
    if _is_prod() and name in _cache:
        return _cache[name]
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    if _is_prod():
        _cache[name] = text
    return text
