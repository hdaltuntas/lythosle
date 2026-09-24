#!/usr/bin/env python3
"""Run Lythos LE.

The package already installs a ``lythosle`` command and answers to
``python -m lythosle``; this file is the obvious thing to reach for in a fresh
clone, and what most hosts run by default.

    python main.py                          start the web interface
    python main.py analyze model.json       anything the CLI accepts
    python main.py example seismic --csv slices.csv
    python main.py --help

With no arguments it serves the browser interface on http://127.0.0.1:8000 and
opens a window. ``HOST`` and ``PORT`` override the address - a host that sets
them (Render, Railway, Fly and friends usually set ``PORT``) gets a server
bound to every interface and no browser.

Nothing needs installing first: the solver, the server and the front end are
standard library only.
"""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Running from a clone: make sure the package next to this file wins over
    # anything with the same name that happens to be installed.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    try:
        from lythosle.cli import main as cli_main
    except ImportError as exc:                       # pragma: no cover
        print(f"could not import lythosle from {here}: {exc}", file=sys.stderr)
        print("run this file from inside the project, or 'pip install lythosle'.",
              file=sys.stderr)
        return 1

    if not argv:
        hosted = "PORT" in os.environ or "HOST" in os.environ
        host = os.environ.get("HOST", "0.0.0.0" if hosted else "127.0.0.1")
        port = os.environ.get("PORT", "8000")
        argv = ["serve", "--host", host, "--port", port]
        if not hosted:
            argv.append("--open")

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
