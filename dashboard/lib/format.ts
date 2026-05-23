/**
 * Funciones de formateo numérico para gráficas y tablas.
 *
 * Reglas:
 * - Las métricas con sufijo `_bytes` y nombre que sugiere "uso" (mem, swap,
 *   disk.used) se formatean en bases de 1024 (KiB/MiB/GiB).
 * - Las métricas con sufijo `_bytes` y nombre que sugiere "tasa"
 *   (`net.*_bytes`, `disk.io_*_bytes`) se formatean en bases de 1000 con
 *   sufijo `/s` (KB/s, MB/s, GB/s) — convención de monitorización de red.
 * - `_pct` siempre como porcentaje 0-100 con un decimal.
 * - `host.uptime_s` como duración legible.
 */

const RATE_METRICS = new Set([
  "net.rx_bytes",
  "net.tx_bytes",
  "disk.io_read_bytes",
  "disk.io_write_bytes",
]);

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let i = 0;
  let v = Math.abs(bytes);
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatRate(bytesPerSec: number): string {
  if (!Number.isFinite(bytesPerSec)) return "—";
  const units = ["B/s", "kB/s", "MB/s", "GB/s", "TB/s"];
  let i = 0;
  let v = Math.abs(bytesPerSec);
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i += 1;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatPct(pct: number): string {
  if (!Number.isFinite(pct)) return "—";
  return `${pct.toFixed(1)} %`;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  const s = Math.floor(seconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function formatLoadAvg(load: number): string {
  if (!Number.isFinite(load)) return "—";
  return load.toFixed(2);
}

/** Formatea un valor según el nombre de su métrica. */
export function formatMetricValue(metric: string, value: number): string {
  if (metric.endsWith("_pct")) return formatPct(value);
  if (metric === "host.uptime_s") return formatDuration(value);
  if (RATE_METRICS.has(metric)) return formatRate(value);
  if (metric.endsWith("_bytes")) return formatBytes(value);
  if (metric.startsWith("cpu.load")) return formatLoadAvg(value);
  return value.toFixed(2);
}

/** Devuelve una etiqueta corta y legible para una serie con labels. */
export function describeSeries(
  metric: string,
  labels: Record<string, string>,
): string {
  const entries = Object.entries(labels).filter(([k]) => k !== "device_id" && k !== "org_id");
  if (entries.length === 0) return metric;
  return entries.map(([, v]) => v).join(" · ");
}

/** Una paleta sobria pensada para fondos oscuros. */
export const SERIES_COLORS = [
  "#63b3ed", // azul
  "#68d391", // verde
  "#f6ad55", // naranja
  "#fc8181", // rojo
  "#b794f4", // morado
  "#4fd1c5", // turquesa
  "#f687b3", // rosa
  "#ecc94b", // amarillo
];

export function colorForIndex(i: number): string {
  return SERIES_COLORS[i % SERIES_COLORS.length];
}
