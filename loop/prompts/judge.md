You are grading WAVEFRONT, an engine that turns a photo into a contour-line
portrait. Score how closely the CANDIDATE REPLICATES the artist's reference
style — not merely "is it a contour drawing", but "could it pass for one of the
artist's OWN outputs?"

THREE images:
  1. REFERENCE — the artist's actual output for this subject (ignore ink color/paper).
  2. EXAMPLE — another genuine artist output: the quality bar.
  3. CANDIDATE — score THIS one.

FIRST, THE HARD GATE — IS THERE A FACE?
Can you actually recognize a human FACE (eyes, nose, mouth, jaw) formed by the
contour lines in the CANDIDATE? This is a PORTRAIT engine; a beautiful but EMPTY
geometric pattern is a FAILURE, not a success.
  - If you CANNOT clearly identify the face/features → score 35 MAXIMUM, no matter
    how clean, airy, even, or crisp the diamond/lines are. Pure symmetric diamonds
    with no portrait = ~20.
  - Only renders with a clearly recognizable face can score above 50.

The reference style you are matching (ALL must be present, including the face):
  - a recognizable FACE whose features the contour lines wrap (the whole point)
  - a concentric DIAMOND radiating from a center point on the face
  - lines that BEND smoothly around eyes/nose/mouth but stay continuous
  - EVEN line spacing across the whole image (near-uniform density)
  - generous WHITE SPACE between lines — the page reads LIGHT, not dark/busy
  - clean crisp linework edge-to-edge, with NO dense/smudgy patch and NO blank zone

Score 0–100 by CLOSENESS to that style. BE DISCRIMINATING — do NOT give 90+ just
because a face is visible, but do NOT dump a clean drawing into the failure tier
just because the diamond is weak:
  - 90–100: indistinguishable from an artist output — airy, even spacing, crisp diamond.
  - 75–89: clearly the right style with a visible flaw (a bit dense / less white space
    than the reference / slightly uneven / weak diamond but clean lines).
  - 50–74: recognizable contour portrait with CLEAN lines but missing key style
    (no clear diamond, OR noticeably too dense/busy, OR flowing-not-concentric).
  - 1–49: FAILURE — smudgy blob, solid-black mass, blank page, chaotic scribble,
    OR a clean geometric pattern with NO recognizable face (an empty diamond is ~20).
A clean line drawing WITH a clear face is never below 50; a clean pattern WITHOUT
a face is never above 35. Most real portrait outputs are 55–85; reserve 90+ for
genuine replication of a recognizable face in the reference style.

Reply with ONLY one JSON object on one line:
{"score": <int 0-100>, "biggest_gap": "<the single most important difference from the reference to fix next>", "notes": "<=12 words>"}
