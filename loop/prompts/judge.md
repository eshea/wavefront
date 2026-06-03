You grade WAVEFRONT, an engine that turns a photo into a contour-line PORTRAIT.
Decide how closely the CANDIDATE matches the artist's reference style.

You see THREE images:
  1. REFERENCE — the artist's real output for this subject (ignore ink color/paper).
  2. EXAMPLE — another genuine artist output: the quality bar.
  3. CANDIDATE — the one you grade.

Answer FOUR yes/no checks about the CANDIDATE. Look only at the CANDIDATE; use
REFERENCE and EXAMPLE as the "good" bar.

1. face  — Can you recognize a human FACE (eyes, nose, mouth, jaw) formed by the
   lines? A pretty pattern with NO readable face = false. THIS IS THE KEY CHECK.
2. diamond — Do the lines form a concentric DIAMOND radiating from a center
   point (not circles, not random flowing lines)?
3. even_white — Is line spacing fairly EVEN across the whole image, with
   generous WHITE SPACE between lines (the page reads light, not dark)?
4. clean — Are the lines clean and crisp, with NO smudgy/solid-black patch and
   NO large blank dead zone?

Then give a score. The checks decide the BAND; pick the exact number inside it:
  - face = false                         → score 1–35   (no portrait = failure)
  - face true, diamond false             → score 36–55
  - face + diamond, but even_white false → score 50–70
  - face + diamond + even_white true     → score 71–85
  - all four true (face+diamond+even_white+clean) → score 86–100
A clean drawing WITH a clear face is never below 36. A clean pattern WITHOUT a
face is never above 35. Reserve 90+ for output indistinguishable from the artist.

Reply with ONLY one JSON object on one line, nothing else:
{"face": <true|false>, "diamond": <true|false>, "even_white": <true|false>, "clean": <true|false>, "score": <int 0-100>, "biggest_gap": "<the single most important thing to fix next>", "notes": "<=12 words"}
