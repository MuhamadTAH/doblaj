import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "dark" | "light";

type UiState = {
  /** Sidebar collapse state. true = expanded (default), false = icon rail. */
  sidebarOpen: boolean;
  /** Color scheme. "dark" is the default since the rest of the UI was built dark-first. */
  theme: Theme;
  /** Actions */
  toggleSidebar: () => void;
  setSidebarOpen: (v: boolean) => void;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      theme: "dark",

      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setSidebarOpen: (v) => set({ sidebarOpen: v }),
      toggleTheme: () =>
        set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setTheme: (t) => set({ theme: t }),
    }),
    {
      name: "pird.ui",
      // Only persist user-visible settings; never persist runtime state.
      partialize: (s) => ({ sidebarOpen: s.sidebarOpen, theme: s.theme }),
    },
  ),
);
