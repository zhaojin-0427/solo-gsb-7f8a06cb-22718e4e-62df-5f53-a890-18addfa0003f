"""Typed AST nodes for the rule expression language."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


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
    body: "Expr"


@dataclass(frozen=True)
class Call:
    func: "Expr"
    arg: "Expr"


@dataclass(frozen=True)
class Let:
    name: str
    value: "Expr"
    body: "Expr"


@dataclass(frozen=True)
class Record:
    # fields keep source order; duplicate names are rejected by the parser
    fields: Tuple[Tuple[str, "Expr"], ...]


@dataclass(frozen=True)
class FieldAccess:
    record: "Expr"
    field: str


Expr = Union[IntLit, BoolLit, Var, Lambda, Call, Let, Record, FieldAccess]
