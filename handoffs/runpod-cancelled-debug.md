# RunPod Worker CANCELLED -- debug prompt

## What just happened

We built and pushed `muhammadtarq/pird-dubbing-worker:v3` with:
- Fixed `runpod_worker.py` (no more Supabase import that crashed)
- HF_TOKEN baked in (Pyannote weights pre-cached)
- All 7 runtime env vars set on the endpoint (CONVEX_URL=https://upbeat-scorpion-447.convex.cloud, INTERNAL_API_KEY, R2_*, HF_TOKEN)

We uploaded a 4 MB test video to R2, POSTed to `https://api.runpod.ai/v2/3wz0kfi2xnbkxx/run` with the real API key. Got HTTP 200 with `IN_QUEUE`. Polled for 105s, then status changed to `CANCELLED`.

Endpoint config (from the RunPod AI's response):
- workersMin: 0
- workersMax: 3
- idleTimeout: 1 second (very aggressive)
- scaler: QUEUE_DELAY / scalerValue: 4

## Question for the next AI

Why did this job go from `IN_QUEUE` to `CANCELLED` instead of `RUNNING` -> `COMPLETED`?

Possible causes to rule out:

1. **GPU type out of stock in us-mo-2 / eu-ro-1** -- even though Max Workers = 3, if RunPod has 0 GPUs of the requested type available, it can't start a worker. The job sits in queue, then RunPod cancels it because no worker can be allocated within the scaler window.

2. **idleTimeout: 1 second is too aggressive** -- a worker can't cold-start (model loading, CUDA init) in 1 second. Worker spins up, gets killed before processing, autoscaler cancels the job.

3. **executionTimeoutMs too low** -- if set to something like 30s, a RoFormer cold-start that takes 60-90s gets killed.

4. **Region selection** -- endpoint might be configured for a region that doesn't have the requested GPU type. Should switch to a region with availability.

## What we need to know

Open the RunPod dashboard for endpoint 3wz0kfi2xnbkxx -> Settings/Config tab. Tell us:

1. **GPU type** selected (e.g. NVIDIA A40, A100 40GB, RTX 4090, etc.)
2. **idleTimeout** value (we know it's 1s -- should be 30-60s)
3. **executionTimeoutMs** value (need 600000+ for RoFormer cold start)
4. **Active workers** count -- should be > 0 in either us-mo-2 or eu-ro-1
5. **Region** the endpoint is pinned to (if any)
6. **Container disk** size -- needs 30+ GB for PyTorch + model cache
7. **Recent failed requests log** -- paste the worker stdout/stderr from a failed run if available

## What we want

A concrete fix. Tell us exactly which RunPod dashboard setting to change, with the new value. Don't suggest alternative architectures (we're committed to RunPod).

If the GPU is unavailable in both regions, suggest a different GPU type that IS available. Cheapest viable: A40 48GB or RTX 4090 24GB.