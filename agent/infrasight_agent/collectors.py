"""Colectores de métricas basados en psutil.

M1 implementa un subconjunto del catálogo descrito en docs/AGENT_PROTOCOL.md.
Las métricas adicionales (E/S de disco, swap, load5/load15) llegan en M2.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

import psutil

from .schemas import MetricSample

# Sistemas de ficheros pseudo que ignoramos por defecto.
_SKIP_FSTYPES = {
    "tmpfs",
    "devtmpfs",
    "overlay",
    "squashfs",
    "proc",
    "sysfs",
    "cgroup",
    "cgroup2",
    "autofs",
    "ramfs",
    "fusectl",
    "debugfs",
    "tracefs",
}

_SKIP_IFACE_PREFIXES = ("lo", "docker", "br-", "veth", "virbr")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# -----------------------------------------------------------------------------
# Estado para métricas derivadas (rates).
# -----------------------------------------------------------------------------
class _RateState:
    def __init__(self) -> None:
        self.last_ts: float | None = None
        self.last_net: dict[str, Any] = {}

    def step(self) -> tuple[float, float | None]:
        now = time.monotonic()
        elapsed = None if self.last_ts is None else max(now - self.last_ts, 1e-6)
        self.last_ts = now
        return now, elapsed


_rate_state = _RateState()


# -----------------------------------------------------------------------------
# Colectores individuales.
# -----------------------------------------------------------------------------
def _cpu_samples(ts: dt.datetime) -> list[MetricSample]:
    samples = [
        MetricSample(
            ts=ts,
            metric="cpu.usage_pct",
            value=float(psutil.cpu_percent(interval=None)),
        ),
    ]
    try:
        load1, _, _ = psutil.getloadavg()
        samples.append(MetricSample(ts=ts, metric="cpu.load1", value=float(load1)))
    except (AttributeError, OSError):
        # En Windows puede no estar disponible.
        pass
    return samples


def _memory_samples(ts: dt.datetime) -> list[MetricSample]:
    vm = psutil.virtual_memory()
    return [
        MetricSample(ts=ts, metric="mem.used_bytes", value=float(vm.used)),
        MetricSample(ts=ts, metric="mem.available_bytes", value=float(vm.available)),
    ]


def _disk_samples(ts: dt.datetime) -> list[MetricSample]:
    out: list[MetricSample] = []
    for part in psutil.disk_partitions(all=False):
        if part.fstype in _SKIP_FSTYPES:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        labels = {"mountpoint": part.mountpoint}
        out.append(
            MetricSample(ts=ts, metric="disk.used_bytes", value=float(usage.used), labels=labels)
        )
        out.append(
            MetricSample(ts=ts, metric="disk.used_pct", value=float(usage.percent), labels=labels)
        )
    return out


def _network_samples(ts: dt.datetime, elapsed_s: float | None) -> list[MetricSample]:
    counters = psutil.net_io_counters(pernic=True)
    out: list[MetricSample] = []
    for iface, c in counters.items():
        if any(iface.startswith(p) for p in _SKIP_IFACE_PREFIXES):
            continue
        prev = _rate_state.last_net.get(iface)
        if prev is not None and elapsed_s is not None:
            rx_rate = max(c.bytes_recv - prev["rx"], 0) / elapsed_s
            tx_rate = max(c.bytes_sent - prev["tx"], 0) / elapsed_s
            labels = {"iface": iface}
            out.append(MetricSample(ts=ts, metric="net.rx_bytes", value=rx_rate, labels=labels))
            out.append(MetricSample(ts=ts, metric="net.tx_bytes", value=tx_rate, labels=labels))
        _rate_state.last_net[iface] = {"rx": c.bytes_recv, "tx": c.bytes_sent}
    return out


def _host_samples(ts: dt.datetime) -> list[MetricSample]:
    try:
        uptime = time.time() - psutil.boot_time()
    except (OSError, AttributeError):
        return []
    return [MetricSample(ts=ts, metric="host.uptime_s", value=float(uptime))]


# -----------------------------------------------------------------------------
# API pública.
# -----------------------------------------------------------------------------
def collect() -> list[MetricSample]:
    """Recolecta una muestra de todas las métricas soportadas en M1."""
    ts = _now()
    _, elapsed = _rate_state.step()
    samples: list[MetricSample] = []
    samples.extend(_cpu_samples(ts))
    samples.extend(_memory_samples(ts))
    samples.extend(_disk_samples(ts))
    samples.extend(_network_samples(ts, elapsed))
    samples.extend(_host_samples(ts))
    return samples
