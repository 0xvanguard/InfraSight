"""Colectores de métricas basados en psutil.

M2 implementa el catálogo completo de v1 según docs/AGENT_PROTOCOL.md:

    cpu.usage_pct, cpu.load1, cpu.load5, cpu.load15
    mem.used_bytes, mem.available_bytes, swap.used_bytes
    disk.used_bytes, disk.used_pct                    (por mountpoint)
    disk.io_read_bytes, disk.io_write_bytes           (rate, por device)
    net.rx_bytes, net.tx_bytes                        (rate, por iface)
    host.uptime_s

Las métricas con sufijo `_bytes` cuando representan E/S son **rates**:
bytes/segundo, calculados como diferencia entre lecturas consecutivas
de los contadores acumulados de psutil. La primera muestra de cada
dispositivo / interfaz se omite porque no tiene baseline.
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

# Discos pseudo / loop / device-mapper internos que ignoramos.
_SKIP_DISK_PREFIXES = ("loop", "ram", "dm-")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# -----------------------------------------------------------------------------
# Estado para métricas derivadas (rates).
# -----------------------------------------------------------------------------
class _RateState:
    """Mantiene los últimos contadores absolutos para calcular tasas.

    Conservamos series por dispositivo y por interfaz por separado: si una
    iface o un disco aparece a mitad de ejecución, no contamina el cálculo
    de las demás.
    """

    def __init__(self) -> None:
        self.last_ts: float | None = None
        self.last_net: dict[str, dict[str, int]] = {}
        self.last_disk_io: dict[str, dict[str, int]] = {}

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
        load1, load5, load15 = psutil.getloadavg()
        samples.append(MetricSample(ts=ts, metric="cpu.load1", value=float(load1)))
        samples.append(MetricSample(ts=ts, metric="cpu.load5", value=float(load5)))
        samples.append(MetricSample(ts=ts, metric="cpu.load15", value=float(load15)))
    except (AttributeError, OSError):
        # En Windows puede no estar disponible.
        pass
    return samples


def _memory_samples(ts: dt.datetime) -> list[MetricSample]:
    vm = psutil.virtual_memory()
    out = [
        MetricSample(ts=ts, metric="mem.used_bytes", value=float(vm.used)),
        MetricSample(ts=ts, metric="mem.available_bytes", value=float(vm.available)),
    ]
    try:
        sw = psutil.swap_memory()
        out.append(MetricSample(ts=ts, metric="swap.used_bytes", value=float(sw.used)))
    except (OSError, NotImplementedError):
        pass
    return out


def _disk_usage_samples(ts: dt.datetime) -> list[MetricSample]:
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


def _disk_io_samples(ts: dt.datetime, elapsed_s: float | None) -> list[MetricSample]:
    """Tasas de E/S por dispositivo de bloque.

    psutil expone contadores acumulados en bytes desde el arranque del SO.
    Convertimos a bytes/segundo restando la lectura previa y dividiendo por
    el tiempo transcurrido. La primera muestra no produce salida.
    """
    try:
        per_disk = psutil.disk_io_counters(perdisk=True)
    except (RuntimeError, AttributeError):
        return []
    if not per_disk:
        return []

    out: list[MetricSample] = []
    for name, counters in per_disk.items():
        if any(name.startswith(p) for p in _SKIP_DISK_PREFIXES):
            continue
        prev = _rate_state.last_disk_io.get(name)
        if prev is not None and elapsed_s is not None:
            read_rate = max(counters.read_bytes - prev["read"], 0) / elapsed_s
            write_rate = max(counters.write_bytes - prev["write"], 0) / elapsed_s
            labels = {"device": name}
            out.append(MetricSample(ts=ts, metric="disk.io_read_bytes", value=read_rate, labels=labels))
            out.append(MetricSample(ts=ts, metric="disk.io_write_bytes", value=write_rate, labels=labels))
        _rate_state.last_disk_io[name] = {
            "read": counters.read_bytes,
            "write": counters.write_bytes,
        }
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
    """Recolecta una muestra de todas las métricas soportadas en v1."""
    ts = _now()
    _, elapsed = _rate_state.step()
    samples: list[MetricSample] = []
    samples.extend(_cpu_samples(ts))
    samples.extend(_memory_samples(ts))
    samples.extend(_disk_usage_samples(ts))
    samples.extend(_disk_io_samples(ts, elapsed))
    samples.extend(_network_samples(ts, elapsed))
    samples.extend(_host_samples(ts))
    return samples
