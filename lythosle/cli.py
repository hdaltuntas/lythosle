"""Command line interface: ``python -m lythosle ...``"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .analysis import AnalysisOptions, analyze
from .examples import get_example, list_examples
from .methods import METHOD_EQUILIBRIUM, METHOD_LABELS, METHODS
from .model import SlopeModel


def _load_json(path: str) -> Dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _run(model_data: Dict[str, Any], options_data: Dict[str, Any],
         args: argparse.Namespace) -> int:
    if args.method:
        options_data = dict(options_data)
        options_data["methods"] = list(args.method)
        search = dict(options_data.get("search") or {})
        search["method"] = args.method[0]
        options_data["search"] = search
    if args.slices:
        options_data = dict(options_data)
        options_data["n_slices"] = args.slices
    if args.optimize:
        options_data = dict(options_data)
        search = dict(options_data.get("search") or {})
        search["optimize"] = True
        options_data["search"] = search

    model = SlopeModel.from_dict(model_data)
    if args.direction == "right":
        model = model.mirror()
    options = AnalysisOptions.from_dict(options_data)
    result = analyze(model, options)

    if not args.quiet:
        print(result.text_report())
    if result.mass is None:
        return 2
    if args.json:
        payload = result.to_dict(include_render=not args.no_render)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        if not args.quiet:
            print(f"\nwrote {args.json}")
    if args.csv:
        _write_csv(args.csv, result.slice_table())
        if not args.quiet:
            print(f"wrote {args.csv}")
    if args.fs_only:
        fs = result.critical_fs
        print(f"{fs:.4f}" if fs is not None else "nan")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="lythosle",
        description="Lythos LE - limit equilibrium slope stability analysis "
                    f"(version {__version__})")
    ap.add_argument("--version", action="version", version=f"lythosle {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("analyze", help="analyse a model from a JSON file")
    run.add_argument("model", help="path to a model JSON file ('-' for stdin)")
    run.add_argument("--options", help="path to an analysis options JSON file")
    run.add_argument("--method", action="append", choices=list(METHODS),
                     help="method to run (repeatable; the first one drives the search)")
    run.add_argument("--slices", type=int, help="number of slices")
    run.add_argument("--direction", choices=["auto", "left", "right"], default="auto",
                     help="direction the sliding mass moves (default: from the geometry)")
    run.add_argument("--optimize", action="store_true",
                     help="refine the critical circle into a non-circular surface")
    run.add_argument("--json", help="write the full result to this JSON file")
    run.add_argument("--no-render", action="store_true",
                     help="omit the drawing data from the JSON output")
    run.add_argument("--csv", help="write the slice table to this CSV file")
    run.add_argument("--fs-only", action="store_true", help="print just the factor of safety")
    run.add_argument("--quiet", action="store_true", help="suppress the report")

    ex = sub.add_parser("example", help="run or export a built-in example")
    ex.add_argument("key", nargs="?", help="example key (omit to list them)")
    ex.add_argument("--save", help="write the example model to this JSON file")
    ex.add_argument("--method", action="append", choices=list(METHODS))
    ex.add_argument("--slices", type=int)
    ex.add_argument("--direction", choices=["auto", "left", "right"], default="auto")
    ex.add_argument("--optimize", action="store_true")
    ex.add_argument("--json")
    ex.add_argument("--no-render", action="store_true")
    ex.add_argument("--csv")
    ex.add_argument("--fs-only", action="store_true")
    ex.add_argument("--quiet", action="store_true")

    sub.add_parser("methods", help="list the available methods")

    srv = sub.add_parser("serve", help="start the web interface")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--open", action="store_true", help="open a browser window")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "methods":
        print(f"{'key':<20}{'method':<34}equilibrium")
        print("-" * 72)
        for m in METHODS:
            print(f"{m:<20}{METHOD_LABELS[m]:<34}{METHOD_EQUILIBRIUM[m]}")
        return 0

    if args.command == "serve":
        from .web.server import serve
        serve(args.host, args.port, args.open)
        return 0

    if args.command == "example":
        if not args.key:
            print("Available examples:\n")
            for e in list_examples():
                print(f"  {e['key']:<18}{e['title']}")
                print(f"  {'':<18}{e['description']}\n")
            return 0
        try:
            example = get_example(args.key)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.save:
            with open(args.save, "w", encoding="utf-8") as fh:
                json.dump({"model": example["model"], "options": example["options"]},
                          fh, indent=2)
            print(f"wrote {args.save}")
            if args.quiet:
                return 0
        return _run(example["model"], example["options"], args)

    if args.command == "analyze":
        data = _load_json(args.model)
        model_data = data.get("model", data)
        options_data = data.get("options", {})
        if args.options:
            options_data = _load_json(args.options)
        return _run(model_data, options_data, args)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
