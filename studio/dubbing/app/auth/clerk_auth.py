"""Clerk JWT authentication for the dubbing service."""
from dataclasses import dataclass
import os
from typing import Any, Dict, Optional

import jwt
from fastapi import Cookie, Header, HTTPException
from jwt import PyJWKClient

CLERK_FRONTEND_API = os.getenv("CLERK_FRONTEND_API", "deciding-quagga-70.clerk.accounts.dev")
CLERK_ISSUER = os.getenv("CLERK_ISSUER", f"https://{CLERK_FRONTEND_API}").rstrip("/")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", f"{CLERK_ISSUER}/.well-known/jwks.json")
CLERK_AUDIENCE = os.getenv("CLERK_AUDIENCE", "pird-dubbing")
CLERK_AUDIENCE_REQUIRED = os.getenv("CLERK_AUDIENCE_REQUIRED", "true").lower() == "true"
_jwks_client = PyJWKClient(CLERK_JWKS_URL)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str
    workspace_id: str
    role: str
    raw_claims: Dict[str, Any]
    access_token: str


def _decode_clerk_jwt(token: str) -> Dict[str, Any]:
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        options = {"require": ["exp", "sub"]}
        if not CLERK_AUDIENCE_REQUIRED:
            options["verify_aud"] = False
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=CLERK_AUDIENCE,
            issuer=CLERK_ISSUER,
            options=options,
            leeway=5,
        )
        
        # PIRD: azp validation to prevent token leakage
        azp = claims.get("azp")
        if azp not in ["https://doblaj.com", "http://localhost:3000", "http://localhost:8081", "https://api.doblaj.com"]:
            raise HTTPException(
                401, 
                "Invalid azp claim", 
                headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid azp claim"'}
            )
            
        return claims
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            401, 
            "Token expired", 
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token expired"'}
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            401, 
            "Invalid token", 
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid token signature"'}
        ) from exc


def _bearer_token(authorization: Optional[str]) -> str:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token
    raise HTTPException(
        401, 
        "Authentication required", 
        headers={"WWW-Authenticate": 'Bearer error="invalid_request", error_description="Missing or invalid Authorization header"'}
    )


async def _resolve_legacy_workspace_id(org_or_workspace_id: str, user_id: str) -> str:
    """If claim is a Clerk org_id (starts with 'org_'), resolve to the user's
    actual workspace legacyId via Convex `workspaces:findByOwnerInternal`.
    Otherwise return the value unchanged (assumed to already be a legacy UUID).
    """
    if not org_or_workspace_id or not org_or_workspace_id.startswith("org_"):
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
    authorization: Optional[str] = Header(None)
) -> AuthenticatedUser:
    token = _bearer_token(authorization)
    claims = _decode_clerk_jwt(token)
    workspace_id = claims.get("workspace_id")
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
    authorization: Optional[str] = Header(None)
) -> Optional[AuthenticatedUser]:
    if not authorization:
        return None
    return await require_user(authorization)
