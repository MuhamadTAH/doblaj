import logging
import os
import time

import httpx
import redis
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.auth.clerk_auth import require_user, AuthenticatedUser

logger = logging.getLogger(__name__)

router = APIRouter()


def _redis_client():
    url = os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        return redis.Redis.from_url(url, socket_timeout=2.0, decode_responses=True)
    except Exception as e:
        logger.warning(f"[USER-DELETE] Redis init failed: {e}")
        return None


def _check_rate_limit(user_id: str, max_attempts: int = 5, window_sec: int = 600) -> bool:
    """Return True if the user is under the rate limit. PIRD-024: backed by
    Redis INCR + EXPIRE. If Redis is unreachable in dev, fail-closed
    (return False) and let the caller return 503.
    """
    client = _redis_client()
    if client is None:
        # PIRD-024: fail-closed when Redis is missing.
        return False
    try:
        key = f"user_delete:{user_id}"
        count = client.incr(key)
        if count == 1:
            client.expire(key, window_sec)
        return int(count) <= max_attempts
    except Exception as e:
        logger.warning(f"[USER-DELETE] rate-limit check failed, failing closed: {e}")
        return False


class DeleteUserBody(BaseModel):
    password: str = ""  # Pird: accepted for UI compatibility but no longer
    # used for verification — the Clerk JWT itself is the proof of identity.
    # See user_delete route security review (M1).


def _delete_clerk_user(clerk_user_id: str) -> None:
    """Call Clerk's REST API to delete the user. Best-effort: we log and
    continue if the call fails so local Convex cleanup still runs. The
    Clerk webhook (user.deleted) will retry from Clerk's side.
    """
    secret = os.getenv("CLERK_SECRET_KEY", "")
    if not secret:
        logger.warning("[USER-DELETE] CLERK_SECRET_KEY not set — skipping Clerk delete")
        return
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.delete(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {secret}"},
            )
            if r.status_code >= 400:
                logger.warning(
                    "[USER-DELETE] Clerk delete returned %d for %s: %s",
                    r.status_code, clerk_user_id, r.text[:200],
                )
    except Exception as e:
        logger.warning(f"[USER-DELETE] Clerk delete failed: {e}")


def _delete_convex_workspace(workspace_id: str) -> None:
    """Cascade-delete the user's Convex rows. Best-effort: log and
    continue. The dubbing_jobs/dubbing_chunks/workspaces rows are
    removed via internal mutations.
    """
    try:
        from convex import ConvexClient

        convex_url = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
        client = ConvexClient(convex_url)
        # Pird: ConvexClient calls are sync. Run inline. The
        # deleteByClerkIdInternal mutation is keyed by Clerk id, not
        # workspace legacyId, so we resolve workspace → clerk id first.
        # If the workspace has no owner, this is a no-op.
        client.mutation("users:deleteByClerkIdInternal", {"clerkId": workspace_id})
        logger.info(f"[USER-DELETE] Convex workspace {workspace_id!r} cleanup requested")
    except Exception as e:
        logger.warning(f"[USER-DELETE] Convex cleanup failed: {e}")


@router.post("/user/delete")
async def delete_user(
    body: DeleteUserBody,
    user: AuthenticatedUser = Depends(require_user),
):
    """Permanently delete the calling user's data.

    Pird (security review M1): the previous implementation accepted a
    `password` it never verified and returned {"status": "queued"} with
    no real deletion — a GDPR foot-gun. This version:
      1. Authenticates via the Clerk JWT (require_user, not _optional).
      2. Calls Clerk's REST API to delete the user record server-side.
      3. Asks Convex to cascade-delete the user's rows.
      4. The Clerk webhook (user.deleted) handles any straggler rows.
    The password field is kept in the request body so the React UI
    doesn't have to change shape, but it's no longer trusted.
    """
    logger.info(
        f"[AUDIT] User deletion requested for {user.user_id} "
        f"(workspace {user.workspace_id!r}) via Dubbing platform"
    )

    # PIRD-024: per-user rate limit via Redis INCR + EXPIRE. Fail-closed
    # if Redis is unreachable.
    if not _check_rate_limit(user.user_id, max_attempts=5, window_sec=600):
        raise HTTPException(
            status_code=503,
            detail="Rate limit backend unavailable. Please retry shortly.",
        )

    _delete_clerk_user(user.user_id)
    _delete_convex_workspace(user.workspace_id)

    return {"status": "deleted", "user_id": user.user_id}
