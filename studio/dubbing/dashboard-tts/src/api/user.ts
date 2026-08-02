const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export async function deleteAccount(
  fetchClient: typeof fetch,
  password?: string,
  signal?: AbortSignal
): Promise<void> {
  const r = await fetchClient(`${API_BASE}/api/user/delete`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ password }),
    signal,
  });
  
  if (r.headers.get("content-type")?.includes("application/json")) {
    await r.json();
  }
}
