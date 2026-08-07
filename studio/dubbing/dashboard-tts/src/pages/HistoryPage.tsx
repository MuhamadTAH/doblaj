import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Link } from "react-router-dom";
import { useTtsStore } from "@/store/tts";
import { formatBytes, formatDuration, formatTimeAgo } from "@/lib/format";
import { t } from "@/lib/i18n";
import { DubJob } from "@/api/dubbing";
import { useApi } from "@/hooks/useApi";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export default function HistoryPage() {
  const [activeTab, setActiveTab] = useState<"video" | "tts">("video");
  
  const history = useTtsStore((s) => s.history);
  const setPlayback = useTtsStore((s) => s.setPlayback);
  const playback = useTtsStore((s) => s.playback);
  const remove = useTtsStore((s) => s.removeFromHistory);
  const clear = useTtsStore((s) => s.clearHistory);
  const api = useApi();

  const [videoJobs, setVideoJobs] = useState<DubJob[]>([]);
  const [loadingVideo, setLoadingVideo] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "processing" | "failed">("all");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const fetchJobs = async (silent = false) => {
    if (!silent) {
      setLoadingVideo(true);
      setIsRefreshing(true);
    }
    try {
      const jobs = await api.getDubJobs();
      setVideoJobs(jobs || []);
    } catch (err) {
      console.error(err);
    } finally {
      if (!silent) {
        setLoadingVideo(false);
        setTimeout(() => setIsRefreshing(false), 400);
      }
    }
  };

  useEffect(() => {
    if (activeTab !== "video") return;
    fetchJobs();
  }, [activeTab, api]);

  // Polling logic removed
  const handleCopyId = (id: string) => {
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const play = (id: string, url: string, duration: number) => {
    if (playback.id === id) {
      setPlayback({ isPlaying: !playback.isPlaying });
      return;
    }
    setPlayback({ id, url, isPlaying: true, currentTime: 0, duration });
  };

  // Video jobs calculations
  const totalVideoCount = videoJobs.length;
  const completedCount = videoJobs.filter((j) => j.status === "completed").length;
  const processingCount = videoJobs.filter((j) => j.status === "pending" || j.status === "processing").length;
  const failedCount = videoJobs.filter((j) => j.status === "failed").length;

  const filteredVideoJobs = videoJobs.filter((job) => {
    const matchesSearch = job.id.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          (job.error && job.error.toLowerCase().includes(searchQuery.toLowerCase()));
    
    if (statusFilter === "all") return matchesSearch;
    if (statusFilter === "completed") return matchesSearch && job.status === "completed";
    if (statusFilter === "processing") return matchesSearch && (job.status === "processing" || job.status === "pending");
    if (statusFilter === "failed") return matchesSearch && job.status === "failed";
    return matchesSearch;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Top Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-brand-400/20 to-purple-500/20 border border-brand-400/30 flex items-center justify-center text-brand-300 shadow-glow">
            <svg viewBox="0 0 24 24" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
              {t("history_page_title", "Generation & Dubbing History")}
            </h1>
            <p className="text-xs text-ink-400 mt-0.5">
              {activeTab === "video" 
                ? `${totalVideoCount} video dubbing jobs processed in cloud workspace`
                : `${history.length} speech generation audio files saved locally`}
            </p>
          </div>
        </div>

        {/* Tab Switcher & Secondary Actions */}
        <div className="flex items-center gap-3 self-start md:self-auto">
          <div className="flex bg-ink-950/80 p-1 rounded-xl border border-white/[0.08] shadow-inner">
            <button
              onClick={() => setActiveTab("video")}
              className={`flex items-center gap-2 px-4 py-1.5 text-xs font-semibold rounded-lg transition-all duration-200 ${
                activeTab === "video"
                  ? "bg-gradient-to-r from-brand-500 to-brand-600 text-white shadow-md shadow-brand-500/20"
                  : "text-ink-400 hover:text-white hover:bg-white/[0.04]"
              }`}
            >
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M23 7l-7 5 7 5V7z" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
              <span>Video Dubbing</span>
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${activeTab === "video" ? "bg-white/20 text-white" : "bg-white/[0.08] text-ink-400"}`}>
                {videoJobs.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTab("tts")}
              className={`flex items-center gap-2 px-4 py-1.5 text-xs font-semibold rounded-lg transition-all duration-200 ${
                activeTab === "tts"
                  ? "bg-gradient-to-r from-brand-500 to-brand-600 text-white shadow-md shadow-brand-500/20"
                  : "text-ink-400 hover:text-white hover:bg-white/[0.04]"
              }`}
            >
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
              <span>TTS History</span>
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${activeTab === "tts" ? "bg-white/20 text-white" : "bg-white/[0.08] text-ink-400"}`}>
                {history.length}
              </span>
            </button>
          </div>

          {activeTab === "tts" && history.length > 0 && (
            <button onClick={clear} className="btn-ghost text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 hover:border-rose-500/20 px-3 py-1.5">
              Clear all
            </button>
          )}
        </div>
      </div>

      {/* Main Content View */}
      {activeTab === "video" && (
        <div className="space-y-6">
          {/* Quick Metrics Cards Overview */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="glass p-4 rounded-xl border border-white/[0.06] flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">Total Dubs</div>
                <div className="text-2xl font-bold text-white mt-0.5">{totalVideoCount}</div>
              </div>
              <div className="w-10 h-10 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 flex items-center justify-center">
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
              </div>
            </div>

            <div className="glass p-4 rounded-xl border border-white/[0.06] flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400/90">Completed</div>
                <div className="text-2xl font-bold text-emerald-400 mt-0.5">{completedCount}</div>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center">
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
            </div>

            <div className="glass p-4 rounded-xl border border-white/[0.06] flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-cyan-400/90">In Progress</div>
                <div className="text-2xl font-bold text-cyan-400 mt-0.5 flex items-center gap-2">
                  {processingCount}
                  {processingCount > 0 && (
                    <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping inline-block" />
                  )}
                </div>
              </div>
              <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 flex items-center justify-center">
                <svg viewBox="0 0 24 24" className="w-5 h-5 animate-spin" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
              </div>
            </div>

            <div className="glass p-4 rounded-xl border border-white/[0.06] flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-400/90">Failed</div>
                <div className="text-2xl font-bold text-rose-400 mt-0.5">{failedCount}</div>
              </div>
              <div className="w-10 h-10 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 flex items-center justify-center">
                <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
              </div>
            </div>
          </div>

          {/* Search & Filter Toolbar */}
          <div className="glass p-3 rounded-2xl flex flex-col md:flex-row items-center justify-between gap-3 border border-white/[0.06]">
            {/* Search Input */}
            <div className="relative w-full md:w-80">
              <svg viewBox="0 0 24 24" className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search jobs by ID or details..."
                className="w-full pl-9 pr-8 py-1.5 bg-ink-900/90 border border-white/[0.08] rounded-xl text-xs text-white placeholder:text-ink-500 focus:outline-none focus:border-brand-400/50 transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-500 hover:text-white"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Status Filter Buttons & Refresh */}
            <div className="flex items-center gap-2 w-full md:w-auto justify-between md:justify-end">
              <div className="flex bg-ink-950/60 p-1 rounded-xl border border-white/[0.06] text-xs">
                <button
                  onClick={() => setStatusFilter("all")}
                  className={`px-3 py-1 rounded-lg transition-colors ${
                    statusFilter === "all" ? "bg-white/10 text-white font-medium shadow-sm" : "text-ink-400 hover:text-white"
                  }`}
                >
                  All ({totalVideoCount})
                </button>
                <button
                  onClick={() => setStatusFilter("completed")}
                  className={`px-3 py-1 rounded-lg transition-colors ${
                    statusFilter === "completed" ? "bg-emerald-500/20 text-emerald-300 font-medium shadow-sm" : "text-ink-400 hover:text-white"
                  }`}
                >
                  Completed ({completedCount})
                </button>
                <button
                  onClick={() => setStatusFilter("processing")}
                  className={`px-3 py-1 rounded-lg transition-colors ${
                    statusFilter === "processing" ? "bg-cyan-500/20 text-cyan-300 font-medium shadow-sm" : "text-ink-400 hover:text-white"
                  }`}
                >
                  Active ({processingCount})
                </button>
                <button
                  onClick={() => setStatusFilter("failed")}
                  className={`px-3 py-1 rounded-lg transition-colors ${
                    statusFilter === "failed" ? "bg-rose-500/20 text-rose-300 font-medium shadow-sm" : "text-ink-400 hover:text-white"
                  }`}
                >
                  Failed ({failedCount})
                </button>
              </div>

              {/* Refresh Action */}
              <button
                onClick={() => fetchJobs(false)}
                disabled={loadingVideo}
                title="Refresh history"
                className="btn-ghost p-2 rounded-xl text-ink-300 hover:text-white disabled:opacity-50"
              >
                <svg
                  viewBox="0 0 24 24"
                  className={`w-4 h-4 ${isRefreshing ? "animate-spin text-brand-400" : ""}`}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21.5 2v6h-6M2.5 22v-6h6" />
                  <path d="M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
                </svg>
              </button>
            </div>
          </div>

          {/* Video Dubbing Jobs Grid */}
          {loadingVideo && videoJobs.length === 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[1, 2, 3].map((i) => (
                <div key={i} className="glass-strong rounded-2xl p-4 space-y-3 animate-pulse border border-white/[0.06]">
                  <div className="aspect-video bg-white/[0.04] rounded-xl" />
                  <div className="h-4 bg-white/[0.06] rounded w-2/3" />
                  <div className="h-3 bg-white/[0.04] rounded w-1/3" />
                  <div className="h-8 bg-white/[0.06] rounded-xl mt-4" />
                </div>
              ))}
            </div>
          ) : filteredVideoJobs.length === 0 ? (
            <div className="glass rounded-2xl py-16 px-6 text-center border border-white/[0.06] space-y-4">
              <div className="w-16 h-16 rounded-2xl bg-white/[0.03] border border-white/[0.08] flex items-center justify-center mx-auto text-ink-500">
                <svg viewBox="0 0 24 24" className="w-8 h-8" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
                  <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
                  <line x1="17.5" y1="6.5" x2="17.51" y2="6.5" />
                </svg>
              </div>
              <div className="space-y-1">
                <h3 className="text-base font-semibold text-white">No video dubs found</h3>
                <p className="text-xs text-ink-400 max-w-sm mx-auto">
                  {searchQuery || statusFilter !== "all"
                    ? "No video jobs match your current search criteria. Try resetting filters."
                    : "You haven't created any AI video dubbing projects yet."}
                </p>
              </div>
              <div className="pt-2">
                <Link to="/dubbing" className="btn-primary text-xs py-2 px-5 rounded-xl shadow-glow">
                  + Create New Video Dub
                </Link>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              <AnimatePresence>
                {filteredVideoJobs.map((job) => {
                  const isCompleted = job.status === "completed";
                  const isFailed = job.status === "failed";
                  const isProcessing = job.status === "processing" || job.status === "pending";

                  return (
                    <motion.div
                      key={job.id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.95 }}
                      transition={{ duration: 0.2 }}
                      className="glass-strong rounded-2xl overflow-hidden border border-white/[0.08] hover:border-brand-400/40 hover:shadow-2xl hover:shadow-brand-500/10 transition-all duration-300 group flex flex-col justify-between"
                    >
                      <div>
                        {/* Video Viewport Container */}
                        {isCompleted && job.output_path ? (
                          <DubVideoCardPlayer jobId={job.id} status={job.status} videoUrl={job.output_path} />
                        ) : isProcessing ? (
                          <div className="aspect-video w-full bg-black/90 relative overflow-hidden group/video border-b border-white/[0.06] flex flex-col items-center justify-center p-6 text-center bg-gradient-to-b from-black/80 to-ink-950/90">
                            <div className="absolute inset-0 bg-cyan-500/5 animate-pulse" />
                            <div className="w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 mb-3 relative">
                              <svg viewBox="0 0 24 24" className="w-6 h-6 animate-spin" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                              </svg>
                            </div>
                            <div className="text-xs font-semibold text-white tracking-wide mb-1">
                              {job.status === "pending" ? "Queued in Cloud..." : "Dubbing & Translating..."}
                            </div>
                            <div className="text-[11px] text-cyan-300/80 mb-3 font-mono">
                              Progress: {job.progress || 0}%
                            </div>

                            {/* Progress bar */}
                            <div className="w-full bg-white/10 rounded-full h-1.5 overflow-hidden border border-white/10 progress-bar-wrap">
                              <div
                                className="bg-gradient-to-r from-cyan-400 to-brand-400 h-full rounded-full transition-all duration-300"
                                style={{ width: `${Math.max(5, job.progress || 0)}%` }}
                              />
                            </div>
                          </div>
                        ) : (
                          <div className="aspect-video w-full flex flex-col items-center justify-center p-6 text-center bg-rose-950/20 border-b border-rose-500/20">
                            <div className="w-10 h-10 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-400 flex items-center justify-center mb-2">
                              <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="12" r="10" />
                                <line x1="15" y1="9" x2="9" y2="15" />
                                <line x1="9" y1="9" x2="15" y2="15" />
                              </svg>
                            </div>
                            <div className="text-xs font-semibold text-rose-300">Processing Error</div>
                            {job.error && (
                              <p className="text-[10px] text-rose-300/70 mt-1 line-clamp-2 px-2 font-mono">
                                {job.error}
                              </p>
                            )}
                          </div>
                        )}

                        {/* Card Body Info */}
                        <div className="p-4 space-y-3">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <h4 className="text-sm font-semibold text-white truncate group-hover:text-brand-300 transition-colors">
                                Dub Session #{job.id.slice(0, 8)}
                              </h4>
                              <div className="text-[11px] text-ink-400 font-mono mt-0.5 flex items-center gap-1.5">
                                <span>ID: {job.id.slice(0, 14)}...</span>
                                <button
                                  onClick={() => handleCopyId(job.id)}
                                  title="Copy Job ID"
                                  className="text-ink-500 hover:text-white transition-colors"
                                >
                                  {copiedId === job.id ? (
                                    <span className="text-emerald-400 text-[10px]">Copied!</span>
                                  ) : (
                                    <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2">
                                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                                    </svg>
                                  )}
                                </button>
                              </div>
                            </div>
                          </div>

                          {job.created_at && (
                            <div className="flex items-center gap-2 text-[11px] text-ink-400 pt-1 border-t border-white/[0.04]">
                              <svg viewBox="0 0 24 24" className="w-3 h-3 text-ink-500" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="12" r="10" />
                                <polyline points="12 6 12 12 16 14" />
                              </svg>
                              <span>{formatTimeAgo(job.created_at)}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Card Footer Actions */}
                      <div className="p-4 pt-0">
                        {isCompleted && job.output_path ? (
                          <a
                            href={job.output_path.startsWith("http") ? job.output_path : `${API_BASE}/video/jobs/${job.id}/download`}
                            download
                            target="_blank"
                            rel="noreferrer"
                            className="w-full btn-primary text-xs py-2 flex items-center justify-center gap-2 rounded-xl shadow-glow"
                          >
                            <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 arrow-flip" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                              <polyline points="7 10 12 15 17 10" />
                              <line x1="12" y1="15" x2="12" y2="3" />
                            </svg>
                            <span>Download Full Dubbed MP4</span>
                          </a>
                        ) : isFailed ? (
                          <Link
                            to="/dubbing"
                            className="w-full btn-ghost text-xs py-2 flex items-center justify-center gap-2 rounded-xl text-rose-300 border-rose-500/20 hover:bg-rose-500/10"
                          >
                            <span>Retry New Dubbing</span>
                          </Link>
                        ) : (
                          <div className="w-full py-2 bg-white/[0.04] rounded-xl text-center text-xs text-ink-400 font-medium border border-white/[0.04]">
                            Processing in cloud...
                          </div>
                        )}
                      </div>
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>
          )}
        </div>
      )}

      {/* TTS Storage History View */}
      {activeTab === "tts" && (
        <div className="glass rounded-2xl overflow-hidden border border-white/[0.08] shadow-2xl">
          <div className="grid grid-cols-12 gap-4 px-6 py-3.5 border-b border-white/[0.08] text-[11px] uppercase tracking-wider text-ink-400 font-bold bg-white/[0.02]">
            <div className="col-span-5">{t("history_col_text", "Text Content")}</div>
            <div className="col-span-2">{t("history_col_voice", "Voice & Lang")}</div>
            <div className="col-span-1 text-end">{t("history_col_length", "Duration")}</div>
            <div className="col-span-1 text-end">{t("history_col_size", "Size")}</div>
            <div className="col-span-2 text-end">{t("history_col_when", "Created")}</div>
            <div className="col-span-1 text-end">{t("history_col_actions", "Actions")}</div>
          </div>

          {history.length === 0 ? (
            <div className="px-6 py-20 text-center space-y-3">
              <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mx-auto text-ink-500">
                <svg viewBox="0 0 24 24" className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                </svg>
              </div>
              <div className="text-sm font-medium text-ink-300">No TTS generations saved locally</div>
              <p className="text-xs text-ink-500 max-w-sm mx-auto">
                Head over to the Generate tab to produce realistic Kurdish & Arabic speech audio.
              </p>
              <div className="pt-2">
                <Link to="/tts" className="btn-primary text-xs py-2 px-4 rounded-xl">
                  Go to Speech Generator
                </Link>
              </div>
            </div>
          ) : (
            <AnimatePresence initial={false}>
              {history.map((h) => {
                const isCurrent = playback.id === h.id;
                return (
                  <motion.div
                    key={h.id}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: -10 }}
                    transition={{ duration: 0.2 }}
                    className={`grid grid-cols-12 gap-4 px-6 py-3.5 items-center border-b border-white/[0.04] last:border-0 transition-colors ${
                      isCurrent ? "bg-brand-500/[0.08]" : "hover:bg-white/[0.03]"
                    }`}
                  >
                    <div className="col-span-5 min-w-0">
                      <div className="text-sm font-medium text-white truncate" title={h.text}>
                        {h.text}
                      </div>
                      <div className="text-[10px] text-ink-500 mt-0.5 font-mono">
                        <bdi>{h.id}</bdi>
                      </div>
                    </div>

                    <div className="col-span-2 text-xs text-ink-200 truncate flex items-center gap-1.5">
                      <span className="font-semibold text-white">{h.voice_name}</span>
                      <span className="text-ink-500 text-[10px] bg-white/[0.06] px-1.5 py-0.5 rounded">
                        <bdi>{h.language}</bdi>
                      </span>
                    </div>

                    <div className="col-span-1 text-end text-xs text-ink-300 font-mono tabular-nums">
                      <bdi>{formatDuration(h.duration_ms)}</bdi>
                    </div>

                    <div className="col-span-1 text-end text-xs text-ink-400 font-mono tabular-nums">
                      <bdi>{formatBytes(h.size_bytes)}</bdi>
                    </div>

                    <div className="col-span-2 text-end text-xs text-ink-400">
                      {formatTimeAgo(h.created_at)}
                    </div>

                    <div className="col-span-1 flex items-center justify-end gap-1">
                      <IconAction
                        title={isCurrent && playback.isPlaying ? t("pause", "Pause") : t("play", "Play")}
                        onClick={() => play(h.id, h.blob_url, h.duration_ms)}
                        active={isCurrent && playback.isPlaying}
                      >
                        {isCurrent && playback.isPlaying ? (
                          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="currentColor">
                            <rect x="6" y="5" width="4" height="14" rx="1" />
                            <rect x="14" y="5" width="4" height="14" rx="1" />
                          </svg>
                        ) : (
                          <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="currentColor">
                            <path d="M8 5v14l11-7z" />
                          </svg>
                        )}
                      </IconAction>

                      <IconAction
                        title={t("download", "Download")}
                        onClick={() => downloadBlob(h.blob_url, `${h.voice_name}-${h.id}.wav`)}
                      >
                        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 arrow-flip" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                      </IconAction>

                      <IconAction title={t("delete", "Delete")} onClick={() => remove(h.id)}>
                        <svg viewBox="0 0 24 24" className="w-3.5 h-3.5 text-rose-400/80 hover:text-rose-400" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6" />
                          <path d="M10 11v6" />
                          <path d="M14 11v6" />
                        </svg>
                      </IconAction>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          )}
        </div>
      )}
    </div>
  );
}

function IconAction({
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
    <button
      onClick={onClick}
      title={title}
      className={`w-8 h-8 rounded-lg flex items-center justify-center transition-all ${
        active
          ? "bg-brand-500/20 text-brand-300 border border-brand-400/30 shadow-sm"
          : "text-ink-400 hover:text-white hover:bg-white/[0.08]"
      }`}
    >
      {children}
    </button>
  );
}

function downloadBlob(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function DubVideoCardPlayer({ jobId, status, videoUrl }: { jobId: string; status: string; videoUrl?: string }) {
  const [orientation, setOrientation] = useState<"vertical" | "landscape" | "square">("landscape");
  const videoSrc = (videoUrl && (videoUrl.startsWith("http") || videoUrl.startsWith("/")))
    ? (videoUrl.startsWith("/") && !videoUrl.startsWith("http") ? `${API_BASE}${videoUrl}` : videoUrl)
    : `${API_BASE}/video/jobs/${jobId}/download?inline=true`;

  return (
    <div
      className={`w-full bg-black/95 relative overflow-hidden group/video border-b border-white/[0.06] flex items-center justify-center transition-all duration-300 ${
        orientation === "vertical"
          ? "aspect-[9/16] max-h-[480px] my-1 rounded-xl shadow-2xl"
          : orientation === "square"
          ? "aspect-square max-h-[380px] my-1 rounded-xl"
          : "aspect-video w-full rounded-xl"
      }`}
    >
      <video
        src={videoSrc}
        controls
        preload="metadata"
        onLoadedMetadata={(e) => {
          const v = e.currentTarget;
          if (v.videoHeight > v.videoWidth * 1.1) {
            setOrientation("vertical");
          } else if (Math.abs(v.videoWidth - v.videoHeight) < 40) {
            setOrientation("square");
          } else {
            setOrientation("landscape");
          }
        }}
        className="w-full h-full object-contain bg-black"
      />
      
      {/* Top-Right Status Overlay */}
      <div className="absolute top-2 right-2 z-10 pointer-events-none">
        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider backdrop-blur-md bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 shadow-lg flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          {status}
        </span>
      </div>
    </div>
  );
}
