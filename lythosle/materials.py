"""Soil strength models.

Every strength model is reduced to a Mohr-Coulomb pair ``(c, tan phi)`` at the
point where the slip surface passes, so the limit-equilibrium solvers only ever
see ``tau_f = c + sigma'_n * tan(phi)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

#: Strength models understood by :class:`Material`.
STRENGTH_MODELS = (
    "mohr_coulomb",      # drained/effective stress: c', phi'
    "undrained",         # phi = 0, s_u (optionally varying linearly with depth)
    "infinite",          # never fails (bedrock, retaining structure)
    "no_strength",       # open water / very soft fill
)

DEFAULT_COLORS = (
    "#D97757", "#C4A883", "#7EA89B", "#9B8AA6", "#B5A642",
    "#8FA6C4", "#C98B8B", "#6F8F6F", "#A88C6B", "#8C8C8C",
)


@dataclass
class Material:
    """A soil (or rock) with a strength model and unit weights.

    Parameters
    ----------
    unit_weight:
        Moist/bulk unit weight used above the water table.
    sat_unit_weight:
        Saturated unit weight used below the water table (defaults to
        ``unit_weight`` when not given).
    cohesion, friction_angle:
        Effective-stress parameters ``c'`` and ``phi'`` (degrees).
    su, su_gradient, su_datum:
        Undrained shear strength ``s_u = su + su_gradient * (su_datum - y)``,
        i.e. a strength that grows linearly with depth below ``su_datum``.
        ``su_datum`` defaults to the ground surface directly above the point.
    ru:
        Pore-pressure ratio ``u = ru * sigma_v`` used when no water table
        applies to this material.
    """

    name: str = "Soil"
    unit_weight: float = 19.0
    sat_unit_weight: Optional[float] = None
    strength_model: str = "mohr_coulomb"
    cohesion: float = 0.0
    friction_angle: float = 30.0
    su: float = 0.0
    su_gradient: float = 0.0
    su_datum: Optional[float] = None
    su_min: float = 0.0
    ru: float = 0.0
    color: str = "#C4A883"
    impenetrable: bool = False

    def __post_init__(self) -> None:
        if self.strength_model not in STRENGTH_MODELS:
            raise ValueError(
                f"unknown strength model {self.strength_model!r}; "
                f"expected one of {', '.join(STRENGTH_MODELS)}"
            )
        if self.unit_weight <= 0:
            raise ValueError(f"material {self.name!r}: unit weight must be > 0")
        if not (-1e-9 <= self.friction_angle < 90.0):
            raise ValueError(f"material {self.name!r}: friction angle must be in [0, 90)")

    # -- unit weights ----------------------------------------------------
    def gamma(self, submerged: bool = False) -> float:
        if submerged and self.sat_unit_weight:
            return float(self.sat_unit_weight)
        return float(self.unit_weight)

    # -- strength --------------------------------------------------------
    def strength_params(self, y: float, y_ground: Optional[float] = None) -> Tuple[float, float]:
        """Return ``(c, tan phi)`` for a point at elevation ``y``."""
        if self.strength_model == "mohr_coulomb":
            return self.cohesion, math.tan(math.radians(self.friction_angle))
        if self.strength_model == "undrained":
            datum = self.su_datum if self.su_datum is not None else y_ground
            su = self.su
            if self.su_gradient and datum is not None:
                su += self.su_gradient * max(0.0, datum - y)
            return max(su, self.su_min), 0.0
        if self.strength_model == "no_strength":
            return 0.0, 0.0
        # "infinite": a very large cohesion keeps surfaces out of this material
        # if they are not rejected outright by the search filter.
        return 1.0e9, 0.0

    @property
    def is_undrained(self) -> bool:
        return self.strength_model == "undrained"

    # -- (de)serialisation ------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "unit_weight": self.unit_weight,
            "sat_unit_weight": self.sat_unit_weight,
            "strength_model": self.strength_model,
            "cohesion": self.cohesion,
            "friction_angle": self.friction_angle,
            "su": self.su,
            "su_gradient": self.su_gradient,
            "su_datum": self.su_datum,
            "su_min": self.su_min,
            "ru": self.ru,
            "color": self.color,
            "impenetrable": self.impenetrable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Material":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        # Tolerate the common aliases used by other slope programs.
        aliases = {
            "gamma": "unit_weight",
            "gamma_sat": "sat_unit_weight",
            "c": "cohesion",
            "phi": "friction_angle",
            "cu": "su",
        }
        for alias, target in aliases.items():
            if alias in data and target not in payload:
                payload[target] = data[alias]
        return cls(**payload)
