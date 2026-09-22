"""Planar geometry primitives used by the limit-equilibrium engine.

Everything here is pure standard library: the whole solver is meant to run on a
bare Python install with no third-party packages.

Coordinate convention
---------------------
``x`` increases to the right, ``y`` is elevation (positive up).  All polylines
that describe surfaces (ground profile, material boundaries, water table) are
single valued in ``x`` and stored with increasing ``x``.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import List, Optional, Sequence, Tuple

Pt = Tuple[float, float]

EPS = 1e-9


def _as_points(pts: Sequence[Sequence[float]]) -> List[Pt]:
    out = [(float(p[0]), float(p[1])) for p in pts]
    if len(out) >= 2 and out[0][0] > out[-1][0]:
        out.reverse()
    return out


class Polyline:
    """A single-valued surface ``y = f(x)`` defined by vertices.

    Queries outside the defined range return the first/last elevation, which is
    how slope-stability programs extend material boundaries and water tables
    beyond the drawn extents.
    """

    __slots__ = ("pts", "xs")

    def __init__(self, pts: Sequence[Sequence[float]]):
        pts = _as_points(pts)
        if len(pts) < 2:
            raise ValueError("a polyline needs at least two points")
        # Collapse duplicated x values (keep the lowest, which is what a
        # vertical step in a boundary means for a downward search).
        cleaned: List[Pt] = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - cleaned[-1][0]) < EPS:
                cleaned[-1] = p
            else:
                cleaned.append(p)
        self.pts = cleaned
        self.xs = [p[0] for p in cleaned]

    # -- basic queries ---------------------------------------------------
    @property
    def x_min(self) -> float:
        return self.xs[0]

    @property
    def x_max(self) -> float:
        return self.xs[-1]

    @property
    def y_min(self) -> float:
        return min(p[1] for p in self.pts)

    @property
    def y_max(self) -> float:
        return max(p[1] for p in self.pts)

    def y(self, x: float) -> float:
        """Elevation at ``x`` (clamped outside the defined range)."""
        pts = self.pts
        if x <= pts[0][0]:
            return pts[0][1]
        if x >= pts[-1][0]:
            return pts[-1][1]
        i = bisect_right(self.xs, x) - 1
        if i >= len(pts) - 1:
            return pts[-1][1]
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x1 - x0 < EPS:
            return y1
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def slope(self, x: float) -> float:
        """dy/dx at ``x`` (0 outside the defined range)."""
        pts = self.pts
        if x <= pts[0][0] or x >= pts[-1][0]:
            return 0.0
        i = bisect_right(self.xs, x) - 1
        i = min(i, len(pts) - 2)
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x1 - x0 < EPS:
            return 0.0
        return (y1 - y0) / (x1 - x0)

    def vertices_between(self, x1: float, x2: float) -> List[float]:
        """Interior vertex abscissae strictly inside ``(x1, x2)``."""
        return [x for x in self.xs if x1 + EPS < x < x2 - EPS]

    def clip(self, x1: float, x2: float) -> List[Pt]:
        """The polyline restricted to ``[x1, x2]`` with interpolated ends."""
        out: List[Pt] = [(x1, self.y(x1))]
        for x, y in self.pts:
            if x1 + EPS < x < x2 - EPS:
                out.append((x, y))
        out.append((x2, self.y(x2)))
        return out

    def points(self) -> List[Pt]:
        return list(self.pts)

    # -- intersections ---------------------------------------------------
    def circle_intersections(self, xc: float, yc: float, r: float) -> List[Pt]:
        """Intersections of this polyline with a circle, sorted by ``x``."""
        hits: List[Pt] = []
        for (ax, ay), (bx, by) in zip(self.pts[:-1], self.pts[1:]):
            hits.extend(segment_circle_intersections(ax, ay, bx, by, xc, yc, r))
        hits.sort(key=lambda p: p[0])
        # Drop near-duplicates at shared vertices.
        out: List[Pt] = []
        for p in hits:
            if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-7:
                out.append(p)
        return out


def segment_circle_intersections(
    ax: float, ay: float, bx: float, by: float, xc: float, yc: float, r: float
) -> List[Pt]:
    """Intersections between segment ``A->B`` and a circle centred at ``C``."""
    dx, dy = bx - ax, by - ay
    fx, fy = ax - xc, ay - yc
    a = dx * dx + dy * dy
    if a < EPS:
        return []
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return []
    sq = math.sqrt(disc)
    out: List[Pt] = []
    for t in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)):
        if -1e-12 <= t <= 1.0 + 1e-12:
            t = min(1.0, max(0.0, t))
            out.append((ax + t * dx, ay + t * dy))
    if len(out) == 2 and math.hypot(out[0][0] - out[1][0], out[0][1] - out[1][1]) < 1e-9:
        out.pop()
    return out


def segment_intersection(
    p1: Pt, p2: Pt, p3: Pt, p4: Pt
) -> Optional[Pt]:
    """Intersection of segments ``p1p2`` and ``p3p4`` (``None`` if none)."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < EPS:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    u = ((x1 - x3) * (y1 - y2) - (y1 - y3) * (x1 - x2)) / den
    if -1e-12 <= t <= 1 + 1e-12 and -1e-12 <= u <= 1 + 1e-12:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def polyline_segment_intersections(pts: Sequence[Pt], p3: Pt, p4: Pt) -> List[Pt]:
    out = []
    for a, b in zip(pts[:-1], pts[1:]):
        hit = segment_intersection(a, b, p3, p4)
        if hit is not None:
            out.append(hit)
    return out


def polygon_area(pts: Sequence[Pt]) -> float:
    """Signed area (positive counter-clockwise) of a closed polygon."""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def polygon_centroid(pts: Sequence[Pt]) -> Pt:
    a = polygon_area(pts)
    if abs(a) < EPS:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    return (cx / (6 * a), cy / (6 * a))


def point_in_polygon(x: float, y: float, poly: Sequence[Pt]) -> bool:
    """Ray-casting test; points on the boundary may return either result."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xint = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < xint:
                inside = not inside
        j = i
    return inside


def circle_from_three_points(p1: Pt, p2: Pt, p3: Pt) -> Optional[Tuple[float, float, float]]:
    """Centre and radius of the circle through three points."""
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return None
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1)
          + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3)
          + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    return (ux, uy, math.hypot(x1 - ux, y1 - uy))
