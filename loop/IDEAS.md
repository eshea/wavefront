# WAVEFRONT wave-field knob menu (pick ONE per tick)

Canonical render is `method=wave` (`engine/field.py` `build_wave_field` — an
L1-Manhattan **diamond** field warped by a luminance **relief**), levels 111,
lum_mix 0.8, 780px raster. Target = the CONTOUR-V / **output-4** nested-diamond
aesthetic on `examples/space/space-source.jpg`. Score = deterministic `d_score`
(0–100, `loop/dscore.py`): source-fidelity + style + a **diamond factor** that
rewards the ±45° organic diamonds (`d_diag`≈0.53) and penalizes stiff/axis-aligned
lines. Canonical currently ~94.

**How to use this each tick:** read the latest metrics (`d_score`, `d_fidelity`,
`d_style`, `d_diag`, `d_ink`), find the ONE matching symptom below, make that one
bounded move. Don't nudge the same knob twice in a row — if the last 2 ticks
touched a knob and the score didn't move, pick a different symptom.

## The menu — symptom → knob move (current → try), all in engine/field.py

| If the symptom is… | Change | Current → try |
|---|---|---|
| Diamonds too STIFF/geometric (`d_diag`>0.6, moiré-ish) | `WAVE_RELIEF` up | 2.8 → 3.4 |
| Diamonds OVER-warped / broken up (`d_diag`<0.45) | `WAVE_RELIEF` down | 2.8 → 2.3 |
| Dark regions over-dense / muddy shadows (`d_ink` high) | `TONE_GAMMA` down (lifts shadows) | 1.0 → 0.6 |
| Subject washed out / not recognizable (`d_fidelity` low) | `TONE_CONTRAST` up, or `TONE_INVERT` 1 (portraits) | 1.0 → 1.4 / 0→1 |
| Background too busy / noisy texture | `WAVE_FAR` down, or `WAVE_SIGMA_BG` up | 0.35→0.2 / 30→40 |
| Face detail lost under blur | `WAVE_SIGMA_FACE` down | 8 → 5 |
| Relief fades too early/late (ring boundary visible) | `WAVE_OUTER` up / `WAVE_INNER` down | — |
| Output too dense / too sparse overall | `levels` (render param) down / up | 111 → 90 / 130 |
| Lines clump near seed vs spread evenly | `THRESHOLD_POWER` toward 1.0 (linear) | 1.3 → 1.0 |

Keep moves small (one step in the suggested direction). If a move helped, the
guard keeps it; next tick address the next gap.

## Notes / breadth (lower priority)
- `TONE_GAMMA / TONE_CONTRAST / TONE_INVERT` are the CONTOUR-V STUDIO tonal
  controls — they shape WHICH tones get contour density (identity at defaults).
  Gamma<1 is the proven shadow-cleanup lever (measured a face 85→98 at 0.6).
- A bounded formula tweak inside `build_wave_field` is allowed (e.g. how the
  relief fades, the blend of light/heavy blur) — but as ONE small copy-verbatim
  SEARCH/REPLACE edit.
- The parked methods (flow/contour/march) and their FLOW_*/FIELD_*/MARCH_*
  constants do NOT affect the wave render — don't edit them.
- Mark tried ideas with their result (✅ better / ➖ same / ❌ worse + score).
