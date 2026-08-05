import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "dark" | "light";

export type AudioDefaults = {
  model: string;
  volume: number;
  speed: number;
  loudnessNorm: boolean;
  textNorm: boolean;
  tagCompat: boolean;
};

export type NotificationSettings = {
  notifyJobComplete: boolean;
  notifyLowCredits: boolean;
  telegramUpdates: boolean;
};

type UiState = {
  /** Sidebar collapse state. true = expanded (default), false = icon rail. */
  sidebarOpen: boolean;
  /** Color scheme. "dark" is the default since the rest of the UI was built dark-first. */
  theme: Theme;
  /** Default audio generation settings */
  audioDefaults: AudioDefaults;
  /** User notification preferences */
  notifications: NotificationSettings;

  /** Actions */
  toggleSidebar: () => void;
  setSidebarOpen: (v: boolean) => void;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
  setAudioDefaults: (defaults: Partial<AudioDefaults>) => void;
  setNotifications: (notifications: Partial<NotificationSettings>) => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      theme: "dark",
      audioDefaults: {
        model: "Fish Audio S2 Pro",
        volume: 0,
        speed: 1.0,
        loudnessNorm: true,
        textNorm: true,
        tagCompat: false,
      },
      notifications: {
        notifyJobComplete: true,
        notifyLowCredits: true,
        telegramUpdates: true,
      },

      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setSidebarOpen: (v) => set({ sidebarOpen: v }),
      toggleTheme: () =>
        set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setTheme: (t) => set({ theme: t }),
      setAudioDefaults: (defaults) =>
        set((s) => ({ audioDefaults: { ...s.audioDefaults, ...defaults } })),
      setNotifications: (notifications) =>
        set((s) => ({ notifications: { ...s.notifications, ...notifications } })),
    }),
    {
      name: "pird.ui",
      // Only persist user-visible settings; never persist runtime state.
      partialize: (s) => ({
        sidebarOpen: s.sidebarOpen,
        theme: s.theme,
        audioDefaults: s.audioDefaults,
        notifications: s.notifications,
      }),
    },
  ),
);

