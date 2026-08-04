const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export async function getTelegramLinkNonce(
  fetchClient: typeof fetch,
  signal?: AbortSignal
): Promise<{ nonce: string }> {
  const r = await fetchClient(`${API_BASE}/api/telegram/link-nonce`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
    signal,
  });
  
  return r.json();
}
