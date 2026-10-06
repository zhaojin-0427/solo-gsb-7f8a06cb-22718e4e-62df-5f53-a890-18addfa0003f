"""FastAPI application exposing POST /infer."""

import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import InferError
from .infer import infer_scheme, render_scheme
from .model import parse

sys.setrecursionlimit(10000)

app = FastAPI(
    title="Rule Expression Type Inference",
    version="1.0.0",
    description="Infers principal type schemes for rule expression trees.",
)


def _error(kind: str, message: str, path: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"kind": kind, "message": message, "path": path}},
    )


@app.post("/infer")
async def infer_endpoint(request: Request):
    try:
        data = await request.json()
    except Exception:
        return _error("structural", "request body must be valid JSON", "$")
    try:
        node = parse(data)
        scheme = infer_scheme(node)
    except InferError as exc:
        return _error(exc.kind, exc.message, exc.path)
    return {"scheme": render_scheme(scheme)}


@app.get("/health")
async def health():
    return {"status": "ok"}
