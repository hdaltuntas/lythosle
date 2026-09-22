"""Limit-equilibrium solvers.

All methods share one slice formulation and differ only in
(a) which equilibrium equations are satisfied and
(b) what is assumed about the interslice forces ``X = lambda * f(x) * E``.

Sign conventions (canonical frame: crest on the right, sliding towards -x)
-------------------------------------------------------------------------
* ``alpha`` is the base inclination measured from the +x axis, so it is
  positive under the crest and negative near the toe.
* Driving quantities are counted positive: the weight moment about the centre
  of rotation is ``W * (x_base - x_axis)`` and the driving horizontal force is
  ``N sin(alpha) + kh W``.
* The mobilised base shear is ``S_m = (c*l + (N - u*l) tan(phi)) / F``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .slices import SlicedMass, fit_circle

#: Methods exposed to users, in reporting order.
METHODS = (
    "ordinary",
    "bishop",
    "janbu",
    "janbu_corrected",
    "corps_engineers",
    "lowe_karafiath",
    "spencer",
    "morgenstern_price",
)

METHOD_LABELS = {
    "ordinary": "Ordinary / Fellenius",
    "bishop": "Bishop simplified",
    "janbu": "Janbu simplified",
    "janbu_corrected": "Janbu corrected",
    "corps_engineers": "Corps of Engineers #1",
    "lowe_karafiath": "Lowe-Karafiath",
    "spencer": "Spencer",
    "morgenstern_price": "Morgenstern-Price (half-sine)",
}

#: Which equilibrium conditions each method satisfies.
METHOD_EQUILIBRIUM = {
    "ordinary": "moment",
    "bishop": "moment",
    "janbu": "force",
    "janbu_corrected": "force",
    "corps_engineers": "force",
    "lowe_karafiath": "force",
    "spencer": "moment + force",
    "morgenstern_price": "moment + force",
}

MIN_M_ALPHA = 0.02
_MAX_FS = 1.0e4


@dataclass
class MethodResult:
    """Outcome of one method on one slip surface."""

    method: str
    fs: Optional[float] = None
    converged: bool = False
    iterations: int = 0
    lam: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    detail: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.fs is not None and self.converged and 0.0 < self.fs < _MAX_FS

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "method": self.method,
            "label": METHOD_LABELS.get(self.method, self.method),
            "equilibrium": METHOD_EQUILIBRIUM.get(self.method, ""),
            "fs": self.fs,
            "converged": self.converged,
            "iterations": self.iterations,
            "lambda": self.lam,
            "notes": list(self.notes),
        }
        if self.detail and self.detail.get("lambda_plot"):
            out["lambda_plot"] = self.detail["lambda_plot"]
        return out


class Context:
    """Pre-computed per-slice quantities shared by every solver."""

    __slots__ = (
        "n", "sa", "ca", "cl", "ul", "tphi", "w", "wk", "rho", "gam", "md",
        "kh", "kv", "x_axis", "y_axis", "fx_slice", "m_ext", "qx", "slices",
        "circular", "radius", "fvals_x",
    )

    def __init__(self, mass: SlicedMass, x_axis: float, y_axis: float):
        model = mass.model
        sl = mass.slices
        self.slices = sl
        self.n = len(sl)
        self.kh = model.seismic.kh
        self.kv = model.seismic.kv
        self.x_axis = x_axis
        self.y_axis = y_axis
        self.circular = mass.surface.kind == "circular"
        self.radius = float(mass.surface.radius) if self.circular else None

        self.sa = [math.sin(s.alpha) for s in sl]
        self.ca = [math.cos(s.alpha) for s in sl]
        self.cl = [s.cohesion * s.length for s in sl]
        self.ul = [s.u * s.length for s in sl]
        self.tphi = [s.tan_phi for s in sl]
        self.w = [s.weight for s in sl]
        self.wk = [s.weight_seismic for s in sl]

        if self.circular:
            r = self.radius
            self.rho = [r] * self.n          # every base shear acts at radius R
            self.gam = [0.0] * self.n        # N passes through the centre
        else:
            self.rho = [(s.x_mid - x_axis) * self.sa[i] - (s.y_base - y_axis) * self.ca[i]
                        for i, s in enumerate(sl)]
            self.gam = [(s.x_mid - x_axis) * self.ca[i] + (s.y_base - y_axis) * self.sa[i]
                        for i, s in enumerate(sl)]

        self.md = [
            s.weight * (1.0 + self.kv) * (s.x_mid - x_axis)
            + self.kh * s.weight_seismic * (y_axis - s.y_cg)
            for s in sl
        ]

        # External point forces (reinforcement, water thrust in a crack).
        self.fx_slice = [0.0] * self.n
        m_ext = 0.0
        qx = 0.0
        edges = [s.x_left for s in sl] + [sl[-1].x_right]
        for f in mass.external_forces():
            px, py, fx, fy = f["x"], f["y"], f["fx"], f["fy"]
            j = 0
            for i in range(self.n):
                if edges[i] <= px <= edges[i + 1]:
                    j = i
                    break
                if px > edges[i + 1]:
                    j = i
            self.fx_slice[j] += fx
            qx += fx
            m_ext += -((px - x_axis) * fy - (py - y_axis) * fx)
        self.m_ext = m_ext
        self.qx = qx

        x1, x2 = sl[0].x_left, sl[-1].x_right
        span = max(x2 - x1, 1e-9)
        self.fvals_x = [(e - x1) / span for e in edges]

    # -- interslice force-function shapes --------------------------------
    def f_constant(self) -> List[float]:
        return [1.0] * (self.n + 1)

    def f_half_sine(self) -> List[float]:
        return [math.sin(math.pi * t) for t in self.fvals_x]

    def f_trapezoidal(self) -> List[float]:
        out = []
        for t in self.fvals_x:
            if t < 0.25:
                out.append(t / 0.25)
            elif t > 0.75:
                out.append((1.0 - t) / 0.25)
            else:
                out.append(1.0)
        return out


def _shear_available(ctx: Context, N: Sequence[float]) -> List[float]:
    out = []
    for i in range(ctx.n):
        n_eff = N[i] - ctx.ul[i]
        if n_eff < 0.0:
            n_eff = 0.0
        out.append(ctx.cl[i] + n_eff * ctx.tphi[i])
    return out


def _normal_forces(ctx: Context, fs: float, x: Sequence[float]) -> Tuple[List[float], float]:
    """Base normal forces from vertical equilibrium of each slice."""
    n = ctx.n
    out = [0.0] * n
    m_min = 1e9
    for i in range(n):
        m = ctx.ca[i] + ctx.sa[i] * ctx.tphi[i] / fs
        if m < m_min:
            m_min = m
        if abs(m) < MIN_M_ALPHA:
            m = math.copysign(MIN_M_ALPHA, m if m != 0 else 1.0)
        # Vertical equilibrium of the slice.  X[i] is the vertical interslice
        # force at boundary i exerted by the material on the left of that
        # boundary on the material to its right, positive upwards, so the
        # resultant of the two faces on this slice is +(X[i+1] - X[i]).
        dx = x[i + 1] - x[i]
        num = (ctx.w[i] * (1.0 + ctx.kv) + dx
               - (ctx.cl[i] - ctx.ul[i] * ctx.tphi[i]) * ctx.sa[i] / fs)
        out[i] = num / m
    return out, m_min


def _moment_fs(ctx: Context, N: Sequence[float], s_av: Sequence[float]) -> Optional[float]:
    num = sum(s_av[i] * ctx.rho[i] for i in range(ctx.n))
    den = sum(ctx.md) + ctx.m_ext - sum(N[i] * ctx.gam[i] for i in range(ctx.n))
    if den <= 1e-9 or num <= 0.0:
        return None
    return num / den


def _force_fs(ctx: Context, N: Sequence[float], s_av: Sequence[float]) -> Optional[float]:
    num = sum(s_av[i] * ctx.ca[i] for i in range(ctx.n))
    den = (sum(N[i] * ctx.sa[i] for i in range(ctx.n))
           + sum(ctx.kh * ctx.wk[i] for i in range(ctx.n)) - ctx.qx)
    if den <= 1e-9 or num <= 0.0:
        return None
    return num / den


def _interslice(ctx: Context, N: Sequence[float], s_av: Sequence[float], fs: float,
                lam: float, fvals: Sequence[float]) -> Tuple[List[float], List[float]]:
    """Integrate horizontal slice equilibrium to get E, then X = lam f E."""
    n = ctx.n
    e = [0.0] * (n + 1)
    for i in range(n):
        de = (-N[i] * ctx.sa[i] + (s_av[i] / fs) * ctx.ca[i]
              - ctx.kh * ctx.wk[i] + ctx.fx_slice[i])
        e[i + 1] = e[i] + de
    x = [lam * fvals[i] * e[i] for i in range(n + 1)]
    x[0] = 0.0
    x[n] = 0.0
    return e, x


def _solve_branch(ctx: Context, lam: float, fvals: Sequence[float], which: str,
                  fs0: float = 1.2, max_iter: int = 80, tol: float = 1e-6,
                  relax: float = 0.6) -> Dict[str, Any]:
    """Iterate one equilibrium branch ('m' = moment, 'f' = force)."""
    fs = fs0
    n = ctx.n
    x = [0.0] * (n + 1)
    e = [0.0] * (n + 1)
    converged = False
    notes: List[str] = []
    it = 0
    N: List[float] = []
    s_av: List[float] = []
    for it in range(1, max_iter + 1):
        N, m_min = _normal_forces(ctx, fs, x)
        s_av = _shear_available(ctx, N)
        fm = _moment_fs(ctx, N, s_av)
        ff = _force_fs(ctx, N, s_av)
        new = fm if which == "m" else ff
        if new is None or not math.isfinite(new) or new <= 0.0:
            return {"fs": None, "converged": False, "iterations": it,
                    "notes": ["no equilibrium solution (zero or reversed driving force)"]}
        new = min(new, _MAX_FS)
        if lam != 0.0:
            e, x = _interslice(ctx, N, s_av, fs, lam, fvals)
        if abs(new - fs) < tol * max(1.0, fs):
            fs = new
            converged = True
            break
        fs += relax * (new - fs)
        if fs <= 0.01:
            fs = 0.01
    N, m_min = _normal_forces(ctx, fs, x)
    if m_min < 0.2:
        notes.append(f"small m-alpha ({m_min:.3f}); the normal force is poorly conditioned")
    return {"fs": fs, "converged": converged, "iterations": it, "notes": notes,
            "N": N, "E": e, "X": x, "S": _shear_available(ctx, N)}


# ----------------------------------------------------------------------
# individual methods
# ----------------------------------------------------------------------
def ordinary(mass: SlicedMass, ctx: Optional[Context] = None, **_: Any) -> MethodResult:
    """Ordinary (Fellenius / Swedish) method: no interslice forces at all."""
    ctx = ctx or make_context(mass)
    N = []
    for i, s in enumerate(ctx.slices):
        N.append(ctx.w[i] * (1.0 + ctx.kv) * ctx.ca[i] - ctx.kh * ctx.wk[i] * ctx.sa[i])
    s_av = _shear_available(ctx, N)
    fs = _moment_fs(ctx, N, s_av)
    if fs is None:
        return MethodResult("ordinary", None, False, 1,
                            notes=["no equilibrium solution"])
    return MethodResult("ordinary", fs, True, 1,
                        detail={"N": N, "S": s_av})


def bishop(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
           **_: Any) -> MethodResult:
    """Bishop's simplified method: moment equilibrium, horizontal interslice forces."""
    ctx = ctx or make_context(mass)
    r = _solve_branch(ctx, 0.0, ctx.f_constant(), "m", fs0=fs0)
    return MethodResult("bishop", r["fs"], r["converged"], r["iterations"],
                        notes=r["notes"], detail=_detail(r))


def janbu(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
          **_: Any) -> MethodResult:
    """Janbu's simplified method: horizontal force equilibrium, X = 0."""
    ctx = ctx or make_context(mass)
    r = _solve_branch(ctx, 0.0, ctx.f_constant(), "f", fs0=fs0)
    return MethodResult("janbu", r["fs"], r["converged"], r["iterations"],
                        notes=r["notes"], detail=_detail(r))


def janbu_correction_factor(mass: SlicedMass) -> float:
    """Janbu's empirical correction ``f0`` for the simplified method."""
    surf = mass.surface
    chord = surf.chord_length
    if chord <= 1e-9:
        return 1.0
    d = surf.max_depth_below_chord()
    has_c = any(s.cohesion > 1e-9 for s in mass.slices)
    has_phi = any(s.tan_phi > 1e-9 for s in mass.slices)
    if has_c and has_phi:
        b1 = 0.50
    elif has_phi:
        b1 = 0.31
    else:
        b1 = 0.69
    ratio = d / chord
    return 1.0 + b1 * (ratio - 1.4 * ratio * ratio)


def janbu_corrected(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
                    **_: Any) -> MethodResult:
    ctx = ctx or make_context(mass)
    base = janbu(mass, ctx, fs0=fs0)
    f0 = janbu_correction_factor(mass)
    fs = base.fs * f0 if base.fs is not None else None
    notes = list(base.notes) + [f"Janbu correction factor f0 = {f0:.3f}"]
    return MethodResult("janbu_corrected", fs, base.converged, base.iterations,
                        notes=notes, detail=base.detail)


def _prescribed_angle_method(name: str, mass: SlicedMass, ctx: Context,
                             fvals: Sequence[float], fs0: float) -> MethodResult:
    r = _solve_branch(ctx, 1.0, fvals, "f", fs0=fs0)
    return MethodResult(name, r["fs"], r["converged"], r["iterations"], lam=1.0,
                        notes=r["notes"], detail=_detail(r))


def corps_engineers(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
                    **_: Any) -> MethodResult:
    """Corps of Engineers #1: interslice forces parallel to the entry-exit chord."""
    ctx = ctx or make_context(mass)
    p0, p1 = mass.surface.points[0], mass.surface.points[-1]
    slope = (p1[1] - p0[1]) / max(p1[0] - p0[0], 1e-9)
    fvals = [slope] * (ctx.n + 1)
    return _prescribed_angle_method("corps_engineers", mass, ctx, fvals, fs0)


def lowe_karafiath(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
                   **_: Any) -> MethodResult:
    """Lowe-Karafiath: interslice inclination = average of ground and base slopes."""
    ctx = ctx or make_context(mass)
    model = mass.model
    sl = mass.slices
    edges = [s.x_left for s in sl] + [sl[-1].x_right]
    fvals = []
    for i, xe in enumerate(edges):
        ground = model.profile.slope(xe)
        if i == 0:
            base = math.tan(sl[0].alpha)
        elif i == len(edges) - 1:
            base = math.tan(sl[-1].alpha)
        else:
            base = 0.5 * (math.tan(sl[i - 1].alpha) + math.tan(sl[i].alpha))
        fvals.append(0.5 * (ground + base))
    return _prescribed_angle_method("lowe_karafiath", mass, ctx, fvals, fs0)


def _gle(name: str, mass: SlicedMass, ctx: Context, fvals: Sequence[float],
         fs0: float, lam_range: Tuple[float, float] = (-0.6, 1.4),
         n_scan: int = 15, lam_seed: Optional[float] = None) -> MethodResult:
    """Spencer / Morgenstern-Price: find lambda where Fm(lambda) = Ff(lambda).

    ``lam_seed`` warm-starts the root search with a secant iteration, which is
    what makes repeated evaluations (surface optimisation) affordable.
    """

    cache: Dict[float, Tuple[Optional[float], Optional[float]]] = {}

    def both(lam: float) -> Tuple[Optional[float], Optional[float]]:
        key = round(lam, 9)
        if key in cache:
            return cache[key]
        rm = _solve_branch(ctx, lam, fvals, "m", fs0=fs0)
        rf = _solve_branch(ctx, lam, fvals, "f", fs0=fs0)
        fm = rm["fs"] if rm["converged"] else None
        ff = rf["fs"] if rf["converged"] else None
        cache[key] = (fm, ff)
        return fm, ff

    if lam_seed is not None:
        fast = _secant_lambda(both, lam_seed, lam_range)
        if fast is not None:
            lam, fm, ff = fast
            fs = 0.5 * (fm + ff)
            return MethodResult(name, fs, True, 0, lam=lam)

    lo, hi = lam_range
    lams = [lo + (hi - lo) * i / (n_scan - 1) for i in range(n_scan)]
    samples: List[Tuple[float, float]] = []
    for lam in lams:
        fm, ff = both(lam)
        if fm is None or ff is None:
            continue
        samples.append((lam, fm - ff))

    if len(samples) < 2:
        # Fall back to the moment solution with zero interslice shear.
        r = _solve_branch(ctx, 0.0, fvals, "m", fs0=fs0)
        return MethodResult(name, r["fs"], False, r["iterations"], lam=0.0,
                            notes=["lambda search failed; reported value is moment-only"],
                            detail=_detail(r))

    bracket = None
    for (l1, g1), (l2, g2) in zip(samples[:-1], samples[1:]):
        if g1 == 0.0:
            bracket = (l1, l1)
            break
        if g1 * g2 < 0.0:
            bracket = (l1, l2)
            break
    notes: List[str] = []
    if bracket is None:
        lam = min(samples, key=lambda s: abs(s[1]))[0]
        fm_c, ff_c = both(lam)
        return MethodResult(
            name, None, False, 0, lam=lam,
            notes=[f"no solution: the moment and force factors of safety never "
                   f"become equal (Fm = {fm_c:.3f} against Ff = {ff_c:.3f} at "
                   f"lambda = {lam:.3f}). This usually means the surface is held "
                   f"by an external force large enough to satisfy force "
                   f"equilibrium on its own; read the moment and force methods "
                   f"separately instead."])
    else:
        a, b = bracket
        ga = (both(a)[0] or 0.0) - (both(a)[1] or 0.0)
        for _ in range(60):
            mid = 0.5 * (a + b)
            fm, ff = both(mid)
            if fm is None or ff is None:
                break
            gm = fm - ff
            if abs(gm) < 1e-7 * fm or (b - a) < 1e-5:
                a = b = mid
                break
            if ga * gm < 0.0:
                b = mid
            else:
                a, ga = mid, gm
        lam = 0.5 * (a + b)

    rm = _solve_branch(ctx, lam, fvals, "m", fs0=fs0)
    rf = _solve_branch(ctx, lam, fvals, "f", fs0=fs0)
    fm, ff = rm["fs"], rf["fs"]
    if fm is None or ff is None:
        return MethodResult(name, None, False, rm["iterations"], lam=lam,
                            notes=notes + ["no converged solution"])
    fs = 0.5 * (fm + ff)
    converged = rm["converged"] and rf["converged"] and abs(fm - ff) < 5e-3 * fs
    if not converged and bracket is not None:
        notes.append(f"Fm = {fm:.4f} vs Ff = {ff:.4f} at lambda = {lam:.4f}")
    detail = _detail(rm)
    if detail is not None:
        detail["lambda_plot"] = [
            {"lambda": l, "fm": both(l)[0], "ff": both(l)[1]} for l in lams
        ]
        detail["E"] = rm.get("E")
        detail["X"] = rm.get("X")
    return MethodResult(name, fs, converged, rm["iterations"], lam=lam,
                        notes=notes + rm["notes"], detail=detail)


def _secant_lambda(both: Callable[[float], Tuple[Optional[float], Optional[float]]],
                   lam0: float, lam_range: Tuple[float, float],
                   max_iter: int = 10, tol: float = 1e-5
                   ) -> Optional[Tuple[float, float, float]]:
    """Secant iteration on g(lambda) = Fm - Ff from a warm start."""
    l0 = lam0
    l1 = lam0 + 0.05
    fm0, ff0 = both(l0)
    if fm0 is None or ff0 is None:
        return None
    g0 = fm0 - ff0
    for _ in range(max_iter):
        fm1, ff1 = both(l1)
        if fm1 is None or ff1 is None:
            return None
        g1 = fm1 - ff1
        if abs(g1) < tol * max(fm1, 1.0):
            return l1, fm1, ff1
        if abs(g1 - g0) < 1e-12:
            return None
        l2 = l1 - g1 * (l1 - l0) / (g1 - g0)
        if not (lam_range[0] - 0.5 <= l2 <= lam_range[1] + 0.5):
            return None
        l0, g0, l1 = l1, g1, l2
    return None


def spencer(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
            lam_seed: Optional[float] = None, **_: Any) -> MethodResult:
    """Spencer's method: constant interslice force inclination."""
    ctx = ctx or make_context(mass)
    return _gle("spencer", mass, ctx, ctx.f_constant(), fs0, lam_seed=lam_seed)


def morgenstern_price(mass: SlicedMass, ctx: Optional[Context] = None, fs0: float = 1.2,
                      force_function: str = "half_sine", **_: Any) -> MethodResult:
    """Morgenstern-Price with a selectable interslice force function."""
    ctx = ctx or make_context(mass)
    fvals = {
        "half_sine": ctx.f_half_sine,
        "constant": ctx.f_constant,
        "trapezoidal": ctx.f_trapezoidal,
    }.get(force_function, ctx.f_half_sine)()
    return _gle("morgenstern_price", mass, ctx, fvals, fs0)


SOLVERS: Dict[str, Callable[..., MethodResult]] = {
    "ordinary": ordinary,
    "bishop": bishop,
    "janbu": janbu,
    "janbu_corrected": janbu_corrected,
    "corps_engineers": corps_engineers,
    "lowe_karafiath": lowe_karafiath,
    "spencer": spencer,
    "morgenstern_price": morgenstern_price,
}


def make_context(mass: SlicedMass, axis: Optional[Tuple[float, float]] = None) -> Context:
    if axis is None:
        xc, yc, _r = fit_circle(mass.surface)
        axis = (xc, yc)
    return Context(mass, axis[0], axis[1])


def _detail(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "N" not in r:
        return None
    return {"N": r.get("N"), "S": r.get("S"), "E": r.get("E"), "X": r.get("X")}


def solve(mass: SlicedMass, method: str, ctx: Optional[Context] = None,
          fs0: float = 1.2, **kwargs: Any) -> MethodResult:
    """Run one named method on a sliced mass."""
    try:
        fn = SOLVERS[method]
    except KeyError:
        raise ValueError(f"unknown method {method!r}; expected one of {', '.join(METHODS)}")
    ctx = ctx or make_context(mass)
    return fn(mass, ctx, fs0=fs0, **kwargs)


def solve_all(mass: SlicedMass, methods: Sequence[str] = METHODS,
              fs0: float = 1.2, **kwargs: Any) -> Dict[str, MethodResult]:
    ctx = make_context(mass)
    out: Dict[str, MethodResult] = {}
    for m in methods:
        out[m] = solve(mass, m, ctx=ctx, fs0=fs0, **kwargs)
    return out
