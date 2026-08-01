import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { t } from "@/lib/i18n";
import { useUiStore } from "@/store/ui";

const items = [
  { to: "/", labelKey: "nav_text_to_speech", defaultLabel: "Text to Speech", icon: "wand" },
  { to: "/dubbing", labelKey: "nav_video_dubbing", defaultLabel: "Video Dubbing", icon: "video" },
  { to: "/voices", labelKey: "nav_voice_library", defaultLabel: "Voice Library", icon: "voices" },
  { to: "/history", labelKey: "nav_history", defaultLabel: "History", icon: "history" },
];

const platform = [
  { to: "/billing", labelKey: "nav_billing", defaultLabel: "Billing", icon: "card" },
  { to: "/pricing", labelKey: "nav_pricing", defaultLabel: "Pricing", icon: "grad" },
];

function Icon({ name }: { name: string }) {
  const cls = "w-4 h-4 shrink-0";
  switch (name) {
    case "wand":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8 19 13"/><path d="M15 9h0"/><path d="M17.8 6.2 19 5"/><path d="M3 21l9-9"/><path d="M12.2 6.2 11 5"/>
        </svg>
      );
    case "voices":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M11 5L6 9H2v6h4l5 4z"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
        </svg>
      );
    case "history":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>
        </svg>
      );
    case "video":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="23 7 16 12 23 17 23 7"/>
          <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
        </svg>
      );
    case "card":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/>
        </svg>
      );
    case "users":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
        </svg>
      );
    case "grad":
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 10v6"/><path d="M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>
        </svg>
      );
    default:
      return null;
  }
}

// Pird: morph between full (240 px) and rail (64 px). framer-motion handles
// the width/label transitions so the sidebar collapses smoothly into an
// icon-only vertical strip.
const EXPANDED = 240;
const COLLAPSED = 64;

export default function Sidebar() {
  const location = useLocation();
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const open = sidebarOpen;

  return (
    <motion.aside
      initial={false}
      animate={{ width: open ? EXPANDED : COLLAPSED }}
      transition={{ type: "spring", stiffness: 320, damping: 32, mass: 0.8 }}
      className="shrink-0 h-screen sticky top-0 border-e border-white/[0.06] dark:border-white/[0.06] flex flex-col bg-ink-900/40 dark:bg-ink-900/40 backdrop-blur-xl overflow-hidden"
    >
      {/* Logo */}
      <div className="h-16 flex items-center gap-2.5 px-5 border-b border-white/[0.06] dark:border-white/[0.06] whitespace-nowrap">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-400 to-accent-500 flex items-center justify-center shadow-glow shrink-0">
          <svg viewBox="0 0 24 24" className="w-4 h-4 text-white" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M3 12 Q6 8 9 12 T15 12 T21 12" />
          </svg>
        </div>
        <motion.span
          initial={false}
          animate={{ opacity: open ? 1 : 0, width: open ? "auto" : 0 }}
          transition={{ duration: 0.15 }}
          className="font-semibold text-white dark:text-white text-[15px] overflow-hidden"
        >
          {t("sidebar_brand", "Pird TTS")}
        </motion.span>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2">
        <motion.div
          initial={false}
          animate={{ opacity: open ? 1 : 0, height: open ? "auto" : 0 }}
          transition={{ duration: 0.15 }}
          className="px-3 pt-3 pb-1 text-[10px] uppercase tracking-wider text-ink-500 dark:text-ink-500 font-semibold overflow-hidden"
        >
          {t("sidebar_section_studio", "Studio")}
        </motion.div>
        <nav className="space-y-1">
          {items.map((it) => {
            const active = location.pathname === it.to;
            return (
              <NavLink
                key={it.to}
                to={it.to}
                className={`nav-item relative ${active ? "nav-item-active" : ""} justify-center`}
              >
                {active && (
                  <motion.span
                    layoutId="sidebar-active"
                    className="absolute start-0 top-1.5 bottom-1.5 w-0.5 rounded-e bg-gradient-to-b from-brand-400 to-accent-500"
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  />
                )}
                <Icon name={it.icon} />
                <motion.span
                  initial={false}
                  animate={{ opacity: open ? 1 : 0, width: open ? "auto" : 0 }}
                  transition={{ duration: 0.15 }}
                  className="overflow-hidden whitespace-nowrap"
                >
                  {t(it.labelKey, it.defaultLabel)}
                </motion.span>
              </NavLink>
            );
          })}
        </nav>

        <motion.div
          initial={false}
          animate={{ opacity: open ? 1 : 0, height: open ? "auto" : 0 }}
          transition={{ duration: 0.15 }}
          className="px-3 pt-5 pb-1 text-[10px] uppercase tracking-wider text-ink-500 dark:text-ink-500 font-semibold overflow-hidden"
        >
          {t("sidebar_section_platform", "Platform")}
        </motion.div>
        <nav className="space-y-1">
          {platform.map((it) => {
            const active = location.pathname === it.to;
            return (
              <NavLink 
                key={it.labelKey} 
                to={it.to} 
                className={`nav-item relative ${active ? "nav-item-active" : "opacity-70 hover:opacity-100"} justify-center`}
              >
                {active && (
                  <motion.span
                    layoutId="sidebar-active"
                    className="absolute start-0 top-1.5 bottom-1.5 w-0.5 rounded-e bg-gradient-to-b from-brand-400 to-accent-500"
                    transition={{ type: "spring", stiffness: 500, damping: 30 }}
                  />
                )}
                <Icon name={it.icon} />
                <motion.span
                  initial={false}
                  animate={{ opacity: open ? 1 : 0, width: open ? "auto" : 0 }}
                  transition={{ duration: 0.15 }}
                  className="overflow-hidden whitespace-nowrap"
                >
                  {t(it.labelKey, it.defaultLabel)}
                </motion.span>
              </NavLink>
            );
          })}
        </nav>
      </div>

      <div className="p-3 border-t border-white/[0.06] dark:border-white/[0.06]">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="w-full rounded-lg bg-gradient-to-b from-amber-200 to-amber-300 text-amber-900 text-sm font-semibold py-2 hover:from-amber-100 transition-colors"
        >
          {open ? (
            <>✦ {t("upgrade_pro", "Upgrade Pro")}</>
          ) : (
            <span className="inline-block">✦</span>
          )}
        </motion.button>
      </div>
    </motion.aside>
  );
}
