"""SQLite stores audit metadata only. No spreadsheet contents are persisted."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _db_path() -> Path:
    return Path(os.environ.get("DATADOCTOR_DB_PATH", "data/datadoctor.sqlite3"))


def _connection():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        action TEXT NOT NULL,
        file_type TEXT NOT NULL,
        rows INTEGER NOT NULL,
        columns INTEGER NOT NULL,
        missing_cells INTEGER NOT NULL,
        duplicate_rows INTEGER NOT NULL
    )""")
    return conn


def record(action: str, file_type: str, summary: dict) -> None:
    with _connection() as conn:
        conn.execute("""INSERT INTO runs (action, file_type, rows, columns, missing_cells, duplicate_rows)
            VALUES (?, ?, ?, ?, ?, ?)""", (
            action, file_type, summary["rows"], summary["columns"],
            summary["missing_cells"], summary["duplicate_rows"],
        ))


def history(limit: int = 20) -> list[dict]:
    with _connection() as conn:
        conn.row_factory = sqlite3.Row
        data = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 100),)).fetchall()
        return [dict(row) for row in data]
