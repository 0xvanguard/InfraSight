import Link from "next/link";
import { notFound } from "next/navigation";

import { DeviceCharts } from "../../../components/DeviceCharts";
import { getDevice } from "../../../lib/api";
import { describeSeries, formatMetricValue } from "../../../lib/format";
import type { MetricSample } from "../../../lib/types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

interface PageProps {
  params: { id: string };
}

export default async function DevicePage({ params }: PageProps) {
  let device;
  try {
    device = await getDevice(params.id);
  } catch (err) {
    if (err instanceof Error && err.message.includes("404")) {
      notFound();
    }
    throw err;
  }

  // Para el panel de "valores actuales" agrupamos las muestras por
  // (metric, labels) y nos quedamos con la última. Las gráficas históricas
  // las renderiza <DeviceCharts /> con su propio fetch contra /series.
  const latestByKey = new Map<string, MetricSample>();
  for (const sample of device.recent_metrics) {
    const labelStr = labelString(sample.labels);
    const key = sample.metric + "|" + labelStr;
    const existing = latestByKey.get(key);
    if (!existing || new Date(sample.ts) > new Date(existing.ts)) {
      latestByKey.set(key, sample);
    }
  }
  const latest = Array.from(latestByKey.values()).sort((a, b) =>
    a.metric.localeCompare(b.metric),
  );

  return (
    <div className="space-y-8">
      <div>
        <Link href="/" className="text-sm text-accent hover:underline">
          ← Volver al parque
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">{device.hostname}</h1>
        <p className="text-sm text-muted">
          {device.os ?? "SO desconocido"} · kernel {device.kernel ?? "—"} · agente{" "}
          {device.agent_version ?? "—"}
        </p>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="Estado" value={device.status} />
        <Card label="Última señal" value={formatTs(device.last_seen_at)} />
        <Card label="Enrolado" value={formatTs(device.enrolled_at)} />
        <Card label="machine_id" value={device.machine_id} mono />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Series temporales</h2>
        <DeviceCharts deviceId={device.id} />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-medium">Valores actuales</h2>
        {latest.length === 0 ? (
          <p className="rounded border border-border bg-surface p-4 text-sm text-muted">
            Aún no han llegado métricas para este dispositivo.
          </p>
        ) : (
          <div className="overflow-hidden rounded border border-border">
            <table className="w-full text-sm">
              <thead className="bg-surface text-left text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-3">Métrica</th>
                  <th className="px-4 py-3">Etiquetas</th>
                  <th className="px-4 py-3 text-right">Valor</th>
                  <th className="px-4 py-3">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {latest.map((m) => (
                  <tr
                    key={m.metric + labelString(m.labels)}
                    className="border-t border-border"
                  >
                    <td className="px-4 py-2 font-mono text-xs">{m.metric}</td>
                    <td className="px-4 py-2 text-xs text-muted">
                      {describeSeries(m.metric, m.labels) === m.metric
                        ? "—"
                        : describeSeries(m.metric, m.labels)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {formatMetricValue(m.metric, m.value)}
                    </td>
                    <td className="px-4 py-2 text-xs text-muted">{formatTs(m.ts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Card({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded border border-border bg-surface p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div
        className={`mt-1 text-base ${mono ? "font-mono text-xs break-all" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}

function formatTs(ts: string | null): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("es-ES", { hour12: false });
}

function labelString(labels: Record<string, string>): string {
  return Object.entries(labels)
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join(",");
}
