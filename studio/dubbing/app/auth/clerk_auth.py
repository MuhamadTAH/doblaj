"""Clerk JWT authentication and Zero-Trust RBAC for the dubbing service."""
import asyncio
from dataclasses import dataclass
import logging
import os
import time
from typing import Any, Dict, Optional, Set

import httpx
import jwt
from fastapi import Cookie, Header, HTTPException, Request
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

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

_jwks_client = None


def get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        if not CLERK_JWKS_URL.startswith("https://") and not CLERK_JWKS_URL.startswith("http://127.0.0.1") and not CLERK_JWKS_URL.startswith("http://localhost"):
            raise ValueError(f"JWKS URL must use HTTPS scheme, got: {CLERK_JWKS_URL}")
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
    is_impersonated: bool = False
    impersonator_id: Optional[str] = None
    impersonator_email: Optional[str] = None


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

        # Check for local impersonation tokens signed with INTERNAL_API_KEY
        if unverified_payload.get("is_impersonated"):
            internal_secret = os.getenv("INTERNAL_API_KEY", "fallback-secret-key-32-chars-long")
            return jwt.decode(token, internal_secret, algorithms=["HS256"])

        try:
            signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        except Exception as jwks_err:
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
            f"Invalid token signature ({exc})",
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
    import logging
    if hasattr(authorization, "default"):
        authorization = authorization.default
    if isinstance(authorization, str) and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token and token != "null":
            return token
    raise HTTPException(
        401,
        "Authentication required",
        headers={"WWW-Authenticate": 'Bearer error="invalid_request", error_description="Missing or invalid Authorization header"'},
    )


async def _resolve_legacy_workspace_id(org_or_workspace_id: str, user_id: str) -> str:
    if not org_or_workspace_id or (not org_or_workspace_id.startswith("org_") and not org_or_workspace_id.startswith("user_")):
        return org_or_workspace_id

    try:
        import asyncio
        from convex import ConvexClient
        convex_url = os.getenv("CONVEX_URL", "https://upbeat-scorpion-447.convex.cloud")
        internal_key = os.getenv("INTERNAL_API_KEY", "")

        def _do_query():
            client = ConvexClient(convex_url)
            return client.query(
                "workspaces:findByOwnerInternal",
                {"ownerUserId": user_id, "__internalApiKey": internal_key},
            )

        result = await asyncio.to_thread(_do_query)
        if result and result.get("legacyId"):
            return result["legacyId"]
        
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
            return created["legacyId"]
    except Exception as e:
        logger.warning(f"[WORKSPACE_RESOLVE] failed: {e}")

    return org_or_workspace_id or user_id


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
    if not workspace_id:
        raise HTTPException(403, "Workspace could not be resolved. Please contact support.")

    is_impersonated = bool(claims.get("is_impersonated", False))
    impersonator_id = claims.get("impersonator_id")
    impersonator_email = claims.get("impersonator_email")

    if is_impersonated and hasattr(request, "state"):
        request.state.is_impersonated = True
        request.state.impersonator_id = impersonator_id
        request.state.impersonator_email = impersonator_email

    return AuthenticatedUser(
        user_id=user_id,
        email=claims.get("email", ""),
        workspace_id=workspace_id,
        role=claims.get("app_role", "org:member"),
        raw_claims=claims,
        access_token=token,
        is_impersonated=is_impersonated,
        impersonator_id=impersonator_id,
        impersonator_email=impersonator_email,
    )


async def require_user_or_internal(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_internal_key: Optional[str] = Header(None)
) -> AuthenticatedUser:
    import hmac
    internal_key = os.getenv("INTERNAL_API_KEY", "")
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


async def require_user_optional(
    request: Request,
    authorization: Optional[str] = Header(None)
) -> Optional[AuthenticatedUser]:
    """Optional user authentication dependency: returns AuthenticatedUser if valid token provided, else None."""
    token = _bearer_token(authorization)
    if not token:
        return None
    try:
        return await require_user(request=request, authorization=authorization)
    except Exception:
        return None


_admin_cache: Dict[str, str] = {}
_admin_cache_exp: Dict[str, float] = {}

async def is_admin_user(user: AuthenticatedUser) -> bool:
    allowed_roles = {"org:admin", "admin", "org:service", "super_admin"}
    
    # 1. Direct role property check
    if getattr(user, "role", "") in allowed_roles:
        return True

    # 2. Check token claims for role properties
    claims = getattr(user, "raw_claims", {}) or {}
    meta_role = (
        claims.get("role")
        or claims.get("app_role")
        or claims.get("org_role")
        or (claims.get("public_metadata") or {}).get("role")
        or (claims.get("metadata") or {}).get("role")
    )
    if meta_role in allowed_roles:
        user.role = meta_role
        return True

    # 3. Environment variable allowlist (ADMIN_EMAILS / ADMIN_USER_IDS)
    admin_emails = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
    admin_user_ids = {u.strip() for u in os.getenv("ADMIN_USER_IDS", "").split(",") if u.strip()}
    if user.email and user.email.lower() in admin_emails:
        user.role = "admin"
        return True
    if user.user_id in admin_user_ids:
        user.role = "admin"
        return True

    # 4. Check cache (5 min TTL)
    now = time.time()
    if user.user_id in _admin_cache and _admin_cache_exp.get(user.user_id, 0) > now:
        user.role = _admin_cache[user.user_id]
        return True

    # 5. Check Convex database for existing admin security record
    try:
        from convex import ConvexClient
        convex_url = os.getenv("CONVEX_URL", "https://upbeat-scorpion-447.convex.cloud")
        internal_key = os.getenv("INTERNAL_API_KEY", "")
        
        def _check_convex():
            client = ConvexClient(convex_url)
            pin_doc = client.query(
                "admin:getAdminPinHashInternal",
                {"userId": user.user_id, "__internalApiKey": internal_key}
            )
            return bool(pin_doc)

        is_convex_admin = await asyncio.to_thread(_check_convex)
        if is_convex_admin:
            _admin_cache[user.user_id] = "admin"
            _admin_cache_exp[user.user_id] = now + 300
            user.role = "admin"
            return True
    except Exception as e:
        logger.debug(f"[RBAC-CONVEX-CHECK] {e}")

    # 6. Check Clerk API directly via CLERK_SECRET_KEY
    clerk_secret = os.getenv("CLERK_SECRET_KEY", "")
    if clerk_secret and user.user_id:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://api.clerk.com/v1/users/{user.user_id}",
                    headers={"Authorization": f"Bearer {clerk_secret}"},
                )
                if resp.status_code == 200:
                    user_data = resp.json()
                    public_metadata = user_data.get("public_metadata", {})
                    clerk_role = public_metadata.get("role", "")
                    if clerk_role in allowed_roles:
                        _admin_cache[user.user_id] = clerk_role
                        _admin_cache_exp[user.user_id] = now + 300
                        user.role = clerk_role
                        return True
                    org_memberships = user_data.get("organization_memberships", [])
                    for mem in org_memberships:
                        if mem.get("role") in allowed_roles:
                            _admin_cache[user.user_id] = mem.get("role")
                            _admin_cache_exp[user.user_id] = now + 300
                            user.role = mem.get("role")
                            return True
        except Exception as e:
            logger.warning(f"[RBAC-CLERK-API-CHECK] Failed to verify user with Clerk API: {e}")

    return False


async def require_admin(
    request: Request,
    authorization: Optional[str] = Header(None)
) -> AuthenticatedUser:
    user = await require_user(request=request, authorization=authorization)
    if not await is_admin_user(user):
        logger.warning(
            f"[RBAC-DENIED] User {user.user_id} ({user.email}) with role '{user.role}' attempted admin endpoint"
        )
        raise HTTPException(403, "Admin privileges required")
    return user


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
    user_role = getattr(user, "role", "viewer") or "viewer"
    user_perms = ROLE_PERMISSIONS.get(user_role, set())
    return permission in user_perms or "admin:all" in user_perms


def require_permission(permission: str):
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


def revoke_all_user_sessions(user_id: str) -> bool:
    """Revoke all active Clerk sessions for user_id via Clerk REST API."""
    secret = os.getenv("CLERK_SECRET_KEY", "")
    if not secret:
        return False
    try:
        import httpx
        with httpx.Client(timeout=10.0) as c:
            r = c.post(
                f"https://api.clerk.com/v1/users/{user_id}/logout",
                headers={"Authorization": f"Bearer {secret}"},
            )
            return r.status_code < 400
    except Exception:
        return False


async def sync_clerk_user_metadata(user_id: str, role: str, permissions: list) -> bool:
    """Synchronize role and permissions to Clerk's public_metadata."""
    secret = os.getenv("CLERK_SECRET_KEY", "")
    if not secret:
        return True
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"https://api.clerk.com/v1/users/{user_id}/metadata",
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                json={
                    "public_metadata": {
                        "role": role,
                        "permissions": permissions,
                    }
                }
            )
            return resp.status_code < 400
    except Exception:
        return False


def generate_impersonation_token(target_user_id: str, target_email: str, workspace_id: str, admin_user: AuthenticatedUser) -> str:
    """Generate a scoped HS256 JWT embedding the impersonator identity for complete auditability."""
    internal_secret = os.getenv("INTERNAL_API_KEY", "fallback-secret-key-32-chars-long")
    now = int(time.time())
    payload = {
        "sub": target_user_id,
        "email": target_email,
        "workspace_id": workspace_id,
        "app_role": "member",
        "is_impersonated": True,
        "impersonator_id": admin_user.user_id,
        "impersonator_email": admin_user.email,
        "iat": now,
        "exp": now + 3600,  # 1 hour lifetime
    }
    return jwt.encode(payload, internal_secret, algorithm="HS256")
