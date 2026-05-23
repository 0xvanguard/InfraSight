"""Endpoints orientados al dashboard: listado y detalle de dispositivos."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import settings
from ..db import acquire
from ..schemas import DeviceDetail, DeviceSummary, MetricSample

router = APIRouter(prefix="/v1", tags=["query"])


def _status_for(last_seen_at: datetime | None) -> str:
    if last_seen_at is None:
        return "offline"
    delta = (datetime.now(timezone.utc) - last_seen_at).total_seconds()
    if delta <= settings.offline_threshold_s:
        return "online"
    if delta <= settings.offline_threshold_s * 4:
        return "stale"
    return "offline"


@router.get("/devices", response_model=list[DeviceSummary])
async def list_devices(
    conn: asyncpg.Connection = Depends(acquire),
) -> list[DeviceSummary]:
    rows = await conn.fetch(
        """
        SELECT id, hostname, os, kernel, agent_version,
               enrolled_at, last_seen_at
        FROM   devices
        WHERE  org_id = $1
        ORDER  BY hostname
        """,
        settings.default_org_id,
    )
    return [
        DeviceSummary(
            id=row["id"],
            hostname=row["hostname"],
            os=row["os"],
            kernel=row["kernel"],
            agent_version=row["agent_version"],
            enrolled_at=row["enrolled_at"],
            last_seen_at=row["last_seen_at"],
            status=_status_for(row["last_seen_at"]),
        )
        for row in rows
    ]


@router.get("/devices/{device_id}", response_model=DeviceDetail)
async def get_device(
    device_id: UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    conn: asyncpg.Connection = Depends(acquire),
) -> DeviceDetail:
    row = await conn.fetchrow(
        """
        SELECT id, hostname, machine_id, os, kernel, agent_version,
               enrolled_at, last_seen_at
        FROM   devices
        WHERE  id = $1 AND org_id = $2
        """,
        device_id,
        settings.default_org_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Dispositivo no encontrado"},
        )

    metric_rows = await conn.fetch(
        """
        SELECT ts, metric, value, labels
        FROM   metrics
        WHERE  device_id = $1
        ORDER  BY ts DESC
        LIMIT  $2
        """,
        device_id,
        limit,
    )

    recent: list[MetricSample] = []
    for m in metric_rows:
        labels_raw = m["labels"]
        labels = json.loads(labels_raw) if isinstance(labels_raw, str) else (labels_raw or {})
        recent.append(
            MetricSample(
                ts=m["ts"],
                metric=m["metric"],
                value=float(m["value"]),
                labels=labels,
            )
        )

    return DeviceDetail(
        id=row["id"],
        hostname=row["hostname"],
        machine_id=row["machine_id"],
        os=row["os"],
        kernel=row["kernel"],
        agent_version=row["agent_version"],
        enrolled_at=row["enrolled_at"],
        last_seen_at=row["last_seen_at"],
        status=_status_for(row["last_seen_at"]),
        recent_metrics=recent,
    )
