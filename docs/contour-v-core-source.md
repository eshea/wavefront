# CONTOUR-V CORE — Replication Target (authoritative source notes)

WAVEFRONT exists to replicate **CONTOUR-V CORE**, a commercial standalone
contour-generator by plotter artist **Robert T Wilson** (VEX-LINE). This file
records the verified, first-party facts about the target so we don't drift back
to guesses. For our derived formula and pipeline see `algorithm.md`; for the
slider/HUD reverse-engineering see `vex-engine-reverse-engineering.md`.

## Primary sources

| Source | What it is | URL |
|---|---|---|
| Ko-fi product page | Official product listing + feature copy | https://ko-fi.com/s/bab05e779e |
| YouTube demo | "Contour-V CORE : Image to SVG Product Demo" by Robert T Wilson (@RTWilsonStudios) | https://www.youtube.com/watch?v=uduMa-syiDs |
| Reddit (r/ClaudeAI) | Artist post: "Fixed a nasty JS loop issue in my contour app with Claude's help" | post id `t3_1snzkr6` |

Local archived copies of the Ko-fi page and the Reddit thread live in
`~/Downloads/` (saved HTML + assets). The tool's own source is **not** in those
archives — the Ko-fi page is the sales page, and the `.html` tool is gated
behind the $9 purchase. Everything below is from product copy, screenshots,
the demo, and behavioral observation, not from the tool's source.

## Product description (verbatim from the Ko-fi listing)

> **CONTOUR-V CORE — Standalone Contour Generator.** Minimal, fast, and focused.
> CONTOUR-V CORE is a lightweight version of the VEX Engine contour system —
> designed for quick image → contour workflows without a complex interface.

**What it does**
- Runs entirely in your browser (no install) — a single standalone HTML file
- Import PNG, JPG, WEBP, or SVG
- Click to place a seed point
- Adjust contour density
- Adjust smoothing (angular ↔ smooth)
- Export clean SVG · Export 2× PNG · Copy SVG code to clipboard

**Best for:** SVG workflows · pen plotting · CNC / Aspire prep · fast experimentation

**Included:** standalone HTML tool · quick-start guide · example files · license

**Pricing:** pay-what-you-want from $9; "24 sold" at time of capture.

## Upgrade path: CONTOUR-V STUDIO

CORE is positioned as the entry point. STUDIO (paid upgrade, discounted for CORE
owners) adds the controls CORE deliberately hides:
- contrast shaping
- gamma tuning
- contour behavior controls
- advanced geometry controls
- workflow tools

This maps directly onto WAVEFRONT's roadmap: we replicate **CORE** behavior, and
the **STUDIO** feature list is our upgrade backlog (see the project memory).

## The "JS loop" insight (Reddit, artist's own words)

This is the single most useful behavioral clue from the artist, and it directly
shaped our field design. Quoting the post:

> "The main one was a JS loop that caused parts of the contour render to be
> drawn **multiple times**. The result looked interesting, but some **shadow
> areas were far too busy**. After fixing it, the output is still dense where it
> should be, but **much cleaner and more controlled**. It also plots much better
> now with more consistent results."

Takeaways for WAVEFRONT:
- **Dark/shadow regions over-densify** is a known failure mode of this class of
  tool — exactly the smudgy-blob problem our `FIELD_SHADOW_LIFT` knob fights
  (raise the dark floor so heavy shadows/makeup don't pile contours into a blob).
- The target aesthetic is "**dense where it should be, but clean and
  controlled**" with **consistent, plotter-friendly** linework — not maximal
  density. Even line spacing and clean white space beat raw line count.
- The reference outputs were produced by the *fixed* version, so any duplicate /
  doubled contour artifact on our side is a regression, not a stylistic match.

## CORE's exposed surface (what we must match) vs. what it hides

CORE exposes only **two sliders** — CONTOURS (density) and LINE SMOOTH
(angular↔smooth) — plus click-to-place seed and a CENTER SEED button. It does
**not** expose `lum_mix` or stroke-weight controls; those are internal constants.
WAVEFRONT surfaces them as sliders, which is a deliberate extension beyond CORE
(toward STUDIO-style control). Treat the two-slider + seed UX as the CORE-parity
baseline; the extra knobs are bonus.
