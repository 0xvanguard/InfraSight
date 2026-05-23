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
