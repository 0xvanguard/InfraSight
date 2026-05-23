# InfraSight Agent Protocol

This document specifies the HTTP contract between the **endpoint agent** and
the **InfraSight backend**. Anything not specified here is undefined behaviour
and must not be relied on.

- **Version:** `v1`
- **Transport:** HTTPS (HTTP allowed only against private addresses)
- **Encoding:** JSON, UTF-8
- **Compression:** `Content-Encoding: gzip` accepted on agent-originated
  requests; the agent SHOULD use it for batches > 4 KiB.
- **Time:** all timestamps are RFC 3339 with timezone offset, UTC preferred
  (`2026-05-23T14:32:01Z`).

---

## 1. Authentication

| Endpoint              | Auth                                              |
|-----------------------|---------------------------------------------------|
| `POST /v1/enroll`     | `Authorization: Bearer <enrollment_token>` (one-time) |
| `POST /v1/heartbeat`  | `Authorization: Bearer <device_token>`            |
| `POST /v1/metrics`    | `Authorization: Bearer <device_token>`            |

The `device_token` is opaque, ≥ 32 bytes of entropy, base64url-encoded. The
agent treats it as a secret and stores it in a file with mode `0600`.

If a request is rejected with `401 invalid_token`, the agent MUST stop
sending and surface the error in its logs / status output. It MUST NOT retry
with the same token. Re-enrollment is a manual operator action.

## 2. Common response shapes

Successful ingest endpoints return `204 No Content` with an empty body.

All errors return:

```json
{
  "error": "string_code",
  "message": "human readable explanation",
  "retry_after_s": 30
}
```

`retry_after_s` is present only when the client is expected to back off.

| HTTP | `error`                | Meaning                                     |
|------|------------------------|---------------------------------------------|
| 400  | `bad_request`          | Malformed JSON or schema violation          |
| 401  | `invalid_token`        | Token unknown, expired, or revoked          |
| 403  | `device_disabled`      | Device exists but is administratively off   |
| 409  | `enrollment_consumed`  | Enrollment token already used               |
| 413  | `payload_too_large`    | Batch exceeds the server limit (default 1 MiB) |
| 422  | `unsupported_metric`   | Unknown metric name in the batch            |
| 429  | `rate_limited`         | Too many requests; honour `retry_after_s`   |
| 5xx  | `server_error`         | Retry with exponential backoff              |

## 3. Endpoints

### 3.1 `POST /v1/enroll`

Exchanges a one-time enrollment token for a long-lived device token and a
device record.

**Request**

```http
POST /v1/enroll HTTP/1.1
Authorization: Bearer <enrollment_token>
Content-Type: application/json

{
  "hostname":      "web-01.prod",
  "os":            "Ubuntu 24.04 LTS",
  "kernel":        "6.8.0-31-generic",
  "arch":          "x86_64",
  "agent_version": "0.1.0",
  "machine_id":    "f1b9...e6"
}
```

`machine_id` is the contents of `/etc/machine-id`. If a device with the same
`(org_id, machine_id)` already exists, the backend reuses that device record
and rotates its token instead of creating a duplicate.

**Response — `200 OK`**

```json
{
  "device_id":    "9c8f2b8e-0a3b-4f4a-8d7e-2a4f0e1c1b22",
  "device_token": "v1.dvc.AbCdEf...",
  "config": {
    "collect_interval_s":   30,
    "heartbeat_interval_s": 60,
    "max_batch_bytes":      1048576
  }
}
```

The `config` object is authoritative — the agent MUST adopt these values for
its main loops, overriding compiled-in defaults.

### 3.2 `POST /v1/heartbeat`

Reports liveness and current agent metadata. Sent every
`heartbeat_interval_s`. Cheap and fixed-size; this is what determines
`devices.status` server-side.

**Request**

```http
POST /v1/heartbeat HTTP/1.1
Authorization: Bearer <device_token>
Content-Type: application/json

{
  "ts":            "2026-05-23T14:32:01Z",
  "agent_version": "0.1.0",
  "uptime_s":      183245,
  "boot_id":       "b0a1...",
  "queue_depth":   0
}
```

`queue_depth` is the number of buffered samples the agent has not yet
flushed. The dashboard surfaces this as a health signal.

**Response — `200 OK`**

```json
{
  "config": {
    "collect_interval_s":   30,
    "heartbeat_interval_s": 60,
    "max_batch_bytes":      1048576
  }
}
```

The agent MUST apply any changed config values on the next loop iteration.
Config changes propagate via heartbeat — there is no separate config push.

### 3.3 `POST /v1/metrics`

Submits a batch of metric samples.

**Request**

```http
POST /v1/metrics HTTP/1.1
Authorization: Bearer <device_token>
Content-Type: application/json
Content-Encoding: gzip

{
  "batch_id": "01HXYZ...ULID",
  "samples": [
    { "ts": "2026-05-23T14:32:00Z", "metric": "cpu.usage_pct",     "value": 17.4 },
    { "ts": "2026-05-23T14:32:00Z", "metric": "cpu.load1",         "value": 0.42 },
    { "ts": "2026-05-23T14:32:00Z", "metric": "mem.used_bytes",    "value": 2147483648 },
    { "ts": "2026-05-23T14:32:00Z", "metric": "mem.available_bytes","value": 6442450944 },
    { "ts": "2026-05-23T14:32:00Z", "metric": "disk.used_pct",     "value": 71.2,
      "labels": { "mountpoint": "/" } },
    { "ts": "2026-05-23T14:32:00Z", "metric": "net.rx_bytes",      "value": 12345.6,
      "labels": { "iface": "eth0" } },
    { "ts": "2026-05-23T14:32:00Z", "metric": "host.uptime_s",     "value": 183245 }
  ]
}
```

Rules:

- `batch_id` is a client-generated ULID. The server treats `(device_id,
  batch_id)` as idempotent: replays of the same batch are accepted with
  `204` but not double-inserted.
- `samples` is a non-empty array, ≤ 5,000 entries per batch.
- Unknown `metric` names cause the **whole batch** to be rejected with `422`
  — never silently dropped.
- `labels` is optional; when present, keys are lowercase ASCII, values are
  short strings (≤ 64 chars). Reserved label keys: `org_id`, `device_id`,
  `metric`, `ts`, `value`.
- The server may close the connection if the decoded body exceeds
  `max_batch_bytes`.

**Response — `204 No Content`** on success.

## 4. Metric catalog (v1)

The agent MUST emit only metrics from this catalog. Adding a new metric is a
protocol change and bumps the minor version.

| Metric                  | Unit         | Required labels         | Notes                      |
|-------------------------|--------------|-------------------------|----------------------------|
| `cpu.usage_pct`         | percent 0-100| —                       | overall, all cores         |
| `cpu.load1`             | float        | —                       | 1-min load average         |
| `cpu.load5`             | float        | —                       | 5-min load average         |
| `cpu.load15`            | float        | —                       | 15-min load average        |
| `mem.used_bytes`        | bytes        | —                       |                            |
| `mem.available_bytes`   | bytes        | —                       |                            |
| `swap.used_bytes`       | bytes        | —                       |                            |
| `disk.used_bytes`       | bytes        | `mountpoint`            | one sample per mountpoint  |
| `disk.used_pct`         | percent      | `mountpoint`            |                            |
| `disk.io_read_bytes`    | bytes/s      | `device`                | rate, derived              |
| `disk.io_write_bytes`   | bytes/s      | `device`                | rate, derived              |
| `net.rx_bytes`          | bytes/s      | `iface`                 | rate, derived              |
| `net.tx_bytes`          | bytes/s      | `iface`                 | rate, derived              |
| `host.uptime_s`         | seconds      | —                       |                            |

The agent SHOULD skip pseudo-filesystems (`tmpfs`, `devtmpfs`, `overlay`,
…) and loopback / docker bridge network interfaces by default. This list is
configurable via `agent.toml`.

## 5. Retry, backoff, and buffering

- On `5xx` or network error: retry with exponential backoff starting at 1s,
  doubling, capped at 60s, jitter ±20%.
- On `429`: sleep for exactly `retry_after_s` before any further requests.
- On `4xx` other than `429`: do **not** retry the same payload. Log and drop.
- While the backend is unreachable, the agent buffers samples in a bounded
  on-disk queue (FIFO, drop-oldest when full). Default cap: 1 hour of
  samples or 10 MiB, whichever is smaller. Buffered samples are flushed in
  original order on reconnect.
- Heartbeats are never buffered; if a heartbeat fails, the next scheduled
  one supersedes it.

## 6. Versioning

The path prefix `/v1` is part of the contract. Backwards-incompatible
changes (removed fields, changed semantics, new required fields) require a
`/v2` prefix and a deprecation window of at least one minor agent release.

Backwards-compatible additions (new optional fields, new metrics added to
the catalog, new error codes) are allowed within `/v1` and do not require an
agent update — but agents MUST tolerate unknown fields in responses without
failing.

## 7. Reference: minimal agent loop (pseudo-code)

```python
def run(cfg):
    token = cfg.device_token
    while True:
        sample_batch = collect()                  # psutil + label assembly
        try:
            post_metrics(token, sample_batch)
        except Retryable as e:
            buffer.push(sample_batch)
        except Fatal as e:
            log.error("fatal ingest error: %s", e)
            return
        sleep(cfg.collect_interval_s)
```

The real loop additionally runs the heartbeat on its own schedule, drains
the buffer when ingest succeeds, and handles config updates from heartbeat
responses.
