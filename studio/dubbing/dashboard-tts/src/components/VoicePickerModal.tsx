import { useState } from "react";
import Modal from "./Modal";
import type { Voice } from "@/api/tts";
import { t } from "@/lib/i18n";

type Props = {
  open: boolean;
  onClose: () => void;
  voices: Voice[];
  onPick: (voice: Voice) => void;
};

const getTabs = () => [
  { id: "recent",   label: t("voice_tab_recent",   "Recently Used") },
  { id: "explore",  label: t("voice_tab_explore",  "Explore") },
  { id: "default",  label: t("voice_tab_default",  "Default Voices") },
  { id: "mine",     label: t("voice_tab_mine",     "My Voices") },
  { id: "bookmark", label: t("voice_tab_bookmark", "Bookmarked") },
] as const;
type TabId = "recent" | "explore" | "default" | "mine" | "bookmark";

export default function VoicePickerModal({ open, onClose, voices, onPick }: Props) {
  const [tab, setTab] = useState<TabId>("recent");
  const [q, setQ] = useState("");
  const tabs = getTabs();

  // Tab -> which voices show
  const list = voices.filter((v) => {
    if (q) {
      const t = `${v.name} ${v.description} ${v.tags.join(" ")} ${v.language}`.toLowerCase();
      if (!t.includes(q.toLowerCase())) return false;
    }
    if (tab === "mine") return v.is_yours;
    if (tab === "default") return !v.is_yours;
    return true; // recent / explore / bookmark all show everything for now
  });

  return (
    <Modal open={open} onClose={onClose} title={t("select_voice_title", "Select Voice")} className="max-w-3xl">
      <div className="px-5 pt-3 pb-2 border-b border-white/[0.06] flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1 overflow-x-auto">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`min-w-[90px] px-3 py-1.5 text-sm rounded-md whitespace-nowrap transition-colors text-center ${
                tab === t.id
                  ? "bg-white/[0.06] text-white"
                  : "text-ink-400 hover:text-white hover:bg-white/[0.04]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button className="ms-auto px-3 py-1.5 text-sm rounded-md bg-white/[0.04] border border-white/[0.06] text-ink-200 hover:bg-white/[0.07] hover:border-white/[0.1] transition-colors inline-flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          {t("create_voice_collection", "Create Voice Collection")}
        </button>
      </div>

      <div className="px-5 py-3 border-b border-white/[0.06]">
        <div className="relative max-w-md">
          <svg viewBox="0 0 24 24" className="w-4 h-4 absolute start-3 top-1/2 -translate-y-1/2 text-ink-500" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("search_voices", "Search voices…")}
            className="input ps-9"
          />
        </div>
      </div>

      <div className="px-5 py-3 space-y-2 min-h-[320px]">
        {list.length === 0 ? (
          <div className="text-center py-12 text-ink-500 text-sm">{t("no_voices_match", "No voices match.")}</div>
        ) : (
          list.map((v) => <PickerRow key={v.id} voice={v} onPick={() => { onPick(v); onClose(); }} />)
        )}
      </div>
    </Modal>
  );
}

function PickerRow({ voice, onPick }: { voice: Voice; onPick: () => void }) {
  const isAr = voice.language.toLowerCase().includes("ar");
  const isCkb = voice.language.toLowerCase().includes("ckb") || voice.language.toLowerCase().includes("ku");
  const badgeClass = isCkb ? "badge-lang-ckb" : isAr ? "badge-lang-ar" : "bg-white/[0.04] text-ink-200 border border-white/[0.06]";

  return (
    <button
      onClick={onPick}
      aria-label={`Select voice ${voice.name}`}
      className="w-full text-start flex items-center gap-3 p-2.5 rounded-lg hover:bg-white/[0.04] border border-transparent hover:border-white/[0.06] transition-colors"
    >
      <div className="w-10 h-10 rounded-full bg-gradient-to-br from-brand-400/25 to-accent-500/25 flex items-center justify-center text-white font-semibold text-base border border-white/[0.08] shrink-0">
        {voice.name.slice(0, 1)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-white font-medium text-sm">{voice.name}</span>
          <span className="text-xs text-ink-400">· {voice.gender}</span>
        </div>
        <div className="text-xs text-ink-400 mt-0.5 truncate">{voice.description}</div>
        <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
          <span className={`chip ${badgeClass}`}>
            {voice.language}
          </span>
          {voice.tags.slice(0, 2).map((t) => (
            <span key={t} className="chip bg-white/[0.04] text-ink-300 border border-white/[0.06]">
              #{t}
            </span>
          ))}
        </div>
      </div>
    </button>
  );
}