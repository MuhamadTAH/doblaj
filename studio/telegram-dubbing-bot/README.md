# Pird Telegram Video Dubbing Bot (MVP)

A standalone, asynchronous Telegram Bot built with **Aiogram 3.x** and **aiohttp**, designed to run as a secure Webhook service on an Azure Linux VM (`172.160.249.201`).

## 🏗️ Architecture & Features
- **Webhook Interface**: Serves HTTPS on port 443 via `aiohttp`, avoiding polling delays.
- **Self-Signed SSL**: Automatically generates SAN-bound OpenSSL certificates required for bare IP webhooks.
- **Security Guardrails**: Enforces `X-Telegram-Bot-Api-Secret-Token` validation and per-IP rate limiting.
- **Strict Validation**: Validates file metadata (strictly under 20 MB) and verifies MP4 magic byte headers (`ftyp`, `moov`, `mdat`) to prevent executable file uploads.
- **Unstable Network Resilience**: Immediately acknowledges Telegram webhooks (`200 OK`) and edits UX to `"Processing..."` before dispatching heavy GPU jobs, preventing retries and timeouts on Iraqi/Sulaymaniyah networks.
- **Serverless GPU Handoff**: Non-blocking asynchronous dispatch to Replicate (`AsyncReplicate`) for video translation and dubbing.
- **Telemetry Logging**: Fire-and-forget HTTP POST requests to Convex database endpoints without slowing down the pipeline.

## 🚀 5-Minute Deployment on Azure Ubuntu VM (`172.160.249.201`)

### 1. Transfer files to server
```bash
# On your local machine:
scp -r ./telegram-dubbing-bot ubuntu@172.160.249.201:~/
```

### 2. Connect via SSH
```bash
ssh ubuntu@172.160.249.201
cd ~/telegram-dubbing-bot
```

### 3. Generate SSL Certificates
```bash
chmod +x generate_cert.sh
./generate_cert.sh
```

### 4. Build and Start Container
```bash
docker compose up -d --build
```

### 5. Check Logs
```bash
docker compose logs -f
```
You should see: `Setting webhook to https://172.160.249.201/webhook`.
Now open Telegram and send `/start` to your bot!
