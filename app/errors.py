"""Error type carried through parsing and inference.

Every ``InferError`` maps to an HTTP 422 response.  ``path`` is a JSON
Pointer (RFC 6901 style) locating the offending expression node; the root
node is reported as ``/``.
"""


class InferError(Exception):
    """A validation / inference failure that maps to HTTP 422."""

    def __init__(self, code: str, message: str, path: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path or "/"
