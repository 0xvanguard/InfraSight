"""Bucle principal del agente.

Implementación M1:
- Si no hay state guardado, hace POST /v1/enroll con el enrollment_token.
- Tras enrolarse, guarda el device_token en disco.
- En paralelo:
    * Bucle de colección: cada `collect_interval_s` llama a psutil y POSTea
      las métricas.
    * Bucle de heartbeat: cada `heartbeat_interval_s` llama a /v1/heartbeat.
- Reintentos básicos con backoff exponencial en errores transitorios.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path

from . import __version__
from .client import APIClient, FatalAPIError, RetryableAPIError
from .collectors import collect
from .config import AgentSettings
from .state import AgentState, load_state, save_state

log = logging.getLogger(__name__)


class Agent:
    def __init__(self, settings: AgentSettings) -> None:
        self._settings = settings
        self._client = APIClient(base_url=settings.api_url)
        self._state: AgentState | None = None
        self._collect_interval_s = settings.collect_interval_s
        self._heartbeat_interval_s = settings.heartbeat_interval_s
        self._stop_event = asyncio.Event()
        self._boot_time = time.time()

    # -------------------------------------------------------------------------
    async def run(self) -> None:
        log.info(
            "Iniciando agente InfraSight v%s contra %s",
            __version__,
            self._settings.api_url,
        )
        try:
            await self._ensure_enrolled()
            await asyncio.gather(
                self._metrics_loop(),
                self._heartbeat_loop(),
            )
        finally:
            await self._client.aclose()

    # -------------------------------------------------------------------------
    async def _ensure_enrolled(self) -> None:
        existing = load_state(self._settings.state_path)
        if existing is not None:
            log.info("Estado encontrado en %s, reusando device_id=%s",
                     self._settings.state_path, existing.device_id)
            self._state = existing
            return

        log.info("No hay estado; iniciando enrolamiento...")
        attempt = 0
        while True:
            try:
                result = await self._client.enroll(
                    enrollment_token=self._settings.enrollment_token,
                    hostname=self._settings.hostname,
                    machine_id=self._settings.machine_id,
                    agent_version=__version__,
                )
            except RetryableAPIError as exc:
                attempt += 1
                wait = _backoff(attempt)
                log.warning("Enrolamiento falló (transitorio): %s. Reintento en %.1fs", exc, wait)
                await asyncio.sleep(wait)
                continue
            except FatalAPIError as exc:
                log.error("Enrolamiento falló (fatal): %s. Abortando.", exc)
                raise

            self._state = AgentState(
                device_id=result.device_id,
                device_token=result.device_token,
            )
            self._collect_interval_s = result.collect_interval_s
            self._heartbeat_interval_s = result.heartbeat_interval_s
            try:
                save_state(self._settings.state_path, self._state)
            except OSError as exc:
                log.warning(
                    "No se pudo persistir el estado en %s: %s. "
                    "El agente seguirá pero perderá el token al reiniciar.",
                    self._settings.state_path, exc,
                )
            log.info("Enrolado correctamente como device_id=%s", result.device_id)
            return

    # -------------------------------------------------------------------------
    async def _metrics_loop(self) -> None:
        assert self._state is not None
        attempt = 0
        while not self._stop_event.is_set():
            samples = collect()
            try:
                await self._client.post_metrics(
                    device_token=self._state.device_token,
                    samples=samples,
                )
                attempt = 0
                log.info("Enviadas %d muestras de métricas", len(samples))
            except RetryableAPIError as exc:
                attempt += 1
                wait = _backoff(attempt)
                log.warning("Ingesta transitoria falló: %s. Reintento en %.1fs", exc, wait)
                await asyncio.sleep(wait)
                continue
            except FatalAPIError as exc:
                log.error("Ingesta fatal: %s. Descartando lote.", exc)
            await asyncio.sleep(self._collect_interval_s)

    # -------------------------------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        assert self._state is not None
        while not self._stop_event.is_set():
            try:
                resp = await self._client.heartbeat(
                    device_token=self._state.device_token,
                    agent_version=__version__,
                    uptime_s=time.time() - self._boot_time,
                    queue_depth=0,
                )
                cfg = resp.get("config") or {}
                self._collect_interval_s = int(
                    cfg.get("collect_interval_s", self._collect_interval_s)
                )
                self._heartbeat_interval_s = int(
                    cfg.get("heartbeat_interval_s", self._heartbeat_interval_s)
                )
            except RetryableAPIError as exc:
                log.warning("Heartbeat transitorio falló: %s", exc)
            except FatalAPIError as exc:
                log.error("Heartbeat fatal: %s", exc)
            await asyncio.sleep(self._heartbeat_interval_s)


def _backoff(attempt: int) -> float:
    base = min(60.0, 1.0 * (2 ** (attempt - 1)))
    return base * (1.0 + random.uniform(-0.2, 0.2))
