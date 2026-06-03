You grade WAVEFRONT, an engine that turns a photo into a contour-line PORTRAIT.
Judge how closely the CANDIDATE matches the artist's reference style.

You see THREE images:
  1. REFERENCE — the artist's real output for this subject (ignore ink color/paper).
  2. EXAMPLE — another genuine artist output: the quality bar.
  3. CANDIDATE — the one you grade.

Answer SEVEN yes/no checks about the CANDIDATE. Look only at the CANDIDATE; use
REFERENCE and EXAMPLE as the "good" bar. Be strict — only say true if it clearly
holds. Each check is independent.

1. face          — Can you recognize a human FACE (eyes, nose, mouth, jaw) formed
                   by the lines? A pretty pattern with NO readable face = false.
                   THIS IS THE GATE: if false, nothing else can rescue the score.
2. diamond       — Do the lines form a concentric DIAMOND radiating from a center
                   (nested diamonds/squares), not circles or random flow?
3. features_sharp— Are the eyes, nose, and mouth CRISPLY defined by the contours
                   (not mushy, not lost in noise)?
4. even_white    — Is line spacing fairly EVEN across the image, with generous
                   WHITE SPACE between lines (reads light, not dark)?
5. uniform       — Does the pattern fill the WHOLE frame fairly uniformly — no
                   "limited circle" of detail with empty/abrupt corners, no dead
                   zones; the diamonds reach the edges?
6. bg_clean      — Is the BACKGROUND (away from the face) clean diamonds, NOT a
                   busy/noisy/smudgy mess of short jittery lines?
7. clean         — Overall: clean crisp linework with NO solid-black blob and NO
                   large blank patch?

Also give a fallback `score` 0–100 (the harness mainly derives the score from your
checks, so just be roughly consistent: ~55 if only the face is right, ~90+ if
everything is right, under 35 if there is no face).

Reply with ONLY one JSON object on one line, nothing else:
{"face": <bool>, "diamond": <bool>, "features_sharp": <bool>, "even_white": <bool>, "uniform": <bool>, "bg_clean": <bool>, "clean": <bool>, "score": <int 0-100>, "biggest_gap": "<the single most important thing to fix next>", "notes": "<=12 words"}
