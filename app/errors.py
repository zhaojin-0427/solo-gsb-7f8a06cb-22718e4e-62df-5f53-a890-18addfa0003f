"""Structured errors. Every error carries a machine-readable ``kind`` and a
JSONPath-style ``path`` pointing at the offending expression node."""


class InferError(Exception):
    """Base class for all errors surfaced as HTTP 422 responses."""

    kind = "error"

    def __init__(self, message: str, path: str = "$"):
        super().__init__(message)
        self.message = message
        self.path = path


class StructuralError(InferError):
    """The JSON expression tree itself is malformed (bad shape, duplicate
    record fields, too many nodes, too deep, ...)."""

    kind = "structural"


class UnboundVariableError(InferError):
    kind = "unbound_variable"


class MissingFieldError(InferError):
    kind = "missing_field"


class TypeConflictError(InferError):
    kind = "type_conflict"


class InfiniteTypeError(InferError):
    kind = "infinite_type"
