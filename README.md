# InfraSight

> Monitorización remota e inteligencia de endpoints para entornos
> empresariales distribuidos.

InfraSight es una plataforma autoalojable para monitorizar endpoints y
servicios críticos en una organización. Recoge métricas de salud mediante un
agente ligero, las muestra en un panel web, levanta alertas técnicas basadas
en umbrales y registra informes de intervención — pensada para equipos de TI
y MSPs que dan soporte a parques distribuidos.

**Estado:** Pre-alpha. Solo especificaciones y esqueletos — todavía no hay
servicios ejecutables.

---

## Por qué

La mayoría de stacks de monitorización tradicionales (Zabbix, Nagios,
despliegues completos de Prometheus + Grafana) son potentes pero pesados de
operar para equipos de TI pequeños o medianos. Las alternativas SaaS
(Datadog, New Relic) son caras y desproporcionadas para parques de unas
decenas o cientos de endpoints.

InfraSight busca el punto medio:

- **Autoalojado** — tus datos se quedan en tu infraestructura.
- **Stack aburrido** — Postgres + FastAPI + Next.js. Sin dependencias
  exóticas.
- **Amigable para el operador** — un único `docker compose up` para el lado
  servidor, un único binario / paquete para el agente.
- **Consciente de las intervenciones** — las alertas no son solo
  notificaciones; cada alerta puede confirmarse y cerrarse con un informe
  de intervención escrito, construyendo un histórico buscable por endpoint.

## Funcionalidades (alcance v1)

- Agente ligero en Python que reporta:
  - Uso de CPU, load average
  - Memoria (usada / disponible / swap)
  - Uso de disco por sistema de ficheros y E/S de disco
  - E/S de red por interfaz
  - Uptime, versión de SO / kernel, hostname
- API de ingesta + consulta en FastAPI con documentación OpenAPI
- TimescaleDB para almacenamiento de series temporales con SQL nativo
- Dashboard en Next.js:
  - Vista general del parque (online/offline, número de alertas)
  - Detalle por endpoint con gráficas (Recharts)
  - Bandeja de alertas e informes de intervención
- Alertas basadas en umbrales (p. ej. `CPU > 90% durante 5 min`) con envío
  por webhook a Slack / Discord / HTTP genérico
- Modelo de datos preparado para multi-tenant desde el día uno (`org_id` en
  todas las tablas), aunque v1 sale como single-tenant

## Fuera del alcance de v1

- Agentes para Windows y macOS (solo servidores / VMs Linux)
- Agregación de logs (solo métricas — los logs son otro problema)
- APM / trazado distribuido
- Aislamiento de UI por cliente (el esquema está listo, la UI no)
- Auto-remediación / ejecución de runbooks
- Scripts de comprobación personalizados por el usuario

## Stack

| Capa                       | Elección                              |
|----------------------------|---------------------------------------|
| Agente de endpoint         | Python 3.11+, `psutil`                |
| Backend / API              | FastAPI + Uvicorn                     |
| Base de datos              | PostgreSQL 16 + TimescaleDB           |
| Dashboard                  | Next.js 14 (App Router) + Tailwind + shadcn/ui + Recharts |
| Transporte de alertas      | Webhooks (Slack / Discord / genérico) |
| Orquestación de contenedores | Docker Compose (un solo nodo)       |

Consulta [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) para la
justificación completa y el flujo de datos.

## Estructura del repositorio (planificada)

```
InfraSight/
├── agent/              # Agente Python (colectores psutil + cliente HTTP)
├── backend/            # Servicio FastAPI: ingesta, consulta, alertas, auth
│   ├── app/
│   ├── migrations/     # Migraciones Alembic (hypertables Timescale)
│   └── tests/
├── dashboard/          # UI web Next.js
├── deploy/
│   └── compose/        # docker-compose.yml + plantillas de env
├── docs/
│   ├── ARCHITECTURE.md
│   └── AGENT_PROTOCOL.md
└── README.md
```

Hoy solo existen `docs/` y `README.md`. Los esqueletos de código llegan en
PRs posteriores.

## Quickstart

> El stack todavía no es ejecutable. Esta sección es un placeholder para
> fijar la experiencia de desarrollador hacia la que vamos.

```bash
# 1. Levantar Postgres/TimescaleDB, la API y el dashboard
cd deploy/compose
cp .env.example .env
docker compose up -d

# 2. Abrir el dashboard
open http://localhost:3000

# 3. Dar de alta un endpoint (ejecutar en la máquina a monitorizar)
curl -fsSL https://<tu-host>/install.sh | sudo bash -s -- \
  --api-url https://<tu-host>/api \
  --enroll-token <token-del-dashboard>
```

## Roadmap

- **M0 — Especificaciones (este PR)** — README + arquitectura + protocolo
  del agente.
- **M1 — Walking skeleton** — el stack Compose levanta; el agente envía una
  métrica hardcodeada; el dashboard muestra un dispositivo.
- **M2 — Métricas reales** — todos los colectores de v1, hypertables,
  gráficas con rangos temporales.
- **M3 — Alertas e intervenciones** — reglas de umbral, webhooks, flujo de
  informe de intervención.
- **M4 — Hardening** — auth, tokens de enrolamiento, auto-update del
  agente, empaquetado.
- **M5 — UI multi-tenant** — exponer `org_id` en el dashboard, RBAC.

## Contribuir

Issues y PRs son bienvenidos una vez aterrice M1. Hasta entonces, la
documentación de este repo es el contrato — abre una issue si algo en
`ARCHITECTURE.md` o `AGENT_PROTOCOL.md` parece incorrecto o poco
especificado.

## Licencia

MIT — ver [LICENSE](LICENSE).
