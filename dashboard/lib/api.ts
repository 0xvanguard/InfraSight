import type { DeviceDetail, DeviceSummary } from "./types";

/**
 * URL base del backend.
 *
 * En el navegador (Client Components) se usa NEXT_PUBLIC_API_URL.
 * En el servidor (Server Components) preferimos INTERNAL_API_URL si está
 * definida — útil cuando el dashboard corre en compose y puede llegar al
 * backend por su DNS interno (`http://backend:8000`) sin pasar por internet.
 */
function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return (
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://backend:8000"
    );
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${apiBaseUrl()}${path}`;
  const resp = await fetch(url, {
    ...init,
    cache: "no-store",
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    throw new Error(`Petición ${path} falló con HTTP ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export function listDevices(): Promise<DeviceSummary[]> {
  return getJson<DeviceSummary[]>("/v1/devices");
}

export function getDevice(id: string): Promise<DeviceDetail> {
  return getJson<DeviceDetail>(
    `/v1/devices/${encodeURIComponent(id)}?limit=200`,
  );
}
