"""Lythos LE - limit equilibrium slope stability analysis.

A dependency-free Python engine (plus a browser front end) that computes the
factor of safety of slopes and embankments with the classical method of
slices: Ordinary/Fellenius, Bishop simplified, Janbu, Corps of Engineers,
Lowe-Karafiath, Spencer and Morgenstern-Price.

Typical use::

    from lythosle import SlopeModel, AnalysisOptions, analyze

    model = SlopeModel.from_dict({...})
    result = analyze(model, AnalysisOptions())
    print(result.critical_fs)
    print(result.text_report())
"""

from .analysis import AnalysisOptions, AnalysisResult, analyze
from .examples import EXAMPLES, get_example, list_examples
from .materials import Material
from .methods import METHOD_LABELS, METHODS, MethodResult, solve, solve_all
from .model import Layer, Seismic, SlopeModel, Support, Surcharge, TensionCrack
from .search import SearchLimits, SearchOptions, search_circular
from .slices import SlipSurface, build_slices, circular_surface, polyline_surface

__version__ = "0.1.0"

__all__ = [
    "AnalysisOptions", "AnalysisResult", "analyze",
    "SlopeModel", "Layer", "Material", "Seismic", "Support", "Surcharge",
    "TensionCrack", "SlipSurface", "build_slices", "circular_surface",
    "polyline_surface", "SearchOptions", "SearchLimits", "search_circular",
    "METHODS", "METHOD_LABELS", "MethodResult", "solve", "solve_all",
    "EXAMPLES", "get_example", "list_examples", "__version__",
]
