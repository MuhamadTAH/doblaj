"""
Backfill Clerk users into Convex `users` table (PROD).

Idempotent — safe to re-run. Re-runs just refresh email/name/image
for existing rows, never duplicate (the Convex mutation upserts by
clerkId).

Uses the public Convex HTTP API directly (POST /api/mutation). No
deploy key required because `users:upsertFromClerk` is a public
mutation that just mirrors what Clerk already knows.

Usage:
    cd D:\\Pird\\studio\\dubbing
    python scripts/backfill_clerk_to_convex.py

Reads:
    .env  ->  CLERK_SECRET_KEY, CONVEX_PROD_URL

Writes:
    Convex (prod)  ->  users table (upsert)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
CONVEX_PROD_URL = os.getenv(
    "CONVEX_PROD_URL",
    "https://upbeat-scorpion-447.convex.cloud",
)
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

if not CLERK_SECRET_KEY:
    sys.exit("CLERK_SECRET_KEY missing from .env")
if not INTERNAL_API_KEY:
    sys.exit("INTERNAL_API_KEY missing from .env")


def list_clerk_users() -> list[dict]:
    """Walk the full Clerk user list with limit/offset paging."""
    users: list[dict] = []
    offset = 0
    page_size = 100
    while True:
        r = httpx.get(
            "https://api.clerk.com/v1/users",
            params={"limit": page_size, "offset": offset, "order_by": "-created_at"},
            headers={
                "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        users.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return users


def primary_email(user: dict) -> str | None:
    pid = user.get("primary_email_address_id")
    addrs = user.get("email_addresses") or []
    for a in addrs:
        if a.get("id") == pid:
            return a.get("email_address")
    return addrs[0].get("email_address") if addrs else None


def upsert_one(client: httpx.Client, clerk_id: str, email, first, last, image):
    res = client.post(
        "/api/mutation",
        json={
            "path": "users:upsertFromClerkInternal",
            "args": {
                "clerkId": clerk_id,
                "email": email,
                "firstName": first,
                "lastName": last,
                "imageUrl": image,
                "__internalApiKey": INTERNAL_API_KEY,
            },
        },
        timeout=15,
    )
    res.raise_for_status()
    body = res.json()
    if body.get("status") != "success":
        raise RuntimeError(body)


def main() -> int:
    print(f"[backfill] Convex (prod): {CONVEX_PROD_URL}")
    print("[backfill] fetching Clerk users...")
    users = list_clerk_users()
    print(f"[backfill] got {len(users)} user(s)")

    ok = 0
    fail = 0
    with httpx.Client(base_url=CONVEX_PROD_URL) as client:
        for u in users:
            clerk_id = u["id"]
            email = primary_email(u)
            try:
                upsert_one(
                    client,
                    clerk_id,
                    email,
                    u.get("first_name") or None,
                    u.get("last_name") or None,
                    u.get("image_url") or None,
                )
                ok += 1
                print(f"  [OK] {clerk_id}  {email}")
            except Exception as e:
                fail += 1
                print(f"  [FAIL] {clerk_id}  {email}  -> {e}")
            time.sleep(0.05)

    print(f"[backfill] done. ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())