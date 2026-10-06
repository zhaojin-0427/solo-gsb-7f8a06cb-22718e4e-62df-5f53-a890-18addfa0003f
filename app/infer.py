"""Algorithm W with let-generalization and row-polymorphic records,
plus rendering of the principal type scheme as JSON."""

from __future__ import annotations

from . import model
from .errors import UnboundVariableError
from .typesys import (
    BOOL,
    INT,
    REMPTY,
    REmpty,
    RExtend,
    RVar,
    Scheme,
    TBool,
    TFun,
    TInt,
    TRecord,
    TVar,
    build_row,
    flatten_row,
    generalize,
    instantiate,
    prune,
    prune_row,
    unify,
)

Env = dict[str, Scheme]


def infer(env: Env, node: model.Node, path: str = "$"):
    """Infer the type of ``node`` under ``env``. ``path`` is the
    JSONPath-style location of the node, used in error reports."""
    if isinstance(node, model.IntLit):
        return INT
    if isinstance(node, model.BoolLit):
        return BOOL

    if isinstance(node, model.Var):
        scheme = env.get(node.name)
        if scheme is None:
            raise UnboundVariableError(f"unbound variable '{node.name}'", path)
        return instantiate(scheme)

    if isinstance(node, model.Lambda):
        # Lambda parameters stay monomorphic inside the body.
        param_type = TVar()
        body_env = {**env, node.param: Scheme(param_type)}
        body_type = infer(body_env, node.body, path + ".body")
        return TFun(param_type, body_type)

    if isinstance(node, model.Call):
        fn_type = infer(env, node.fn, path + ".fn")
        arg_type = infer(env, node.arg, path + ".arg")
        result_type = TVar()
        # The argument type must unify with the parameter type.
        unify(fn_type, TFun(arg_type, result_type), path)
        return result_type

    if isinstance(node, model.Let):
        # Non-recursive: the value is inferred in the unextended env.
        value_type = infer(env, node.value, path + ".value")
        # Generalize only variables not free in the current environment;
        # every later reference instantiates an independent copy.
        scheme = generalize(env, value_type)
        body_env = {**env, node.name: scheme}
        return infer(body_env, node.body, path + ".body")

    if isinstance(node, model.Record):
        # Record literals are closed records.
        fields = {}
        for i, (name, sub) in enumerate(node.fields):
            fields[name] = infer(env, sub, f"{path}.fields[{i}].value")
        return TRecord(build_row(fields, REMPTY))

    if isinstance(node, model.Field):
        # Field access: an open record that must contain the field but
        # allows any other fields; the row variable lacks the listed field.
        record_type = infer(env, node.record, path + ".record")
        result_type = TVar()
        tail = RVar(lacks={node.name})
        unify(record_type, TRecord(RExtend(node.name, result_type, tail)), path)
        return result_type

    raise AssertionError(f"unexpected node: {node!r}")


def infer_scheme(node: model.Node) -> Scheme:
    """Infer the principal type scheme of a closed expression."""
    type_ = infer({}, node)
    return generalize({}, type_)


# ---------------------------------------------------------------------------
# JSON rendering of the principal scheme
# ---------------------------------------------------------------------------

class _Namer:
    """Assigns canonical names (t0, t1, ... / r0, r1, ...) in order of
    first occurrence."""

    def __init__(self):
        self.t_names: dict[int, str] = {}
        self.r_names: dict[int, str] = {}

    def tname(self, var: TVar) -> str:
        if var.id not in self.t_names:
            self.t_names[var.id] = f"t{len(self.t_names)}"
        return self.t_names[var.id]

    def rname(self, var: RVar) -> str:
        if var.id not in self.r_names:
            self.r_names[var.id] = f"r{len(self.r_names)}"
        return self.r_names[var.id]


def render_scheme(scheme: Scheme) -> dict:
    namer = _Namer()
    type_json = render_type(scheme.type, namer)
    return {
        "forall": {
            "type_vars": list(namer.t_names.values()),
            "row_vars": list(namer.r_names.values()),
        },
        "type": type_json,
    }


def render_type(t, namer: _Namer) -> dict:
    t = prune(t)
    if isinstance(t, TInt):
        return {"kind": "int"}
    if isinstance(t, TBool):
        return {"kind": "bool"}
    if isinstance(t, TVar):
        return {"kind": "var", "name": namer.tname(t)}
    if isinstance(t, TFun):
        return {
            "kind": "fun",
            "param": render_type(t.param, namer),
            "result": render_type(t.result, namer),
        }
    if isinstance(t, TRecord):
        fields, tail = flatten_row(t.row)
        return {
            "kind": "record",
            "fields": [
                {"name": label, "type": render_type(field_type, namer)}
                for label, field_type in sorted(fields.items())
            ],
            "tail": _render_tail(tail, namer),
        }
    raise AssertionError(f"cannot render type: {t!r}")


def _render_tail(tail, namer: _Namer) -> dict:
    tail = prune_row(tail)
    if isinstance(tail, REmpty):
        return {"kind": "closed"}
    return {
        "kind": "open",
        "var": namer.rname(tail),
        "lacks": sorted(tail.lacks),
    }
