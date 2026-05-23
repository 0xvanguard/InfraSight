# Protocolo del Agente de InfraSight

Este documento especifica el contrato HTTP entre el **agente endpoint** y el
**backend de InfraSight**. Cualquier cosa no especificada aquí es
comportamiento indefinido y no debe asumirse.

- **Versión:** `v1`
- **Transporte:** HTTPS (HTTP solo permitido contra direcciones privadas)
- **Codificación:** JSON, UTF-8
- **Compresión:** se acepta `Content-Encoding: gzip` en peticiones
  originadas por el agente; el agente DEBERÍA usarla para lotes > 4 KiB.
- **Tiempo:** todos los timestamps son RFC 3339 con offset de zona horaria,
  preferentemente UTC (`2026-05-23T14:32:01Z`).

---

## 1. Autenticación

| Endpoint              | Auth                                              |
|-----------------------|---------------------------------------------------|
| `POST /v1/enroll`     | `Authorization: Bearer <enrollment_token>` (un solo uso) |
| `POST /v1/heartbeat`  | `Authorization: Bearer <device_token>`            |
| `POST /v1/metrics`    | `Authorization: Bearer <device_token>`            |

El `device_token` es opaco, ≥ 32 bytes de entropía, codificado en
base64url. El agente lo trata como secreto y lo guarda en un fichero con
modo `0600`.

Si una petición se rechaza con `401 invalid_token`, el agente DEBE dejar
de enviar y exponer el error en sus logs / salida de estado. NO DEBE
reintentar con el mismo token. El re-enrolamiento es una acción manual del
operador.

## 2. Formatos comunes de respuesta

Los endpoints de ingesta exitosos devuelven `204 No Content` con cuerpo
vacío.

Todos los errores devuelven:

```json
{
  "error": "codigo_string",
  "message": "explicación legible para humanos",
  "retry_after_s": 30
}
```

`retry_after_s` está presente solo cuando se espera que el cliente haga
backoff.

| HTTP | `error`                | Significado                                |
|------|------------------------|--------------------------------------------|
| 400  | `bad_request`          | JSON malformado o violación de esquema     |
| 401  | `invalid_token`        | Token desconocido, expirado o revocado     |
| 403  | `device_disabled`      | El dispositivo existe pero está desactivado administrativamente |
| 409  | `enrollment_consumed`  | Token de enrolamiento ya usado             |
| 413  | `payload_too_large`    | El lote excede el límite del servidor (por defecto 1 MiB) |
| 422  | `unsupported_metric`   | Nombre de métrica desconocido en el lote   |
| 429  | `rate_limited`         | Demasiadas peticiones; respetar `retry_after_s` |
| 5xx  | `server_error`         | Reintentar con backoff exponencial         |

## 3. Endpoints

### 3.1 `POST /v1/enroll`

Intercambia un token de enrolamiento de un solo uso por un token de
dispositivo de larga duración y un registro de dispositivo.

**Petición**

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

`machine_id` es el contenido de `/etc/machine-id`. Si ya existe un
dispositivo con el mismo `(org_id, machine_id)`, el backend reutiliza ese
registro y rota su token en lugar de crear un duplicado.

**Respuesta — `200 OK`**

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

El objeto `config` es autoritativo — el agente DEBE adoptar estos valores
para sus bucles principales, sobrescribiendo los defaults compilados.

### 3.2 `POST /v1/heartbeat`

Reporta liveness y los metadatos actuales del agente. Se envía cada
`heartbeat_interval_s`. Barato y de tamaño fijo; esto es lo que determina
`devices.status` en el lado del servidor.

**Petición**

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

`queue_depth` es el número de muestras buffereadas que el agente todavía
no ha vaciado. El dashboard lo muestra como señal de salud.

**Respuesta — `200 OK`**

```json
{
  "config": {
    "collect_interval_s":   30,
    "heartbeat_interval_s": 60,
    "max_batch_bytes":      1048576
  }
}
```

El agente DEBE aplicar cualquier valor de configuración que haya cambiado
en la siguiente iteración del bucle. Los cambios de configuración se
propagan vía heartbeat — no hay un push de configuración aparte.

### 3.3 `POST /v1/metrics`

Envía un lote de muestras de métricas.

**Petición**

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

Reglas:

- `batch_id` es un ULID generado por el cliente. El servidor trata
  `(device_id, batch_id)` como idempotente: los reenvíos del mismo lote
  se aceptan con `204` pero no se insertan dos veces.
- `samples` es un array no vacío, ≤ 5.000 entradas por lote.
- Los nombres de `metric` desconocidos provocan el rechazo del **lote
  entero** con `422` — nunca se descartan silenciosamente.
- `labels` es opcional; cuando está presente, las claves son ASCII en
  minúsculas, los valores son cadenas cortas (≤ 64 chars). Claves de
  label reservadas: `org_id`, `device_id`, `metric`, `ts`, `value`.
- El servidor puede cerrar la conexión si el cuerpo decodificado excede
  `max_batch_bytes`.

**Respuesta — `204 No Content`** en caso de éxito.

## 4. Catálogo de métricas (v1)

El agente DEBE emitir solo métricas de este catálogo. Añadir una nueva
métrica es un cambio de protocolo y sube la versión menor.

| Métrica                 | Unidad        | Labels requeridas       | Notas                       |
|-------------------------|---------------|-------------------------|-----------------------------|
| `cpu.usage_pct`         | porcentaje 0-100 | —                    | global, todos los cores     |
| `cpu.load1`             | float         | —                       | load average a 1 minuto     |
| `cpu.load5`             | float         | —                       | load average a 5 minutos    |
| `cpu.load15`            | float         | —                       | load average a 15 minutos   |
| `mem.used_bytes`        | bytes         | —                       |                             |
| `mem.available_bytes`   | bytes         | —                       |                             |
| `swap.used_bytes`       | bytes         | —                       |                             |
| `disk.used_bytes`       | bytes         | `mountpoint`            | una muestra por mountpoint  |
| `disk.used_pct`         | porcentaje    | `mountpoint`            |                             |
| `disk.io_read_bytes`    | bytes/s       | `device`                | ratio, derivado             |
| `disk.io_write_bytes`   | bytes/s       | `device`                | ratio, derivado             |
| `net.rx_bytes`          | bytes/s       | `iface`                 | ratio, derivado             |
| `net.tx_bytes`          | bytes/s       | `iface`                 | ratio, derivado             |
| `host.uptime_s`         | segundos      | —                       |                             |

El agente DEBERÍA omitir pseudo-sistemas de ficheros (`tmpfs`,
`devtmpfs`, `overlay`, …) e interfaces de red de loopback / bridge de
docker por defecto. Esta lista es configurable en `agent.toml`.

## 5. Reintentos, backoff y buffering

- En caso de `5xx` o error de red: reintentar con backoff exponencial
  empezando en 1s, doblando, con tope en 60s, jitter ±20%.
- En caso de `429`: dormir exactamente `retry_after_s` antes de
  cualquier petición posterior.
- En caso de `4xx` distinto de `429`: **no** reintentar el mismo
  payload. Loguear y descartar.
- Mientras el backend no sea alcanzable, el agente bufferea muestras en
  una cola en disco acotada (FIFO, descarta los más antiguos cuando se
  llena). Tope por defecto: 1 hora de muestras o 10 MiB, lo que sea
  menor. Las muestras buffereadas se vacían en orden original al
  reconectar.
- Los heartbeats nunca se bufferean; si un heartbeat falla, el siguiente
  programado lo reemplaza.

## 6. Versionado

El prefijo de ruta `/v1` es parte del contrato. Los cambios
incompatibles hacia atrás (campos eliminados, semántica cambiada,
nuevos campos requeridos) requieren un prefijo `/v2` y una ventana de
deprecación de al menos una release menor del agente.

Las adiciones compatibles hacia atrás (nuevos campos opcionales, nuevas
métricas añadidas al catálogo, nuevos códigos de error) se permiten
dentro de `/v1` y no requieren actualizar el agente — pero los agentes
DEBEN tolerar campos desconocidos en las respuestas sin fallar.

## 7. Referencia: bucle mínimo del agente (pseudo-código)

```python
def run(cfg):
    token = cfg.device_token
    while True:
        sample_batch = collect()                  # psutil + ensamblado de labels
        try:
            post_metrics(token, sample_batch)
        except Retryable as e:
            buffer.push(sample_batch)
        except Fatal as e:
            log.error("error fatal de ingesta: %s", e)
            return
        sleep(cfg.collect_interval_s)
```

El bucle real ejecuta además el heartbeat con su propia planificación,
vacía el buffer cuando la ingesta tiene éxito, y maneja las
actualizaciones de configuración de las respuestas de heartbeat.
