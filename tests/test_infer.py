"""End-to-end tests: JSON in, type scheme / 422 error out."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ------------------------------------------------------------ expression builders
def I(v):
    return {"kind": "int", "value": v}


def B(v):
    return {"kind": "bool", "value": v}


def V(n):
    return {"kind": "var", "name": n}


def lam(p, b):
    return {"kind": "lambda", "param": p, "body": b}


def call(f, a):
    return {"kind": "call", "func": f, "arg": a}


def let(n, v, b):
    return {"kind": "let", "name": n, "value": v, "body": b}


def rec(**fields):
    return {"kind": "record", "fields": [{"name": k, "value": v} for k, v in fields.items()]}


def fld(r, name):
    return {"kind": "field", "record": r, "field": name}


def infer(expr):
    return client.post("/infer", json=expr)


# ------------------------------------------------------------------ success cases
def test_int_literal():
    r = infer(I(42))
    assert r.status_code == 200
    s = r.json()["type_scheme"]
    assert s["type"] == {"kind": "int"}
    assert s["quantified"] == {"type_vars": [], "row_vars": []}
    assert s["pretty"] == "int"


def test_bool_literal():
    r = infer(B(True))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {"kind": "bool"}


def test_identity_lambda():
    r = infer(lam("x", V("x")))
    assert r.status_code == 200
    s = r.json()["type_scheme"]
    assert s["quantified"]["type_vars"] == ["a"]
    assert s["quantified"]["row_vars"] == []
    assert s["type"] == {
        "kind": "fun",
        "param": {"kind": "var", "name": "a"},
        "result": {"kind": "var", "name": "a"},
    }
    assert s["pretty"] == "∀ a. a → a"


def test_const_lambda():
    r = infer(lam("x", lam("y", V("x"))))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["pretty"] == "∀ a b. a → b → a"


def test_apply_identity_to_int():
    r = infer(call(lam("x", V("x")), I(1)))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {"kind": "int"}


def test_let_polymorphism_independent_instantiation():
    # let id = λx. x in {n: id 1, b: id true}  →  {b: bool, n: int}
    expr = let("id", lam("x", V("x")), rec(n=call(V("id"), I(1)), b=call(V("id"), B(True))))
    r = infer(expr)
    assert r.status_code == 200
    s = r.json()["type_scheme"]
    assert s["quantified"] == {"type_vars": [], "row_vars": []}
    assert s["type"] == {
        "kind": "record",
        "fields": [
            {"name": "b", "type": {"kind": "bool"}},
            {"name": "n", "type": {"kind": "int"}},
        ],
        "tail": {"kind": "empty"},
    }


def test_let_value_not_generalised_below_lambda():
    # λx. let y = x in y  →  ∀ a. a → a   (y is monomorphic, tied to x)
    r = infer(lam("x", let("y", V("x"), V("y"))))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["pretty"] == "∀ a. a → a"


def test_lambda_param_is_monomorphic():
    # λf. {a: f 1, b: f true} must fail: f used at two different types
    expr = lam("f", rec(a=call(V("f"), I(1)), b=call(V("f"), B(True))))
    r = infer(expr)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "type_mismatch"


def test_record_literal_is_closed():
    r = infer(rec(a=I(1), b=B(False)))
    assert r.status_code == 200
    s = r.json()["type_scheme"]
    assert s["type"]["tail"] == {"kind": "empty"}
    assert s["pretty"] == "{a: int, b: bool}"


def test_field_access_open_record():
    # λr. r.a  →  ∀ a r0. {a: a | r0} → a
    r = infer(lam("r", fld(V("r"), "a")))
    assert r.status_code == 200
    s = r.json()["type_scheme"]
    assert s["quantified"] == {"type_vars": ["a"], "row_vars": ["r0"]}
    assert s["type"] == {
        "kind": "fun",
        "param": {
            "kind": "record",
            "fields": [{"name": "a", "type": {"kind": "var", "name": "a"}}],
            "tail": {"kind": "row_var", "name": "r0", "excludes": ["a"]},
        },
        "result": {"kind": "var", "name": "a"},
    }
    assert s["pretty"] == "∀ a r0. {a: a | r0} → a"


def test_field_access_two_fields_merges_rows():
    # λr. {x: r.a, y: r.b}  →  ∀ a b r0. {a: a, b: b | r0} → {x: a, y: b}
    expr = lam("r", rec(x=fld(V("r"), "a"), y=fld(V("r"), "b")))
    r = infer(expr)
    assert r.status_code == 200
    s = r.json()["type_scheme"]
    assert s["pretty"] == "∀ a b r0. {a: a, b: b | r0} → {x: a, y: b}"
    param = s["type"]["param"]
    assert param["tail"] == {"kind": "row_var", "name": "r0", "excludes": ["a", "b"]}


def test_field_access_on_record_literal():
    r = infer(fld(rec(a=I(1), b=B(True)), "a"))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {"kind": "int"}


def test_row_polymorphism_through_let():
    # let get = λr. r.a in {x: get {a: 1}, y: get {a: true, b: 2}} → {x: int, y: bool}
    expr = let(
        "get",
        lam("r", fld(V("r"), "a")),
        rec(
            x=call(V("get"), rec(a=I(1))),
            y=call(V("get"), rec(a=B(True), b=I(2))),
        ),
    )
    r = infer(expr)
    assert r.status_code == 200
    assert r.json()["type_scheme"]["pretty"] == "{x: int, y: bool}"


def test_nested_field_access():
    r = infer(fld(fld(rec(a=rec(b=I(7))), "a"), "b"))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {"kind": "int"}


def test_shadowing():
    r = infer(let("x", I(1), let("x", B(True), V("x"))))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {"kind": "bool"}


def test_empty_record():
    r = infer({"kind": "record", "fields": []})
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {
        "kind": "record",
        "fields": [],
        "tail": {"kind": "empty"},
    }


def test_higher_order():
    # λf. λx. f (f x)  →  ∀ a. (a → a) → a → a
    r = infer(lam("f", lam("x", call(V("f"), call(V("f"), V("x"))))))
    assert r.status_code == 200
    assert r.json()["type_scheme"]["pretty"] == "∀ a. (a → a) → a → a"


def test_wrapper_key_and_type_alias():
    # body wrapped in {"expression": ...} and "type" used as discriminator
    r = client.post("/infer", json={"expression": {"type": "int", "value": 3}})
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"] == {"kind": "int"}


# -------------------------------------------------------------------- error cases
def test_unbound_variable():
    r = infer(V("nope"))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "unbound_variable"
    assert err["path"] == "/"
    assert "type_scheme" not in r.json()


def test_unbound_variable_path():
    r = infer(lam("x", call(V("x"), V("y"))))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "unbound_variable"
    assert err["path"] == "/body/arg"


def test_let_is_not_recursive():
    r = infer(let("x", V("x"), I(1)))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "unbound_variable"
    assert err["path"] == "/value"


def test_infinite_type():
    r = infer(lam("x", call(V("x"), V("x"))))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "infinite_type"
    assert err["path"] == "/body"


def test_infinite_type_through_record():
    # λr. (r.a) r  —  r's type would have to contain itself
    r = infer(lam("r", call(fld(V("r"), "a"), V("r"))))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "infinite_type"


def test_type_mismatch_int_bool():
    # λx. if-ish: force x to be both int and bool via calls
    expr = lam("x", rec(a=call(lam("y", I(0)), V("x")), b=call(lam("y", B(True)), fld(V("x"), "a"))))
    # simpler deterministic conflict: apply an int
    r = infer(call(I(1), I(2)))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "type_mismatch"


def test_type_mismatch_param_arg():
    # (λr. r.a) 1  —  int is not a record
    r = infer(call(lam("r", fld(V("r"), "a")), I(1)))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "type_mismatch"


def test_missing_field():
    r = infer(fld(rec(a=I(1)), "b"))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "missing_field"
    assert "b" in err["message"]
    assert err["path"] == "/"


def test_missing_field_nested_path():
    r = infer(lam("x", fld(rec(a=I(1)), "zzz")))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "missing_field"
    assert err["path"] == "/body"


def test_field_access_on_int():
    r = infer(fld(I(5), "a"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "type_mismatch"


def test_duplicate_field():
    expr = {
        "kind": "record",
        "fields": [
            {"name": "a", "value": I(1)},
            {"name": "a", "value": I(2)},
        ],
    }
    r = infer(expr)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "duplicate_field"
    assert "a" in err["message"]


def test_closed_records_cannot_merge():
    # λf. {r1: f {a: 1}, r2: f {b: 2}} — f is monomorphic, so the two closed
    # record arguments must unify and neither has the other's field
    expr = lam("f", rec(r1=call(V("f"), rec(a=I(1))), r2=call(V("f"), rec(b=I(2)))))
    r = infer(expr)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "missing_field"


# ------------------------------------------------------------------ limits
def _deep(n):
    expr = V("x")
    for _ in range(n):
        expr = lam("x", expr)
    return expr


def _wide_record(n):
    # one record node + n int-literal field values, depth 2
    return {"kind": "record", "fields": [{"name": f"f{i}", "value": I(i)} for i in range(n)]}


def test_depth_limit_accepts_20():
    assert infer(_deep(19)).status_code == 200  # deepest node at depth 20


def test_depth_limit_rejects_21():
    r = infer(_deep(20))  # deepest node at depth 21
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "too_deep"


def test_node_limit_accepts_80():
    assert infer(_wide_record(79)).status_code == 200  # 79 + 1 = 80 nodes


def test_node_limit_rejects_81():
    r = infer(_wide_record(80))  # 80 + 1 = 81 nodes
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "too_many_nodes"


# ------------------------------------------------------------------ structural
def test_unknown_kind():
    r = infer({"kind": "if", "cond": B(True)})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_expression"


def test_missing_kind():
    r = infer({"value": 1})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_expression"


def test_int_value_must_be_int():
    for bad in (True, 1.5, "1", None):
        r = infer({"kind": "int", "value": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "invalid_expression"


def test_bool_value_must_be_bool():
    r = infer({"kind": "bool", "value": 1})
    assert r.status_code == 422


def test_body_not_object():
    r = infer([1, 2, 3])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_expression"


def test_invalid_json():
    r = client.post("/infer", content="{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_json"


def test_record_fields_must_be_array():
    r = infer({"kind": "record", "fields": 42})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_expression"


def test_record_field_pair_form():
    # ["name", expr] pairs are accepted too
    r = infer({"kind": "record", "fields": [["a", I(1)]]})
    assert r.status_code == 200
    assert r.json()["type_scheme"]["type"]["fields"] == [
        {"name": "a", "type": {"kind": "int"}}
    ]


def test_error_response_has_no_scheme():
    r = infer(V("x"))
    assert set(r.json().keys()) == {"error"}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
