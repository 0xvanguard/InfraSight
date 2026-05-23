import Link from "next/link";
import { notFound } from "next/navigation";
import { getDevice } from "../../../lib/api";
import type { MetricSample } from "../../../lib/types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function formatValue(metric: string, value: number): string {
  if (metric.endsWith("_bytes")) return formatBytes(value);
  if (metric.endsWith("_pct")) return `${value.toFixed(1)} %`;
  if (metric === "host.uptime_s") return formatDuration(value);
  return value.toFixed(2);
}

function formatBytes(bytes: number): string {
  if (!isFinite(bytes)) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  let v = Math.abs(bytes);
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

function formatDuration(seconds: number): string {
  const s = Math.floor(seconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function labelString(labels: Record<string, string>): string {
  const entries = Object.entries(labels);
  if (entries.length === 0) return "";
  return entries.map(([k, v]) => `${k}=${v}`).join(", ");
}

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

  // Para M1: agrupamos las muestras por (metric, labels) y nos quedamos con la
  // última. Las gráficas históricas llegan en M2.
  const latestByKey = new Map<string, MetricSample>();
  for (const sample of device.recent_metrics) {
    const key = sample.metric + "|" + labelString(sample.labels);
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

      <section>
        <h2 className="mb-3 text-lg font-medium">Últimas métricas</h2>
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
                    <td className="px-4 py-2 font-mono text-xs text-muted">
                      {labelString(m.labels) || "—"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {formatValue(m.metric, m.value)}
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
