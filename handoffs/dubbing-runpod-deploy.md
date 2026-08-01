# RunPod Serverless Worker — Deploy Handoff

The dubbing pipeline splits heavy work between two compute backends:
RunPod Serverless (GPU phases) and the FastAPI host (CPU phases). This
handoff documents what the RunPod worker needs to actually start.

## Image

The RunPod Serverless endpoint `3wz0kfi2xnbkxx` is built from
`studio/dubbing/Dockerfile`. The Dockerfile:

- Base: `pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime`
- Caches AI models via `python scripts/cache_models.py` at build time
  (Demucs, Pyannote, Resemble-Enhance). This means Pyannote weights
  must be downloadable -- see HF_TOKEN below.
- CMD: `python -u runpod_worker.py`

## Env vars the operator MUST set on the RunPod endpoint

These are injected at endpoint-creation time via the RunPod dashboard
("Environment Variables" section when creating the endpoint). They are
NOT in `.env` on the FastAPI host and the worker cannot read them from
anywhere else.

| Variable | Why |
|---|---|
| `CONVEX_URL` | Worker patches Convex job status (`gpu_finished`, `failed`). Use the prod URL `https://upbeat-scorpion-447.convex.cloud`. |
| `INTERNAL_API_KEY` | The shared secret Convex checks on every `*Internal` mutation. MUST match the value in `studio/dubbing/.env.production` AND `dashboard-tts/convex/.env`. |
| `R2_ENDPOINT` | Worker downloads source video from R2 and uploads intermediate zip back. |
| `R2_ACCESS_KEY_ID` | R2 auth. |
| `R2_SECRET_ACCESS_KEY` | R2 auth. |
| `R2_BUCKET` | `doblaj-media` |
| `HF_TOKEN` | Pyannote.audio weights are gated; without this `scripts/cache_models.py` fails at Docker build time. Acquire from huggingface.co/settings/tokens AFTER accepting the Pyannote model license. |

## Trigger URL (important — easy to get wrong)

The FastAPI backend POSTs to RunPod Serverless at:

```
https://api.runpod.ai/v2/{endpoint_id}/run
```

**NOT** `api.runpod.io` — that hostname returns 404. The `/v2/` path
lives on the `.ai` domain. Don't be fooled by the `.io` docs pages.

## What the worker does

`runpod_worker.py` is the entry point. Per request it:

1. Reads the event payload: `{job_id, workspace_id, category, entity, source_video_r2_key}`.
2. Downloads the source video from R2 to `data/jobs/sessions/inputs/{job_id}.mp4`.
3. Runs `process_video_gpu_phase(...)` -- Stages 0-3:
   - Phase 0: pre-stretch to 0.95x (ffmpeg)
   - Stage 1: Demucs vocal isolation (GPU)
   - Stage 1.5: separate vocal-only and noise-only video files (ffmpeg)
   - Stage 2: Pyannote diarization (GPU)
   - Stage 2.5: secondary-speaker restoration (resemble-enhance, GPU)
   - Stage 3: pristine slice & gate (CPU ffmpeg)
4. Zips the entire `work_dir` into `{job_id}.zip`.
5. Uploads the zip to R2 under `workspaces/{workspace_id}/jobs/{job_id}/intermediate_{job_id}.zip`.
6. Patches Convex: status=`gpu_finished`, progress=50, output_path=R2 zip key.
7. Returns `{status: "success", result_zip_r2_key: ...}`.

The Azure CPU worker (running on the FastAPI host) sees status=`gpu_finished`
on its next 5s poll, downloads the zip, runs Stages 4-8, uploads the final MP4.

## Failure modes the operator should know

- **"HF_TOKEN missing" during Docker build.** Acquire the token after
  accepting the Pyannote license at huggingface.co/pyannote/segmentation-3.0.
  Pass via `docker build --build-arg HF_TOKEN=hf_xxx .` when rebuilding.
- **Worker times out on first request.** Pyannote cold-start is slow
  even with cached weights. Set RunPod endpoint `executionTimeoutMs` to
  at least 600000 (10 min) for the first request; subsequent runs hit
  warm cache.
- **"WORKSPACE_MISMATCH" on status patch.** The Convex internal API key
  in the RunPod env doesn't match Convex's. Both must be the same value.
- **Status stuck at `gpu_finished`.** Worker uploaded zip but Azure CPU
  worker is not polling. Check `app.state.cpu_worker_task` is running on
  the FastAPI host (look for `[STARTUP] Azure CPU polling worker spawned`
  in FastAPI logs).

## Rebuild trigger

After any change to `runpod_worker.py`, `app/services/video_worker_vcta.py`,
or the Dockerfile: rebuild the image and re-deploy to RunPod via the
RunPod dashboard "Custom Image" workflow, then update endpoint
`3wz0kfi2xnbkxx` to point at the new image tag.