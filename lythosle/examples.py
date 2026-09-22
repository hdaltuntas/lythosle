"""Ready-made models used by the demo, the CLI and the browser front end."""

from __future__ import annotations

from typing import Any, Dict, List


def _slope_profile(toe_x: float, toe_y: float, height: float, ratio: float,
                   toe_run: float = 15.0, crest_run: float = 20.0) -> List[List[float]]:
    """A single planar face: ``ratio`` is horizontal per unit vertical."""
    x0 = toe_x - toe_run
    x1 = toe_x
    x2 = toe_x + ratio * height
    x3 = x2 + crest_run
    return [[x0, toe_y], [x1, toe_y], [x2, toe_y + height], [x3, toe_y + height]]


EXAMPLES: Dict[str, Dict[str, Any]] = {}


def _add(key: str, title: str, description: str, model: Dict[str, Any],
         options: Dict[str, Any]) -> None:
    EXAMPLES[key] = {"key": key, "title": title, "description": description,
                     "model": model, "options": options}


# 1 -------------------------------------------------------------------
_add(
    "homogeneous",
    "Homogeneous slope (ACADS 1a)",
    "10 m high 2H:1V embankment, c' = 3 kPa, phi' = 19.6 deg, dry. "
    "The published reference factor of safety is 1.00.",
    {
        "name": "Homogeneous slope",
        "units": "metric",
        "profile": _slope_profile(10, 0, 10, 2.0, 10, 20),
        "materials": [{"name": "Embankment fill", "unit_weight": 20.0,
                       "cohesion": 3.0, "friction_angle": 19.6, "color": "#C4A883"}],
        "layers": [{"material": "Embankment fill"}],
    },
    {"methods": ["ordinary", "bishop", "janbu_corrected", "spencer", "morgenstern_price"],
     "n_slices": 50,
     "search": {"mode": "auto", "method": "bishop", "nx": 14, "ny": 14,
                "n_tangent": 14, "refine_passes": 3}},
)

# 2 -------------------------------------------------------------------
_add(
    "layered_water",
    "Layered slope with a water table",
    "A 15 m cut through weathered fill over stiff clay and dense sand, with a "
    "phreatic surface that daylights on the slope face.",
    {
        "name": "Layered slope with groundwater",
        "units": "metric",
        "profile": [[0, 0], [18, 0], [48, 15], [75, 15]],
        "materials": [
            {"name": "Weathered fill", "unit_weight": 18.0, "sat_unit_weight": 19.5,
             "cohesion": 5.0, "friction_angle": 26.0, "color": "#C4A883"},
            {"name": "Stiff clay", "unit_weight": 19.0, "sat_unit_weight": 20.0,
             "cohesion": 15.0, "friction_angle": 22.0, "color": "#9B8AA6"},
            {"name": "Dense sand", "unit_weight": 20.0, "sat_unit_weight": 21.0,
             "cohesion": 0.0, "friction_angle": 36.0, "color": "#B5A642"},
        ],
        "layers": [
            {"material": "Weathered fill"},
            {"material": "Stiff clay", "boundary": [[0, -4], [18, -4], [48, 7], [75, 7]]},
            {"material": "Dense sand", "boundary": [[0, -12], [75, -6]]},
        ],
        "water_table": [[0, -2.0], [18, -1.5], [30, 3.5], [48, 9.0], [75, 9.5]],
    },
    {"methods": ["ordinary", "bishop", "janbu_corrected", "spencer", "morgenstern_price"],
     "n_slices": 60,
     "search": {"mode": "auto", "method": "bishop", "nx": 14, "ny": 14,
                "n_tangent": 14, "refine_passes": 3}},
)

# 3 -------------------------------------------------------------------
_add(
    "soft_foundation",
    "Embankment on soft clay",
    "A 6 m embankment built on normally consolidated clay whose undrained "
    "strength grows with depth (su = 12 + 1.8 z kPa). End-of-construction case.",
    {
        "name": "Embankment on soft clay",
        "units": "metric",
        "profile": [[0, 0], [12, 0], [24, 6], [44, 6], [56, 0], [70, 0]],
        "materials": [
            {"name": "Granular fill", "unit_weight": 20.0, "sat_unit_weight": 21.0,
             "cohesion": 0.0, "friction_angle": 34.0, "color": "#C4A883"},
            {"name": "Soft clay", "unit_weight": 16.5, "sat_unit_weight": 16.5,
             "strength_model": "undrained", "su": 12.0, "su_gradient": 1.8,
             "su_datum": 0.0, "color": "#7EA89B"},
            {"name": "Firm base", "unit_weight": 21.0, "strength_model": "infinite",
             "impenetrable": True, "color": "#8C8C8C"},
        ],
        "layers": [
            {"material": "Granular fill"},
            {"material": "Soft clay", "boundary": [[0, 0], [70, 0]]},
            {"material": "Firm base", "boundary": [[0, -12], [70, -12]]},
        ],
        "water_table": [[0, 0], [70, 0]],
    },
    {"methods": ["ordinary", "bishop", "janbu_corrected", "spencer"],
     "n_slices": 60,
     "search": {"mode": "auto", "method": "bishop", "nx": 16, "ny": 14,
                "n_tangent": 16, "refine_passes": 3}},
)

# 4 -------------------------------------------------------------------
_add(
    "seismic",
    "Pseudo-static (seismic) case",
    "The layered slope again, with a horizontal seismic coefficient "
    "kh = 0.15 and a road surcharge of 20 kPa on the crest.",
    {
        "name": "Pseudo-static analysis",
        "units": "metric",
        "profile": [[0, 0], [18, 0], [42, 12], [70, 12]],
        "materials": [
            {"name": "Colluvium", "unit_weight": 19.0, "sat_unit_weight": 20.0,
             "cohesion": 8.0, "friction_angle": 28.0, "color": "#C4A883"},
            {"name": "Residual soil", "unit_weight": 20.0, "sat_unit_weight": 21.0,
             "cohesion": 20.0, "friction_angle": 30.0, "color": "#9B8AA6"},
        ],
        "layers": [
            {"material": "Colluvium"},
            {"material": "Residual soil", "boundary": [[0, -6], [18, -6], [42, 4], [70, 4]]},
        ],
        "water_table": [[0, -3], [18, -2], [42, 5], [70, 6]],
        "seismic": {"kh": 0.15, "kv": 0.0},
        "surcharges": [{"x1": 44, "x2": 62, "pressure": 20.0, "include_in_seismic": True}],
    },
    {"methods": ["bishop", "janbu_corrected", "spencer", "morgenstern_price"],
     "n_slices": 60,
     "search": {"mode": "auto", "method": "bishop", "nx": 14, "ny": 14,
                "n_tangent": 14, "refine_passes": 3}},
)

# 5 -------------------------------------------------------------------
_add(
    "reinforced",
    "Soil-nailed cut",
    "A steep 9 m cut in silty sand over rock, held by four rows of soil nails "
    "that each provide 40 kN/m of design tensile resistance.",
    {
        "name": "Soil-nailed cut",
        "units": "metric",
        "profile": [[0, 0], [12, 0], [24, 9], [46, 9]],
        "materials": [
            {"name": "Silty sand", "unit_weight": 19.0, "cohesion": 5.0,
             "friction_angle": 32.0, "color": "#C4A883"},
            {"name": "Rock", "unit_weight": 24.0, "strength_model": "infinite",
             "impenetrable": True, "color": "#8C8C8C"},
        ],
        "layers": [
            {"material": "Silty sand"},
            {"material": "Rock", "boundary": [[0, -0.5], [46, -0.5]]},
        ],
        "supports": [
            {"name": "Nail 1", "x1": 14.0, "y1": 1.5, "x2": 28.0, "y2": -0.2, "capacity": 40.0},
            {"name": "Nail 2", "x1": 17.0, "y1": 3.8, "x2": 31.0, "y2": 1.3, "capacity": 40.0},
            {"name": "Nail 3", "x1": 20.0, "y1": 6.0, "x2": 34.0, "y2": 3.5, "capacity": 40.0},
            {"name": "Nail 4", "x1": 22.5, "y1": 8.0, "x2": 36.5, "y2": 5.5, "capacity": 40.0},
        ],
    },
    {"methods": ["bishop", "janbu_corrected", "spencer"],
     "n_slices": 50,
     "search": {"mode": "auto", "method": "bishop", "nx": 14, "ny": 14,
                "n_tangent": 14, "refine_passes": 3}},
)

# 6 -------------------------------------------------------------------
_add(
    "tension_crack",
    "Clay cutting with a tension crack",
    "A 12 m cutting in stiff clay (su = 60 kPa) with a water-filled tension "
    "crack at the crest and a non-circular surface optimisation.",
    {
        "name": "Clay cutting with tension crack",
        "units": "metric",
        "profile": [[0, 0], [14, 0], [32, 12], [58, 12]],
        "materials": [
            {"name": "Stiff clay", "unit_weight": 19.5, "sat_unit_weight": 20.0,
             "strength_model": "undrained", "su": 60.0, "color": "#9B8AA6"},
        ],
        "layers": [{"material": "Stiff clay"}],
        "water_table": [[0, -1], [14, -1], [32, 6], [58, 7]],
        "tension_crack": {"enabled": True, "depth": 3.0, "water_fill": 1.0},
    },
    {"methods": ["ordinary", "bishop", "spencer", "morgenstern_price"],
     "n_slices": 50,
     "search": {"mode": "auto", "method": "bishop", "nx": 14, "ny": 14,
                "n_tangent": 14, "refine_passes": 3, "optimize": True,
                "optimize_vertices": 20, "optimize_passes": 30}},
)


def list_examples() -> List[Dict[str, str]]:
    return [{"key": e["key"], "title": e["title"], "description": e["description"]}
            for e in EXAMPLES.values()]


def get_example(key: str) -> Dict[str, Any]:
    try:
        return EXAMPLES[key]
    except KeyError:
        raise KeyError(f"unknown example {key!r}; available: {', '.join(EXAMPLES)}")
