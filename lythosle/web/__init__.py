"""Browser front end for Lythos LE.

``api`` holds the transport-independent request handling; ``server`` is a
zero-dependency standard-library server and ``app`` exposes the same API
through FastAPI when it happens to be installed.
"""

from .api import handle_request

__all__ = ["handle_request"]
