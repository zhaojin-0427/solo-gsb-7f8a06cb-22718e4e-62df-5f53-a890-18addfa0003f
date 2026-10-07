"""HTTP API for rule-expression type inference.

* ``POST /infer`` — infer the principal type scheme of a JSON expression tree.
* ``GET  /health`` — liveness probe.
* ``GET  /``       — service info.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import InferError
from .infer import infer
from .parser import MAX_DEPTH, MAX_NODES, parse_expression
from .serialize import serialize_scheme
from .typesys import Ctx

app = FastAPI(
    title="Rule Expression Type Inference",
    version="1.0.0",
    description=(
        "Infers principal type schemes (Hindley–Milner with row-polymorphic "
        "records) for rule expression trees, for pre-publish validation."
    ),
)

# If the body is not itself an expression node, look for a wrapper key.
_WRAPPER_KEYS = ("expression", "expr", "root", "tree", "ast")
_DISCRIMINATOR_KEYS = ("kind", "type", "tag", "node")


def _error(code: str, message: str, path: str = "/") -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": code, "message": message, "path": path}},
    )


@app.get("/")
def index():
    return {
        "service": "rule-expression-type-inference",
        "usage": "POST /infer with a JSON expression tree",
        "limits": {"max_nodes": MAX_NODES, "max_depth": MAX_DEPTH},
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/infer")
async def infer_endpoint(request: Request):
    try:
        body = await request.json()
    except RecursionError:
        return _error("too_deep", "JSON nesting is too deep")
    except Exception:
        return _error("invalid_json", "request body is not valid JSON")

    data = body
    if isinstance(data, dict) and not any(k in data for k in _DISCRIMINATOR_KEYS):
        for key in _WRAPPER_KEYS:
            if key in data:
                data = data[key]
                break

    try:
        expr = parse_expression(data)
        ctx = Ctx()
        ty = infer(ctx, None, expr, "")
        scheme = serialize_scheme(ty)
    except InferError as exc:
        return _error(exc.code, exc.message, exc.path)
    except RecursionError:
        return _error("too_deep", "expression nesting is too deep")

    return {"type_scheme": scheme}
