"""Model queries: stratigraphy, column weights, pore pressures, mirroring."""

import unittest

from lythosle.materials import Material
from lythosle.model import SlopeModel

BASE = {
    "profile": [[0, 0], [20, 0], [50, 15], [80, 15]],
    "materials": [
        {"name": "fill", "unit_weight": 18.0, "sat_unit_weight": 20.0,
         "cohesion": 5.0, "friction_angle": 30.0},
        {"name": "clay", "unit_weight": 19.0, "strength_model": "undrained", "su": 40.0},
    ],
    "layers": [{"material": "fill"}, {"material": "clay", "boundary": [[0, -5], [80, -5]]}],
    "water_table": [[0, -2], [80, -2]],
}


class TestModel(unittest.TestCase):
    def setUp(self):
        self.m = SlopeModel.from_dict(BASE)

    def test_material_lookup(self):
        self.assertEqual(self.m.material_at(10, -1).name, "fill")
        self.assertEqual(self.m.material_at(10, -8).name, "clay")

    def test_column_weight_switches_to_saturated(self):
        # 0 to -2 moist fill, -2 to -5 saturated fill, -5 to -10 clay
        w, _ = self.m.column(10.0, -10.0, 0.0)
        self.assertAlmostEqual(w, 18 * 2 + 20 * 3 + 19 * 5)

    def test_column_centroid(self):
        w, y = self.m.column(10.0, -4.0, 0.0)
        self.assertLess(y, 0.0)
        self.assertGreater(y, -4.0)

    def test_pore_pressure(self):
        self.assertAlmostEqual(self.m.pore_pressure(10, -7), 9.81 * 5)
        self.assertAlmostEqual(self.m.pore_pressure(10, 1), 0.0)

    def test_ru_overrides_water_table(self):
        data = dict(BASE)
        data["materials"] = [dict(BASE["materials"][0], ru=0.3), BASE["materials"][1]]
        m = SlopeModel.from_dict(data)
        u = m.pore_pressure(10, -1)
        self.assertAlmostEqual(u, 0.3 * m.vertical_stress(10, -1))

    def test_mirroring_round_trip(self):
        mirrored = self.m.mirror()
        self.assertTrue(mirrored.mirrored)
        self.assertAlmostEqual(mirrored.ground_y(-10), self.m.ground_y(10))
        self.assertAlmostEqual(mirrored.to_user_x(-10), 10)
        back = mirrored.mirror()
        self.assertFalse(back.mirrored)
        self.assertAlmostEqual(back.ground_y(35), self.m.ground_y(35))

    def test_canonical_puts_the_crest_on_the_right(self):
        flipped = SlopeModel.from_dict(dict(BASE, profile=[[0, 15], [30, 15], [60, 0], [80, 0]]))
        canonical = flipped.canonical()
        self.assertTrue(canonical.mirrored)
        self.assertGreater(canonical.profile.pts[-1][1], canonical.profile.pts[0][1])

    def test_undrained_strength_gradient(self):
        mat = Material(name="soft", strength_model="undrained", su=10.0,
                       su_gradient=2.0, su_datum=0.0)
        c, tanphi = mat.strength_params(-5.0)
        self.assertAlmostEqual(c, 20.0)
        self.assertAlmostEqual(tanphi, 0.0)

    def test_bad_material_is_rejected(self):
        with self.assertRaises(ValueError):
            Material(name="x", strength_model="nonsense")
        with self.assertRaises(ValueError):
            Material(name="x", unit_weight=-1)

    def test_serialisation_round_trip(self):
        data = self.m.to_dict()
        again = SlopeModel.from_dict(data)
        self.assertAlmostEqual(again.ground_y(35), self.m.ground_y(35))
        self.assertEqual(set(again.materials), set(self.m.materials))


if __name__ == "__main__":
    unittest.main()
