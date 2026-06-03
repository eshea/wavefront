# WAVEFRONT — Vision

## What it is

WAVEFRONT turns any image into **topographic contour line art** — concentric,
luminance-warped diamonds suitable for pen plotters, CNC, and SVG workflows. It
is a faithful, open replication of **CONTOUR-V CORE** by plotter artist Robert T
Wilson (VEX-LINE), extended with a self-improving tuning loop.

## Why

The CONTOUR-V aesthetic — crisp concentric diamonds emanating from a seed point,
bending around facial features, dense where it should be but clean and
plotter-friendly — is distinctive and in demand among the plotter-art community.
CORE is a closed $9 standalone HTML tool. WAVEFRONT reproduces its output
quality from first principles (see `algorithm.md`) so the pipeline is
inspectable, tunable, and extensible.

## What "good" means

The reference outputs in `examples/` define the target. Concretely:
- **Crisp concentric diamonds** (Manhattan/L1 distance) that stay topologically
  intact and bend — not break into loops — around eyes/nose/mouth.
- **Even line spacing and clean white space**, consistent from the seed to the
  image edges. No artificial circular "zone."
- **Dense where it should be, but controlled** — never a smudgy blob in shadow
  regions (the artist's own stated failure mode; see `contour-v-core-source.md`).
- **Plotter-ready SVG** sized to the original image, with adaptive stroke weight.

## Scope: CORE parity, then STUDIO

- **CORE parity (current focus).** Two-slider UX — CONTOURS (density) + LINE
  SMOOTH (angular↔smooth) — plus click-to-place seed and center-seed. Import
  PNG/JPG/WEBP/SVG; export clean SVG, 2× PNG, copy SVG. This is the baseline we
  must hit.
- **STUDIO roadmap (next).** The paid CONTOUR-V STUDIO upgrade exposes the
  controls CORE hides — contrast shaping, gamma tuning, contour-behavior and
  advanced geometry controls, workflow tools. That feature list is WAVEFRONT's
  upgrade backlog. WAVEFRONT already exposes `lum_mix` and stroke-weight as
  sliders (CORE keeps these internal) as a first step in that direction.

## How we get there

A reverse-engineered L1-diamond ("wave") distance+luminance field (`algorithm.md`), driven
toward the reference by the **ralph loop** (`loop/`): an autonomous
iterate-render-score-document cycle that tunes one engine knob at a time against
the `examples/` targets, with a held-out set to guard against overfitting.
