import Link from "next/link";
import { listDevices } from "../lib/api";
import type { DeviceStatus, DeviceSummary } from "../lib/types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function statusBadge(status: DeviceStatus) {
  const palette: Record<DeviceStatus, string> = {
    online: "bg-ok/20 text-ok",
    stale: "bg-warn/20 text-warn",
    offline: "bg-bad/20 text-bad",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${palette[status]}`}
    >
      {status}
    </span>
  );
}

function formatTs(ts: string | null): string {
  if (!ts) return "—";
  const date = new Date(ts);
  return date.toLocaleString("es-ES", { hour12: false });
}

export default async function FleetPage() {
  let devices: DeviceSummary[] = [];
  let error: string | null = null;

  try {
    devices = await listDevices();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Parque de endpoints</h1>
        <p className="mt-1 text-sm text-muted">
          Lista de dispositivos enrolados con su última señal de vida.
        </p>
      </div>

      {error && (
        <div className="rounded border border-bad/40 bg-bad/10 p-4 text-sm text-bad">
          No se pudo cargar el parque: {error}
        </div>
      )}

      {!error && devices.length === 0 && (
        <div className="rounded border border-border bg-surface p-6 text-center text-muted">
          Todavía no hay dispositivos enrolados. Arranca el agente y vuelve aquí en
          unos segundos.
        </div>
      )}

      {devices.length > 0 && (
        <div className="overflow-hidden rounded border border-border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-3">Estado</th>
                <th className="px-4 py-3">Hostname</th>
                <th className="px-4 py-3">SO</th>
                <th className="px-4 py-3">Agente</th>
                <th className="px-4 py-3">Última señal</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr
                  key={d.id}
                  className="border-t border-border bg-background/40 hover:bg-surface"
                >
                  <td className="px-4 py-3">{statusBadge(d.status)}</td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/devices/${d.id}`}
                      className="text-accent hover:underline"
                    >
                      {d.hostname}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-muted">{d.os ?? "—"}</td>
                  <td className="px-4 py-3 text-muted">{d.agent_version ?? "—"}</td>
                  <td className="px-4 py-3 text-muted">{formatTs(d.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
