"""Cliente HTTP del agente contra la API de InfraSight."""

from __future__ import annotations

import datetime as dt
import logging
import platform
from dataclasses import dataclass
from typing import Any

import httpx
from ulid import ULID

from .schemas import MetricSample

log = logging.getLogger(__name__)


class FatalAPIError(Exception):
    """Errores 4xx (excepto 429): no debemos reintentar el mismo payload."""


class RetryableAPIError(Exception):
    """Errores 5xx, 429 o de red: reintentar con backoff."""


@dataclass
class EnrollResult:
    device_id: str
    device_token: str
    collect_interval_s: int
    heartbeat_interval_s: int


class APIClient:
    def __init__(self, base_url: str, *, timeout_s: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_s,
            headers={"User-Agent": "infrasight-agent/0.1.0"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -------------------------------------------------------------------------
    async def enroll(
        self,
        *,
        enrollment_token: str,
        hostname: str,
        machine_id: str,
        agent_version: str,
    ) -> EnrollResult:
        body = {
            "hostname": hostname,
            "machine_id": machine_id,
            "agent_version": agent_version,
            "os": _os_string(),
            "kernel": platform.release(),
            "arch": platform.machine(),
        }
        resp = await self._client.post(
            "/v1/enroll",
            json=body,
            headers={"Authorization": f"Bearer {enrollment_token}"},
        )
        _raise_for_status(resp)
        data = resp.json()
        cfg = data.get("config", {})
        return EnrollResult(
            device_id=data["device_id"],
            device_token=data["device_token"],
            collect_interval_s=int(cfg.get("collect_interval_s", 30)),
            heartbeat_interval_s=int(cfg.get("heartbeat_interval_s", 60)),
        )

    # -------------------------------------------------------------------------
    async def heartbeat(
        self,
        *,
        device_token: str,
        agent_version: str,
        uptime_s: float,
        queue_depth: int,
    ) -> dict[str, Any]:
        body = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "agent_version": agent_version,
            "uptime_s": uptime_s,
            "queue_depth": queue_depth,
        }
        resp = await self._client.post(
            "/v1/heartbeat",
            json=body,
            headers={"Authorization": f"Bearer {device_token}"},
        )
        _raise_for_status(resp)
        return resp.json()

    # -------------------------------------------------------------------------
    async def post_metrics(
        self,
        *,
        device_token: str,
        samples: list[MetricSample],
    ) -> None:
        if not samples:
            return
        body = {
            "batch_id": str(ULID()),
            "samples": [s.to_jsonable() for s in samples],
        }
        resp = await self._client.post(
            "/v1/metrics",
            json=body,
            headers={"Authorization": f"Bearer {device_token}"},
        )
        _raise_for_status(resp)


# -----------------------------------------------------------------------------
def _os_string() -> str:
    try:
        return f"{platform.system()} {platform.release()}"
    except Exception:  # pragma: no cover
        return platform.system() or "unknown"


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    status = resp.status_code
    try:
        payload = resp.json()
    except ValueError:
        payload = {"error": "unknown", "message": resp.text}

    if status in (408, 429) or status >= 500:
        raise RetryableAPIError(f"{status}: {payload}")
    raise FatalAPIError(f"{status}: {payload}")
