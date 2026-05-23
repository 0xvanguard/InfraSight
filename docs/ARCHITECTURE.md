# InfraSight Architecture

This document is the source of truth for how InfraSight is structured. It
defines the components, the contracts between them, the data model, and the
non-functional choices (security, scale, deployment).

If code disagrees with this document, the code is wrong or this document is
stale — open an issue.

---

## 1. System overview

```
┌──────────────────┐        HTTPS          ┌────────────────────────────┐
│  Endpoint Agent  │  ───── ingest ─────►  │       FastAPI Backend      │
│  (Python, Linux) │   POST /v1/metrics    │                            │
│                  │   POST /v1/heartbeat  │  ┌──────────────────────┐  │
└──────────────────┘                       │  │ Ingest router        │  │
        ▲                                  │  │ Query router         │  │
        │ enroll token                     │  │ Alert evaluator      │  │
        │ (one-time)                       │  │ Webhook dispatcher   │  │
        │                                  │  └──────────┬───────────┘  │
        │                                  │             │              │
        │                                  └─────────────┼──────────────┘
        │                                                │ SQL
        │                                                ▼
        │                                  ┌────────────────────────────┐
        │                                  │  PostgreSQL + TimescaleDB  │
        │                                  │  - devices, orgs, users    │
        │                                  │  - metrics (hypertable)    │
        │                                  │  - alerts, interventions   │
        │                                  └────────────────────────────┘
        │                                                ▲
        │                                                │ SQL (read)
        │                                  ┌─────────────┴──────────────┐
        └─── enrollment ◄────── HTTPS ─────│       Next.js Dashboard    │
                                           │       (App Router)         │
                                           └────────────────────────────┘
                                                         │
                                                         ▼
                                           ┌────────────────────────────┐
                                           │   Webhook destinations     │
                                           │   Slack / Discord / HTTP   │
                                           └────────────────────────────┘
```

Four runtime components:

1. **Endpoint agent** — a Python process running on each monitored Linux host.
2. **Backend API** — a FastAPI service that ingests metrics, serves the
   dashboard, evaluates alert rules, and dispatches webhooks.
3. **Database** — PostgreSQL with the TimescaleDB extension. All persistent
   state lives here.
4. **Dashboard** — a Next.js app talking to the backend over HTTPS.

There is intentionally **no message broker** in v1. Ingest writes straight to
Postgres. We add Redis/NATS only if benchmarks force us to.

## 2. Components

### 2.1 Endpoint agent

- **Runtime:** Python 3.11+, packaged with PyInstaller for distribution.
- **Process model:** single long-running process (managed by `systemd`).
- **Collection loop:** every `collect_interval_s` (default 30s), gather a
  metrics sample using `psutil` and send it to the backend.
- **Heartbeat:** independent of metrics, every `heartbeat_interval_s`
  (default 60s) — used to determine online/offline state even if metric
  ingest is throttled.
- **Buffering:** if the backend is unreachable, samples are buffered in a
  bounded on-disk queue (default 1h, 10MB cap) and flushed on reconnect.
- **Configuration:** `/etc/infrasight/agent.toml`. Includes API URL, device
  ID, enrollment-derived token, intervals, and feature flags.
- **Update model:** v1 = manual reinstall. M4 introduces an auto-update
  channel.

### 2.2 Backend API

FastAPI app split into routers:

- `ingest/` — agent-facing, token-authenticated:
  - `POST /v1/metrics` — bulk metric samples
  - `POST /v1/heartbeat` — liveness + agent metadata
  - `POST /v1/enroll` — exchange enrollment token for device token
- `query/` — dashboard-facing, session-authenticated:
  - `GET /v1/devices` — fleet listing
  - `GET /v1/devices/{id}` — device detail + recent metrics
  - `GET /v1/devices/{id}/metrics?from=&to=&series=` — time-series query
  - `GET /v1/alerts`, `POST /v1/alerts/{id}/ack`, `POST /v1/alerts/{id}/close`
  - `POST /v1/interventions` — create an intervention report
- `admin/` — org/user management, alert rule CRUD, webhook config.

Background workers run in the same process (FastAPI lifespan + `asyncio`
tasks) for v1:

- **Alert evaluator** — every 30s, for each active rule, query the relevant
  metric window and compare against threshold. Open / close / suppress
  alerts accordingly.
- **Webhook dispatcher** — drains an in-process queue of pending webhook
  deliveries with retries (exponential backoff, 5 attempts).
- **Liveness checker** — flags devices whose latest heartbeat is older than
  `offline_threshold_s` (default 180s) as `offline`.

### 2.3 Database

PostgreSQL 16 with the TimescaleDB extension. One database, schema split by
concern (relational vs. time-series).

See [§3 Data model](#3-data-model).

### 2.4 Dashboard

Next.js 14 with the App Router. Server Components for data fetching against
the backend; Client Components only where interactivity demands it (charts,
forms). Auth via session cookies issued by the backend.

Key pages:

- `/` — fleet overview
- `/devices/[id]` — per-device metrics and history
- `/alerts` — open and recently-closed alerts
- `/interventions` — searchable intervention log
- `/settings/rules` — alert rule editor
- `/settings/webhooks` — webhook configuration

## 3. Data model

Multi-tenant-ready: every row that belongs to a customer carries `org_id`.
v1 ships with a single org seeded automatically.

### 3.1 Relational tables

```sql
-- Tenancy
orgs(id UUID PK, name TEXT, created_at TIMESTAMPTZ)

-- Operators of the platform
users(id UUID PK, org_id UUID FK, email CITEXT UNIQUE, password_hash TEXT,
      role TEXT CHECK (role IN ('admin','operator','viewer')),
      created_at TIMESTAMPTZ)

-- Monitored machines
devices(id UUID PK, org_id UUID FK, hostname TEXT, os TEXT, kernel TEXT,
        agent_version TEXT, enrolled_at TIMESTAMPTZ,
        last_seen_at TIMESTAMPTZ,
        status TEXT CHECK (status IN ('online','offline','stale')),
        labels JSONB DEFAULT '{}'::jsonb)

-- Long-lived per-device tokens for ingest auth
device_tokens(id UUID PK, device_id UUID FK, token_hash TEXT,
              created_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ NULL)

-- Short-lived enrollment tokens issued by the dashboard
enrollment_tokens(id UUID PK, org_id UUID FK, token_hash TEXT,
                  expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ NULL,
                  created_by UUID FK users.id)

-- Alert rules
alert_rules(id UUID PK, org_id UUID FK, name TEXT, metric TEXT,
            comparator TEXT CHECK (comparator IN ('>','>=','<','<=','==')),
            threshold DOUBLE PRECISION,
            duration_s INTEGER,
            scope JSONB,           -- e.g. {"device_id": "..."} or {"label": {...}}
            severity TEXT CHECK (severity IN ('info','warning','critical')),
            enabled BOOLEAN DEFAULT TRUE)

-- Open / historical alerts
alerts(id UUID PK, org_id UUID FK, rule_id UUID FK, device_id UUID FK,
       opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ NULL,
       state TEXT CHECK (state IN ('firing','acked','resolved','closed')),
       last_value DOUBLE PRECISION,
       acked_by UUID FK users.id NULL,
       acked_at TIMESTAMPTZ NULL)

-- Human-written follow-ups
interventions(id UUID PK, org_id UUID FK, alert_id UUID FK NULL,
              device_id UUID FK, author_id UUID FK users.id,
              summary TEXT, body_md TEXT,
              started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ NULL)

-- Outbound notifications config
webhooks(id UUID PK, org_id UUID FK, kind TEXT CHECK (kind IN ('slack','discord','generic')),
         url TEXT, secret TEXT NULL, enabled BOOLEAN DEFAULT TRUE)
```

Useful indexes (non-exhaustive):

- `devices(org_id, status)`
- `alerts(org_id, state, opened_at DESC)`
- `interventions(org_id, device_id, started_at DESC)`

### 3.2 Time-series tables

A single Timescale hypertable, narrow schema, one row per `(device_id,
metric)` per sample:

```sql
metrics(
  ts          TIMESTAMPTZ NOT NULL,
  org_id      UUID        NOT NULL,
  device_id   UUID        NOT NULL,
  metric      TEXT        NOT NULL,   -- e.g. 'cpu.usage_pct', 'mem.used_bytes'
  value       DOUBLE PRECISION NOT NULL,
  labels      JSONB       NOT NULL DEFAULT '{}'::jsonb
                          -- e.g. {"mountpoint":"/"} or {"iface":"eth0"}
);

SELECT create_hypertable('metrics', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON metrics (device_id, metric, ts DESC);
CREATE INDEX ON metrics (org_id, ts DESC);
```

Retention and compression policies (defaults, tunable per deployment):

- **Compression:** chunks older than 7 days are compressed.
- **Retention:** raw data dropped after 90 days.
- **Continuous aggregates:** 1-minute and 1-hour rollups for chart queries
  spanning days/weeks.

Metric naming follows a dotted lowercase convention:

| Metric                  | Unit         | Notes                          |
|-------------------------|--------------|--------------------------------|
| `cpu.usage_pct`         | percent 0-100| overall                        |
| `cpu.load1`             | float        | 1-min load average             |
| `mem.used_bytes`        | bytes        |                                |
| `mem.available_bytes`   | bytes        |                                |
| `swap.used_bytes`       | bytes        |                                |
| `disk.used_bytes`       | bytes        | `labels.mountpoint`            |
| `disk.used_pct`         | percent      | `labels.mountpoint`            |
| `disk.io_read_bytes`    | bytes/s      | `labels.device`                |
| `disk.io_write_bytes`   | bytes/s      | `labels.device`                |
| `net.rx_bytes`          | bytes/s      | `labels.iface`                 |
| `net.tx_bytes`          | bytes/s      | `labels.iface`                 |
| `host.uptime_s`         | seconds      |                                |

The full agent payload contract lives in
[`AGENT_PROTOCOL.md`](AGENT_PROTOCOL.md).

## 4. Data flow

### 4.1 Enrollment

1. Operator logs into the dashboard, clicks **Add device**, gets a one-time
   enrollment token (TTL 1h).
2. Operator runs the install script on the target host with that token.
3. Agent calls `POST /v1/enroll` with the enrollment token + host facts
   (hostname, OS, kernel).
4. Backend validates token, creates a `devices` row, issues a long-lived
   `device_token`, returns it.
5. Agent persists the device token in `/etc/infrasight/agent.toml` (mode 0600,
   owned by the agent's service user) and starts collecting.

### 4.2 Metric ingest

1. Agent collects a sample, builds an `IngestBatch` (see protocol doc).
2. Agent `POST /v1/metrics` with `Authorization: Bearer <device_token>`.
3. Backend validates the token, resolves `device_id` and `org_id`, and
   `INSERT`s rows into `metrics`. Updates `devices.last_seen_at`.
4. Agent receives `204 No Content` on success or a structured error.

### 4.3 Alert evaluation

Runs every 30s:

1. For each enabled `alert_rules` row, run a SQL query of the form:
   ```sql
   SELECT device_id, AVG(value)
   FROM   metrics
   WHERE  org_id = $1
     AND  metric = $2
     AND  ts >= now() - make_interval(secs => $3)
     AND  -- scope filter, e.g. device_id IN (...) or labels @> ...
   GROUP BY device_id
   HAVING AVG(value) <comparator> $4;
   ```
2. For each device returned, upsert into `alerts`:
   - If no open alert for `(rule_id, device_id)`, INSERT one in `firing`.
   - If one exists and is `firing`/`acked`, update `last_value`.
3. For devices that previously had an open alert but no longer match, transition
   the alert to `resolved` (auto-close).
4. On state transitions, enqueue webhook deliveries for all org webhooks.

### 4.4 Intervention reports

Triggered manually by an operator from the dashboard. An intervention may be
linked to a specific alert (`alert_id`) or stand alone against a device. A
closed intervention is immutable — corrections require a new entry that
references the original.

## 5. Security

### 5.1 Authentication

| Caller             | Mechanism                                        |
|--------------------|--------------------------------------------------|
| Agent → backend    | Bearer device token (long-lived, revocable)      |
| Operator → backend | Email + password, session cookie (HttpOnly, Secure, SameSite=Lax) |
| Operator → enroll  | One-time enrollment token (single-use, TTL 1h)   |
| Backend → webhook  | Per-webhook HMAC-SHA256 signature header         |

All tokens are stored hashed (Argon2id for user passwords, SHA-256 with random
prefix for machine tokens — they are high-entropy already).

### 5.2 Transport

TLS terminated at a reverse proxy (Caddy or Traefik in the reference
compose file). The backend listens on plain HTTP inside the Docker network.
Agent connections require HTTPS in production; HTTP is allowed only when
`api_url` resolves to a private RFC1918 / loopback address.

### 5.3 Authorization

v1 roles inside an org:

- `admin` — everything, including user management and alert rule edits.
- `operator` — ack/close alerts, write interventions, view all data.
- `viewer` — read-only.

Cross-org access is impossible: every query is parameterized by the session's
`org_id` and the database constraints reflect that.

### 5.4 Threat model (abbreviated)

In scope:

- A compromised agent leaking only that device's data and being revocable.
- An operator with `viewer` role unable to escalate.
- Ingest endpoint resistant to floods (rate-limited per device token).

Out of scope for v1:

- Defending against a malicious operator with `admin` role (there is no
  separate audit log signed offline).
- End-to-end encryption between agent and backend beyond TLS.

## 6. Deployment

Reference deployment is `docker compose` on a single VM:

```
deploy/compose/
├── docker-compose.yml
├── .env.example
└── caddy/Caddyfile
```

Services: `caddy` (TLS), `backend` (FastAPI/Uvicorn), `dashboard` (Next.js
standalone build), `db` (TimescaleDB official image). The agent is **not**
part of this compose file — it is deployed onto each monitored host
separately.

Sizing rule of thumb (to be validated in M2):

- 100 endpoints @ 30s interval, 12 metrics each → ~3.5M rows/day → fits
  comfortably on a 2 vCPU / 4 GB VM with default Timescale compression.

## 7. Open questions

These intentionally remain open and will be resolved as the milestones land:

- Do we ship a Prometheus scrape endpoint on the backend for users who
  already run Grafana? (Likely yes, M4.)
- How are agent config changes rolled out — pull (agent re-reads on
  heartbeat response) or push (server-initiated)? (Leaning pull.)
- SSO (OIDC) timing — M4 or post-1.0?

## 8. Glossary

- **Endpoint / device** — a monitored host running the agent.
- **Org** — a tenant. v1 ships with one auto-created org.
- **Rule** — a stored definition that produces alerts when matched.
- **Alert** — an instance of a rule firing for a specific device.
- **Intervention** — a human-written report of action taken in response to
  an alert (or an ad-hoc maintenance event).
