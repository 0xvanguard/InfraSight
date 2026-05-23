"""Punto de entrada de la API de InfraSight."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import close_pool, init_pool
from .routers import ingest, query


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(
    title="InfraSight API",
    description=(
        "API de ingesta y consulta de InfraSight. Versión M1: walking "
        "skeleton con endpoints de enrolamiento, heartbeat, métricas y "
        "consulta de dispositivos."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allow_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Sonda de liveness simple. La revisa el healthcheck de compose."""
    return {"status": "ok"}


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "bad_request", "message": str(exc)},
    )


app.include_router(ingest.router)
app.include_router(query.router)
