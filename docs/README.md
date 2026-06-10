# WAVEFRONT docs

Documentation set for WAVEFRONT, a topographic contour portrait engine that
replicates CONTOUR-V CORE. **Keep these in sync with the code** — when engine
behavior, the field formula, tuning knobs, or the pipeline change, update the
relevant doc in the same change.

| Doc | What it covers |
|---|---|
| [vision.md](vision.md) | What WAVEFRONT is, why it exists, what "good" means, scope (CORE parity → STUDIO roadmap) |
| [tech.md](tech.md) | Stack, request flow, architecture, key design points, ops notes |
| [algorithm.md](algorithm.md) | The current `method=march` pipeline (fast marching, reciprocal cost), step by step (the authoritative algorithm reference) |
| [contour-v-core-source.md](contour-v-core-source.md) | The replication target — verified first-party facts (Ko-fi product copy, demo video, Reddit, the STUDIO screenshot decode). Read before changing the field. |
| [research.md](research.md) | Early research notes on the VEX-LINE aesthetic and field derivation (partly superseded — see header) |
| [vex-engine-reverse-engineering.md](vex-engine-reverse-engineering.md) | Working log: UI/HUD reverse-engineering and formula derivation (partly superseded — see header) |

Project-level guidance for working in this repo lives in the root
[`CLAUDE.md`](../CLAUDE.md). The ralph tuning loop has its own
[`loop/README.md`](../loop/README.md).
