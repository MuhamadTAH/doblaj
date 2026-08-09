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
