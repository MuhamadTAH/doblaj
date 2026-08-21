import React, { useState } from "react";
import { usePaginatedQuery, useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useAuth } from "@clerk/clerk-react";
import { downloadJobSource, retryJob, failJob, nukeJob, triggerSeparation, triggerTranscribe, signMediaKey } from "../../api/adminApi";

export const JobOperationsView: React.FC = () => {
  const { getToken } = useAuth();
  const [statusFilter, setStatusFilter] = useState("ALL");
  const { results: jobs, status, loadMore, isLoading } = usePaginatedQuery(
    api.adminQuery.listJobsPaginated,
    { statusFilter },
    { initialNumItems: 50 }
  );

  const [inspectJob, setInspectJob] = useState<any | null>(null);
  const [inspectVideoUrl, setInspectVideoUrl] = useState<string | null>(null);
  const [activeAudioStemUrl, setActiveAudioStemUrl] = useState<{ key: string; url: string; title: string } | null>(null);
  const [node2Running, setNode2Running] = useState(false);
  const [node3Running, setNode3Running] = useState(false);
  const [node2Error, setNode2Error] = useState<string | null>(null);

  const [selectedJob, setSelectedJob] = useState<any | null>(null);
  const [actionType, setActionType] = useState<"RETRY" | "FAIL" | "NUKE" | null>(null);
  const [nukeConfirmText, setNukeConfirmText] = useState("");
  const [failReason, setFailReason] = useState("");
  const [overrideProvider, setOverrideProvider] = useState("runpod");
  const [actionLoading, setActionLoading] = useState(false);

  // Live real-time WebSocket subscription to the inspected job document
  const liveJobDoc = useQuery(
    api.adminQuery.getJobById,
    inspectJob ? { jobId: inspectJob._id } : "skip"
  );
  const activeJob = liveJobDoc || inspectJob;

  // Live real-time WebSocket subscription to chunks for inspected job
  const jobChunks = useQuery(
    api.adminQuery.listChunksForJob,
    inspectJob ? { jobId: inspectJob._id } : "skip"
  ) || [];

  const handleInspect = async (job: any) => {
    setInspectJob(job);
    setInspectVideoUrl(null);
    setActiveAudioStemUrl(null);
    setNode2Error(null);
    try {
      const data = await downloadJobSource(getToken, job._id);
      if (data.download_url) {
        setInspectVideoUrl(data.download_url);
      }
    } catch (e) {
      console.warn("Could not fetch video streaming URL for inspection:", e);
    }
  };

  const handlePlayStem = async (key: string | undefined, title: string) => {
    if (!key) {
      alert("This audio stem or chunk has not been generated on storage yet.");
      return;
    }
    try {
      const res = await signMediaKey(getToken, activeJob._id, key);
      if (res.url) {
        setActiveAudioStemUrl({ key, url: res.url, title });
      } else {
        alert("Could not retrieve streaming URL.");
      }
    } catch (e: any) {
      alert(`Could not sign audio URL: ${e.message}`);
    }
  };

  const handleRunNode2 = async () => {
    if (!activeJob) return;
    setNode2Running(true);
    setNode2Error(null);
    try {
      await triggerSeparation(getToken, activeJob._id);
      alert("Node 2 Audio Separation & Segmentation triggered! Sliced chunks will appear live below.");
    } catch (e: any) {
      setNode2Error(e.message || "Failed to trigger Node 2 separation");
    } finally {
      setNode2Running(false);
    }
  };

  const handleRunNode3 = async () => {
    if (!activeJob) return;
    setNode3Running(true);
    try {
      await triggerTranscribe(getToken, activeJob._id);
      alert("Node 3 Kurdish Sorani ASR triggered! Live transcripts will stream directly into the grid below.");
    } catch (e: any) {
      alert(`Node 3 trigger error: ${e.message}`);
    } finally {
      setNode3Running(false);
    }
  };

  const handleSourceDownload = async (jobId: string) => {
    try {
      const data = await downloadJobSource(getToken, jobId);
      if (data.download_url) {
        window.open(data.download_url, "_blank");
      } else {
        alert("Download URL not available.");
      }
    } catch (e: any) {
      alert(`Error fetching download URL: ${e.message}`);
    }
  };

  const executeAction = async () => {
    if (!selectedJob) return;
    setActionLoading(true);

    try {
      if (actionType === "RETRY") {
        await retryJob(getToken, selectedJob._id, { force_provider: overrideProvider });
      } else if (actionType === "FAIL") {
        await failJob(getToken, selectedJob._id, failReason || "Marked failed by administrator");
      } else if (actionType === "NUKE") {
        if (nukeConfirmText !== `NUKE ${selectedJob._id}`) {
          alert(`Type confirmation "NUKE ${selectedJob._id}" exactly to unlock.`);
          setActionLoading(false);
          return;
        }
        await nukeJob(getToken, selectedJob._id, nukeConfirmText);
      }

      setActionType(null);
      setSelectedJob(null);
      setNukeConfirmText("");
      setFailReason("");
    } catch (err: any) {
      alert(`Action failed: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Metrics Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div>
          <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
            <span>Job Operations & DLQ Triage</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-brand-500/20 text-brand-300 border border-brand-500/30">
              Live Real-Time Sync
            </span>
          </h2>
          <p className="text-xs text-ink-400 mt-1">
            Inspect real-time dubbing pipeline states, audio stems, sliced chunks, and trigger dead-letter queue retries.
          </p>
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-2">
          {["ALL", "FAILED", "PROCESSING", "COMPLETED"].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors ${
                statusFilter === st
                  ? "bg-brand-500 text-white font-bold"
                  : "bg-ink-900 text-ink-400 hover:text-white border border-white/5"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Main Jobs Table */}
      <div className="rounded-xl border border-white/10 bg-ink-900/60 backdrop-blur-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono divide-y divide-white/10">
            <thead className="bg-ink-950/80 text-ink-400 uppercase text-[10px] tracking-wider">
              <tr>
                <th className="py-3 px-4">Job ID / Legacy</th>
                <th className="py-3 px-4">Created / Duration</th>
                <th className="py-3 px-4">Source Media</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Progress</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 text-ink-300">
              {jobs.map((job: any) => {
                const isFailed = (job.status || "").toLowerCase().includes("fail") || (job.status || "").toLowerCase().includes("error");
                const isCompleted = (job.status || "").toLowerCase() === "completed";
                const isProcessing = !isFailed && !isCompleted;

                return (
                  <tr key={job._id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-bold text-white">{job._id}</div>
                      <div className="text-[10px] text-ink-500">{job.legacyId || "No legacy ID"}</div>
                    </td>
                    <td className="py-3 px-4">
                      <div>{job.createdAt ? new Date(job.createdAt).toLocaleString() : "--"}</div>
                      <div className="text-[10px] text-brand-400">
                        {job.total_duration_sec ? `${job.total_duration_sec}s` : (job.mediaMetadata?.durationSec ? `${job.mediaMetadata.durationSec}s` : "--")}
                      </div>
                    </td>
                    <td className="py-3 px-4 max-w-[200px] truncate text-ink-400">
                      {job.sourceVideoR2Key || job.source_video_r2_key || "--"}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase inline-flex items-center gap-1 ${
                          isCompleted
                            ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                            : isFailed
                            ? "bg-red-500/20 text-red-400 border border-red-500/30"
                            : "bg-brand-500/20 text-brand-300 border border-brand-500/30"
                        }`}
                      >
                        {isProcessing && <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-ping" />}
                        <span>{job.status}</span>
                      </span>
                    </td>
                    <td className="py-3 px-4 font-bold text-white">
                      {job.progress ? `${job.progress}%` : (isCompleted ? "100%" : "0%")}
                    </td>
                    <td className="py-3 px-4 text-right space-x-1.5">
                      <button
                        onClick={() => handleInspect(job)}
                        className="px-2.5 py-1 rounded bg-brand-500/20 hover:bg-brand-500/30 text-brand-300 border border-brand-500/30 font-bold transition-colors cursor-pointer"
                      >
                        👁️ Live Telemetry
                      </button>
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setActionType("RETRY");
                        }}
                        className="px-2 py-1 rounded bg-white/[0.05] hover:bg-white/[0.1] text-ink-300 transition-colors"
                      >
                        🔄 Retry
                      </button>
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setActionType("FAIL");
                        }}
                        className="px-2 py-1 rounded bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 transition-colors"
                      >
                        ⚠️ Fail
                      </button>
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setActionType("NUKE");
                        }}
                        className="px-2 py-1 rounded bg-red-900/30 hover:bg-red-900/50 text-red-300 border border-red-500/40 transition-colors"
                      >
                        💥 Nuke
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {status === "CanLoadMore" && (
          <div className="p-4 text-center border-t border-white/5">
            <button
              onClick={() => loadMore(25)}
              disabled={isLoading}
              className="px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-xs font-mono text-white transition-colors"
            >
              {isLoading ? "Loading..." : "Load More Jobs"}
            </button>
          </div>
        )}
      </div>

      {/* ───────────────────────────────────────────────────────────── */}
      {/* LIVE WATCH & PIPELINE INSPECTOR MODAL                        */}
      {/* ───────────────────────────────────────────────────────────── */}
      {inspectJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md p-4 overflow-y-auto">
          <div className="max-w-5xl w-full rounded-2xl border border-white/10 bg-[#0c0e14] p-6 space-y-6 shadow-2xl my-8">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="text-xl font-bold text-white tracking-tight">Live Pipeline Watch & Telemetry</span>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    {activeJob.status}
                  </span>
                </div>
                <p className="text-xs text-ink-400 font-mono mt-1">
                  Job ID: <span className="text-white">{activeJob._id}</span> · Legacy: <span className="text-ink-300">{activeJob.legacyId}</span>
                </p>
              </div>

              <button
                onClick={() => setInspectJob(null)}
                className="w-8 h-8 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-ink-400 hover:text-white flex items-center justify-center text-sm font-bold transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* ───────────────────────────────────────────────────────────── */}
            {/* 1. THE MACRO STEPPER VIEW                                    */}
            {/* ───────────────────────────────────────────────────────────── */}
            {(() => {
              const totalChunks = jobChunks.length;
              const asrDoneCount = jobChunks.filter((c: any) => !!c.kurdishRaw || (c.status || "").includes("TRANSCRIBED") || (c.status || "").includes("COMPLETED")).length;
              const iraqiDoneCount = jobChunks.filter((c: any) => !!c.arabicText).length;
              const ttsDoneCount = jobChunks.filter((c: any) => !!c.ttsAudioR2Key).length;

              const isSeparationDone = totalChunks > 0 || (activeJob.status || "").toLowerCase().includes("separation");
              const isAsrActive = (activeJob.status || "").toLowerCase().includes("transcribing") || (isSeparationDone && asrDoneCount < totalChunks);
              const isAsrDone = totalChunks > 0 && asrDoneCount === totalChunks;

              const isIraqiActive = isAsrDone && iraqiDoneCount < totalChunks;
              const isIraqiDone = totalChunks > 0 && iraqiDoneCount === totalChunks;

              const isTtsActive = isIraqiDone && ttsDoneCount < totalChunks;
              const isTtsDone = totalChunks > 0 && ttsDoneCount === totalChunks;

              const isCompleted = (activeJob.status || "").toLowerCase() === "completed";

              const steps = [
                { id: "s1", num: "1", title: "Ingestion", sub: "R2 & Probe", done: true, active: false, progress: 100 },
                {
                  id: "s2",
                  num: "2",
                  title: "Separation",
                  sub: totalChunks > 0 ? `${totalChunks} Chunks` : "Demucs & VAD",
                  done: isSeparationDone,
                  active: !isSeparationDone && (activeJob.status || "").toLowerCase().includes("separat"),
                  progress: isSeparationDone ? 100 : 25,
                },
                {
                  id: "s3",
                  num: "3",
                  title: "Kurdish ASR",
                  sub: totalChunks > 0 ? `${asrDoneCount}/${totalChunks} Transcribed` : "Gemini Sorani",
                  done: isAsrDone,
                  active: isAsrActive,
                  progress: totalChunks > 0 ? Math.round((asrDoneCount / totalChunks) * 100) : 0,
                },
                {
                  id: "s4",
                  num: "4",
                  title: "Iraqi Arabic",
                  sub: totalChunks > 0 ? `${iraqiDoneCount}/${totalChunks} Localized` : "Syllable Match",
                  done: isIraqiDone,
                  active: isIraqiActive,
                  progress: totalChunks > 0 ? Math.round((iraqiDoneCount / totalChunks) * 100) : 0,
                },
                {
                  id: "s5",
                  num: "5",
                  title: "TTS Synthesis",
                  sub: totalChunks > 0 ? `${ttsDoneCount}/${totalChunks} Voiced` : "Voice Clone",
                  done: isTtsDone,
                  active: isTtsActive,
                  progress: totalChunks > 0 ? Math.round((ttsDoneCount / totalChunks) * 100) : 0,
                },
                {
                  id: "s6",
                  num: "6",
                  title: "Master Mux",
                  sub: isCompleted ? "Ready to Export" : "Ducking Mux",
                  done: isCompleted,
                  active: !isCompleted && isTtsDone,
                  progress: isCompleted ? 100 : 0,
                },
              ];

              return (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-6 gap-2">
                    {steps.map((st) => (
                      <div
                        key={st.id}
                        className={`p-2.5 rounded-xl border relative overflow-hidden transition-all ${
                          st.done
                            ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                            : st.active
                            ? "border-brand-500/80 bg-brand-500/20 ring-2 ring-brand-500/40 shadow-lg shadow-brand-500/20 animate-pulse text-white"
                            : "border-white/[0.08] bg-ink-900/40 text-ink-400"
                        }`}
                      >
                        <div className="flex items-center justify-between font-mono text-[10px] font-bold">
                          <span>STEP {st.num}</span>
                          <span>{st.done ? "✅" : st.active ? "⚡" : "⏳"}</span>
                        </div>
                        <div className="text-xs font-bold mt-1 truncate">{st.title}</div>
                        <div className="text-[10px] font-mono opacity-80 truncate">{st.sub}</div>

                        {st.active && (
                          <div className="w-full bg-white/10 rounded-full h-1 mt-2 overflow-hidden">
                            <div
                              className="bg-brand-400 h-full transition-all duration-300"
                              style={{ width: `${Math.max(10, st.progress)}%` }}
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* ───────────────────────────────────────────────────────────── */}
            {/* 2. AUDIO STEMS & CONTROL ACTION BAR                          */}
            {/* ───────────────────────────────────────────────────────────── */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs">
              {/* Background Stem */}
              <div className="p-3 rounded-xl border border-white/[0.08] bg-ink-950/60 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-ink-400 font-bold uppercase">🎵 Background Stem</span>
                  <span className="text-[10px] text-emerald-400 font-bold">44.1kHz Stereo</span>
                </div>
                <div className="text-xs font-semibold text-white truncate">
                  {activeJob.bgAudioR2Key || "Not separated yet"}
                </div>
                <button
                  onClick={() => handlePlayStem(activeJob.bgAudioR2Key, "Background Stem (no_vocals.wav)")}
                  disabled={!activeJob.bgAudioR2Key}
                  className={`w-full py-1.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-colors ${
                    activeJob.bgAudioR2Key
                      ? "bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 cursor-pointer"
                      : "bg-white/[0.04] text-ink-500 cursor-not-allowed"
                  }`}
                >
                  <span>▶️</span>
                  <span>{activeJob.bgAudioR2Key ? "Play Instrumental" : "Stem Not Ready"}</span>
                </button>
              </div>

              {/* Vocals Stem */}
              <div className="p-3 rounded-xl border border-white/[0.08] bg-ink-950/60 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-ink-400 font-bold uppercase">🗣️ Isolated Vocals</span>
                  <span className="text-[10px] text-purple-400 font-bold">44.1kHz Master</span>
                </div>
                <div className="text-xs font-semibold text-white truncate">
                  {activeJob.isolatedVocalsR2Key || "Not separated yet"}
                </div>
                <button
                  onClick={() => handlePlayStem(activeJob.isolatedVocalsR2Key, "Isolated Vocals Stem (vocals.wav)")}
                  disabled={!activeJob.isolatedVocalsR2Key}
                  className={`w-full py-1.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-colors ${
                    activeJob.isolatedVocalsR2Key
                      ? "bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/30 cursor-pointer"
                      : "bg-white/[0.04] text-ink-500 cursor-not-allowed"
                  }`}
                >
                  <span>▶️</span>
                  <span>{activeJob.isolatedVocalsR2Key ? "Play Vocals" : "Stem Not Ready"}</span>
                </button>
              </div>

              {/* Pipeline Quick Triggers */}
              <div className="p-3 rounded-xl border border-white/[0.08] bg-ink-950/60 flex flex-col justify-between space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-ink-400 font-bold uppercase">⚡ Worker Controls</span>
                  <span className="text-[10px] text-brand-300 font-bold">Manual Trigger</span>
                </div>
                <div className="flex flex-col gap-1.5">
                  <button
                    onClick={handleRunNode2}
                    disabled={node2Running}
                    className="w-full py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-mono text-xs font-bold transition-colors flex items-center justify-center gap-1.5 shadow-lg shadow-purple-600/20 cursor-pointer"
                  >
                    <span>⚡</span>
                    <span>{node2Running ? "Separating Audio..." : "Run Node 2 (Demucs)"}</span>
                  </button>
                  <button
                    onClick={handleRunNode3}
                    disabled={node3Running || jobChunks.length === 0}
                    className={`w-full py-1.5 rounded-lg text-xs font-mono font-bold flex items-center justify-center gap-1.5 transition-colors ${
                      jobChunks.length > 0
                        ? "bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20 cursor-pointer"
                        : "bg-white/[0.04] text-ink-500 cursor-not-allowed"
                    }`}
                  >
                    <span>🎙️</span>
                    <span>{node3Running ? "Transcribing Chunks..." : "Run Node 3 (Kurdish ASR)"}</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Error banner if present */}
            {node2Error && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs font-mono text-red-400">
                ⚠️ Error: {node2Error}
              </div>
            )}

            {/* Active Stem / Chunk Player Bar */}
            {activeAudioStemUrl && (
              <div className="p-3 rounded-xl border border-brand-500/40 bg-brand-500/15 space-y-1.5">
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-white font-bold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-brand-400 animate-ping" />
                    <span>Now Playing: {activeAudioStemUrl.title}</span>
                  </span>
                  <button
                    onClick={() => setActiveAudioStemUrl(null)}
                    className="text-ink-400 hover:text-white text-[11px] px-2 py-0.5 rounded bg-white/[0.05] cursor-pointer"
                  >
                    ✕ Close Player
                  </button>
                </div>
                <audio src={activeAudioStemUrl.url} controls autoPlay className="w-full h-8" />
              </div>
            )}

            {/* ───────────────────────────────────────────────────────────── */}
            {/* 3. THE LIVE CHUNK DATA GRID (THE MICRO VIEW)                 */}
            {/* ───────────────────────────────────────────────────────────── */}
            <div className="space-y-3 rounded-xl border border-white/[0.08] bg-ink-950/60 p-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
                <div className="flex items-center gap-2.5">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-white font-mono flex items-center gap-2">
                    <span>📊 Live Sliced Chunks & Telemetry Grid</span>
                  </h3>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-brand-500/20 text-brand-300 border border-brand-500/30">
                    {jobChunks.length} Chunks Total
                  </span>
                </div>

                <div className="flex items-center gap-2 text-[11px] font-mono text-ink-400">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span>Real-Time WebSocket Stream</span>
                </div>
              </div>

              {jobChunks.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border border-white/[0.06]">
                  <table className="w-full text-left text-xs font-mono divide-y divide-white/[0.06]">
                    <thead className="bg-ink-900/80 text-[10px] text-ink-400 uppercase">
                      <tr>
                        <th className="py-2.5 px-3">#</th>
                        <th className="py-2.5 px-3">Bounds</th>
                        <th className="py-2.5 px-3">Audio</th>
                        <th className="py-2.5 px-3">Kurdish Sorani (Unicode)</th>
                        <th className="py-2.5 px-3">Iraqi Arabic (العامية)</th>
                        <th className="py-2.5 px-3 text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.04] bg-ink-950/40">
                      {jobChunks.map((chunk: any) => {
                        const st = (chunk.status || "PENDING").toUpperCase();
                        const isProcessing = st.includes("PROCESS") || st.includes("EXTRACT");
                        const isDone = st.includes("COMPLET") || st.includes("TRANSCRIB");
                        const isFailed = st.includes("FAIL") || st.includes("ERROR");

                        return (
                          <tr key={chunk._id} className="hover:bg-white/[0.02] transition-colors">
                            <td className="py-3 px-3 font-bold text-brand-300">
                              #{chunk.chunkIndex + 1}
                            </td>
                            <td className="py-3 px-3 text-ink-200">
                              <div>{chunk.startTime.toFixed(2)}s ➔ {chunk.endTime.toFixed(2)}s</div>
                              <div className="text-[10px] text-purple-300">
                                ({(chunk.speechDuration ?? (chunk.endTime - chunk.startTime)).toFixed(2)}s)
                              </div>
                            </td>
                            <td className="py-3 px-3">
                              {chunk.kurdish_raw_audio_url ? (
                                <button
                                  onClick={() =>
                                    handlePlayStem(
                                      chunk.kurdish_raw_audio_url,
                                      `Chunk #${chunk.chunkIndex + 1} (${chunk.startTime.toFixed(2)}s - ${chunk.endTime.toFixed(2)}s)`
                                    )
                                  }
                                  className="px-2.5 py-1 rounded bg-white/[0.06] hover:bg-white/[0.12] text-ink-200 text-[11px] font-bold flex items-center gap-1 cursor-pointer transition-colors"
                                >
                                  <span>▶️</span>
                                  <span>Play</span>
                                </button>
                              ) : (
                                <span className="text-[10px] text-ink-600">Pending</span>
                              )}
                            </td>
                            <td className="py-3 px-3 text-ink-100 max-w-[200px] sm:max-w-[280px]">
                              {chunk.kurdishRaw ? (
                                <div className="p-2 rounded bg-black/30 border border-white/[0.04] text-xs font-kurdish text-white leading-relaxed">
                                  {chunk.kurdishRaw}
                                </div>
                              ) : (
                                <span className="text-ink-600 italic text-[11px]">
                                  {isProcessing ? "Transcribing with Gemini..." : "Waiting for Node 3..."}
                                </span>
                              )}
                            </td>
                            <td className="py-3 px-3 text-ink-100 max-w-[200px] sm:max-w-[280px]">
                              {chunk.arabicText ? (
                                <div className="p-2 rounded bg-brand-500/10 border border-brand-500/20 text-xs font-arabic text-brand-200 leading-relaxed">
                                  {chunk.arabicText}
                                </div>
                              ) : (
                                <span className="text-ink-600 italic text-[11px]">
                                  {isProcessing ? "Localizing..." : "Waiting for Node 4..."}
                                </span>
                              )}
                            </td>
                            <td className="py-3 px-3 text-right">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold inline-flex items-center gap-1 ${
                                  isDone
                                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                                    : isProcessing
                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse"
                                    : isFailed
                                    ? "bg-red-500/20 text-red-400 border border-red-500/30"
                                    : "bg-white/[0.05] text-ink-400 border border-white/[0.08]"
                                }`}
                              >
                                {isProcessing && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping" />}
                                <span>{chunk.status || "PENDING"}</span>
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-8 text-center text-xs text-ink-400 font-mono space-y-3 rounded-lg border border-dashed border-white/[0.08] bg-ink-900/20">
                  <p className="text-white font-semibold">No chunks generated yet for this job.</p>
                  <p className="text-[11px] text-ink-400">
                    Run Node 2 separation to extract audio stems and slice 44.1kHz speech chunks.
                  </p>
                  <button
                    onClick={handleRunNode2}
                    disabled={node2Running}
                    className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs font-mono transition-colors shadow-lg shadow-purple-600/20 cursor-pointer"
                  >
                    ⚡ Run Node 2 Audio Separation Now
                  </button>
                </div>
              )}
            </div>

            {/* Actions Footer */}
            <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
              <button
                onClick={() => handleSourceDownload(inspectJob._id)}
                className="px-4 py-2 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-xs font-mono font-semibold text-white transition-colors cursor-pointer"
              >
                📥 Download Source Video
              </button>
              <button
                onClick={() => setInspectJob(null)}
                className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-mono font-bold text-white transition-colors cursor-pointer"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Dialog for Actions */}
      {actionType && selectedJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4">
          <div className="max-w-md w-full rounded-2xl border border-white/10 bg-ink-900 p-6 space-y-4 shadow-2xl">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              {actionType === "RETRY" && "🔄 Force Retry Job"}
              {actionType === "FAIL" && "⚠️ Mark Job as Failed & Issue Refund"}
              {actionType === "NUKE" && "💥 Poison Pill Nuke & Ban"}
            </h3>

            <p className="text-xs text-ink-400 font-mono">
              Target Job ID: <span className="text-white">{selectedJob._id}</span>
            </p>

            {actionType === "RETRY" && (
              <div className="space-y-3">
                <label className="block text-xs text-ink-300 font-medium">Provider Override:</label>
                <select
                  value={overrideProvider}
                  onChange={(e) => setOverrideProvider(e.target.value)}
                  className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-xs text-white"
                >
                  <option value="runpod">RunPod GPU Serverless</option>
                  <option value="gemini">Gemini Direct 3.1 Pro</option>
                  <option value="fish_audio">Fish Audio Cloud</option>
                </select>
              </div>
            )}

            {actionType === "FAIL" && (
              <div className="space-y-3">
                <label className="block text-xs text-ink-300 font-medium">Failure Reason:</label>
                <input
                  type="text"
                  placeholder="e.g. Unrecoverable audio corruption"
                  value={failReason}
                  onChange={(e) => setFailReason(e.target.value)}
                  className="w-full bg-ink-950 border border-white/10 rounded-lg p-2 text-xs text-white"
                />
              </div>
            )}

            {actionType === "NUKE" && (
              <div className="space-y-3">
                <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-xs text-red-300 font-mono">
                  ⚠️ BLAST RADIUS: This will permanently delete R2 audio/video files, mark the job CANCELLED_PURGED, ban the user, and terminate all active user sessions.
                </div>
                <label className="block text-xs text-ink-300">
                  Type <span className="text-red-400 font-mono font-bold">NUKE {selectedJob._id}</span> to confirm:
                </label>
                <input
                  type="text"
                  value={nukeConfirmText}
                  onChange={(e) => setNukeConfirmText(e.target.value)}
                  placeholder={`NUKE ${selectedJob._id}`}
                  className="w-full bg-ink-950 border border-red-500/30 rounded-lg p-2 text-xs font-mono text-white"
                />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setActionType(null)}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-300 hover:bg-ink-700 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={executeAction}
                disabled={actionLoading}
                className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider text-white ${
                  actionType === "NUKE"
                    ? "bg-red-600 hover:bg-red-500"
                    : "bg-brand-500 hover:bg-brand-400"
                }`}
              >
                {actionLoading ? "Executing..." : "Confirm Action"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default JobOperationsView;
