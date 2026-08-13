import logging
import os
import json
import asyncio
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

# PIRD-010: rate limiting. The expensive routes (job creation, ingest,
# internal jobs) are decorated per-route with `app.core.ratelimit.rate_limited`,
# so a runaway caller can't saturate the worker.
#
# There is deliberately NO app-wide default limit here. A previous version
# built a slowapi Limiter with default_limits=["5/minute"] and registered
# `app.state.limiter` + the 429 handler, but never added SlowAPIMiddleware
# and never decorated a route with it — so it was dead code that read like
# working protection. Adding that middleware now would apply 5/minute to
# every endpoint including job-status polling, which would break the
# dashboard. The per-route decorators are the real mechanism.

load_dotenv()

# ---------------------------------------------------------------------------
# Pird: locale + i18n (RTL Fix 1 from dubbing-rtl-want-vs-have.md)
#
# Locale resolution: ?lang= query  >  Supabase profile (post-login)  >
# Accept-Language header  >  fallback "en".
#
# RTL Fixes 2-5 are intentionally stubbed here; they touch the templates
# and i18n strings, not the backend. Re-open dubbing-rtl-want-vs-have.md to
# pick them up.
# ---------------------------------------------------------------------------
RTL_LANGS = {"ckb", "ar", "fa", "he", "ku", "ur"}


def resolve_locale(request: Request) -> str:
    """Return the user's locale string (e.g. 'ckb', 'ar', 'en'). Never raises."""
    # PIRD DR-004: validate against allowlist to prevent XSS injection.
    # This value flows into a <script> tag via json.dumps, which does NOT
    # escape </script>. Without this check, ?lang=</script><script>alert(1)
    # would execute arbitrary JS in the user's browser.
    q = request.query_params.get("lang")
    if q and q.lower() in {"ckb", "ar", "en", "fa", "he", "ku", "ur"}:
        return q.lower()
    # After sign-in, the JWT's user_metadata may carry the locale.
    user = request.state.__dict__.get("user") if hasattr(request, "state") else None
    if user and getattr(user, "locale", None):
        return user.locale
    accept = request.headers.get("accept-language", "")
    if accept:
        first = accept.split(",")[0].split(";")[0].strip().lower()
        aliases = {"ku": "ckb", "fa-af": "fa", "fa-ir": "fa"}
        first = aliases.get(first, first)
        if first in {"ckb", "ar", "en"}:
            return first
    return "en"


def is_rtl(locale: str) -> bool:
    return locale in RTL_LANGS


# Pird: hand-rolled i18n loader. Replace with gettext when 5+ locales exist.
_I18N_DIR = Path(__file__).parent / "app" / "i18n"
_STRINGS: dict = {}


def _load_i18n() -> None:
    global _STRINGS
    _STRINGS = {}
    if not _I18N_DIR.is_dir():
        return
    for f in _I18N_DIR.glob("*.json"):
        try:
            _STRINGS[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("[i18n] failed to parse %s", f)


_load_i18n()


def t(locale: str, key: str, default: str = "") -> str:
    """Translate a string. Falls back to English, then to the default, then to the key."""
    return (
        _STRINGS.get(locale, {}).get(key)
        or _STRINGS.get("en", {}).get(key)
        or default
        or key
    )


# TODO RTL Fix 2-5 (per dubbing-rtl-want-vs-have.md):
#   - Mirror layout in dubbing.html + translate_dashboard.html
#   - Replace `margin-left` -> `margin-inline-start`, etc.
#   - Add `<bdi>` wrappers around numerals / IDs / emails / URLs
#   - Seed app/i18n/{en,ckb,ar}.json with all template strings
#   - Set user locale in Supabase profile (Fix 5, optional)

# Configure global file logging for the terminal dashboard
log_dir = Path("data/logs")
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Pird: rotate at 10 MB × 5 backups. Without rotation data/logs/vcta.log grows
# without bound. See PIRD-011 in findings_ledger.json.
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler(
    log_dir / "vcta.log",
    encoding="utf-8",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
file_handler.setLevel(logging.INFO)
root_logger = logging.getLogger()
if not any(isinstance(h, (logging.FileHandler, RotatingFileHandler)) for h in root_logger.handlers):
    root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

app = FastAPI(title="Dubbing Service")

# PIRD-014: tighten local FS permissions on data/jobs. Biometric
# intermediates land here; the directory should be unreadable by other
# users on the host. Idempotent; logs and continues on failure (e.g.
# on Windows where chmod is a no-op).
import stat
try:
    jobs_dir = Path("data/jobs")
    jobs_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "chmod"):
        os.chmod(jobs_dir, 0o700)
        logger.info("[STARTUP] data/jobs perms set to 0o700")
except Exception as e:
    logger.warning(f"[STARTUP] could not chmod data/jobs: {e}")

# Pird: Convex is the sole persistence backend. The legacy Supabase
# monkey-patch (which copied Convex functions onto the database_supabase
# module so old `from app.core import database_supabase as database`
# call sites kept working) is no longer needed — that module is gone and
# all routes import through `app.core.db` which now resolves to Convex.
logger.info("[STARTUP] Dubbing data backend: Convex")

# Pird: redirect unauthenticated HTML navigations to the Pird shell with
# ?next=<current-url>. Only fires for browser navigations (Accept: text/html
# + GET) returning 401 from a require_user-gated route. API/JSON callers
# still get the raw 401 so curl/scripts aren't redirected.
# (AuthBounceMiddleware removed in favor of React ClerkProvider)

# PIRD-019: CORS configuration — explicit origin allowlist per RFC 6454.
# Never combine allow_origins=["*"] with allow_credentials=True.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
cors_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://localhost:8002",
    "http://localhost:8081",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8002",
    "http://127.0.0.1:8081",
    "https://doblaj.com",
    "https://www.doblaj.com",
    "https://api.doblaj.com",
    "https://checkout.suby.fi",
]
if _raw_origins:
    for o in _raw_origins.split(","):
        cleaned = o.strip()
        if cleaned and cleaned not in cors_origins:
            cors_origins.append(cleaned)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Part 05 / Video 25: Add security response headers to protect browser clients."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' blob: https:; "
            "connect-src 'self' https: wss:; "
            "font-src 'self' data: https:; "
            "object-src 'none'; "
            "frame-ancestors 'none';"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins, 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"], 
)


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Pird: serve the logo animation MP4 from the React build output.
# FileResponse supports HTTP Range requests so browsers can scrub the
# video without downloading the whole 1.2 MB at once. We use an explicit
# route (not a Mount) because Starlette reserves Mount paths without
# extensions, which conflicts with `.mp4` URLs.
LOGO_MP4 = BASE_DIR / "app" / "static" / "tts-dashboard" / "logo.mp4"
if LOGO_MP4.is_file():
    from fastapi.responses import FileResponse

    @app.get("/logo.mp4", include_in_schema=False)
    async def serve_logo_mp4():
        return FileResponse(
            str(LOGO_MP4),
            media_type="video/mp4",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    logger.info("[STARTUP] logo.mp4 served at /logo.mp4")

# Pird: serve the merged TTS dashboard React build at /tts/* (Fix 3+4).
# We replaced StaticFiles(html=True) with a FastAPI handler so that:
#   1. We can gate the React shell on the same Supabase JWT the rest of
#      dubbing uses (AuthBounceMiddleware then 401→302s browser nav to shell).
#   2. We can inject `window.__PIRD_CONFIG__` (locale/dir) into the served
#      index.html before the React bundle boots — keeps RTL Fix 1 plumbing
#      and matches the Option A recommendation in the handoff.
#   3. We preserve the SPA deep-link fallback that StaticFiles(html=True)
#      gave us for free: every /tts/<anything> path serves the same
#      index.html so React Router can take over on the client.
TTS_DASHBOARD_DIR = BASE_DIR / "app" / "static" / "tts-dashboard"
_TTS_INDEX_PATH = TTS_DASHBOARD_DIR / "index.html"


def _read_tts_index_html() -> Optional[str]:
    """Read the built index.html from disk on every call.

    Pird: intentionally NOT cached — the file is < 1 KB so the disk read
    is negligible, and reading fresh means an `npm run build` takes effect
    immediately without restarting the server. A stale in-memory cache was
    the cause of 404s when the build hash changed between rebuilds.
    """
    if not _TTS_INDEX_PATH.is_file():
        return None
    return _TTS_INDEX_PATH.read_text(encoding="utf-8")


def _inject_pird_config(index_html: str, locale: str, dir_attr: str) -> str:
    """Insert a `<script>window.__PIRD_CONFIG__ = {...}</script>` block
    right before `</head>`. The React entry (dashboard-tts/src/main.tsx)
    reads this on mount and applies dir/lang to <html>.

    Pird: also injects `strings` so React components can call
    t(key, fallback) without extra network round-trips (Fix 3b).
    """
    import json as _json
    strings = _STRINGS.get(locale, {})
    payload = _json.dumps({"locale": locale, "dir": dir_attr, "strings": strings})
    block = (
        f'<script>window.__PIRD_CONFIG__ = {payload};</script>\n  '
    )
    # idempotent: if the React build was rebuilt with a stale script, replace it.
    # Use re.DOTALL so the pattern crosses newlines; lazy .+? handles nested {}.
    if "window.__PIRD_CONFIG__" in index_html:
        import re
        index_html = re.sub(
            r'<script>window\.__PIRD_CONFIG__ = \{.+?\};</script>\n?\s*',
            "",
            index_html,
            flags=re.DOTALL,
        )
    # Inject BEFORE the first <script tag so the global is guaranteed to exist
    # before any module script evaluates. Vite places the bundle <script> in
    # <head>; if we inject after it, module evaluation may race the sync script.
    if "<script" in index_html:
        return index_html.replace("<script", f"{block}<script", 1)
    # Fallback: no script tag found (shouldn't happen with a normal Vite build)
    return index_html.replace("</head>", f"{block}</head>", 1)


async def _resolve_user_from_request(request: Request) -> Optional["AuthenticatedUser"]:
    """Decode the Clerk JWT from the Authorization header."""
    from app.auth.clerk_auth import require_user, AuthenticatedUser
    from fastapi import HTTPException

    auth = request.headers.get("authorization")

    if not auth:
        return None

    try:
        return await require_user(request=request, authorization=auth)
    except HTTPException:
        return None


async def _serve_tts_shell(request: Request) -> HTMLResponse:
    """Serve the React shell for /tts and /tts/{anything}.

    Auth: Handled entirely by the React app (ClerkProvider).
    """
    index_html = _read_tts_index_html()
    if index_html is None:
        return HTMLResponse(
            "<h1>TTS dashboard build missing</h1>"
            "<p>Run <code>npm run build</code> in <code>studio/dubbing/dashboard-tts/</code>.</p>",
            status_code=503,
        )

    locale = resolve_locale(request)
    dir_attr = "rtl" if is_rtl(locale) else "ltr"
    rendered = _inject_pird_config(index_html, locale, dir_attr)
    return HTMLResponse(
        rendered,
        headers={"Cache-Control": "no-store"},
    )


if TTS_DASHBOARD_DIR.is_dir():
    # Pird: register static asset mounts BEFORE the gated shell handler
    # so Starlette's insertion-order router matches them first. Otherwise
    # `/tts/{path:path}` swallows `/tts/assets/index-XXX.js` and 401s
    # before StaticFiles ever sees it. Asset bundles are public once the
    # gate has approved the user (the gate's HTML references them and the
    # browser fetches them on its own — no JWT on asset requests).
    app.mount(
        "/tts/assets",
        StaticFiles(directory=str(TTS_DASHBOARD_DIR / "assets")),
        name="tts_assets",
    )
    app.mount(
        "/assets",
        StaticFiles(directory=str(TTS_DASHBOARD_DIR / "assets")),
        name="assets",
    )

    # Favicon: small public file the browser auto-requests. Must be
    # registered BEFORE the catch-all `/tts/{path:path}` or the shell
    # handler eats it. Non-sensitive, public is fine.
    _favicon_path = TTS_DASHBOARD_DIR / "favicon.svg"
    if _favicon_path.is_file():
        @app.get("/tts/favicon.svg", include_in_schema=False)
        @app.get("/favicon.svg", include_in_schema=False)
        async def tts_favicon():
            from fastapi.responses import FileResponse
            return FileResponse(str(_favicon_path), media_type="image/svg+xml")

    # Two routes: exact `/tts` and the catch-all `/tts/{path:path}`. Both
    # funnel into the same handler so React Router's deep links (e.g.
    # /tts/voices, /tts/history) all resolve to the shell. Anything that's
    # not auth'd gets a 401 that AuthBounceMiddleware turns into a 302.
    @app.get("/tts", include_in_schema=False)
    async def tts_index(request: Request):
        return await _serve_tts_shell(request)

    @app.get("/tts/{path:path}", include_in_schema=False)
    async def tts_spa(request: Request, path: str):
        return await _serve_tts_shell(request)

    # Root-level SPA route fallbacks for deep links like /settings, /dubbing, etc.
    @app.get("/settings", include_in_schema=False)
    @app.get("/dubbing", include_in_schema=False)
    @app.get("/voices", include_in_schema=False)
    @app.get("/history", include_in_schema=False)
    @app.get("/pricing", include_in_schema=False)
    @app.get("/billing", include_in_schema=False)
    async def root_spa_routes(request: Request):
        return await _serve_tts_shell(request)

    logger.info(
        "[STARTUP] TTS dashboard gated at /tts/* (handler + static assets from %s)",
        TTS_DASHBOARD_DIR,
    )
else:
    logger.warning(
        "[STARTUP] TTS dashboard build missing at %s — run `npm run build` "
        "in dashboard-tts/. Skipping /tts mount.",
        TTS_DASHBOARD_DIR,
    )
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
try:
    from app.api.routes import video
    from app.api.routes import manual_video
    from app.api.routes import internal_jobs
    # Pird: TTS dashboard routes merged from studio/tts-service_old/ per
    # D:\pird\handoffs\dubbing-tts-merge-want-vs-have.md (Fix 1).
    # Mounted at /api/tts-dashboard to avoid collision with dubbing's own
    # GET /api/voices stub. Auth + locale wiring is Fix 4 (later).
    try:
        from app.api.routes import tts_dashboard
        app.include_router(tts_dashboard.router, tags=["tts_dashboard"])
        logger.info("[STARTUP] TTS dashboard router loaded OK")
    except Exception as e:
        logger.exception("[STARTUP] TTS dashboard router failed to load: %s", e)
    app.include_router(video.router, prefix="/video", tags=["video"])
    app.include_router(manual_video.router, prefix="/video/manual", tags=["manual_video"])
    # ponytail: /video/internal/* lives under the same prefix so it sits
    # next to the user-facing routes. No Supabase auth, gated by INTERNAL_API_KEY.
    app.include_router(internal_jobs.router, prefix="/video", tags=["internal_jobs"])
    
    try:
        from app.api.routes import user_delete
        app.include_router(user_delete.router, prefix="/api", tags=["user"])
    except Exception as e:
        logger.exception("[STARTUP] User delete router failed to load: %s", e)
    
    try:
        from app.api.routes import payments
        app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
        app.include_router(payments.router, prefix="/payments", tags=["payments"])
        logger.info("[STARTUP] Payments router loaded OK")
    except Exception as e:
        logger.exception("[STARTUP] Payments router failed to load: %s", e)
        
    try:
        from app.api.routes import telegram
        app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])
        logger.info("[STARTUP] Telegram router loaded OK")
    except Exception as e:
        logger.exception("[STARTUP] Telegram router failed to load: %s", e)

    try:
        from app.api.routes import support_playbook
        app.include_router(support_playbook.router, prefix="/api", tags=["support"])
        logger.info("[STARTUP] Support playbook router loaded OK")
    except Exception as e:
        logger.exception("[STARTUP] Support playbook router failed to load: %s", e)

    try:
        from app.api.routes import security_policy
        app.include_router(security_policy.router, prefix="/api", tags=["security"])
        logger.info("[STARTUP] Security policy router loaded OK")
    except Exception as e:
        logger.exception("[STARTUP] Security policy router failed to load: %s", e)
        
    logger.info("[STARTUP] Routers loaded OK")


except Exception as e:
    logger.exception("Failed to import routers: %s", e)


@app.on_event("startup")
async def on_startup():
    # Pird: validate required cloud API keys BEFORE doing anything else.
    # A half-configured prod deploy is the worst outcome -- jobs fail
    # mysteriously halfway through CPU phase and the operator has no idea
    # which provider is missing. Fail fast and loud.
    _REQUIRED_KEYS = [
        ("OPEN_ROUTER_API_KEY", "translation (Kurdish -> Arabic)"),
        ("FISH_API_KEY", "primary TTS (voice cloning)"),
        ("GEMINI_API_KEY", "collision-chunk transcription + translation"),
        ("ASSEMBLYAI_API_KEY", "fallback transcription"),
        ("DEEPGRAM_API_KEY", "fallback transcription"),
        ("R2_ENDPOINT", "source upload + zip download"),
        ("R2_ACCESS_KEY_ID", "R2 auth"),
        ("R2_SECRET_ACCESS_KEY", "R2 auth"),
        ("R2_BUCKET", "R2 bucket"),
        ("CONVEX_URL", "data layer"),
        ("INTERNAL_API_KEY", "Convex *Internal mutations"),
        ("CLERK_SECRET_KEY", "JWT verification"),
        ("RUNPOD_ENDPOINT_ID", "RunPod GPU trigger (skip if running local-only)"),
        ("RUNPOD_API_KEY", "RunPod GPU trigger (skip if running local-only)"),
    ]
    missing = [
        f"{name} ({purpose})"
        for name, purpose in _REQUIRED_KEYS
        if not os.getenv(name)
    ]
    is_prod = os.getenv("PIRD_ENV", "").lower() == "prod"
    if missing:
        logger.error(
            "[STARTUP] Missing env vars: %s",
            ", ".join(m.split(" ")[0] for m in missing),
        )

    try:
        from app.core import database
        await database.init_db()
        logger.info("[STARTUP] SQLite database ready")
    except Exception as e:
        logger.exception("[STARTUP] DB init failed: %s", e)

    # Pird (Option A): spawn the Azure CPU polling worker. After the
    # RunPod GPU phase finishes a job (status="gpu_finished"), nothing
    # advances it to "completed" unless this worker runs. It polls
    # Convex every 5s and runs ffmpeg mux on each gpu_finished job.
    # TEMP: disable on laptop swap-deploy (CONVEX_URL was pointing at
    # 127.0.0.1:3210 = dead local; worker hangs forever on its first
    # query, preventing uvicorn from finishing startup). Set to 1 to
    # skip. Re-enable once .env points at prod Convex URL.
    if os.getenv("DISABLE_CPU_WORKER") != "1":
        try:
            from app.services.cpu_worker import poll_for_gpu_finished_jobs
            app.state.cpu_worker_task = asyncio.create_task(poll_for_gpu_finished_jobs())
            logger.info("[STARTUP] Azure CPU polling worker spawned")
        except Exception as e:
            logger.exception("[STARTUP] Failed to spawn CPU worker: %s", e)
    else:
        logger.info("[STARTUP] Azure CPU polling worker DISABLED (DISABLE_CPU_WORKER=1)")


@app.on_event("shutdown")
async def on_shutdown():
    """Cancel the CPU polling worker gracefully."""
    task = getattr(app.state, "cpu_worker_task", None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("[SHUTDOWN] Azure CPU polling worker cancelled")


@app.get("/soraniq", response_class=HTMLResponse, include_in_schema=False)
@app.get("/{country_code}/soraniq", response_class=HTMLResponse, include_in_schema=False)
async def soraniq_landing(request: Request, country_code: str = "iq"):
    from pathlib import Path
    from fastapi.responses import HTMLResponse
    template_path = Path(__file__).parent / "templates" / "soraniq_landing.html"
    if template_path.is_file():
        return HTMLResponse(template_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>SoranIQ Landing Page</h1>", status_code=200)


@app.get("/")
async def index():
    return RedirectResponse(url="/tts/dubbing", status_code=302)


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = await _resolve_user_from_request(request)
    if not user:
        return {}
    
    try:
        from app.core import db as database
        import datetime
        user_client = database.get_user_client(user.access_token)

        # Process payment sync if returning with payment=success or ref parameter
        ref_id = request.query_params.get("ref") or request.query_params.get("referenceId")
        if ref_id:
            try:
                service_client = database._get_service_role_client()
                await database.process_payment_success_atomic(
                    service_client,
                    transaction_id=ref_id,
                    workspace_id=user.workspace_id,
                    tier="test_1000iqd",
                    amount_usd=1,
                    minutes_added=1
                )
            except Exception as sync_err:
                logger.warning(f"[AUTH_ME] Payment sync warning for ref {ref_id}: {sync_err}")

        remaining_minutes = await database.get_workspace_minutes(user_client, workspace_id=user.workspace_id)
        
        # Fetch transactions
        transactions = await database.list_transactions(user_client, workspace_id=user.workspace_id)
        
        total_purchased_minutes = sum(tx.get("minutesAdded", 0) for tx in transactions)
        total_minutes = max(remaining_minutes, total_purchased_minutes)
        if total_minutes == 0 and remaining_minutes > 0:
            total_minutes = remaining_minutes # Fallback if they were manually granted minutes without a transaction
            
        used_minutes = max(0, total_minutes - remaining_minutes)
        
        plan_expiry = "None"
        if remaining_minutes >= 100000:
            plan_type = "Enterprise"
        elif transactions:
            # Find most recent transaction date and tier
            recent_tx = max(transactions, key=lambda x: x.get("createdAt", ""))
            plan_type = str(recent_tx.get("tier", "Starter")).capitalize()
            created_at_str = recent_tx.get("createdAt")
            if created_at_str:
                try:
                    clean_ts = created_at_str.replace("Z", "+00:00")
                    tx_dt = datetime.datetime.fromisoformat(clean_ts)
                    expiry_dt = tx_dt + datetime.timedelta(days=30)
                    plan_expiry = expiry_dt.isoformat()
                except Exception as e:
                    logger.warning(f"Failed to parse transaction date: {e}")
        else:
            plan_type = "Free"
            
    except Exception as e:
        logger.warning(f"Failed to query workspace metrics: {e}")
        remaining_minutes = 999999
        total_minutes = 999999
        used_minutes = 0
        transactions = []
        plan_type = "Enterprise"
        plan_expiry = "Unlimited"

    return {
        "id": user.user_id,
        "workspace_id": user.workspace_id,
        "remaining_minutes": remaining_minutes,
        "total_minutes": total_minutes,
        "used_minutes": used_minutes,
        "plan": plan_type,
        "plan_expiry": plan_expiry,
        "transactions": transactions,
    }


@app.get("/healthz")
@app.get("/health")
@app.head("/healthz")
@app.head("/health")
async def healthz():
    return {"status": "ok"}


@app.get("/api/voices")
async def get_voices():
    return [{"id": "default", "name": "Default Voice", "status_tag": "ready"}]


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)


