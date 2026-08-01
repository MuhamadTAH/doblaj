# Dubbing Service

Kurdish Sorani → Iraqi Arabic dubbing pipeline. Receives a video, separates vocals, transcribes via Gemini, translates via MiniMax/Claude, synthesizes audio, and reassembles via FFmpeg.

## Domain
- Production: `https://studio.mysite.com/api/dub` (reverse proxied)
- Local dev: `http://localhost:8002`

## Stack
- **Runtime:** Python
- **Framework:** FastAPI
- **Storage:** Cloudflare R2
- **Database:** Supabase Postgres

## How to run locally
1. `cp .env.example .env` and fill in values
2. Create virtual environment and install requirements
3. Run uvicorn: `uvicorn main:app --reload --port 8002`

## Required env vars
See `.env.example` for the full list. Key ones:
- `DUBBING_URL` — public URL of this service
- `AI_GATEWAY_URL` — for translation/ASR (NEVER call providers directly)
- `R2_*` — Cloudflare R2 configuration
- `INTERNAL_API_KEY` — shared secret key for internal requests
- `SUPABASE_*` — for `dubbing_jobs` and `dubbing_chunks` tables

## Tables owned
`dubbing_jobs`, `dubbing_chunks`.

## Cross-service calls
All other services are reached by HTTP using `os.getenv("<SERVICE>_URL")`.
Never import code from other services.

