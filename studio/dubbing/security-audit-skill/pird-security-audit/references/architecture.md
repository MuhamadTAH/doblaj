# Pird - Architecture Map

Kurdish-rooted platform: dubbing pipeline (Kurdish video to Iraqi-Arabic dub with vocal cloning) + Medusa storefront (Kurdish/Arabic products) + Chatwoot-based omnichannel bots (Instagram/Meta).

Status: pre-launch, internal-only, no live users or transactions yet. Solo-maintained, no code review process besides self-review across audit passes.

**Stack migration confirmed (pass-9):** the dubbing service + dashboard have moved off Supabase (Postgres + Auth) onto Convex (data) + Clerk (auth, via Organizations). Medusa's storefront keeps its own Postgres - a structural requirement of Medusa itself, untouched by this migration.

## Services

| Layer | Tech |
|---|---|
| Dubbing backend | Python 3.11+, FastAPI, uvicorn |
| Store backend | Node 20+, Medusa.js 2.x (own Postgres, unaffected by this migration) |
| Storefront | Next.js 14, yarn 4.12 |
| Dubbing dashboard | React + Vite + TypeScript, Zustand, Tailwind |
| Chat platform | Chatwoot (cloned from upstream, official Docker image) |
| Worker queue | Celery + Redis |
| Data layer | Convex - a pass-through persistence layer here; it does not independently check identity |
| Auth | Clerk, via Organizations (`org_xxx` claims resolved to legacy workspace UUIDs) |
| ML models | BS-RoFormer, HTDemucs_ft, Pyannote diarization, Silero VAD, Resemble Enhance |
| TTS / transcription | Fish Audio (HTTP), ElevenLabs, Gemini 3.5 Flash + 3 Flash via OpenRouter |
| Storage | Cloudflare R2 (outputs), local FS (intermediates) |
| Bot integrations | Meta Graph API, Chatwoot webhooks |

Monorepo, 7 services. `bot-bridge` and `ai-gateway` are scaffolds only (no package.json yet) - don't assume they have the same protections as the services that do exist until they're actually built out.

## Data map

| Data | Where | Sensitivity |
|---|---|---|
| Emails + user IDs | Clerk (user records) | PII |
| Voice recordings (originals) | Local FS `data/jobs/sessions/{n}/`, R2 | High - biometric-adjacent, no consent flow documented |
| Reference voice WAVs (cloning input) | Local FS `data/jobs/playground_ingest/{session_id}/global_voice_ref.wav` | High - direct cloning material; now also used by ElevenLabs, not just Fish Audio |
| Job/chunk state, translated text | Convex (was Supabase) | Medium - reveals video content |
| TTS audio | Local FS + R2 | Medium |
| Workspace/tenant membership | Clerk Organizations (`org_xxx`), resolved to a legacy UUID via `_resolve_legacy_workspace_id` | Low, but this resolution chain IS the entire isolation boundary - see PIRD-001 |
| API keys / secrets | `.env`, `.env.production`, plus Clerk + Convex credentials, `INTERNAL_API_KEY` | High |

Everything also lands in `data/logs/vcta.log` - the global file logging handler (`main.py:98-103`) writes every request, with no rotation.

## Trust boundaries

- **Edge**: Caddy reverse proxy terminates TLS in prod (`https://dubbing.pird.com`, `https://doblaj.com` - DNS not pointed there yet).
- **Internal**: container-to-container traffic is plain HTTP. Fine for a single host; stops being fine the moment services split across hosts.
- **Outbound**: dubbing job callbacks go to a caller-supplied `webhook_url` (SSRF-relevant - see PIRD-004); dubbing also calls out to Fish Audio, ElevenLabs, OpenRouter/Gemini, R2, and Convex.
- **Inbound**: bot-bridge receives Chatwoot webhooks; comment-bot receives Meta Graph API comments.
- **Confirmed request path - two entry points into Convex:**
  1. **Browser -> FastAPI -> Convex.** The browser sends `dubbing_access_token` (same cookie name as the Supabase era, now a Clerk-issued session JWT). FastAPI's `/video/*`, `/tts/*`, `/api/*` routes decode the Clerk JWT, resolve its `org_xxx` claim to a legacy workspace UUID via `_resolve_legacy_workspace_id`, and pass that UUID to Convex as a plain string argument. `AuthBounceMiddleware` already handles the missing-JWT case (401) - no need to re-test that specifically.
  2. **RunPod worker -> FastAPI's `internalJobs` router (main.py:390) -> Convex.** Gated by one static `INTERNAL_API_KEY` shared across every cross-service call - not scoped per caller or per workspace. This router takes `workspace_id` directly from the request body instead of deriving it from anything the worker can't forge. This is PIRD-017, the actual current isolation gap.
- **Auth model, stated plainly**: Convex does not independently verify identity. `ctx.auth`/Clerk-JWT validation inside Convex functions is not in use here - every public Convex function has zero identity checks by design. Isolation lives entirely at the FastAPI edge: Convex's `by_workspace_id` index filtering trusts whatever string it's handed. This is a coherent architecture - Convex's `internal*` functions are platform-blocked from any external caller, not just convention-blocked - but it means the whole isolation guarantee rests on FastAPI always computing the correct `workspace_id` for the correct caller, on **both** entry points above, not just the browser one.
- **Confirmed non-issue**: `ttsVoices:list` is a public Convex query, directly reachable via Convex's HTTP API, returning all voices globally with no per-workspace filtering. Accepted as fine - voices are global reference data, not tenant-scoped (PIRD-018). Documented so it doesn't get re-flagged as a gap later.
- **Not yet audited**: every other Convex query/mutation's workspace filtering. Only `users`, `dubbingJobs:list*`, and `ttsVoices:list` have been spot-checked so far. Anything tenant-scoped that turns out to be a public (non-`internal*`) function is a live PIRD-015 instance - run `convex_function_audit.sh` against the real `convex/` directory before assuming coverage.

## Deployment target

Dev: Windows 11 dev machine, Docker + docker-compose. Prod target: Railway (per `.claude/agents/devops-deployer.md`), not yet deployed. Nothing is reachable from the public internet today - don't let that lower the severity of any finding, since severity describes what happens if it's exploited, not how likely exploitation is on day one.
