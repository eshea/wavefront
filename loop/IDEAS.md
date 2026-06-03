# WAVEFRONT wave-field knob menu (pick ONE per tick)

Canonical render is `method=wave` (`build_wave_field` in `engine/field.py`),
centered seed, levels 90, lum_mix 0.8. Target = the artist's actual CONTOUR-V
output for the astronaut-helmet input: `examples/contour_space_pre.jpg` →
`examples/contour_space_post.webp` (a clean, matched pair; flowing-wave look).
Judge = local Qwen (harsh reference-replication rubric).

**How to use this each tick:** read the latest `judge_gap` (the judge's single
biggest difference from the reference), find the ONE matching symptom below, and
make that one bounded move. Don't nudge the same knob twice in a row — if the
last 2 ticks touched a knob and the score didn't move, pick a different symptom.

## The menu — symptom → knob move (current value → try)

| If the gap / symptom is… | Change (engine/field.py) | Current → try |
|---|---|---|
| Background too busy / dense texture in hair/bg | `WAVE_SIGMA_BG` up | 30.0 → 40.0 |
| Background still busy after SIGMA_BG | `WAVE_FAR` down | 0.20 → 0.12 |
| Face looks flat / no relief, too plain | `WAVE_RELIEF` up | 0.45 → 0.60 |
| Whole image too ripply / not diamond enough | `WAVE_DIAMOND` up | 0.0 → 0.20 |
| Features blurred / lost near the seed | `WAVE_SIGMA_FACE` down | 8.0 → 6.0 |
| Face zone too small (relief stops too soon) | `WAVE_INNER` / `WAVE_OUTER` up | 0.20 / 0.42 → 0.25 / 0.50 |
| Line spacing uneven (too dense near seed) | `THRESHOLD_POWER` toward 1.0 (engine/contour.py) | 1.3 → 1.0 |

Keep moves small (one step in the suggested direction). If a move helped, the
guard keeps it; next tick you can step it again OR address the next gap.

## Notes / breadth (lower priority)
- If several knob moves stall, a bounded formula tweak inside `build_wave_field`
  is allowed (e.g. clamp the relief term to a percentile so a few black pixels
  don't blow it up) — but still as ONE small copy-verbatim SEARCH/REPLACE edit.
- Add a new line-spacing-evenness metric/test (engine + loop/score.py) if the
  judge keeps citing uneven density — measurable signal beats guessing.
- Mark tried ideas with their result here (✅ better / ➖ same / ❌ worse + score).
