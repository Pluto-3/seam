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

CREATE TABLE IF NOT EXISTS settlement_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    tick BIGINT NOT NULL,
    node TEXT NOT NULL,
    population_alive INTEGER NOT NULL,
    roster_size INTEGER NOT NULL,
    avg_energy DOUBLE PRECISION NOT NULL,
    avg_hunger DOUBLE PRECISION NOT NULL,
    total_food_held DOUBLE PRECISION NOT NULL,
    ts BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS settlement_run_idx ON settlement_snapshots (run_id, tick);
