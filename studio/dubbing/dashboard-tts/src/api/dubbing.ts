// Dubbing API client. Calls /video/* through FastAPI. FastAPI verifies
// the Clerk session cookie set by the shell, then proxies reads/writes
// to the Convex backend.

// Pird: see api/tts.ts API_BASE note. Same env var drives /video/* too.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export type DubJobStatus = "pending" | "processing" | "completed" | "failed";

export type DubJob = {
  id: string;
  status: DubJobStatus;
  progress: number;
  output_path?: string | null;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export async function submitDubJob(
  file: File,
  meta?: { category?: string; entity?: string },
): Promise<{ id: string; status: DubJobStatus }> {
  const form = new FormData();
  form.append("file", file);
  // Pird: optional category + entity so the downstream pipeline can
  // tailor translation (e.g. preserve "Ford F-150" as a brand). Both
  // are optional — backend falls back to "general" when missing.
  if (meta?.category) form.append("category", meta.category);
  if (meta?.entity) form.append("entity", meta.entity);
  // Pird: include dubbing_access_token cookie so the request isn't 401'd.
  // See handoffs/dubbing-security-pass2-fixes.md Fix 6.
  const r = await fetch(`${API_BASE}/video/jobs`, { method: "POST", body: form, credentials: "include" });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`dubbing submit -> ${r.status}: ${t.slice(0, 200)}`);
  }
  return r.json();
}

export async function getDubStatus(jobId: string): Promise<DubJob> {
  const r = await fetch(`${API_BASE}/video/jobs/${jobId}`, { credentials: "include" });
  if (!r.ok) throw new Error(`dubbing status -> ${r.status}`);
  return r.json();
}

export async function getDubJobs(): Promise<DubJob[]> {
  const r = await fetch(`${API_BASE}/video/jobs`, { credentials: "include" });
  if (!r.ok) throw new Error(`dubbing list -> ${r.status}`);
  return r.json();
}