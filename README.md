# InfraSight

> Remote monitoring and endpoint intelligence for distributed business environments.

InfraSight is a self-hostable platform for monitoring endpoints and critical
services across an organization. It collects health metrics from a lightweight
agent, surfaces them in a web dashboard, raises threshold-based technical
alerts, and tracks intervention reports — geared toward IT teams and MSPs that
support distributed fleets.

**Status:** Pre-alpha. Specs and skeletons only — no runnable services yet.

---

## Why

Most off-the-shelf monitoring stacks (Zabbix, Nagios, full Prometheus + Grafana
deployments) are powerful but heavy to operate for small-to-mid IT teams.
Hosted alternatives (Datadog, New Relic) are expensive and overkill for fleets
of a few dozen to a few hundred endpoints.

InfraSight aims for the middle ground:

- **Self-hosted** — your data stays on your infrastructure.
- **Boring stack** — Postgres + FastAPI + Next.js. No exotic dependencies.
- **Operator-friendly** — single `docker compose up` for the server side, single
  binary / package for the agent.
- **Intervention-aware** — alerts are not just notifications; each alert can be
  acknowledged and closed with a written intervention report, building a
  searchable history per endpoint.

## Features (v1 scope)

- Lightweight Python agent reporting:
  - CPU usage, load average
  - Memory (used / available / swap)
  - Disk usage per filesystem and disk I/O
  - Network I/O per interface
  - Uptime, OS / kernel version, hostname
- FastAPI ingest + query API with OpenAPI docs
- TimescaleDB for time-series storage with native SQL
- Next.js dashboard:
  - Fleet overview (online/offline, alert counts)
  - Per-endpoint detail with charts (Recharts)
  - Alert inbox and intervention reports
- Threshold-based alerting (e.g. `CPU > 90% for 5 min`) with webhook delivery
  to Slack / Discord / generic HTTP
- Multi-tenant-ready data model from day one (`org_id` everywhere) even though
  v1 ships single-tenant

## Out of scope for v1

- Windows and macOS agents (Linux servers / VMs only)
- Log aggregation (metrics only — logs are a separate problem)
- APM / distributed tracing
- Per-customer UI isolation (schema is ready, UI is not)
- Auto-remediation / runbook execution
- Custom user-defined check scripts

## Stack

| Layer                   | Choice                          |
|-------------------------|---------------------------------|
| Endpoint agent          | Python 3.11+, `psutil`          |
| Backend / API           | FastAPI + Uvicorn               |
| Database                | PostgreSQL 16 + TimescaleDB     |
| Dashboard               | Next.js 14 (App Router) + Tailwind + shadcn/ui + Recharts |
| Alerting transport      | Webhooks (Slack / Discord / generic) |
| Container orchestration | Docker Compose (single-node)    |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full rationale and
data flow.

## Repository layout (planned)

```
InfraSight/
├── agent/              # Python endpoint agent (psutil collectors + HTTP client)
├── backend/            # FastAPI service: ingest, query, alerting, auth
│   ├── app/
│   ├── migrations/     # Alembic migrations (Timescale hypertables)
│   └── tests/
├── dashboard/          # Next.js web UI
├── deploy/
│   └── compose/        # docker-compose.yml + env templates
├── docs/
│   ├── ARCHITECTURE.md
│   └── AGENT_PROTOCOL.md
└── README.md
```

Only `docs/` and `README.md` exist today. Code skeletons land in subsequent PRs.

## Quickstart

> The stack is not yet runnable. This section is a placeholder to lock the
> developer experience we are designing toward.

```bash
# 1. Bring up Postgres/TimescaleDB, the API, and the dashboard
cd deploy/compose
cp .env.example .env
docker compose up -d

# 2. Open the dashboard
open http://localhost:3000

# 3. Enroll an endpoint (run on the machine to be monitored)
curl -fsSL https://<your-host>/install.sh | sudo bash -s -- \
  --api-url https://<your-host>/api \
  --enroll-token <token-from-dashboard>
```

## Roadmap

- **M0 — Specs (this PR)** — README + architecture + agent protocol.
- **M1 — Walking skeleton** — Compose stack stands up; agent posts a hardcoded
  metric; dashboard shows one device.
- **M2 — Real metrics** — All v1 collectors, hypertables, time-range charts.
- **M3 — Alerts & interventions** — Threshold rules, webhooks, intervention
  report workflow.
- **M4 — Hardening** — Auth, enrollment tokens, agent auto-update, packaging.
- **M5 — Multi-tenant UI** — Surface `org_id` in the dashboard, RBAC.

## Contributing

Issues and PRs welcome once M1 lands. Until then, the docs in this repo are
the contract — open an issue if something in `ARCHITECTURE.md` or
`AGENT_PROTOCOL.md` looks wrong or under-specified.

## License

MIT — see [LICENSE](LICENSE).
