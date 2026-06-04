# WAVEFRONT flow-field knob menu (pick ONE per tick)

Canonical render is `method=flow` (`engine/flow.py` — evenly-spaced streamlines
that flow along the image), levels 90, lum_mix 0.8. Target = the artist's actual
CONTOUR-V output for the astronaut-helmet input: `examples/contour_space_pre.jpg`
→ `examples/contour_space_post.webp` (clean flowing waves, dense at the dark visor,
sparse in the bright sky). Judge = local Qwen (harsh reference-replication rubric:
structure_match + resemblance + subject gate; current attempts ~5–25, target ~90).

**How to use this each tick:** read the latest `judge_gap` (the judge's single
biggest difference from the reference), find the ONE matching symptom below, and
make that one bounded move. Don't nudge the same knob twice in a row — if the last
2 ticks touched a knob and the score didn't move, pick a different symptom.

## The menu — symptom → knob move (current value → try), all in engine/flow.py

| If the gap / symptom is… | Change | Current → try |
|---|---|---|
| Flat areas (sky) curl / lines wander | `FLOW_CARRIER` up | 0.6 → 0.8 |
| Waves run the wrong way vs the reference | `FLOW_ANGLE` | 20 → 0 (horizontal) or 45 |
| Carrier overrides the helmet detail (subject lost) | `FLOW_CARRIER` down, or `FLOW_CARRIER_MAG` down | 0.6→0.45 / 6.0→3.0 |
| Dark regions (visor) not dense enough | `FLOW_TONE_DENSITY` up | 0.6 → 0.8 |
| Output too busy / dense overall | `FLOW_TONE_DENSITY` down, or levels down | 0.6→0.45 |
| Lines short / choppy / curly everywhere | raise `sigma` default in `trace_flow_lines` | 3.0 → 5.0 |
| Overall too sparse / faint | levels up (render param) or `FLOW_TONE_DENSITY` up | — |

Keep moves small (one step in the suggested direction). If a move helped, the
guard keeps it; next tick address the next gap.

## Notes / breadth (lower priority)
- A bounded formula tweak inside `_tangent_field` / `trace_flow_lines` is allowed
  (e.g. blend the carrier differently, vary `min_len`) — but as ONE small
  copy-verbatim SEARCH/REPLACE edit.
- The parked methods (wave/contour/march) and their WAVE_*/FIELD_*/MARCH_*
  constants do NOT affect the flow render — don't edit them.
- Mark tried ideas with their result (✅ better / ➖ same / ❌ worse + score).
