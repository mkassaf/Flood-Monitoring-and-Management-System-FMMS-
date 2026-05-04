-- FMMS — Postgres + TimescaleDB initialization
--
-- Runs once on first container start (mounted to /docker-entrypoint-initdb.d).
-- Creates two logical schemas in one DB for the PoC:
--   * opdb       — operational store (areas, sensors, users, alerts)
--   * tsdb       — telemetry hypertable
-- Production splits these into separate physical instances (architecture.md §6.1).

\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()

CREATE SCHEMA IF NOT EXISTS opdb;
CREATE SCHEMA IF NOT EXISTS tsdb;

-- ─── opdb: areas, sensors, users, alerts, thresholds ──────────────

CREATE TABLE opdb.region (
    region_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE opdb.city (
    city_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    region_id   UUID NOT NULL REFERENCES opdb.region(region_id),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (region_id, name)
);

CREATE TABLE opdb.area (
    area_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    city_id     UUID NOT NULL REFERENCES opdb.city(city_id),
    name        TEXT NOT NULL,
    risk_profile TEXT NOT NULL DEFAULT 'standard',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (city_id, name)
);

CREATE TABLE opdb.sensor (
    sensor_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    area_id      UUID NOT NULL REFERENCES opdb.area(area_id),
    label        TEXT,
    -- Hashed token for ADR-006 layer-2 identity. Never stored in plaintext.
    token_hash   TEXT NOT NULL,
    decommissioned_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sensor_area_idx ON opdb.sensor(area_id) WHERE decommissioned_at IS NULL;

CREATE TABLE opdb.threshold (
    area_id     UUID NOT NULL REFERENCES opdb.area(area_id),
    parameter   TEXT NOT NULL,
    warning_lo  DOUBLE PRECISION,
    warning_hi  DOUBLE PRECISION,
    critical_lo DOUBLE PRECISION,
    critical_hi DOUBLE PRECISION,
    PRIMARY KEY (area_id, parameter)
);

CREATE TABLE opdb.app_user (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    -- argon2id hash; auth-service is the only writer
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('area_manager', 'city_manager', 'regional_manager')),
    -- jurisdiction is a JSONB blob holding the list of UUIDs for the role's level
    jurisdiction JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE opdb.refresh_token (
    jti         UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES opdb.app_user(user_id),
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ
);
CREATE INDEX refresh_token_user_idx ON opdb.refresh_token(user_id) WHERE revoked_at IS NULL;

CREATE TABLE opdb.alert (
    alert_id     UUID PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('threshold','malfunction','priority')),
    severity     TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    area_id      UUID NOT NULL REFERENCES opdb.area(area_id),
    sensor_id    UUID,
    parameter    TEXT,
    value        DOUBLE PRECISION,
    threshold    DOUBLE PRECISION,
    ts_event     TIMESTAMPTZ NOT NULL,
    ts_emitted   TIMESTAMPTZ NOT NULL,
    ts_persisted TIMESTAMPTZ NOT NULL DEFAULT now(),
    context      JSONB NOT NULL DEFAULT '{}'::jsonb,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID REFERENCES opdb.app_user(user_id),
    ack_reason   TEXT
);
CREATE INDEX alert_area_emitted_idx ON opdb.alert(area_id, ts_emitted DESC);
CREATE INDEX alert_severity_emitted_idx ON opdb.alert(severity, ts_emitted DESC) WHERE acknowledged_at IS NULL;

CREATE TABLE opdb.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT NOT NULL,                -- "user:<uuid>" or "service:<name>"
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    outcome     TEXT NOT NULL CHECK (outcome IN ('allowed','denied')),
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_log_ts_idx ON opdb.audit_log(ts DESC);

-- ─── tsdb: telemetry hypertable + continuous aggregates ───────────

CREATE TABLE tsdb.telemetry (
    ts                       TIMESTAMPTZ NOT NULL,
    sensor_id                UUID NOT NULL,
    area_id                  UUID NOT NULL,
    status                   SMALLINT NOT NULL,
    mode                     TEXT NOT NULL CHECK (mode IN ('nominal','critical')),
    water_level_m            DOUBLE PRECISION,
    river_flow_velocity_m_s  DOUBLE PRECISION,
    rainfall_mm_h            DOUBLE PRECISION,
    soil_saturation_pct      DOUBLE PRECISION,
    wind_speed_m_s           DOUBLE PRECISION,
    wind_direction_deg       DOUBLE PRECISION,
    ingested_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

SELECT create_hypertable('tsdb.telemetry', by_range('ts', INTERVAL '1 day'));
SELECT add_dimension('tsdb.telemetry', by_hash('area_id', 4));

CREATE INDEX telemetry_sensor_ts_idx ON tsdb.telemetry(sensor_id, ts DESC);
CREATE INDEX telemetry_area_ts_idx ON tsdb.telemetry(area_id, ts DESC);

-- Continuous aggregate at 1-minute granularity (architecture.md §3.2 dashboard reads).
CREATE MATERIALIZED VIEW tsdb.telemetry_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', ts) AS bucket,
    area_id,
    AVG(water_level_m)           AS avg_water_level_m,
    MAX(water_level_m)           AS max_water_level_m,
    AVG(river_flow_velocity_m_s) AS avg_river_flow_velocity_m_s,
    AVG(rainfall_mm_h)           AS avg_rainfall_mm_h,
    AVG(soil_saturation_pct)     AS avg_soil_saturation_pct,
    AVG(wind_speed_m_s)          AS avg_wind_speed_m_s,
    COUNT(*)                     AS sample_count
FROM tsdb.telemetry
GROUP BY bucket, area_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('tsdb.telemetry_1min',
    start_offset => INTERVAL '1 hour',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

-- Compression policy on raw chunks older than 7 days (ADR-004).
ALTER TABLE tsdb.telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'area_id, sensor_id'
);
SELECT add_compression_policy('tsdb.telemetry', INTERVAL '7 days');

-- Retention: drop raw chunks older than 90 days (Phase 0 working assumption).
SELECT add_retention_policy('tsdb.telemetry', INTERVAL '90 days');
