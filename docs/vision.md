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
- **Dense where it should be, but controlled** — deep darks saturate to solid
  ink (eyes, visors) while midtones stay a gentle halftone; never a smudgy blob
  across whole shadow regions (the artist's own stated failure mode; see
  `contour-v-core-source.md`).
- **Plotter-ready SVG** sized to the original image — constant ink stroke by
  default (a plotter has one pen), adaptive stroke weight opt-in.

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
- **Mural / large-format output (extension beyond CORE).** Opt-in features for
  producing big physical wall pieces from one photo: a **wide canvas** that pads
  the subject into a chosen aspect (e.g. 7ft×3.5ft ≈ 2:1) and lets the diamond
  field fill the margins; **multi-pen color separations** (duotone by darkness, or
  a depth/elevation color ramp — exported as Inkscape pen layers for plotters);
  and **print-ready export** (physical units stamped on the SVG, raised processing
  detail for large sources). All default off — CORE renders single black ink at
  source aspect unchanged. See `algorithm.md` → "Mural extensions". Production
  paths (large-format print shop vs wall-drawing robot vs projection) are a
  separate, non-code workflow choice.

## How we get there

A reverse-engineered fast-marching contour field — CONTOUR-V's own confirmed
model: a 4-connected arrival-time field with reciprocal brightness cost
(`algorithm.md`) — driven toward the reference by the **ralph loop** (`loop/`):
an autonomous iterate-render-score-document cycle that tunes one engine knob at
a time against the `examples/` targets, with a held-out set to guard against
overfitting.
