import { create } from "zustand";
import { persist, StateStorage, createJSONStorage } from "zustand/middleware";
import * as idb from "idb-keyval";
import type { TtsHistoryItem } from "@/api/tts";

type Playback = {
  id: string | null;
  url: string | null;
  isPlaying: boolean;
  currentTime: number;
  duration: number;
};

type TtsState = {
  // generation
  isGenerating: boolean;
  error: string | null;

  // history
  history: TtsHistoryItem[];

  // currently playing
  playback: Playback;

  // actions
  setGenerating: (v: boolean) => void;
  setError: (e: string | null) => void;
  addToHistory: (item: TtsHistoryItem) => void;
  removeFromHistory: (id: string) => void;
  clearHistory: () => void;
  setPlayback: (p: Partial<Playback>) => void;
  stopPlayback: () => void;
};

const idbStorage: StateStorage = {
  getItem: async (name: string): Promise<string | null> => {
    return (await idb.get(name)) || null;
  },
  setItem: async (name: string, value: string): Promise<void> => {
    await idb.set(name, value);
  },
  removeItem: async (name: string): Promise<void> => {
    await idb.del(name);
  },
};

export const useTtsStore = create<TtsState>()(
  persist(
    (set) => ({
      isGenerating: false,
      error: null,
      history: [],
      playback: { id: null, url: null, isPlaying: false, currentTime: 0, duration: 0 },

      setGenerating: (v) => set({ isGenerating: v, error: v ? null : (undefined as any) }),
      setError: (e) => set({ error: e }),
      addToHistory: (item) =>
        set((s) => ({
          history: [item, ...s.history.filter((h) => h.id !== item.id)].slice(0, 100),
        })),
      removeFromHistory: (id) =>
        set((s) => ({ history: s.history.filter((h) => h.id !== id) })),
      clearHistory: () => set({ history: [] }),

      setPlayback: (p) => set((s) => ({ playback: { ...s.playback, ...p } })),
      stopPlayback: () => set((s) => ({ playback: { ...s.playback, isPlaying: false } })),
    }),
    {
      name: "pird.tts.store",
      storage: createJSONStorage(() => idbStorage),
      partialize: (s) => ({ history: s.history }),
    }
  )
);