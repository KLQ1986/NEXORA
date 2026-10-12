"""SQLite access for the Platform core: one file, WAL mode, explicit transactions."""
import sqlite3
import threading
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
    lane            TEXT NOT NULL DEFAULT 'interactive',
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
CREATE TABLE IF NOT EXISTS calls (
    call_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    at         REAL NOT NULL,
    adapter    TEXT NOT NULL,
    operation  TEXT NOT NULL,
    runs       TEXT NOT NULL,
    seconds    REAL NOT NULL,
    ok         INTEGER NOT NULL,
    error_code TEXT,
    attempt_id TEXT,
    units      REAL NOT NULL DEFAULT 0,
    cost       REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS calls_by_time ON calls(at);
CREATE TABLE IF NOT EXISTS volumes (
    volume_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    mount_path TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    asset_id      TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    origin        TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_versions (
    seq                   INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id            TEXT NOT NULL UNIQUE,
    asset_id              TEXT NOT NULL REFERENCES assets(asset_id),
    role                  TEXT NOT NULL,
    volume_id             TEXT NOT NULL REFERENCES volumes(volume_id),
    relative_path         TEXT NOT NULL,
    checksum              TEXT,
    size                  INTEGER NOT NULL,
    metadata              TEXT NOT NULL DEFAULT '{}',
    parents               TEXT NOT NULL DEFAULT '[]',
    created_by_attempt_id TEXT,
    created_at            REAL NOT NULL,
    UNIQUE (volume_id, relative_path)
);
CREATE INDEX IF NOT EXISTS versions_by_checksum ON asset_versions(checksum);
CREATE TABLE IF NOT EXISTS moments (
    moment_id  TEXT PRIMARY KEY,
    asset_id   TEXT NOT NULL,
    level      TEXT NOT NULL,
    t_start    REAL NOT NULL,
    t_end      REAL NOT NULL,
    text       TEXT NOT NULL,
    data       TEXT NOT NULL DEFAULT '{}',
    source     TEXT NOT NULL DEFAULT 'model',
    analyzer   TEXT,
    created_at REAL NOT NULL,
    UNIQUE (asset_id, level, t_start, t_end)
);
CREATE VIRTUAL TABLE IF NOT EXISTS moments_fts USING fts5(text, moment_id UNINDEXED, tokenize = "unicode61 remove_diacritics 2");
CREATE TABLE IF NOT EXISTS moment_vectors (
    moment_id TEXT PRIMARY KEY,
    vector    BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    format     TEXT NOT NULL DEFAULT 'landscape',
    auto_accept INTEGER NOT NULL DEFAULT 0,
    style      TEXT,
    narration_dir TEXT,
    budget_cap REAL,
    music_path TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS scripts (
    script_id      TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(project_id),
    version        INTEGER NOT NULL,
    match_approved INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shots (
    shot_id   TEXT PRIMARY KEY,
    script_id TEXT NOT NULL REFERENCES scripts(script_id),
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    scene     TEXT,
    brief     TEXT,
    screen_text TEXT,
    target_seconds REAL,
    sound_cue TEXT,
    is_fact   INTEGER NOT NULL DEFAULT 0,
    source    TEXT
);
CREATE TABLE IF NOT EXISTS selections (
    shot_id    TEXT PRIMARY KEY REFERENCES shots(shot_id),
    status     TEXT NOT NULL,
    asset_id   TEXT,
    moment_id  TEXT,
    t_in       REAL,
    t_out      REAL,
    score      REAL,
    reason     TEXT,
    alternates TEXT NOT NULL DEFAULT '[]',
    decided_by TEXT NOT NULL DEFAULT 'system',
    extras     TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS renders (
    render_id  TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    script_id  TEXT NOT NULL,
    path       TEXT NOT NULL,
    qc         TEXT NOT NULL,
    created_at REAL NOT NULL,
    review     TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    stage_key  TEXT,
    reason     TEXT,
    created_at REAL NOT NULL,
    read_at    REAL
);
CREATE TABLE IF NOT EXISTS generations (
    record_id        TEXT PRIMARY KEY,
    shot_id          TEXT NOT NULL,
    kind             TEXT NOT NULL,
    spec             TEXT NOT NULL,
    prompt           TEXT NOT NULL,
    compiler_version TEXT NOT NULL,
    provider         TEXT NOT NULL,
    model            TEXT,
    seed             INTEGER,
    asset_id         TEXT,
    status           TEXT NOT NULL DEFAULT 'candidate',
    created_at       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS match_feedback (
    line      TEXT NOT NULL,
    moment_id TEXT NOT NULL,
    asset_id  TEXT,
    verdict   TEXT NOT NULL,
    at        REAL NOT NULL,
    PRIMARY KEY (line, moment_id)
);
CREATE TABLE IF NOT EXISTS audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at       REAL NOT NULL,
    method   TEXT NOT NULL,
    path     TEXT NOT NULL,
    status   INTEGER NOT NULL,
    detail   TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# Columns added after a table first shipped. CREATE TABLE IF NOT EXISTS does not add them to an existing database.
MIGRATIONS = [
    ("projects", "format", "TEXT NOT NULL DEFAULT 'landscape'"),
    ("projects", "music_path", "TEXT"),
    ("projects", "auto_accept", "INTEGER NOT NULL DEFAULT 0"),
    ("projects", "style", "TEXT"),
    ("projects", "narration_dir", "TEXT"),
    ("projects", "budget_cap", "REAL"),
    ("renders", "review", "TEXT"),
    ("assets", "note", "TEXT"),
    ("shots", "scene", "TEXT"),
    ("shots", "target_seconds", "REAL"),
    ("shots", "sound_cue", "TEXT"),
    ("shots", "is_fact", "INTEGER NOT NULL DEFAULT 0"),
    ("shots", "source", "TEXT"),
    ("projects", "research", "TEXT"),
    ("shots", "brief", "TEXT"),
    ("shots", "screen_text", "TEXT"),
    ("projects", "profile", "TEXT"),
    ("projects", "voice", "TEXT"),
    ("projects", "music_gain", "REAL"),
    ("projects", "template", "TEXT"),
    ("assets", "rating", "INTEGER NOT NULL DEFAULT 0"),
    ("assets", "collections", "TEXT NOT NULL DEFAULT '[]'"),
    ("stages", "lane", "TEXT NOT NULL DEFAULT 'interactive'"),
    ("selections", "extras", "TEXT NOT NULL DEFAULT '{}'"),
    ("shots", "fact_check", "TEXT"),
    ("scripts", "critique", "TEXT"),
    ("projects", "due_date", "TEXT"),
    ("assets", "rejected", "INTEGER NOT NULL DEFAULT 0"),
    ("shots", "gen", "TEXT"),
    ("projects", "options", "TEXT"),
    ("projects", "channel", "TEXT"),
    ("projects", "bible", "TEXT"),
    ("generations", "quality", "TEXT"),
]


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    for table, column, ddl in MIGRATIONS:
        if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass                                     # another connection added it first
    return conn


class LocalConnections:
    """One connection per thread. The API serves requests on worker threads while the pipeline worker
    runs on another; SQLite connections must not cross threads, and WAL lets them work side by side."""

    def __init__(self, path: str | Path):
        self._path, self._local = path, threading.local()
        self.get()                                  # create the schema at construction

    def get(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = connect(self._path)
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
