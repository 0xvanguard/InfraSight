"""Endpoints orientados al agente: /v1/enroll, /v1/heartbeat, /v1/metrics."""

from __future__ import annotations

import json
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from ..config import settings
from ..db import acquire
from ..schemas import (
    AgentConfig,
    EnrollRequest,
    EnrollResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    IngestBatch,
)
from ..security import (
    generate_device_token,
    hash_token,
    lookup_device_by_token,
)

router = APIRouter(prefix="/v1", tags=["ingest"])


def _agent_config() -> AgentConfig:
    return AgentConfig(
        collect_interval_s=settings.agent_collect_interval_s,
        heartbeat_interval_s=settings.agent_heartbeat_interval_s,
        max_batch_bytes=settings.agent_max_batch_bytes,
    )


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_token",
                "message": "Falta cabecera Authorization con esquema Bearer",
            },
        )
    return authorization.split(" ", 1)[1].strip()


# -----------------------------------------------------------------------------
# POST /v1/enroll
# -----------------------------------------------------------------------------
@router.post(
    "/enroll",
    response_model=EnrollResponse,
    status_code=status.HTTP_200_OK,
)
async def enroll(
    body: EnrollRequest,
    authorization: Annotated[str | None, Header()] = None,
    conn: asyncpg.Connection = Depends(acquire),
) -> EnrollResponse:
    token = _extract_bearer(authorization)
    if token != settings.enrollment_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_token",
                "message": "Token de enrolamiento incorrecto",
            },
        )

    org_id = settings.default_org_id

    async with conn.transaction():
        # Upsert idempotente por (org_id, machine_id).
        device_row = await conn.fetchrow(
            """
            INSERT INTO devices
                (org_id, hostname, machine_id, os, kernel, agent_version,
                 enrolled_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $6, now(), now())
            ON CONFLICT (org_id, machine_id) DO UPDATE
                SET hostname      = EXCLUDED.hostname,
                    os            = EXCLUDED.os,
                    kernel        = EXCLUDED.kernel,
                    agent_version = EXCLUDED.agent_version,
                    last_seen_at  = now()
            RETURNING id
            """,
            org_id,
            body.hostname,
            body.machine_id,
            body.os,
            body.kernel,
            body.agent_version,
        )
        device_id = device_row["id"]

        # Revocamos tokens previos del dispositivo y emitimos uno nuevo.
        await conn.execute(
            """
            UPDATE device_tokens
            SET    revoked_at = now()
            WHERE  device_id  = $1
              AND  revoked_at IS NULL
            """,
            device_id,
        )

        device_token = generate_device_token()
        await conn.execute(
            """
            INSERT INTO device_tokens (device_id, token_hash)
            VALUES ($1, $2)
            """,
            device_id,
            hash_token(device_token),
        )

    return EnrollResponse(
        device_id=device_id,
        device_token=device_token,
        config=_agent_config(),
    )


# -----------------------------------------------------------------------------
# POST /v1/heartbeat
# -----------------------------------------------------------------------------
@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    status_code=status.HTTP_200_OK,
)
async def heartbeat(
    body: HeartbeatRequest,
    authorization: Annotated[str | None, Header()] = None,
    conn: asyncpg.Connection = Depends(acquire),
) -> HeartbeatResponse:
    token = _extract_bearer(authorization)
    device = await lookup_device_by_token(conn, token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_token",
                "message": "Token de dispositivo desconocido o revocado",
            },
        )

    await conn.execute(
        """
        UPDATE devices
        SET    last_seen_at  = now(),
               agent_version = COALESCE($2, agent_version)
        WHERE  id = $1
        """,
        device["device_id"],
        body.agent_version,
    )

    return HeartbeatResponse(config=_agent_config())


# -----------------------------------------------------------------------------
# POST /v1/metrics
# -----------------------------------------------------------------------------
@router.post("/metrics", status_code=status.HTTP_204_NO_CONTENT)
async def ingest_metrics(
    batch: IngestBatch,
    authorization: Annotated[str | None, Header()] = None,
    conn: asyncpg.Connection = Depends(acquire),
) -> Response:
    token = _extract_bearer(authorization)
    device = await lookup_device_by_token(conn, token)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_token",
                "message": "Token de dispositivo desconocido o revocado",
            },
        )

    device_id = device["device_id"]
    org_id = device["org_id"]

    rows = [
        (
            sample.ts,
            org_id,
            device_id,
            sample.metric,
            float(sample.value),
            json.dumps(sample.labels),
        )
        for sample in batch.samples
    ]

    async with conn.transaction():
        await conn.executemany(
            """
            INSERT INTO metrics (ts, org_id, device_id, metric, value, labels)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            rows,
        )
        await conn.execute(
            "UPDATE devices SET last_seen_at = now() WHERE id = $1",
            device_id,
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
