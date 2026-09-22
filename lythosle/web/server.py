"""A zero-dependency web server for the Lythos LE front end.

Run it with ``python -m lythosle serve`` (or ``python -m lythosle.web.server``).
It only uses :mod:`http.server`, so the whole application works on a bare
Python installation.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .api import handle_request, json_dumps

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

MAX_BODY = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "LythosLE"
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str,
              extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json_dumps(payload).encode("utf-8"), "application/json")

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._send_json(404, {"error": f"not found: {path}"})
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            body = fh.read()
        self._send(200, body, CONTENT_TYPES.get(ext, "application/octet-stream"),
                   {"Cache-Control": "no-cache"})

    # -- verbs -----------------------------------------------------------
    def do_GET(self) -> None:          # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            status, payload = handle_request("GET", path)
            self._send_json(status, payload)
        else:
            self._static(path)

    do_HEAD = do_GET

    def do_POST(self) -> None:         # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send_json(413, {"error": "request body too large"})
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": f"invalid JSON body: {exc}"})
            return
        status, payload = handle_request("POST", path, body)
        self._send_json(status, payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("LYTHOSLE_QUIET"):
            return
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False) -> None:
    httpd = Server((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Lythos LE is running on {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Serve the Lythos LE web interface")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="open a browser window")
    args = ap.parse_args()
    serve(args.host, args.port, args.open)
