# Arquitectura de InfraSight

Este documento es la fuente de verdad sobre cómo está estructurado
InfraSight. Define los componentes, los contratos entre ellos, el modelo de
datos y las decisiones no funcionales (seguridad, escala, despliegue).

Si el código contradice a este documento, o el código está mal o este
documento está desactualizado — abre una issue.

---

## 1. Visión general del sistema

```
┌──────────────────┐        HTTPS          ┌────────────────────────────┐
│  Agente Endpoint │  ───── ingesta ────►  │       Backend FastAPI      │
│  (Python, Linux) │   POST /v1/metrics    │                            │
│                  │   POST /v1/heartbeat  │  ┌──────────────────────┐  │
└──────────────────┘                       │  │ Router de ingesta    │  │
        ▲                                  │  │ Router de consulta   │  │
        │ token de enrolamiento            │  │ Evaluador de alertas │  │
        │ (un solo uso)                    │  │ Despachador webhooks │  │
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
        │                                                │ SQL (lectura)
        │                                  ┌─────────────┴──────────────┐
        └─── enrolamiento ◄──── HTTPS ─────│      Dashboard Next.js     │
                                           │       (App Router)         │
                                           └────────────────────────────┘
                                                         │
                                                         ▼
                                           ┌────────────────────────────┐
                                           │   Destinos de webhook      │
                                           │   Slack / Discord / HTTP   │
                                           └────────────────────────────┘
```

Cuatro componentes en ejecución:

1. **Agente endpoint** — un proceso Python corriendo en cada host Linux
   monitorizado.
2. **Backend API** — un servicio FastAPI que ingesta métricas, sirve al
   dashboard, evalúa reglas de alerta y despacha webhooks.
3. **Base de datos** — PostgreSQL con la extensión TimescaleDB. Todo el
   estado persistente vive aquí.
4. **Dashboard** — una app Next.js que habla con el backend por HTTPS.

Intencionalmente **no hay broker de mensajes** en v1. La ingesta escribe
directamente a Postgres. Añadiremos Redis/NATS solo si los benchmarks lo
fuerzan.

## 2. Componentes

### 2.1 Agente endpoint

- **Runtime:** Python 3.11+, empaquetado con PyInstaller para distribución.
- **Modelo de proceso:** un único proceso de larga duración (gestionado por
  `systemd`).
- **Bucle de recolección:** cada `collect_interval_s` (por defecto 30s),
  recoge una muestra de métricas usando `psutil` y la envía al backend.
- **Heartbeat:** independiente de las métricas, cada
  `heartbeat_interval_s` (por defecto 60s) — usado para determinar el
  estado online/offline incluso si la ingesta de métricas está limitada.
- **Buffering:** si el backend no es alcanzable, las muestras se bufferean
  en una cola en disco acotada (por defecto 1h, tope de 10MB) y se vacían
  al reconectar.
- **Configuración:** `/etc/infrasight/agent.toml`. Incluye URL de la API,
  ID del dispositivo, token derivado del enrolamiento, intervalos y
  feature flags.
- **Modelo de actualización:** v1 = reinstalación manual. M4 introduce un
  canal de auto-update.

### 2.2 Backend API

App FastAPI dividida en routers:

- `ingest/` — orientado al agente, autenticado con token:
  - `POST /v1/metrics` — lote de muestras de métricas
  - `POST /v1/heartbeat` — liveness + metadatos del agente
  - `POST /v1/enroll` — intercambia token de enrolamiento por token de
    dispositivo
- `query/` — orientado al dashboard, autenticado por sesión:
  - `GET /v1/devices` — listado del parque
  - `GET /v1/devices/{id}` — detalle del dispositivo + métricas recientes
  - `GET /v1/devices/{id}/metrics?from=&to=&series=` — consulta de series
    temporales
  - `GET /v1/alerts`, `POST /v1/alerts/{id}/ack`, `POST /v1/alerts/{id}/close`
  - `POST /v1/interventions` — crear un informe de intervención
- `admin/` — gestión de orgs/usuarios, CRUD de reglas de alerta,
  configuración de webhooks.

Los workers en segundo plano corren en el mismo proceso (lifespan de
FastAPI + tareas `asyncio`) para v1:

- **Evaluador de alertas** — cada 30s, para cada regla activa, consulta la
  ventana de métrica relevante y la compara contra el umbral. Abre /
  cierra / suprime alertas en consecuencia.
- **Despachador de webhooks** — vacía una cola en proceso de envíos
  pendientes con reintentos (backoff exponencial, 5 intentos).
- **Comprobador de liveness** — marca como `offline` los dispositivos cuyo
  último heartbeat sea más antiguo que `offline_threshold_s` (por defecto
  180s).

### 2.3 Base de datos

PostgreSQL 16 con la extensión TimescaleDB. Una sola base de datos, esquema
dividido por preocupación (relacional vs. series temporales).

Ver [§3 Modelo de datos](#3-modelo-de-datos).

### 2.4 Dashboard

Next.js 14 con App Router. Server Components para el fetch de datos contra
el backend; Client Components solo donde la interactividad lo exige
(gráficas, formularios). Auth mediante cookies de sesión emitidas por el
backend.

Páginas clave:

- `/` — vista general del parque
- `/devices/[id]` — métricas e historial por dispositivo
- `/alerts` — alertas abiertas y recientemente cerradas
- `/interventions` — log buscable de intervenciones
- `/settings/rules` — editor de reglas de alerta
- `/settings/webhooks` — configuración de webhooks

## 3. Modelo de datos

Preparado para multi-tenant: cada fila que pertenezca a un cliente lleva
`org_id`. v1 sale con una única org sembrada automáticamente.

### 3.1 Tablas relacionales

```sql
-- Tenancy
orgs(id UUID PK, name TEXT, created_at TIMESTAMPTZ)

-- Operadores de la plataforma
users(id UUID PK, org_id UUID FK, email CITEXT UNIQUE, password_hash TEXT,
      role TEXT CHECK (role IN ('admin','operator','viewer')),
      created_at TIMESTAMPTZ)

-- Máquinas monitorizadas
devices(id UUID PK, org_id UUID FK, hostname TEXT, os TEXT, kernel TEXT,
        agent_version TEXT, enrolled_at TIMESTAMPTZ,
        last_seen_at TIMESTAMPTZ,
        status TEXT CHECK (status IN ('online','offline','stale')),
        labels JSONB DEFAULT '{}'::jsonb)

-- Tokens de larga duración por dispositivo para auth de ingesta
device_tokens(id UUID PK, device_id UUID FK, token_hash TEXT,
              created_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ NULL)

-- Tokens de enrolamiento de corta duración emitidos por el dashboard
enrollment_tokens(id UUID PK, org_id UUID FK, token_hash TEXT,
                  expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ NULL,
                  created_by UUID FK users.id)

-- Reglas de alerta
alert_rules(id UUID PK, org_id UUID FK, name TEXT, metric TEXT,
            comparator TEXT CHECK (comparator IN ('>','>=','<','<=','==')),
            threshold DOUBLE PRECISION,
            duration_s INTEGER,
            scope JSONB,           -- p. ej. {"device_id": "..."} o {"label": {...}}
            severity TEXT CHECK (severity IN ('info','warning','critical')),
            enabled BOOLEAN DEFAULT TRUE)

-- Alertas abiertas / históricas
alerts(id UUID PK, org_id UUID FK, rule_id UUID FK, device_id UUID FK,
       opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ NULL,
       state TEXT CHECK (state IN ('firing','acked','resolved','closed')),
       last_value DOUBLE PRECISION,
       acked_by UUID FK users.id NULL,
       acked_at TIMESTAMPTZ NULL)

-- Seguimientos escritos por humanos
interventions(id UUID PK, org_id UUID FK, alert_id UUID FK NULL,
              device_id UUID FK, author_id UUID FK users.id,
              summary TEXT, body_md TEXT,
              started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ NULL)

-- Configuración de notificaciones salientes
webhooks(id UUID PK, org_id UUID FK, kind TEXT CHECK (kind IN ('slack','discord','generic')),
         url TEXT, secret TEXT NULL, enabled BOOLEAN DEFAULT TRUE)
```

Índices útiles (no exhaustivo):

- `devices(org_id, status)`
- `alerts(org_id, state, opened_at DESC)`
- `interventions(org_id, device_id, started_at DESC)`

### 3.2 Tablas de series temporales

Una única hypertable de Timescale, esquema estrecho, una fila por
`(device_id, metric)` por muestra:

```sql
metrics(
  ts          TIMESTAMPTZ NOT NULL,
  org_id      UUID        NOT NULL,
  device_id   UUID        NOT NULL,
  metric      TEXT        NOT NULL,   -- p. ej. 'cpu.usage_pct', 'mem.used_bytes'
  value       DOUBLE PRECISION NOT NULL,
  labels      JSONB       NOT NULL DEFAULT '{}'::jsonb
                          -- p. ej. {"mountpoint":"/"} o {"iface":"eth0"}
);

SELECT create_hypertable('metrics', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON metrics (device_id, metric, ts DESC);
CREATE INDEX ON metrics (org_id, ts DESC);
```

Políticas de retención y compresión (valores por defecto, ajustables por
despliegue):

- **Compresión:** los chunks de más de 7 días se comprimen.
- **Retención:** los datos en crudo se descartan tras 90 días.
- **Continuous aggregates:** rollups a 1 minuto y 1 hora para consultas de
  gráficas que abarquen días/semanas.

El nombrado de métricas sigue una convención dotted en minúsculas:

| Métrica                 | Unidad        | Notas                          |
|-------------------------|---------------|--------------------------------|
| `cpu.usage_pct`         | porcentaje 0-100 | global                      |
| `cpu.load1`             | float         | load average a 1 minuto        |
| `mem.used_bytes`        | bytes         |                                |
| `mem.available_bytes`   | bytes         |                                |
| `swap.used_bytes`       | bytes         |                                |
| `disk.used_bytes`       | bytes         | `labels.mountpoint`            |
| `disk.used_pct`         | porcentaje    | `labels.mountpoint`            |
| `disk.io_read_bytes`    | bytes/s       | `labels.device`                |
| `disk.io_write_bytes`   | bytes/s       | `labels.device`                |
| `net.rx_bytes`          | bytes/s       | `labels.iface`                 |
| `net.tx_bytes`          | bytes/s       | `labels.iface`                 |
| `host.uptime_s`         | segundos      |                                |

El contrato completo del payload del agente vive en
[`AGENT_PROTOCOL.md`](AGENT_PROTOCOL.md).

## 4. Flujo de datos

### 4.1 Enrolamiento

1. El operador entra al dashboard, hace clic en **Añadir dispositivo** y
   obtiene un token de enrolamiento de un solo uso (TTL 1h).
2. El operador ejecuta el script de instalación en el host destino con ese
   token.
3. El agente llama a `POST /v1/enroll` con el token de enrolamiento + datos
   del host (hostname, OS, kernel).
4. El backend valida el token, crea una fila en `devices`, emite un
   `device_token` de larga duración y lo devuelve.
5. El agente persiste el token de dispositivo en
   `/etc/infrasight/agent.toml` (modo 0600, propietario el usuario de
   servicio del agente) y empieza a recolectar.

### 4.2 Ingesta de métricas

1. El agente recoge una muestra y construye un `IngestBatch` (ver doc del
   protocolo).
2. El agente hace `POST /v1/metrics` con
   `Authorization: Bearer <device_token>`.
3. El backend valida el token, resuelve `device_id` y `org_id`, e
   `INSERT`a filas en `metrics`. Actualiza `devices.last_seen_at`.
4. El agente recibe `204 No Content` en caso de éxito o un error
   estructurado.

### 4.3 Evaluación de alertas

Corre cada 30s:

1. Para cada fila habilitada en `alert_rules`, ejecuta una consulta SQL del
   tipo:
   ```sql
   SELECT device_id, AVG(value)
   FROM   metrics
   WHERE  org_id = $1
     AND  metric = $2
     AND  ts >= now() - make_interval(secs => $3)
     AND  -- filtro de scope, p. ej. device_id IN (...) o labels @> ...
   GROUP BY device_id
   HAVING AVG(value) <comparator> $4;
   ```
2. Para cada dispositivo devuelto, hace upsert en `alerts`:
   - Si no hay alerta abierta para `(rule_id, device_id)`, INSERTa una con
     estado `firing`.
   - Si existe y está en `firing`/`acked`, actualiza `last_value`.
3. Para dispositivos que antes tenían una alerta abierta y ya no
   coinciden, transiciona la alerta a `resolved` (auto-cierre).
4. En las transiciones de estado, encola entregas de webhook para todos
   los webhooks de la org.

### 4.4 Informes de intervención

Disparado manualmente por un operador desde el dashboard. Una intervención
puede estar enlazada a una alerta concreta (`alert_id`) o ser autónoma
contra un dispositivo. Una intervención cerrada es inmutable — las
correcciones requieren una entrada nueva que referencie a la original.

## 5. Seguridad

### 5.1 Autenticación

| Llamante               | Mecanismo                                          |
|------------------------|----------------------------------------------------|
| Agente → backend       | Bearer token de dispositivo (larga duración, revocable) |
| Operador → backend     | Email + contraseña, cookie de sesión (HttpOnly, Secure, SameSite=Lax) |
| Operador → enrolamiento| Token de enrolamiento de un solo uso (TTL 1h)      |
| Backend → webhook      | Cabecera de firma HMAC-SHA256 por webhook          |

Todos los tokens se almacenan hasheados (Argon2id para contraseñas de
usuario, SHA-256 con prefijo aleatorio para tokens de máquina — ya tienen
alta entropía).

### 5.2 Transporte

TLS terminado en un reverse proxy (Caddy o Traefik en el compose de
referencia). El backend escucha en HTTP plano dentro de la red Docker. Las
conexiones del agente requieren HTTPS en producción; se permite HTTP solo
cuando `api_url` resuelve a una dirección privada RFC1918 / loopback.

### 5.3 Autorización

Roles dentro de una org en v1:

- `admin` — todo, incluyendo gestión de usuarios y edición de reglas de
  alerta.
- `operator` — confirmar/cerrar alertas, escribir intervenciones, ver
  todos los datos.
- `viewer` — solo lectura.

El acceso entre orgs es imposible: cada consulta está parametrizada por
el `org_id` de la sesión y las restricciones de la base de datos lo
reflejan.

### 5.4 Modelo de amenazas (resumido)

Dentro del alcance:

- Un agente comprometido solo expone datos de ese dispositivo y es
  revocable.
- Un operador con rol `viewer` no puede escalar privilegios.
- El endpoint de ingesta es resistente a inundaciones (rate-limit por
  token de dispositivo).

Fuera del alcance para v1:

- Defenderse contra un operador malicioso con rol `admin` (no hay un log
  de auditoría firmado offline aparte).
- Cifrado extremo a extremo entre agente y backend más allá de TLS.

## 6. Despliegue

El despliegue de referencia es `docker compose` sobre una sola VM:

```
deploy/compose/
├── docker-compose.yml
├── .env.example
└── caddy/Caddyfile
```

Servicios: `caddy` (TLS), `backend` (FastAPI/Uvicorn), `dashboard`
(Next.js standalone build), `db` (imagen oficial de TimescaleDB). El
agente **no** forma parte de este compose — se despliega en cada host
monitorizado por separado.

Regla aproximada de dimensionado (a validar en M2):

- 100 endpoints @ intervalo de 30s, 12 métricas cada uno → ~3.5M filas/día
  → encaja cómodamente en una VM de 2 vCPU / 4 GB con la compresión por
  defecto de Timescale.

## 7. Cuestiones abiertas

Estas se dejan abiertas a propósito y se resolverán según vayan
aterrizando los milestones:

- ¿Sacamos un endpoint de scrape Prometheus en el backend para usuarios
  que ya tengan Grafana? (Probablemente sí, M4.)
- ¿Cómo se despliegan los cambios de configuración del agente — pull (el
  agente relee en la respuesta de heartbeat) o push (iniciado por el
  servidor)? (Inclinación pull.)
- Timing de SSO (OIDC) — ¿M4 o post-1.0?

## 8. Glosario

- **Endpoint / dispositivo** — un host monitorizado que ejecuta el agente.
- **Org** — un tenant. v1 sale con una única org auto-creada.
- **Regla** — una definición almacenada que produce alertas cuando se
  cumple.
- **Alerta** — una instancia de una regla disparándose para un
  dispositivo concreto.
- **Intervención** — un informe escrito por un humano sobre la acción
  tomada en respuesta a una alerta (o un evento de mantenimiento ad-hoc).
