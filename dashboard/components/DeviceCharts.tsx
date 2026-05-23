"use client";

import { useCallback, useEffect, useState } from "react";

import { getDeviceSeries } from "../lib/api";
import type {
  MetricSeries,
  MetricSeriesResponse,
  RangePreset,
} from "../lib/types";
import { MetricChart, type ValueKind } from "./MetricChart";
import { RangePicker } from "./RangePicker";

interface Props {
  deviceId: string;
}

interface ChartSpec {
  title: string;
  metrics: string[];
  valueKind: ValueKind;
  yDomain?: [number | "auto", number | "auto"];
}

const CHART_LAYOUT: ChartSpec[] = [
  {
    title: "Uso de CPU",
    metrics: ["cpu.usage_pct"],
    valueKind: "pct",
    yDomain: [0, 100],
  },
  {
    title: "Load average (1 / 5 / 15 min)",
    metrics: ["cpu.load1", "cpu.load5", "cpu.load15"],
    valueKind: "load",
  },
  {
    title: "Memoria usada",
    metrics: ["mem.used_bytes", "swap.used_bytes"],
    valueKind: "bytes",
  },
  {
    title: "Uso de disco por mountpoint",
    metrics: ["disk.used_pct"],
    valueKind: "pct",
    yDomain: [0, 100],
  },
  {
    title: "E/S de disco (lectura / escritura)",
    metrics: ["disk.io_read_bytes", "disk.io_write_bytes"],
    valueKind: "rate",
  },
  {
    title: "Tráfico de red (rx / tx)",
    metrics: ["net.rx_bytes", "net.tx_bytes"],
    valueKind: "rate",
  },
];

const ALL_METRICS = Array.from(new Set(CHART_LAYOUT.flatMap((c) => c.metrics)));

/**
 * Orquesta la carga de series para todas las gráficas con una sola petición
 * por refresco. Mantiene estado de rango, auto-refresh y errores.
 */
export function DeviceCharts({ deviceId }: Props) {
  const [range, setRange] = useState<RangePreset>("1h");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [data, setData] = useState<MetricSeriesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await getDeviceSeries(deviceId, {
        metrics: ALL_METRICS,
        range,
      });
      setData(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, [deviceId, range]);

  // Carga inicial y cuando cambian rango / refreshTick.
  useEffect(() => {
    fetchData();
  }, [fetchData, refreshTick]);

  // Auto-refresh cada 30s. Sólo cuando autoRefresh está activo y la pestaña
  // está visible — no quema CPU ni cuota mientras el usuario está en otra app.
  useEffect(() => {
    if (!autoRefresh) return;
    const tick = () => {
      if (document.visibilityState === "visible") {
        setRefreshTick((n) => n + 1);
      }
    };
    const id = window.setInterval(tick, 30_000);
    return () => window.clearInterval(id);
  }, [autoRefresh]);

  const seriesByMetric: Record<string, MetricSeries[]> = {};
  for (const s of data?.series ?? []) {
    (seriesByMetric[s.metric] ??= []).push(s);
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <RangePicker
          value={range}
          onChange={setRange}
          autoRefresh={autoRefresh}
          onToggleAutoRefresh={setAutoRefresh}
        />
        <div className="flex items-center gap-3 text-xs text-muted">
          {data && (
            <span>
              Resolución {humanInterval(data.interval_s)} · fuente{" "}
              <code className="rounded bg-background px-1 py-0.5 font-mono text-[11px]">
                {data.source}
              </code>
            </span>
          )}
          <button
            type="button"
            onClick={() => setRefreshTick((n) => n + 1)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs text-muted hover:text-foreground"
          >
            Refrescar
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          No se pudieron cargar las series: {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {CHART_LAYOUT.map((spec) => {
          const merged: MetricSeries[] = spec.metrics.flatMap(
            (m) => seriesByMetric[m] ?? [],
          );
          return (
            <MetricChart
              key={spec.title}
              title={spec.title}
              series={merged}
              valueKind={spec.valueKind}
              yDomain={spec.yDomain}
              loading={loading && merged.length === 0}
            />
          );
        })}
      </div>
    </section>
  );
}

function humanInterval(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}
