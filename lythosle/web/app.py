"""Optional FastAPI adapter.

``python -m lythosle serve`` uses the standard-library server and needs nothing
installed.  If FastAPI and uvicorn are available you can instead run::

    uvicorn lythosle.web.app:app --reload

Both front ends delegate to :func:`lythosle.web.api.handle_request`, so they
behave identically.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:   # pragma: no cover - exercised only without FastAPI
    raise ImportError(
        "FastAPI is not installed. Use 'python -m lythosle serve' for the "
        "dependency-free server, or 'pip install fastapi uvicorn'."
    ) from exc

import os

from .api import handle_request

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Lythos LE", description="Limit equilibrium slope stability",
              version="1.0.0")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return handle_request("GET", "/api/health")[1]


@app.get("/api/methods")
def methods() -> Dict[str, Any]:
    return handle_request("GET", "/api/methods")[1]


@app.get("/api/examples")
def examples() -> Dict[str, Any]:
    return handle_request("GET", "/api/examples")[1]


@app.get("/api/examples/{key}")
def example(key: str) -> JSONResponse:
    status, payload = handle_request("GET", f"/api/examples/{key}")
    return JSONResponse(payload, status_code=status)


@app.post("/api/analyze")
async def run_analysis(request: Request) -> JSONResponse:
    body = await request.json()
    status, payload = handle_request("POST", "/api/analyze", body)
    return JSONResponse(payload, status_code=status)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
