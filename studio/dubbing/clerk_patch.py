"""Surgical fix: lazy-init PyJWKClient + try/except router imports.

Root cause: app/auth/clerk_auth.py:14 constructs PyJWKClient(URL) at import
time. PyJWT 2.6+ prefetches JWKS during __init__, blocking on Clerk reachability.
On the prod VM, Clerk is unreachable (dev instance in prod env, NSG blocks, etc),
so the import hangs -> app.include_router never returns -> Uvicorn never
finishes binding -> /healthz fails.

Fix:
1. Lazy-init the JWKS client behind get_jwks_client() with a 5s timeout.
2. Update _decode_clerk_jwt to call get_jwks_client().
3. Wrap the tts_dashboard router include in main.py with try/except so a
   failing Clerk import logs a WARNING and the rest of the API still comes up.
"""
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/app/studio/dubbing")

# --- Patch 1: clerk_auth.py ---
p = ROOT / "app/auth/clerk_auth.py"
src = p.read_text()

old_module_level = "_jwks_client = PyJWKClient(CLERK_JWKS_URL)"
new_module_level = (
    "# Pird: lazy-init JWKS client.\n"
    "# PyJWT 2.6+ prefetches the JWKS at construction time, which blocks startup\n"
    "# indefinitely if Clerk is unreachable from this host. Build the client on\n"
    "# first call inside get_jwks_client() so a Clerk outage fails auth requests,\n"
    "# not the whole server boot.\n"
    "_jwks_client = None\n\n\n"
    "def get_jwks_client():\n"
    "    global _jwks_client\n"
    "    if _jwks_client is None:\n"
    "        # timeout=5s so a hung JWKS fetch never stalls request handlers.\n"
    "        _jwks_client = PyJWKClient(CLERK_JWKS_URL, timeout=5)\n"
    "    return _jwks_client"
)

if old_module_level in src:
    src = src.replace(old_module_level, new_module_level)
    print("[1/2] clerk_auth.py: _jwks_client made lazy")
else:
    print("[1/2] clerk_auth.py: original line not found, skipping")

old_decode = "signing_key = _jwks_client.get_signing_key_from_jwt(token)"
new_decode = "signing_key = get_jwks_client().get_signing_key_from_jwt(token)"
if old_decode in src:
    src = src.replace(old_decode, new_decode)
    print("[1/2] clerk_auth.py: _decode_clerk_jwt updated to lazy accessor")
else:
    print("[1/2] clerk_auth.py: _decode line not found, skipping")

p.write_text(src)

# --- Patch 2: main.py: wrap tts_dashboard include in try/except ---
p2 = ROOT / "main.py"
src2 = p2.read_text()

# Find the tts_dashboard import + include block. Pattern: lines that import
# tts_dashboard from app.api.routes and include its router at /api/tts-dashboard.
# Be conservative: only patch if we can match both lines exactly.
old_block = (
    "    from app.api.routes import tts_dashboard\n"
    "    app.include_router(tts_dashboard.router, prefix=\"/api/tts-dashboard\")"
)
new_block = (
    "    try:\n"
    "        from app.api.routes import tts_dashboard\n"
    "        app.include_router(tts_dashboard.router, prefix=\"/api/tts-dashboard\")\n"
    "    except Exception as exc:\n"
    "        # Pird: a Clerk or auth-import failure must NOT take down the whole API.\n"
    "        # The dashboard route is non-critical for the dubbing pipeline; log and\n"
    "        # continue so /api/jobs, the RunPod trigger, and the CPU worker still work.\n"
    "        logger.exception(\"[STARTUP] Failed to mount /api/tts-dashboard router: %s\", exc)"
)

if old_block in src2:
    src2 = src2.replace(old_block, new_block)
    print("[2/2] main.py: tts_dashboard router include wrapped in try/except")
else:
    print("[2/2] main.py: tts_dashboard block not matched (skipping). Manual fix needed.")

p2.write_text(src2)
print("Done.")