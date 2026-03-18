"""
application_tracker.py

SQLite-backed tracker for all job applications.
Thread-safe via connection-per-call pattern.
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id              TEXT UNIQUE,
    company             TEXT NOT NULL,
    job_title           TEXT NOT NULL,
    location            TEXT,
    job_url             TEXT,
    external_url        TEXT,
    application_type    TEXT,
    ats_platform        TEXT,
    status              TEXT DEFAULT 'pending',
    levels_verified     INTEGER DEFAULT 0,
    estimated_tc        INTEGER,
    domain_score        INTEGER,
    evidence_folder     TEXT,
    applied_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    failure_reason      TEXT,
    new_account_created INTEGER DEFAULT 0,
    notes               TEXT
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or config.DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
    logger.debug("Database initialized at %s", db_path or config.DB_PATH)


def has_applied(job_id: str, db_path: Path | None = None) -> bool:
    """Return True if this job_id is already in the DB with status=applied."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
    if row is None:
        return False
    return row["status"] == "applied"


def upsert_application(record: dict[str, Any], db_path: Path | None = None) -> None:
    """Insert or update an application record."""
    cols = [
        "job_id", "company", "job_title", "location", "job_url", "external_url",
        "application_type", "ats_platform", "status", "levels_verified",
        "estimated_tc", "domain_score", "evidence_folder", "applied_at",
        "failure_reason", "new_account_created", "notes",
    ]
    data = {k: record.get(k) for k in cols}
    placeholders = ", ".join("?" for _ in cols)
    col_names = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "job_id")

    sql = f"""
        INSERT INTO applications ({col_names}) VALUES ({placeholders})
        ON CONFLICT(job_id) DO UPDATE SET {updates}
    """
    with _connect(db_path) as conn:
        conn.execute(sql, [data[c] for c in cols])
    logger.debug("Upserted application: %s / %s", record.get("company"), record.get("job_id"))


def update_status(
    job_id: str,
    status: str,
    failure_reason: str | None = None,
    db_path: Path | None = None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE applications SET status=?, failure_reason=? WHERE job_id=?",
            (status, failure_reason, job_id),
        )


def list_applications(
    status: str | None = None,
    limit: int = 500,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM applications"
    params: list[Any] = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY applied_at DESC LIMIT ?"
    params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_application(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def stats(db_path: Path | None = None) -> dict[str, Any]:
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as n FROM applications GROUP BY status"
        ).fetchall()
        last_row = conn.execute(
            "SELECT applied_at FROM applications ORDER BY applied_at DESC LIMIT 1"
        ).fetchone()

    return {
        "total": total,
        "by_status": {r["status"]: r["n"] for r in by_status},
        "last_applied": last_row["applied_at"] if last_row else None,
    }


def export_csv(output_path: Path, db_path: Path | None = None) -> Path:
    import csv
    rows = list_applications(db_path=db_path)
    if not rows:
        output_path.write_text("No applications found.")
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Exported %d rows to %s", len(rows), output_path)
    return output_path
