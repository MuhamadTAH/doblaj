import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import { useUiStore } from "./store/ui";

// Pird: Apply locale/dir injected by the FastAPI shell handler
// (`main.py::_serve_tts_shell` writes window.__PIRD_CONFIG__ before
// serving index.html). Must run BEFORE React mounts so the first paint
// already has correct dir/lang (no flash of LTR-then-RTL).
//
// Translation helper (Fix 3b) lives in @/lib/i18n — NOT here.
// Components import { t, locale, dir } from "@/lib/i18n" to avoid
// a circular dependency (main.tsx → App → components → main.tsx).
declare global {
  interface Window {
    __PIRD_CONFIG__?: {
      locale?: string;
      dir?: "rtl" | "ltr";
      strings?: Record<string, Record<string, string>>;
    };
  }
}
const pirdCfg = window.__PIRD_CONFIG__;
if (pirdCfg?.locale) {
  document.documentElement.lang = pirdCfg.locale;
}
if (pirdCfg?.dir) {
  document.documentElement.dir = pirdCfg.dir;
}

// Pird: apply persisted theme (default "dark") to <html> before React
// renders so Tailwind's `dark:` variant resolves correctly and there's
// no flash of unstyled content. Then subscribe so subsequent toggle clicks
// keep the class in sync.
const initialTheme = useUiStore.getState().theme;
document.documentElement.classList.toggle("dark", initialTheme === "dark");
useUiStore.subscribe((s) => {
  document.documentElement.classList.toggle("dark", s.theme === "dark");
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename="/tts">
      <App />
    </BrowserRouter>
  </React.StrictMode>
);