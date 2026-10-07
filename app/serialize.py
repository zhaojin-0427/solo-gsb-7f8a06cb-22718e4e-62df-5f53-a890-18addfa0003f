"""Rendering of the principal type scheme as JSON.

All variables free in the final type are quantified (the top-level
environment is empty).  Variables are uniformly renamed: type variables
become ``a, b, c, …`` and row variables ``r0, r1, …`` in first-occurrence
order, so the output is deterministic.
"""
from __future__ import annotations

from typing import Dict

from .typesys import (RVar, TBool, TFun, TInt, TRecord, TVar, Type, norm_row,
                      prune)


def _tvar_name(i: int) -> str:
    return chr(ord("a") + i) if i < 26 else f"t{i}"


def serialize_scheme(t: Type) -> dict:
    tnames: Dict[int, str] = {}
    rnames: Dict[int, str] = {}

    def assign(ty: Type) -> None:
        ty = prune(ty)
        if isinstance(ty, TVar):
            if ty.id not in tnames:
                tnames[ty.id] = _tvar_name(len(tnames))
        elif isinstance(ty, TFun):
            assign(ty.param)
            assign(ty.result)
        elif isinstance(ty, TRecord):
            row = norm_row(ty.row)
            for key in sorted(row.fields):
                assign(row.fields[key])
            if isinstance(row.tail, RVar) and row.tail.id not in rnames:
                rnames[row.tail.id] = f"r{len(rnames)}"

    assign(t)

    def ser(ty: Type) -> dict:
        ty = prune(ty)
        if isinstance(ty, TInt):
            return {"kind": "int"}
        if isinstance(ty, TBool):
            return {"kind": "bool"}
        if isinstance(ty, TVar):
            return {"kind": "var", "name": tnames[ty.id]}
        if isinstance(ty, TFun):
            return {
                "kind": "fun",
                "param": ser(ty.param),
                "result": ser(ty.result),
            }
        if isinstance(ty, TRecord):
            row = norm_row(ty.row)
            fields = [
                {"name": k, "type": ser(v)} for k, v in sorted(row.fields.items())
            ]
            if isinstance(row.tail, RVar):
                # open tail: the row variable excludes the fields listed here
                tail = {
                    "kind": "row_var",
                    "name": rnames[row.tail.id],
                    "excludes": sorted(row.fields),
                }
            else:
                tail = {"kind": "empty"}
            return {"kind": "record", "fields": fields, "tail": tail}
        raise AssertionError("unreachable")

    pretty = _Pretty(tnames, rnames).show(t)
    quantified_t = list(tnames.values())
    quantified_r = list(rnames.values())
    if quantified_t or quantified_r:
        pretty = "∀ " + " ".join(quantified_t + quantified_r) + ". " + pretty

    return {
        "quantified": {"type_vars": quantified_t, "row_vars": quantified_r},
        "type": ser(t),
        "pretty": pretty,
    }


class _Pretty:
    def __init__(self, tnames: Dict[int, str], rnames: Dict[int, str]):
        self.tnames = tnames
        self.rnames = rnames

    def show(self, t: Type, nested: bool = False) -> str:
        t = prune(t)
        if isinstance(t, TInt):
            return "int"
        if isinstance(t, TBool):
            return "bool"
        if isinstance(t, TVar):
            return self.tnames[t.id]
        if isinstance(t, TFun):
            s = f"{self.show(t.param, True)} → {self.show(t.result)}"
            return f"({s})" if nested else s
        if isinstance(t, TRecord):
            row = norm_row(t.row)
            inner = ", ".join(
                f"{k}: {self.show(v)}" for k, v in sorted(row.fields.items())
            )
            if isinstance(row.tail, RVar):
                inner = f"{inner} | {self.rnames[row.tail.id]}" if inner else f"| {self.rnames[row.tail.id]}"
            return "{" + inner + "}"
        raise AssertionError("unreachable")
