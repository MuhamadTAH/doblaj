"""
database.py — SQLite-based local persistence layer for dubbing jobs.
Uses aiosqlite for async access. Same high-level function signatures
so the rest of the codebase does not need to change.
"""
import os
import json
import logging
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = Path("data/dubbing.db")


async def init_db():
    """Initialize the SQLite database and create tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                store_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER NOT NULL DEFAULT 0,
                input_path TEXT,
                output_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()
    logger.info("[DATABASE] SQLite database initialized at %s", DB_PATH)


async def create_job(job_id: str, store_id: str = "", input_path: str = "") -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "INSERT INTO jobs (id, store_id, status, progress, input_path, output_path, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, store_id, "pending", 0, input_path, "", "", now, now)
        )
        await db.commit()
    return {
        "id": job_id,
        "store_id": store_id,
        "status": "pending",
        "progress": 0,
        "input_path": input_path,
        "output_path": "",
        "error": "",
        "created_at": now,
        "updated_at": now,
    }


async def get_job(job_id: str, workspace_id: str = "") -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
    return None


async def list_jobs(workspace_id: str = "", store_id: str = "") -> List[Dict[str, Any]]:
    # Pird: refuse un-scoped reads. Returning all jobs when no filter is
    # supplied was a workspace-isolation bypass waiting to happen. See
    # handoffs/dubbing-audit-fixes-2026-07-15.md Fix 5.
    filter_id = workspace_id or store_id
    if not filter_id:
        raise ValueError("list_jobs requires workspace_id or store_id")
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM jobs WHERE store_id = ? ORDER BY created_at DESC", (filter_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_job_status(
    job_id: str,
    status: str,
    workspace_id: str = "",
    progress: int = -1,
    output_path: str = "",
    error: str = "",
    **kwargs,  # absorb any extra keyword args from old call sites
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        if progress >= 0:
            await db.execute(
                "UPDATE jobs SET status = ?, progress = ?, output_path = CASE WHEN ? = '' THEN output_path ELSE ? END, error = ?, updated_at = ? WHERE id = ?",
                (status, progress, output_path, output_path, error, now, job_id)
            )
        else:
            await db.execute(
                "UPDATE jobs SET status = ?, output_path = CASE WHEN ? = '' THEN output_path ELSE ? END, error = ?, updated_at = ? WHERE id = ?",
                (status, output_path, output_path, error, now, job_id)
            )
        await db.commit()
    return True
