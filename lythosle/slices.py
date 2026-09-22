"""Slip surfaces and the division of a sliding mass into vertical slices."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .geometry import EPS, Polyline, Pt, circle_from_three_points
from .model import SlopeModel

# Surfaces shallower than this (relative to the slope height) are ignored by the
# search: they are numerically noisy and geotechnically meaningless.
MIN_DEPTH_RATIO = 0.02


@dataclass
class SlipSurface:
    """A trial failure surface, always stored left to right."""

    kind: str                    # "circular" | "polyline"
    points: List[Pt]
    xc: Optional[float] = None
    yc: Optional[float] = None
    radius: Optional[float] = None

    @property
    def x_left(self) -> float:
        return self.points[0][0]

    @property
    def x_right(self) -> float:
        return self.points[-1][0]

    @property
    def entry(self) -> Pt:
        """Where the mass detaches: the upper (crest side) end."""
        return self.points[-1]

    @property
    def exit(self) -> Pt:
        """Where the mass daylights: the lower (toe side) end."""
        return self.points[0]

    def y(self, x: float) -> float:
        if self.kind == "circular":
            dx = x - float(self.xc)
            r2 = float(self.radius) ** 2 - dx * dx
            return float(self.yc) - math.sqrt(max(r2, 0.0))
        return Polyline(self.points).y(x)

    @property
    def chord_length(self) -> float:
        (x1, y1), (x2, y2) = self.points[0], self.points[-1]
        return math.hypot(x2 - x1, y2 - y1)

    def max_depth_below_chord(self) -> float:
        (x1, y1), (x2, y2) = self.points[0], self.points[-1]
        if abs(x2 - x1) < EPS:
            return 0.0
        d = 0.0
        for x, y in self.points:
            chord_y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
            d = max(d, chord_y - y)
        return d

    def to_dict(self, model: Optional[SlopeModel] = None) -> Dict[str, Any]:
        pts = model.to_user_points(self.points) if model else list(self.points)
        out: Dict[str, Any] = {"kind": self.kind, "points": [list(p) for p in pts]}
        if self.kind == "circular":
            xc = model.to_user_x(float(self.xc)) if model else self.xc
            out.update({"xc": xc, "yc": self.yc, "radius": self.radius})
        return out


@dataclass
class Slice:
    """One vertical slice and everything the equilibrium equations need."""

    index: int
    x_left: float
    x_right: float
    x_mid: float
    width: float
    y_base_left: float
    y_base_right: float
    y_base: float               # base mid-ordinate on the slip surface
    y_top: float                # ground surface above the slice mid-point
    alpha: float                # base inclination (rad), +ve on the crest side
    length: float               # base length
    weight: float               # total weight incl. surcharge and ponded water
    weight_seismic: float       # part of the weight that carries seismic inertia
    y_cg: float
    u: float                    # pore pressure at the base
    cohesion: float
    tan_phi: float
    material: str

    @property
    def height(self) -> float:
        return self.y_top - self.y_base


@dataclass
class SlicedMass:
    """A slip surface discretised into slices, plus mass-level quantities."""

    surface: SlipSurface
    slices: List[Slice]
    model: SlopeModel
    crack_force: float = 0.0          # water thrust in the tension crack
    crack_force_y: float = 0.0
    crack_depth: float = 0.0
    supports: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_weight(self) -> float:
        return sum(s.weight for s in self.slices)

    def external_forces(self) -> List[Dict[str, float]]:
        """Point forces acting on the mass other than weight and inertia."""
        out: List[Dict[str, float]] = []
        for sup in self.supports:
            out.append({"x": sup["x"], "y": sup["y"], "fx": sup["fx"], "fy": sup["fy"]})
        if self.crack_force:
            # Water in the crack pushes the mass down-slope, i.e. towards -x.
            out.append({"x": self.surface.points[-1][0], "y": self.crack_force_y,
                        "fx": -self.crack_force, "fy": 0.0})
        return out


# ----------------------------------------------------------------------
# building surfaces
# ----------------------------------------------------------------------
def circular_surface(
    model: SlopeModel,
    xc: float,
    yc: float,
    radius: float,
    n_points: int = 60,
    min_depth: Optional[float] = None,
    allow_bedrock_cut: bool = False,
) -> Optional[SlipSurface]:
    """Build the valid arc of a trial circle, or ``None`` if there is none.

    The arc must daylight at both ends, stay below the ground surface in
    between, and (unless allowed) stay out of impenetrable materials.
    """
    if radius <= 0:
        return None
    hits = model.profile.circle_intersections(xc, yc, radius)
    hits = [h for h in hits if h[1] <= yc + 1e-9]
    if len(hits) < 2:
        return None
    if min_depth is None:
        min_depth = MIN_DEPTH_RATIO * max(model.height, 1.0)

    def arc_y(x: float) -> float:
        r2 = radius * radius - (x - xc) ** 2
        return yc - math.sqrt(max(r2, 0.0))

    best: Optional[SlipSurface] = None
    best_score = 0.0
    for a, b in zip(hits[:-1], hits[1:]):
        x1, x2 = a[0], b[0]
        if x2 - x1 < 1e-6:
            continue
        n = max(12, n_points)
        xs = [x1 + (x2 - x1) * i / n for i in range(n + 1)]
        ok = True
        depth = 0.0
        for x in xs[1:-1]:
            ya = arc_y(x)
            yg = model.ground_y(x)
            if ya > yg - 1e-9:
                ok = False
                break
            depth = max(depth, yg - ya)
            if not allow_bedrock_cut:
                rock = model.impenetrable_y(x)
                if rock is not None and ya < rock:
                    ok = False
                    break
        if not ok or depth < min_depth:
            continue
        pts = [(x1, a[1])] + [(x, arc_y(x)) for x in xs[1:-1]] + [(x2, b[1])]
        score = depth * (x2 - x1)
        if score > best_score:
            best_score = score
            best = SlipSurface("circular", pts, xc, yc, radius)
    return best


def polyline_surface(model: SlopeModel, pts: Sequence[Sequence[float]]) -> Optional[SlipSurface]:
    """Build a general (non-circular) surface from user vertices."""
    pl = Polyline(pts)
    points = [(float(x), float(y)) for x, y in pl.pts]
    # Trim/extend the ends so that they sit exactly on the ground surface.
    def snap_end(p_in: Pt, p_next: Pt) -> Pt:
        x0, y0 = p_in
        x1, y1 = p_next
        if abs(y0 - model.ground_y(x0)) < 1e-6:
            return p_in
        lo, hi = (x0, x1) if x0 < x1 else (x1, x0)
        f_lo = model.ground_y(lo) - Polyline(points).y(lo)
        f_hi = model.ground_y(hi) - Polyline(points).y(hi)
        if f_lo * f_hi > 0:
            return p_in
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            f_mid = model.ground_y(mid) - Polyline(points).y(mid)
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo, f_lo = mid, f_mid
        x = 0.5 * (lo + hi)
        return (x, model.ground_y(x))

    points[0] = snap_end(points[0], points[1])
    points[-1] = snap_end(points[-1], points[-2])
    points = [p for p in points if points[0][0] <= p[0] <= points[-1][0]]
    if len(points) < 2 or points[-1][0] - points[0][0] < 1e-6:
        return None
    return SlipSurface("polyline", points)


def fit_circle(surface: SlipSurface) -> Tuple[float, float, float]:
    """Centre/radius of a representative circle (used as a moment axis)."""
    if surface.kind == "circular":
        return float(surface.xc), float(surface.yc), float(surface.radius)
    pts = surface.points
    mid = pts[len(pts) // 2]
    fit = circle_from_three_points(pts[0], mid, pts[-1])
    if fit is None:
        x1, y1 = pts[0]
        x2, y2 = pts[-1]
        return 0.5 * (x1 + x2), max(y1, y2) + surface.chord_length, surface.chord_length
    return fit


# ----------------------------------------------------------------------
# slicing
# ----------------------------------------------------------------------
def _boundary_xs(model: SlopeModel, x1: float, x2: float) -> List[float]:
    xs = set()
    for x in model.profile.vertices_between(x1, x2):
        xs.add(x)
    for lay in model.layers[1:]:
        for x in lay.boundary.vertices_between(x1, x2):
            xs.add(x)
    if model.water_table:
        for x in model.water_table.vertices_between(x1, x2):
            xs.add(x)
    for s in model.surcharges:
        for x in (s.x1, s.x2):
            if x1 + EPS < x < x2 - EPS:
                xs.add(x)
    return sorted(xs)


def build_slices(
    model: SlopeModel,
    surface: SlipSurface,
    n_slices: int = 50,
    honour_tension_crack: bool = True,
) -> Optional[SlicedMass]:
    """Divide the mass above ``surface`` into slices.

    Slice boundaries are placed at every geometric discontinuity (profile
    vertices, layer boundaries, water-table vertices, edges of surcharges) and
    the remaining width is filled with slices of roughly equal width.
    """
    x1, x2 = surface.x_left, surface.x_right
    warnings: List[str] = []
    crack_depth = 0.0
    crack_force = 0.0
    crack_force_y = 0.0

    # ---- tension crack truncates the upper (crest side, +x) end ----------
    if honour_tension_crack and model.tension_crack.enabled:
        z = model.tension_crack_depth(x2)
        if z > 1e-6:
            n = 200
            x_cut = None
            for i in range(n + 1):
                x = x2 - (x2 - x1) * i / n
                if model.ground_y(x) - surface.y(x) >= z:
                    x_cut = x
                    break
            if x_cut is not None and x_cut > x1 + 1e-6:
                crack_depth = model.ground_y(x_cut) - surface.y(x_cut)
                x2 = x_cut
                fill = max(0.0, min(1.0, model.tension_crack.water_fill))
                hw = fill * crack_depth
                if hw > 0:
                    crack_force = 0.5 * model.water_unit_weight * hw * hw
                    crack_force_y = surface.y(x_cut) + hw / 3.0
            else:
                warnings.append("tension crack deeper than the slip surface; ignored")

    if x2 - x1 < 1e-6:
        return None

    # ---- slice boundaries -------------------------------------------------
    fixed = [x1] + [x for x in _boundary_xs(model, x1, x2)] + [x2]
    if surface.kind == "polyline":
        fixed += [p[0] for p in surface.points if x1 + EPS < p[0] < x2 - EPS]
    fixed = sorted(set(round(x, 12) for x in fixed))
    total = x2 - x1
    edges: List[float] = [fixed[0]]
    for a, b in zip(fixed[:-1], fixed[1:]):
        seg = b - a
        if seg <= 1e-9:
            continue
        k = max(1, int(round(n_slices * seg / total)))
        for i in range(1, k + 1):
            edges.append(a + seg * i / k)
    edges = [e for i, e in enumerate(edges) if i == 0 or e - edges[i - 1] > 1e-9]
    if len(edges) < 3:
        return None

    yw_available = model.water_table is not None
    slices: List[Slice] = []
    for i, (xl, xr) in enumerate(zip(edges[:-1], edges[1:])):
        b = xr - xl
        if b <= 1e-9:
            continue
        yl, yr = surface.y(xl), surface.y(xr)
        xm = 0.5 * (xl + xr)
        ym = surface.y(xm)
        alpha = math.atan2(yr - yl, b)
        length = b / math.cos(alpha)
        y_top = model.ground_y(xm)
        if y_top - ym <= 1e-9:
            continue
        w_soil, y_cg = model.column(xm, ym, y_top)
        w_soil *= b
        q_total, q_seis = model.surcharge_at(xm)
        weight = w_soil + q_total * b
        w_seis = w_soil + q_seis * b
        if yw_available:
            yw = model.water_table.y(xm)
            if yw > y_top:  # ponded water on the slope surface
                extra = model.water_unit_weight * (yw - y_top) * b
                weight += extra
                w_seis += extra
        mat = model.material_at(xm, ym - 1e-6)
        c, tanphi = mat.strength_params(ym, y_top)
        u = model.pore_pressure(xm, ym, mat)
        slices.append(Slice(
            index=len(slices), x_left=xl, x_right=xr, x_mid=xm, width=b,
            y_base_left=yl, y_base_right=yr, y_base=ym, y_top=y_top,
            alpha=alpha, length=length, weight=weight, weight_seismic=w_seis,
            y_cg=y_cg, u=u, cohesion=c, tan_phi=tanphi, material=mat.name,
        ))

    if len(slices) < 3:
        return None

    trimmed = SlipSurface(surface.kind,
                          [(s.x_left, s.y_base_left) for s in slices] +
                          [(slices[-1].x_right, slices[-1].y_base_right)],
                          surface.xc, surface.yc, surface.radius)
    mass = SlicedMass(surface=trimmed, slices=slices, model=model,
                      crack_force=crack_force, crack_force_y=crack_force_y,
                      crack_depth=crack_depth, warnings=warnings)
    mass.supports = model.support_forces(trimmed.points)
    return mass
