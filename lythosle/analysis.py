"""Top level driver: take a model, find the critical surface, report results."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .methods import (METHOD_EQUILIBRIUM, METHOD_LABELS, METHODS, MethodResult,
                      make_context, solve)
from .model import SlopeModel
from .search import (SearchOptions, SearchResult, optimize_noncircular,
                     search_circular, slope_geometry)
from .slices import (SlicedMass, SlipSurface, build_slices, circular_surface,
                     polyline_surface)

DEFAULT_METHODS = ("ordinary", "bishop", "janbu_corrected", "spencer", "morgenstern_price")


@dataclass
class AnalysisOptions:
    methods: Sequence[str] = DEFAULT_METHODS
    n_slices: int = 50
    force_function: str = "half_sine"
    search: SearchOptions = field(default_factory=SearchOptions)
    search_each_method: bool = False
    include_slice_table: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisOptions":
        data = dict(data or {})
        s = dict(data.get("search") or {})
        limits_raw = dict(s.pop("limits", None) or {})
        from .search import SearchLimits
        limits = SearchLimits(**{k: v for k, v in limits_raw.items()
                                 if k in SearchLimits.__dataclass_fields__})
        def pair(v):
            return tuple(float(x) for x in v) if v else None
        search = SearchOptions(
            mode=s.get("mode", "auto"),
            method=s.get("method", "bishop"),
            n_slices=int(s.get("n_slices", 25)),
            center_x=pair(s.get("center_x")),
            center_y=pair(s.get("center_y")),
            nx=int(s.get("nx", 12)),
            ny=int(s.get("ny", 12)),
            radius_mode=s.get("radius_mode", "tangent"),
            tangent_y=pair(s.get("tangent_y")),
            n_tangent=int(s.get("n_tangent", 12)),
            radius=pair(s.get("radius")),
            n_radius=int(s.get("n_radius", 12)),
            refine_passes=int(s.get("refine_passes", 3)),
            limits=limits,
            circle=pair(s.get("circle")),
            polyline=s.get("polyline"),
            optimize=bool(s.get("optimize", False)),
            optimize_vertices=int(s.get("optimize_vertices", 20)),
            optimize_passes=int(s.get("optimize_passes", 40)),
            optimize_method=s.get("optimize_method", "spencer"),
        )
        methods = data.get("methods") or DEFAULT_METHODS
        methods = [m for m in methods if m in METHODS]
        if not methods:
            methods = list(DEFAULT_METHODS)
        if search.method not in methods:
            methods = [search.method] + list(methods)
        return cls(
            methods=methods,
            n_slices=max(5, int(data.get("n_slices", 50))),
            force_function=data.get("force_function", "half_sine"),
            search=search,
            search_each_method=bool(data.get("search_each_method", False)),
            include_slice_table=bool(data.get("include_slice_table", True)),
        )


@dataclass
class AnalysisResult:
    model: SlopeModel
    options: AnalysisOptions
    mass: Optional[SlicedMass]
    results: Dict[str, MethodResult] = field(default_factory=dict)
    search: Optional[SearchResult] = None
    per_method_surfaces: Dict[str, SlipSurface] = field(default_factory=dict)
    per_method_fs: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    runtime: float = 0.0

    @property
    def critical_fs(self) -> Optional[float]:
        primary = self.options.search.method
        r = self.results.get(primary)
        if r and r.fs is not None:
            return r.fs
        for r in self.results.values():
            if r.fs is not None:
                return r.fs
        return None

    # -- reporting -------------------------------------------------------
    def slice_table(self) -> List[Dict[str, Any]]:
        if self.mass is None:
            return []
        primary = self.options.search.method
        res = self.results.get(primary)
        detail = res.detail if res else None
        n_forces = (detail or {}).get("N")
        s_forces = (detail or {}).get("S")
        fs = res.fs if res and res.fs else 1.0
        rows = []
        for i, s in enumerate(self.mass.slices):
            n = n_forces[i] if n_forces else None
            s_av = s_forces[i] if s_forces else None
            row = {
                "index": i + 1,
                "x": self.model.to_user_x(s.x_mid),
                "width": s.width,
                "alpha_deg": math.degrees(s.alpha) * (-1 if self.model.mirrored else 1),
                "height": s.height,
                "weight": s.weight,
                "base_length": s.length,
                "u": s.u,
                "cohesion": s.cohesion,
                "phi_deg": math.degrees(math.atan(s.tan_phi)),
                "material": s.material,
                "normal_force": n,
                "normal_stress": (n / s.length) if n else None,
                "shear_strength": (s_av / s.length) if s_av else None,
                "shear_mobilised": (s_av / (s.length * fs)) if s_av else None,
            }
            rows.append(row)
        return rows

    def to_dict(self, include_render: bool = True) -> Dict[str, Any]:
        model = self.model
        out: Dict[str, Any] = {
            "name": model.name,
            "units": model.units,
            "runtime_s": round(self.runtime, 3),
            "critical_fs": self.critical_fs,
            "primary_method": self.options.search.method,
            "methods": [self.results[m].to_dict() for m in self.options.methods
                        if m in self.results],
            "surface": self.mass.surface.to_dict(model) if self.mass else None,
            "notes": list(self.notes),
            "geometry": slope_geometry(model),
        }
        if self.mass is not None:
            out["mass"] = {
                "weight": self.mass.total_weight,
                "n_slices": len(self.mass.slices),
                "crack_depth": self.mass.crack_depth,
                "crack_force": self.mass.crack_force,
                "supports": [
                    {**s, "x": model.to_user_x(s["x"]),
                     "fx": -s["fx"] if model.mirrored else s["fx"]}
                    for s in self.mass.supports
                ],
                "warnings": list(self.mass.warnings),
            }
        if self.search is not None:
            out["search"] = {
                "evaluated": self.search.evaluated,
                "rejected": self.search.rejected,
                "grid": self.search.grid,
                "box": self.search.box,
                "notes": list(self.search.notes),
            }
        if self.per_method_fs:
            out["per_method"] = {
                m: {"fs": self.per_method_fs[m],
                    "surface": self.per_method_surfaces[m].to_dict(model)}
                for m in self.per_method_fs
            }
        if self.options.include_slice_table:
            out["slices"] = self.slice_table()
        if include_render:
            out["render"] = render_data(self)
        return out

    def text_report(self) -> str:
        m = self.model
        g = slope_geometry(m)
        lines: List[str] = []
        lines.append("Lythos LE  -  limit equilibrium slope stability")
        lines.append("=" * 62)
        lines.append(f"Model            : {m.name}")
        lines.append(f"Units            : {m.units}")
        lines.append(f"Slope height     : {g['height']:.2f}")
        lines.append(f"Average face     : {g['angle']:.1f} deg")
        lines.append(f"Materials        : {', '.join(m.materials)}")
        if m.water_table:
            lines.append("Groundwater      : water table")
        if m.seismic.kh or m.seismic.kv:
            lines.append(f"Seismic          : kh = {m.seismic.kh}, kv = {m.seismic.kv}")
        if self.mass is not None:
            s = self.mass.surface
            if s.kind == "circular":
                lines.append(f"Critical circle  : centre ({m.to_user_x(s.xc):.2f}, "
                             f"{s.yc:.2f}), R = {s.radius:.2f}")
            else:
                lines.append(f"Critical surface : non-circular, "
                             f"{len(s.points)} vertices")
            exit_pt = m.to_user_point(s.points[0])
            entry_pt = m.to_user_point(s.points[-1])
            lines.append(f"Entry / exit     : x = {entry_pt[0]:.2f} / {exit_pt[0]:.2f}")
            lines.append(f"Sliding weight   : {self.mass.total_weight:.1f} per unit width")
            lines.append(f"Slices           : {len(self.mass.slices)}")
        lines.append("")
        lines.append(f"{'Method':<32}{'FS':>9}  {'Equilibrium':<16}{'lambda':>8}")
        lines.append("-" * 68)
        for name in self.options.methods:
            r = self.results.get(name)
            if r is None:
                continue
            fs = f"{r.fs:.3f}" if r.fs is not None else "  -  "
            lam = f"{r.lam:+.3f}" if r.lam is not None else "    -"
            flag = "" if r.converged else "  (not converged)"
            lines.append(f"{METHOD_LABELS[name]:<32}{fs:>9}  "
                         f"{METHOD_EQUILIBRIUM[name]:<16}{lam:>8}{flag}")
        if self.search:
            lines.append("")
            lines.append(f"Surfaces evaluated: {self.search.evaluated} "
                         f"({self.search.rejected} rejected)")
        notes = list(self.notes) + [n for r in self.results.values() for n in r.notes]
        if notes:
            lines.append("")
            lines.append("Notes")
            for n in dict.fromkeys(notes):
                lines.append(f"  - {n}")
        lines.append("")
        lines.append(f"Run time: {self.runtime:.2f} s")
        return "\n".join(lines)


# ----------------------------------------------------------------------
def analyze(model: SlopeModel, options: Optional[AnalysisOptions] = None,
            progress: Optional[Callable[[int, int], None]] = None) -> AnalysisResult:
    """Find the critical surface and evaluate every requested method on it."""
    t0 = time.time()
    options = options or AnalysisOptions()
    model = model.canonical()
    notes: List[str] = []
    search_res: Optional[SearchResult] = None
    surface: Optional[SlipSurface] = None
    sopts = options.search

    if sopts.mode == "single" and sopts.circle:
        xc, yc, r = sopts.circle
        if model.mirrored:
            xc = -xc
        surface = circular_surface(model, xc, yc, r)
        if surface is None:
            notes.append("the specified circle does not form a valid slip surface")
    elif sopts.mode == "polyline" and sopts.polyline:
        pts = [(-p[0], p[1]) for p in sopts.polyline] if model.mirrored else sopts.polyline
        surface = polyline_surface(model, sorted(pts, key=lambda p: p[0]))
        if surface is None:
            notes.append("the specified surface is not valid for this geometry")
    else:
        if model.mirrored:
            sopts = _mirror_search_options(sopts)
        search_res = search_circular(model, sopts, progress)
        surface = search_res.surface
        notes.extend(search_res.notes)
        if surface is not None and sopts.optimize:
            opt = optimize_noncircular(model, surface, sopts)
            notes.extend(opt.notes)
            if opt.surface is not None:
                surface = opt.surface

    if surface is None:
        return AnalysisResult(model, options, None, {}, search_res, notes=notes,
                              runtime=time.time() - t0)

    mass = build_slices(model, surface, options.n_slices)
    if mass is None:
        notes.append("the critical surface could not be sliced at the requested detail")
        return AnalysisResult(model, options, None, {}, search_res, notes=notes,
                              runtime=time.time() - t0)
    notes.extend(mass.warnings)

    ctx = make_context(mass)
    results: Dict[str, MethodResult] = {}
    fs0 = 1.2
    if search_res and search_res.fs:
        fs0 = max(0.2, min(search_res.fs, 50.0))
    for name in options.methods:
        results[name] = solve(mass, name, ctx=ctx, fs0=fs0,
                              force_function=options.force_function)

    per_fs: Dict[str, float] = {}
    per_surf: Dict[str, SlipSurface] = {}
    if options.search_each_method and sopts.mode in ("auto", "grid"):
        for name in options.methods:
            if name == sopts.method:
                continue
            opt2 = SearchOptions(**{**sopts.__dict__, "method": name})
            r2 = search_circular(model, opt2)
            if r2.surface is not None and r2.fs is not None:
                per_fs[name] = r2.fs
                per_surf[name] = r2.surface
        if per_fs:
            notes.append("each method was searched separately; the plotted surface "
                         f"is the critical one for {METHOD_LABELS[sopts.method]}")
    elif len(options.methods) > 1:
        notes.append("all factors of safety are reported for the critical surface of "
                     f"{METHOD_LABELS[sopts.method]}")

    if mass.surface.kind != "circular":
        for name in ("ordinary", "bishop"):
            if name in results:
                results[name].notes.append(
                    "moment-only method on a non-circular surface: the result "
                    "depends on the moment axis")

    return AnalysisResult(model, options, mass, results, search_res, per_surf, per_fs,
                          notes, time.time() - t0)


def _mirror_search_options(s: SearchOptions) -> SearchOptions:
    """Mirror user-supplied search bounds into the canonical frame."""
    def flip(p):
        return (-p[1], -p[0]) if p else None
    lim = s.limits
    from .search import SearchLimits
    new_lim = SearchLimits(
        exit_min=-lim.exit_max if lim.exit_max is not None else None,
        exit_max=-lim.exit_min if lim.exit_min is not None else None,
        entry_min=-lim.entry_max if lim.entry_max is not None else None,
        entry_max=-lim.entry_min if lim.entry_min is not None else None,
        min_depth=lim.min_depth, max_depth=lim.max_depth, min_weight=lim.min_weight,
    )
    out = SearchOptions(**{**s.__dict__})
    out.center_x = flip(s.center_x)
    out.limits = new_lim
    if s.circle:
        out.circle = (-s.circle[0], s.circle[1], s.circle[2])
    return out


# ----------------------------------------------------------------------
def render_data(result: AnalysisResult) -> Dict[str, Any]:
    """Everything the browser needs to draw the model, in user coordinates."""
    model = result.model
    prof = model.profile
    x1, x2 = prof.x_min, prof.x_max
    ys = [p[1] for p in prof.pts]
    for lay in model.layers[1:]:
        ys.extend(p[1] for p in lay.boundary.pts)
    if result.mass is not None:
        ys.extend(p[1] for p in result.mass.surface.points)
    y_bottom = min(ys) - 0.12 * max(model.height, 1.0)

    def to_user(pts):
        return [list(p) for p in model.to_user_points(pts)]

    xs_all = sorted({x1, x2} | set(prof.xs) |
                    {x for lay in model.layers[1:] for x in lay.boundary.xs
                     if x1 < x < x2})

    layers = []
    for i, lay in enumerate(model.layers):
        top = lay.boundary
        bot = model.layers[i + 1].boundary if i + 1 < len(model.layers) else None
        xs = sorted(set(xs_all) | {x for x in top.xs if x1 <= x <= x2} |
                    ({x for x in bot.xs if x1 <= x <= x2} if bot else set()))
        upper = [(x, min(top.y(x), prof.y(x))) for x in xs]
        if bot is None:
            lower = [(x, y_bottom) for x in xs]
        else:
            lower = [(x, min(bot.y(x), top.y(x), prof.y(x))) for x in xs]
        poly = upper + list(reversed(lower))
        mat = model.materials[lay.material]
        layers.append({
            "material": lay.material,
            "color": mat.color,
            "polygon": to_user(poly),
            "boundary": to_user(top.clip(x1, x2)),
        })

    data: Dict[str, Any] = {
        "extents": {"x_min": model.to_user_x(x1 if not model.mirrored else x2),
                    "x_max": model.to_user_x(x2 if not model.mirrored else x1),
                    "y_min": y_bottom, "y_max": max(ys) + 0.05 * max(model.height, 1.0)},
        "profile": to_user(prof.pts),
        "layers": layers,
        "water_table": to_user(model.water_table.clip(x1, x2)) if model.water_table else None,
        "surcharges": [{"x1": model.to_user_x(s.x1), "x2": model.to_user_x(s.x2),
                        "pressure": s.pressure,
                        "y1": prof.y(s.x1), "y2": prof.y(s.x2)}
                       for s in model.surcharges],
        "supports": [{"name": s.name,
                      "p1": list(model.to_user_point((s.x1, s.y1))),
                      "p2": list(model.to_user_point((s.x2, s.y2))),
                      "capacity": s.capacity}
                     for s in model.supports],
    }

    if result.mass is not None:
        surf = result.mass.surface
        data["surface"] = surf.to_dict(model)
        data["slices"] = [
            {"polygon": to_user([(s.x_left, s.y_base_left), (s.x_right, s.y_base_right),
                                 (s.x_right, model.ground_y(s.x_right)),
                                 (s.x_left, model.ground_y(s.x_left))]),
             "weight": s.weight, "alpha_deg": math.degrees(s.alpha)}
            for s in result.mass.slices
        ]
        if result.mass.crack_depth:
            x_top = surf.points[-1][0]
            data["tension_crack"] = {
                "x": model.to_user_x(x_top),
                "y_top": model.ground_y(x_top),
                "y_bottom": surf.points[-1][1],
            }
    if result.search is not None:
        data["search_grid"] = result.search.grid
        box = result.search.box
        if box.get("center_x") and box.get("center_y"):
            cx = sorted(model.to_user_x(v) for v in box["center_x"])
            data["search_box"] = {"x_min": cx[0], "x_max": cx[1],
                                  "y_min": min(box["center_y"]),
                                  "y_max": max(box["center_y"])}
    if result.per_method_surfaces:
        data["per_method_surfaces"] = {
            k: v.to_dict(model) for k, v in result.per_method_surfaces.items()}
    return data
