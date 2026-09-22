"""Critical slip surface searches.

Two searches are provided:

``grid and tangent``
    The classic Slide/SLOPE-W style search.  Circle centres are taken from a
    rectangular grid and radii from a set of tangent elevations, then the grid
    is refined around the best centre a few times.

``surface optimisation``
    A non-circular refinement that perturbs the vertices of the critical
    circular surface (Greco-style coordinate descent) to find a lower factor of
    safety.
"""

from __future__ import annotations

import math
import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .methods import solve
from .model import SlopeModel
from .slices import SlipSurface, build_slices, circular_surface, fit_circle


@dataclass
class SearchLimits:
    """Where a slip surface is allowed to enter and exit the ground."""

    exit_min: Optional[float] = None    # toe side (left in the canonical frame)
    exit_max: Optional[float] = None
    entry_min: Optional[float] = None   # crest side
    entry_max: Optional[float] = None
    min_depth: Optional[float] = None
    max_depth: Optional[float] = None
    min_weight: float = 0.0


@dataclass
class SearchOptions:
    """Controls for the critical surface search."""

    mode: str = "auto"                 # "auto" | "grid" | "single" | "polyline"
    method: str = "bishop"             # method used to rank trial surfaces
    n_slices: int = 25                 # slices used while searching
    # explicit grid (canonical/user coordinates are handled by the caller)
    center_x: Optional[Tuple[float, float]] = None
    center_y: Optional[Tuple[float, float]] = None
    nx: int = 12
    ny: int = 12
    radius_mode: str = "tangent"       # "tangent" | "range"
    tangent_y: Optional[Tuple[float, float]] = None
    n_tangent: int = 12
    radius: Optional[Tuple[float, float]] = None
    n_radius: int = 12
    refine_passes: int = 3
    limits: SearchLimits = field(default_factory=SearchLimits)
    # single surface
    circle: Optional[Tuple[float, float, float]] = None
    polyline: Optional[List[Sequence[float]]] = None
    # non-circular optimisation
    optimize: bool = False
    optimize_vertices: int = 20
    optimize_passes: int = 40
    optimize_method: str = "spencer"


@dataclass
class SearchResult:
    surface: Optional[SlipSurface]
    fs: Optional[float]
    evaluated: int
    rejected: int
    grid: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    box: Dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
def slope_geometry(model: SlopeModel) -> Dict[str, float]:
    """Toe, crest and average inclination of the face that faces -x.

    In the canonical frame the sliding mass moves towards -x, so the face of
    interest is the one on the left of the highest ground.  Taking the crest as
    the first point at the maximum elevation and the toe as the last low point
    before it also gives the right answer for two-sided embankments.
    """
    pts = model.profile.pts
    y_crest = max(p[1] for p in pts)
    x_crest = min(p[0] for p in pts if abs(p[1] - y_crest) < 1e-9)
    left = [p for p in pts if p[0] <= x_crest + 1e-9]
    if len(left) < 2:
        left = pts[:2]
    y_toe = min(p[1] for p in left)
    x_toe = max(p[0] for p in left if abs(p[1] - y_toe) < 1e-9)
    height = max(y_crest - y_toe, 1e-6)
    run = max(x_crest - x_toe, 1e-6)
    return {"x_toe": x_toe, "y_toe": y_toe, "x_crest": x_crest, "y_crest": y_crest,
            "height": height, "run": run,
            "angle": math.degrees(math.atan2(height, run))}


def auto_search_options(model: SlopeModel, base: Optional[SearchOptions] = None) -> SearchOptions:
    """Derive a sensible grid-and-tangent search box from the geometry.

    A copy is returned: filling in a box for one model must not leak into the
    caller's options and then be reused for a different geometry.
    """
    opts = copy.copy(base) if base is not None else SearchOptions()
    opts.limits = copy.copy(opts.limits)
    g = slope_geometry(model)
    h = g["height"]
    x_toe, x_crest = g["x_toe"], g["x_crest"]
    if opts.center_x is None:
        opts.center_x = (x_toe - 0.4 * h, x_crest + 1.4 * h)
    if opts.center_y is None:
        opts.center_y = (g["y_crest"] + 0.15 * h, g["y_crest"] + 2.2 * h)
    if opts.tangent_y is None:
        rock = model.impenetrable_y(0.5 * (x_toe + x_crest))
        deepest = g["y_toe"] - 1.0 * h
        if rock is not None:
            deepest = max(rock + 0.02 * h, g["y_toe"] - 2.5 * h)
        opts.tangent_y = (deepest, g["y_toe"] + 0.45 * h)
    if opts.limits.min_depth is None:
        opts.limits.min_depth = 0.04 * h
    return opts


def _evaluate(model: SlopeModel, xc: float, yc: float, radius: float,
              opts: SearchOptions) -> Tuple[Optional[float], Optional[SlipSurface], str]:
    surf = circular_surface(model, xc, yc, radius, n_points=32,
                            min_depth=opts.limits.min_depth)
    if surf is None:
        return None, None, "no valid arc"
    lim = opts.limits
    x_exit, x_entry = surf.x_left, surf.x_right
    if lim.exit_min is not None and x_exit < lim.exit_min:
        return None, None, "exit outside limits"
    if lim.exit_max is not None and x_exit > lim.exit_max:
        return None, None, "exit outside limits"
    if lim.entry_min is not None and x_entry < lim.entry_min:
        return None, None, "entry outside limits"
    if lim.entry_max is not None and x_entry > lim.entry_max:
        return None, None, "entry outside limits"
    if lim.max_depth is not None:
        depth = max(model.ground_y(x) - y for x, y in surf.points)
        if depth > lim.max_depth:
            return None, None, "deeper than the limit"
    mass = build_slices(model, surf, opts.n_slices)
    if mass is None:
        return None, None, "could not slice"
    if lim.min_weight and mass.total_weight < lim.min_weight:
        return None, None, "mass too small"
    res = solve(mass, opts.method)
    if not res.ok:
        return None, None, "no converged solution"
    return res.fs, mass.surface, ""


def search_circular(model: SlopeModel, opts: Optional[SearchOptions] = None,
                    progress: Optional[Callable[[int, int], None]] = None) -> SearchResult:
    """Grid-and-tangent search, with an adaptive box and local refinement.

    The coarse grid is expanded (up to ``MAX_EXPANSIONS`` times) whenever the
    best trial sits on the edge of the search box, so a critical surface that
    is deeper or further back than the default box is still found.  The grid is
    then refined around the best centre and tangent.
    """
    opts = auto_search_options(model, opts)
    state = _SearchState(model, opts)

    cx = tuple(opts.center_x)          # type: ignore[arg-type]
    cy = tuple(opts.center_y)          # type: ignore[arg-type]
    ty = tuple(opts.tangent_y) if opts.tangent_y else None
    rr = tuple(opts.radius) if opts.radius else None
    nx, ny = max(2, opts.nx), max(2, opts.ny)
    nt = max(2, opts.n_tangent if opts.radius_mode == "tangent" else opts.n_radius)

    expansions = 0
    while True:
        edges = state.run_pass(cx, cy, ty, rr, nx, ny, nt, progress)
        if (expansions >= MAX_EXPANSIONS or state.best_fs is None
                or not any(edges.values())):
            break
        expansions += 1
        w = (cx[1] - cx[0]) or 1.0
        hgt = (cy[1] - cy[0]) or 1.0
        if edges.get("x_lo"):
            cx = (cx[0] - 0.6 * w, cx[1])
        if edges.get("x_hi"):
            cx = (cx[0], cx[1] + 0.6 * w)
        if edges.get("y_lo"):
            cy = (max(model.crest_y + 1e-3, cy[0] - 0.4 * hgt), cy[1])
        if edges.get("y_hi"):
            cy = (cy[0], cy[1] + 0.6 * hgt)
        if ty and (edges.get("t_lo") or edges.get("t_hi")):
            span = (ty[1] - ty[0]) or 1.0
            lo, hi = ty
            if edges.get("t_lo"):
                lo -= 0.5 * span
                rock = model.impenetrable_y(0.5 * (cx[0] + cx[1]))
                if rock is not None:
                    lo = max(lo, rock + 1e-3)
            if edges.get("t_hi"):
                hi = min(hi + 0.4 * span, model.crest_y - 1e-3)
            ty = (lo, hi)
        state.notes.append("search box expanded to reach the critical surface")

    # ---- local refinement -------------------------------------------------
    for _ in range(max(0, opts.refine_passes)):
        if state.best_center is None:
            break
        dx = (cx[1] - cx[0]) / max(nx - 1, 1)
        dy = (cy[1] - cy[0]) / max(ny - 1, 1)
        cx = (state.best_center[0] - dx, state.best_center[0] + dx)
        cy = (state.best_center[1] - dy, state.best_center[1] + dy)
        if opts.radius_mode == "tangent" and ty and state.best_tangent is not None:
            dt = (ty[1] - ty[0]) / max(nt - 1, 1)
            ty = (state.best_tangent - dt, state.best_tangent + dt)
        elif rr and state.best_surface is not None:
            dr = (rr[1] - rr[0]) / max(nt - 1, 1)
            r0 = float(state.best_surface.radius or 0.0)
            rr = (r0 - dr, r0 + dr)
        nx = ny = nt = 7
        state.run_pass(cx, cy, ty, rr, nx, ny, nt, progress)

    box = {"center_x": list(cx), "center_y": list(cy)}
    if ty:
        box["tangent_y"] = list(ty)
    result = state.result()
    result.box = box
    return result


MAX_EXPANSIONS = 3


class _SearchState:
    """Mutable bookkeeping shared by the passes of one search."""

    def __init__(self, model: SlopeModel, opts: SearchOptions):
        self.model = model
        self.opts = opts
        self.grid_map: Dict[Tuple[float, float], float] = {}
        self.evaluated = 0
        self.rejected = 0
        self.best_fs: Optional[float] = None
        self.best_surface: Optional[SlipSurface] = None
        self.best_center: Optional[Tuple[float, float]] = None
        self.best_tangent: Optional[float] = None
        self.notes: List[str] = []

    def run_pass(self, cx, cy, ty, rr, nx, ny, nt, progress) -> Dict[str, bool]:
        opts = self.opts
        xs = [cx[0] + (cx[1] - cx[0]) * i / (nx - 1) for i in range(nx)] if nx > 1 else [cx[0]]
        ys = [cy[0] + (cy[1] - cy[0]) * i / (ny - 1) for i in range(ny)] if ny > 1 else [cy[0]]
        if opts.radius_mode == "tangent" and ty:
            levels = [ty[0] + (ty[1] - ty[0]) * i / (nt - 1) for i in range(nt)]
        elif rr:
            levels = [rr[0] + (rr[1] - rr[0]) * i / (nt - 1) for i in range(nt)]
        else:
            levels = []
        total = len(xs) * len(ys) * max(1, len(levels))
        done = 0
        pass_best = None
        for x in xs:
            for y in ys:
                cell_best: Optional[float] = None
                for lv in levels:
                    radius = (y - lv) if opts.radius_mode == "tangent" else lv
                    done += 1
                    if radius <= 0:
                        self.rejected += 1
                        continue
                    fs, surf, _why = _evaluate(self.model, x, y, radius, opts)
                    self.evaluated += 1
                    if fs is None:
                        self.rejected += 1
                        continue
                    if cell_best is None or fs < cell_best:
                        cell_best = fs
                    if self.best_fs is None or fs < self.best_fs:
                        self.best_fs, self.best_surface = fs, surf
                        self.best_center, self.best_tangent = (x, y), lv
                    if pass_best is None or fs < pass_best[0]:
                        pass_best = (fs, x, y, lv)
                if cell_best is not None:
                    key = (round(x, 6), round(y, 6))
                    prev = self.grid_map.get(key)
                    if prev is None or cell_best < prev:
                        self.grid_map[key] = cell_best
                if progress:
                    progress(done, total)
        if pass_best is None:
            return {}
        _fs, bx, by, blv = pass_best
        tol = 1e-9
        return {
            "x_lo": abs(bx - xs[0]) < tol and len(xs) > 1,
            "x_hi": abs(bx - xs[-1]) < tol and len(xs) > 1,
            "y_lo": abs(by - ys[0]) < tol and len(ys) > 1,
            "y_hi": abs(by - ys[-1]) < tol and len(ys) > 1,
            "t_lo": bool(levels) and abs(blv - levels[0]) < tol and len(levels) > 1,
            "t_hi": bool(levels) and abs(blv - levels[-1]) < tol and len(levels) > 1,
        }

    def result(self) -> SearchResult:
        notes = list(dict.fromkeys(self.notes))
        if self.best_surface is None:
            notes.append("no valid slip surface was found; check the search limits "
                         "and the slope geometry")
        grid = [{"x": self.model.to_user_x(k[0]), "y": k[1], "fs": v}
                for k, v in self.grid_map.items()]
        return SearchResult(self.best_surface, self.best_fs,
                            self.evaluated, self.rejected, grid, notes)


# ----------------------------------------------------------------------
def _admissible(model: SlopeModel, pts: Sequence[Sequence[float]],
                min_depth: float, x_bounds: Tuple[float, float]) -> bool:
    """Kinematic admissibility checks for a trial non-circular surface.

    The surface must stay under the ground and out of impenetrable materials,
    its segments must not be near-vertical, and it must be concave upwards:
    the base inclination has to increase from the toe towards the crest, which
    is what a rotational/translational mechanism looks like.  Without this the
    optimiser happily invents zig-zag surfaces with a meaningless low FS.
    """
    if pts[-1][0] - pts[0][0] < 1e-6:
        return False
    if pts[0][0] < x_bounds[0] - 1e-9 or pts[-1][0] > x_bounds[1] + 1e-9:
        return False
    depth = 0.0
    prev_alpha = None
    for i, (x, y) in enumerate(pts):
        yg = model.ground_y(x)
        if i in (0, len(pts) - 1):
            if abs(y - yg) > 1e-6:
                return False
        else:
            if y > yg - 1e-9:
                return False
            depth = max(depth, yg - y)
        rock = model.impenetrable_y(x)
        if rock is not None and y < rock - 1e-9:
            return False
        if i:
            dx = x - pts[i - 1][0]
            if dx <= 1e-9:
                return False
            alpha = math.atan2(y - pts[i - 1][1], dx)
            if abs(alpha) > math.radians(80.0):
                return False
            if prev_alpha is not None and alpha < prev_alpha - 0.02:
                return False   # concave upwards
            prev_alpha = alpha
    return depth >= min_depth


def _surface_fs(model: SlopeModel, pts: Sequence[Sequence[float]], opts: SearchOptions,
                axis: Optional[Tuple[float, float]] = None,
                method: Optional[str] = None, lam_seed: Optional[float] = None
                ) -> Tuple[Optional[float], Optional[SlipSurface], Optional[float]]:
    from .methods import make_context
    from .slices import polyline_surface
    surf = polyline_surface(model, pts)
    if surf is None:
        return None, None, None
    mass = build_slices(model, surf, opts.n_slices)
    if mass is None:
        return None, None, None
    ctx = make_context(mass, axis=axis)
    res = solve(mass, method or opts.method, ctx=ctx, lam_seed=lam_seed)
    if not res.ok:
        return None, None, None
    return res.fs, mass.surface, res.lam


def optimize_noncircular(model: SlopeModel, surface: SlipSurface,
                         opts: SearchOptions) -> SearchResult:
    """Improve a surface by moving its vertices (Greco-style coordinate descent).

    The starting surface is resampled to ``optimize_vertices`` points; interior
    vertices then move vertically and the two ends slide along the ground
    surface.  A move is kept only when it lowers the factor of safety *and*
    leaves the surface admissible.

    Trials are ranked with a complete-equilibrium method (Spencer by default),
    warm-started from the previous lambda.  Ranking non-circular surfaces with
    a moment-only method such as Bishop is meaningless - the result then
    depends on an arbitrary moment axis, and the optimiser simply walks towards
    whatever axis flatters it.
    """
    n = max(6, opts.optimize_vertices)
    x1, x2 = surface.x_left, surface.x_right
    span = x2 - x1
    pts = [[x1 + span * i / (n - 1), surface.y(x1 + span * i / (n - 1))] for i in range(n)]
    pts[0][1] = model.ground_y(pts[0][0])
    pts[-1][1] = model.ground_y(pts[-1][0])

    method = opts.optimize_method
    if method in ("ordinary", "bishop"):
        method = "spencer"
    height = max(model.height, 1.0)
    min_depth = opts.limits.min_depth or 0.04 * height
    reach = 0.4 * height
    x_bounds = (max(model.x_min, x1 - reach), min(model.x_max, x2 + reach))
    axis = fit_circle(surface)[:2]

    # Baseline: the circular surface itself, scored with the same method, so
    # the reported gain is not just the polygonal resampling being recovered.
    circ_fs = None
    circ_mass = build_slices(model, surface, opts.n_slices)
    if circ_mass is not None:
        from .methods import make_context
        res0 = solve(circ_mass, method, ctx=make_context(circ_mass, axis=axis))
        if res0.ok:
            circ_fs = res0.fs

    fs, best_surf, lam = _surface_fs(model, pts, opts, axis, method)
    if fs is None:
        return SearchResult(None, None, 0, 0,
                            notes=["the starting surface could not be optimised"])
    start_fs = fs
    step = 0.06 * height
    evaluated = improved = 0
    for _ in range(max(1, opts.optimize_passes)):
        moved = False
        for i in range(n):
            for sign in (-1.0, 1.0):
                trial = [list(p) for p in pts]
                if i in (0, n - 1):
                    trial[i][0] += sign * step
                    trial[i][1] = model.ground_y(trial[i][0])
                    if trial[-1][0] - trial[0][0] < max(0.4 * span, 2.0 * min_depth):
                        continue
                else:
                    trial[i][1] += sign * step
                if not _admissible(model, trial, min_depth, x_bounds):
                    continue
                f, s, l = _surface_fs(model, trial, opts, axis, method, lam)
                evaluated += 1
                if f is not None and f < fs - 1e-6:
                    fs, best_surf, pts = f, s, trial
                    if l is not None:
                        lam = l
                    moved = True
                    improved += 1
        if not moved:
            step *= 0.5
            if step < 0.002 * height:
                break
    base_fs = circ_fs if circ_fs is not None else start_fs
    gain = 100.0 * (base_fs - fs) / base_fs if base_fs else 0.0
    from .methods import METHOD_LABELS
    notes = [f"non-circular optimisation ({METHOD_LABELS[method]}): FS {base_fs:.3f} "
             f"-> {fs:.3f} ({gain:.1f}%) after {evaluated} trial surfaces"]
    if fs >= base_fs - 1e-9:
        return SearchResult(None, None, evaluated, 0,
                            notes=["the circular surface could not be improved on"])
    return SearchResult(best_surf, fs, evaluated, 0, notes=notes)
