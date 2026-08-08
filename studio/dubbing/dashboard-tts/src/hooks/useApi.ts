import { useCallback, useMemo } from 'react';
import { useAuth } from '@clerk/clerk-react';
import { getDubJobs, getDubStatus, submitDubJob } from '../api/dubbing';
import { fetchVoices, generateTts, previewVoice, TtsRequest } from '../api/tts';
import { deleteAccount } from '../api/user';
import { getTelegramLinkNonce } from '../api/telegram';
import { secureAuthFetch } from '../lib/apiClient';

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

export const useApi = () => {
  const { getToken } = useAuth();

  const authFetch = useCallback(async (url: string | URL | globalThis.Request, options: RequestInit = {}): Promise<Response> => {
    return secureAuthFetch(getToken, url, options);
  }, [getToken]);

  return useMemo(() => ({
    getDubJobs: (signal?: AbortSignal) => getDubJobs(authFetch, signal),
    getDubStatus: (jobId: string, signal?: AbortSignal) => getDubStatus(authFetch, jobId, signal),
    submitDubJob: (file: File, meta?: { category?: string; entity?: string; consent_text_version?: string }, signal?: AbortSignal) => submitDubJob(authFetch, file, meta, signal),
    fetchVoices: (signal?: AbortSignal) => fetchVoices(authFetch, signal),
    generateTts: (req: TtsRequest, signal?: AbortSignal) => generateTts(authFetch, req, signal),
    previewVoice: (voiceId: string, signal?: AbortSignal) => previewVoice(authFetch, voiceId, signal),
    deleteAccount: (password: string, signal?: AbortSignal) => deleteAccount(authFetch, password, signal),
    getTelegramLinkNonce: (signal?: AbortSignal) => getTelegramLinkNonce(authFetch, signal),
  }), [authFetch]);
};
