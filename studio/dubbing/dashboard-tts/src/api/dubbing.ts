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
  fetchClient: typeof fetch,
  file: File,
  meta?: { category?: string; entity?: string },
  signal?: AbortSignal
): Promise<{ id: string; status: DubJobStatus }> {
  const form = new FormData();
  form.append("file", file);
  // Pird: Optional category + entity so the downstream pipeline can
  // tailor translation (e.g. preserve "Ford F-150" as a brand). Both
  // are optional — backend falls back to "general" when missing.
  if (meta?.category) form.append("category", meta.category);
  if (meta?.entity) form.append("entity", meta.entity);
  
  const r = await fetchClient(`${API_BASE}/video/jobs`, { 
    method: "POST", 
    body: form,
    signal
  });
  return r.json();
}

export async function getDubStatus(fetchClient: typeof fetch, jobId: string, signal?: AbortSignal): Promise<DubJob> {
  const r = await fetchClient(`${API_BASE}/video/jobs/${jobId}`, { signal });
  return r.json();
}

export async function getDubJobs(fetchClient: typeof fetch, signal?: AbortSignal): Promise<DubJob[]> {
  const r = await fetchClient(`${API_BASE}/video/jobs`, { signal });
  return r.json();
}