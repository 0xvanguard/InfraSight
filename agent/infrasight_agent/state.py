"""Persistencia mínima del estado del agente (device_id + device_token)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentState:
    device_id: str
    device_token: str

    def to_dict(self) -> dict[str, str]:
        return {"device_id": self.device_id, "device_token": self.device_token}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "AgentState":
        return cls(device_id=data["device_id"], device_token=data["device_token"])


def load_state(path: Path) -> AgentState | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return AgentState.from_dict(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
        return None


def save_state(path: Path, state: AgentState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state.to_dict(), fh)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Sistemas que no soportan chmod (Windows) — aceptable.
        pass
