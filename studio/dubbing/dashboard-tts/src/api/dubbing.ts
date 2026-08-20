import { 
  uploadDirectToR2, 
  uploadInChunksWithProgress, 
  uploadWithAuthProgress, 
  getApiBaseUrl, 
  postJsonWithAuthRetry, 
  type TokenGetter, 
  type UploadProgressData 
} from "../lib/apiClient";

const API_BASE = getApiBaseUrl();

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

export interface JobInitResponse {
  job_id: string;
  upload_url: string;
  key: string;
  max_bytes?: number;
}

/**
 * Node 1: Pre-Signed Direct Cloudflare R2 Ingestion.
 * 1. Asks FastAPI to validate credits and generate a pre-signed PUT URL.
 * 2. Uploads 2GB file directly to R2 from the browser (bypasses server).
 * 3. Finalizes job registration and kicks off metadata extraction and processing.
 */
export async function submitDubJobDirectR2(
  getToken: TokenGetter,
  file: File,
  meta?: { category?: string; entity?: string; consent_text_version?: string },
  onProgress?: (progress: UploadProgressInfo) => void,
  signal?: AbortSignal
): Promise<{ id: string; status: DubJobStatus }> {
  // Step 1: Request pre-signed PUT URL from FastAPI
  const initRes = await postJsonWithAuthRetry(getToken, `${API_BASE}/video/jobs/init`, {
    filename: file.name,
    category: meta?.category,
    entity: meta?.entity,
    consent_text_version: meta?.consent_text_version,
  });

  if (!initRes.ok) {
    const err = await initRes.json().catch(() => ({ detail: "Failed to initialize upload session" }));
    throw new Error(err.detail || "Failed to initialize upload session");
  }

  const initData: JobInitResponse = await initRes.json();

  // Step 2: Direct browser PUT upload to Cloudflare R2
  await uploadDirectToR2(initData.upload_url, file, onProgress, signal);

  // Step 3: Finalize upload, extract FFprobe metadata, and start pipeline
  const finalRes = await postJsonWithAuthRetry(getToken, `${API_BASE}/video/jobs/${initData.job_id}/finalize-upload`, {
    category: meta?.category,
    entity: meta?.entity,
  });

  if (!finalRes.ok) {
    const err = await finalRes.json().catch(() => ({ detail: "Failed to finalize video job" }));
    throw new Error(err.detail || "Failed to finalize video job");
  }

  return { id: initData.job_id, status: "pending" };
}

export async function submitDubJobWithProgress(
  getToken: TokenGetter,
  file: File,
  meta?: { category?: string; entity?: string; consent_text_version?: string },
  onProgress?: (progress: UploadProgressInfo) => void,
  signal?: AbortSignal
): Promise<{ id: string; status: DubJobStatus }> {
  try {
    return await submitDubJobDirectR2(getToken, file, meta, onProgress, signal);
  } catch (err: any) {
    console.warn("Direct R2 upload fallback to chunked upload:", err);
    return await uploadInChunksWithProgress<{ id: string; status: DubJobStatus }>(
      getToken,
      API_BASE,
      file,
      meta,
      onProgress,
      signal
    );
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