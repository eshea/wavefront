#!/usr/bin/env python3
"""
loop/agent.py — a minimal local-LLM coding agent that drives ONE ralph tick
against a local vLLM (neuromancer Qwen3.5-122B), bypassing Claude Code.

Why this exists: Claude Code only executes Anthropic `tool_use` blocks, but the
vLLM emits tool calls as Qwen/Hermes-style TEXT (`<tool_call><function=...>`),
so routing claude -p through litellm does nothing. This agent talks to the vLLM
directly and parses that native format, executing bash/read/write/edit/view_image.

Per-tick contract (matches what ralph.sh expects from the old `claude -p`):
the agent reads loop/PROMPT.md, makes ONE change, renders via render_tick.sh,
logs to EXPERIMENT_LOG.md, then exits. ralph.sh scores + guards afterward.

Usage:
    python loop/agent.py            # run one tick
    python loop/agent.py --selftest # verify the tool loop on a trivial task
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

LLM_BASE = os.environ.get("WAVEFRONT_LLM", "http://neuromancer:8000").rstrip("/")
MODEL = os.environ.get("WAVEFRONT_LLM_MODEL", "qwen")
REPO = Path(__file__).resolve().parent.parent
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "30"))
MAX_OUT = 6000          # truncate tool output fed back to the model
BASH_TIMEOUT = 420

SYSTEM = """You are an autonomous coding agent improving the WAVEFRONT project
(a topographic-contour portrait engine). You do real work by calling tools.

Output tool calls in EXACTLY this format (one per message is safest):

<tool_call>
<function=bash>
<parameter=command>ls loop/</parameter>
</function>
</tool_call>

Available tools:
- bash       {command}            run a shell command in the repo root (stdout+stderr returned)
- read_file  {path}               print a text file
- write_file {path, content}      overwrite a file with content
- edit_file  {path, old, new}     replace the FIRST exact occurrence of `old` with `new`
- view_image {path}               SEE an image (your render or a reference) using your vision

After each tool call, STOP and wait — you'll get the result, then continue.
Make exactly ONE focused change this tick, then STOP. Workflow:
  1. read recent loop/EXPERIMENT_LOG.md + loop/IDEAS.md to pick an idea,
  2. make ONE change (edit_file), 3. render: `./loop/render_tick.sh "$(cat loop/.iter)"`,
  4. append ONE entry to loop/EXPERIMENT_LOG.md, 5. output <done>.

CRITICAL: after you append the EXPERIMENT_LOG entry, your VERY NEXT message
MUST be exactly `<done>summary</done>` and nothing else. Do NOT start a second
change, do NOT keep exploring. One change per tick.

<done>one-line summary of what you changed</done>

Do NOT output <done> until you have actually made a change AND rendered it."""


def _truncate(s, n=MAX_OUT):
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n...[truncated {len(s)-n} chars]"


# ---- tools -----------------------------------------------------------------
def t_bash(args):
    cmd = args.get("command", "")
    try:
        p = subprocess.run(cmd, shell=True, cwd=str(REPO), capture_output=True,
                           text=True, timeout=BASH_TIMEOUT)
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        return _truncate(out) or f"(exit {p.returncode}, no output)"
    except subprocess.TimeoutExpired:
        return f"[timeout after {BASH_TIMEOUT}s]"
    except Exception as e:
        return f"[bash error: {e}]"


def t_read_file(args):
    p = REPO / args.get("path", "")
    try:
        return _truncate(p.read_text())
    except Exception as e:
        return f"[read error: {e}]"


def t_write_file(args):
    p = REPO / args.get("path", "")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args.get("content", ""))
        return f"[wrote {p}]"
    except Exception as e:
        return f"[write error: {e}]"


def t_edit_file(args):
    p = REPO / args.get("path", "")
    old, new = args.get("old", ""), args.get("new", "")
    try:
        txt = p.read_text()
        if old not in txt:
            return "[edit error: `old` string not found]"
        p.write_text(txt.replace(old, new, 1))
        return f"[edited {p}]"
    except Exception as e:
        return f"[edit error: {e}]"


def t_view_image(args):
    """Returns a special marker; the caller turns it into an image message."""
    p = REPO / args.get("path", "")
    if not p.exists():
        return "[view error: file not found]"
    return {"__image__": str(p)}


TOOLS = {"bash": t_bash, "read_file": t_read_file, "write_file": t_write_file,
         "edit_file": t_edit_file, "view_image": t_view_image}


# ---- model I/O -------------------------------------------------------------
def img_data_url(path, max_side=768):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        im = im.resize((int(w*s), int(h*s)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def call_llm(messages, timeout=300):
    payload = {"model": MODEL, "messages": messages, "temperature": 0.3,
               "max_tokens": 2048, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"{LLM_BASE}/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"].get("content") or ""


_TC = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FN = re.compile(r"<function=([\w.]+)>")
_PM = re.compile(r"<parameter=([\w.]+)>(.*?)</parameter>", re.DOTALL)


def parse_tool_calls(text):
    """Parse Qwen/Hermes <tool_call> blocks; also tolerate a JSON variant."""
    calls = []
    for block in _TC.findall(text):
        fn = _FN.search(block)
        if fn:
            args = {k: v.strip() for k, v in _PM.findall(block)}
            calls.append((fn.group(1).strip().lower(), args))
            continue
        try:  # JSON fallback: {"name":..., "arguments":{...}}
            j = json.loads(block.strip())
            calls.append((str(j.get("name", "")).lower(),
                          j.get("arguments") or j.get("args") or {}))
        except Exception:
            pass
    return calls


def run_tick(task, log=sys.stderr):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    summary = None
    for turn in range(1, MAX_TURNS + 1):
        try:
            reply = call_llm(messages)
        except Exception as e:
            print(f"[agent] LLM call failed: {e}", file=log); break
        messages.append({"role": "assistant", "content": reply})

        done = re.search(r"<done>(.*?)</done>", reply, re.DOTALL)
        calls = parse_tool_calls(reply)
        print(f"[agent] turn {turn}: {len(calls)} tool call(s)"
              + (" + <done>" if done else ""), file=log)

        if done and not calls:
            summary = done.group(1).strip(); break
        if not calls:
            messages.append({"role": "user", "content":
                             "No tool call detected. If you've already made your "
                             "one change, rendered, and logged it, output exactly "
                             "<done>summary</done> NOW. Otherwise call a tool."})
            continue

        # Execute tool calls; collect text + any images for the next message.
        parts, images = [], []
        for name, args in calls:
            fn = TOOLS.get(name)
            if not fn:
                parts.append(f"[{name}] unknown tool"); continue
            res = fn(args)
            if isinstance(res, dict) and "__image__" in res:
                images.append(res["__image__"])
                parts.append(f"[view_image {args.get('path')}] (shown below)")
            else:
                parts.append(f"[{name}]\n{res}")
        content = [{"type": "text", "text": "\n\n".join(parts)}]
        for ip in images:
            try:
                content.append({"type": "image_url",
                                "image_url": {"url": img_data_url(ip)}})
            except Exception as e:
                content[0]["text"] += f"\n[image load failed: {e}]"
        messages.append({"role": "user", "content": content})
        if done:
            summary = done.group(1).strip(); break

    return summary, turn


def main():
    if "--selftest" in sys.argv:
        task = ("Self-test. Run `echo agent-ok` with bash, read its output, then "
                "output <done>selftest</done>.")
    else:
        task = (REPO / "loop" / "PROMPT.md").read_text()
        it = (REPO / "loop" / ".iter").read_text().strip()
        task += f"\n\n---\nThe current iteration number is {it}. Begin this tick now."

    t0 = time.monotonic()
    summary, turns = run_tick(task)
    # Emit a small JSON line so ralph.sh's usage parse doesn't choke.
    print(json.dumps({"driver": "agent", "model": MODEL, "turns": turns,
                      "summary": summary, "elapsed_s": round(time.monotonic()-t0, 1),
                      "usage": {"input_tokens": 0, "output_tokens": 0}}))
    return 0 if summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
