You compare a CANDIDATE contour render to the artist REFERENCE and rate ONLY how
well the candidate REPLICATES the reference's SPECIFIC look. BE HARSH — most
current attempts are far off, and saying so is the point. Judge against whatever
the reference actually shows (it may be a face in concentric diamonds, a helmet in
flowing waves, etc.) — do not assume a particular pattern.

Two images:
  REFERENCE — the artist's target output (the exact look to replicate).
  CANDIDATE — score this one.

Rate two dimensions (0–10 each) and one gate:

- structure_match (0–10): does the CANDIDATE show the SAME contour-line STRUCTURE as
  the reference — the same kind of pattern (concentric diamonds vs flowing waves vs
  …), the same flow/direction, and the same density distribution (dense where the
  reference is dense, sparse where it's sparse)? 10 = identical structure, 5 = right
  family but distorted, 0 = unrelated structure.

- resemblance (0–10): could this pass as the SAME artist output for THIS image
  (composition, line density, line quality)? 10 = indistinguishable, 5 = clearly
  related but off, 0 = unrelated.

- subject (true/false): is the reference's main SUBJECT (whatever it is — a face, a
  helmet, an object) actually recognizable in the candidate's contour lines? false
  if the subject is lost in an abstract pattern.

A genuine artist output scores 8–10 on both dimensions. Most current attempts are
weak: typical structure_match 2–5, resemblance 2–5. Reserve 8+ for near-perfect
replication of the reference.

Reply with ONLY one JSON object on one line, nothing else:
{"structure_match": <0-10>, "resemblance": <0-10>, "subject": <true|false>, "biggest_gap": "<the single most important change to look more like the reference>", "notes": "<=12 words>"}
