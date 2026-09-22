"""The HTTP API and the command line interface."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from lythosle.cli import main
from lythosle.examples import EXAMPLES
from lythosle.web.api import ApiError, analyze_payload, handle_request
from lythosle.web.server import STATIC_DIR, Handler, Server

SMALL = {
    "model": {
        "profile": [[0, 0], [10, 0], [30, 10], [50, 10]],
        "materials": [{"name": "soil", "unit_weight": 20.0, "cohesion": 3.0,
                       "friction_angle": 19.6}],
        "layers": [{"material": "soil"}],
    },
    "options": {"methods": ["bishop"], "n_slices": 30,
                "search": {"nx": 6, "ny": 6, "n_tangent": 6, "refine_passes": 1,
                           "n_slices": 20}},
}


class TestApi(unittest.TestCase):
    def test_health_and_methods(self):
        status, payload = handle_request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        status, payload = handle_request("GET", "/api/methods")
        self.assertTrue(any(m["key"] == "spencer" for m in payload["methods"]))

    def test_examples(self):
        status, payload = handle_request("GET", "/api/examples")
        self.assertEqual(len(payload["examples"]), len(EXAMPLES))
        status, payload = handle_request("GET", "/api/examples/homogeneous")
        self.assertEqual(status, 200)
        self.assertIn("model", payload)
        status, payload = handle_request("GET", "/api/examples/nope")
        self.assertEqual(status, 404)
        self.assertIn("unknown example", payload["error"])

    def test_analyze(self):
        status, payload = handle_request("POST", "/api/analyze", SMALL)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(payload["critical_fs"], 1.0, delta=0.05)
        self.assertIn("render", payload)
        json.dumps(payload)          # must be JSON serialisable end to end

    def test_analyze_direction(self):
        flipped = json.loads(json.dumps(SMALL))
        flipped["model"]["profile"] = [[0, 10], [20, 10], [40, 0], [50, 0]]
        flipped["options"]["direction"] = "right"
        status, payload = handle_request("POST", "/api/analyze", flipped)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(payload["critical_fs"], 1.0, delta=0.05)

    def test_bad_requests(self):
        status, payload = handle_request("POST", "/api/analyze", {})
        self.assertEqual(status, 400)
        status, payload = handle_request("POST", "/api/analyze", {"model": {"profile": []}})
        self.assertEqual(status, 400)
        status, payload = handle_request("GET", "/api/nothing")
        self.assertEqual(status, 404)

    def test_oversized_search_is_refused(self):
        payload = json.loads(json.dumps(SMALL))
        payload["options"]["search"].update({"nx": 200, "ny": 200})
        with self.assertRaises(ApiError):
            analyze_payload(payload)

    def test_static_files_exist(self):
        for name in ("index.html", "styles.css", "app.js"):
            self.assertTrue(os.path.isfile(os.path.join(STATIC_DIR, name)), name)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["LYTHOSLE_QUIET"] = "1"
        cls.httpd = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=30) as response:
            return response.status, response.read()

    def test_serves_the_page(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Lythos LE", body)
        for asset in ("/styles.css", "/app.js"):
            status, body = self.get(asset)
            self.assertEqual(status, 200)
            self.assertTrue(body)

    def test_path_traversal_is_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/../../etc/passwd")
        self.assertEqual(ctx.exception.code, 404)

    def test_post_analyze(self):
        request = urllib.request.Request(
            self.url("/api/analyze"), data=json.dumps(SMALL).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])

    def test_invalid_json_body(self):
        request = urllib.request.Request(
            self.url("/api/analyze"), data=b"{not json",
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=30)
        self.assertEqual(ctx.exception.code, 400)


class TestCli(unittest.TestCase):
    def test_methods_command(self):
        self.assertEqual(main(["methods"]), 0)

    def test_example_listing(self):
        self.assertEqual(main(["example"]), 0)

    def test_example_run_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "model.json")
            self.assertEqual(main(["example", "homogeneous", "--save", model_path,
                                   "--quiet"]), 0)
            with open(model_path) as fh:
                saved = json.load(fh)
            self.assertIn("model", saved)

            json_path = os.path.join(tmp, "out.json")
            csv_path = os.path.join(tmp, "slices.csv")
            code = main(["analyze", model_path, "--method", "bishop", "--slices", "30",
                         "--json", json_path, "--csv", csv_path, "--quiet", "--no-render"])
            self.assertEqual(code, 0)
            with open(json_path) as fh:
                result = json.load(fh)
            self.assertNotIn("render", result)
            self.assertAlmostEqual(result["critical_fs"], 1.0, delta=0.05)
            with open(csv_path) as fh:
                lines = fh.read().strip().split("\n")
            self.assertGreater(len(lines), 10)
            self.assertIn("alpha_deg", lines[0])


if __name__ == "__main__":
    unittest.main()
