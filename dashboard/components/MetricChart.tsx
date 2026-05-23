"use client";

import { format } from "date-fns";
import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  colorForIndex,
  describeSeries,
  formatBytes,
  formatDuration,
  formatLoadAvg,
  formatPct,
  formatRate,
} from "../lib/format";
import type { MetricSeries } from "../lib/types";

export type ValueKind = "pct" | "bytes" | "rate" | "load" | "duration" | "raw";

interface Props {
  title: string;
  series: MetricSeries[];
  /** Cómo formatear los valores numéricos (eje Y, tooltip). */
  valueKind: ValueKind;
  /** Forzar el rango del eje Y. Útil para porcentajes (siempre 0-100). */
  yDomain?: [number | "auto", number | "auto"];
  height?: number;
  /** Indicador de carga; cuando es true mostramos un placeholder. */
  loading?: boolean;
  /** Si todas las series están vacías mostramos un mensaje en lugar de un canvas vacío. */
  emptyMessage?: string;
}

/**
 * Convierte la lista de series del backend en filas para Recharts.
 *
 * Recharts trabaja mejor con `data: [{ ts, serie1, serie2, ... }]`. Pivotamos
 * los puntos de todas las series alineándolos por timestamp; los buckets sin
 * dato (gap fill devolvió null) se conservan como null para que la línea
 * tenga huecos reales.
 */
function pivotSeries(series: MetricSeries[]): Array<Record<string, number | string | null>> {
  const byTs = new Map<string, Record<string, number | string | null>>();
  for (const s of series) {
    const key = seriesKey(s);
    for (const p of s.points) {
      let row = byTs.get(p.ts);
      if (!row) {
        row = { ts: p.ts };
        byTs.set(p.ts, row);
      }
      row[key] = p.avg;
    }
  }
  return Array.from(byTs.values()).sort((a, b) =>
    String(a.ts).localeCompare(String(b.ts)),
  );
}

function seriesKey(s: MetricSeries): string {
  const labelStr = Object.entries(s.labels)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join(",");
  return labelStr ? `${s.metric}|${labelStr}` : s.metric;
}

function formatValue(kind: ValueKind, value: number): string {
  switch (kind) {
    case "pct":
      return formatPct(value);
    case "bytes":
      return formatBytes(value);
    case "rate":
      return formatRate(value);
    case "load":
      return formatLoadAvg(value);
    case "duration":
      return formatDuration(value);
    case "raw":
      return value.toFixed(2);
  }
}

function formatTimeTick(iso: string, span: "short" | "long"): string {
  const d = new Date(iso);
  if (span === "short") return format(d, "HH:mm");
  return format(d, "dd MMM HH:mm");
}

export function MetricChart({
  title,
  series,
  valueKind,
  yDomain,
  height = 220,
  loading = false,
  emptyMessage = "Sin datos en el rango seleccionado.",
}: Props) {
  const hasData = useMemo(
    () => series.some((s) => s.points.some((p) => p.avg !== null)),
    [series],
  );

  const data = useMemo(() => pivotSeries(series), [series]);

  // Decidir si las etiquetas X muestran sólo hora o también fecha.
  const tickFormat = useMemo<"short" | "long">(() => {
    if (data.length < 2) return "short";
    const first = new Date(String(data[0].ts)).getTime();
    const last = new Date(String(data[data.length - 1].ts)).getTime();
    const spanH = (last - first) / 3600_000;
    return spanH > 36 ? "long" : "short";
  }, [data]);

  return (
    <div className="rounded border border-border bg-surface p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        {loading && <span className="text-xs text-muted">Cargando…</span>}
      </div>
      {!loading && !hasData ? (
        <div
          className="flex items-center justify-center text-sm text-muted"
          style={{ height }}
        >
          {emptyMessage}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="rgb(45 50 60)" strokeDasharray="3 3" />
            <XAxis
              dataKey="ts"
              stroke="rgb(148 163 184)"
              fontSize={11}
              tickFormatter={(v) => formatTimeTick(String(v), tickFormat)}
              minTickGap={32}
            />
            <YAxis
              stroke="rgb(148 163 184)"
              fontSize={11}
              tickFormatter={(v) => formatValue(valueKind, Number(v))}
              domain={yDomain ?? ["auto", "auto"]}
              width={68}
            />
            <Tooltip
              contentStyle={{
                background: "rgb(24 27 33)",
                border: "1px solid rgb(45 50 60)",
                fontSize: 12,
              }}
              labelStyle={{ color: "rgb(229 231 235)" }}
              labelFormatter={(v) => format(new Date(String(v)), "dd MMM yyyy HH:mm:ss")}
              formatter={(v: number | string, name: string) => {
                if (v === null || v === undefined) return ["—", name];
                return [formatValue(valueKind, Number(v)), prettyKey(name)];
              }}
            />
            {series.length > 1 && (
              <Legend
                wrapperStyle={{ fontSize: 11, color: "rgb(148 163 184)" }}
                formatter={(value) => prettyKey(String(value))}
              />
            )}
            {series.map((s, i) => (
              <Line
                key={seriesKey(s)}
                type="monotone"
                dataKey={seriesKey(s)}
                stroke={colorForIndex(i)}
                strokeWidth={1.6}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function prettyKey(key: string): string {
  // 'metric|k1=v1,k2=v2' -> 'v1 · v2'
  const [metric, labelStr] = key.split("|", 2);
  if (!labelStr) return metric;
  const labels: Record<string, string> = {};
  for (const part of labelStr.split(",")) {
    const [k, ...rest] = part.split("=");
    labels[k] = rest.join("=");
  }
  return describeSeries(metric, labels);
}
