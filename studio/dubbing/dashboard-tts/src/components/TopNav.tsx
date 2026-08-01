import { useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { t } from "@/lib/i18n";
import { useUiStore } from "@/store/ui";

type RouteTitle = { titleKey: string; subKey?: string; titleFallback: string; subFallback?: string };

const titles: Record<string, RouteTitle> = {
  "/": {
    titleKey: "generate_page_title",
    subKey: "nav_text_to_speech_sub",
    titleFallback: "Text to Speech",
    subFallback: "Turn text into natural speech",
  },
  "/dubbing": {
    titleKey: "nav_video_dubbing",
    subKey: "nav_video_dubbing_sub",
    titleFallback: "Video Dubbing",
    subFallback: "Translate and re-voice your videos into any language",
  },
  "/voices": {
    titleKey: "nav_voice_library",
    subKey: "nav_voice_library_sub",
    titleFallback: "Voice Library",
    subFallback: "Browse and preview all available voices",
  },
  "/history": {
    titleKey: "nav_history",
    subKey: "nav_history_sub",
    titleFallback: "History",
    subFallback: "Everything you've generated, with playback",
  },
};

export default function TopNav() {
  const { pathname } = useLocation();
  const meta = titles[pathname] ?? titles["/"];
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  return (
    <header className="h-16 sticky top-0 z-40 flex items-center justify-between px-6 border-b border-white/[0.06] dark:border-white/[0.06] bg-ink-950/70 dark:bg-ink-950/70 backdrop-blur-xl">
      <div className="flex items-center gap-3 min-w-0">
        <motion.button
          onClick={toggleSidebar}
          whileTap={{ scale: 0.92 }}
          aria-label={t("topnav_toggle_sidebar", "Toggle sidebar")}
          title={t("topnav_toggle_sidebar", "Toggle sidebar")}
          className="w-9 h-9 rounded-md hover:bg-white/[0.04] flex items-center justify-center text-ink-300 cursor-pointer transition-colors"
        >
          {/* Pird: morphs hamburger ↔ chevron to reflect open state. */}
          <AnimatePresence mode="wait" initial={false}>
            {sidebarOpen ? (
              <motion.svg
                key="open"
                viewBox="0 0 24 24"
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ rotate: -90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: 90, opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                <path d="M11 4 L4 12 L11 20" />
                <path d="M20 4 L13 12 L20 20" />
              </motion.svg>
            ) : (
              <motion.svg
                key="closed"
                viewBox="0 0 24 24"
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ rotate: -90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: 90, opacity: 0 }}
                transition={{ duration: 0.2 }}
              >
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </motion.svg>
            )}
          </AnimatePresence>
        </motion.button>
        <div className="min-w-0">
          <div className="text-white dark:text-white text-sm font-semibold leading-none">{t(meta.titleKey, meta.titleFallback)}</div>
          {meta.subKey && (
            <div className="text-xs text-ink-400 mt-0.5 truncate">{t(meta.subKey, meta.subFallback ?? "")}</div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Pird: theme toggle. Sun in light mode, moon in dark mode, with
            a rotate+scale morph between clicks. */}
        <IconButton
          title={theme === "dark" ? t("topnav_toggle_theme", "Toggle theme") : t("topnav_toggle_theme", "Toggle theme")}
          active={theme === "light"}
          onClick={toggleTheme}
        >
          <AnimatePresence mode="wait" initial={false}>
            {theme === "dark" ? (
              <motion.svg
                key="moon"
                viewBox="0 0 24 24"
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ rotate: -90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: 90, opacity: 0 }}
                transition={{ duration: 0.25 }}
              >
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </motion.svg>
            ) : (
              <motion.svg
                key="sun"
                viewBox="0 0 24 24"
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ rotate: 90, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                exit={{ rotate: -90, opacity: 0 }}
                transition={{ duration: 0.25 }}
              >
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2" /><path d="M12 20v2" /><path d="M4.93 4.93l1.41 1.41" />
                <path d="M17.66 17.66l1.41 1.41" /><path d="M2 12h2" /><path d="M20 12h2" />
                <path d="M4.93 19.07l1.41-1.41" /><path d="M17.66 6.34l1.41-1.41" />
              </motion.svg>
            )}
          </AnimatePresence>
        </IconButton>
        <IconButton title={t("topnav_docs", "Docs")}>
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
          </svg>
        </IconButton>
        <IconButton title={t("topnav_discord", "Discord")}>
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="currentColor">
            <path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"/>
          </svg>
        </IconButton>
        <IconButton title={t("topnav_support", "Support")}>
          <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1v-6h3v4zM3 19a2 2 0 0 0 2 2h1v-6H3v4z"/>
          </svg>
        </IconButton>

        <div className="ms-2 flex items-center gap-2 rounded-full ps-3 pe-1 py-1 bg-white/[0.04] dark:bg-white/[0.04] border border-white/[0.06] dark:border-white/[0.06] hover:bg-white/[0.06] transition-colors cursor-pointer">
          <span className="text-xs text-white dark:text-white font-medium">{t("topnav_team_label", "Pird Team")}</span>
          <span className="text-[10px] font-semibold bg-white/[0.06] text-ink-300 px-2 py-0.5 rounded-full">{t("topnav_plan_free", "Free")}</span>
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-400 to-accent-500 text-white text-xs font-bold flex items-center justify-center">P</div>
        </div>
      </div>
    </header>
  );
}

function IconButton({
  children,
  title,
  onClick,
  active,
}: {
  children: React.ReactNode;
  title: string;
  onClick?: () => void;
  active?: boolean;
}) {
  return (
    <motion.button
      onClick={onClick}
      title={title}
      whileTap={{ scale: 0.92 }}
      className={`w-9 h-9 rounded-full border flex items-center justify-center transition-all ${
        active
          ? "bg-brand-400/20 text-brand-300 border-brand-400/30"
          : "bg-white/[0.04] border-white/[0.06] text-ink-300 hover:text-white hover:bg-white/[0.07]"
      }`}
    >
      {children}
    </motion.button>
  );
}