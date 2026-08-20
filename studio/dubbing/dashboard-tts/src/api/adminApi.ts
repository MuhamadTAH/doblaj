import { getDubbingApiToken, getApiBaseUrl, TokenGetter } from "../lib/apiClient";

export async function adminFetch(
  getToken: TokenGetter,
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = await getDubbingApiToken(getToken, false);
  const apiBase = getApiBaseUrl();
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${apiBase}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;

  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(url, { ...options, headers });
}

// -------------------------------------------------------------
// Admin Shield (Argon2id Server-Side Verification)
// -------------------------------------------------------------
export async function getShieldStatus(getToken: TokenGetter) {
  const res = await adminFetch(getToken, "/api/admin/shield/status", { method: "GET" });
  if (!res.ok) {
    throw new Error(`Shield status error: HTTP ${res.status}`);
  }
  return res.json();
}

export async function setupShieldPin(
  getToken: TokenGetter,
  pin: string,
  confirmPin: string
) {
  const res = await adminFetch(getToken, "/api/admin/shield/setup-pin", {
    method: "POST",
    body: JSON.stringify({ pin, confirm_pin: confirmPin }),
  });
  const data = await res.json().catch(() => ({ detail: `HTTP ${res.status} non-JSON response` }));
  if (!res.ok) {
    const errorMsg = data.detail || data.error || (typeof data === "object" ? JSON.stringify(data) : String(data));
    console.error("[SETUP-PIN-SERVER-ERROR]", res.status, data);
    throw new Error(`SETUP-PIN failed: ${errorMsg}`);
  }
  return data;
}

export async function verifyShieldPin(getToken: TokenGetter, pin: string) {
  const res = await adminFetch(getToken, "/api/admin/shield/verify-pin", {
    method: "POST",
    body: JSON.stringify({ pin }),
  });
  const data = await res.json();
  if (!res.ok) {
    const error: any = new Error(data.detail || `Verification failed (HTTP ${res.status})`);
    error.status = res.status;
    error.detail = data.detail;
    throw error;
  }
  return data;
}

// -------------------------------------------------------------
// Job Operations & DLQ
// -------------------------------------------------------------
export async function downloadJobSource(getToken: TokenGetter, jobId: string) {
  const res = await adminFetch(getToken, `/api/admin/jobs/${jobId}/source-download`, {
    method: "GET",
  });
  return res.json();
}

export async function retryJob(
  getToken: TokenGetter,
  jobId: string,
  overrideParams?: any
) {
  const res = await adminFetch(getToken, `/api/admin/jobs/${jobId}/retry`, {
    method: "POST",
    body: JSON.stringify({ override_params: overrideParams }),
  });
  return res.json();
}

export async function failJob(getToken: TokenGetter, jobId: string, reason?: string) {
  const res = await adminFetch(getToken, `/api/admin/jobs/${jobId}/fail`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  return res.json();
}

export async function nukeJob(
  getToken: TokenGetter,
  jobId: string,
  confirmText: string
) {
  const res = await adminFetch(getToken, `/api/admin/jobs/${jobId}/nuke`, {
    method: "POST",
    body: JSON.stringify({ confirm_text: confirmText }),
  });
  return res.json();
}

// -------------------------------------------------------------
// Approvals & Financial
// -------------------------------------------------------------
export async function approveAction(
  getToken: TokenGetter,
  approvalId: string,
  reason?: string
) {
  const res = await adminFetch(getToken, `/api/admin/approvals/${approvalId}/approve`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  return res.json();
}

export async function rejectAction(
  getToken: TokenGetter,
  approvalId: string,
  reason?: string
) {
  const res = await adminFetch(getToken, `/api/admin/approvals/${approvalId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  return res.json();
}

export async function requestRefund(
  getToken: TokenGetter,
  txId: string,
  amountUsd: number,
  reason?: string
) {
  const res = await adminFetch(getToken, `/api/admin/refunds/${txId}`, {
    method: "POST",
    body: JSON.stringify({ amount_usd: amountUsd, reason }),
  });
  return res.json();
}

// -------------------------------------------------------------
// System Configs & Feature Flags
// -------------------------------------------------------------
export async function toggleFeatureFlag(
  getToken: TokenGetter,
  flagKey: string,
  isActive: boolean,
  reason?: string
) {
  const res = await adminFetch(getToken, `/api/admin/flags/${flagKey}/toggle`, {
    method: "POST",
    body: JSON.stringify({ is_active: isActive, reason }),
  });
  return res.json();
}

export async function assignUserRole(
  getToken: TokenGetter,
  userId: string,
  roleName: string,
  permissions: string[]
) {
  const res = await adminFetch(getToken, "/api/admin/roles/assign", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, role_name: roleName, permissions }),
  });
  return res.json();
}

// -------------------------------------------------------------
// Telegram Command Center
// -------------------------------------------------------------
export async function sendTelegramBroadcast(getToken: TokenGetter, message: string) {
  const res = await adminFetch(getToken, "/api/admin/telegram/send", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
  return res.json();
}

export async function takeoverTelegram(
  getToken: TokenGetter,
  pauseMinutes: number = 60
) {
  const res = await adminFetch(getToken, "/api/admin/telegram/takeover", {
    method: "POST",
    body: JSON.stringify({ pause_duration_minutes: pauseMinutes }),
  });
  return res.json();
}

export async function resumeTelegram(getToken: TokenGetter) {
  const res = await adminFetch(getToken, "/api/admin/telegram/resume", {
    method: "POST",
    body: JSON.stringify({}),
  });
  return res.json();
}
