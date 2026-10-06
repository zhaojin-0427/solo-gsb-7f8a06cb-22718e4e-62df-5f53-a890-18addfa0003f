"""Types, rows, unification and type schemes.

Types:

    Int, Bool, t (unification variable), T1 -> T2, {row}

Rows (Rémy-style, with "lacks" constraints on row variables):

    {}                       closed empty row (REMPTY)
    {l: T, ... | r}          extension chain ending in a row variable
    r                        row variable; r.lacks is the set of field names
                             the variable must NOT be instantiated with

Unification variables are mutable: ``instance`` starts as None and is set
once, ``prune``/``prune_row`` follow the chain.
"""

from __future__ import annotations

from itertools import count

from .errors import InfiniteTypeError, MissingFieldError, TypeConflictError

_ids = count()


# ---------------------------------------------------------------------------
# Types and rows
# ---------------------------------------------------------------------------

class Type:
    __slots__ = ()


class TInt(Type):
    __slots__ = ()


class TBool(Type):
    __slots__ = ()


INT = TInt()
BOOL = TBool()


class TVar(Type):
    __slots__ = ("id", "instance")

    def __init__(self):
        self.id = next(_ids)
        self.instance: Type | None = None


class TFun(Type):
    __slots__ = ("param", "result")

    def __init__(self, param: Type, result: Type):
        self.param = param
        self.result = result


class TRecord(Type):
    __slots__ = ("row",)

    def __init__(self, row: "Row"):
        self.row = row


class Row:
    __slots__ = ()


class REmpty(Row):
    """The closed empty row: no further fields."""
    __slots__ = ()


REMPTY = REmpty()


class RVar(Row):
    """Row variable. ``lacks``: field names this variable may never contain."""

    __slots__ = ("id", "lacks", "instance")

    def __init__(self, lacks=()):
        self.id = next(_ids)
        self.lacks = frozenset(lacks)
        self.instance: Row | None = None


class RExtend(Row):
    __slots__ = ("label", "type", "rest")

    def __init__(self, label: str, type_: Type, rest: Row):
        self.label = label
        self.type = type_
        self.rest = rest


def prune(t: Type) -> Type:
    while isinstance(t, TVar) and t.instance is not None:
        t = t.instance
    return t


def prune_row(r: Row) -> Row:
    while isinstance(r, RVar) and r.instance is not None:
        r = r.instance
    return r


def build_row(fields: dict[str, Type], tail: Row) -> Row:
    row = tail
    for label in sorted(fields, reverse=True):
        row = RExtend(label, fields[label], row)
    return row


def flatten_row(row: Row) -> tuple[dict[str, Type], Row]:
    """Flatten an extension chain into (fields, tail) where tail is
    REMPTY or an unbound RVar."""
    fields: dict[str, Type] = {}
    while True:
        row = prune_row(row)
        if isinstance(row, RExtend):
            fields[row.label] = row.type  # no duplicates by construction
            row = row.rest
        else:
            return fields, row


# ---------------------------------------------------------------------------
# Occurs checks (infinite-type prevention)
# ---------------------------------------------------------------------------

def occurs_type(var: TVar, t: Type) -> bool:
    t = prune(t)
    if t is var:
        return True
    if isinstance(t, TFun):
        return occurs_type(var, t.param) or occurs_type(var, t.result)
    if isinstance(t, TRecord):
        return _occurs_type_row(var, t.row)
    return False


def _occurs_type_row(var: TVar, row: Row) -> bool:
    row = prune_row(row)
    if isinstance(row, RExtend):
        return occurs_type(var, row.type) or _occurs_type_row(var, row.rest)
    return False


def occurs_row(var: RVar, row: Row) -> bool:
    row = prune_row(row)
    if row is var:
        return True
    if isinstance(row, RExtend):
        return _occurs_row_type(var, row.type) or occurs_row(var, row.rest)
    return False


def _occurs_row_type(var: RVar, t: Type) -> bool:
    t = prune(t)
    if isinstance(t, TFun):
        return _occurs_row_type(var, t.param) or _occurs_row_type(var, t.result)
    if isinstance(t, TRecord):
        return occurs_row(var, t.row)
    return False


# ---------------------------------------------------------------------------
# Unification
# ---------------------------------------------------------------------------

def unify(a: Type, b: Type, path: str) -> None:
    a = prune(a)
    b = prune(b)
    if a is b:
        return
    if isinstance(a, TVar):
        _bind_tvar(a, b, path)
        return
    if isinstance(b, TVar):
        _bind_tvar(b, a, path)
        return
    if isinstance(a, TInt) and isinstance(b, TInt):
        return
    if isinstance(a, TBool) and isinstance(b, TBool):
        return
    if isinstance(a, TFun) and isinstance(b, TFun):
        unify(a.param, b.param, path)
        unify(a.result, b.result, path)
        return
    if isinstance(a, TRecord) and isinstance(b, TRecord):
        unify_row(a.row, b.row, path)
        return
    raise TypeConflictError(
        f"type conflict: {show_type(a)} does not match {show_type(b)}", path)


def _bind_tvar(var: TVar, t: Type, path: str) -> None:
    if occurs_type(var, t):
        raise InfiniteTypeError(
            f"cannot construct the infinite type "
            f"{show_type(var)} = {show_type(t)}", path)
    var.instance = t


def _bind_rvar(var: RVar, row: Row, path: str) -> None:
    if occurs_row(var, row):
        raise InfiniteTypeError("cannot construct an infinite record type", path)
    var.instance = row


def unify_row(row1: Row, row2: Row, path: str) -> None:
    fields1, tail1 = flatten_row(row1)
    fields2, tail2 = flatten_row(row2)

    for label in fields1.keys() & fields2.keys():
        unify(fields1[label], fields2[label], path)

    only1 = {l: t for l, t in fields1.items() if l not in fields2}
    only2 = {l: t for l, t in fields2.items() if l not in fields1}
    closed1 = isinstance(tail1, REmpty)
    closed2 = isinstance(tail2, REmpty)

    if closed1 and only2:
        raise MissingFieldError(
            f"record is missing field '{sorted(only2)[0]}'", path)
    if closed2 and only1:
        raise MissingFieldError(
            f"record is missing field '{sorted(only1)[0]}'", path)
    if closed1 and closed2:
        return

    if tail1 is tail2:
        # Same open tail on both sides: leftover fields can never match,
        # because the shared tail may not contain any of them.
        if not only1 and not only2:
            return
        label = sorted(set(only1) | set(only2))[0]
        raise TypeConflictError(
            f"record field '{label}' cannot be present on only one side "
            f"of a shared record type", path)

    if not closed1 and not closed2:
        # Two distinct open tails: link each to the other's extra fields
        # over a fresh shared tail.
        _check_lacks(tail1, only2, path)
        _check_lacks(tail2, only1, path)
        tail = RVar(lacks=tail1.lacks | tail2.lacks
                    | fields1.keys() | fields2.keys())
        _bind_rvar(tail1, build_row(only2, tail), path)
        _bind_rvar(tail2, build_row(only1, tail), path)
        return

    if not closed1:  # tail2 is REMPTY
        _check_lacks(tail1, only2, path)
        _bind_rvar(tail1, build_row(only2, REMPTY), path)
        return

    # tail1 is REMPTY, tail2 is a variable
    _check_lacks(tail2, only1, path)
    _bind_rvar(tail2, build_row(only1, REMPTY), path)


def _check_lacks(var: RVar, fields: dict[str, Type], path: str) -> None:
    bad = sorted(var.lacks & fields.keys())
    if bad:
        raise TypeConflictError(
            f"record field '{bad[0]}' is both required and excluded "
            f"for the same record type", path)


# ---------------------------------------------------------------------------
# Free variables, schemes, generalization, instantiation
# ---------------------------------------------------------------------------

def free_vars_type(t: Type, tvars: dict[int, TVar], rvars: dict[int, RVar]) -> None:
    t = prune(t)
    if isinstance(t, TVar):
        tvars.setdefault(t.id, t)
    elif isinstance(t, TFun):
        free_vars_type(t.param, tvars, rvars)
        free_vars_type(t.result, tvars, rvars)
    elif isinstance(t, TRecord):
        free_vars_row(t.row, tvars, rvars)


def free_vars_row(row: Row, tvars: dict[int, TVar], rvars: dict[int, RVar]) -> None:
    row = prune_row(row)
    if isinstance(row, RVar):
        rvars.setdefault(row.id, row)
    elif isinstance(row, RExtend):
        free_vars_type(row.type, tvars, rvars)
        free_vars_row(row.rest, tvars, rvars)


class Scheme:
    """A type scheme: a type with some of its variables quantified."""

    __slots__ = ("type", "qt", "qr", "_qt_ids", "_qr_ids")

    def __init__(self, type_: Type, qt=(), qr=()):
        self.type = type_
        self.qt: tuple[TVar, ...] = tuple(qt)
        self.qr: tuple[RVar, ...] = tuple(qr)
        self._qt_ids = frozenset(v.id for v in self.qt)
        self._qr_ids = frozenset(v.id for v in self.qr)

    def free_var_ids(self) -> tuple[set[int], set[int]]:
        tvars, rvars = {}, {}
        free_vars_type(self.type, tvars, rvars)
        return set(tvars) - self._qt_ids, set(rvars) - self._qr_ids


def generalize(env: dict[str, Scheme], type_: Type) -> Scheme:
    """Quantify exactly the type/row variables of ``type_`` that do not
    occur free in the current environment."""
    env_tv: set[int] = set()
    env_rv: set[int] = set()
    for scheme in env.values():
        tv, rv = scheme.free_var_ids()
        env_tv |= tv
        env_rv |= rv
    tvars, rvars = {}, {}
    free_vars_type(type_, tvars, rvars)
    qt = [v for k, v in tvars.items() if k not in env_tv]
    qr = [v for k, v in rvars.items() if k not in env_rv]
    return Scheme(type_, qt, qr)


def instantiate(scheme: Scheme) -> Type:
    """Fresh independent copy of the scheme's quantified variables.
    Row variables keep their ``lacks`` constraints."""
    if not scheme.qt and not scheme.qr:
        return scheme.type
    tmap = {v.id: TVar() for v in scheme.qt}
    rmap = {v.id: RVar(lacks=v.lacks) for v in scheme.qr}
    return _inst_type(scheme.type, tmap, rmap)


def _inst_type(t: Type, tmap: dict[int, TVar], rmap: dict[int, RVar]) -> Type:
    t = prune(t)
    if isinstance(t, TVar):
        return tmap.get(t.id, t)
    if isinstance(t, TFun):
        return TFun(_inst_type(t.param, tmap, rmap),
                    _inst_type(t.result, tmap, rmap))
    if isinstance(t, TRecord):
        return TRecord(_inst_row(t.row, tmap, rmap))
    return t


def _inst_row(row: Row, tmap: dict[int, TVar], rmap: dict[int, RVar]) -> Row:
    row = prune_row(row)
    if isinstance(row, RVar):
        return rmap.get(row.id, row)
    if isinstance(row, RExtend):
        return RExtend(row.label, _inst_type(row.type, tmap, rmap),
                       _inst_row(row.rest, tmap, rmap))
    return row


# ---------------------------------------------------------------------------
# Pretty printing (error messages only)
# ---------------------------------------------------------------------------

def show_type(t: Type) -> str:
    t = prune(t)
    if isinstance(t, TInt):
        return "Int"
    if isinstance(t, TBool):
        return "Bool"
    if isinstance(t, TVar):
        return f"t{t.id}"
    if isinstance(t, TFun):
        return f"({show_type(t.param)} -> {show_type(t.result)})"
    if isinstance(t, TRecord):
        fields, tail = flatten_row(t.row)
        parts = [f"{l}: {show_type(ft)}" for l, ft in sorted(fields.items())]
        if isinstance(tail, RVar):
            parts.append(f"..r{tail.id}")
        return "{" + ", ".join(parts) + "}"
    return "?"
