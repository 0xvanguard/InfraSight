-- =============================================================================
-- Inicialización de la base de datos para M1.
-- Este script lo ejecuta automáticamente la imagen de TimescaleDB la primera
-- vez que se levanta el contenedor (por estar en /docker-entrypoint-initdb.d).
--
-- Esquema deliberadamente reducido para M1: solo lo necesario para que el
-- pipeline agente -> backend -> dashboard funcione de extremo a extremo.
-- Las tablas de alertas / intervenciones / reglas llegan en M3.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- para gen_random_uuid()

-- -----------------------------------------------------------------------------
-- Tenancy mínima: una sola org sembrada automáticamente.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orgs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Org por defecto con un UUID fijo para simplicidad en M1.
INSERT INTO orgs (id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'default')
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Dispositivos monitorizados.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID        NOT NULL REFERENCES orgs(id),
    hostname        TEXT        NOT NULL,
    machine_id      TEXT        NOT NULL,
    os              TEXT,
    kernel          TEXT,
    agent_version   TEXT,
    enrolled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ,
    UNIQUE (org_id, machine_id)
);

CREATE INDEX IF NOT EXISTS idx_devices_org_lastseen
    ON devices (org_id, last_seen_at DESC);

-- -----------------------------------------------------------------------------
-- Tokens por dispositivo (M1: hash SHA-256 hex).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_tokens (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id   UUID        NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    token_hash  TEXT        NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_device_tokens_device
    ON device_tokens (device_id) WHERE revoked_at IS NULL;

-- -----------------------------------------------------------------------------
-- Métricas: hypertable de Timescale, esquema estrecho.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics (
    ts          TIMESTAMPTZ      NOT NULL,
    org_id      UUID             NOT NULL,
    device_id   UUID             NOT NULL,
    metric      TEXT             NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    labels      JSONB            NOT NULL DEFAULT '{}'::jsonb
);

SELECT create_hypertable(
    'metrics', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_metrics_device_metric_ts
    ON metrics (device_id, metric, ts DESC);

CREATE INDEX IF NOT EXISTS idx_metrics_org_ts
    ON metrics (org_id, ts DESC);
