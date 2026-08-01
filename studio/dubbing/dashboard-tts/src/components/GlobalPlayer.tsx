import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTtsStore } from "@/store/tts";
import { formatDuration } from "@/lib/format";

export default function GlobalPlayer() {
  const playback = useTtsStore((s) => s.playback);
  const setPlayback = useTtsStore((s) => s.setPlayback);
  const stop = useTtsStore((s) => s.stopPlayback);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [visible, setVisible] = useState(false);
  const currentBlobUrlRef = useRef<string | null>(null);

  // Show player when there's an active playback
  useEffect(() => {
    if (playback.url) setVisible(true);
  }, [playback.url]);

  // Wire HTMLAudioElement events into the store
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;

    const onTime = () => setPlayback({ currentTime: a.currentTime * 1000 });
    const onMeta = () => {
      const dur = a.duration;
      if (dur && isFinite(dur) && dur > 0) {
        setPlayback({ duration: dur * 1000 });
      }
    };
    const onEnd = () => stop();
    const onPlay = () => setPlayback({ isPlaying: true });
    const onPause = () => setPlayback({ isPlaying: false });

    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onMeta);
    a.addEventListener("ended", onEnd);
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("loadedmetadata", onMeta);
      a.removeEventListener("ended", onEnd);
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
    };
  }, [setPlayback, stop]);

  // Sync src and playback state
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;

    // 1. If URL changed, update src and load
    if (a.getAttribute("data-current-url") !== playback.url) {
      if (playback.url) {
        if (currentBlobUrlRef.current && currentBlobUrlRef.current.startsWith("blob:") && currentBlobUrlRef.current !== playback.url) {
          URL.revokeObjectURL(currentBlobUrlRef.current);
        }
        currentBlobUrlRef.current = playback.url;
        a.src = playback.url;
        a.setAttribute("data-current-url", playback.url);
        a.load();
      } else {
        a.removeAttribute("src");
        a.removeAttribute("data-current-url");
        a.load(); // stop downloading the previous src
      }
    }

    // 2. Sync isPlaying
    if (playback.isPlaying && playback.url) {
      a.play().catch((err) => {
        console.warn("Audio play interrupted:", err);
      });
    } else {
      a.pause();
    }
  }, [playback.url, playback.isPlaying]);

  const togglePlay = () => {
    setPlayback({ isPlaying: !playback.isPlaying });
  };

  const progress =
    playback.duration > 0 ? playback.currentTime / playback.duration : 0;

  const onSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const a = audioRef.current;
    if (!a || !playback.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, x / rect.width));
    a.currentTime = (ratio * playback.duration) / 1000;
    setPlayback({ currentTime: ratio * playback.duration });
  };

  const close = () => {
    setVisible(false);
    setTimeout(() => {
      setPlayback({ id: null, url: null, isPlaying: false, currentTime: 0, duration: 0 });
    }, 250);
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 80, opacity: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 32 }}
          className="fixed bottom-32 left-1/2 -translate-x-1/2 z-50 w-[min(720px,calc(100vw-2rem))]"
        >
          <div className="glass-strong rounded-2xl px-4 py-3 flex items-center gap-3 shadow-2xl border border-white/[0.1]">
            <button
              onClick={togglePlay}
              aria-label={playback.isPlaying ? "Pause audio playback" : "Play audio"}
              aria-pressed={playback.isPlaying}
              className="w-10 h-10 rounded-full bg-gradient-to-b from-brand-400 to-brand-600 text-white flex items-center justify-center shadow-glow hover:from-brand-300 transition-colors"
            >
              {playback.isPlaying ? (
                <svg viewBox="0 0 24 24" className="w-4 h-4" fill="currentColor">
                  <rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" className="w-4 h-4 translate-x-0.5" fill="currentColor">
                  <path d="M8 5v14l11-7z"/>
                </svg>
              )}
            </button>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1.5">
                <Waveform active={playback.isPlaying} />
                <span className="text-[10px] text-ink-400 font-mono tabular-nums">
                  {formatDuration(playback.currentTime)} / {formatDuration(playback.duration)}
                </span>
              </div>
              <div
                onClick={onSeek}
                role="slider"
                aria-label="Audio playback progress"
                aria-valuenow={Math.round(progress * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
                className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden cursor-pointer group"
              >
                <div
                  className="h-full waveform transition-[width] duration-100"
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
            </div>

            <a
              href={playback.url ?? "#"}
              download="pird-tts.wav"
              aria-label="Download generated audio WAV file"
              className="w-9 h-9 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center text-ink-300 hover:text-white hover:bg-white/[0.07] transition-colors"
              title="Download"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4 arrow-flip" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </a>

            <button
              onClick={close}
              aria-label="Close audio player"
              className="w-9 h-9 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center text-ink-300 hover:text-white hover:bg-white/[0.07] transition-colors"
              title="Close"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>

            {/* Hidden audio element drives the playback */}
            <audio ref={audioRef} className="hidden" />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex items-end gap-[2px] h-3" aria-hidden="true">
      {Array.from({ length: 24 }).map((_, i) => {
        const h = 30 + ((i * 37) % 70);
        const delay = (i % 6) * 0.15;
        return (
          <span
            key={i}
            className={`w-[2px] rounded-sm bg-gradient-to-t from-brand-400 to-accent-500 transition-opacity ${
              active ? "waveform-bar-active" : "opacity-40"
            }`}
            style={{
              height: `${h}%`,
              animationDelay: `${delay}s`,
            }}
          />
        );
      })}
    </div>
  );
}