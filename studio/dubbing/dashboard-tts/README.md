# Pird TTS Dashboard

A premium, multi-page Text-to-Speech web dashboard for the **Pird TTS** service
in `D:\Pird\studio\tts-service_old\`. Built with Vite + React + TypeScript +
Tailwind + Framer Motion. Backend is a thin FastAPI proxy to the Fish Audio API
(no local PyTorch / no model weights).

## Pages

| Route        | Purpose                                                    |
|--------------|------------------------------------------------------------|
| `/`          | **Text to Speech** — multi-speaker, voice picker, settings/history tabs in right sidebar |
| `/dubbing`   | **Video Dubbing** — source audio upload, target voice picker, convert/history |
| `/voices`    | **Voice Library** — grid of voices with preview            |
| `/history`   | **History** — every generation, with play/download/delete  |

## Stack

- **React 18 + TypeScript** — typed component model
- **Vite** — dev server + bundler
- **React Router v6** — true multi-page app
- **Tailwind CSS** — utility-first styling
- **Framer Motion** — micro-animations (sidebar indicator, player slide-in, list transitions)
- **Zustand** — global state for the audio player + history
- **FastAPI** — `/api/tts`, `/api/voices`, `/api/health` (proxies Fish Audio)

## Quick start

```bash
# 1. Install JS deps
cd D:\Pird\studio\tts-service_old\dashboard
npm install

# 2. Run the dashboard (dev)
npm run dev
# opens http://localhost:5173 — proxies /api to localhost:8000

# 3. Run the backend in another terminal
cd D:\Pird\studio\tts-service_old
pip install fastapi uvicorn httpx python-dotenv
uvicorn main:app --reload --port 8000
```

The Vite dev server proxies `/api/*` to `http://localhost:8000`, so the React
app's `fetch('/api/tts')` call hits the FastAPI route transparently.

### Without a Fish Audio key

The dashboard gracefully **falls back to a mock silent WAV** if `/api/tts`
fails. This means the UI demos end-to-end with no key, no model, and no
backend — just `npm run dev`.

## Wiring a real Fish Audio key

Add to `D:\Pird\studio\tts-service_old\.env`:

```
FISH_API_KEY=fa-xxxxxxxxxxxxxxxx
INTERNAL_API_KEY=some-long-random-string   # for cross-service calls
```

Then `dashboard_api.py` will proxy real audio instead of returning 503.

## Layout

```
dashboard/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── index.html
├── public/favicon.svg
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── index.css
    ├── api/tts.ts              # fetch wrappers, mock silent WAV
    ├── store/tts.ts            # Zustand store
    ├── lib/format.ts           # uid, formatDuration, formatTimeAgo
    ├── components/
    │   ├── Sidebar.tsx
    │   ├── TopNav.tsx
    │   ├── GlobalPlayer.tsx
    │   ├── Modal.tsx
    │   └── VoicePickerModal.tsx
    └── pages/
        ├── GeneratePage.tsx        # Text to Speech
        ├── VideoDubbingPage.tsx
        ├── VoiceLibraryPage.tsx
        └── HistoryPage.tsx
```

## Production build

```bash
npm run build
# outputs to dist/
```

You can mount `dist/` behind FastAPI as a `StaticFiles` mount, or behind nginx
alongside the API. The single-page app falls back to `index.html` for unknown
routes (configure on your reverse proxy).