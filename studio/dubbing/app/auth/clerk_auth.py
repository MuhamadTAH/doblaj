"""Clerk JWT authentication for the dubbing service."""
from dataclasses import dataclass
import os
from typing import Any, Dict, Optional, Set

import jwt
from fastapi import Cookie, Header, HTTPException, Request
from jwt import PyJWKClient

CLERK_FRONTEND_API = os.getenv("CLERK_FRONTEND_API")
CLERK_ISSUER_URL = (
    os.getenv("CLERK_ISSUER_URL")
    or os.getenv("CLERK_ISSUER")
    or (f"https://{CLERK_FRONTEND_API}" if CLERK_FRONTEND_API else None)
)
if not CLERK_ISSUER_URL:
    raise RuntimeError(
        "CLERK_ISSUER_URL (or CLERK_ISSUER / CLERK_FRONTEND_API) is required. "
        "Set it in the environment before starting the dubbing service."
    )
CLERK_ISSUER_URL = CLERK_ISSUER_URL.rstrip("/")
CLERK_ISSUER = CLERK_ISSUER_URL
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", f"{CLERK_ISSUER}/.well-known/jwks.json")
CLERK_AUDIENCE = os.getenv("CLERK_AUDIENCE", "dubbing-api")
CLERK_AUDIENCE_REQUIRED = os.getenv("CLERK_AUDIENCE_REQUIRED", "true").lower() == "true"
ALLOWED_AZPS = {
    "https://doblaj.com",
    "https://www.doblaj.com",
    "http://localhost:3000",
    "http://localhost:8081",
    "http://localhost:5173",
    "https://api.doblaj.com",
    "https://pird.ai",
}
if os.getenv("ALLOWED_AZPS"):
    ALLOWED_AZPS.update(x.strip() for x in os.getenv("ALLOWED_AZPS").split(",") if x.strip())

# Pird: lazy-init JWKS client.
# PyJWT 2.6+ prefetches the JWKS at construction time, which blocks startup
# indefinitely if Clerk is unreachable from this host. Build the client on
# first call inside get_jwks_client() so a Clerk outage fails auth requests,
# not the whole server boot.
_jwks_client = None


def get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        # Enforce HTTPS scheme validation to prevent local file inclusion / SSRF scheme smuggling.
        if not CLERK_JWKS_URL.startswith("https://") and not CLERK_JWKS_URL.startswith("http://127.0.0.1") and not CLERK_JWKS_URL.startswith("http://localhost"):
            raise ValueError(f"JWKS URL must use HTTPS scheme, got: {CLERK_JWKS_URL}")
        # timeout=5s so a hung JWKS fetch never stalls request handlers.
        _jwks_client = PyJWKClient(CLERK_JWKS_URL, timeout=5)
    return _jwks_client

@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str
    workspace_id: str
    role: str
    raw_claims: Dict[str, Any]
    access_token: str


def _decode_clerk_jwt(token: str) -> Dict[str, Any]:
    import logging
    logger = logging.getLogger(__name__)
    token_iss_raw = ""
    expected_issuer_raw = ""
    try:
        unverified_payload = {}
        try:
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
        except Exception:
            pass

        token_iss_raw = unverified_payload.get("iss", "")
        token_iss = token_iss_raw.rstrip("/")

        try:
            signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        except Exception as jwks_err:
            # Fallback: if token carries iss, attempt fetching JWKS directly from token's issuer
            try:
                if token_iss_raw and token_iss_raw.startswith("https://"):
                    fallback_jwks_url = f"{token_iss_raw.rstrip('/')}/.well-known/jwks.json"
                    fallback_client = PyJWKClient(fallback_jwks_url, timeout=5)
                    signing_key = fallback_client.get_signing_key_from_jwt(token)
                else:
                    raise jwks_err
            except Exception:
                raise jwks_err

        options = {"require": ["exp", "sub"]}
        if not CLERK_AUDIENCE_REQUIRED:
            options["verify_aud"] = False

        expected_issuer_raw = os.getenv("CLERK_ISSUER_URL") or os.getenv("CLERK_ISSUER") or CLERK_ISSUER or ""
        expected_issuer = expected_issuer_raw.rstrip("/")

        # Compare normalized issuer strings (ignore trailing slash / scheme differences)
        if expected_issuer and token_iss:
            norm_token_iss = token_iss.replace("https://", "").replace("http://", "")
            norm_expected_iss = expected_issuer.replace("https://", "").replace("http://", "")
            if norm_token_iss == norm_expected_iss:
                verify_issuer = token_iss_raw
            else:
                logger.error(f"[AUTH] Issuer mismatch: token has '{token_iss}', env expected '{expected_issuer}'")
                verify_issuer = expected_issuer_raw
        elif expected_issuer:
            verify_issuer = expected_issuer_raw
        else:
            options["verify_iss"] = False
            verify_issuer = None

        # Perform JWT verification with 10s clock leeway
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLERK_AUDIENCE if CLERK_AUDIENCE_REQUIRED else None,
            issuer=verify_issuer,
            options=options,
            leeway=10,
        )

        azp = claims.get("azp")
        if azp and azp not in ALLOWED_AZPS:
            logger.warning(f"[AUTH] azp '{azp}' not in ALLOWED_AZPS; allowing request")

        return claims
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            401,
            "Token expired",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token expired"'}
        ) from exc
    except jwt.PyJWTError as exc:
        logger.error(f"[AUTH] JWT validation failed: {exc} | token_iss='{token_iss_raw}', expected='{expected_issuer_raw}'")
        raise HTTPException(
            401,
            f"Invalid token signature ({exc}: token_iss='{token_iss_raw}', expected='{expected_issuer_raw}')",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[AUTH] Unexpected JWT error: {exc}")
        raise HTTPException(
            401,
            f"Authentication failed ({exc})",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
        ) from exc



def _bearer_token(authorization: Optional[str]) -> str:
    # Part05 / Layer 12: NEVER log the raw Authorization header. The
    # previous debug line emitted the full JWT at ERROR level, which
    # leaks bearer tokens to every log sink. Log only metadata — the
    # scheme, whether a token was present, and the token length.
    import logging
    if hasattr(authorization, "default"):
        authorization = authorization.default
    if isinstance(authorization, str) and authorization:
        scheme, _, token = authorization.partition(" ")

        if scheme.lower() == "bearer" and token and token != "null":
            logging.getLogger(__name__).info(
                "[AUTH] bearer token present (scheme=%s, len=%d)",
                scheme, len(token),
            )
            return token
        # Malformed header — log the scheme (not the token) and length.
        logging.getLogger(__name__).info(
            "[AUTH] malformed Authorization header (scheme=%r, len=%d)",
            scheme or None, len(authorization),
        )
    else:
        logging.getLogger(__name__).info("[AUTH] no Authorization header")

    raise HTTPException(
        401,
        "Authentication required",
        headers={"WWW-Authenticate": 'Bearer error="invalid_request", error_description="Missing or invalid Authorization header"'},
    )


async def _resolve_legacy_workspace_id(org_or_workspace_id: str, user_id: str) -> str:
    """If claim is a Clerk org_id (starts with 'org_'), resolve to the user's
    actual workspace legacyId via Convex `workspaces:findByOwnerInternal`.
    Otherwise return the value unchanged (assumed to already be a legacy UUID).
    """
    if not org_or_workspace_id or (not org_or_workspace_id.startswith("org_") and not org_or_workspace_id.startswith("user_")):
        return org_or_workspace_id

    # Use the Clerk user id directly. The Convex `workspaces` table stores
    # `ownerUserId` populated by the Clerk webhook (see convex/http.ts) and
    # `users:upsertFromClerk` — both record `clerkId` as the canonical id.
    # No hand-mapping; the legacy-Supabase UUID lookup is gone.
    try:
        import asyncio
        from convex import ConvexClient
        import os
        convex_url = os.getenv("CONVEX_URL", "http://127.0.0.1:3210")
        internal_key = os.getenv("INTERNAL_API_KEY", "")

        def _do_query():
            client = ConvexClient(convex_url)
            return client.query(
                "workspaces:findByOwnerInternal",
                {"ownerUserId": user_id, "__internalApiKey": internal_key},
            )

        result = await asyncio.to_thread(_do_query)
        if result and result.get("legacyId"):
            import logging
            logging.getLogger(__name__).info(
                f"[WORKSPACE_RESOLVE] Clerk org_id={org_or_workspace_id!r} → legacyId={result['legacyId']!r}"
            )
            return result["legacyId"]
        # No workspace found. Auto-provision one for this Clerk org so first
        # sign-in completes instead of looping. The Clerk webhook will keep
        # this record in sync on subsequent user.events.
        import logging
        def _do_create():
            client = ConvexClient(convex_url)
            return client.mutation(
                "workspaces:createForOwnerInternal",
                {
                    "ownerUserId": user_id,
                    "orgId": org_or_workspace_id,
                    "__internalApiKey": internal_key,
                },
            )
        created = await asyncio.to_thread(_do_create)
        if created and created.get("legacyId"):
            logging.getLogger(__name__).info(
                f"[WORKSPACE_PROVISION] created legacyId={created['legacyId']!r} for Clerk org_id={org_or_workspace_id!r}"
            )
            # Pull any orphan jobs (ownerUserId="" or workspaceId="") into
            # the new workspace so first sign-in shows the user's history.
            try:
                def _reassign():
                    return client.mutation(
                        "dubbingJobs:reassignOrphansToWorkspaceInternal",
                        {
                            "ownerUserId": user_id,
                            "workspaceId": created["legacyId"],
                            "__internalApiKey": internal_key,
                        },
                    )
                reassigned = await asyncio.to_thread(_reassign)
                if reassigned:
                    logging.getLogger(__name__).info(
                        f"[JOB_REASSIGN] moved {reassigned} orphan jobs into legacyId={created['legacyId']!r}"
                    )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"[JOB_REASSIGN] failed (jobs may stay invisible): {e}"
                )
            return created["legacyId"]
        logging.getLogger(__name__).warning(
            f"[WORKSPACE_RESOLVE] no workspace found for Clerk user_id={user_id!r} org_id={org_or_workspace_id!r}"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[WORKSPACE_RESOLVE] failed: {e}")

    # Fall through: caller (require_user) will surface 403 via the
    # `if not workspace_id` guard when the JWT lacks a workspace_id claim.
    # We deliberately do NOT return the org_xxx value here.
    return ""

async def require_user(
    request: Request,
    authorization: Optional[str] = Header(None)
) -> AuthenticatedUser:
    if hasattr(authorization, "default"):
        authorization = authorization.default
    auth_header = authorization or (request.headers.get("authorization") if hasattr(request, "headers") and request.headers else None)
    token = _bearer_token(auth_header)

    claims = _decode_clerk_jwt(token)
    workspace_id = claims.get("workspace_id") or claims.get("org_id") or claims.get("sub")
    if not workspace_id:
        raise HTTPException(403, "Select or create a Clerk organization before using Dubbing Studio")
    user_id = claims["sub"]
    workspace_id = await _resolve_legacy_workspace_id(workspace_id, user_id)
    # PIRD DR-001: Second guard — resolution may return "" on Convex failure
    # or when no workspace exists for the Clerk org. Without this, the user
    # authenticates with workspace_id="" and bypasses tenant isolation.
    if not workspace_id:
        raise HTTPException(403, "Workspace could not be resolved. Please contact support.")
    return AuthenticatedUser(user_id=user_id, email=claims.get("email", ""), workspace_id=workspace_id, role=claims.get("app_role", "org:member"), raw_claims=claims, access_token=token)


async def require_user_optional(
    request: Request,
    authorization: Optional[str] = Header(None)
) -> Optional[AuthenticatedUser]:
    auth_header = authorization or request.headers.get("authorization")
    if not auth_header:
        return None
    return await require_user(request=request, authorization=auth_header)


async def require_user_or_internal(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_internal_key: Optional[str] = Header(None)
) -> AuthenticatedUser:
    import os
    import hmac
    internal_key = os.getenv("INTERNAL_API_KEY", "")
    
    # Use request.headers fallback in case FastAPI Depends misses it
    actual_internal_key = x_internal_key or request.headers.get("x-internal-key")
    
    if actual_internal_key and internal_key and hmac.compare_digest(actual_internal_key, internal_key):
        bot_user_id = request.headers.get("x-user-id") or os.getenv("BOT_SERVICE_USER_ID", "telegram-bot")
        bot_workspace_id = request.headers.get("x-workspace-id") or os.getenv("BOT_SERVICE_WORKSPACE_ID", "telegram-bot-ws")
        return AuthenticatedUser(
            user_id=bot_user_id,
            email="bot@internal.doblaj.com",
            workspace_id=bot_workspace_id,
            role="org:service",
            raw_claims={"sub": bot_user_id, "workspace_id": bot_workspace_id, "azp": "https://api.doblaj.com"},
            access_token="internal-bot-token"
        )
        
    return await require_user(request=request, authorization=authorization)


async def require_admin(
    request: Request,
    authorization: Optional[str] = Header(None)
) -> AuthenticatedUser:
    """Part 07 / Video 39: Enforce Role-Based Access Control (RBAC) at the API layer."""
    user = await require_user(request=request, authorization=authorization)
    allowed_roles = {"org:admin", "admin", "org:service"}
    if getattr(user, "role", "") not in allowed_roles:
        import logging
        logging.getLogger(__name__).warning(
            f"[RBAC-DENIED] User {user.user_id} with role '{user.role}' attempted admin endpoint"
        )
        raise HTTPException(403, "Admin privileges required")
    return user


# Part 08 / Video 45: Granular Permissions RBAC Matrix
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "org:admin": {"dubbing:read", "dubbing:write", "dubbing:delete", "billing:manage", "admin:all"},
    "admin": {"dubbing:read", "dubbing:write", "dubbing:delete", "billing:manage", "admin:all"},
    "org:service": {"dubbing:read", "dubbing:write", "dubbing:delete", "billing:manage", "admin:all"},
    "org:member": {"dubbing:read", "dubbing:write"},
    "member": {"dubbing:read", "dubbing:write"},
    "org:viewer": {"dubbing:read"},
    "viewer": {"dubbing:read"},
}


def has_permission(user: AuthenticatedUser, permission: str) -> bool:
    """Check if the user's role grants a specific permission action."""
    user_role = getattr(user, "role", "viewer") or "viewer"
    user_perms = ROLE_PERMISSIONS.get(user_role, set())
    return permission in user_perms or "admin:all" in user_perms


def require_permission(permission: str):
    """Dependency builder enforcing a granular permission action on API routes."""
    async def _permission_dependency(
        request: Request,
        authorization: Optional[str] = Header(None)
    ) -> AuthenticatedUser:
        user = await require_user(request=request, authorization=authorization)
        if not has_permission(user, permission):
            import logging
            logging.getLogger(__name__).warning(
                f"[PERM-DENIED] User {user.user_id} ({user.role}) missing permission '{permission}'"
            )
            raise HTTPException(403, f"Permission '{permission}' required")
        return user
    return _permission_dependency


# Part 10 / Video 60: Instant Session Revocation Helper
def revoke_all_user_sessions(user_id: str) -> bool:
    """Revoke all active Clerk sessions for user_id upon security events.
    
    Calls Clerk's REST API endpoint /v1/users/{user_id}/logout.
    """
    secret = os.getenv("CLERK_SECRET_KEY", "")
    if not secret:
        import logging
        logging.getLogger(__name__).warning("[SESSION-REVOKE] CLERK_SECRET_KEY unset — session revocation skipped")
        return False
    try:
        import httpx
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                f"https://api.clerk.com/v1/users/{user_id}/logout",
                headers={"Authorization": f"Bearer {secret}"},
            )
            if r.status_code < 400:
                import logging
                logging.getLogger(__name__).info(f"[SESSION-REVOKE] Revoked active sessions for user {user_id}")
                return True
            import logging
            logging.getLogger(__name__).warning(
                f"[SESSION-REVOKE] Clerk logout returned status {r.status_code} for user {user_id}"
            )
            return False
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[SESSION-REVOKE] Session revocation failed for {user_id}: {e}")
        return False



