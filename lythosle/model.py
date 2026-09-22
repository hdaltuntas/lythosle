"""The slope model: geometry, stratigraphy, groundwater and loading.

Internal orientation
--------------------
The solver works in a canonical frame in which the **crest is on the right and
the sliding mass moves towards -x**.  Models drawn the other way round are
mirrored on input (``SlopeModel.mirrored``) and mirrored back when results are
serialised, so the user never has to care.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .geometry import EPS, Polyline, Pt, point_in_polygon
from .materials import DEFAULT_COLORS, Material

WATER_UNIT_WEIGHT = {"metric": 9.81, "imperial": 62.4}


@dataclass
class Layer:
    """A stratum, identified by the material below ``boundary``."""

    material: str
    boundary: Polyline


@dataclass
class Surcharge:
    """A uniform vertical pressure applied to the ground surface."""

    x1: float
    x2: float
    pressure: float
    include_in_seismic: bool = False

    def at(self, x: float) -> float:
        lo, hi = min(self.x1, self.x2), max(self.x1, self.x2)
        return self.pressure if lo - EPS <= x <= hi + EPS else 0.0


@dataclass
class Support:
    """A reinforcement element (anchor, nail, geosynthetic layer).

    The element applies ``capacity`` (force per unit width out of plane) to the
    sliding mass at the point where the slip surface crosses it, directed along
    the element towards its anchored end.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    capacity: float
    name: str = "Support"

    @property
    def p1(self) -> Pt:
        return (self.x1, self.y1)

    @property
    def p2(self) -> Pt:
        return (self.x2, self.y2)


@dataclass
class TensionCrack:
    """A vertical crack that truncates the upper end of the slip surface."""

    enabled: bool = False
    depth: Optional[float] = None       # measured below the ground surface
    auto: bool = False                  # z = 2c/gamma * tan(45 + phi/2)
    water_fill: float = 0.0             # 0..1 fraction of the crack holding water


@dataclass
class Seismic:
    kh: float = 0.0     # horizontal coefficient, force acts down-slope
    kv: float = 0.0     # vertical coefficient, positive acts downwards


class SlopeModel:
    """Container for everything that defines a stability problem."""

    def __init__(
        self,
        profile: Sequence[Sequence[float]],
        materials: Sequence[Material],
        layers: Optional[Sequence[Layer]] = None,
        water_table: Optional[Sequence[Sequence[float]]] = None,
        water_unit_weight: float = 9.81,
        seismic: Optional[Seismic] = None,
        surcharges: Optional[Sequence[Surcharge]] = None,
        supports: Optional[Sequence[Support]] = None,
        tension_crack: Optional[TensionCrack] = None,
        units: str = "metric",
        name: str = "Slope",
        mirrored: bool = False,
    ):
        self.name = name
        self.units = units
        self.profile = Polyline(profile)
        self.materials: Dict[str, Material] = {m.name: m for m in materials}
        if not self.materials:
            raise ValueError("the model needs at least one material")
        if layers:
            self.layers = list(layers)
        else:
            first = next(iter(self.materials))
            self.layers = [Layer(first, self.profile)]
        # The top of the uppermost layer is always the ground surface.
        self.layers[0] = Layer(self.layers[0].material, self.profile)
        for lay in self.layers:
            if lay.material not in self.materials:
                raise ValueError(f"layer references unknown material {lay.material!r}")
        self.water_table = Polyline(water_table) if water_table else None
        self.water_unit_weight = float(water_unit_weight)
        self.seismic = seismic or Seismic()
        self.surcharges = list(surcharges or [])
        self.supports = list(supports or [])
        self.tension_crack = tension_crack or TensionCrack()
        self.mirrored = mirrored

    # ------------------------------------------------------------------
    # geometry queries
    # ------------------------------------------------------------------
    @property
    def x_min(self) -> float:
        return self.profile.x_min

    @property
    def x_max(self) -> float:
        return self.profile.x_max

    def ground_y(self, x: float) -> float:
        return self.profile.y(x)

    @property
    def crest_y(self) -> float:
        return max(p[1] for p in self.profile.pts)

    @property
    def toe_y(self) -> float:
        return min(p[1] for p in self.profile.pts)

    @property
    def height(self) -> float:
        return self.crest_y - self.toe_y

    def layer_index_at(self, x: float, y: float) -> int:
        """Index of the layer containing ``(x, y)`` (0 = uppermost)."""
        idx = 0
        for i, lay in enumerate(self.layers):
            if lay.boundary.y(x) >= y - 1e-9:
                idx = i
            else:
                break
        return idx

    def material_at(self, x: float, y: float) -> Material:
        return self.materials[self.layers[self.layer_index_at(x, y)].material]

    def water_y(self, x: float) -> Optional[float]:
        return self.water_table.y(x) if self.water_table else None

    def surcharge_at(self, x: float) -> Tuple[float, float]:
        """``(total pressure, pressure that participates in seismic loading)``."""
        total = seis = 0.0
        for s in self.surcharges:
            q = s.at(x)
            total += q
            if s.include_in_seismic:
                seis += q
        return total, seis

    # ------------------------------------------------------------------
    # column integration
    # ------------------------------------------------------------------
    def column(self, x: float, y_bot: float, y_top: Optional[float] = None) -> Tuple[float, float]:
        """Integrate a vertical column of soil at abscissa ``x``.

        Returns ``(weight per unit width, centroid elevation)`` between
        ``y_bot`` and the ground surface (or ``y_top`` when given).  Unit
        weights switch to the saturated value below the water table.
        """
        if y_top is None:
            y_top = self.ground_y(x)
        if y_top - y_bot <= EPS:
            return 0.0, y_bot
        splits = {y_bot, y_top}
        for lay in self.layers[1:]:
            yb = lay.boundary.y(x)
            if y_bot < yb < y_top:
                splits.add(yb)
        if self.water_table:
            yw = self.water_table.y(x)
            if y_bot < yw < y_top:
                splits.add(yw)
        ys = sorted(splits)
        w = 0.0
        moment = 0.0
        yw = self.water_table.y(x) if self.water_table else None
        for lo, hi in zip(ys[:-1], ys[1:]):
            h = hi - lo
            if h <= EPS:
                continue
            ymid = 0.5 * (lo + hi)
            mat = self.material_at(x, ymid)
            submerged = yw is not None and ymid < yw
            dw = mat.gamma(submerged) * h
            w += dw
            moment += dw * ymid
        return w, (moment / w if w > EPS else 0.5 * (y_bot + y_top))

    def vertical_stress(self, x: float, y: float) -> float:
        """Total vertical stress at ``(x, y)`` from the soil column above."""
        w, _ = self.column(x, y)
        return w

    def pore_pressure(self, x: float, y: float, material: Optional[Material] = None) -> float:
        """Pore water pressure at a point on the slip surface."""
        mat = material or self.material_at(x, y)
        if mat.ru > 0.0:
            return mat.ru * self.vertical_stress(x, y)
        if self.water_table is not None:
            head = self.water_table.y(x) - y
            if head > 0.0:
                return self.water_unit_weight * head
        return 0.0

    # ------------------------------------------------------------------
    # helpers used by the slicing / search code
    # ------------------------------------------------------------------
    def impenetrable_y(self, x: float) -> Optional[float]:
        """Top elevation of the shallowest impenetrable layer at ``x``."""
        for lay in self.layers:
            if self.materials[lay.material].impenetrable:
                return lay.boundary.y(x)
        return None

    def tension_crack_depth(self, x: float) -> float:
        """Crack depth below the crest, either user-given or estimated."""
        tc = self.tension_crack
        if not tc.enabled:
            return 0.0
        if tc.depth is not None and not tc.auto:
            return max(0.0, float(tc.depth))
        mat = self.material_at(x, self.ground_y(x) - 1e-6)
        c, _ = mat.strength_params(self.ground_y(x), self.ground_y(x))
        gamma = mat.gamma(False)
        phi = 0.0 if mat.is_undrained else mat.friction_angle
        ka_term = math.tan(math.radians(45.0 + phi / 2.0))
        return max(0.0, 2.0 * c * ka_term / gamma) if gamma > 0 else 0.0

    def mass_polygon(self, surface_pts: Sequence[Pt]) -> List[Pt]:
        """Closed polygon of the sliding mass (ground above, slip below)."""
        x1, x2 = surface_pts[0][0], surface_pts[-1][0]
        top = self.profile.clip(min(x1, x2), max(x1, x2))
        poly = list(surface_pts) + list(reversed(top))
        return poly

    def support_forces(self, surface_pts: Sequence[Pt]) -> List[Dict[str, Any]]:
        """Resolve reinforcement forces acting on a given sliding mass."""
        if not self.supports:
            return []
        poly = self.mass_polygon(surface_pts)
        out: List[Dict[str, Any]] = []
        surf = list(surface_pts)
        for sup in self.supports:
            hits = []
            for a, b in zip(surf[:-1], surf[1:]):
                from .geometry import segment_intersection
                hit = segment_intersection(a, b, sup.p1, sup.p2)
                if hit is not None:
                    hits.append(hit)
            if not hits:
                continue
            px, py = hits[0]
            in1 = point_in_polygon(sup.x1, sup.y1, poly)
            in2 = point_in_polygon(sup.x2, sup.y2, poly)
            if in1 and not in2:
                anchor = sup.p2
            elif in2 and not in1:
                anchor = sup.p1
            else:  # ambiguous: point towards the end further from the mass
                anchor = sup.p2
            dx, dy = anchor[0] - px, anchor[1] - py
            norm = math.hypot(dx, dy)
            if norm < EPS:
                continue
            out.append({
                "name": sup.name,
                "x": px, "y": py,
                "fx": sup.capacity * dx / norm,
                "fy": sup.capacity * dy / norm,
                "magnitude": sup.capacity,
            })
        return out

    # ------------------------------------------------------------------
    # mirroring
    # ------------------------------------------------------------------
    def to_user_x(self, x: float) -> float:
        return -x if self.mirrored else x

    def to_user_point(self, p: Sequence[float]) -> Pt:
        return (self.to_user_x(p[0]), p[1])

    def to_user_points(self, pts: Sequence[Sequence[float]]) -> List[Pt]:
        out = [self.to_user_point(p) for p in pts]
        return list(reversed(out)) if self.mirrored else out

    def mirror(self) -> "SlopeModel":
        """Return a copy with ``x -> -x`` (crest and toe swapped)."""
        def mx(pts):
            return [(-p[0], p[1]) for p in reversed(list(pts))]

        return SlopeModel(
            profile=mx(self.profile.pts),
            materials=list(self.materials.values()),
            layers=[Layer(l.material, Polyline(mx(l.boundary.pts))) for l in self.layers],
            water_table=mx(self.water_table.pts) if self.water_table else None,
            water_unit_weight=self.water_unit_weight,
            seismic=self.seismic,
            surcharges=[Surcharge(-s.x2, -s.x1, s.pressure, s.include_in_seismic)
                        for s in self.surcharges],
            supports=[Support(-s.x1, s.y1, -s.x2, s.y2, s.capacity, s.name)
                      for s in self.supports],
            tension_crack=self.tension_crack,
            units=self.units,
            name=self.name,
            mirrored=not self.mirrored,
        )

    def canonical(self) -> "SlopeModel":
        """Return this model oriented with the crest on the right."""
        if self.profile.pts[0][1] > self.profile.pts[-1][1]:
            return self.mirror()
        return self

    # ------------------------------------------------------------------
    # (de)serialisation
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlopeModel":
        units = data.get("units", "metric")
        mats = [Material.from_dict(m) for m in data.get("materials", [])]
        if not mats:
            mats = [Material()]
        for i, m in enumerate(mats):
            if not m.color:
                m.color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        profile = data["profile"]
        layers: List[Layer] = []
        raw_layers = data.get("layers") or []
        for i, lay in enumerate(raw_layers):
            boundary = lay.get("boundary")
            if i == 0 or not boundary:
                boundary = profile if i == 0 else None
            if boundary is None:
                raise ValueError("layers below the first one need a boundary")
            layers.append(Layer(lay["material"], Polyline(boundary)))
        if not layers:
            layers = [Layer(mats[0].name, Polyline(profile))]
        seismic_raw = data.get("seismic") or {}
        tc_raw = data.get("tension_crack") or {}
        model = cls(
            profile=profile,
            materials=mats,
            layers=layers,
            water_table=data.get("water_table"),
            water_unit_weight=float(
                data.get("water_unit_weight", WATER_UNIT_WEIGHT.get(units, 9.81))),
            seismic=Seismic(float(seismic_raw.get("kh", 0.0)), float(seismic_raw.get("kv", 0.0))),
            surcharges=[Surcharge(float(s["x1"]), float(s["x2"]), float(s["pressure"]),
                                  bool(s.get("include_in_seismic", False)))
                        for s in data.get("surcharges", [])],
            supports=[Support(float(s["x1"]), float(s["y1"]), float(s["x2"]), float(s["y2"]),
                              float(s.get("capacity", 0.0)), s.get("name", "Support"))
                      for s in data.get("supports", [])],
            tension_crack=TensionCrack(
                enabled=bool(tc_raw.get("enabled", False)),
                depth=(float(tc_raw["depth"]) if tc_raw.get("depth") not in (None, "") else None),
                auto=bool(tc_raw.get("auto", False)),
                water_fill=float(tc_raw.get("water_fill", 0.0)),
            ),
            units=units,
            name=data.get("name", "Slope"),
        )
        return model

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "units": self.units,
            "profile": [list(self.to_user_point(p)) for p in
                        (reversed(self.profile.pts) if self.mirrored else self.profile.pts)],
            "materials": [m.to_dict() for m in self.materials.values()],
            "layers": [
                {"material": l.material,
                 "boundary": [list(self.to_user_point(p)) for p in
                              (reversed(l.boundary.pts) if self.mirrored else l.boundary.pts)]}
                for l in self.layers
            ],
            "water_table": ([list(self.to_user_point(p)) for p in
                             (reversed(self.water_table.pts) if self.mirrored
                              else self.water_table.pts)]
                            if self.water_table else None),
            "water_unit_weight": self.water_unit_weight,
            "seismic": {"kh": self.seismic.kh, "kv": self.seismic.kv},
            "surcharges": [
                {"x1": self.to_user_x(s.x1), "x2": self.to_user_x(s.x2),
                 "pressure": s.pressure, "include_in_seismic": s.include_in_seismic}
                for s in self.surcharges
            ],
            "supports": [
                {"name": s.name, "x1": self.to_user_x(s.x1), "y1": s.y1,
                 "x2": self.to_user_x(s.x2), "y2": s.y2, "capacity": s.capacity}
                for s in self.supports
            ],
            "tension_crack": {
                "enabled": self.tension_crack.enabled,
                "depth": self.tension_crack.depth,
                "auto": self.tension_crack.auto,
                "water_fill": self.tension_crack.water_fill,
            },
        }
