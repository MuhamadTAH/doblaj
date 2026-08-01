"""Backfill historical jobs from SQLite (data/dubbing.db) into Convex.

Reads non-chunk rows from the legacy SQLite jobs table, skips ones already
present in Convex (by legacyId), and inserts the rest as owned by the
current Clerk user.

Run once after the workspace reprovision. Idempotent.

Usage:
    cd D:\\Pird\\studio\\dubbing
    python scripts/backfill_sqlite_to_convex.py --clerk-user user_3Gqh0sVtFqypoOoT3L5TntH3AO9
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "data" / "dubbing.db"
CONVEX_URL = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")

# Job status mapping from SQLite -> Convex schema
STATUS_MAP = {
    "pending": "pending",
    "processing": "processing",
    "completed": "done",
    "done": "done",
    "failed": "failed",
}


def fetch_existing_legacy_ids(client: httpx.Client) -> set[str]:
    r = client.post(
        f"{CONVEX_URL}/api/query",
        json={
            "path": "dubbingJobs:listAllLegacyIdsInternal",
            "args": {"__internalApiKey": INTERNAL_KEY},
            "format": "json",
        },
        timeout=10.0,
    )
    if r.status_code != 200 or r.json().get("status") != "success":
        print("  listAllLegacyIdsInternal missing, falling back to skip-duplicate check", file=sys.stderr)
        return set()
    return set(r.json().get("value", []))


def insert_job(client: httpx.Client, **kwargs) -> str:
    r = client.post(
        f"{CONVEX_URL}/api/mutation",
        json={
            "path": "dubbingJobs:backfillInsertInternal",
            "args": {**kwargs, "__internalApiKey": INTERNAL_KEY},
            "format": "json",
        },
        timeout=10.0,
    )
    body = r.json()
    if r.status_code != 200 or body.get("status") != "success":
        raise RuntimeError(f"insert failed: {body}")
    return body["value"]


def main(clerk_user: str, workspace: str) -> int:
    if not INTERNAL_KEY:
        print("INTERNAL_API_KEY not set in .env", file=sys.stderr)
        return 1

    print(f"[BACKFILL] Clerk user: {clerk_user}")
    print(f"[BACKFILL] Workspace: {workspace}")
    print(f"[BACKFILL] Convex: {CONVEX_URL}")

    with httpx.Client() as client:
        existing = fetch_existing_legacy_ids(client)
        print(f"[BACKFILL] Convex already has {len(existing)} jobs")

        if not DB_PATH.is_file():
            print(f"[BACKFILL] No SQLite db at {DB_PATH}", file=sys.stderr)
            return 1
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, status, progress, output_path, error, created_at, updated_at "
            "FROM jobs WHERE id NOT LIKE 'chunk_%' AND id NOT LIKE 'test_%' "
            "ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
        conn.close()

        succeeded = 0
        skipped = 0
        failed = 0
        for r in rows:
            legacy_id = r["id"]
            if legacy_id in existing:
                skipped += 1
                continue
            try:
                insert_job(
                    client,
                    legacyId=legacy_id,
                    workspaceId=workspace,
                    ownerUserId=clerk_user,
                    status=STATUS_MAP.get(r["status"], r["status"]),
                    progress=r["progress"] or 0,
                    resultVideoR2Key=r["output_path"] or "",
                    error=r["error"] or "",
                    createdAt=r["created_at"],
                    updatedAt=r["updated_at"],
                )
                succeeded += 1
                print(f"  [{succeeded}] {legacy_id[:12]} {r['status']} -> {r['output_path'] or '(no output)'}")
            except Exception as e:
                failed += 1
                print(f"  [FAIL] {legacy_id[:12]} {e}", file=sys.stderr)

        print(f"\n[BACKFILL] Done: {succeeded} inserted, {skipped} skipped, {failed} failed.")
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--clerk-user", required=True)
    p.add_argument("--workspace", default="org_3Gqh0tJsDrEn6YFh95nhqR78AKE")
    args = p.parse_args()
    sys.exit(main(args.clerk_user, args.workspace))