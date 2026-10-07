"""Types, rows, unification, generalisation and instantiation.

The engine is Damas–Hindley–Milner inference extended with row-polymorphic
records (Rémy-style rows):

* record literals are **closed** records (empty row tail),
* field selection requires an **open** record ``{field: α | ρ}`` whose row
  variable ``ρ`` must never again mention the selected label — the
  unification algorithm below maintains exactly that invariant,
* ``let`` generalises only the type/row variables not free in the current
  environment; every later reference instantiates fresh variables,
* lambda parameters stay monomorphic.
"""
from __future__ import annotations

from typing import Dict, Iterator, Optional, Set

from .errors import InferError


# ------------------------------------------------------------------ types
class Type:
    __slots__ = ()


class TInt(Type):
    __slots__ = ()


class TBool(Type):
    __slots__ = ()


class TVar(Type):
    """A unification variable; ``instance`` is the union-find link."""

    __slots__ = ("id", "instance")

    def __init__(self, vid: int):
        self.id = vid
        self.instance: Optional[Type] = None


class TFun(Type):
    __slots__ = ("param", "result")

    def __init__(self, param: Type, result: Type):
        self.param = param
        self.result = result


class TRecord(Type):
    __slots__ = ("row",)

    def __init__(self, row: "Row"):
        self.row = row


INT = TInt()
BOOL = TBool()


# ------------------------------------------------------------------- rows
class Row:
    """A row: labelled fields plus a tail (``REmpty`` or ``RVar``)."""

    __slots__ = ("fields", "tail")

    def __init__(self, fields: Dict[str, Type], tail):
        self.fields = fields
        self.tail = tail


class REmpty:
    __slots__ = ()


EMPTY = REmpty()


class RVar:
    """A row variable; ``instance`` is the union-find link to a ``Row``."""

    __slots__ = ("id", "instance")

    def __init__(self, rid: int):
        self.id = rid
        self.instance: Optional[Row] = None


class Ctx:
    """Per-request state: the fresh-variable supply."""

    def __init__(self) -> None:
        self._next = 0

    def _new_id(self) -> int:
        self._next += 1
        return self._next

    def fresh_tvar(self) -> TVar:
        return TVar(self._new_id())

    def fresh_rvar(self) -> RVar:
        return RVar(self._new_id())


# ------------------------------------------------------------- normal forms
def prune(t: Type) -> Type:
    """Follow bound type variables (with path compression)."""
    while isinstance(t, TVar) and t.instance is not None:
        nxt = prune(t.instance)
        t.instance = nxt
        t = nxt
    return t


def norm_row(row: Row) -> Row:
    """Flatten a row by following bound row variables in its tail."""
    fields = row.fields
    tail = row.tail
    while isinstance(tail, RVar) and tail.instance is not None:
        inst = tail.instance
        if fields is row.fields:
            fields = dict(row.fields)
        fields.update(inst.fields)  # disjoint from `fields` by the row invariant
        tail = inst.tail
    if fields is row.fields and tail is row.tail:
        return row
    return Row(fields, tail)


# ------------------------------------------------------------- occurs checks
def occurs_tvar(v: TVar, t: Type) -> bool:
    t = prune(t)
    if isinstance(t, TVar):
        return t is v
    if isinstance(t, TFun):
        return occurs_tvar(v, t.param) or occurs_tvar(v, t.result)
    if isinstance(t, TRecord):
        row = norm_row(t.row)
        return any(occurs_tvar(v, ft) for ft in row.fields.values())
    return False


def occurs_rvar(v: RVar, t: Type) -> bool:
    t = prune(t)
    if isinstance(t, TFun):
        return occurs_rvar(v, t.param) or occurs_rvar(v, t.result)
    if isinstance(t, TRecord):
        return occurs_rvar_row(v, t.row)
    return False


def occurs_rvar_row(v: RVar, row: Row) -> bool:
    row = norm_row(row)
    if row.tail is v:
        return True
    return any(occurs_rvar(v, ft) for ft in row.fields.values())


# ------------------------------------------------------------- display (errors)
def show(t: Type) -> str:
    t = prune(t)
    if isinstance(t, TInt):
        return "int"
    if isinstance(t, TBool):
        return "bool"
    if isinstance(t, TVar):
        return f"t{t.id}"
    if isinstance(t, TFun):
        param = show(t.param)
        if isinstance(prune(t.param), TFun):
            param = f"({param})"
        return f"{param} -> {show(t.result)}"
    if isinstance(t, TRecord):
        return show_row(t.row)
    return "?"


def show_row(row: Row) -> str:
    row = norm_row(row)
    inner = ", ".join(f"{k}: {show(v)}" for k, v in sorted(row.fields.items()))
    if isinstance(row.tail, RVar):
        inner = f"{inner} | r{row.tail.id}" if inner else f"| r{row.tail.id}"
    return "{" + inner + "}"


# -------------------------------------------------------------- unification
def unify(ctx: Ctx, t1: Type, t2: Type, path: str) -> None:
    t1 = prune(t1)
    t2 = prune(t2)
    if t1 is t2:
        return
    if isinstance(t1, TVar):
        _bind_tvar(t1, t2, path)
        return
    if isinstance(t2, TVar):
        _bind_tvar(t2, t1, path)
        return
    if isinstance(t1, TInt) and isinstance(t2, TInt):
        return
    if isinstance(t1, TBool) and isinstance(t2, TBool):
        return
    if isinstance(t1, TFun) and isinstance(t2, TFun):
        unify(ctx, t1.param, t2.param, path)
        unify(ctx, t1.result, t2.result, path)
        return
    if isinstance(t1, TRecord) and isinstance(t2, TRecord):
        unify_rows(ctx, t1.row, t2.row, path)
        return
    raise InferError(
        "type_mismatch", f"cannot unify {show(t1)} with {show(t2)}", path
    )


def _bind_tvar(v: TVar, t: Type, path: str) -> None:
    if occurs_tvar(v, t):
        raise InferError(
            "infinite_type",
            f"cannot construct the infinite type t{v.id} = {show(t)}",
            path,
        )
    v.instance = t


def unify_rows(ctx: Ctx, row1: Row, row2: Row, path: str) -> None:
    r1 = norm_row(row1)
    r2 = norm_row(row2)
    f1, tail1 = r1.fields, r1.tail
    f2, tail2 = r2.fields, r2.tail

    for name in f1.keys() & f2.keys():
        unify(ctx, f1[name], f2[name], path)

    only1 = {k: v for k, v in f1.items() if k not in f2}
    only2 = {k: v for k, v in f2.items() if k not in f1}

    if isinstance(tail1, RVar) and isinstance(tail2, RVar):
        if tail1 is tail2:
            # Same row variable on both sides: any leftover field would have
            # to live inside that very variable, i.e. the row variable would
            # contain a field already listed next to it — reject.
            if only1 or only2:
                raise InferError(
                    "type_mismatch",
                    "incompatible records: the shared row variable would have "
                    "to contain field(s) already listed: "
                    + ", ".join(sorted(set(only1) | set(only2))),
                    path,
                )
            return
        fresh = ctx.fresh_rvar()
        _bind_rvar(tail1, Row(only2, fresh), path)
        _bind_rvar(tail2, Row(only1, fresh), path)
        return
    if isinstance(tail1, RVar):  # tail2 is empty (closed row)
        if only1:
            raise InferError(
                "missing_field",
                "record is missing required field(s): " + ", ".join(sorted(only1)),
                path,
            )
        _bind_rvar(tail1, Row(only2, EMPTY), path)
        return
    if isinstance(tail2, RVar):  # tail1 is empty (closed row)
        if only2:
            raise InferError(
                "missing_field",
                "record is missing required field(s): " + ", ".join(sorted(only2)),
                path,
            )
        _bind_rvar(tail2, Row(only1, EMPTY), path)
        return
    # both rows closed
    if only1 or only2:
        raise InferError(
            "missing_field",
            "record is missing required field(s): " + ", ".join(sorted(set(only1) | set(only2))),
            path,
        )


def _bind_rvar(v: RVar, row: Row, path: str) -> None:
    if occurs_rvar_row(v, row):
        raise InferError(
            "infinite_type",
            "cannot construct an infinite row type",
            path,
        )
    v.instance = row


# -------------------------------------------------------- schemes / variables
class Scheme:
    """A type scheme: quantified type/row variable ids plus the body type."""

    __slots__ = ("qtvars", "qrvars", "type")

    def __init__(self, qtvars, qrvars, body: Type):
        self.qtvars = qtvars
        self.qrvars = qrvars
        self.type = body

    @staticmethod
    def mono(t: Type) -> "Scheme":
        return Scheme(frozenset(), frozenset(), t)


def free_vars(t: Type, tvars: Set[int], rvars: Set[int]) -> None:
    t = prune(t)
    if isinstance(t, TVar):
        tvars.add(t.id)
    elif isinstance(t, TFun):
        free_vars(t.param, tvars, rvars)
        free_vars(t.result, tvars, rvars)
    elif isinstance(t, TRecord):
        free_vars_row(t.row, tvars, rvars)


def free_vars_row(row: Row, tvars: Set[int], rvars: Set[int]) -> None:
    row = norm_row(row)
    for ft in row.fields.values():
        free_vars(ft, tvars, rvars)
    if isinstance(row.tail, RVar):
        rvars.add(row.tail.id)


def generalize(env_schemes: Iterator[Scheme], t: Type) -> Scheme:
    """Quantify the variables of ``t`` not free in the current environment."""
    env_t: Set[int] = set()
    env_r: Set[int] = set()
    for scheme in env_schemes:
        st: Set[int] = set()
        sr: Set[int] = set()
        free_vars(scheme.type, st, sr)
        env_t |= st - set(scheme.qtvars)
        env_r |= sr - set(scheme.qrvars)
    tt: Set[int] = set()
    tr: Set[int] = set()
    free_vars(t, tt, tr)
    return Scheme(frozenset(tt - env_t), frozenset(tr - env_r), t)


def instantiate(ctx: Ctx, scheme: Scheme) -> Type:
    """Fresh copy of the scheme body with new variables for the quantified ones."""
    if not scheme.qtvars and not scheme.qrvars:
        return scheme.type
    tmap = {q: ctx.fresh_tvar() for q in scheme.qtvars}
    rmap = {q: ctx.fresh_rvar() for q in scheme.qrvars}
    return _inst(scheme.type, tmap, rmap)


def _inst(t: Type, tmap: Dict[int, TVar], rmap: Dict[int, RVar]) -> Type:
    t = prune(t)
    if isinstance(t, TVar):
        return tmap.get(t.id, t)
    if isinstance(t, TFun):
        return TFun(_inst(t.param, tmap, rmap), _inst(t.result, tmap, rmap))
    if isinstance(t, TRecord):
        row = norm_row(t.row)
        fields = {k: _inst(v, tmap, rmap) for k, v in row.fields.items()}
        tail = row.tail
        if isinstance(tail, RVar):
            tail = rmap.get(tail.id, tail)
        return TRecord(Row(fields, tail))
    return t
