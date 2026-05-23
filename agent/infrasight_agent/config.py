"""Carga de configuración del agente desde TOML + variables de entorno."""

from __future__ import annotations

import os
import socket
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_CONFIG_PATHS = [
    Path("/etc/infrasight/agent.toml"),
    Path.cwd() / "agent.toml",
]
DEFAULT_STATE_PATH = Path("/var/lib/infrasight/agent.state")


@dataclass
class AgentSettings:
    api_url: str
    enrollment_token: str
    hostname: str
    machine_id: str
    collect_interval_s: int = 30
    heartbeat_interval_s: int = 60
    state_path: Path = field(default=DEFAULT_STATE_PATH)
    agent_version: str = "0.1.0"


def _detect_machine_id() -> str:
    """Lee /etc/machine-id si existe; si no, usa un UUID derivado del hostname."""
    candidates = [Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")]
    for path in candidates:
        try:
            value = path.read_text().strip()
        except OSError:
            continue
        if value:
            return value
    # Fallback estable para entornos donde no exista (p. ej. macOS).
    return str(
        uuid.uuid5(uuid.NAMESPACE_DNS, f"infrasight:{socket.gethostname()}")
    )


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_config() -> AgentSettings:
    """Combina TOML + variables de entorno (estas últimas tienen prioridad)."""
    file_data: dict[str, Any] = {}

    explicit = os.environ.get("INFRASIGHT_CONFIG_PATH")
    paths = [Path(explicit)] if explicit else DEFAULT_CONFIG_PATHS
    for path in paths:
        data = _read_toml(path)
        if data:
            file_data = data
            break

    api_url = os.environ.get("INFRASIGHT_API_URL", file_data.get("api_url", ""))
    enrollment_token = os.environ.get(
        "INFRASIGHT_ENROLLMENT_TOKEN", file_data.get("enrollment_token", "")
    )
    hostname = (
        os.environ.get("INFRASIGHT_HOSTNAME")
        or file_data.get("hostname")
        or socket.gethostname()
    )
    machine_id = (
        os.environ.get("INFRASIGHT_MACHINE_ID")
        or file_data.get("machine_id")
        or _detect_machine_id()
    )
    collect_interval_s = int(
        os.environ.get(
            "INFRASIGHT_COLLECT_INTERVAL_S",
            file_data.get("collect_interval_s", 30),
        )
    )
    heartbeat_interval_s = int(
        os.environ.get(
            "INFRASIGHT_HEARTBEAT_INTERVAL_S",
            file_data.get("heartbeat_interval_s", 60),
        )
    )
    state_path = Path(
        os.environ.get(
            "INFRASIGHT_STATE_PATH",
            file_data.get("state_path", str(DEFAULT_STATE_PATH)),
        )
    )

    if not api_url:
        raise RuntimeError(
            "Configuración inválida: api_url vacío. Define INFRASIGHT_API_URL "
            "o el campo api_url en agent.toml."
        )
    if not enrollment_token:
        raise RuntimeError(
            "Configuración inválida: enrollment_token vacío. Define "
            "INFRASIGHT_ENROLLMENT_TOKEN o el campo enrollment_token en agent.toml."
        )

    return AgentSettings(
        api_url=api_url.rstrip("/"),
        enrollment_token=enrollment_token,
        hostname=hostname,
        machine_id=machine_id,
        collect_interval_s=collect_interval_s,
        heartbeat_interval_s=heartbeat_interval_s,
        state_path=state_path,
    )
