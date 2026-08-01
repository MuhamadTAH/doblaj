/**
 * Pird i18n helper — Fix 3b
 *
 * Reads strings from window.__PIRD_CONFIG__.strings, which is injected by
 * FastAPI's `_inject_pird_config()` before the React bundle boots.
 *
 * Usage in any component:
 *   import { t, locale, dir } from "@/lib/i18n";
 *   <h1>{t("generate_page_title", "Text to Speech")}</h1>
 *
 * Key lookup order: every namespace in insertion order → fallback arg → key.
 * This mirrors the server-side `main.py:t()` function.
 */

declare global {
  interface Window {
    __PIRD_CONFIG__?: {
      locale?: string;
      dir?: "rtl" | "ltr";
      strings?: Record<string, Record<string, string>>;
    };
  }
}

const _cfg = window.__PIRD_CONFIG__ ?? {};

/**
 * Active locale, e.g. "ckb", "ar", "en". Defaults to "en".
 */
export const locale: string = _cfg.locale ?? "en";

/**
 * Active text direction, "rtl" or "ltr". Defaults to "ltr".
 */
export const dir: "rtl" | "ltr" = _cfg.dir ?? "ltr";

/**
 * Nested strings dict from the injected config.
 * Shape: { tts_dashboard: { key: value }, common: { key: value }, … }
 */
const _strings: Record<string, Record<string, string>> = _cfg.strings ?? {};

/**
 * Translate a key.
 * Searches every namespace (tts_dashboard, common, dubbing_page, …) in
 * insertion order, then falls back to the fallback argument, then the key.
 *
 * @param key      - The translation key, e.g. "generate_page_title"
 * @param fallback - English fallback shown when the key is not yet translated
 */
export function t(key: string, fallback = key): string {
  for (const ns of Object.values(_strings)) {
    if (ns && typeof ns === "object" && key in ns) return ns[key];
  }
  return fallback;
}
