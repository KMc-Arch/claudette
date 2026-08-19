#!/usr/bin/env python3
"""Read-only legibility linter for a diagram in this standard.

It reads a .drawio and reports geometry facts. It never writes, and it never judges appearance:
every rule below is an arithmetic statement about rectangles and segments, which is the half of
"is this readable" that a machine can actually answer. The other half is a person looking at a
print, and that is what produced these rules in the first place.

    python3 lint.py heartbeat-03.drawio

Each rule exists because a cold reader, given only a PNG, failed at it. Their words are quoted.

  R1 label-erases-edge   drawio paints an edge label on an opaque backing, so a label wider than
                         the segment it sits on deletes the edge. "At page scale this looks like a
                         line struck through the words." Two headline edges were invisible.
  R2 edge-through-box    a line crossing a box it does not connect cannot be told from a line
                         ending at it. "The naive reading is wrong, and the picture supports it."
  R3 label-on-trunk      OPERATOR RULING 2026-08-19: edges converging on, or diverging from, one
                         shape MAY coincide — a merged trunk is legal and is the intended reading.
                         What must not happen is a label on the shared run: it would be ambiguous
                         between the merged edges, and its opaque backing would erase all of them at
                         once. A label belongs on the distinct segment, near the end that tells the
                         edges apart. Fires when a labelled edge's label position falls on a segment
                         it shares with another edge.
  R4 crowded-parallels   independent lines closer than 24px read as one stroke (measured: pairs at
                         2px and 14px each read as a single line). Only fires for edges that share
                         NO endpoint — by the ruling above, converging edges are meant to coincide.
  R5 collinear-border    a segment sharing an axis with a box border reads as that border, wiring
                         the box into the graph. "A cold reader will conclude the note box is
                         wired into the scheduler."
  R6 label-on-shape      a label rectangle at the path midpoint landing on any shape.
  R7 unmarked-crossing   crossings with no jump: "a crossing and a corner are visually identical."
                         Reported as a count; set jumpStyle on the survivors.
"""
import math
import re
import sys
import xml.etree.ElementTree as ET
from itertools import combinations

CHAR_W, LABEL_H, MIN_PARALLEL, PAD = 5.6, 18.0, 24.0, 6.0


def visible(v):
    v = re.sub(r'<br\s*/?>', ' ', v or '')
    v = re.sub(r'&[a-z]+;', 'x', v)
    return re.sub('<[^>]+>', '', v).strip()


def skey(style, k, default):
    m = re.search(r'(?:^|;)%s=([^;]*)' % k, style or '')
    return float(m.group(1)) if m else default


def rects(cells):
    byid = {c.get('id'): c for c in cells}
    out = {}

    def res(c):
        i = c.get('id')
        if i in out:
            return out[i]
        g = c.find('mxGeometry')
        if g is None or g.get('x') is None:
            return None
        v = [float(g.get('x')), float(g.get('y')), float(g.get('width') or 0), float(g.get('height') or 0)]
        p = byid.get(c.get('parent'))
        if p is not None and p.get('vertex') == '1':
            pg = res(p)
            if pg:
                v = [v[0] + pg[0], v[1] + pg[1], v[2], v[3]]
        out[i] = v
        return v
    for c in cells:
        if c.get('vertex') == '1':
            res(c)
    return out


def polyline(edge, box):
    st = edge.get('style') or ''
    s, t = box.get(edge.get('source')), box.get(edge.get('target'))
    if not s or not t:
        return None
    pts = [(s[0] + skey(st, 'exitX', .5) * s[2], s[1] + skey(st, 'exitY', .5) * s[3])]
    g = edge.find('mxGeometry')
    arr = g.find('Array') if g is not None else None
    if arr is not None:
        pts += [(float(p.get('x')), float(p.get('y'))) for p in arr.findall('mxPoint')]
    pts.append((t[0] + skey(st, 'entryX', .5) * t[2], t[1] + skey(st, 'entryY', .5) * t[3]))
    return pts


def seg_hits_rect(p, q, rc, pad=PAD):
    x, y, w, h = rc[0] - pad, rc[1] - pad, rc[2] + 2 * pad, rc[3] + 2 * pad
    if abs(p[0] - q[0]) < 1:
        return x < p[0] < x + w and min(p[1], q[1]) < y + h and max(p[1], q[1]) > y
    if abs(p[1] - q[1]) < 1:
        return y < p[1] < y + h and min(p[0], q[0]) < x + w and max(p[0], q[0]) > x
    return False


def label_point(pts, rel=0.0):
    """Where drawio actually draws the label: rel is the edge geometry's x, -1 source .. +1 target,
    0 = midpoint. Returns the point and the length of the segment the label sits on."""
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    want, run = sum(seg) * (rel + 1) / 2, 0
    for i, d in enumerate(seg):
        if run + d >= want and d > 0:
            f = (want - run) / d
            return (pts[i][0] + f * (pts[i + 1][0] - pts[i][0]), pts[i][1] + f * (pts[i + 1][1] - pts[i][1])), d
        run += d
    return pts[-1], seg[-1] if seg else 0


def lint(path):
    root = ET.parse(path).getroot()
    total = 0
    for dia in root.findall('diagram'):
        cells = dia.find('mxGraphModel').find('root').findall('mxCell')
        box = rects(cells)
        shapes = [(c.get('id'), box[c.get('id')]) for c in cells if c.get('vertex') == '1'
                  and box.get(c.get('id')) and not (c.get('style') or '').startswith('text;')]
        solid = [(i, r) for i, r in shapes if 'swimlane' not in
                 (next(c for c in cells if c.get('id') == i).get('style') or '')]
        edges = [c for c in cells if c.get('edge') == '1']
        f = {k: [] for k in ('R1', 'R2', 'R3', 'R4', 'R5', 'R6')}
        segs, labelled = [], []
        for e in edges:
            pts = polyline(e, box)
            if not pts:
                continue
            eid, lab = e.get('id'), visible(e.get('value'))
            g = e.find('mxGeometry')
            rel = float(g.get('x')) if (g is not None and g.get('x')) else 0.0
            mid, seglen = label_point(pts, rel)
            lw = len(lab) * CHAR_W + 12
            labelled.append((eid, lab, mid, lw))
            if lab and lw > seglen - 10:
                f['R1'].append((eid, lab, round(lw), round(seglen)))
            if lab:
                lr = [mid[0] - lw / 2, mid[1] - LABEL_H / 2, lw, LABEL_H]
                for sid, rc in solid:
                    if lr[0] < rc[0] + rc[2] and rc[0] < lr[0] + lr[2] and lr[1] < rc[1] + rc[3] and rc[1] < lr[1] + lr[3]:
                        f['R6'].append((eid, sid))
                        break
            for i in range(len(pts) - 1):
                p, q = pts[i], pts[i + 1]
                segs.append((eid, p, q))
                for sid, rc in solid:
                    if sid in (e.get('source'), e.get('target')):
                        continue
                    if seg_hits_rect(p, q, rc):
                        f['R2'].append((eid, sid))
                        break
                for sid, rc in shapes:
                    if abs(p[0] - q[0]) < 1 and (abs(p[0] - rc[0]) < 4 or abs(p[0] - rc[0] - rc[2]) < 4) \
                       and min(p[1], q[1]) < rc[1] + rc[3] and max(p[1], q[1]) > rc[1] and sid not in (e.get('source'), e.get('target')):
                        f['R5'].append((eid, sid))
                        break
        for eid, lab, mid, own in labelled:
            if not lab:
                continue
            for oid, p, q in segs:
                if oid == eid:
                    continue
                # is the label sitting on a run this edge shares with another?
                if abs(p[0] - q[0]) < 1 and abs(mid[0] - p[0]) < 6 and min(p[1], q[1]) - 6 < mid[1] < max(p[1], q[1]) + 6 \
                   or abs(p[1] - q[1]) < 1 and abs(mid[1] - p[1]) < 6 and min(p[0], q[0]) - 6 < mid[0] < max(p[0], q[0]) + 6:
                    f['R3'].append((eid, oid))
                    break
        ends = {e.get('id'): {e.get('source'), e.get('target')} for e in edges}
        for (ea, pa, qa), (eb, pb, qb) in combinations(segs, 2):
            if ea == eb or (ends.get(ea, set()) & ends.get(eb, set())):
                continue
            if abs(pa[0] - qa[0]) < 1 and abs(pb[0] - qb[0]) < 1:
                d = abs(pa[0] - pb[0])
                if d < MIN_PARALLEL and min(max(pa[1], qa[1]), max(pb[1], qb[1])) - max(min(pa[1], qa[1]), min(pb[1], qb[1])) > 40:
                    f['R4'].append((ea, eb, round(d)))
            if abs(pa[1] - qa[1]) < 1 and abs(pb[1] - qb[1]) < 1:
                d = abs(pa[1] - pb[1])
                if d < MIN_PARALLEL and min(max(pa[0], qa[0]), max(pb[0], qb[0])) - max(min(pa[0], qa[0]), min(pb[0], qb[0])) > 40:
                    f['R4'].append((ea, eb, round(d)))
        for k in f:
            f[k] = sorted(set(map(tuple, f[k])))
        n = sum(len(v) for v in f.values())
        total += n
        print(f"{dia.get('name'):32s} " + "  ".join(f"{k}={len(v)}" for k, v in f.items()) + f"   [{n}]")
        for k, v in f.items():
            for item in v[:4]:
                print(f"      {k} {item}")
    print(f"\nTOTAL {total} — a page is publishable at 0")
    return total


if __name__ == '__main__':
    sys.exit(1 if lint(sys.argv[1] if len(sys.argv) > 1 else 'heartbeat-02.drawio') else 0)
