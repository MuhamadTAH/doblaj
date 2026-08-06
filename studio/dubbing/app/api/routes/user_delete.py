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


def _delete_convex_workspace(user_id: str, workspace_id: str) -> None:
    """Cascade-delete the user's Convex rows. Best-effort: log and
    continue. The dubbing_jobs/dubbing_chunks/workspaces rows are
    removed via internal mutations.
    """
    try:
        from convex import ConvexClient

        convex_url = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
        internal_key = os.getenv("INTERNAL_API_KEY", "")
        client = ConvexClient(convex_url)
        if user_id:
            client.mutation("users:deleteByClerkIdInternal", {"clerkId": user_id, "__internalApiKey": internal_key})
        if workspace_id:
            try:
                client.mutation("users:deleteByLegacyWorkspaceIdInternal", {"workspaceId": workspace_id, "__internalApiKey": internal_key})
            except Exception as w_exc:
                logger.debug(f"[USER-DELETE] Legacy workspace cleanup: {w_exc}")
        logger.info(f"[USER-DELETE] Convex cleanup requested for user {user_id!r} (workspace {workspace_id!r})")
    except Exception as e:
        logger.warning(f"[USER-DELETE] Convex cleanup failed: {e}")


@router.post("/user/delete")
async def delete_user(
    body: DeleteUserBody,
    user: AuthenticatedUser = Depends(require_user),
):
    """Permanently delete the calling user's data."""
    logger.info(
        f"[AUDIT] User deletion requested for {user.user_id} "
        f"(workspace {user.workspace_id!r}) via Dubbing platform"
    )

    if not _check_rate_limit(user.user_id, max_attempts=5, window_sec=600):
        raise HTTPException(
            status_code=503,
            detail="Rate limit backend unavailable. Please retry shortly.",
        )

    _delete_clerk_user(user.user_id)
    _delete_convex_workspace(user.user_id, user.workspace_id)

    return {"status": "deleted", "user_id": user.user_id}
