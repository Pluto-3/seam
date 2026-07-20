-- Phase 5: the v2 data layer. Lean on purpose - four tables, each mirroring
-- something the sim already produces, just persisted properly instead of
-- living in whatever JSONL file a script happened to point at.

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    tick BIGINT NOT NULL,
    agent_id TEXT NOT NULL,
    tier TEXT NOT NULL,
    specialty TEXT,              -- fixes a real v1 gap: agents.py's snapshot() never
                                  -- logged specialty, so export_strategy.py's compare
                                  -- mode had to fall back to a separate stats.csv for
                                  -- the specialization index. Logged directly now.
    action TEXT NOT NULL,
    target TEXT,
    success BOOLEAN NOT NULL,
    state_before JSONB NOT NULL,
    state_after JSONB NOT NULL,
    delta JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run_tick_idx ON events (run_id, tick);
CREATE INDEX IF NOT EXISTS events_run_agent_idx ON events (run_id, agent_id);

CREATE TABLE IF NOT EXISTS lead_memory_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    tick BIGINT NOT NULL,
    lead_id TEXT NOT NULL,
    memory_summary TEXT NOT NULL,
    caution_bias DOUBLE PRECISION NOT NULL,
    trade_success_ratio DOUBLE PRECISION,
    hunger_scares_witnessed INTEGER NOT NULL,
    ts BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS lead_memory_run_lead_idx ON lead_memory_snapshots (run_id, lead_id, tick);

CREATE TABLE IF NOT EXISTS narrative_scenes (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    tick BIGINT NOT NULL,
    text TEXT NOT NULL,
    ts BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS narrative_run_idx ON narrative_scenes (run_id, tick);

-- Wave 5 (2026-07-20): renamed from settlement_snapshots - pre-dated the v3
-- N-society model, when "node" alone was enough to identify the one
-- settlement a run had. society_id and specialization_index added at the
-- same time. On an existing pre-Wave-5 database, don't just re-run this -
-- migrate in place instead (rename, add columns, backfill society_id from
-- the existing node column - every legacy run had exactly one settlement
-- per node, so that's an honest backfill; leave specialization_index NULL
-- for legacy rows rather than faking a value nobody actually computed at
-- the time). This CREATE TABLE is the shape for a genuinely fresh install
-- only, where specialization_index can be NOT NULL from day one.
CREATE TABLE IF NOT EXISTS society_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    tick BIGINT NOT NULL,
    society_id TEXT NOT NULL,
    node TEXT NOT NULL,
    population_alive INTEGER NOT NULL,
    roster_size INTEGER NOT NULL,
    avg_energy DOUBLE PRECISION NOT NULL,
    avg_hunger DOUBLE PRECISION NOT NULL,
    total_food_held DOUBLE PRECISION NOT NULL,
    specialization_index DOUBLE PRECISION NOT NULL,
    ts BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS society_run_idx ON society_snapshots (run_id, tick);
