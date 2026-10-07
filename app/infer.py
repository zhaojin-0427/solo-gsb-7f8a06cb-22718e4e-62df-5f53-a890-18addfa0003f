"""Damas–Hindley–Milner inference over the expression AST."""
from __future__ import annotations

from typing import Iterator, Optional

from .astnodes import (BoolLit, Call, Expr, FieldAccess, IntLit, Lambda, Let,
                       Record, Var)
from .errors import InferError
from .typesys import (BOOL, EMPTY, INT, Ctx, Row, Scheme, TFun, TRecord, Type,
                      generalize, instantiate, unify)


class Env:
    """Lexical scope: a persistent (linked) mapping of names to schemes."""

    __slots__ = ("parent", "name", "scheme")

    def __init__(self, parent: Optional["Env"], name: str, scheme: Scheme):
        self.parent = parent
        self.name = name
        self.scheme = scheme


def lookup(env: Optional[Env], name: str) -> Optional[Scheme]:
    while env is not None:
        if env.name == name:
            return env.scheme
        env = env.parent
    return None


def env_schemes(env: Optional[Env]) -> Iterator[Scheme]:
    while env is not None:
        yield env.scheme
        env = env.parent


def infer(ctx: Ctx, env: Optional[Env], expr: Expr, path: str) -> Type:
    """Infer the type of ``expr``; ``path`` is the JSON Pointer of the node."""
    if isinstance(expr, IntLit):
        return INT
    if isinstance(expr, BoolLit):
        return BOOL

    if isinstance(expr, Var):
        scheme = lookup(env, expr.name)
        if scheme is None:
            raise InferError(
                "unbound_variable", f"unbound variable '{expr.name}'", path
            )
        # every reference instantiates the scheme independently
        return instantiate(ctx, scheme)

    if isinstance(expr, Lambda):
        # lambda parameters stay monomorphic
        param_t = ctx.fresh_tvar()
        body_t = infer(
            ctx, Env(env, expr.param, Scheme.mono(param_t)), expr.body, path + "/body"
        )
        return TFun(param_t, body_t)

    if isinstance(expr, Call):
        func_t = infer(ctx, env, expr.func, path + "/func")
        arg_t = infer(ctx, env, expr.arg, path + "/arg")
        result_t = ctx.fresh_tvar()
        # the argument type must unify with the parameter type
        unify(ctx, func_t, TFun(arg_t, result_t), path)
        return result_t

    if isinstance(expr, Let):
        # non-recursive: the bound name is not in scope inside its own value
        value_t = infer(ctx, env, expr.value, path + "/value")
        # generalise only variables not free in the current environment
        scheme = generalize(env_schemes(env), value_t)
        return infer(ctx, Env(env, expr.name, scheme), expr.body, path + "/body")

    if isinstance(expr, Record):
        # record literals are closed records
        fields = {}
        for i, (name, value_expr) in enumerate(expr.fields):
            fields[name] = infer(ctx, env, value_expr, f"{path}/fields/{i}/value")
        return TRecord(Row(fields, EMPTY))

    if isinstance(expr, FieldAccess):
        record_t = infer(ctx, env, expr.record, path + "/record")
        field_t = ctx.fresh_tvar()
        rest = ctx.fresh_rvar()
        # open record: extra fields allowed, but the row variable must not
        # mention the selected field again
        unify(ctx, record_t, TRecord(Row({expr.field: field_t}, rest)), path)
        return field_t

    raise InferError("invalid_expression", "unknown expression node", path)
