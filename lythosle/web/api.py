"""Transport-independent API used by both server front ends.

Every endpoint takes and returns plain JSON-able dictionaries so the standard
library server and the optional FastAPI app share exactly the same behaviour.
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Dict, Optional, Tuple

from ..analysis import AnalysisOptions, analyze
from ..examples import get_example, list_examples
from ..methods import METHOD_EQUILIBRIUM, METHOD_LABELS, METHODS
from ..model import SlopeModel

MAX_SLICES = 500
MAX_GRID_POINTS = 60 * 60
MAX_TRIALS = 400_000


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


def _guard_options(opts: Dict[str, Any]) -> None:
    """Keep a browser request from asking for a search that never finishes."""
    if int(opts.get("n_slices", 50)) > MAX_SLICES:
        raise ApiError(f"n_slices is limited to {MAX_SLICES}")
    s = opts.get("search") or {}
    nx, ny = int(s.get("nx", 12)), int(s.get("ny", 12))
    nt = max(int(s.get("n_tangent", 12)), int(s.get("n_radius", 12)))
    if nx * ny > MAX_GRID_POINTS:
        raise ApiError("the centre grid is too large (nx * ny limited to 3600)")
    if nx * ny * nt > MAX_TRIALS:
        raise ApiError("the search asks for too many trial surfaces")


def analyze_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run an analysis from a ``{model, options}`` request body."""
    model_data = payload.get("model")
    if not isinstance(model_data, dict):
        raise ApiError("the request needs a 'model' object")
    if not model_data.get("profile"):
        raise ApiError("the model needs a ground surface profile")
    options_data = payload.get("options") or {}
    _guard_options(options_data)
    try:
        model = SlopeModel.from_dict(model_data)
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(f"invalid model: {exc}")
    options = AnalysisOptions.from_dict(options_data)
    direction = (options_data.get("direction") or "auto").lower()
    if direction == "left":
        pass                      # canonical already: crest on the right
    elif direction == "right":
        model = model.mirror()
    result = analyze(model, options)
    out = result.to_dict()
    out["ok"] = result.mass is not None
    if not out["ok"] and not out["notes"]:
        out["notes"] = ["no valid slip surface was found for this model"]
    return out


def handle_request(method: str, path: str,
                   body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """Route one API call.  Returns ``(status, payload)``."""
    method = method.upper()
    path = path.rstrip("/") or "/"
    try:
        if method == "GET" and path == "/api/health":
            from .. import __version__
            return 200, {"status": "ok", "version": __version__}
        if method == "GET" and path == "/api/methods":
            return 200, {"methods": [
                {"key": m, "label": METHOD_LABELS[m],
                 "equilibrium": METHOD_EQUILIBRIUM[m]} for m in METHODS]}
        if method == "GET" and path == "/api/examples":
            return 200, {"examples": list_examples()}
        if method == "GET" and path.startswith("/api/examples/"):
            key = path[len("/api/examples/"):]
            try:
                return 200, get_example(key)
            except KeyError as exc:
                raise ApiError(exc.args[0] if exc.args else "unknown example", 404)
        if method == "POST" and path == "/api/analyze":
            return 200, analyze_payload(body or {})
        raise ApiError(f"no route for {method} {path}", 404)
    except ApiError as exc:
        return exc.status, {"error": exc.message}
    except Exception as exc:                      # pragma: no cover - safety net
        return 500, {"error": f"{type(exc).__name__}: {exc}",
                     "traceback": traceback.format_exc(limit=5)}


def json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, allow_nan=False, default=_fallback)


def _fallback(obj: Any) -> Any:
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return str(obj)
