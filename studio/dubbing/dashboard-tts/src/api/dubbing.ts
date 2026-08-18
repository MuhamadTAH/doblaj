import { uploadWithAuthProgress, uploadDirectToPresignedUrl, getDubbingApiToken, type TokenGetter, type UploadProgressData } from "../lib/apiClient";

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
  try {
    const token = await getDubbingApiToken(getToken, false);

    // 1. Get direct R2 presigned PUT URL
    const initRes = await fetch(`${API_BASE}/video/jobs/upload-url`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        filename: file.name,
        category: meta?.category,
        entity: meta?.entity,
        consent_text_version: meta?.consent_text_version,
      }),
      signal,
    });

    if (initRes.ok) {
      const { job_id, upload_url } = await initRes.json();

      // 2. Direct upload to Cloudflare R2 (bypasses 100MB proxy body caps and socket stalls)
      await uploadDirectToPresignedUrl(
        upload_url,
        file,
        file.type || "video/mp4",
        onProgress,
        signal
      );

      // 3. Trigger processing on backend
      const startRes = await fetch(`${API_BASE}/video/jobs/${job_id}/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          category: meta?.category,
          entity: meta?.entity,
        }),
        signal,
      });

      if (!startRes.ok) {
        const err = await startRes.text();
        throw new Error(`Failed to start job: ${err}`);
      }

      return { id: job_id, status: "pending" };
    }
  } catch (err) {
    console.warn("Direct R2 upload initiation failed, attempting multipart fallback:", err);
  }

  // Fallback: Standard multipart upload to FastAPI
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