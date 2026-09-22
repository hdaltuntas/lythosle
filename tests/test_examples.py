"""Every built-in example must run and give a defensible answer."""

import unittest

from lythosle import AnalysisOptions, SlopeModel, analyze, get_example, list_examples

EXPECTED = {
    # key            fs low, fs high  (bracketing the answer a reviewer would accept)
    "homogeneous": (0.95, 1.05),
    "layered_water": (0.9, 1.6),
    "soft_foundation": (0.6, 1.2),
    "seismic": (0.9, 1.5),
    "reinforced": (1.8, 3.0),
    "tension_crack": (1.0, 1.7),
}


class TestExamples(unittest.TestCase):
    def test_all_examples_run(self):
        for entry in list_examples():
            key = entry["key"]
            with self.subTest(example=key):
                data = get_example(key)
                model = SlopeModel.from_dict(data["model"])
                result = analyze(model, AnalysisOptions.from_dict(data["options"]))
                self.assertIsNotNone(result.mass, f"{key}: no surface found")
                fs = result.critical_fs
                low, high = EXPECTED[key]
                self.assertTrue(low <= fs <= high,
                                f"{key}: FS = {fs:.3f} outside [{low}, {high}]")
                for name, res in result.results.items():
                    self.assertTrue(res.ok, f"{key}/{name} did not converge")

    def test_reinforcement_is_actually_picked_up(self):
        data = get_example("reinforced")
        options = AnalysisOptions.from_dict(data["options"])
        with_nails = analyze(SlopeModel.from_dict(data["model"]), options)
        bare = dict(data["model"])
        bare["supports"] = []
        without = analyze(SlopeModel.from_dict(bare), AnalysisOptions.from_dict(data["options"]))
        self.assertGreater(with_nails.critical_fs, without.critical_fs)
        self.assertTrue(with_nails.mass.supports)

    def test_seismic_example_is_worse_than_static(self):
        data = get_example("seismic")
        static = dict(data["model"])
        static["seismic"] = {"kh": 0.0, "kv": 0.0}
        options = AnalysisOptions.from_dict(data["options"])
        seismic = analyze(SlopeModel.from_dict(data["model"]), options)
        still = analyze(SlopeModel.from_dict(static), AnalysisOptions.from_dict(data["options"]))
        self.assertLess(seismic.critical_fs, still.critical_fs)


if __name__ == "__main__":
    unittest.main()
