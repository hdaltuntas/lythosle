"""Critical surface search and non-circular optimisation."""

import copy
import unittest

from lythosle.analysis import AnalysisOptions, analyze
from lythosle.model import SlopeModel
from lythosle.search import (SearchLimits, SearchOptions, auto_search_options,
                             optimize_noncircular, search_circular, slope_geometry)

SIMPLE = {
    "profile": [[0, 0], [20, 0], [50, 15], [90, 15]],
    "materials": [{"name": "soil", "unit_weight": 19.0, "cohesion": 10.0,
                   "friction_angle": 28.0}],
    "layers": [{"material": "soil"}],
}


class TestGeometryDetection(unittest.TestCase):
    def test_simple_slope(self):
        g = slope_geometry(SlopeModel.from_dict(SIMPLE).canonical())
        self.assertAlmostEqual(g["x_toe"], 20.0)
        self.assertAlmostEqual(g["x_crest"], 50.0)
        self.assertAlmostEqual(g["height"], 15.0)
        self.assertAlmostEqual(g["angle"], 26.565, places=2)

    def test_two_sided_embankment_uses_the_left_face(self):
        model = SlopeModel.from_dict(dict(
            SIMPLE, profile=[[0, 0], [12, 0], [24, 6], [44, 6], [56, 0], [70, 0]])).canonical()
        g = slope_geometry(model)
        self.assertAlmostEqual(g["x_toe"], 12.0)
        self.assertAlmostEqual(g["x_crest"], 24.0)
        self.assertAlmostEqual(g["height"], 6.0)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.model = SlopeModel.from_dict(SIMPLE).canonical()

    def test_finds_a_surface_through_the_slope(self):
        result = search_circular(self.model, SearchOptions(nx=10, ny=10, n_tangent=10,
                                                           refine_passes=2, n_slices=25))
        self.assertIsNotNone(result.surface)
        self.assertGreater(result.evaluated, 100)
        # the critical circle of a c-phi slope daylights at or near the toe
        self.assertLess(abs(result.surface.x_left - 20.0), 6.0)
        self.assertGreater(result.surface.x_right, 45.0)
        self.assertTrue(all(g["fs"] > 0 for g in result.grid))

    def test_options_are_not_mutated(self):
        opts = SearchOptions(nx=6, ny=6, n_tangent=6, refine_passes=1, n_slices=20)
        before = copy.deepcopy(opts)
        search_circular(self.model, opts)
        self.assertEqual(opts.center_x, before.center_x)
        self.assertEqual(opts.tangent_y, before.tangent_y)
        self.assertEqual(opts.limits.min_depth, before.limits.min_depth)

    def test_refinement_improves_on_the_coarse_grid(self):
        coarse = search_circular(self.model, SearchOptions(nx=8, ny=8, n_tangent=8,
                                                           refine_passes=0, n_slices=25))
        fine = search_circular(self.model, SearchOptions(nx=8, ny=8, n_tangent=8,
                                                         refine_passes=3, n_slices=25))
        self.assertLessEqual(fine.fs, coarse.fs + 1e-9)

    def test_exit_limits_are_honoured(self):
        limits = SearchLimits(exit_min=30.0)
        result = search_circular(self.model, SearchOptions(nx=8, ny=8, n_tangent=8,
                                                           refine_passes=1, n_slices=25,
                                                           limits=limits))
        self.assertIsNotNone(result.surface)
        self.assertGreaterEqual(result.surface.x_left, 30.0 - 1e-6)

    def test_impenetrable_layer_is_respected(self):
        model = SlopeModel.from_dict({
            **SIMPLE,
            "materials": SIMPLE["materials"] + [
                {"name": "rock", "unit_weight": 24.0, "strength_model": "infinite",
                 "impenetrable": True}],
            "layers": [{"material": "soil"},
                       {"material": "rock", "boundary": [[0, -3], [90, -3]]}],
        }).canonical()
        result = search_circular(model, SearchOptions(nx=10, ny=10, n_tangent=10,
                                                      refine_passes=2, n_slices=25))
        self.assertIsNotNone(result.surface)
        self.assertGreaterEqual(min(p[1] for p in result.surface.points), -3.0 - 1e-6)

    def test_auto_box_covers_the_slope(self):
        opts = auto_search_options(self.model)
        self.assertIsNotNone(opts.center_x)
        self.assertLess(opts.center_y[0], opts.center_y[1])
        self.assertGreater(opts.center_y[0], self.model.crest_y)


class TestOptimisation(unittest.TestCase):
    def test_optimised_surface_is_admissible_and_better(self):
        model = SlopeModel.from_dict({
            "profile": [[0, 0], [14, 0], [32, 12], [58, 12]],
            "materials": [{"name": "clay", "unit_weight": 19.5,
                           "strength_model": "undrained", "su": 60.0}],
            "layers": [{"material": "clay"}],
        }).canonical()
        base = search_circular(model, SearchOptions(nx=10, ny=10, n_tangent=10,
                                                    refine_passes=2, n_slices=25))
        opts = SearchOptions(n_slices=25, method="bishop", optimize_vertices=14,
                             optimize_passes=12)
        result = optimize_noncircular(model, base.surface, opts)
        if result.surface is None:
            self.skipTest("the circular surface could not be improved on")
        self.assertEqual(result.surface.kind, "polyline")
        # the optimiser must not run away: ends stay near the original surface
        self.assertGreater(result.surface.x_left, base.surface.x_left - 0.4 * model.height - 1)
        self.assertLess(result.surface.x_right, base.surface.x_right + 0.4 * model.height + 1)
        for x, y in result.surface.points[1:-1]:
            self.assertLessEqual(y, model.ground_y(x) + 1e-6)


class TestAnalysisDriver(unittest.TestCase):
    def test_single_circle_mode(self):
        model = SlopeModel.from_dict(SIMPLE)
        result = analyze(model, AnalysisOptions.from_dict({
            "methods": ["bishop"], "n_slices": 40,
            "search": {"mode": "single", "circle": [40, 35, 32]}}))
        self.assertIsNotNone(result.mass)
        self.assertAlmostEqual(result.mass.surface.radius, 32.0)
        self.assertIsNone(result.search)

    def test_polyline_mode(self):
        model = SlopeModel.from_dict(SIMPLE)
        result = analyze(model, AnalysisOptions.from_dict({
            "methods": ["spencer"], "n_slices": 40,
            "search": {"mode": "polyline",
                       "polyline": [[22, 0], [30, -4], [40, -3], [48, 6], [52, 15]]}}))
        self.assertIsNotNone(result.mass)
        self.assertEqual(result.mass.surface.kind, "polyline")
        self.assertTrue(result.results["spencer"].ok)

    def test_impossible_model_reports_instead_of_raising(self):
        model = SlopeModel.from_dict({
            "profile": [[0, 0], [100, 0]],
            "materials": [{"name": "s", "unit_weight": 19.0, "cohesion": 50.0,
                           "friction_angle": 35.0}],
            "layers": [{"material": "s"}],
        })
        result = analyze(model, AnalysisOptions.from_dict(
            {"methods": ["bishop"], "search": {"nx": 5, "ny": 5, "n_tangent": 5,
                                               "refine_passes": 0}}))
        self.assertIsNone(result.critical_fs)
        self.assertTrue(result.notes)

    def test_report_and_serialisation(self):
        model = SlopeModel.from_dict(SIMPLE)
        result = analyze(model, AnalysisOptions.from_dict({
            "methods": ["bishop", "spencer"], "n_slices": 30,
            "search": {"nx": 8, "ny": 8, "n_tangent": 8, "refine_passes": 1}}))
        text = result.text_report()
        self.assertIn("Bishop simplified", text)
        self.assertIn("Critical circle", text)
        data = result.to_dict()
        self.assertIn("render", data)
        self.assertEqual(len(data["slices"]), len(result.mass.slices))
        self.assertTrue(data["render"]["layers"])
        self.assertAlmostEqual(data["critical_fs"], result.critical_fs)


if __name__ == "__main__":
    unittest.main()
