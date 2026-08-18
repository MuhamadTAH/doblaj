import { uploadInChunksWithProgress, uploadWithAuthProgress, type TokenGetter, type UploadProgressData } from "../lib/apiClient";

// Dubbing API client. Calls /video/* through FastAPI. FastAPI verifies
// the Clerk session cookie set by the shell, then proxies reads/writes
// to the Convex backend.

// Pird: see api/tts.ts API_BASE note. Same env var drives /video/* too.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

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

export type UploadProgressInfo = UploadProgressData;

export async function submitDubJobWithProgress(
  getToken: TokenGetter,
  file: File,
  meta?: { category?: string; entity?: string; consent_text_version?: string },
  onProgress?: (progress: UploadProgressInfo) => void,
  signal?: AbortSignal
): Promise<{ id: string; status: DubJobStatus }> {
  // Use robust 20MB chunked upload. Completely avoids 100MB Cloudflare proxy limits and R2 CORS preflights.
  try {
    return await uploadInChunksWithProgress<{ id: string; status: DubJobStatus }>(
      getToken,
      API_BASE,
      file,
      meta,
      onProgress,
      signal
    );
  } catch (err: any) {
    // If chunked fails for small files, try standard fallback
    if (file.size <= 50 * 1024 * 1024) {
      console.warn("Chunked upload failed, falling back to standard upload:", err);
      const form = new FormData();
      form.append("file", file);
      if (meta?.category) form.append("category", meta.category);
      if (meta?.entity) form.append("entity", meta.entity);
      if (meta?.consent_text_version) form.append("consent_text_version", meta.consent_text_version);

      return uploadWithAuthProgress<{ id: string; status: DubJobStatus }>(
        getToken,
        `${API_BASE}/video/jobs`,
        form,
        onProgress,
        signal
      );
    }
    throw err;
  }
}



export async function submitDubJob(
  fetchClient: typeof fetch,
  file: File,
  meta?: { category?: string; entity?: string; consent_text_version?: string },
  signal?: AbortSignal
): Promise<{ id: string; status: DubJobStatus }> {
  const form = new FormData();
  form.append("file", file);
  if (meta?.category) form.append("category", meta.category);
  if (meta?.entity) form.append("entity", meta.entity);
  if (meta?.consent_text_version) form.append("consent_text_version", meta.consent_text_version);
  
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