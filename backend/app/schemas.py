"""Modelos Pydantic compartidos por los routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Configuración que el backend empuja al agente.
# -----------------------------------------------------------------------------
class AgentConfig(BaseModel):
    collect_interval_s: int
    heartbeat_interval_s: int
    max_batch_bytes: int


# -----------------------------------------------------------------------------
# Enrolamiento.
# -----------------------------------------------------------------------------
class EnrollRequest(BaseModel):
    hostname: str
    os: str | None = None
    kernel: str | None = None
    arch: str | None = None
    agent_version: str | None = None
    machine_id: str = Field(min_length=1)


class EnrollResponse(BaseModel):
    device_id: UUID
    device_token: str
    config: AgentConfig


# -----------------------------------------------------------------------------
# Heartbeat.
# -----------------------------------------------------------------------------
class HeartbeatRequest(BaseModel):
    ts: datetime
    agent_version: str | None = None
    uptime_s: float | None = None
    boot_id: str | None = None
    queue_depth: int | None = None


class HeartbeatResponse(BaseModel):
    config: AgentConfig


# -----------------------------------------------------------------------------
# Ingesta de métricas.
# -----------------------------------------------------------------------------
class MetricSample(BaseModel):
    ts: datetime
    metric: str
    value: float
    labels: dict[str, Any] = Field(default_factory=dict)


class IngestBatch(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)
    samples: list[MetricSample] = Field(min_length=1, max_length=5000)


# -----------------------------------------------------------------------------
# Respuestas de consulta para el dashboard.
# -----------------------------------------------------------------------------
class DeviceSummary(BaseModel):
    id: UUID
    hostname: str
    os: str | None
    kernel: str | None
    agent_version: str | None
    enrolled_at: datetime
    last_seen_at: datetime | None
    status: str  # 'online' | 'offline' | 'stale'


class DeviceDetail(DeviceSummary):
    machine_id: str
    recent_metrics: list[MetricSample]


# -----------------------------------------------------------------------------
# Series temporales (M2).
# -----------------------------------------------------------------------------
class MetricSeriesPoint(BaseModel):
    """Un punto de una serie temporal ya bucketeada.

    `avg`/`min`/`max` son None cuando el bucket no tiene muestras (gap fill).
    """

    ts: datetime
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    samples: int = 0


class MetricSeries(BaseModel):
    """Serie de un único `(metric, labels)`.

    Las labels se mantienen como dict para que el dashboard pueda derivar
    el nombre legible (`mountpoint=/`, `iface=eth0`, etc.).
    """

    metric: str
    labels: dict[str, Any] = Field(default_factory=dict)
    points: list[MetricSeriesPoint]


class MetricSeriesResponse(BaseModel):
    """Sobre que envuelve la respuesta de /v1/devices/{id}/series."""

    device_id: UUID
    from_: datetime = Field(alias="from", serialization_alias="from")
    to: datetime
    interval_s: int
    source: str  # 'metrics' | 'metrics_1m' | 'metrics_1h'
    series: list[MetricSeries]

    model_config = {"populate_by_name": True}


# -----------------------------------------------------------------------------
# Errores estructurados.
# -----------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    error: str
    message: str
    retry_after_s: int | None = None
