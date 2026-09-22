"""Geometry primitives."""

import unittest

from lythosle.geometry import (Polyline, circle_from_three_points, point_in_polygon,
                               polygon_area, polygon_centroid,
                               segment_circle_intersections, segment_intersection)


class TestPolyline(unittest.TestCase):
    def setUp(self):
        self.pl = Polyline([(0, 0), (10, 0), (30, 10), (50, 10)])

    def test_interpolation(self):
        self.assertAlmostEqual(self.pl.y(0), 0.0)
        self.assertAlmostEqual(self.pl.y(20), 5.0)
        self.assertAlmostEqual(self.pl.y(30), 10.0)

    def test_clamped_outside_range(self):
        self.assertAlmostEqual(self.pl.y(-100), 0.0)
        self.assertAlmostEqual(self.pl.y(100), 10.0)

    def test_reversed_input_is_normalised(self):
        pl = Polyline([(50, 10), (30, 10), (10, 0), (0, 0)])
        self.assertAlmostEqual(pl.y(20), 5.0)
        self.assertLess(pl.pts[0][0], pl.pts[-1][0])

    def test_slope(self):
        self.assertAlmostEqual(self.pl.slope(20), 0.5)
        self.assertAlmostEqual(self.pl.slope(5), 0.0)

    def test_clip_adds_interpolated_ends(self):
        clipped = self.pl.clip(5, 25)
        self.assertAlmostEqual(clipped[0][0], 5)
        self.assertAlmostEqual(clipped[-1][0], 25)
        self.assertAlmostEqual(clipped[-1][1], 7.5)

    def test_circle_intersections(self):
        flat = Polyline([(-10, 0), (10, 0)])
        hits = flat.circle_intersections(0.0, 0.0, 5.0)
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(hits[0][0], -5.0)
        self.assertAlmostEqual(hits[1][0], 5.0)

    def test_too_few_points(self):
        with self.assertRaises(ValueError):
            Polyline([(0, 0)])


class TestPrimitives(unittest.TestCase):
    def test_segment_circle(self):
        hits = segment_circle_intersections(-10, 0, 10, 0, 0, 0, 4)
        self.assertEqual(len(hits), 2)
        hits = segment_circle_intersections(-10, 20, 10, 20, 0, 0, 4)
        self.assertEqual(hits, [])

    def test_segment_intersection(self):
        p = segment_intersection((0, 0), (10, 10), (0, 10), (10, 0))
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p[0], 5.0)
        self.assertAlmostEqual(p[1], 5.0)
        self.assertIsNone(segment_intersection((0, 0), (1, 0), (0, 5), (1, 5)))

    def test_polygon_area_and_centroid(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4)]
        self.assertAlmostEqual(polygon_area(square), 16.0)
        cx, cy = polygon_centroid(square)
        self.assertAlmostEqual(cx, 2.0)
        self.assertAlmostEqual(cy, 2.0)

    def test_point_in_polygon(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4)]
        self.assertTrue(point_in_polygon(2, 2, square))
        self.assertFalse(point_in_polygon(5, 2, square))

    def test_circle_from_three_points(self):
        fit = circle_from_three_points((-3, 0), (0, 3), (3, 0))
        self.assertIsNotNone(fit)
        x, y, r = fit
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(r, 3.0)
        self.assertIsNone(circle_from_three_points((0, 0), (1, 1), (2, 2)))


if __name__ == "__main__":
    unittest.main()
