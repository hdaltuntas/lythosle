# Formulation

This is what Lythos LE actually computes. It is written so that a reviewer can
check the numbers by hand.

## 1. Coordinates and sign conventions

`x` increases to the right and `y` is elevation. Internally the solver works in
a **canonical frame in which the crest is on the right and the sliding mass
moves towards −x**. A model drawn the other way round is mirrored (`x → −x`) on
input and every result is mirrored back, so the user never sees the internal
frame. `"direction"` in the analysis options forces the choice for geometries
that are ambiguous, such as a two-sided embankment.

For each slice:

| Symbol | Meaning |
|---|---|
| `b`, `l` | slice width and base length, `l = b / cos α` |
| `α` | base inclination from the +x axis, measured on the chord between the two base corners. Positive under the crest, negative near the toe |
| `W` | total slice weight, including surcharge and any ponded water above the ground surface |
| `u` | pore water pressure at the mid-point of the base |
| `c`, `φ` | strength parameters of the material immediately **below** the base |
| `N` | total normal force on the base |
| `S_m` | mobilised shear on the base, `S_m = (c l + (N − u l) tan φ) / F` |
| `E`, `X` | horizontal and vertical interslice forces, both counted as the force exerted by the material on the left of a boundary on the material to its right, `E` positive in compression and `X` positive upwards |

Driving quantities are counted positive. For a circular surface the driving
moment of the weights about the centre of rotation is `Σ W (x_base − x_centre)`
and the driving horizontal force is `Σ N sin α + Σ k_h W`.

## 2. Slice equilibrium

Vertical equilibrium of a slice, with the vertical seismic coefficient `k_v`
acting downwards:

```
N cos α + S_m sin α = W (1 + k_v) + (X_right − X_left)
```

Substituting the Mohr-Coulomb shear and solving for `N`:

```
N = [ W (1 + k_v) + (X_right − X_left) − (c l − u l tan φ) sin α / F ] / m_α
m_α = cos α + sin α tan φ / F
```

`m_α` below 0.2 is reported as poorly conditioned; below 0.02 it is clamped so a
single bad slice cannot produce a meaningless factor of safety. The effective
normal force `N − u l` is clipped at zero, which is the usual treatment of
tensile slices.

Horizontal equilibrium of the same slice gives the interslice normal force by
recursion from `E = 0` at the toe end:

```
E_{i+1} = E_i − N sin α + S_m cos α − k_h W + Q_x,i
```

where `Q_x,i` is any external horizontal point force applied within that slice
(reinforcement, water thrust in a tension crack). The interslice shear follows
the assumed force function,

```
X_i = λ f(x_i) E_i ,   X = 0 at both ends
```

with `f(x) = 1` for Spencer and a half sine, constant or trapezoid for
Morgenstern-Price. `f(x)` is fixed at the chord inclination for Corps of
Engineers #1 and at the average of ground and base inclination for
Lowe-Karafiath, both with `λ = 1`.

## 3. Factor of safety

**Moment equilibrium** about the axis `(x_O, y_O)`:

```
F_m = Σ S_avail ρ / [ Σ M_driving + M_external − Σ N γ ]

ρ = (x_b − x_O) sin α − (y_b − y_O) cos α          ( = R for a circle )
γ = (x_b − x_O) cos α + (y_b − y_O) sin α          ( = 0 for a circle )
M_driving = W (1 + k_v)(x_b − x_O) + k_h W (y_O − y_cg)
S_avail = c l + (N − u l) tan φ
```

For a circular surface the base shear acts at radius `R` and the normal force
passes through the centre, so this reduces to the familiar
`F = Σ S_avail R / Σ W (x_b − x_c)`. For a non-circular surface the axis is the
centre of the circle fitted through the first, middle and last points of the
surface, and the result **depends on that choice** unless force equilibrium is
also satisfied — which is why Spencer or Morgenstern-Price should be used there.

**Horizontal force equilibrium** of the whole mass:

```
F_f = Σ S_avail cos α / [ Σ N sin α + Σ k_h W − Q_x ]
```

Both are solved by fixed-point iteration with under-relaxation, starting from
the factor of safety found during the search.

**Spencer and Morgenstern-Price** solve both at once. For a trial `λ` the
interslice forces are iterated to convergence and `F_m(λ)` and `F_f(λ)` are
computed; `λ` is then found by bisection on `F_m − F_f`, seeded by a scan over
`λ ∈ [−0.6, 1.4]`. Repeated evaluations (during surface optimisation) use a
secant iteration warm-started from the previous `λ`. If the two curves never
cross, there is no Spencer solution and Lythos LE says so instead of reporting a
number.

**Ordinary / Fellenius** ignores interslice forces completely and resolves the
weight (and seismic force) perpendicular to the base:

```
N = W (1 + k_v) cos α − k_h W sin α
```

**Janbu corrected** multiplies the simplified force solution by

```
f0 = 1 + b1 [ d/L − 1.4 (d/L)² ]
```

with `d` the maximum depth of the surface below its chord, `L` the chord length,
and `b1` = 0.69 for `φ = 0`, 0.31 for `c = 0` and 0.50 for `c-φ` soils.

## 4. Weights, water and loads

The weight of a slice is integrated as a column at the slice mid-point: the
column is split at every material boundary and at the water table, and each
piece uses the saturated unit weight when it lies below the water table and the
bulk unit weight above it. Surcharge pressure over the slice width is added to
the weight, and so is any water standing above the ground surface.

Pore pressure at the base is `u = γ_w (y_water − y_base)` from the piezometric
line, or `u = r_u σ_v` when the material carries a pore pressure ratio, with
`σ_v` the total vertical stress of the column above the point. `r_u` takes
precedence over the water table for that material.

Seismic loading is pseudo-static: a horizontal inertia force `k_h W` acting
down-slope and a vertical force `k_v W` acting downwards. Surcharges only
contribute inertia when `"include_in_seismic"` is set.

A tension crack truncates the crest end of the surface at the depth given, or at
`z = (2c/γ) tan(45° + φ/2)` when `"auto"` is set. Water in the crack applies a
horizontal thrust `½ γ_w h_w²` at one third of the water depth above the base of
the crack, in the driving direction.

Reinforcement applies its capacity as a force at the point where the slip
surface crosses the element, directed along the element towards whichever end
lies outside the sliding mass. The force enters the slice it acts in, the global
force balance and the moment balance.

## 5. Searching for the critical surface

The default search is grid-and-tangent: circle centres are taken from a
rectangular grid above the slope, and each centre is combined with a set of
tangent elevations to give the radii. A trial circle is rejected when it does
not daylight at both ends, when the arc rises above the ground surface between
its ends, when it enters an impenetrable material, when it is shallower than the
minimum depth, or when the chosen method does not converge on it. Where a circle
cuts the ground more than twice — a benched slope — the largest valid arc is
used.

The box adapts: if the best trial of a pass sits on the edge of the grid or at
the extreme tangent elevation, that side is extended and the pass repeats, up to
three times. This is what finds the deep foundation failures of an embankment
on soft clay without the user setting anything. The grid is then refined around
the best centre and tangent for a few passes, each pass covering one cell of the
previous one.

Searching is done with a single method (Bishop by default, 25 slices) and every
requested method is then evaluated on the resulting critical surface; the report
says so. `"search_each_method": true` repeats the whole search for each method
instead.

**Non-circular optimisation** starts from the critical circle, resamples it to
20 vertices, and moves each vertex in turn — interior vertices vertically, the
two ends along the ground surface — keeping any move that lowers the factor of
safety. The step halves when a pass makes no progress. Trials are ranked with
Spencer, warm-started from the previous `λ`, because ranking non-circular
surfaces with a moment-only method just walks the surface towards whatever
moment axis flatters it.

A trial surface must stay below the ground and above any impenetrable material,
its segments must be flatter than 80°, and its base inclination must increase
monotonically from toe to crest (concave upwards). Without that last condition
the optimiser invents zig-zag surfaces with a meaningless low factor of safety.
The optimised surface is reported only if it beats the circular one on the same
basis.

## 6. Numerical defaults

| | |
|---|---|
| Slices for the final analysis | 50 (boundaries are placed at every profile vertex, material boundary, water-table vertex and surcharge edge first, then the remaining width is divided evenly) |
| Slices during the search | 25 |
| Iteration tolerance on `F` | 1e-6 relative, 80 iterations, relaxation 0.6 |
| `λ` scan | 15 points over [−0.6, 1.4], then bisection to 1e-5 |
| Search grid | 12 × 12 centres × 12 tangents, 3 refinement passes |

## References

Bishop, A. W. (1955). The use of the slip circle in the stability analysis of
slopes. *Géotechnique* 5(1), 7-17.

Fellenius, W. (1936). Calculation of the stability of earth dams.
*Transactions, 2nd Congress on Large Dams*, Washington DC.

Fredlund, D. G. and Krahn, J. (1977). Comparison of slope stability methods of
analysis. *Canadian Geotechnical Journal* 14(3), 429-439.

Janbu, N. (1973). Slope stability computations. In *Embankment Dam
Engineering*, Casagrande Volume, Wiley.

Krahn, J. (2003). The 2001 R. M. Hardy Lecture: The limits of limit equilibrium
analyses. *Canadian Geotechnical Journal* 40(3), 643-660.

Morgenstern, N. R. and Price, V. E. (1965). The analysis of the stability of
general slip surfaces. *Géotechnique* 15(1), 79-93.

Spencer, E. (1967). A method of analysis of the stability of embankments
assuming parallel inter-slice forces. *Géotechnique* 17(1), 11-26.

Taylor, D. W. (1937). Stability of earth slopes. *Journal of the Boston Society
of Civil Engineers* 24, 197-246.
