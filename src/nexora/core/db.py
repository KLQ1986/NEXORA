"""SQLite access for the Platform core: one file, WAL mode, explicit transactions."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    pipeline_id      TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    project_id       TEXT,
    subject_ref      TEXT,
    priority         INTEGER NOT NULL DEFAULT 0,
    idempotency_key  TEXT UNIQUE,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    budget_cap       REAL,
    created_at       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stages (
    stage_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    position        INTEGER NOT NULL,
    stage_key       TEXT NOT NULL,
    depends_on      TEXT NOT NULL,
    status          TEXT NOT NULL,
    effect_class    TEXT NOT NULL,
    costly          INTEGER NOT NULL,
    gate            INTEGER NOT NULL,
    max_attempts    INTEGER NOT NULL,
    timeout_seconds REAL NOT NULL,
    outputs         TEXT,
    blocked_reason  TEXT,
    next_retry_at   REAL,
    UNIQUE (run_id, stage_key)
);
CREATE INDEX IF NOT EXISTS stages_by_status ON stages(status);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id        TEXT PRIMARY KEY,
    stage_id          TEXT NOT NULL REFERENCES stages(stage_id),
    number            INTEGER NOT NULL,
    outcome           TEXT,
    worker_id         TEXT NOT NULL,
    claim_expires_at  REAL NOT NULL,
    heartbeat_at      REAL NOT NULL,
    external_ref      TEXT,
    error_code        TEXT,
    error_message     TEXT,
    started_at        REAL NOT NULL,
    ended_at          REAL
);
CREATE INDEX IF NOT EXISTS attempts_by_stage ON attempts(stage_id);
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    stage_id    TEXT,
    attempt_id  TEXT,
    kind        TEXT NOT NULL,
    payload     TEXT,
    actor       TEXT NOT NULL,
    occurred_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cost_records (
    cost_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    attempt_id  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    units       REAL NOT NULL,
    cost        REAL NOT NULL,
    currency    TEXT NOT NULL,
    recorded_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def write(conn: sqlite3.Connection):
    """One write transaction. BEGIN IMMEDIATE takes the write lock up front, so of two
    concurrent claimers exactly one proceeds and the other sees the result."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
