"""The limit equilibrium solvers, checked against closed-form answers.

The references used here are:

* an infinite slope, where ``FS = tan(phi') / tan(beta)`` exactly;
* a circular arc in a weightless-free phi = 0 soil, where the moment balance
  ``FS = c * L_arc * R / M_driving`` can be integrated directly;
* Taylor's (1937) stability numbers for phi = 0 slopes steeper than 53 deg,
  where the critical mechanism is unambiguously a toe circle;
* the ACADS benchmark problem 1(a), whose published answer is FS = 1.00.
"""

import math
import unittest

from lythosle.analysis import AnalysisOptions, analyze
from lythosle.methods import METHODS, solve_all
from lythosle.model import SlopeModel
from lythosle.slices import build_slices, circular_surface, polyline_surface


def simple_model(**over):
    data = {
        "profile": [[0, 0], [20, 0], [50, 15], [90, 15]],
        "materials": [{"name": "soil", "unit_weight": 19.0,
                       "cohesion": 10.0, "friction_angle": 28.0}],
        "layers": [{"material": "soil"}],
    }
    data.update(over)
    if "layers" not in over:
        data["layers"] = [{"material": data["materials"][0]["name"]}]
    return SlopeModel.from_dict(data).canonical()


class TestClosedForm(unittest.TestCase):
    def test_phi_zero_arc_matches_direct_integration(self):
        su, gamma = 50.0, 19.0
        model = simple_model(materials=[{"name": "c", "unit_weight": gamma,
                                         "strength_model": "undrained", "su": su}])
        xc, yc, r = 40.0, 35.0, 32.0
        surface = circular_surface(model, xc, yc, r, n_points=400)
        self.assertIsNotNone(surface)

        n = 200000
        x_a, x_b = surface.x_left, surface.x_right
        h = (x_b - x_a) / n
        moment = arc = 0.0
        for i in range(n):
            x = x_a + (i + 0.5) * h
            ya = yc - math.sqrt(max(r * r - (x - xc) ** 2, 0.0))
            moment += gamma * (model.ground_y(x) - ya) * (x - xc) * h
            dydx = (x - xc) / math.sqrt(max(r * r - (x - xc) ** 2, 1e-12))
            arc += math.sqrt(1 + dydx * dydx) * h
        exact = su * arc * r / moment

        mass = build_slices(model, surface, 200)
        results = solve_all(mass, ["ordinary", "bishop", "spencer", "morgenstern_price"])
        for name, res in results.items():
            self.assertAlmostEqual(res.fs, exact, delta=0.002,
                                   msg=f"{name} gave {res.fs} against {exact}")

    def test_slice_refinement_converges(self):
        model = simple_model()
        surface = circular_surface(model, 40, 35, 32)
        values = []
        for n in (20, 50, 100, 200):
            mass = build_slices(model, surface, n)
            values.append(solve_all(mass, ["bishop"])["bishop"].fs)
        # monotone convergence: each refinement changes the answer less
        self.assertLess(abs(values[-1] - values[-2]), abs(values[1] - values[0]))
        self.assertAlmostEqual(values[-1], values[-2], delta=0.002)

    def test_infinite_slope(self):
        beta, phi = 20.0, 30.0
        exact = math.tan(math.radians(phi)) / math.tan(math.radians(beta))
        length = 300.0
        model = SlopeModel.from_dict({
            "profile": [[0, 0], [length, length * math.tan(math.radians(beta))]],
            "materials": [{"name": "s", "unit_weight": 20.0,
                           "cohesion": 0.0, "friction_angle": phi}],
            "layers": [{"material": "s"}],
        }).canonical()
        depth, x0, x1 = 2.0, 40.0, 260.0
        pts = [[x0, model.ground_y(x0)], [x0 + 4, model.ground_y(x0 + 4) - depth]]
        xs = [x0 + 4 + i * (x1 - 4 - x0 - 4) / 60 for i in range(1, 61)]
        pts += [[x, model.ground_y(x) - depth] for x in xs]
        pts += [[x1, model.ground_y(x1)]]
        mass = build_slices(model, polyline_surface(model, pts), 200)
        for name in ("bishop", "janbu", "spencer", "morgenstern_price"):
            fs = solve_all(mass, [name])[name].fs
            self.assertAlmostEqual(fs, exact, delta=0.03 * exact, msg=name)


class TestMethodRelationships(unittest.TestCase):
    def setUp(self):
        self.model = simple_model()
        self.mass = build_slices(self.model, circular_surface(self.model, 40, 35, 32), 60)
        self.res = solve_all(self.mass)

    def test_every_method_converges(self):
        for name in METHODS:
            self.assertTrue(self.res[name].ok, f"{name} did not converge")

    def test_ordinary_is_the_most_conservative(self):
        for name in ("bishop", "spencer", "morgenstern_price"):
            self.assertLess(self.res["ordinary"].fs, self.res[name].fs)

    def test_bishop_agrees_with_spencer(self):
        # for a circular surface the two normally sit within a couple of percent
        self.assertAlmostEqual(self.res["bishop"].fs, self.res["spencer"].fs,
                               delta=0.02 * self.res["spencer"].fs)

    def test_morgenstern_price_needs_a_larger_lambda_than_spencer(self):
        # the half-sine function averages less than one, so lambda has to grow
        self.assertGreater(abs(self.res["morgenstern_price"].lam),
                           abs(self.res["spencer"].lam))
        self.assertAlmostEqual(self.res["morgenstern_price"].fs, self.res["spencer"].fs,
                               delta=0.01 * self.res["spencer"].fs)

    def test_janbu_correction_raises_the_force_solution(self):
        self.assertGreater(self.res["janbu_corrected"].fs, self.res["janbu"].fs)

    def test_lambda_is_positive_for_a_normal_slope(self):
        self.assertGreater(self.res["spencer"].lam, 0.0)


class TestLoadingEffects(unittest.TestCase):
    def fs(self, **over):
        model = simple_model(**over)
        mass = build_slices(model, circular_surface(model, 40, 35, 32), 50)
        return solve_all(mass, ["bishop"])["bishop"].fs

    def test_water_table_lowers_the_factor_of_safety(self):
        dry = self.fs()
        wet = self.fs(water_table=[[0, 2], [90, 12]])
        self.assertLess(wet, dry)

    def test_ru_lowers_the_factor_of_safety(self):
        dry = self.fs()
        ru = self.fs(materials=[{"name": "soil", "unit_weight": 19.0, "cohesion": 10.0,
                                 "friction_angle": 28.0, "ru": 0.3}])
        self.assertLess(ru, dry)

    def test_seismic_loading_lowers_the_factor_of_safety(self):
        self.assertLess(self.fs(seismic={"kh": 0.15}), self.fs())

    def test_surcharge_on_the_crest_lowers_the_factor_of_safety(self):
        self.assertLess(self.fs(surcharges=[{"x1": 50, "x2": 90, "pressure": 50}]),
                        self.fs())

    def test_reinforcement_raises_the_factor_of_safety(self):
        plain = self.fs()
        held = self.fs(supports=[{"name": "nail", "x1": 30, "y1": 6,
                                  "x2": 48, "y2": 2, "capacity": 300}])
        self.assertGreater(held, plain)

    def test_tension_crack_lowers_the_factor_of_safety(self):
        model = simple_model(tension_crack={"enabled": True, "depth": 3.0, "water_fill": 1.0})
        surface = circular_surface(model, 40, 35, 32)
        mass = build_slices(model, surface, 50)
        self.assertGreater(mass.crack_depth, 0.0)
        self.assertGreater(mass.crack_force, 0.0)
        self.assertLess(solve_all(mass, ["bishop"])["bishop"].fs, self.fs())

    def test_mirrored_geometry_gives_the_same_answer(self):
        forward = SlopeModel.from_dict({
            "profile": [[0, 0], [20, 0], [50, 15], [90, 15]],
            "materials": [{"name": "s", "unit_weight": 19.0, "cohesion": 10.0,
                           "friction_angle": 28.0}],
            "layers": [{"material": "s"}],
            "water_table": [[0, 2], [90, 12]],
        })
        backward = SlopeModel.from_dict({
            "profile": [[0, 15], [40, 15], [70, 0], [90, 0]],
            "materials": [{"name": "s", "unit_weight": 19.0, "cohesion": 10.0,
                           "friction_angle": 28.0}],
            "layers": [{"material": "s"}],
            "water_table": [[0, 12], [90, 2]],
        })
        opts = AnalysisOptions.from_dict(
            {"methods": ["bishop", "spencer"], "n_slices": 50,
             "search": {"nx": 10, "ny": 10, "n_tangent": 10, "refine_passes": 3}})
        a = analyze(forward, opts)
        b = analyze(backward, opts)
        self.assertAlmostEqual(a.critical_fs, b.critical_fs, delta=0.01)
        self.assertAlmostEqual(a.results["spencer"].lam, b.results["spencer"].lam, delta=0.05)


class TestPublishedBenchmarks(unittest.TestCase):
    def test_acads_problem_1a(self):
        """H = 10 m, 2H:1V, c' = 3 kPa, phi' = 19.6 deg, gamma = 20: FS = 1.00."""
        model = SlopeModel.from_dict({
            "profile": [[0, 0], [10, 0], [30, 10], [50, 10]],
            "materials": [{"name": "soil", "unit_weight": 20.0,
                           "cohesion": 3.0, "friction_angle": 19.6}],
            "layers": [{"material": "soil"}],
        })
        result = analyze(model, AnalysisOptions.from_dict({
            "methods": ["bishop", "spencer"], "n_slices": 60,
            "search": {"nx": 16, "ny": 16, "n_tangent": 16, "refine_passes": 4}}))
        self.assertAlmostEqual(result.results["bishop"].fs, 1.00, delta=0.03)
        self.assertAlmostEqual(result.results["spencer"].fs, 1.00, delta=0.03)

    def test_taylor_stability_numbers(self):
        """N = c / (gamma H F) for phi = 0 with a firm base at the toe."""
        taylor = {75: 0.219, 60: 0.191, 53: 0.181}
        height, gamma, su = 10.0, 20.0, 50.0
        for beta, number in taylor.items():
            run = height / math.tan(math.radians(beta))
            model = SlopeModel.from_dict({
                "profile": [[0, 0], [20, 0], [20 + run, height], [20 + run + 25, height]],
                "materials": [
                    {"name": "clay", "unit_weight": gamma,
                     "strength_model": "undrained", "su": su},
                    {"name": "rock", "unit_weight": 24.0, "strength_model": "infinite",
                     "impenetrable": True}],
                "layers": [{"material": "clay"},
                           {"material": "rock", "boundary": [[0, 0], [100, 0]]}],
            })
            result = analyze(model, AnalysisOptions.from_dict({
                "methods": ["bishop"], "n_slices": 60,
                "search": {"nx": 16, "ny": 16, "n_tangent": 14, "refine_passes": 4}}))
            expected = su / (gamma * height * number)
            self.assertAlmostEqual(result.critical_fs, expected, delta=0.03 * expected,
                                   msg=f"beta = {beta} deg")


if __name__ == "__main__":
    unittest.main()
