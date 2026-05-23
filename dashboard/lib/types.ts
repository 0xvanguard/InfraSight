export type DeviceStatus = "online" | "offline" | "stale";

export interface DeviceSummary {
  id: string;
  hostname: string;
  os: string | null;
  kernel: string | null;
  agent_version: string | null;
  enrolled_at: string;
  last_seen_at: string | null;
  status: DeviceStatus;
}

export interface MetricSample {
  ts: string;
  metric: string;
  value: number;
  labels: Record<string, string>;
}

export interface DeviceDetail extends DeviceSummary {
  machine_id: string;
  recent_metrics: MetricSample[];
}

// ---------------------------------------------------------------------------
// Series temporales (M2)
// ---------------------------------------------------------------------------
export interface MetricSeriesPoint {
  ts: string;
  avg: number | null;
  min: number | null;
  max: number | null;
  samples: number;
}

export interface MetricSeries {
  metric: string;
  labels: Record<string, string>;
  points: MetricSeriesPoint[];
}

export interface MetricSeriesResponse {
  device_id: string;
  from: string;
  to: string;
  interval_s: number;
  source: "metrics" | "metrics_1m" | "metrics_1h";
  series: MetricSeries[];
}

export type RangePreset = "1h" | "6h" | "24h" | "7d" | "30d";

export const RANGE_PRESETS: { key: RangePreset; label: string }[] = [
  { key: "1h", label: "1 h" },
  { key: "6h", label: "6 h" },
  { key: "24h", label: "24 h" },
  { key: "7d", label: "7 d" },
  { key: "30d", label: "30 d" },
];
