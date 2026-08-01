# RunPod debug prompt -- give to another AI to diagnose

## Context

We built a dubbing pipeline that splits work between two compute backends:

- **GPU phases** (Demucs RoFormer vocal isolation + Pyannote speaker diarization) run on RunPod Serverless
- **CPU phases** (transcribe, translate, TTS, mux) run on our FastAPI host, polling Convex

The FastAPI backend uploads the source video to Cloudflare R2, then POSTs to RunPod's
Serverless endpoint to trigger GPU work. When GPU work finishes, the RunPod worker
uploads an intermediate zip to R2 and patches Convex status to `gpu_finished`. Our
CPU worker then picks it up.

## The bug we just found and fixed

My Python code was POSTing to `https://api.runpod.io/v2/{endpoint}/run`. That returns
404 -- the `/v2/` API actually lives at `https://api.runpod.ai/v2/{endpoint}/run`.
Both URLs come up in RunPod docs and it's confusing. The correct one for our case
is `.ai`. We changed `app/api/routes/video.py` to use `.ai`.

## What works (verified just now)

- FastAPI uploads 4 MB TikTok video to R2: OK
- POST to `https://api.runpod.ai/v2/3wz0kfi2xnbkxx/run` with Bearer auth: HTTP 200, returns `{"id": "...", "status": "IN_QUEUE"}`
- RunPod accepts the job

## What doesn't work

- Job stays `IN_QUEUE` indefinitely (60s, then 100s, no movement)
- Worker never picks it up
- No error, no FAILED, no progress

## What we know about the endpoint

- Endpoint ID: `3wz0kfi2xnbkxx`
- RunPod dashboard URL: `https://console.runpod.io/serverless/user/endpoint/3wz0kfi2xnbkxx?tab=overview`
- Regions available: `us-mo-2` (US Missouri) and `eu-ro-1` (EU Romania)
- The user has not yet shared a screenshot of the dashboard or confirmed:
  - Whether Min Workers / Max Workers are set
  - What GPU type is selected
  - Whether a custom Docker image is configured
  - Whether the 7 required env vars are set (CONVEX_URL, INTERNAL_API_KEY, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, HF_TOKEN)

## What we need to know

Diagnose why jobs stay `IN_QUEUE`. Possible causes:

1. **No active workers** -- endpoint created with `Max Workers = 0` or workers scaled to zero. Should be at least 1.
2. **No GPU available in region** -- us-mo-2 or eu-ro-1 may not have the requested GPU type in stock. Try the other region.
3. **Docker image missing/broken** -- RunPod needs a custom image. We have a Dockerfile at `studio/dubbing/Dockerfile` that builds from `pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime` and runs `python -u runpod_worker.py`. Has this been built and pushed to Docker Hub or RunPod's registry? Has the endpoint been pointed at it?
4. **Worker boots then crashes** -- env vars missing or wrong. Without `CONVEX_URL` etc., the worker `import runpod` succeeds but the first request handler fails. RunPod's logs tab on the endpoint should show the traceback.
5. **Cold start in progress** -- first request to a Serverless endpoint takes 30s-2min to spin up a worker. Maybe just wait longer.

## What we want

A concrete fix. Please:

1. Identify which of the 5 causes above applies.
2. If it's cause 3 or 4, tell us exactly which env var is missing or which Dockerfile step is wrong.
3. If it's cause 1 or 2, tell us the exact RunPod dashboard setting to change (with screenshot if helpful).
4. If it's cause 5, tell us how long to wait and how to verify the worker eventually picks up the job.

Don't speculate. Don't suggest alternative architectures (we already committed to RunPod + Convex + R2). Just diagnose this specific failure.

## What you can ask us

- Screenshot of the endpoint Overview tab
- Screenshot of the Logs tab after triggering a test job
- Contents of the endpoint's Environment Variables section
- The Docker image name/tag the endpoint is configured to use

We will paste whatever you ask for.