"""
database.py — SQLite-based local persistence layer for dubbing jobs.
Uses aiosqlite for async access. Same high-level function signatures
so the rest of the codebase does not need to change.
"""
import os
import json
import logging
import secrets
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS telegram_nonces (
                nonce TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS telegram_accounts (
                telegram_chat_id TEXT PRIMARY KEY,
                workspace_id TEXT UNIQUE NOT NULL
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


async def create_telegram_nonce(workspace_id: str, expires_in_minutes: int = 10) -> str:
    """Create a short-lived nonce for Telegram account linking."""
    nonce = secrets.token_urlsafe(16)
    expires_at = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + (expires_in_minutes * 60), 
        timezone.utc
    ).isoformat()
    
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute(
            "INSERT INTO telegram_nonces (nonce, workspace_id, expires_at) VALUES (?, ?, ?)",
            (nonce, workspace_id, expires_at)
        )
        await db.commit()
    return nonce


async def consume_telegram_nonce(nonce: str) -> Optional[str]:
    """Consume a nonce and return the workspace_id if valid."""
    now = datetime.now(timezone.utc).isoformat()
    workspace_id = None
    
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        # Get the nonce if it hasn't expired
        cursor = await db.execute(
            "SELECT workspace_id FROM telegram_nonces WHERE nonce = ? AND expires_at > ?", 
            (nonce, now)
        )
        row = await cursor.fetchone()
        if row:
            workspace_id = row["workspace_id"]
            
            # Immediately invalidate the nonce by deleting it
            await db.execute("DELETE FROM telegram_nonces WHERE nonce = ?", (nonce,))
            await db.commit()
            
    return workspace_id


async def link_telegram_account(telegram_chat_id: str, workspace_id: str) -> bool:
    """
    Link a Telegram chat ID to a workspace.
    Enforces a strict 1:1 unique mapping.
    """
    async with aiosqlite.connect(str(DB_PATH)) as db:
        try:
            # UPSERT: If telegram_chat_id exists, we update the workspace_id.
            # The UNIQUE constraint on workspace_id prevents a workspace from linking multiple telegram_chat_ids.
            await db.execute("""
                INSERT INTO telegram_accounts (telegram_chat_id, workspace_id)
                VALUES (?, ?)
                ON CONFLICT(telegram_chat_id) DO UPDATE SET workspace_id=excluded.workspace_id
            """, (telegram_chat_id, workspace_id))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            # This happens if the workspace_id is already linked to a different telegram_chat_id
            logger.error(f"[DATABASE] Integrity error: Workspace {workspace_id} is already linked to another Telegram account.")
            return False


async def get_workspace_by_telegram_id(telegram_chat_id: str) -> Optional[str]:
    """Retrieve the linked workspace ID for a given Telegram chat ID."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT workspace_id FROM telegram_accounts WHERE telegram_chat_id = ?", 
            (telegram_chat_id,)
        )
        row = await cursor.fetchone()
        if row:
            return row["workspace_id"]
    return None
