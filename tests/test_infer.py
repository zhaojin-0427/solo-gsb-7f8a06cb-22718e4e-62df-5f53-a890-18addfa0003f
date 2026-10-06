"""End-to-end tests for POST /infer."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(expr):
    return client.post("/infer", json=expr)


def lam(param, body):
    return {"tag": "lambda", "param": param, "body": body}


def call(fn, arg):
    return {"tag": "call", "fn": fn, "arg": arg}


def let(name, value, body):
    return {"tag": "let", "name": name, "value": value, "body": body}


def var(name):
    return {"tag": "var", "name": name}


def num(n):
    return {"tag": "int", "value": n}


def boolean(b):
    return {"tag": "bool", "value": b}


def record(**fields):
    return {"tag": "record",
            "fields": [{"name": k, "value": v} for k, v in fields.items()]}


def field(rec, name):
    return {"tag": "field", "record": rec, "name": name}


IDENTITY = lam("x", var("x"))


# ---------------------------------------------------------------------------
# Successful inference
# ---------------------------------------------------------------------------

def test_int_literal():
    r = post(num(42))
    assert r.status_code == 200
    scheme = r.json()["scheme"]
    assert scheme["type"] == {"kind": "int"}
    assert scheme["forall"] == {"type_vars": [], "row_vars": []}


def test_bool_literal():
    r = post(boolean(True))
    assert r.status_code == 200
    assert r.json()["scheme"]["type"] == {"kind": "bool"}


def test_identity_is_polymorphic():
    r = post(IDENTITY)
    assert r.status_code == 200
    scheme = r.json()["scheme"]
    assert scheme["forall"] == {"type_vars": ["t0"], "row_vars": []}
    assert scheme["type"] == {
        "kind": "fun",
        "param": {"kind": "var", "name": "t0"},
        "result": {"kind": "var", "name": "t0"},
    }


def test_closed_record_literal():
    r = post(record(a=num(1), b=boolean(False)))
    assert r.status_code == 200
    t = r.json()["scheme"]["type"]
    assert t == {
        "kind": "record",
        "fields": [
            {"name": "a", "type": {"kind": "int"}},
            {"name": "b", "type": {"kind": "bool"}},
        ],
        "tail": {"kind": "closed"},
    }


def test_field_access_infers_open_record():
    r = post(lam("r", field(var("r"), "age")))
    assert r.status_code == 200
    scheme = r.json()["scheme"]
    assert scheme["forall"] == {"type_vars": ["t0"], "row_vars": ["r0"]}
    assert scheme["type"] == {
        "kind": "fun",
        "param": {
            "kind": "record",
            "fields": [{"name": "age", "type": {"kind": "var", "name": "t0"}}],
            # open tail excludes the already-listed field
            "tail": {"kind": "open", "var": "r0", "lacks": ["age"]},
        },
        "result": {"kind": "var", "name": "t0"},
    }


def test_field_access_on_closed_record():
    r = post(field(record(a=num(7)), "a"))
    assert r.status_code == 200
    assert r.json()["scheme"]["type"] == {"kind": "int"}


def test_open_record_absorbs_extra_fields():
    # (λr. r.a) {a: 1, b: true}  →  int
    r = post(call(lam("r", field(var("r"), "a")),
                  record(a=num(1), b=boolean(True))))
    assert r.status_code == 200
    assert r.json()["scheme"]["type"] == {"kind": "int"}


def test_let_generalizes_and_each_use_instantiates():
    # let id = λx. x in {a: id 1, b: id true}  →  {a: int, b: bool}
    expr = let("id", IDENTITY,
               record(a=call(var("id"), num(1)),
                      b=call(var("id"), boolean(True))))
    r = post(expr)
    assert r.status_code == 200
    t = r.json()["scheme"]["type"]
    assert t["fields"] == [
        {"name": "a", "type": {"kind": "int"}},
        {"name": "b", "type": {"kind": "bool"}},
    ]
    assert t["tail"] == {"kind": "closed"}


def test_let_generalizes_row_vars_per_use():
    # let get = λr. r.a in {x: get {a: 1}, y: get {a: true, b: 2}}
    #   →  {x: int, y: bool}
    get = lam("r", field(var("r"), "a"))
    expr = let("get", get,
               record(x=call(var("get"), record(a=num(1))),
                      y=call(var("get"), record(a=boolean(True), b=num(2)))))
    r = post(expr)
    assert r.status_code == 200
    assert r.json()["scheme"]["type"]["fields"] == [
        {"name": "x", "type": {"kind": "int"}},
        {"name": "y", "type": {"kind": "bool"}},
    ]


def test_let_does_not_generalize_env_free_vars():
    # λx. let y = x in y  →  t0 -> t0  (y must NOT become polymorphic)
    expr = lam("x", let("y", var("x"), var("y")))
    r = post(expr)
    assert r.status_code == 200
    scheme = r.json()["scheme"]
    assert scheme["forall"]["type_vars"] == ["t0"]
    assert scheme["type"] == {
        "kind": "fun",
        "param": {"kind": "var", "name": "t0"},
        "result": {"kind": "var", "name": "t0"},
    }


def test_let_shadowing():
    expr = let("x", num(1), let("x", boolean(True), var("x")))
    r = post(expr)
    assert r.status_code == 200
    assert r.json()["scheme"]["type"] == {"kind": "bool"}


def test_two_field_accesses_merge_rows():
    # λr. {x: r.a, y: r.b}  →  {a: t0, b: t1 | r0} -> {x: t0, y: t1}
    expr = lam("r", record(x=field(var("r"), "a"), y=field(var("r"), "b")))
    r = post(expr)
    assert r.status_code == 200
    scheme = r.json()["scheme"]
    param = scheme["type"]["param"]
    assert [f["name"] for f in param["fields"]] == ["a", "b"]
    assert param["tail"]["kind"] == "open"
    assert param["tail"]["lacks"] == ["a", "b"]
    assert scheme["forall"]["row_vars"] == [param["tail"]["var"]]


# ---------------------------------------------------------------------------
# Type errors (422, with node path, no scheme)
# ---------------------------------------------------------------------------

def check_error(expr, kind, path=None):
    r = post(expr)
    assert r.status_code == 422
    body = r.json()
    assert "scheme" not in body
    err = body["error"]
    assert err["kind"] == kind
    if path is not None:
        assert err["path"] == path
    return err


def test_unbound_variable():
    check_error(lam("x", var("y")), "unbound_variable", "$.body")


def test_unbound_variable_deep_path():
    expr = lam("x", lam("y", call(var("x"), var("z"))))
    check_error(expr, "unbound_variable", "$.body.body.arg")


def test_let_is_not_recursive():
    expr = let("x", var("x"), num(1))
    check_error(expr, "unbound_variable", "$.value")


def test_missing_field():
    expr = field(record(a=num(1)), "b")
    err = check_error(expr, "missing_field", "$")
    assert "'b'" in err["message"]


def test_missing_field_nested_path():
    expr = lam("r", field(record(a=var("r")), "zzz"))
    check_error(expr, "missing_field", "$.body")


def test_type_conflict_int_vs_bool():
    # λf. {a: f 1, b: f true} — lambda-bound f is monomorphic
    expr = lam("f", record(a=call(var("f"), num(1)),
                           b=call(var("f"), boolean(True))))
    check_error(expr, "type_conflict")


def test_type_conflict_calling_non_function():
    check_error(call(num(1), num(2)), "type_conflict", "$")


def test_infinite_type():
    # λx. x x
    check_error(lam("x", call(var("x"), var("x"))), "infinite_type")


def test_infinite_type_through_records():
    # λr. r {a = r}  — r occurs in its own record type
    expr = lam("r", call(var("r"), record(a=var("r"))))
    check_error(expr, "infinite_type")


# ---------------------------------------------------------------------------
# Structural errors (422)
# ---------------------------------------------------------------------------

def test_duplicate_record_fields():
    expr = {"tag": "record", "fields": [
        {"name": "a", "value": num(1)},
        {"name": "a", "value": num(2)},
    ]}
    check_error(expr, "structural", "$.fields[1]")


def test_unknown_tag():
    check_error({"tag": "plus", "a": num(1)}, "structural", "$")


def test_missing_key():
    check_error({"tag": "lambda", "param": "x"}, "structural", "$")


def test_int_value_must_not_be_bool():
    check_error({"tag": "int", "value": True}, "structural", "$")


def test_fields_must_be_array():
    check_error({"tag": "record", "fields": {"a": num(1)}}, "structural", "$")


def test_node_limit_80():
    expr = record(**{f"f{i}": num(i) for i in range(81)})  # 82 nodes
    err = check_error(expr, "structural")
    assert "80" in err["message"]


def test_node_limit_exactly_80_ok():
    expr = record(**{f"f{i}": num(i) for i in range(79)})  # 80 nodes
    assert post(expr).status_code == 200


def _nested_lets(n):
    expr = num(0)
    for i in range(n):
        expr = let(f"x{i}", num(i), expr)
    return expr


def test_depth_limit_20():
    err = check_error(_nested_lets(20), "structural")
    assert "depth" in err["message"]
    assert err["path"].startswith("$.body")


def test_depth_exactly_20_ok():
    assert post(_nested_lets(19)).status_code == 200


def test_invalid_json_body():
    r = client.post("/infer", content="{not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "structural"


def test_body_must_be_object():
    check_error([1, 2, 3], "structural", "$")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def test_health():
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("expr", [num(1), IDENTITY, record(a=num(1))])
def test_success_response_shape(expr):
    r = post(expr)
    assert r.status_code == 200
    scheme = r.json()["scheme"]
    assert set(scheme.keys()) == {"forall", "type"}
    assert set(scheme["forall"].keys()) == {"type_vars", "row_vars"}
