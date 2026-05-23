"""Endpoints orientados al dashboard: listado, detalle y series temporales."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import settings
from ..db import acquire
from ..schemas import (
    DeviceDetail,
    DeviceSummary,
    MetricSample,
    MetricSeries,
    MetricSeriesPoint,
    MetricSeriesResponse,
)

router = APIRouter(prefix="/v1", tags=["query"])


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _status_for(last_seen_at: datetime | None) -> str:
    if last_seen_at is None:
        return "offline"
    delta = (datetime.now(timezone.utc) - last_seen_at).total_seconds()
    if delta <= settings.offline_threshold_s:
        return "online"
    if delta <= settings.offline_threshold_s * 4:
        return "stale"
    return "offline"


@dataclass(frozen=True)
class _BucketChoice:
    """Representa una elección de granularidad para una serie temporal.

    `source` es el nombre de la tabla/vista a consultar. Para rangos cortos
    consultamos la hypertable raw con un `time_bucket` ad-hoc; para rangos
    largos vamos contra los continuous aggregates ya materializados.
    """

    source: str           # 'metrics', 'metrics_1m', 'metrics_1h'
    bucket: timedelta     # tamaño del bucket de respuesta
    needs_time_bucket: bool  # True si hay que envolver en time_bucket()


# Reglas de resolución: pensadas para mantener ~120-720 puntos por gráfica.
# Si el usuario fuerza un `interval` explícito, respetamos esa resolución
# pero seguimos eligiendo la fuente más barata que cubra la granularidad.
_RESOLUTION_RULES: list[tuple[timedelta, _BucketChoice]] = [
    # rango <= 1h  -> raw, 10s
    (timedelta(hours=1),   _BucketChoice("metrics",    timedelta(seconds=10), True)),
    # rango <= 6h  -> raw, 30s
    (timedelta(hours=6),   _BucketChoice("metrics",    timedelta(seconds=30), True)),
    # rango <= 24h -> CAGG 1m
    (timedelta(hours=24),  _BucketChoice("metrics_1m", timedelta(minutes=1),  False)),
    # rango <= 7d  -> CAGG 1m, bucketeado a 5m
    (timedelta(days=7),    _BucketChoice("metrics_1m", timedelta(minutes=5),  True)),
    # cualquier cosa más larga -> CAGG 1h
    (timedelta(days=3650), _BucketChoice("metrics_1h", timedelta(hours=1),    False)),
]


def _choose_resolution(
    range_span: timedelta,
    forced_interval: timedelta | None,
) -> _BucketChoice:
    base = next(rule for limit, rule in _RESOLUTION_RULES if range_span <= limit)
    if forced_interval is None:
        return base
    # Honramos el interval pedido pero impedimos resoluciones más finas que la
    # fuente: pedir 1s sobre el CAGG horario carece de sentido.
    if forced_interval < base.bucket:
        forced_interval = base.bucket
    return _BucketChoice(
        source=base.source,
        bucket=forced_interval,
        needs_time_bucket=True,
    )


def _parse_interval(value: str | None) -> timedelta | None:
    """Acepta sufijos: 's', 'm', 'h'. Ejemplos: '30s', '5m', '1h'."""
    if value is None:
        return None
    if not value or value[-1] not in {"s", "m", "h"}:
        raise ValueError("interval debe terminar en 's', 'm' o 'h'")
    try:
        n = int(value[:-1])
    except ValueError as exc:
        raise ValueError("interval inválido") from exc
    if n <= 0:
        raise ValueError("interval debe ser positivo")
    unit = value[-1]
    if unit == "s":
        return timedelta(seconds=n)
    if unit == "m":
        return timedelta(minutes=n)
    return timedelta(hours=n)


# -----------------------------------------------------------------------------
# /v1/devices
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# /v1/devices/{id}
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# /v1/devices/{id}/series
# -----------------------------------------------------------------------------
@router.get(
    "/devices/{device_id}/series",
    response_model=MetricSeriesResponse,
)
async def get_device_series(
    device_id: UUID,
    metric: Annotated[
        list[str],
        Query(
            description="Una o más métricas. Repite el parámetro: ?metric=cpu.usage_pct&metric=mem.used_bytes",
            min_length=1,
            max_length=20,
        ),
    ],
    range: Annotated[
        str,
        Query(
            description="Rango temporal: '1h', '6h', '24h', '7d', '30d'. Ignorado si se pasa from/to.",
            pattern=r"^\d+[smhd]$",
        ),
    ] = "1h",
    from_: Annotated[
        datetime | None,
        Query(alias="from", description="ISO 8601 con zona horaria."),
    ] = None,
    to: datetime | None = None,
    interval: Annotated[
        str | None,
        Query(
            description="Forzar resolución del bucket: '10s', '30s', '1m', '5m', '1h'. Si se omite se elige automáticamente.",
            pattern=r"^\d+[smh]$",
        ),
    ] = None,
    conn: asyncpg.Connection = Depends(acquire),
) -> MetricSeriesResponse:
    # 1. Resolver ventana temporal.
    if from_ is not None and to is not None:
        if to <= from_:
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "'to' debe ser posterior a 'from'"},
            )
        start, end = from_, to
    else:
        end = datetime.now(timezone.utc)
        # `range` admite sufijos s/m/h/d; _parse_interval no acepta 'd'.
        try:
            if range.endswith("d"):
                span = timedelta(days=int(range[:-1]))
            else:
                span = _parse_interval(range) or timedelta(hours=1)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": str(exc)},
            ) from exc
        start = end - span

    span = end - start
    if span > timedelta(days=365):
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "El rango máximo es 365 días"},
        )

    # 2. Validar interval del usuario y elegir resolución.
    try:
        forced = _parse_interval(interval)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": str(exc)},
        ) from exc

    choice = _choose_resolution(span, forced)

    # 3. Verificar que el dispositivo existe y pertenece al org de la sesión.
    exists = await conn.fetchval(
        "SELECT 1 FROM devices WHERE id = $1 AND org_id = $2",
        device_id,
        settings.default_org_id,
    )
    if not exists:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "Dispositivo no encontrado"},
        )

    # 4. Construir y ejecutar la query. Una sola query para todas las métricas.
    series = await _query_series(
        conn,
        device_id=device_id,
        metrics=metric,
        start=start,
        end=end,
        choice=choice,
    )

    return MetricSeriesResponse(
        device_id=device_id,
        from_=start,
        to=end,
        interval_s=int(choice.bucket.total_seconds()),
        source=choice.source,
        series=series,
    )


# -----------------------------------------------------------------------------
async def _query_series(
    conn: asyncpg.Connection,
    *,
    device_id: UUID,
    metrics: list[str],
    start: datetime,
    end: datetime,
    choice: _BucketChoice,
) -> list[MetricSeries]:
    """Devuelve una lista de series, una por (metric, labels) único.

    Usa `time_bucket_gapfill` cuando está disponible para devolver buckets
    vacíos como NULL — esto permite a Recharts dibujar huecos reales en
    lugar de interpolar valores inexistentes.
    """
    bucket_seconds = int(choice.bucket.total_seconds())

    if choice.source == "metrics":
        # Hypertable raw: bucketear con time_bucket_gapfill.
        sql = """
            SELECT
                time_bucket_gapfill(make_interval(secs => $1), ts) AS bucket,
                metric,
                labels,
                AVG(value) AS avg,
                MIN(value) AS min,
                MAX(value) AS max,
                COUNT(*)   AS samples
            FROM   metrics
            WHERE  device_id = $2
              AND  metric = ANY($3::text[])
              AND  ts >= $4
              AND  ts <  $5
            GROUP BY bucket, metric, labels
            ORDER BY metric, labels, bucket
        """
        rows = await conn.fetch(sql, bucket_seconds, device_id, metrics, start, end)
    elif choice.needs_time_bucket:
        # CAGG 1m re-bucketeado a 5m (caso 7d).
        sql = f"""
            SELECT
                time_bucket_gapfill(make_interval(secs => $1), bucket) AS bucket,
                metric,
                labels,
                AVG(avg) AS avg,
                MIN(min) AS min,
                MAX(max) AS max,
                SUM(samples) AS samples
            FROM   {choice.source}
            WHERE  device_id = $2
              AND  metric = ANY($3::text[])
              AND  bucket >= $4
              AND  bucket <  $5
            GROUP BY bucket, metric, labels
            ORDER BY metric, labels, bucket
        """
        rows = await conn.fetch(sql, bucket_seconds, device_id, metrics, start, end)
    else:
        # CAGG consultado a su resolución nativa (1m o 1h).
        sql = f"""
            SELECT
                bucket,
                metric,
                labels,
                avg,
                min,
                max,
                samples
            FROM   {choice.source}
            WHERE  device_id = $1
              AND  metric = ANY($2::text[])
              AND  bucket >= $3
              AND  bucket <  $4
            ORDER BY metric, labels, bucket
        """
        rows = await conn.fetch(sql, device_id, metrics, start, end)

    # Agrupar las filas en series por (metric, labels).
    grouped: dict[tuple[str, str], MetricSeries] = {}
    for row in rows:
        labels_raw = row["labels"]
        labels = json.loads(labels_raw) if isinstance(labels_raw, str) else (labels_raw or {})
        key = (row["metric"], json.dumps(labels, sort_keys=True))
        if key not in grouped:
            grouped[key] = MetricSeries(
                metric=row["metric"],
                labels=labels,
                points=[],
            )
        avg = row["avg"]
        grouped[key].points.append(
            MetricSeriesPoint(
                ts=row["bucket"],
                avg=float(avg) if avg is not None else None,
                min=float(row["min"]) if row["min"] is not None else None,
                max=float(row["max"]) if row["max"] is not None else None,
                samples=int(row["samples"]) if row["samples"] is not None else 0,
            )
        )

    return list(grouped.values())
