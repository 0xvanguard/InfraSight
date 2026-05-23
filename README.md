# InfraSight

> Monitorización remota e inteligencia de endpoints para entornos
> empresariales distribuidos.

InfraSight es una plataforma autoalojable para monitorizar endpoints y
servicios críticos en una organización. Recoge métricas de salud mediante un
agente ligero, las muestra en un panel web, levanta alertas técnicas basadas
en umbrales y registra informes de intervención — pensada para equipos de TI
y MSPs que dan soporte a parques distribuidos.

**Estado:** Pre-alpha (M2). El stack levanta de extremo a extremo con
`docker compose up`. El agente cubre el catálogo completo de métricas
de v1, el backend almacena con TimescaleDB usando agregados continuos
y políticas de retención/compresión, y el dashboard renderiza gráficas
históricas con selector de rango (1h–30d) y auto-refresh. Las
funcionalidades de alertas, intervenciones y auth de operadores
llegan en milestones posteriores.

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

## Quickstart (M1)

Requisitos: Docker y `docker compose` v2. Probado en Linux.

```bash
# 1. Configurar variables de entorno
cd deploy/compose
cp .env.example .env
# Edita .env y cambia POSTGRES_PASSWORD y ENROLLMENT_TOKEN.

# 2. Levantar el stack completo (db + backend + dashboard + agente demo)
docker compose up -d --build

# 3. Comprobar que todo arranca
docker compose ps
docker compose logs -f agent          # debería mostrar "Enrolado correctamente"
                                       # y "Enviadas N muestras de métricas"

# 4. Abrir el dashboard
xdg-open http://localhost:3000        # Linux
# o simplemente: navegar manualmente a http://localhost:3000
```

A los pocos segundos verás un dispositivo `demo-endpoint` en el listado.
Pulsa sobre él para ver sus últimas métricas (CPU, memoria, disco, red,
uptime).

**Limpiar todo:**

```bash
docker compose down -v   # -v borra también el volumen de Postgres
```

### Cómo correr el agente fuera de Docker

En producción el agente se instala en cada host monitorizado, no como
contenedor. Para probarlo en local sin Docker:

```bash
cd agent
pip install -e .

export INFRASIGHT_API_URL=http://localhost:8000
export INFRASIGHT_ENROLLMENT_TOKEN=enrol-demo-cambia-esto   # el de tu .env
export INFRASIGHT_HOSTNAME=mi-laptop
export INFRASIGHT_STATE_PATH=./agent.state                  # estado local

python -m infrasight_agent
```

## Roadmap

- **M0 — Especificaciones** ✅ — README + arquitectura + protocolo del
  agente.
- **M1 — Walking skeleton** ✅ — el stack Compose levanta; el agente envía
  métricas reales (CPU, memoria, disco, red, uptime) y el dashboard
  muestra los dispositivos con sus últimas mediciones.
- **M2 — Gráficas y rangos temporales** ✅ — gráficas con Recharts y
  selector de rango (1h/6h/24h/7d/30d) con auto-refresh, endpoint
  `GET /v1/devices/{id}/series` con resolución adaptativa, continuous
  aggregates a 1m y 1h en TimescaleDB, políticas de compresión
  (>7 días) y retención (>90 días), métricas adicionales (`load5`/
  `load15`, `swap`, `disk.io_*`).
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
