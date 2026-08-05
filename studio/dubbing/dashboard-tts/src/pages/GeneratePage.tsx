import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { type Voice } from "@/api/tts";
import { useApi, AuthFailedError, AuthNetworkError } from "@/hooks/useApi";
import { useTtsStore } from "@/store/tts";
import { useUiStore } from "@/store/ui";
import { uid } from "@/lib/format";
import VoicePickerModal from "@/components/VoicePickerModal";
import Modal from "@/components/Modal";
import { t } from "@/lib/i18n";

type Speaker = { id: string; voice: Voice | null; text: string };

const MAX_SPEAKERS = 4;
const MAX_CHARS = 500;

export default function TextToSpeechPage() {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([
    { id: uid(), voice: null, text: "" },
  ]);
  const [activeSpeakerId, setActiveSpeakerId] = useState<string>("");

  const [rightTab, setRightTab] = useState<"settings" | "history">("settings");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTarget, setPickerTarget] = useState<string | null>(null); // speaker id, or null for "+ Add more voice"

  // Global settings
  const audioDefaults = useUiStore((s) => s.audioDefaults);
  const [model, setModel] = useState(audioDefaults.model || "Fish Audio S2 Pro");
  const [volume, setVolume] = useState(audioDefaults.volume ?? 0);     // -5..+5
  const [speed, setSpeed] = useState(audioDefaults.speed ?? 1);        // 0.7..1.3
  const [loudness, setLoudness] = useState(audioDefaults.loudnessNorm ?? true);
  const [textNorm, setTextNorm] = useState(audioDefaults.textNorm ?? true);
  const [tagCompat, setTagCompat] = useState(audioDefaults.tagCompat ?? false);
  const [confirmDelete, setConfirmDelete] = useState<{ speakerId: string } | null>(null);
  const [consent, setConsent] = useState(false);


  const isGenerating = useTtsStore((s) => s.isGenerating);
  const setGenerating = useTtsStore((s) => s.setGenerating);
  const setError = useTtsStore((s) => s.setError);
  const error = useTtsStore((s) => s.error);
  const addToHistory = useTtsStore((s) => s.addToHistory);
  const setPlayback = useTtsStore((s) => s.setPlayback);
  const api = useApi();

  // Load voices once
  useEffect(() => {
    let mounted = true;
    api.fetchVoices().then((v) => {
      if (!mounted) return;
      setVoices(v);
      // Auto-pick the first voice for the first speaker
      if (v.length) {
        setSpeakers((s) => {
          const next = [...s];
          if (next[0] && !next[0].voice) next[0] = { ...next[0], voice: v[0] };
          return next;
        });
      }
    });
    return () => {
      mounted = false;
    };
  }, [api]);

  // Set initial active speaker
  useEffect(() => {
    if (!activeSpeakerId && speakers[0]) setActiveSpeakerId(speakers[0].id);
  }, [activeSpeakerId, speakers]);

  const totalChars = useMemo(
    () => speakers.reduce((sum, s) => sum + s.text.length, 0),
    [speakers]
  );

  const updateSpeaker = (id: string, patch: Partial<Speaker>) =>
    setSpeakers((s) => s.map((sp) => (sp.id === id ? { ...sp, ...patch } : sp)));

  const removeSpeaker = (id: string) =>
    setSpeakers((s) => (s.length > 1 ? s.filter((sp) => sp.id !== id) : s));

  const addSpeaker = () => {
    if (speakers.length >= MAX_SPEAKERS) return;
    const newSpeaker: Speaker = { id: uid(), voice: null, text: "" };
    setSpeakers((s) => [...s, newSpeaker]);
    setActiveSpeakerId(newSpeaker.id);
  };

  const openPicker = (speakerId: string | null) => {
    setPickerTarget(speakerId);
    setPickerOpen(true);
  };

  const onPickVoice = (v: Voice) => {
    if (pickerTarget) {
      // Replacing an existing speaker's voice
      updateSpeaker(pickerTarget, { voice: v });
      setActiveSpeakerId(pickerTarget);
    } else {
      // "+ Add more voice" — attach to the first speaker that has no voice,
      // otherwise create a new speaker (up to the max).
      const emptySpeaker = speakers.find((s) => !s.voice);
      if (emptySpeaker) {
        updateSpeaker(emptySpeaker.id, { voice: v });
        setActiveSpeakerId(emptySpeaker.id);
      } else if (speakers.length < MAX_SPEAKERS) {
        const newId = uid();
        setSpeakers((s) => [...s, { id: newId, voice: v, text: "" }]);
        setActiveSpeakerId(newId);
      } else {
        // Max reached — fall back to replacing the active speaker
        const target = activeSpeakerId || speakers[0]?.id;
        if (target) updateSpeaker(target, { voice: v });
      }
    }
    setPickerTarget(null);
  };

  // Auto-tag all: inserts [chuckle] at the start of each line of text
  const autoTagAll = () => {
    setSpeakers((s) =>
      s.map((sp) => ({
        ...sp,
        text: sp.text
          .split(/(?<=[.!?])\s+/)
          .map((sent) => (sent.trim() ? `[chuckle] ${sent}` : sent))
          .join(" "),
      }))
    );
  };

  const onGenerate = async () => {
    if (speakers.length === 0) return;
    const texts = speakers.map((s) => s.text.trim()).filter(Boolean);
    if (texts.length === 0) return;

    setGenerating(true);
    setError(null);
    try {
      // For multi-speaker, generate per-speaker sequentially
      for (const sp of speakers) {
        if (!sp.voice || !sp.text.trim()) continue;
        const blob = await api.generateTts({
          text: sp.text.trim(),
          voice_id: sp.voice.id,
          language: sp.voice.language,
          speed,
          pitch: volume,
          consent_text_version: "v1.0_2026",
        });

        // Use Object URL for fast native audio loading
        const objectUrl = URL.createObjectURL(blob);
        const audioObj = new Audio(objectUrl);
        await new Promise((res) => {
          audioObj.onloadedmetadata = () => res(null);
          audioObj.onerror = () => res(null);
          setTimeout(res, 2000); // give it more time if needed
        });
        const durationMs =
          audioObj.duration && isFinite(audioObj.duration) && audioObj.duration > 0
            ? Math.round(audioObj.duration * 1000)
            : Math.max(1000, Math.round((sp.text.trim().length / 15) * 1000));

        // Convert blob to Data URL for persistence across reloads/routes
        const dataUrl = await new Promise<string>((resolve) => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result as string);
          reader.readAsDataURL(blob);
        });

        const id = uid();
        addToHistory({
          id,
          text: sp.text.trim(),
          voice_id: sp.voice.id,
          voice_name: sp.voice.name,
          language: sp.voice.language,
          created_at: new Date().toISOString(),
          duration_ms: durationMs,
          blob_url: dataUrl,
          size_bytes: blob.size,
        });
        
        // Pass the objectUrl to playback so it starts instantly without DataURL decoding overhead
        setPlayback({ id, url: objectUrl, isPlaying: true, currentTime: 0, duration: durationMs });
        break; // play the first generated speaker audio
      }
    } catch (e: any) {
      setError(e?.message ?? "Failed to generate audio");
    } finally {
      setGenerating(false);
    }
  };

  // Determine the "+ Add more voice" label:
  // "Add more voice" when there are no speakers with a voice, else "More voice"
  // (user said: "after deleting the voice it changes to more voice")
  const voicesAssigned = speakers.filter((s) => s.voice).length;
  const addMoreLabel = voicesAssigned === 0
    ? t("add_more_voice", "+ Add more voice")
    : t("more_voice", "+ More voice");

  return (
    <div className="flex h-full">
      {/* ============ CENTER COLUMN ============ */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 overflow-y-auto p-6 space-y-3">
          {speakers.map((sp) => (
            <SpeakerBlock
              key={sp.id}
              speaker={sp}
              isActive={sp.id === activeSpeakerId}
              onActivate={() => setActiveSpeakerId(sp.id)}
              onChangeText={(t) => updateSpeaker(sp.id, { text: t })}
              onPickVoice={() => openPicker(sp.id)}
              onDelete={() => removeSpeaker(sp.id)}
              canDelete={speakers.length > 1}
            />
          ))}

          {speakers.length < MAX_SPEAKERS && (
            <button
              onClick={addSpeaker}
              className="rounded-xl border border-dashed border-white/[0.08] text-ink-300 hover:text-white hover:border-white/[0.16] hover:bg-white/[0.02] px-4 py-2.5 text-sm transition-colors inline-flex items-center gap-2"
            >
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              {t("add_speaker", "Add Speaker")}
            </button>
          )}

          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {error}
            </div>
          )}
        </div>

        {/* Bottom bar */}
        <div className="sticky bottom-0 border-t border-white/[0.06] bg-ink-950/80 backdrop-blur-xl px-6 py-3 flex items-center justify-between gap-3">
          <div className="text-xs text-ink-400 font-mono tabular-nums">
            <span className={totalChars > MAX_CHARS ? "text-red-400" : "text-white"}>{totalChars}</span>
            <span> / {MAX_CHARS} {t("characters", "characters")}</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={autoTagAll} className="btn-ghost text-xs">
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 14.4 7.2 16.9l.9-5.4L4.2 7.7l5.4-.8L12 2z"/>
              </svg>
              {t("auto_tag_all", "Auto Tag All")}
            </button>
            <div className="flex items-center gap-2 ml-4 mr-2 max-w-sm">
              <input type="checkbox" id="consent" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="rounded bg-ink-900 border-white/[0.1] text-blue-500 focus:ring-blue-500/50 cursor-pointer flex-shrink-0" />
              <label htmlFor="consent" className="text-[10px] leading-tight text-ink-300 select-none cursor-pointer">
                {t("consent_warrant", "I warrant and represent that I possess all legal rights, permissions, and authorizations to process and clone the audio/voice in this media. I agree to the AI Acceptable Use Policy.")}
              </label>
            </div>
            <button
              onClick={onGenerate}
              disabled={isGenerating || totalChars === 0 || !consent}
              className="btn-primary text-sm"
            >
              {isGenerating ? (
                <>
                  <Spinner /> {t("generating", "Generating…")}
                </>
              ) : (
                <>
                  {t("generate_speech", "Generate Speech")}
                  <kbd className="ms-1 text-[10px] bg-white/15 px-1.5 py-0.5 rounded font-mono">Ctrl+↵</kbd>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* ============ RIGHT SIDEBAR (Settings / History) ============ */}
      <aside className="w-80 shrink-0 border-s border-white/[0.06] flex flex-col bg-ink-900/40">
        {/* Tabs */}
        <div className="p-3">
          <div className="flex p-1 rounded-xl bg-white/[0.04] border border-white/[0.06]">
            <button
              onClick={() => setRightTab("settings")}
              className={`flex-1 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                rightTab === "settings" ? "bg-white/[0.06] text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.06)]" : "text-ink-400 hover:text-white"
              }`}
            >
              {t("settings", "Settings")}
            </button>
            <button
              onClick={() => setRightTab("history")}
              className={`flex-1 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                rightTab === "history" ? "bg-white/[0.06] text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.06)]" : "text-ink-400 hover:text-white"
              }`}
            >
              {t("nav_history", "History")}
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-5">
          {rightTab === "settings" ? (
            <>
              {/* Voice section */}
              <section>
                <h3 className="label mb-2 px-1">{t("voice_label", "Voice")}</h3>
                <div className="space-y-2">
                  {speakers.filter((s) => s.voice).map((sp) => (
                    <VoiceCard
                      key={sp.id}
                      voice={sp.voice!}
                      onPickVoice={() => openPicker(sp.id)}
                      onDelete={() => setConfirmDelete({ speakerId: sp.id })}
                    />
                  ))}
                </div>
                <button
                  onClick={() => openPicker(null)}
                  className="mt-2 w-full rounded-lg border border-dashed border-white/[0.08] text-ink-300 hover:text-white hover:border-white/[0.16] hover:bg-white/[0.02] px-3 py-2.5 text-sm transition-colors flex items-center gap-2"
                >
                  <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>
                  </svg>
                  {addMoreLabel}
                </button>
              </section>

              {/* Model section */}
              <section>
                <h3 className="label mb-2 px-1">{t("model_label", "Model")}</h3>
                <div className="relative">
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="input pe-9 cursor-pointer appearance-none"
                  >
                    <option className="bg-ink-900">{t("model_s2_pro", "Fish Audio S2 Pro")}</option>
                    <option className="bg-ink-900">{t("model_s1", "Fish Audio S1")}</option>
                    <option className="bg-ink-900">{t("model_s2", "Fish Audio S2")}</option>
                  </select>
                  <span className="absolute end-2 top-1/2 -translate-y-1/2 text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded pointer-events-none">
                    {t("newest", "Newest")}
                  </span>
                  <svg viewBox="0 0 24 24" className="w-4 h-4 arrow-flip absolute end-3 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </div>
              </section>

              {/* Audio Controls */}
              <section>
                <h3 className="label mb-2 px-1">{t("audio_controls_label", "Audio Controls")}</h3>
                <div className="space-y-2">
                  <SliderRow
                    label={t("volume_label", "Volume")}
                    value={volume}
                    min={-5}
                    max={5}
                    step={1}
                    onChange={setVolume}
                    format={(v) => (v > 0 ? `+${v}` : `${v}`)}
                  />
                  <SliderRow
                    label={t("speed_label", "Speed")}
                    value={speed}
                    min={0.7}
                    max={1.3}
                    step={0.05}
                    onChange={setSpeed}
                    format={(v) => `${v.toFixed(2)}x`}
                  />
                </div>
                <div className="mt-3 space-y-2">
                  <ToggleRow label={t("loudness_normalization", "Loudness Normalization")} value={loudness} onChange={setLoudness} />
                  <ToggleRow label={t("text_normalization", "Text Normalization")}    value={textNorm} onChange={setTextNorm} />
                  <ToggleRow label={t("tag_compatible_mode", "Tag Compatible Mode")}    value={tagCompat} onChange={setTagCompat} />
                </div>
              </section>
            </>
          ) : (
            <HistoryInline />
          )}
        </div>
      </aside>

      <VoicePickerModal
        open={pickerOpen}
        onClose={() => { setPickerOpen(false); setPickerTarget(null); }}
        voices={voices}
        onPick={onPickVoice}
      />

      <Modal open={!!confirmDelete} onClose={() => setConfirmDelete(null)} title={t("delete_voice_title", "Delete voice?")}>
        <div className="p-5 space-y-3">
          <p className="text-sm text-ink-300">
            {t("delete_voice_confirm", "Remove this voice from the speaker? The voice itself stays in your library, but it'll be unassigned.")}
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setConfirmDelete(null)} className="btn-ghost text-sm">{t("cancel", "Cancel")}</button>
            <button
              onClick={() => {
                if (!confirmDelete) return;
                updateSpeaker(confirmDelete.speakerId, { voice: null });
                setConfirmDelete(null);
              }}
              className="px-4 py-2 rounded-lg bg-red-500/90 hover:bg-red-500 text-white text-sm font-medium transition-colors"
            >
              {t("unassign", "Unassign")}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ============================================================
// Speaker block (the main textarea + voice chip + hover buttons)
// ============================================================
function SpeakerBlock({
  speaker,
  isActive,
  onActivate,
  onChangeText,
  onPickVoice,
  onDelete,
  canDelete,
}: {
  speaker: Speaker;
  isActive: boolean;
  onActivate: () => void;
  onChangeText: (t: string) => void;
  onPickVoice: () => void;
  onDelete: () => void;
  canDelete: boolean;
}) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const [hovered, setHovered] = useState(false);

  // Auto-grow textarea
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, [speaker.text]);

  return (
    <div
      onClick={onActivate}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`group rounded-xl border transition-colors ${
        isActive
          ? "border-white/[0.1] bg-white/[0.02]"
          : "border-white/[0.04] bg-transparent hover:border-white/[0.06]"
      }`}
    >
      <div className="flex items-center gap-3 px-4 pt-3">
        {speaker.voice ? (
          <button
            onClick={(e) => { e.stopPropagation(); onPickVoice(); }}
            className="flex items-center gap-2 group/voice"
          >
            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-orange-400 to-pink-500 flex items-center justify-center text-white text-[10px] font-semibold">
              {speaker.voice.name.slice(0, 1)}
            </div>
            <span className="text-sm text-white font-medium">{speaker.voice.name}</span>
            <svg viewBox="0 0 24 24" className="w-3 h-3 arrow-flip text-ink-500 group-hover/voice:text-white transition-colors" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
        ) : (
          <button
            onClick={(e) => { e.stopPropagation(); onPickVoice(); }}
            className="text-sm text-ink-400 hover:text-white transition-colors inline-flex items-center gap-2"
          >
            <div className="w-6 h-6 rounded-full border border-dashed border-ink-500 flex items-center justify-center">
              <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
            </div>
            {t("pick_a_voice", "Pick a voice")}
          </button>
        )}

        <div className="ms-auto opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
          {speaker.voice && (
            <button
              onClick={(e) => { e.stopPropagation(); onPickVoice(); }}
              className="w-7 h-7 rounded-md flex items-center justify-center text-ink-300 hover:text-white hover:bg-white/[0.06] transition-colors"
              title={t("change_voice", "Change voice")}
            >
              {/* Repeat / exchange icon */}
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="17 1 21 5 17 9"/>
                <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
                <polyline points="7 23 3 19 7 15"/>
                <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
              </svg>
            </button>
          )}
          {canDelete && (
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              className="w-7 h-7 rounded-md flex items-center justify-center text-ink-300 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              title={t("delete", "Delete")}
            >
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      <textarea
        ref={taRef}
        value={speaker.text}
        onChange={(e) => onChangeText(e.target.value)}
        placeholder={t("textarea_placeholder", "Type your text with audio tags like [laughs] to turn into expressive speech...")}
        rows={2}
        className="w-full bg-transparent px-4 py-3 text-[15px] text-white placeholder:text-ink-500 resize-none focus:outline-none leading-relaxed overflow-hidden"
      />
    </div>
  );
}

// ============================================================
// Voice card (right sidebar — used in Voice section)
// ============================================================
function VoiceCard({
  voice,
  onPickVoice,
  onDelete,
}: {
  voice: Voice;
  onPickVoice: () => void;
  onDelete: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="relative rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 transition-colors hover:border-white/[0.1]"
    >
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-orange-400 to-pink-500 flex items-center justify-center text-white font-semibold text-sm border border-white/[0.08]">
          {voice.name.slice(0, 1)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <button onClick={onPickVoice} className="text-sm text-white font-medium hover:underline">
              {voice.name}
            </button>
            <span className="text-[11px] text-ink-400">· {voice.gender}</span>
          </div>
          <div className="text-[11px] text-ink-400 mt-0.5 truncate">{voice.description}</div>
        </div>
        <AnimatePresence>
          {hovered && (
            <motion.div
              initial={{ opacity: 0, x: 4 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 4 }}
              transition={{ duration: 0.15 }}
              className="flex items-center gap-1"
            >
              <button
                onClick={onPickVoice}
                className="w-8 h-8 rounded-md flex items-center justify-center text-ink-300 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] transition-colors"
                title={t("change_voice", "Change voice")}
              >
                {/* Repeat / exchange icon */}
                <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="17 1 21 5 17 9"/>
                  <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
                  <polyline points="7 23 3 19 7 15"/>
                  <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
                </svg>
              </button>
              <button
                onClick={onDelete}
                className="w-8 h-8 rounded-md flex items-center justify-center text-red-400 hover:text-white bg-red-500/10 hover:bg-red-500/20 transition-colors"
                title={t("delete", "Delete")}
              >
                <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/>
                </svg>
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        <span className="chip bg-white/[0.04] text-ink-200 border border-white/[0.06]">
          <span className="inline-block w-3 h-2 rounded-sm me-1 bg-gradient-to-b from-red-500 via-white to-blue-700" />
          {voice.language}
        </span>
        {voice.tags.slice(0, 2).map((t) => (
          <span key={t} className="chip bg-white/[0.04] text-ink-200 border border-white/[0.06]">
            {t}
          </span>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-ink-400">
        <span className="inline-flex items-center gap-1">
          <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-5"/>
          </svg>
          <bdi>789.{Math.floor(Math.random() * 9 + 1)} K</bdi>
        </span>
        <span className="inline-flex items-center gap-1">
          <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
          2.5 K
        </span>
      </div>
    </div>
  );
}

// ============================================================
// Slider row (Volume -5..5, Speed 0.7..1.3)
// ============================================================
function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1 px-1">
        <span className="text-sm text-ink-200">{label}</span>
        <span className="text-xs text-ink-300 font-mono tabular-nums">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 appearance-none rounded-full bg-white/[0.06] cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none
          [&::-webkit-slider-thumb]:w-3.5
          [&::-webkit-slider-thumb]:h-3.5
          [&::-webkit-slider-thumb]:rounded-full
          [&::-webkit-slider-thumb]:bg-white
          [&::-webkit-slider-thumb]:shadow-[0_0_0_4px_rgba(255,255,255,0.06)]
          [&::-webkit-slider-thumb]:cursor-pointer
          [&::-webkit-slider-thumb]:transition-transform
          [&::-webkit-slider-thumb]:hover:scale-110"
      />
    </div>
  );
}

// ============================================================
// Toggle row (Off / On segments)
// ============================================================
function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-ink-200">{label}</span>
      <div className="inline-flex p-0.5 rounded-lg bg-white/[0.04] border border-white/[0.06]">
        <button
          onClick={() => onChange(false)}
          className={`px-3 py-1 text-xs rounded-md transition-colors ${
            !value ? "bg-white/[0.08] text-white" : "text-ink-400 hover:text-white"
          }`}
        >
          {t("off", "Off")}
        </button>
        <button
          onClick={() => onChange(true)}
          className={`px-3 py-1 text-xs rounded-md transition-colors ${
            value ? "bg-white/[0.08] text-white" : "text-ink-400 hover:text-white"
          }`}
        >
          {t("on", "On")}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// History inline view (right sidebar, when History tab active)
// ============================================================
function HistoryInline() {
  const history = useTtsStore((s) => s.history);
  const setPlayback = useTtsStore((s) => s.setPlayback);
  const remove = useTtsStore((s) => s.removeFromHistory);

  if (history.length === 0) {
    return (
      <div className="text-center text-ink-500 text-sm py-12">
        {t("no_generations_yet", "No generations yet.")}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {history.map((h) => (
        <div key={h.id} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
          <div className="flex items-center gap-2 text-xs text-ink-300">
            <span className="text-white font-medium truncate">{h.voice_name}</span>
            <span className="text-ink-500">· {h.language}</span>
          </div>
          <div className="text-xs text-ink-400 mt-1 line-clamp-2">{h.text}</div>
          <div className="mt-2 flex items-center gap-1">
            <button
              onClick={() => setPlayback({ id: h.id, url: h.blob_url, isPlaying: true, currentTime: 0, duration: h.duration_ms })}
              className="w-7 h-7 rounded-md flex items-center justify-center text-ink-300 hover:text-white hover:bg-white/[0.06]"
            >
              <svg viewBox="0 0 24 24" className="w-3 h-3" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            </button>
            <button
              onClick={() => remove(h.id)}
              className="w-7 h-7 rounded-md flex items-center justify-center text-ink-400 hover:text-red-400 hover:bg-red-500/10"
            >
              <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/>
              </svg>
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function Spinner() {
  return (
    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <circle cx="12" cy="12" r="9" opacity="0.25" />
      <path d="M21 12a9 9 0 0 1-9 9" strokeLinecap="round" />
    </svg>
  );
}