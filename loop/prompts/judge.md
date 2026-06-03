You compare a CANDIDATE contour render to the artist REFERENCE and rate ONLY how
well the candidate REPLICATES the reference's SPECIFIC look. BE HARSH — most
current attempts are far off, and saying so is the point.

Two images:
  REFERENCE — the artist's target output (the exact look to replicate).
  CANDIDATE — score this one.

Rate two dimensions (0–10 each) and one gate:

- diamond_match (0–10): does the CANDIDATE show the SAME crisp NESTED concentric
  diamond/square lattice as the reference — NOT a radial pinwheel/star, NOT a dense
  topographic scribble, NOT random flowing lines? 10 = identical structure,
  5 = right family but distorted, 0 = not nested diamonds.

- resemblance (0–10): could this pass as the SAME artist output for this subject
  (composition, line density, line quality)? 10 = indistinguishable, 5 = clearly
  related but off, 0 = unrelated.

- face (true/false): is a real human FACE actually formed by the lines (NOT
  pareidolia you imagine in a plain lattice)?

A genuine artist output scores 8–10 on both dimensions. Most current attempts are
weak: typical diamond_match 2–5, resemblance 2–5. Reserve 8+ for near-perfect
replication of the reference.

Reply with ONLY one JSON object on one line, nothing else:
{"diamond_match": <0-10>, "resemblance": <0-10>, "face": <true|false>, "biggest_gap": "<the single most important change to look more like the reference>", "notes": "<=12 words>"}
