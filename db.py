import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from config import DB_PATH


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applied_jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                match_score REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                applied_at TIMESTAMP NOT NULL
            )
            """
        )
        conn.commit()


def is_job_applied(job_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT 1 FROM applied_jobs WHERE id = ?", (job_id,))
        return cursor.fetchone() is not None


def log_job_application(job_data: dict) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO applied_jobs
            (id, title, company, platform, url, match_score, status, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_data["id"],
                job_data["title"],
                job_data["company"],
                job_data["platform"],
                job_data["url"],
                job_data["match_score"],
                job_data.get("status", "pending"),
                job_data.get("applied_at", datetime.now().isoformat()),
            ),
        )
        conn.commit()


def get_applied_jobs_count(date: Optional[str] = None) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        if date:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM applied_jobs WHERE DATE(applied_at) = ?", (date,)
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) FROM applied_jobs")
        return cursor.fetchone()[0]


def close_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


__all__ = [
    "init_db",
    "is_job_applied",
    "log_job_application",
    "get_applied_jobs_count",
    "close_db",
]
