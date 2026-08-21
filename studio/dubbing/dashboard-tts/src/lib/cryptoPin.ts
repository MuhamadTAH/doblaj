/**
 * cryptoPin.ts — Client-Side Zero-Trust Cryptographic PIN Hashing & Verification
 * Uses Web Crypto API SHA-256 with user-bound cryptographic salt.
 * Eliminates all hardcoded default PINs.
 */

function buf2hex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}

export function getOrCreateSalt(userId: string): string {
  const key = `admin_pin_salt_${userId || "default"}`;
  let salt = localStorage.getItem(key);
  if (!salt) {
    const array = new Uint8Array(16);
    window.crypto.getRandomValues(array);
    salt = buf2hex(array.buffer);
    localStorage.setItem(key, salt);
  }
  return salt;
}

export async function hashPinWithSalt(pin: string, salt: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(`PIRD_SHIELD_V1:${salt}:${pin}`);
  const hashBuffer = await window.crypto.subtle.digest("SHA-256", data);
  return buf2hex(hashBuffer);
}

export function isPinConfigured(userId: string): boolean {
  const key = `admin_pin_hash_${userId || "default"}`;
  return Boolean(localStorage.getItem(key));
}

export async function savePin(userId: string, pin: string): Promise<void> {
  if (pin.length < 6) {
    throw new Error("PIN must be at least 6 digits");
  }
  const salt = getOrCreateSalt(userId);
  const hash = await hashPinWithSalt(pin, salt);
  localStorage.setItem(`admin_pin_hash_${userId || "default"}`, hash);
  // Remove any legacy insecure keys
  localStorage.removeItem("admin_shield_pin");
}

export async function verifyPin(userId: string, pin: string): Promise<boolean> {
  const key = `admin_pin_hash_${userId || "default"}`;
  const storedHash = localStorage.getItem(key);
  if (!storedHash) return false;

  const salt = getOrCreateSalt(userId);
  const computedHash = await hashPinWithSalt(pin, salt);
  return computedHash === storedHash;
}

export function clearPin(userId: string): void {
  localStorage.removeItem(`admin_pin_hash_${userId || "default"}`);
  localStorage.removeItem(`admin_pin_salt_${userId || "default"}`);
}
