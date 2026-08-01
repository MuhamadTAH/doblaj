import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { fetchVoices, previewVoice, type Voice } from "@/api/tts";
import { useTtsStore } from "@/store/tts";
import { uid } from "@/lib/format";
import { t } from "@/lib/i18n";

export default function VoiceLibraryPage() {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [q, setQ] = useState("");
  const [lang, setLang] = useState<string>("all");
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const setPlayback = useTtsStore((s) => s.setPlayback);

  useEffect(() => {
    fetchVoices()
      .then((list) => {
        setVoices(list);
        if (list.length === 0) {
          setLoadError("No voices available — check Supabase + Fish Audio key");
        } else {
          // Pre-fetch top 4 voices in background for zero-delay play
          list.slice(0, 4).forEach((v) => {
            previewVoice(v.id).catch(() => {});
          });
        }
      })
      .catch((e) => setLoadError(String(e)));
  }, []);

  const langs = useMemo(() => {
    const set = new Set(voices.map((v) => v.language));
    return ["all", ...Array.from(set)];
  }, [voices]);

  const filtered = useMemo(() => {
    return voices.filter((v) => {
      if (lang !== "all" && v.language !== lang) return false;
      if (q && !`${v.name} ${v.description ?? ""} ${(v.tags ?? []).join(" ")}`.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [voices, q, lang]);

  const [loadingId, setLoadingId] = useState<string | null>(null);

  const onPreview = async (v: Voice) => {
    // Toggle off if already playing
    if (previewingId === v.id) {
      setPlayback({ isPlaying: false });
      setPreviewingId(null);
      return;
    }

    setLoadingId(v.id);
    try {
      const { url, isMock } = await previewVoice(v.id);
      setPreviewingId(v.id);
      setPlayback({
        id: uid(),
        url,
        isPlaying: true,
        currentTime: 0,
        duration: 0,
      });
      if (isMock) {
        console.warn(`Preview for "${v.name}" is a mock (backend unreachable).`);
      }
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-semibold text-white">{t("nav_voice_library", "Voice Library")}</h1>
          <p className="text-sm text-ink-400 mt-1">
            {filtered.length} voice{filtered.length === 1 ? "" : "s"} available
            {loadError && <span className="ml-2 text-amber-400">· {loadError}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <svg viewBox="0 0 24 24" className="w-4 h-4 absolute start-3 top-1/2 -translate-y-1/2 text-ink-500" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search voices…"
              aria-label="Search voices"
              className="input ps-9 w-64"
            />
          </div>
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value)}
            aria-label="Filter voices by language"
            className="input w-36 cursor-pointer"
          >
            {langs.map((l) => (
              <option key={l} value={l} className="bg-ink-900">
                {l === "all" ? "All languages" : l}
              </option>
            ))}
          </select>
        </div>
      </div>

      {voices.length === 0 && !loadError && (
        <div className="text-center py-16 text-ink-500 text-sm">
          Loading voices from database…
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((v, idx) => {
          const isAr = v.language.toLowerCase().includes("ar");
          const isCkb = v.language.toLowerCase().includes("ckb") || v.language.toLowerCase().includes("ku");
          const badgeClass = isCkb ? "badge-lang-ckb" : isAr ? "badge-lang-ar" : "bg-white/[0.06] text-ink-200 border border-white/[0.08]";
          const isLoading = loadingId === v.id;
          const isPlaying = previewingId === v.id;

          return (
            <motion.div
              key={v.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(idx * 0.02, 0.2), duration: 0.2 }}
              onMouseEnter={() => previewVoice(v.id)}
              className="glass rounded-xl p-4 hover:border-sky-500/30 hover:shadow-lg transition-all group flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start gap-3">
                  <div className="w-11 h-11 rounded-full bg-gradient-to-br from-brand-400/25 to-accent-500/25 flex items-center justify-center text-white font-semibold text-base border border-white/[0.08] shrink-0">
                    {v.name.slice(0, 1)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-white font-medium text-sm truncate">{v.name}</h3>
                      {v.is_yours && (
                        <span className="chip bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">your</span>
                      )}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                      <span className={`chip ${badgeClass}`}>
                        {v.language}
                      </span>
                      <span className="text-xs text-ink-400">· {v.gender}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => onPreview(v)}
                    onMouseEnter={() => previewVoice(v.id)}
                    aria-label={`Preview voice sample for ${v.name}`}
                    aria-pressed={isPlaying}
                    disabled={isLoading}
                    className={`w-9 h-9 rounded-lg flex items-center justify-center transition-all shrink-0 ${
                      isPlaying
                        ? "bg-gradient-to-b from-brand-400 to-brand-600 text-white shadow-glow"
                        : "bg-white/[0.04] border border-white/[0.06] text-ink-300 hover:text-white hover:bg-white/[0.07]"
                    }`}
                    title={isPlaying ? "Pause preview" : "Play preview"}
                  >
                    {isLoading ? (
                      <svg viewBox="0 0 24 24" className="w-4 h-4 animate-spin text-brand-300" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="10" />
                      </svg>
                    ) : isPlaying ? (
                      <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="currentColor">
                        <rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 translate-x-0.5" fill="currentColor">
                        <path d="M8 5v14l11-7z"/>
                      </svg>
                    )}
                  </button>
                </div>
                {v.description && (
                  <p className="text-xs text-ink-400 mt-2.5 leading-relaxed line-clamp-2">{v.description}</p>
                )}
              </div>

              <div className="mt-3 pt-2.5 border-t border-white/[0.04] flex items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1">
                  {v.tags && v.tags.slice(0, 3).map((t) => (
                    <span key={t} className="chip bg-white/[0.03] text-ink-400 border border-white/[0.05]">
                      #{t}
                    </span>
                  ))}
                </div>
                {v.provider_checkpoint && (
                  <span className="text-[10px] text-ink-500 font-mono truncate max-w-[90px]" title={`Checkpoint: ${v.provider_checkpoint}`}>
                    {v.provider_checkpoint.slice(0, 8)}…
                  </span>
                )}
              </div>
            </motion.div>
          );
        })}

        {voices.length > 0 && filtered.length === 0 && (
          <div className="col-span-full text-center py-16 text-ink-500 text-sm">
            No voices match your search criteria.
          </div>
        )}
      </div>
    </div>
  );
}