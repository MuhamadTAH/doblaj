import { AuthFailedError, AuthNetworkError, HttpError } from '../hooks/useApi';

export function getApiBaseUrl(): string {
  const envUrl = (import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE || "") as string;
  return envUrl.trim().replace(/\/$/, "");
}

export const API_BASE = getApiBaseUrl();

export interface TokenGetter {
  (options?: { template?: string; skipCache?: boolean }): Promise<string | null>;
}

let refreshTokenPromise: Promise<string | null> | null = null;

export async function getDubbingApiToken(getToken: TokenGetter, forceRefresh = false): Promise<string> {
  // Single-flight: always coalesce onto an in-flight refresh, including the
  // retry path after a 401. Without this, N concurrent 401s each call
  // getToken({ skipCache: true }) and N parallel refreshes hit Clerk.
  if (refreshTokenPromise) {
    const token = await refreshTokenPromise;
    if (token) return token;
  }

  refreshTokenPromise = (async () => {
    try {
      const token = await getToken({ template: "dubbing-api", skipCache: forceRefresh });
      return token;
    } catch (sdkError: any) {
      console.error("Clerk getToken error for template 'dubbing-api':", sdkError);
      const errorStr = String(sdkError).toLowerCase();
      if (errorStr.includes('401') || sdkError?.status === 401) {
        handleAuthFailure();
        throw new AuthFailedError();
      }
      throw new AuthNetworkError();
    } finally {
      setTimeout(() => {
        refreshTokenPromise = null;
      }, 50);
    }
  })();

  const token = await refreshTokenPromise;
  if (!token) {
    handleAuthFailure();
    throw new AuthFailedError("No valid token returned for template 'dubbing-api'");
  }
  return token;
}

export async function secureAuthFetch(
  getToken: TokenGetter,
  url: string | URL | Request,
  options: RequestInit = {}
): Promise<Response> {
  let token = await getDubbingApiToken(getToken, false);

  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token}`);

  let res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    console.warn("Received 401 from FastAPI, attempting synchronized token refresh...");
    try {
      token = await getDubbingApiToken(getToken, true);
      headers.set("Authorization", `Bearer ${token}`);
      res = await fetch(url, { ...options, headers });
    } catch (err) {
      console.error("Synchronized token refresh failed:", err);
      handleAuthFailure();
      throw new AuthFailedError();
    }
  }

  if (res.status === 401) {
    try {
      const errorText = await res.clone().text();
      console.error(`Auth failed with 401 after retry. Backend response: ${errorText}`);
    } catch {
      console.error('Auth failed with 401 after retry.');
    }
    handleAuthFailure();
    throw new AuthFailedError();
  }

  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const errorData = await res.json();
      errorDetail = errorData.detail || errorDetail;
    } catch {
      // Ignore JSON parse errors
    }
    throw new HttpError(res.status, errorDetail);
  }

  return res;
}

export interface UploadProgressData {
  loadedBytes: number;
  totalBytes: number;
  percent: number;
  loadedMB: string;
  totalMB: string;
  remainMB: string;
  speedMBs: string;
  etaFormatted: string;
}

export function handleAuthFailure() {
  if (
    typeof window !== 'undefined' &&
    !window.location.pathname.startsWith('/sign-in') &&
    !window.location.pathname.startsWith('/sign-up')
  ) {
    console.warn('[AUTH] Session expired or invalid token. Redirecting to sign-in...');
    const currentPath = window.location.pathname + window.location.search;
    window.location.href = `/sign-in?redirect_url=${encodeURIComponent(currentPath)}`;
  }
}

export async function uploadWithAuthProgress<T = any>(
  getToken: TokenGetter,
  url: string,
  formData: FormData,
  onProgress?: (data: UploadProgressData) => void,
  signal?: AbortSignal
): Promise<T> {
  let token = await getDubbingApiToken(getToken, false);

  return new Promise<T>((resolve, reject) => {
    const executeUpload = (authToken: string, isRetry = false) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url, true);
      xhr.withCredentials = true;
      xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);

      if (signal) {
        signal.addEventListener("abort", () => xhr.abort());
      }

      const startTime = Date.now();

      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable && e.total > 0) {
            const loadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
            const totalMB = (e.total / (1024 * 1024)).toFixed(1);
            const remainMB = Math.max(0, (e.total - e.loaded) / (1024 * 1024)).toFixed(1);
            const percent = Math.min(100, Math.round((e.loaded / e.total) * 100));

            const elapsedSec = (Date.now() - startTime) / 1000;
            let speedMBs = "0.0";
            let etaFormatted = "--";

            if (elapsedSec > 0.3 && e.loaded > 0) {
              const bytesPerSec = e.loaded / elapsedSec;
              const mbPerSec = bytesPerSec / (1024 * 1024);
              speedMBs = mbPerSec.toFixed(1);

              const remainingBytes = e.total - e.loaded;
              if (remainingBytes > 0 && bytesPerSec > 0) {
                const etaSec = Math.round(remainingBytes / bytesPerSec);
                if (etaSec < 60) {
                  etaFormatted = `${etaSec}s`;
                } else {
                  const m = Math.floor(etaSec / 60);
                  const s = etaSec % 60;
                  etaFormatted = `${m}m ${s < 10 ? "0" : ""}${s}s`;
                }
              } else {
                etaFormatted = "0s";
              }
            }

            onProgress({
              loadedBytes: e.loaded,
              totalBytes: e.total,
              percent,
              loadedMB,
              totalMB,
              remainMB,
              speedMBs,
              etaFormatted,
            });
          }
        };
      }

      xhr.onload = async () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const res = JSON.parse(xhr.responseText);
            resolve(res);
          } catch {
            resolve(xhr.responseText as unknown as T);
          }
        } else if (xhr.status === 401 && !isRetry) {
          console.warn("Upload received 401, attempting synchronized token refresh...");
          try {
            const freshToken = await getDubbingApiToken(getToken, true);
            executeUpload(freshToken, true);
          } catch (err) {
            handleAuthFailure();
            reject(new AuthFailedError());
          }
        } else {
          if (xhr.status === 401) {
            handleAuthFailure();
            reject(new AuthFailedError());
            return;
          }
          let errorDetail = `Upload failed (${xhr.status})`;
          try {
            const errJson = JSON.parse(xhr.responseText);
            errorDetail = errJson.detail || errJson.message || errorDetail;
          } catch {
            if (xhr.responseText) {
              errorDetail = xhr.responseText.slice(0, 300);
            }
          }
          reject(new HttpError(xhr.status, errorDetail));
        }
      };

      xhr.onerror = () => {
        reject(new AuthNetworkError("Network request failed during video upload. Please check connection or file size limit."));
      };

      xhr.onabort = () => {
        reject(new Error("Upload aborted by user."));
      };

      xhr.send(formData);
    };

    executeUpload(token, false);
  });
}

export async function uploadDirectToPresignedUrl(
  uploadUrl: string,
  file: File,
  contentType = "video/mp4",
  onProgress?: (data: UploadProgressData) => void,
  signal?: AbortSignal
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl, true);
    xhr.setRequestHeader("Content-Type", contentType);

    if (signal) {
      signal.addEventListener("abort", () => xhr.abort());
    }

    const startTime = Date.now();

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) {
          const loadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
          const totalMB = (e.total / (1024 * 1024)).toFixed(1);
          const remainMB = Math.max(0, (e.total - e.loaded) / (1024 * 1024)).toFixed(1);
          const percent = Math.min(100, Math.round((e.loaded / e.total) * 100));

          const elapsedSec = (Date.now() - startTime) / 1000;
          let speedMBs = "0.0";
          let etaFormatted = "--";

          if (elapsedSec > 0.3 && e.loaded > 0) {
            const bytesPerSec = e.loaded / elapsedSec;
            const mbPerSec = bytesPerSec / (1024 * 1024);
            speedMBs = mbPerSec.toFixed(1);

            const remainingBytes = e.total - e.loaded;
            if (remainingBytes > 0 && bytesPerSec > 0) {
              const etaSec = Math.round(remainingBytes / bytesPerSec);
              if (etaSec < 60) {
                etaFormatted = `${etaSec}s`;
              } else {
                const m = Math.floor(etaSec / 60);
                const s = etaSec % 60;
                etaFormatted = `${m}m ${s < 10 ? "0" : ""}${s}s`;
              }
            } else {
              etaFormatted = "0s";
            }
          }

          onProgress({
            loadedBytes: e.loaded,
            totalBytes: e.total,
            percent,
            loadedMB,
            totalMB,
            remainMB,
            speedMBs,
            etaFormatted,
          });
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new HttpError(xhr.status, `Storage upload failed with HTTP ${xhr.status}`));
      }
    };

    xhr.onerror = () => {
      reject(new AuthNetworkError("Network request failed during direct upload to storage."));
    };

    xhr.onabort = () => {
      reject(new Error("Upload aborted."));
    };

    xhr.send(file);
  });
}

export async function uploadInChunksWithProgress<T = any>(
  getToken: TokenGetter,
  apiBase: string,
  file: File,
  meta?: { category?: string; entity?: string; consent_text_version?: string },
  onProgress?: (data: UploadProgressData) => void,
  signal?: AbortSignal
): Promise<T> {
  let token = await getDubbingApiToken(getToken, false);
  const CHUNK_SIZE = 20 * 1024 * 1024; // 20 MB chunks
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  // Helper for JSON endpoints in chunked flow with 401 retry
  const postJsonWithAuthRetry = async (url: string, payload: any): Promise<Response> => {
    let res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
      signal,
    });

    if (res.status === 401) {
      console.warn(`401 on ${url}, attempting synchronized token refresh...`);
      try {
        token = await getDubbingApiToken(getToken, true);
        res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(payload),
          signal,
        });
      } catch (err) {
        handleAuthFailure();
        throw new AuthFailedError();
      }
    }

    if (res.status === 401) {
      handleAuthFailure();
      throw new AuthFailedError();
    }

    return res;
  };

  // 1. Initialize Chunked Job
  const initRes = await postJsonWithAuthRetry(`${apiBase}/video/jobs/chunked/init`, {
    filename: file.name,
    total_bytes: file.size,
    total_chunks: totalChunks,
    category: meta?.category,
    entity: meta?.entity,
    consent_text_version: meta?.consent_text_version,
  });

  if (!initRes.ok) {
    const errText = await initRes.text();
    let detail = `Failed to initialize upload (${initRes.status})`;
    try {
      const j = JSON.parse(errText);
      detail = j.detail || detail;
    } catch {}
    throw new HttpError(initRes.status, detail);
  }

  const { job_id, chunk_size_bytes } = await initRes.json();
  const effectiveChunkSize = chunk_size_bytes || CHUNK_SIZE;
  const startTime = Date.now();
  let uploadedBytesBeforeCurrentChunk = 0;

  // 2. Upload each chunk sequentially with granular progress & 401 retry
  for (let chunkIdx = 0; chunkIdx < totalChunks; chunkIdx++) {
    if (signal?.aborted) {
      throw new Error("Upload aborted by user.");
    }

    const startByte = chunkIdx * effectiveChunkSize;
    const endByte = Math.min(file.size, startByte + effectiveChunkSize);
    const chunkBlob = file.slice(startByte, endByte);

    await new Promise<void>((resolve, reject) => {
      const sendChunk = (authToken: string, isRetry = false) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${apiBase}/video/jobs/chunked/upload`, true);
        xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);

        if (signal) {
          signal.addEventListener("abort", () => xhr.abort());
        }

        if (xhr.upload && onProgress) {
          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
              const currentTotalLoaded = uploadedBytesBeforeCurrentChunk + e.loaded;
              const loadedMB = (currentTotalLoaded / (1024 * 1024)).toFixed(1);
              const totalMB = (file.size / (1024 * 1024)).toFixed(1);
              const remainMB = Math.max(0, (file.size - currentTotalLoaded) / (1024 * 1024)).toFixed(1);
              const percent = Math.min(100, Math.round((currentTotalLoaded / file.size) * 100));

              const elapsedSec = (Date.now() - startTime) / 1000;
              let speedMBs = "0.0";
              let etaFormatted = "--";

              if (elapsedSec > 0.3 && currentTotalLoaded > 0) {
                const bytesPerSec = currentTotalLoaded / elapsedSec;
                const mbPerSec = bytesPerSec / (1024 * 1024);
                speedMBs = mbPerSec.toFixed(1);

                const remainingBytes = file.size - currentTotalLoaded;
                if (remainingBytes > 0 && bytesPerSec > 0) {
                  const etaSec = Math.round(remainingBytes / bytesPerSec);
                  if (etaSec < 60) {
                    etaFormatted = `${etaSec}s`;
                  } else {
                    const m = Math.floor(etaSec / 60);
                    const s = etaSec % 60;
                    etaFormatted = `${m}m ${s < 10 ? "0" : ""}${s}s`;
                  }
                } else {
                  etaFormatted = "0s";
                }
              }

              onProgress({
                loadedBytes: currentTotalLoaded,
                totalBytes: file.size,
                percent,
                loadedMB,
                totalMB,
                remainMB,
                speedMBs,
                etaFormatted,
              });
            }
          };
        }

        xhr.onload = async () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            uploadedBytesBeforeCurrentChunk += chunkBlob.size;
            resolve();
          } else if (xhr.status === 401 && !isRetry) {
            console.warn(`Chunk ${chunkIdx + 1} got 401, refreshing token and retrying...`);
            try {
              token = await getDubbingApiToken(getToken, true);
              sendChunk(token, true);
            } catch (err) {
              handleAuthFailure();
              reject(new AuthFailedError());
            }
          } else {
            if (xhr.status === 401) {
              handleAuthFailure();
              reject(new AuthFailedError());
              return;
            }
            let errDetail = `Chunk ${chunkIdx + 1}/${totalChunks} upload failed (${xhr.status})`;
            try {
              const errJson = JSON.parse(xhr.responseText);
              errDetail = errJson.detail || errDetail;
            } catch {}
            reject(new HttpError(xhr.status, errDetail));
          }
        };

        xhr.onerror = () => {
          reject(new AuthNetworkError(`Network error on chunk ${chunkIdx + 1}/${totalChunks}.`));
        };

        xhr.onabort = () => {
          reject(new Error("Upload aborted by user."));
        };

        const chunkForm = new FormData();
        chunkForm.append("job_id", job_id);
        chunkForm.append("chunk_index", String(chunkIdx));
        chunkForm.append("chunk_file", chunkBlob, file.name);

        xhr.send(chunkForm);
      };

      sendChunk(token, false);
    });
  }

  // 3. Complete chunked job
  const compRes = await postJsonWithAuthRetry(`${apiBase}/video/jobs/chunked/complete`, {
    job_id,
    filename: file.name,
    category: meta?.category,
    entity: meta?.entity,
    consent_text_version: meta?.consent_text_version,
  });

  if (!compRes.ok) {
    const errText = await compRes.text();
    let detail = `Failed to finalize chunked video (${compRes.status})`;
    try {
      const j = JSON.parse(errText);
      detail = j.detail || detail;
    } catch {}
    throw new HttpError(compRes.status, detail);
  }

  return (await compRes.json()) as T;
}



