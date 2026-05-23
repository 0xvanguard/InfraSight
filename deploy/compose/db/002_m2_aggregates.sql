-- =============================================================================
-- M2: agregados continuos, políticas de compresión y retención.
-- Se ejecuta automáticamente sólo en una DB recién creada (la imagen oficial
-- de TimescaleDB ejecuta /docker-entrypoint-initdb.d/* únicamente la primera
-- vez). Para una DB existente, ejecuta este script manualmente:
--   docker compose exec db psql -U infrasight -d infrasight -f /docker-entrypoint-initdb.d/002_m2_aggregates.sql
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Compresión de la hypertable raw.
--
-- Las consultas más frecuentes filtran por device_id y metric (con
-- desempate por ts), así que segmentamos por esa pareja para que los
-- chunks comprimidos puedan saltarse columnas no relevantes y devolver
-- rangos en O(metadatos).
-- -----------------------------------------------------------------------------
ALTER TABLE metrics
    SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'device_id, metric',
        timescaledb.compress_orderby   = 'ts DESC'
    );

SELECT add_compression_policy('metrics', INTERVAL '7 days', if_not_exists => TRUE);

-- -----------------------------------------------------------------------------
-- Retención: borra datos en crudo más antiguos que 90 días.
-- Los agregados continuos sobreviven y siguen siendo consultables.
-- -----------------------------------------------------------------------------
SELECT add_retention_policy('metrics', INTERVAL '90 days', if_not_exists => TRUE);

-- -----------------------------------------------------------------------------
-- Continuous aggregate a 1 minuto.
--
-- - AVG/MIN/MAX por bucket cubren la mayoría de visualizaciones (líneas y
--   bandas).
-- - COUNT permite distinguir buckets vacíos de buckets con valor cero,
--   útil cuando un mountpoint o interfaz desaparece.
-- - Materializado: las consultas del dashboard van directamente contra
--   esta vista, no contra la hypertable raw, salvo que pidan un rango
--   más reciente que la frontera materializada (Timescale lo combina
--   transparentemente).
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', ts) AS bucket,
    org_id,
    device_id,
    metric,
    labels,
    AVG(value)   AS avg,
    MIN(value)   AS min,
    MAX(value)   AS max,
    COUNT(*)     AS samples
FROM   metrics
GROUP  BY bucket, org_id, device_id, metric, labels
WITH NO DATA;

-- Refresco continuo: no toca el último minuto (puede estar incompleto)
-- y materializa hasta una hora hacia atrás cada minuto.
SELECT add_continuous_aggregate_policy(
    'metrics_1m',
    start_offset      => INTERVAL '1 hour',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE
);

-- -----------------------------------------------------------------------------
-- Continuous aggregate a 1 hora, construido a partir del de 1 minuto.
--
-- Hierarchical CAGGs reducen el coste de mantenimiento: el rollup horario
-- sólo lee buckets de un minuto ya materializados, no la hypertable raw.
--
-- Nota sobre AVG(avg): es una aproximación. El promedio matemáticamente
-- correcto sería SUM(avg * samples) / SUM(samples) (promedio ponderado).
-- En nuestro perfil de carga (collect_interval = 30 s) todos los buckets
-- de 1 minuto contienen ~2 muestras, así que la diferencia es < 1 % en la
-- práctica. Si en el futuro queremos garantías exactas, sustituiremos
-- esta vista por una con cálculo ponderado.
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', bucket) AS bucket,
    org_id,
    device_id,
    metric,
    labels,
    AVG(avg)       AS avg,
    MIN(min)       AS min,
    MAX(max)       AS max,
    SUM(samples)   AS samples
FROM   metrics_1m
GROUP  BY 1, org_id, device_id, metric, labels
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'metrics_1h',
    start_offset      => INTERVAL '1 day',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists     => TRUE
);

-- -----------------------------------------------------------------------------
-- Índices para acelerar las consultas del dashboard sobre los CAGGs.
-- Los CAGGs heredan el índice por tiempo, pero device_id+metric+ts
-- acelera muchísimo el camino caliente del frontend.
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_metrics_1m_device_metric_bucket
    ON metrics_1m (device_id, metric, bucket DESC);

CREATE INDEX IF NOT EXISTS idx_metrics_1h_device_metric_bucket
    ON metrics_1h (device_id, metric, bucket DESC);
