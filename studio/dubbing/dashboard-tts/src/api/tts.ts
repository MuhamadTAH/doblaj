// API layer for Pird TTS.
// In production, the FastAPI backend (tts-service_old) is a thin proxy to Fish Audio.
// In dev, when the backend isn't running, the fetch helper falls back to a silent
// WAV so the UI flow still demos.

// Pird: when deployed to CF Pages (doblaj.com) the API lives at api.doblaj.com,
// not on the same origin. VITE_API_BASE_URL is set in the Pages dashboard and
// injected at build time. Empty in dev -> fetch uses a relative path so Vite's
// proxy in vite.config.ts can forward /api and /video to localhost:8002.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export type TtsRequest = {
  text: string;
  voice_id: string;
  language: string;
  speed?: number;
  pitch?: number;
};

export type TtsHistoryItem = {
  id: string;
  text: string;
  voice_id: string;
  voice_name: string;
  language: string;
  created_at: string; // ISO
  duration_ms: number;
  blob_url: string; // object URL
  size_bytes: number;
};

/**
 * Build a silent WAV blob in the browser. Used as a fallback when the backend
 * is unreachable so the UI flow still demos end-to-end with no server.
 */
function makeSilentWav(durationSeconds = 1, sampleRate = 8000): Blob {
  const numSamples = Math.floor(durationSeconds * sampleRate);
  const blockAlign = 2; // 16-bit mono
  const byteRate = sampleRate * blockAlign;
  const dataSize = numSamples * blockAlign;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  return new Blob([buffer], { type: "audio/wav" });
}

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
}

export type Voice = {
  id: string;
  name: string;
  language: string;
  gender: "male" | "female" | "neutral";
  description?: string;
  tags: string[];
  is_yours?: boolean;
  // Optional fields populated when the backend response is shaped from Supabase
  provider?: string;
  provider_checkpoint?: string;
  status?: string;
  voice_type?: string;
};

/**
 * Fetch all available voices from the backend.
 * The backend reads them from the Supabase `voices` table.
 * Endpoint: /api/tts-dashboard/voices (merged from tts-service_old;
 * /api/voices is a legacy stub in dubbing with a different shape).
 */
export async function fetchVoices(): Promise<Voice[]> {
  try {
    const res = await fetch(`${API_BASE}/api/tts-dashboard/voices`);
    if (!res.ok) throw new Error(`voices: ${res.status}`);
    const data: Voice[] = await res.json();
    if (!Array.isArray(data)) return [];
    // Hardening: defend against partial / shape-mismatched rows so a stray
    // null doesn't crash the React tree on `.slice` (Rule: fail loud at the
    // edge, render empty gracefully).
    return data
      .filter((v): v is Voice => v != null && typeof v === "object" && typeof v.id === "string")
      .map((v) => ({
        id: v.id,
        name: v.name ?? "Unnamed Voice",
        language: v.language ?? "ar",
        gender: v.gender ?? "neutral",
        description: v.description ?? "",
        tags: Array.isArray(v.tags) ? v.tags : [],
        is_yours: !!v.is_yours,
        provider: v.provider,
        provider_checkpoint: v.provider_checkpoint ?? "",
        status: v.status,
        voice_type: v.voice_type,
      }));
  } catch (err) {
    console.warn("Voices fetch failed, returning empty list", err);
    return [];
  }
}

/**
 * Real TTS call. Streams a Blob (mp3) from the backend, which proxies Fish Audio.
 * Falls back to a silent WAV if the backend is unreachable.
 */
export async function generateTts(req: TtsRequest): Promise<Blob> {
  try {
    const res = await fetch(`${API_BASE}/api/tts-dashboard/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error(`TTS backend returned ${res.status}`);
    return await res.blob();
  } catch (err) {
    console.warn("TTS fetch failed, returning silent fallback", err);
    const seconds = Math.max(1, Math.min(8, Math.round(req.text.length / 20)));
    return makeSilentWav(seconds);
  }
}

const previewCache = new Map<string, { blob: Blob; url: string; isMock: boolean }>();

/**
 * Fetch a short audio preview for a voice (mp3 from Fish Audio).
 * Returns a Blob URL the GlobalPlayer can consume.
 * Falls back to a silent WAV if the backend is unreachable.
 */
export async function previewVoice(voiceId: string): Promise<{ blob: Blob; url: string; isMock: boolean }> {
  if (previewCache.has(voiceId)) {
    return previewCache.get(voiceId)!;
  }

  try {
    const res = await fetch(`${API_BASE}/api/tts-dashboard/voices/${encodeURIComponent(voiceId)}/preview`);
    if (!res.ok) throw new Error(`preview: ${res.status}`);
    const blob = await res.blob();
    const result = { blob, url: URL.createObjectURL(blob), isMock: false };
    previewCache.set(voiceId, result);
    return result;
  } catch (err) {
    console.warn("Preview failed, returning silent fallback", err);
    const blob = makeSilentWav(1.4);
    return { blob, url: URL.createObjectURL(blob), isMock: true };
  }
}