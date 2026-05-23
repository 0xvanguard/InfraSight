"""Modelos del agente (sin dependencias de Pydantic para mantenerlo ligero)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricSample:
    ts: dt.datetime
    metric: str
    value: float
    labels: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ts": self.ts.isoformat(),
            "metric": self.metric,
            "value": self.value,
        }
        if self.labels:
            out["labels"] = self.labels
        return out
