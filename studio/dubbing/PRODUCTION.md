# Pird Dubbing — Production Platform

Single source of truth for the live dubbing platform. Read this before making
any change that touches production data, prod credentials, or a prod service.
If you are an AI assistant and the user is asking you to "change X in
production" or "fix Y for prod", start here.

**Repository**: `MuhamadTAH/doblaj` (branch: `main`)
**Owner**: FIXDAI LLC (d/b/a Doblaj)
**Status**: live at `https://doblaj.com`

---

## What runs where

| Service             | Where                              | URL / Endpoint                                  | Notes                                                                                          |
|---------------------|------------------------------------|--------------------------------------------------|------------------------------------------------------------------------------------------------|
| Frontend (React)    | Cloudflare Pages                   | `https://doblaj.com`                             | Vite SPA, env-injected at build: `VITE_API_BASE_URL`, `VITE_CONVEX_URL`, Clerk publishable key  |
| Backend (FastAPI)   | Azure VM `dubbing-bot-vps`         | `https://api.doblaj.com` → `127.0.0.1:8002`     | Cloudflare Tunnel, no inbound ports open; runs on `azureuser` via systemd `doblaj.service`     |
| GPU worker          | RunPod Serverless `eu-ro-1`        | endpoint `3wz0kfi2xnbkxx`                        | Image `muhammadtarq/pird-dubbing-worker:v6`, async handler, L4 GPU                             |
| CPU worker          | In-process on FastAPI VM           | n/a (polls Convex)                               | `app/services/cpu_worker.py` started by FastAPI lifespan                                       |
| Data layer          | Convex (prod)                      | `https://upbeat-scorpion-447.convex.cloud`       | Deployment hash `20260728T224050Z-a42e7a9c8375`; backend holds shared `INTERNAL_API_KEY`      |
| Object storage      | Cloudflare R2                      | bucket `doblaj-media`                            | Holds source uploads, GPU intermediate zips (`dubbing/intermediates/...`), final MP4s          |
| Auth                | Clerk (prod)                       | issuer `https://clerk.doblaj.com`                | `pk_live_...` / `sk_live_...`; JWT cookie domain `.doblaj.com`                                |
| Payments            | Suby                               | `https://api.suby.fi/api`                        | Static checkout links: `SUBY_LINK_STARTER`, `SUBY_LINK_PRO`, `SUBY_LINK_CREATOR`               |

## Convex prod quick-check

```bash
# Deploy reachable?
curl -sS "https://upbeat-scorpion-447.convex.cloud/version"
# → 20260728T224050Z-a42e7a9c8375

# Authenticated query (read the matching .ts file for the right path + args)
INTERNAL_KEY=$(grep "^INTERNAL_API_KEY=" /opt/app/studio/dubbing/.env | cut -d= -f2-)
curl -sS -X POST "https://upbeat-scorpion-447.convex.cloud/api/query" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"<module>:<function>\",\"args\":{...,\"__internalApiKey\":\"$INTERNAL_KEY\"}}"
```

For live data inspection prefer the Convex dashboard (https://dashboard.convex.dev).

## Repository layout (dubbing only)

```
studio/dubbing/
├── main.py                         # FastAPI entrypoint
├── app/
│   ├── auth/clerk_auth.py          # Clerk JWT validation (lazy JWKS, see below)
│   ├── api/routes/video.py         # /api/video/jobs — main user-facing endpoint
│   ├── api/routes/internal_jobs.py # /api/internal/jobs — service-to-service (mock pipeline)
│   ├── api/routes/payments.py      # Suby checkout
│   ├── api/routes/tts_dashboard.py # /api/tts-dashboard/* (Clerk-gated)
│   ├── core/db.py                  # Data layer selector (DATA_BACKEND=convex)
│   ├── services/
│   │   ├── cpu_worker.py           # In-process poll of Convex, runs CPU phase
│   │   ├── pipeline.py             # Stage 4-8: reassemble dubbed MP4
│   │   ├── runpod.py               # Triggers GPU worker
│   │   ├── r2.py                   # R2 client + presigned URL helper
│   │   ├── database_convex.py      # Convex client wrapper
│   │   └── suby_client.py          # Suby payment client
│   └── static/tts-dashboard/       # Built React SPA (committed for prod)
├── dashboard-tts/                  # React/Vite source
│   ├── src/                        # Components, pages, hooks
│   └── convex/                     # Convex schema + functions (TypeScript)
│       ├── schema.ts               # Tables: workspaces, dubbingJobs, voices, ...
│       ├── workspaces.ts           # Internal-key-gated workspace functions
│       ├── dubbingJobs.ts          # Job lifecycle
│       └── http.ts                 # Clerk webhook handler
├── clerk_patch.py                  # Lazy-init JWKS client (already merged into clerk_auth.py as of 5936801)
├── test_*.py                       # Pytest tests
└── .env                            # PRODUCTION secrets — never commit
```

## How a dubbing job flows

1. **Upload** — Browser `POST /api/video/jobs` (multipart). Clerk session cookie → `require_user` → `AuthenticatedUser{user_id, workspace_id}`. Job inserted into Convex `dubbingJobs` with `status="pending"`. Source MP4 uploaded to R2 at `dubbing/uploads/<job_id>.mp4`. Returns `{id, status}`.
2. **GPU trigger** — `app/services/runpod.py:trigger_runpod_job()` POSTs to RunPod `https://api.runpod.ai/v2/<endpoint>/run` with `{input: {job_id, r2_key, ...}}`. RunPod pulls image `muhammadtarq/pird-dubbing-worker:v6`, runs async handler (audio separation skipped in v6, transcription, translation, TTS).
3. **GPU complete** — Worker uploads intermediate zip to R2 at `dubbing/intermediates/<job_id>.zip`, updates Convex `status="gpu_complete"`, posts callback to FastAPI.
4. **CPU worker** — `app/services/cpu_worker.py` polls Convex every N seconds for `status="gpu_complete" && cpuWorkerClaimedAt=null`. Claims job, downloads zip, runs `pipeline.process_video_cpu_phase()` (reassemble audio+video, render final MP4, upload to `dubbing/outputs/<job_id>.mp4`), updates Convex `status="completed"`.
5. **Download** — User polls `GET /api/video/jobs/{id}` for status + progress. On `completed`, browser hits `GET /api/video/jobs/{id}/download` which 302s to a presigned R2 URL (24h TTL by default).

## Critical env vars (in `studio/dubbing/.env` on the VM)

| Var | Purpose |
|---|---|
| `PIRD_ENV=prod` | Switches startup validator to prod-required-keys mode |
| `PIRD_SHELL_ORIGIN=https://doblaj.com` | Used for auth redirects |
| `CONVEX_URL=https://upbeat-scorpion-447.convex.cloud` | Prod Convex |
| `DATA_BACKEND=convex` | Selects Convex data layer |
| `INTERNAL_API_KEY` | Shared secret with bot-bridge / ai-gateway. 64-char hex. **Compromised** — leaked in earlier session chat. **Rotate**. |
| `FISH_API_KEY`, `OPEN_ROUTER_API_KEY`, `HF_TOKEN`, `ASSEMBLYAI_API_KEY`, `DEEPGRAM_API_KEY` | Audio + translation providers. **All leaked — rotate.** |
| `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET=doblaj-media` | Object storage. **All leaked — rotate.** |
| `RUNPOD_ENDPOINT_ID=3wz0kfi2xnbkxx`, `RUNPOD_API_KEY` | GPU worker. **Leaked — rotate.** |
| `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_ISSUER=https://clerk.doblaj.com`, `CLERK_JWKS_URL`, `CLERK_AUDIENCE=pird-dubbing`, `CLERK_FRONTEND_API=clerk.doblaj.com` | Auth. **Leaked — rotate.** |
| `COOKIE_DOMAIN=.doblaj.com`, `ALLOWED_ORIGINS=https://doblaj.com,https://api.doblaj.com` | CORS / cookies |
| `SUBY_API_KEY`, `SUBY_WEBHOOK_SECRET`, `SUBY_API_URL=https://api.suby.fi/api` | Payments. **Leaked — rotate.** |
| `SUBY_LINK_STARTER`, `SUBY_LINK_PRO`, `SUBY_LINK_CREATOR` | Static checkout URLs (no secrets) |
| `GEMINI_API_KEY` | OPTIONAL — `main.py` skips it in the required-keys check |

## Required prod patches (already in origin/main as of `5936801`)

- `app/auth/clerk_auth.py`: lazy `_jwks_client = None` + `get_jwks_client()` so PyJWT's JWKS prefetch doesn't block startup when Clerk is slow
- `main.py`: `name != "GEMINI_API_KEY"` in the missing-keys check so an unset Gemini key doesn't 500 the server

`clerk_patch.py` is a one-shot patcher for those two changes. It is committed
for historical reference; the source files already contain the patches.

## How to deploy a change

User workflow (laptop → VM). The operator is the human; AI assistants do not
have SSH or push access.

```powershell
# Laptop
cd D:\pird
git add -A
git commit -m "<type>(<scope>): <subject>"
git push origin main
```

```bash
# VM (via SSH)
pirdupdate     # alias defined in ~/.bashrc:
               # cd /opt/app && sudo git fetch origin &&
               # sudo git reset --hard origin/main &&
               # cd studio/dubbing &&
               # sudo systemctl restart doblaj &&
               # sleep 20 && curl -sS https://api.doblaj.com/healthz
```

For Convex-only changes (no Python):

```powershell
cd D:\pird\studio\dubbing\dashboard-tts
npx convex deploy --prod
```

The next `pirdupdate` on the VM is a no-op (the backend reads Convex live).

## Systemd units on the VM

- `/etc/systemd/system/doblaj.service` — FastAPI + CPU worker. `User=azureuser`, `EnvironmentFile=/opt/app/studio/dubbing/.env`, `ExecStart=/opt/app/studio/dubbing/.venv/bin/python main.py`. `Restart=always`.
- `/etc/systemd/system/cloudflared.service` — Tunnel `8669efeb-5ea7-4de5-b8e6-151ce23890d2`, routes `api.doblaj.com` → `http://127.0.0.1:8002`.

Restart commands:
```bash
sudo systemctl restart doblaj
sudo systemctl restart cloudflared
```

## Verification (smoke test)

```bash
# Backend up
curl -sS https://api.doblaj.com/healthz                 # {"status":"ok"}
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  https://api.doblaj.com/api/auth/me                    # 200 (user is null) or 401

# Convex wired
curl -sS https://upbeat-scorpion-447.convex.cloud/version
INTERNAL_KEY=$(grep "^INTERNAL_API_KEY=" /opt/app/studio/dubbing/.env | cut -d= -f2-)
curl -sS -X POST "https://upbeat-scorpion-447.convex.cloud/api/query" \
  -H "Content-Type: application/json" \
  -d "{\"path\":\"workspaces:findByOwnerInternal\",\"args\":{\"ownerUserId\":\"smoketest\",\"__internalApiKey\":\"$INTERNAL_KEY\"}}"
# → {"status":"success","value":null}
```

## Out of scope (DO NOT TOUCH in a dubbing-only task)

- `store/`, `store/backend`, `store/storefront` (Medusa)
- `chatwoot-clone/`
- `studio/ai-gateway/`
- `studio/bot-bridge/`
- `studio/comment-bot/`
- `studio/telegram-dubbing-bot/` (separate bot, not in dubbing-platform scope)
- `studio/tts-service/` (legacy)
- `tools/SkillSpector/`

## Known issues / non-urgent TODOs

- All API keys/secrets leaked in earlier chat sessions. **Rotation pending.**
- VM is `172.160.249.201` with `azureuser` SSH — keep that user + key for now.
- CPU phase runs in-process on the FastAPI VM. For scale, move to a separate worker pool (RQ/Celery) — already noted in `app/services/workers.py` (refactor #111).
- Frontend build is committed in `app/static/tts-dashboard/` (Vite output). For a frontend-only change: edit under `dashboard-tts/src/`, `npm run build`, commit the new `app/static/tts-dashboard/` artifacts.
- The CF Pages deployment uses `VITE_API_BASE_URL=https://api.doblaj.com` — do NOT add `VITE_API_BASE` (legacy) or `SUBY_*` (backend-only) to the Pages env.

## Acceptance criteria for a "dubbing works in prod" check

1. `https://doblaj.com` loads, sidebar shows English labels (no raw i18n keys)
2. Sign in via Clerk, land on the dashboard
3. Browser Network tab shows calls to `api.doblaj.com/api/...` (not `doblaj.com/api/...`)
4. Voices list loads (TTS dashboard)
5. Upload a small MP4 through `/dubbing`
6. Job appears in `GET /api/video/jobs` list
7. Status progresses `pending` → `processing` → `completed`
8. Final MP4 downloads from R2 presigned URL

Tasks #98 (CF Pages smoke test) and #135 (end-to-end CPU phase test) are the
remaining items to mark the deploy complete.
