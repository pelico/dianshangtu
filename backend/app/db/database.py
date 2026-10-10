"""SQLite 访问层。

设计要点（PLAN_v2 §6）：
- 不引入 ORM，sqlite3 标准库 + Row 工厂，保持依赖最小。
- 迁移用有序脚本列表 + _migrations 版本表；M1 一次性建齐全部表，后续里程碑只追加迁移。
- WAL 模式，兼容进程内 worker 与 API 并发读写。
"""
import sqlite3

from ..core.config import DATA_DIR

DB_PATH = DATA_DIR / "workbench.db"

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS preset (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'aplus_banner',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE preset_version (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id  TEXT NOT NULL REFERENCES preset(id),
    version    INTEGER NOT NULL,
    body_json  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (preset_id, version)
);
CREATE TABLE brand_profile (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    body_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE project (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    preset_version_id INTEGER,
    brand_profile_id  TEXT,
    brief             TEXT NOT NULL DEFAULT '',
    params_json       TEXT NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'created',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE project_ref (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES project(id),
    path       TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    order_no   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE plan (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES project(id),
    revision   INTEGER NOT NULL,
    body_json  TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'ai',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, revision)
);
CREATE TABLE job (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    target_id    TEXT,
    status       TEXT NOT NULL DEFAULT 'queued',
    attempt      INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT
);
CREATE TABLE asset (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        TEXT NOT NULL,
    module_id         TEXT,
    kind              TEXT NOT NULL DEFAULT 'image',
    path              TEXT,
    raw_path          TEXT,
    width             INTEGER,
    height            INTEGER,
    model             TEXT,
    mode              TEXT,
    params_json       TEXT NOT NULL DEFAULT '{}',
    prompt_text       TEXT NOT NULL DEFAULT '',
    prompt_edited     INTEGER NOT NULL DEFAULT 0,
    ref_hashes_json   TEXT NOT NULL DEFAULT '[]',
    preset_version_id INTEGER,
    plan_revision     INTEGER,
    parent_asset_id   INTEGER,
    attempt           INTEGER NOT NULL DEFAULT 0,
    qa_status         TEXT NOT NULL DEFAULT '',
    qa_json           TEXT NOT NULL DEFAULT '{}',
    tokens_json       TEXT NOT NULL DEFAULT '{}',
    cost_estimate     REAL NOT NULL DEFAULT 0,
    elapsed_s         REAL NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE setting (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_project  ON job(project_id, status);
CREATE INDEX IF NOT EXISTS idx_asset_project ON asset(project_id, module_id);
"""),
    (2, """
ALTER TABLE asset ADD COLUMN role TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS script (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    body_json  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""),
]


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        applied = {r["version"] for r in conn.execute("SELECT version FROM _migrations")}
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            conn.executescript(sql)
            conn.execute("INSERT INTO _migrations(version) VALUES (?)", (version,))
        conn.commit()
