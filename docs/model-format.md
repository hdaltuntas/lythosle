# Model and options format

Both the CLI and the HTTP API take the same two objects. A file produced by the
browser's **Download** button looks like

```json
{ "model": { ... }, "options": { ... } }
```

`lythosle analyze` accepts either that wrapper or a bare model.

Units are whatever consistent set you work in; `"units"` only selects the
default unit weight of water (9.81 metric, 62.4 imperial) and the labels shown
in the interface.

## model

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | `"Slope"` | label used in reports |
| `units` | `"metric"` \| `"imperial"` | `"metric"` | see above |
| `profile` | `[[x, y], ...]` | required | ground surface, single valued in `x`. Order does not matter |
| `materials` | list of material objects | required | see below |
| `layers` | list of layer objects | one layer of the first material | top down; see below |
| `water_table` | `[[x, y], ...]` or `null` | `null` | piezometric line |
| `water_unit_weight` | number | 9.81 / 62.4 | unit weight of water |
| `seismic` | `{"kh": 0, "kv": 0}` | zero | pseudo-static coefficients, `kh` acts down-slope, `kv` downwards |
| `surcharges` | list | `[]` | `{"x1", "x2", "pressure", "include_in_seismic"}` |
| `supports` | list | `[]` | `{"name", "x1", "y1", "x2", "y2", "capacity"}`, head first, anchor second |
| `tension_crack` | object | disabled | `{"enabled", "depth", "auto", "water_fill"}` |

### material

| Key | Default | Meaning |
|---|---|---|
| `name` | `"Soil"` | referenced by layers |
| `unit_weight` | 19 | bulk unit weight above the water table |
| `sat_unit_weight` | = `unit_weight` | used below the water table |
| `strength_model` | `"mohr_coulomb"` | `"mohr_coulomb"`, `"undrained"`, `"infinite"`, `"no_strength"` |
| `cohesion`, `friction_angle` | 0, 30 | `c'` and `phi'` in degrees, for `mohr_coulomb` |
| `su`, `su_gradient`, `su_datum`, `su_min` | 0, 0, ground surface, 0 | undrained strength `su + su_gradient * (su_datum − y)` |
| `ru` | 0 | pore pressure ratio; overrides the water table for this material |
| `color` | palette | used in the drawing |
| `impenetrable` | `false` | slip surfaces may not enter this material |

`c`, `phi`, `gamma`, `gamma_sat` and `cu` are accepted as aliases.

### layer

```json
{"material": "Clay", "boundary": [[0, -4], [75, 7]]}
```

Layers are ordered from the top down. The first layer's boundary is always the
ground surface and may be omitted; every layer below it needs one. A boundary
is extended horizontally beyond its first and last point. The material at a
point is the lowest layer whose boundary is still above that point.

## options

| Key | Default | Meaning |
|---|---|---|
| `methods` | ordinary, bishop, janbu_corrected, spencer, morgenstern_price | any of `ordinary`, `bishop`, `janbu`, `janbu_corrected`, `corps_engineers`, `lowe_karafiath`, `spencer`, `morgenstern_price` |
| `n_slices` | 50 | slices in the final analysis (maximum 500) |
| `force_function` | `"half_sine"` | `half_sine`, `constant` or `trapezoidal`, for Morgenstern-Price |
| `direction` | `"auto"` | `"left"` or `"right"`: which way the mass slides. `auto` takes it from the profile |
| `search_each_method` | `false` | repeat the whole search for every method instead of reporting them all on one surface |
| `include_slice_table` | `true` | include the per-slice results |
| `search` | see below | |

### options.search

| Key | Default | Meaning |
|---|---|---|
| `mode` | `"auto"` | `auto`, `grid`, `single` (with `circle`) or `polyline` (with `polyline`) |
| `method` | `"bishop"` | method used to rank trial surfaces and to report the critical one |
| `n_slices` | 25 | slices used while searching |
| `nx`, `ny` | 12, 12 | grid of circle centres |
| `radius_mode` | `"tangent"` | `tangent` (radii from tangent elevations) or `range` |
| `n_tangent`, `n_radius` | 12 | levels per centre |
| `center_x`, `center_y`, `tangent_y`, `radius` | derived from the geometry | `[from, to]` pairs; set them to pin the box down |
| `refine_passes` | 3 | local refinements around the best centre |
| `limits` | none | `{"exit_min", "exit_max", "entry_min", "entry_max", "min_depth", "max_depth", "min_weight"}` |
| `circle` | | `[xc, yc, radius]` for `mode: "single"` |
| `polyline` | | `[[x, y], ...]` for `mode: "polyline"` |
| `optimize` | `false` | refine the critical circle into a non-circular surface |
| `optimize_vertices`, `optimize_passes`, `optimize_method` | 20, 40, `"spencer"` | optimisation controls |

## HTTP API

| Route | |
|---|---|
| `GET /api/health` | version check |
| `GET /api/methods` | the method list with labels and equilibrium conditions |
| `GET /api/examples` | the built-in examples |
| `GET /api/examples/{key}` | one example, as `{model, options}` |
| `POST /api/analyze` | body `{model, options}`, returns the result below |

### result

```jsonc
{
  "ok": true,
  "critical_fs": 0.985,
  "primary_method": "bishop",
  "methods": [{"method": "bishop", "label": "Bishop simplified", "fs": 0.985,
               "equilibrium": "moment", "lambda": null, "iterations": 10,
               "converged": true, "notes": [],
               "lambda_plot": [{"lambda": -0.6, "fm": 1.02, "ff": 0.88}, ...]}],
  "surface": {"kind": "circular", "xc": 9.4, "yc": 29.5, "radius": 29.5,
              "points": [[x, y], ...]},
  "mass": {"weight": 898.0, "n_slices": 50, "crack_depth": 0.0, "supports": []},
  "search": {"evaluated": 3773, "rejected": 1884, "grid": [{"x": ..., "y": ..., "fs": ...}]},
  "slices": [{"index": 1, "x": 10.2, "width": 0.43, "alpha_deg": 2.1,
              "weight": 0.8, "u": 0.0, "normal_stress": 1.8,
              "shear_strength": 3.7, "shear_mobilised": 3.7, ...}],
  "geometry": {"height": 10.0, "angle": 26.6, "x_toe": 10.0, "x_crest": 30.0},
  "render": { "...": "polygons, water table, slices and search grid for drawing" },
  "notes": ["..."],
  "runtime_s": 1.26
}
```

All coordinates in the result are in the user's frame, whichever way the slope
was drawn.
