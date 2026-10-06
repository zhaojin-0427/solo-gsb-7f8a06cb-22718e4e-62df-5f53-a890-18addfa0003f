"""Expression tree model and structural validation.

Accepted JSON format — every node is an object with a string ``tag``:

    {"tag": "int",    "value": 42}
    {"tag": "bool",   "value": true}
    {"tag": "var",    "name": "x"}
    {"tag": "lambda", "param": "x", "body": <expr>}
    {"tag": "call",   "fn": <expr>, "arg": <expr>}
    {"tag": "let",    "name": "x", "value": <expr>, "body": <expr>}
    {"tag": "record", "fields": [{"name": "a", "value": <expr>}, ...]}
    {"tag": "field",  "record": <expr>, "name": "a"}

Limits: at most 80 nodes, depth at most 20 (root is depth 1).
Duplicate record field names are a structural error.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import StructuralError

MAX_NODES = 80
MAX_DEPTH = 20


@dataclass(frozen=True)
class IntLit:
    value: int


@dataclass(frozen=True)
class BoolLit:
    value: bool


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Lambda:
    param: str
    body: Node


@dataclass(frozen=True)
class Call:
    fn: Node
    arg: Node


@dataclass(frozen=True)
class Let:
    name: str
    value: Node
    body: Node


@dataclass(frozen=True)
class Record:
    fields: tuple[tuple[str, Node], ...]


@dataclass(frozen=True)
class Field:
    record: Node
    name: str


Node = IntLit | BoolLit | Var | Lambda | Call | Let | Record | Field


def parse(data) -> Node:
    """Validate raw JSON data and build the expression tree.

    Raises StructuralError on any malformed input.
    """
    return _parse(data, "$", 1, [0])


def _parse(data, path: str, depth: int, counter: list[int]) -> Node:
    if depth > MAX_DEPTH:
        raise StructuralError(
            f"expression depth exceeds the maximum of {MAX_DEPTH}", path)
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise StructuralError(
            f"expression has more than {MAX_NODES} nodes", path)
    if not isinstance(data, dict):
        raise StructuralError("expression node must be a JSON object", path)
    tag = data.get("tag")
    if not isinstance(tag, str):
        raise StructuralError("expression node must have a string 'tag'", path)

    if tag == "int":
        value = _required(data, "value", path)
        # bool is a subclass of int in Python — reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            raise StructuralError("'value' of an int node must be an integer", path)
        return IntLit(value)

    if tag == "bool":
        value = _required(data, "value", path)
        if not isinstance(value, bool):
            raise StructuralError("'value' of a bool node must be a boolean", path)
        return BoolLit(value)

    if tag == "var":
        return Var(_name(_required(data, "name", path), "name", path))

    if tag == "lambda":
        param = _name(_required(data, "param", path), "param", path)
        body = _parse(_required(data, "body", path), path + ".body", depth + 1, counter)
        return Lambda(param, body)

    if tag == "call":
        fn = _parse(_required(data, "fn", path), path + ".fn", depth + 1, counter)
        arg = _parse(_required(data, "arg", path), path + ".arg", depth + 1, counter)
        return Call(fn, arg)

    if tag == "let":
        name = _name(_required(data, "name", path), "name", path)
        value = _parse(_required(data, "value", path), path + ".value", depth + 1, counter)
        body = _parse(_required(data, "body", path), path + ".body", depth + 1, counter)
        return Let(name, value, body)

    if tag == "record":
        fields = _required(data, "fields", path)
        if not isinstance(fields, list):
            raise StructuralError("'fields' of a record node must be an array", path)
        seen: set[str] = set()
        items: list[tuple[str, Node]] = []
        for i, item in enumerate(fields):
            item_path = f"{path}.fields[{i}]"
            if not isinstance(item, dict):
                raise StructuralError(
                    "record field must be an object with 'name' and 'value'", item_path)
            name = _name(_required(item, "name", item_path), "name", item_path)
            if name in seen:
                raise StructuralError(f"duplicate record field '{name}'", item_path)
            seen.add(name)
            value = _parse(_required(item, "value", item_path),
                           item_path + ".value", depth + 1, counter)
            items.append((name, value))
        return Record(tuple(items))

    if tag == "field":
        record = _parse(_required(data, "record", path), path + ".record",
                        depth + 1, counter)
        name = _name(_required(data, "name", path), "name", path)
        return Field(record, name)

    raise StructuralError(f"unknown expression tag '{tag}'", path)


def _required(data: dict, key: str, path: str):
    if key not in data:
        raise StructuralError(f"missing required key '{key}'", path)
    return data[key]


def _name(value, key: str, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise StructuralError(f"'{key}' must be a non-empty string", path)
    return value
