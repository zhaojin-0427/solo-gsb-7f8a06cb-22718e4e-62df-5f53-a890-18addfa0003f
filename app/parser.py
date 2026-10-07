"""Structural validation of the incoming JSON expression tree.

Converts raw JSON into the AST while enforcing the structural contract:

* at most ``MAX_NODES`` expression nodes,
* nesting depth at most ``MAX_DEPTH`` (root node is depth 1),
* only the eight supported node kinds,
* record fields given as an array of key/value items with unique names.

Every problem raises :class:`InferError`, which the API maps to HTTP 422.
"""
from __future__ import annotations

from typing import Any

from .astnodes import (BoolLit, Call, Expr, FieldAccess, IntLit, Lambda, Let,
                       Record, Var)
from .errors import InferError

MAX_NODES = 80
MAX_DEPTH = 20

# Canonical node kinds and accepted aliases for the discriminator value.
_KIND_ALIASES = {
    "int": "int", "integer": "int", "int_lit": "int", "intlit": "int",
    "bool": "bool", "boolean": "bool", "bool_lit": "bool", "boollit": "bool",
    "var": "var", "variable": "var",
    "lambda": "lambda", "lam": "lambda", "fn": "lambda", "fun": "lambda",
    "abs": "lambda", "function": "lambda",
    "call": "call", "app": "call", "apply": "call", "application": "call",
    "let": "let",
    "record": "record", "rec": "record", "object": "record",
    "field": "field", "get": "field", "select": "field", "project": "field",
    "dot": "field", "access": "field", "field_access": "field",
}


def _pick(d: dict, *keys: str):
    """Return ``(value, True)`` for the first present key, else ``(None, False)``."""
    for key in keys:
        if key in d:
            return d[key], True
    return None, False


class _Parser:
    def __init__(self) -> None:
        self.nodes = 0

    def parse(self, data: Any, path: str, depth: int) -> Expr:
        if depth > MAX_DEPTH:
            raise InferError(
                "too_deep",
                f"expression depth exceeds the limit of {MAX_DEPTH}",
                path,
            )
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise InferError(
                "too_many_nodes",
                f"expression has more than {MAX_NODES} nodes",
                path,
            )
        if not isinstance(data, dict):
            raise InferError(
                "invalid_expression",
                "expression node must be a JSON object",
                path,
            )
        raw_kind, ok = _pick(data, "kind", "type", "tag", "node")
        if not ok or not isinstance(raw_kind, str):
            raise InferError(
                "invalid_expression",
                'expression node is missing its "kind"',
                path,
            )
        kind = _KIND_ALIASES.get(raw_kind.strip().lower())
        if kind is None:
            raise InferError(
                "invalid_expression",
                f"unknown expression kind {raw_kind!r}",
                path,
            )
        return getattr(self, f"_parse_{kind}")(data, path, depth)

    # ---------------------------------------------------------- literals
    def _parse_int(self, data: dict, path: str, depth: int) -> Expr:
        value, ok = _pick(data, "value", "val")
        # bool is a subclass of int in Python — reject it explicitly
        if not ok or isinstance(value, bool) or not isinstance(value, int):
            raise InferError(
                "invalid_expression",
                'int literal requires an integer "value"',
                path,
            )
        return IntLit(value)

    def _parse_bool(self, data: dict, path: str, depth: int) -> Expr:
        value, ok = _pick(data, "value", "val")
        if not ok or not isinstance(value, bool):
            raise InferError(
                "invalid_expression",
                'bool literal requires a boolean "value"',
                path,
            )
        return BoolLit(value)

    # ----------------------------------------------------------- names
    @staticmethod
    def _name(value: Any, what: str, path: str) -> str:
        if not isinstance(value, str) or not value:
            raise InferError(
                "invalid_expression",
                f'{what} requires a non-empty string "name"',
                path,
            )
        return value

    def _parse_var(self, data: dict, path: str, depth: int) -> Expr:
        name, ok = _pick(data, "name", "id", "identifier")
        if not ok:
            raise InferError("invalid_expression", 'variable requires a "name"', path)
        return Var(self._name(name, "variable", path))

    # ---------------------------------------------------------- lambda
    def _parse_lambda(self, data: dict, path: str, depth: int) -> Expr:
        param, ok = _pick(data, "param", "parameter", "arg", "var", "name", "bound")
        if not ok or not isinstance(param, str) or not param:
            raise InferError(
                "invalid_expression",
                'lambda requires a non-empty string "param"',
                path,
            )
        body, ok = _pick(data, "body")
        if not ok:
            raise InferError("invalid_expression", 'lambda requires a "body"', path)
        return Lambda(param, self.parse(body, path + "/body", depth + 1))

    # ------------------------------------------------------------ call
    def _parse_call(self, data: dict, path: str, depth: int) -> Expr:
        func, ok = _pick(data, "func", "fun", "function", "callee", "fn")
        if not ok:
            raise InferError("invalid_expression", 'call requires a "func"', path)
        arg, ok = _pick(data, "arg", "argument")
        if not ok:
            raise InferError("invalid_expression", 'call requires an "arg"', path)
        return Call(
            self.parse(func, path + "/func", depth + 1),
            self.parse(arg, path + "/arg", depth + 1),
        )

    # ------------------------------------------------------------- let
    def _parse_let(self, data: dict, path: str, depth: int) -> Expr:
        name, ok = _pick(data, "name", "var", "id", "binding")
        if not ok or not isinstance(name, str) or not name:
            raise InferError(
                "invalid_expression",
                'let requires a non-empty string "name"',
                path,
            )
        value, ok = _pick(data, "value", "val", "bound", "definition", "rhs")
        if not ok:
            raise InferError("invalid_expression", 'let requires a "value"', path)
        body, ok = _pick(data, "body", "in", "expr")
        if not ok:
            raise InferError("invalid_expression", 'let requires a "body"', path)
        return Let(
            name,
            self.parse(value, path + "/value", depth + 1),
            self.parse(body, path + "/body", depth + 1),
        )

    # ---------------------------------------------------------- record
    def _parse_record(self, data: dict, path: str, depth: int) -> Expr:
        fields, ok = _pick(data, "fields", "items", "entries", "properties", "props")
        if not ok or not isinstance(fields, (list, dict)):
            raise InferError(
                "invalid_expression",
                'record requires a "fields" array of key/value items',
                path,
            )
        if isinstance(fields, dict):  # object form accepted as a convenience
            fields = [{"name": k, "value": v} for k, v in fields.items()]
        seen = set()
        items = []
        for i, item in enumerate(fields):
            item_path = f"{path}/fields/{i}"
            name, value = self._parse_field_item(item, item_path)
            if name in seen:
                raise InferError(
                    "duplicate_field",
                    f'duplicate field "{name}" in record literal',
                    path,
                )
            seen.add(name)
            items.append((name, self.parse(value, item_path + "/value", depth + 1)))
        return Record(tuple(items))

    @staticmethod
    def _parse_field_item(item: Any, item_path: str):
        if isinstance(item, dict):
            name, ok = _pick(item, "name", "key", "label", "field")
            if not ok or not isinstance(name, str) or not name:
                raise InferError(
                    "invalid_expression",
                    'record field item requires a non-empty string "name"',
                    item_path,
                )
            value, ok = _pick(item, "value", "val", "expr")
            if not ok:
                raise InferError(
                    "invalid_expression",
                    'record field item requires a "value"',
                    item_path,
                )
            return name, value
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[0], str)
            and item[0]
        ):
            return item[0], item[1]
        raise InferError(
            "invalid_expression",
            'record field item must be an object with "name" and "value"',
            item_path,
        )

    # ---------------------------------------------------- field access
    def _parse_field(self, data: dict, path: str, depth: int) -> Expr:
        record, ok = _pick(data, "record", "object", "target", "expr", "value", "rec")
        if not ok:
            raise InferError(
                "invalid_expression",
                'field access requires a "record"',
                path,
            )
        field, ok = _pick(data, "field", "name", "label", "key", "member")
        if not ok or not isinstance(field, str) or not field:
            raise InferError(
                "invalid_expression",
                'field access requires a non-empty string "field"',
                path,
            )
        return FieldAccess(self.parse(record, path + "/record", depth + 1), field)


def parse_expression(data: Any) -> Expr:
    """Validate raw JSON and return the corresponding AST."""
    return _Parser().parse(data, "", 1)
