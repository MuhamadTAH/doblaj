import { useCallback, useMemo } from 'react';
import { useAuth, useClerk } from '@clerk/clerk-react';
import { getDubJobs, getDubStatus, submitDubJob } from '../api/dubbing';
import { fetchVoices, generateTts, previewVoice, TtsRequest } from '../api/tts';
import { deleteAccount } from '../api/user';

export class AuthFailedError extends Error {
  constructor(message = "Authentication failed") {
    super(message);
    this.name = "AuthFailedError";
  }
}

export class AuthNetworkError extends Error {
  constructor(message = "Network error during authentication") {
    super(message);
    this.name = "AuthNetworkError";
  }
}

export class HttpError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "HttpError";
  }
}

let isSigningOut = false;

export const useApi = () => {
  const { getToken } = useAuth();
  const { signOut } = useClerk();

  const authFetch = useCallback(async (url: string | URL | globalThis.Request, options: RequestInit = {}): Promise<Response> => {
    let token: string | null = null;
    try {
      token = await getToken({ template: 'pird-dubbing' });
    } catch (sdkError: any) {
      console.error("Clerk getToken error:", sdkError);
      
      const errorStr = String(sdkError).toLowerCase();
      // Only sign out if it's explicitly an unauthorized (401) session error.
      // A 404 here usually means the JWT template 'pird-dubbing' is missing in the Clerk dashboard.
      if (errorStr.includes('401') || sdkError?.status === 401) {
        if (!isSigningOut) {
          isSigningOut = true;
          await signOut();
          isSigningOut = false;
        }
        throw new AuthFailedError();
      }
      throw new AuthNetworkError();
    }

    if (!token) {
      if (!isSigningOut) {
        isSigningOut = true;
        await signOut();
        isSigningOut = false;
      }
      throw new AuthFailedError();
    }

    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);
    
    // We do NOT set Content-Type here to preserve FormData boundaries if they exist.
    
    const res = await fetch(url, { ...options, headers });

    if (res.status === 401) {
      if (!isSigningOut) {
        isSigningOut = true;
        await signOut();
        isSigningOut = false;
      }
      throw new AuthFailedError();
    }

    if (!res.ok) {
      let errorDetail = res.statusText;
      try {
        const errorData = await res.json();
        errorDetail = errorData.detail || errorDetail;
      } catch {
        // Ignore parsing errors here, it's probably HTML
      }
      throw new HttpError(res.status, errorDetail);
    }

    return res;
  }, [getToken, signOut]);

  return useMemo(() => ({
    getDubJobs: (signal?: AbortSignal) => getDubJobs(authFetch, signal),
    getDubStatus: (jobId: string, signal?: AbortSignal) => getDubStatus(authFetch, jobId, signal),
    submitDubJob: (file: File, meta?: { category?: string; entity?: string; consent_text_version?: string }, signal?: AbortSignal) => submitDubJob(authFetch, file, meta, signal),
    fetchVoices: (signal?: AbortSignal) => fetchVoices(authFetch, signal),
    generateTts: (req: TtsRequest, signal?: AbortSignal) => generateTts(authFetch, req, signal),
    previewVoice: (voiceId: string, signal?: AbortSignal) => previewVoice(authFetch, voiceId, signal),
    deleteAccount: (password: string, signal?: AbortSignal) => deleteAccount(authFetch, password, signal),
  }), [authFetch]);
};
