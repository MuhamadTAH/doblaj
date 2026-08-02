import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { t } from "@/lib/i18n";
import { type DubJob } from "@/api/dubbing";
import StageIcons, { activeStageIndex } from "@/components/StageIcons";
import { useApi, AuthFailedError, AuthNetworkError } from "@/hooks/useApi";

const ACCEPTED = ".mp4,.mov,.webm,.mkv,video/*";
const MAX_BYTES = 500 * 1024 * 1024; // 500 MB

type Phase = "idle" | "ready" | "uploading" | "processing" | "completed" | "failed";

// Pird: live crop tuner for the brand logo video. The animation may
// sit anywhere in the frame; these three numbers let you position the
// circular clip over the actual logo. Defaults assume a centered
// 512×512 logo; tweak to match the rendered asset.
const DEFAULT_LOGO_CROP = { cx: 45.5, cy: 51, r: 21 };

// Pird: category → sub-options mapping. The second dropdown only shows
// after a category is picked. "Other" reveals a free-text input so the
// user can type any model the option list doesn't cover.
const CATEGORIES: { id: string; labelKey: string; defaultLabel: string; subOptions: { value: string; labelKey: string; defaultLabel: string }[] }[] = [
  {
    id: "automotive",
    labelKey: "cat_automotive",
    defaultLabel: "Automotive",
    subOptions: [
      { value: "ford_f150", labelKey: "model_ford_f150", defaultLabel: "Ford F-150" },
      { value: "toyota_camry", labelKey: "model_toyota_camry", defaultLabel: "Toyota Camry" },
      { value: "honda_civic", labelKey: "model_honda_civic", defaultLabel: "Honda Civic" },
      { value: "bmw_x5", labelKey: "model_bmw_x5", defaultLabel: "BMW X5" },
      { value: "mercedes_c_class", labelKey: "model_mercedes_c_class", defaultLabel: "Mercedes C-Class" },
      { value: "tesla_model_3", labelKey: "model_tesla_model_3", defaultLabel: "Tesla Model 3" },
    ],
  },
  {
    id: "tech",
    labelKey: "cat_tech",
    defaultLabel: "Tech",
    subOptions: [
      { value: "iphone_15", labelKey: "model_iphone_15", defaultLabel: "iPhone 15" },
      { value: "macbook_pro_m3", labelKey: "model_macbook_pro_m3", defaultLabel: "MacBook Pro M3" },
      { value: "pixel_8", labelKey: "model_pixel_8", defaultLabel: "Pixel 8" },
      { value: "airpods_pro", labelKey: "model_airpods_pro", defaultLabel: "AirPods Pro" },
    ],
  },
  {
    id: "gaming",
    labelKey: "cat_gaming",
    defaultLabel: "Gaming",
    subOptions: [
      { value: "ps5", labelKey: "model_ps5", defaultLabel: "PlayStation 5" },
      { value: "xbox_series_x", labelKey: "model_xbox_series_x", defaultLabel: "Xbox Series X" },
      { value: "steam_deck", labelKey: "model_steam_deck", defaultLabel: "Steam Deck" },
      { value: "switch_oled", labelKey: "model_switch_oled", defaultLabel: "Nintendo Switch OLED" },
    ],
  },
  {
    id: "clothes",
    labelKey: "cat_clothes",
    defaultLabel: "Clothes",
    subOptions: [
      { value: "nike_air_max", labelKey: "model_nike_air_max", defaultLabel: "Nike Air Max" },
      { value: "adidas_yeezy", labelKey: "model_adidas_yeezy", defaultLabel: "Adidas Yeezy" },
      { value: "levis_501", labelKey: "model_levis_501", defaultLabel: "Levi's 501" },
    ],
  },
  {
    id: "other",
    labelKey: "cat_other",
    defaultLabel: "Other",
    subOptions: [], // free-text input shown instead
  },
];

export default function VideoDubbingPage() {
  const api = useApi();
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState<string>("");
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [targetLang, setTargetLang] = useState<"ckb" | "ar">("ckb");
  // Pird: category + entity. category is one of the CATEGORIES ids (or
  // "" = not chosen); entity is either a sub-option value or a free-text
  // string when category === "other".
  const [category, setCategory] = useState<string>("");
  // Pird: free-text values for the "_custom_" sentinel category/entity.
  // The actual FormData submission uses customCategory / customEntity
  // when their respective pickers are in custom mode.
  const [customCategory, setCustomCategory] = useState<string>("");
  const [customEntity, setCustomEntity] = useState<string>("");
  const [entity, setEntity] = useState<string>("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollRef = useRef<number | null>(null);

  // ── Notification state ───────────────────────────────────────────
  const [showNotifPrompt, setShowNotifPrompt] = useState(false);
  const [notifGranted, setNotifGranted] = useState<boolean>(
    typeof Notification !== "undefined" && Notification.permission === "granted"
  );
  // Track whether we've already asked this session so we never show twice
  const notifAskedRef = useRef(false);

  const isBusy = phase === "uploading" || phase === "processing";
  // Pird: gate the Dub Now button on BOTH video + category + entity so
  // the user can't fire a half-configured pipeline. Re-evaluated when
  // either field changes.
  // Special value: when category === "_custom_" the category input is
  // free-text (customCategory); the same applies when entity === "_custom_"
  // (customEntity). Both are sent to the backend as `category` / `entity`.
  // Pird: when the pickers are in custom mode, validate the free-text
  // values instead of the dropdown values.
  const resolvedCategory =
    category === "_custom_" ? customCategory.trim() : category;
  const resolvedEntity =
    entity === "_custom_" ? customEntity.trim() : entity;
  const canSubmit =
    !!file && resolvedCategory !== "" && resolvedEntity !== "" && !isBusy;

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const reset = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setFile(null);
    setJobId(null);
    setVideoUrl(null);
    setProgress(0);
    setPhase("idle");
    setStatusMsg("");
    setError(null);
    setCategory("");
    setEntity("");
  };

  const onPickFile = (f: File | null) => {
    setError(null);
    setVideoUrl(null);
    setJobId(null);
    setProgress(0);
    setStatusMsg("");
    if (!f) {
      setFile(null);
      setPhase("idle");
      return;
    }
    if (!f.type.startsWith("video/")) {
      setError(t("video_only", "Please upload a video file."));
      return;
    }
    if (f.size > MAX_BYTES) {
      setError(t("file_too_large", "File too large (max 500 MB)."));
      return;
    }
    setFile(f);
    setPhase("ready");
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onPickFile(f);
  };

  const startDubbing = async () => {
    if (!file) {
      fileInputRef.current?.click();
      return;
    }
    if (!canSubmit) return; // Pird: button is disabled until both are set; this is the safety net.
    setError(null);
    setPhase("uploading");
    setProgress(5);
    setStatusMsg(t("status_uploading", "Uploading to pipeline…"));

    try {
      const job = await api.submitDubJob(file, {
        category: resolvedCategory || undefined,
        entity: resolvedEntity || undefined,
      });
      setJobId(job.id);
      setPhase("processing");
      setProgress(15);
      setStatusMsg(t("status_uploading", "Uploading to pipeline…"));

      pollRef.current = window.setInterval(async () => {
        try {
          const s: DubJob = await api.getDubStatus(job.id);
          setProgress((p) => Math.max(p, s.progress));
          if (s.status === "completed") {
            setProgress(100);
            setPhase("completed");
            setVideoUrl(s.output_path ?? null);
            setStatusMsg(t("dubbing_complete", "Dubbing complete"));
            if (pollRef.current) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            // Fire browser notification if permission was granted
            if (
              typeof Notification !== "undefined" &&
              Notification.permission === "granted"
            ) {
              const notif = new Notification("Your dubbed video is ready! 🎬", {
                body: "Click here to view your dubbed video.",
                icon: "/logo.png",
              });
              notif.onclick = () => {
                window.focus();
                notif.close();
              };
            }
          } else if (s.status === "failed") {
            setPhase("failed");
            setError(s.error ?? "Processing failed.");
            if (pollRef.current) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
          } else {
            setStatusMsg(stageLabel(s.progress));
          }
        } catch (e: any) {
          if (e instanceof AuthFailedError || e instanceof AuthNetworkError) {
            if (pollRef.current) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            return;
          }
          // Silent — keep polling; transient errors shouldn't kill the job.
          console.warn("poll err", e);
        }
      }, 1500);
    } catch (e: any) {
      if (e instanceof AuthFailedError || e instanceof AuthNetworkError) return;
      setPhase("failed");
      setError(e?.message ?? "Upload failed");
    }
  };

  // Called when user clicks "Allow" in our custom prompt
  const acceptNotif = async () => {
    setShowNotifPrompt(false);
    notifAskedRef.current = true;
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      try {
        const result = await Notification.requestPermission();
        setNotifGranted(result === "granted");
      } catch (err) {
        console.error("Error requesting notification permission:", err);
      }
    }
    startDubbing();
  };

  // Called when user clicks "No thanks"
  const declineNotif = () => {
    setShowNotifPrompt(false);
    notifAskedRef.current = true;
    startDubbing();
  };

  // Intercepts Dub Now: show our custom prompt first (once per session)
  const onDubNowClick = () => {
    if (!canSubmit) return;

    if (!notifAskedRef.current) {
      setShowNotifPrompt(true);
    } else {
      startDubbing();
    }
  };

  return (
    <div className="min-h-[calc(100vh-80px)] flex flex-col items-center px-4 py-12">

      {/* ── Notification permission modal ──────────────────── */}
      <AnimatePresence>
        {showNotifPrompt && (
          <motion.div
            key="notif-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.6 }}
            exit={{ opacity: 0 }}
            onClick={declineNotif}
            className="fixed inset-0 bg-black/80 z-[100] pointer-events-auto"
          />
        )}
        {showNotifPrompt && (
          <motion.div 
            key="notif-modal"
            initial={{ opacity: 0, scale: 0.95, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 16 }}
            className="fixed inset-0 flex items-center justify-center z-[101] p-4 pointer-events-none"
          >
            <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#0f1117] p-6 shadow-2xl pointer-events-auto flex flex-col items-center text-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 shadow-xl shadow-blue-500/30 mb-5">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
              </div>
              <h3 className="text-xl font-bold text-white mb-2">Enable Notifications?</h3>
              <p className="text-sm text-white/70 mb-6 leading-relaxed">
                We'll notify you the instant your video is dubbed and ready. You can safely switch tabs or minimize the window.
              </p>
              <div className="flex w-full gap-3">
                <button
                  onClick={declineNotif}
                  className="flex-1 rounded-2xl border border-white/10 px-4 py-3.5 text-sm font-semibold text-white/80 hover:text-white hover:bg-white/5 transition-colors"
                >
                  No thanks
                </button>
                <button
                  onClick={acceptNotif}
                  className="flex-1 rounded-2xl bg-blue-600 px-4 py-3.5 text-sm font-bold text-white shadow-lg shadow-blue-600/30 hover:bg-blue-500 hover:shadow-blue-600/40 active:scale-95 transition-all"
                >
                  Yes, notify me!
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Pird: Mockup-style landing state — floating language pill over a
          single cyan-glow drop card, big "Dub Now" pill. Becomes the
          pipeline state (progress + stages + player) once processing
          starts; collapses back when the user hits "New video". */}
      <AnimatePresence mode="wait">
        {(() => {
          const landingPhases: Phase[] = ["idle", "ready", "failed"];
          if (!landingPhases.includes(phase)) return null;
          return (
          <motion.div
            key="landing"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
            className="flex flex-col items-center w-full"
          >
            {/* Pird: brand logo animation at the top of the dubbing page.
                Source: src=D:\Pird\studio\dubbing\dubbing logo animation.mp4
                Rendered as <video autoplay muted loop playsinline> so it
                loops silently without user interaction and works inline
                on iOS Safari. Object-cover keeps it square. */}
            <motion.div
              key={file ? `thumb-${file.name}-${file.size}` : "logo"}
              initial={{ opacity: 0, y: -8, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.4, ease: "easeOut" }}
              className="mb-6 w-40 h-40 sm:w-52 sm:h-52 rounded-full overflow-hidden shadow-2xl shadow-cyan-500/10 ring-1 ring-white/10 bg-[#0b1019]"
              style={{
                // Pird: circular clip centered on the logo artwork.
                // Values baked from dev tuner: cx=45.5, cy=51, r=21.
                clipPath: `circle(${DEFAULT_LOGO_CROP.r}% at ${DEFAULT_LOGO_CROP.cx}% ${DEFAULT_LOGO_CROP.cy}%)`,
              }}
            >
              {file ? (
                // Pird: show the selected video as a paused first-frame
                // thumbnail. We use <video> (not <img>) so the browser
                // extracts a real video poster; paused at t=0.1s so the
                // first decoded frame renders. The same circular clip
                // and ring stay in place.
                <VideoThumbnail file={file} />
              ) : (
                <video
                  src="/logo.mp4"
                  autoPlay
                  muted
                  loop
                  playsInline
                  preload="auto"
                  className="w-full h-full object-cover"
                  aria-label="Pird dubbing logo"
                />
              )}
            </motion.div>

            {/* Floating language pill — click to cycle ckb ↔ ar */}
            <button
              onClick={() => setTargetLang((l) => (l === "ckb" ? "ar" : "ckb"))}
              className="mb-[-22px] z-10 relative inline-flex items-center gap-2 rounded-full bg-[#1a2030]/90 backdrop-blur-md border border-white/10 px-5 py-2 text-sm text-white shadow-xl hover:bg-[#1a2030] transition-colors"
            >
              <span className="font-medium">
                {targetLang === "ckb" ? t("sorani_label", "Sorani") : t("arabic_label", "Arabic")}
              </span>
              <span className="inline-block">🇮🇶</span>
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4 text-white/80"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M5 12h14" />
                <path d="M13 6l6 6-6 6" />
              </svg>
              <span className="inline-block">🇮🇶</span>
              <span className="font-medium">{t("iraqi_arabic", "Iraqi Arabic")}</span>
            </button>

            {/* Drop card with cyan glow border */}
            <motion.div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`relative w-full max-w-2xl h-72 rounded-3xl cursor-pointer transition-all ${
                dragOver ? "scale-[1.01]" : ""
              }`}
            >
              <div
                className="absolute inset-0 rounded-3xl"
                style={{
                  background:
                    "linear-gradient(180deg, rgba(34,211,238,0.85) 0%, rgba(34,211,238,0.4) 100%)",
                  padding: "2px",
                  boxShadow:
                    "0 0 60px rgba(34,211,238,0.35), 0 0 120px rgba(34,211,238,0.15)",
                }}
              >
                <div className="w-full h-full rounded-[22px] bg-[#0b1019]/95 backdrop-blur-md flex flex-col items-center justify-center gap-5">
                  <motion.svg
                    animate={{ y: dragOver ? -3 : 0 }}
                    transition={{ type: "spring", stiffness: 300, damping: 18 }}
                    viewBox="0 0 24 24"
                    className="w-14 h-14 text-cyan-400"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.75" />
                    <polyline points="8 16 12 12 16 16" />
                    <line x1="12" y1="12" x2="12" y2="21" />
                  </motion.svg>
                  <div className="text-2xl font-medium text-white tracking-tight">
                    {file
                      ? file.name
                      : t(
                          "drop_your_video_to_start",
                          "Drop your video to start.",
                        )}
                  </div>
                </div>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED}
                className="hidden"
                onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
              />
            </motion.div>

            {/* Pird: cascading category + entity dropdowns. Only show
                once a video is picked. Second dropdown reveals once the
                user picks a category; for 'Other' it shows a free-text
                input so any model name can be typed. */}
            <AnimatePresence>
              {file && (phase === "ready" || phase === "failed") && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.25 }}
                  className="mt-8 w-full max-w-2xl flex flex-col sm:flex-row sm:justify-between gap-3"
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* Category select — capped at half width so the second
                      dropdown has room when it appears. Last option is
                      "Custom" which reveals a free-text input. */}
                  <div className="w-full sm:w-1/2 sm:max-w-md">
                    <label className="block text-xs uppercase tracking-wider text-ink-400 mb-1.5 font-semibold">
                      {t("cat_label", "Category")}
                    </label>
                    <select
                      value={category}
                      onChange={(e) => {
                        setCategory(e.target.value);
                        setEntity(""); // Pird: reset entity when category changes
                        setCustomEntity(""); // also reset custom entity
                      }}
                      className="w-full bg-[#0a0f1c] border border-cyan-400/30 focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 outline-none text-white rounded-xl px-4 py-3 text-sm appearance-none cursor-pointer"
                    >
                      <option value="">{t("cat_select", "Choose a category…")}</option>
                      {CATEGORIES.map((c) => (
                        <option key={c.id} value={c.id}>
                          {t(c.labelKey, c.defaultLabel)}
                        </option>
                      ))}
                      <option value="_custom_">
                        ✎ {t("cat_custom", "Custom (type your own)")}
                      </option>
                    </select>
                    <AnimatePresence>
                      {category === "_custom_" && (
                        <motion.input
                          key="custom-cat"
                          initial={{ opacity: 0, y: -4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -4 }}
                          transition={{ duration: 0.15 }}
                          type="text"
                          value={customCategory}
                          onChange={(e) => setCustomCategory(e.target.value)}
                          placeholder={t(
                            "cat_custom_placeholder",
                            "e.g. industrial machinery",
                          )}
                          className="mt-2 w-full bg-[#0a0f1c] border border-cyan-400/30 focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 outline-none text-white placeholder:text-ink-500 rounded-xl px-4 py-2.5 text-sm"
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                    </AnimatePresence>
                  </div>

                  {/* Sub-options: dropdown for known categories, free-text for 'Other' */}
                  <AnimatePresence mode="wait">
                    {category && (
                      <motion.div
                        key={category}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        transition={{ duration: 0.2 }}
                        className="w-full sm:w-1/2 sm:max-w-md"
                      >
                        <label className="block text-xs uppercase tracking-wider text-ink-400 mb-1.5 font-semibold">
                          {t("model_label", "Model")}
                        </label>
                        {(() => {
                          const cat = CATEGORIES.find((c) => c.id === category);
                          if (!cat) return null;
                          // Pird: for known categories, show a dropdown
                          // with the predefined sub-options + a "Custom"
                          // sentinel at the bottom that reveals a text
                          // input. For the "Other" / custom category,
                          // skip the dropdown entirely and go straight
                          // to a free-text input.
                          const showSubOptions = cat.subOptions.length > 0;
                          return (
                            <div className="flex flex-col gap-2">
                              {showSubOptions && (
                                <select
                                  value={entity}
                                  onChange={(e) => setEntity(e.target.value)}
                                  className="w-full bg-[#0a0f1c] border border-cyan-400/30 focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 outline-none text-white rounded-xl px-4 py-3 text-sm appearance-none cursor-pointer"
                                >
                                  <option value="">{t("model_select", "Choose a model…")}</option>
                                  {cat.subOptions.map((m) => (
                                    <option key={m.value} value={m.value}>
                                      {t(m.labelKey, m.defaultLabel)}
                                    </option>
                                  ))}
                                  <option value="_custom_">
                                    ✎ {t("model_custom", "Custom (type your own)")}
                                  </option>
                                </select>
                              )}
                              <AnimatePresence>
                                {(entity === "_custom_" || (!showSubOptions && category !== "")) && (
                                  <motion.input
                                    key="custom-ent"
                                    initial={{ opacity: 0, y: -4 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -4 }}
                                    transition={{ duration: 0.15 }}
                                    type="text"
                                    value={entity === "_custom_" ? customEntity : entity}
                                    onChange={(e) => {
                                      if (entity === "_custom_") {
                                        setCustomEntity(e.target.value);
                                      } else {
                                        setEntity(e.target.value);
                                      }
                                    }}
                                    placeholder={t(
                                      "model_custom_placeholder",
                                      "e.g. iPhone 15 Pro Max 256GB",
                                    )}
                                    className="w-full bg-[#0a0f1c] border border-cyan-400/30 focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 outline-none text-white placeholder:text-ink-500 rounded-xl px-4 py-2.5 text-sm"
                                    onClick={(e) => e.stopPropagation()}
                                  />
                                )}
                              </AnimatePresence>
                            </div>
                          );
                        })()}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Dub Now CTA */}
            <motion.button
              whileHover={
                canSubmit
                  ? { scale: 1.03, boxShadow: "0 0 32px rgba(59,130,246,0.6)" }
                  : {}
              }
              whileTap={canSubmit ? { scale: 0.97 } : {}}
              onClick={(e) => {
                e.stopPropagation();
                onDubNowClick();
              }}
              disabled={!canSubmit}
              aria-disabled={!canSubmit}
              title={
                !file
                  ? t("cta_hint_upload", "Upload a video first")
                  : !category
                  ? t("cta_hint_category", "Choose a category")
                  : !entity.trim()
                  ? t("cta_hint_entity", "Pick or type a model")
                  : t("dub_now", "Dub Now")
              }
              className="mt-10 px-12 py-4 rounded-full bg-blue-600 hover:bg-blue-500 text-white text-lg font-semibold shadow-lg shadow-blue-600/40 disabled:opacity-30 disabled:cursor-not-allowed disabled:grayscale transition-colors"
            >
              {phase === "uploading"
                ? t("status_uploading", "Uploading to pipeline…")
                : t("dub_now", "Dub Now")}
            </motion.button>

            {/* Pird: format + size hint */}
            <div className="mt-6 text-xs text-ink-500 font-mono tracking-wide">
              MP4 · MOV · WEBM · MKV &nbsp;·&nbsp; 500 MB MAX
            </div>

            {error && (
              <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300 max-w-2xl w-full">
                {error}
              </div>
            )}
          </motion.div>
        );
        })()}

        {((phase as string) === "uploading" || (phase as string) === "processing") && (
          <motion.div
            key="processing"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
            className="w-full max-w-2xl mt-2 space-y-5"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand-400 to-accent-500 flex items-center justify-center shadow-lg shadow-brand-500/30">
                <Spinner />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-white truncate">{file?.name}</div>
                <div className="text-[11px] text-ink-400 font-mono">
                  {jobId ? (
                    <span>
                      {t("job_label", "Job")}{" "}
                      <bdi>{jobId.slice(0, 8)}…</bdi>
                    </span>
                  ) : (
                    "—"
                  )}{" "}
                  · {statusMsg}
                </div>
              </div>
            </div>
            <ProgressBar value={progress} />
            <StageIcons activeIndex={activeStageIndex(progress)} />
          </motion.div>
        )}

        {((phase as string) === "completed") && (
          <motion.div
            key="completed"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.4 }}
            className="w-full max-w-2xl space-y-4"
          >
            <div className="flex items-center justify-between">
              <div className="text-sm text-emerald-300 inline-flex items-center gap-2">
                <svg
                  viewBox="0 0 24 24"
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                {t("dubbing_complete", "Dubbing complete")}
              </div>
              <button onClick={reset} className="btn-ghost text-xs">
                {t("new_video", "New video")}
              </button>
            </div>
            {videoUrl && (
              <div className="rounded-3xl border border-white/[0.08] bg-ink-950/60 backdrop-blur-xl overflow-hidden">
                <video
                  src={videoUrl}
                  controls
                  autoPlay
                  className="w-full max-h-[500px] object-contain bg-black"
                />
                <div className="px-5 py-3 flex items-center justify-between border-t border-white/[0.06]">
                  <div className="text-xs text-ink-400 font-mono truncate">
                    {videoUrl}
                  </div>
                  <a
                    href={videoUrl}
                    download={`dubbed-${jobId?.slice(0, 8)}.mp4`}
                    className="btn-ghost text-xs"
                  >
                    {t("download_video", "Download")}
                  </a>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Pird: local helper components — kept inline so this file is
// self-contained. Stage labels are i18n-aware.

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[11px] text-ink-400">
        <span>{t("pipeline_progress", "Pipeline progress")}</span>
        <span className="font-mono text-white">{Math.round(value)}%</span>
      </div>
      <div className="h-2 rounded-full bg-white/[0.06] overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-brand-400 via-accent-400 to-emerald-400"
          initial={{ width: 0 }}
          animate={{ width: `${value}%` }}
          transition={{ duration: 0.4, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}


function stageLabel(p: number): string {
  if (p < 20) return t("status_uploading", "Uploading to pipeline…");
  if (p < 40) return t("status_separating", "Separating vocals from background…");
  if (p < 60) return t("status_transcribing", "Transcribing source audio…");
  if (p < 80) return t("status_translating", "Translating to Iraqi Arabic…");
  if (p < 95) return t("status_revoicing", "Re-voicing with target speaker…");
  return t("status_assembling", "Assembling final video…");
}

function Spinner() {
  return (
    <svg
      className="w-5 h-5 animate-spin text-white"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
    >
      <circle cx="12" cy="12" r="9" opacity="0.25" />
      <path d="M21 12a9 9 0 0 1-9 9" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Pird: paused first-frame thumbnail of the selected video. Renders a
 * hidden <video> element (object-URL src), waits for `loadedmetadata`,
 * seeks to t=0.1s, then pauses — so the first decoded frame is what
 * the user sees. Re-rendering when the file changes re-fires the
 * seek via the `key` on the parent motion.div.
 */
function VideoThumbnail({ file }: { file: File }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [src, setSrc] = useState<string>("");

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  return (
    <video
      ref={videoRef}
      src={src}
      muted
      playsInline
      preload="metadata"
      onLoadedMetadata={(e) => {
        // Seek past 0 so the first decoded frame is visible.
        e.currentTarget.currentTime = 0.1;
      }}
      className="w-full h-full object-cover"
      aria-label="Selected video thumbnail"
    />
  );
}
