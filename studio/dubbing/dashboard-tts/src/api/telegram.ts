import { getApiBaseUrl } from "../lib/apiClient";

const API_BASE = getApiBaseUrl();

export async function getTelegramLinkNonce(
  fetchClient: typeof fetch,
  signal?: AbortSignal
): Promise<{ nonce: string }> {
  const r = await fetchClient(`${API_BASE}/api/telegram/link-nonce`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    signal,
  });
  
  return r.json();
}
