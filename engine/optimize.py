"""Plotter output optimization (opt-in): merge, sort, and 2-opt path ordering.

A plotter draws each path with a pen-down stroke and travels pen-up between
paths. Marching-squares output is emitted in scan order, so consecutive paths
can be far apart — lots of wasted pen-up travel and pen lifts. These passes cut
that travel without changing the drawn geometry — CONTOUR-V STUDIO's
"CHAIN GAP / TSP-ORDER / 2-OPT" workflow tools.

  - merge_chains   join open paths whose endpoints are within a gap (fewer lifts)
  - reorder_nearest greedy nearest-neighbour visiting order (shorter pen-up)
  - two_opt        bounded 2-opt polish on that order (never increases travel)

(Point-budget *simplification* is a separate concern — `engine.smooth.
decimate_contours` / the `simplify_mm` param already provide RDP decimation.)

Everything is **layer-aware**: contours carrying different `layer` tags (multi-pen
color mode) are never merged or reordered across layers, so each pen's set stays
intact and is reassembled in its original layer order. `optimize_contours` is the
single entry point and returns the input list unchanged when every option is at
its off value (byte-stable default — proven by an identity unit test)."""

import numpy as np


def _path_length(points):
    if len(points) < 2:
        return 0.0
    d = np.diff(points, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def _is_closed(points, tol=1e-6):
    return len(points) > 2 and float(np.hypot(points[0, 0] - points[-1, 0],
                                              points[0, 1] - points[-1, 1])) <= tol


def _reversed(contour):
    """A copy of `contour` traversed end-to-start (same drawn line, reversed pen)."""
    out = dict(contour)
    out['points'] = contour['points'][::-1].copy()
    return out


def _dist(a, b):
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


def _layer_groups(contours):
    """Split into (layer -> [contours]) preserving first-seen layer order."""
    order, groups = [], {}
    for c in contours:
        L = c.get('layer', 0)
        if L not in groups:
            groups[L] = []
            order.append(L)
        groups[L].append(c)
    return order, groups


def _apply_per_layer(contours, fn):
    """Run `fn` on each layer group independently, reassembling in layer order."""
    order, groups = _layer_groups(contours)
    out = []
    for L in order:
        out.extend(fn(groups[L]))
    return out


def drop_short(contours, min_seg):
    """Drop paths whose total arclength is below `min_seg` (grid px). Off at <=0."""
    if min_seg <= 0:
        return contours
    return [c for c in contours if _path_length(c['points']) >= min_seg]


def _merge_layer(paths, gap):
    """Greedy endpoint chaining of the OPEN paths in one layer; closed loops pass
    through untouched. Joins a path onto the growing chain's tail whenever an
    endpoint lies within `gap`, flipping the joined path as needed."""
    closed = [c for c in paths if _is_closed(c['points'])]
    opens = [c for c in paths if not _is_closed(c['points'])]
    if gap <= 0 or len(opens) < 2:
        return paths
    cell = max(float(gap), 1e-3)
    g2 = float(gap) * float(gap)
    used = [False] * len(opens)

    buckets = {}
    def bkey(p):
        return (int(p[0] // cell), int(p[1] // cell))
    for i, c in enumerate(opens):
        pts = c['points']
        buckets.setdefault(bkey(pts[0]), []).append(i)
        buckets.setdefault(bkey(pts[-1]), []).append(i)

    def nearest(pt, skip):
        kx, ky = bkey(pt)
        best, bestd = None, g2
        for gx in (kx - 1, kx, kx + 1):
            for gy in (ky - 1, ky, ky + 1):
                for j in buckets.get((gx, gy), ()):
                    if used[j] or j == skip:
                        continue
                    for end in (0, -1):
                        dd = (pt[0] - opens[j]['points'][end][0]) ** 2 + \
                             (pt[1] - opens[j]['points'][end][1]) ** 2
                        # deterministic: strictly nearer, or equal with smaller (j,end)
                        if dd < bestd or (best is not None and dd == bestd
                                          and (j, end) < best):
                            bestd, best = dd, (j, end)
        return best

    merged = []
    for i in range(len(opens)):
        if used[i]:
            continue
        used[i] = True
        chain = opens[i]['points'].copy()
        while True:
            nb = nearest(chain[-1], i)
            if nb is None:
                break
            j, end = nb
            used[j] = True
            seg = opens[j]['points']
            chain = np.vstack([chain, seg[::-1] if end == -1 else seg])
        out = dict(opens[i])           # inherit normalized_t / layer / threshold
        out['points'] = chain
        merged.append(out)
    return merged + closed


def merge_chains(contours, gap):
    """Join open paths within `gap` to cut pen lifts (layer-aware). Off at gap<=0."""
    if gap <= 0:
        return contours
    return _apply_per_layer(contours, lambda g: _merge_layer(g, gap))


def _reorder_layer(paths):
    """Greedy nearest-neighbour visiting order over path endpoints, reversing a
    path when entering from its far end is closer. Starts at the first path."""
    if len(paths) < 3:
        return list(paths)
    remaining = list(range(len(paths)))
    cur = remaining.pop(0)
    ordered = [paths[cur]]
    tail = paths[cur]['points'][-1]
    while remaining:
        best, bestd = None, None
        for k in remaining:
            p = paths[k]['points']
            for rev in (False, True):
                entry = p[-1] if rev else p[0]
                dd = (tail[0] - entry[0]) ** 2 + (tail[1] - entry[1]) ** 2
                if bestd is None or dd < bestd or (dd == bestd and (k, rev) < best):
                    bestd, best = dd, (k, rev)
        k, rev = best
        remaining.remove(k)
        c = _reversed(paths[k]) if rev else paths[k]
        ordered.append(c)
        tail = c['points'][-1]
    return ordered


def reorder_nearest(contours):
    """Greedy nearest-neighbour reordering to shorten pen-up travel (layer-aware)."""
    return _apply_per_layer(contours, _reorder_layer)


def _tour_cost(order):
    return sum(_dist(a['points'][-1], b['points'][0])
               for a, b in zip(order, order[1:]))


def _two_opt_layer(order, passes):
    """First-improvement 2-opt on the visiting order: reversing positions i..j
    flips each path's direction, changing only the two boundary pen-up edges
    (internal edges are symmetric, so their cost is unchanged). Capped at
    `passes` sweeps; guarded so it can never increase total travel."""
    n = len(order)
    if n < 4 or passes <= 0:
        return order
    start_cost = _tour_cost(order)
    order = list(order)
    for _ in range(int(passes)):
        improved = False
        for i in range(0, n - 1):
            for j in range(i + 1, n):
                ei = order[i]['points'][0]          # entry of segment i
                xj = order[j]['points'][-1]          # exit of segment j
                # leading edge (i-1 -> i): present only when i > 0
                old_lead = _dist(order[i - 1]['points'][-1], ei) if i > 0 else 0.0
                new_lead = _dist(order[i - 1]['points'][-1], xj) if i > 0 else 0.0
                # trailing edge (j -> j+1): present only when j < n-1
                if j < n - 1:
                    tj = order[j + 1]['points'][0]
                    old_trail = _dist(order[j]['points'][-1], tj)
                    new_trail = _dist(order[i]['points'][0], tj)
                else:
                    old_trail = new_trail = 0.0
                if (new_lead + new_trail) + 1e-9 < (old_lead + old_trail):
                    order[i:j + 1] = [_reversed(c) for c in reversed(order[i:j + 1])]
                    improved = True
        if not improved:
            break
    # Safety net: never return a worse tour than we started with.
    return order if _tour_cost(order) <= start_cost + 1e-6 else order


def two_opt(contours, passes):
    """Bounded 2-opt polish of the visiting order (layer-aware). Off at passes<=0."""
    if passes <= 0:
        return contours
    return _apply_per_layer(contours, lambda g: _two_opt_layer(g, passes))


def optimize_contours(contours, *, merge_gap=0.0, reorder=False,
                      two_opt_passes=0, min_seg=0.0):
    """Apply the opt-in plotter passes in order: drop-short -> merge -> reorder
    -> 2-opt. Returns the input list unchanged when every option is off (so the
    default export path is byte-identical)."""
    if merge_gap <= 0 and not reorder and two_opt_passes <= 0 and min_seg <= 0:
        return contours
    out = drop_short(contours, min_seg)
    if merge_gap > 0:
        out = merge_chains(out, merge_gap)
    if reorder:
        out = reorder_nearest(out)
    if two_opt_passes > 0:
        out = two_opt(out, two_opt_passes)
    return out
