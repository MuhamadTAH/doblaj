import { AuthFailedError, AuthNetworkError, HttpError } from '../hooks/useApi';

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

export async function uploadWithAuthProgress<T = any>(
  getToken: TokenGetter,
  url: string,
  formData: FormData,
  onProgress?: (data: UploadProgressData) => void,
  signal?: AbortSignal
): Promise<T> {
  let token = await getDubbingApiToken(getToken, false);

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);

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
        try {
          const res = JSON.parse(xhr.responseText);
          resolve(res);
        } catch {
          resolve(xhr.responseText as unknown as T);
        }
      } else {
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
  });
}

