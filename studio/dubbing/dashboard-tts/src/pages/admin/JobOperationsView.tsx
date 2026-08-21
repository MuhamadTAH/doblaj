import React, { useState } from "react";
import { usePaginatedQuery, useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useAuth } from "@clerk/clerk-react";
import { downloadJobSource, retryJob, failJob, nukeJob, triggerSeparation, signMediaKey } from "../../api/adminApi";

export const JobOperationsView: React.FC = () => {
  const { getToken } = useAuth();
  const [statusFilter, setStatusFilter] = useState("ALL");
  const { results: jobs, status, loadMore, isLoading } = usePaginatedQuery(
    api.adminQuery.listJobsPaginated,
    { statusFilter },
    { initialNumItems: 50 }
  );

  const [inspectJob, setInspectJob] = useState<any | null>(null);
  const [activeNodeTab, setActiveNodeTab] = useState<string>("node1");
  const [inspectVideoUrl, setInspectVideoUrl] = useState<string | null>(null);
  const [activeAudioStemUrl, setActiveAudioStemUrl] = useState<{ key: string; url: string; title: string } | null>(null);
  const [node2Running, setNode2Running] = useState(false);
  const [node2Error, setNode2Error] = useState<string | null>(null);

  const [selectedJob, setSelectedJob] = useState<any | null>(null);
  const [actionType, setActionType] = useState<"RETRY" | "FAIL" | "NUKE" | null>(null);
  const [nukeConfirmText, setNukeConfirmText] = useState("");
  const [failReason, setFailReason] = useState("");
  const [overrideProvider, setOverrideProvider] = useState("runpod");
  const [actionLoading, setActionLoading] = useState(false);

  // Live real-time subscription to chunks for inspected job
  const jobChunks = useQuery(
    api.adminQuery.listChunksForJob,
    inspectJob ? { jobId: inspectJob._id } : "skip"
  ) || [];

  const handleInspect = async (job: any, initialTab: string = "node1") => {
    setInspectJob(job);
    setActiveNodeTab(initialTab);
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

  const handlePlayStem = async (key: string, title: string) => {
    if (!inspectJob || !key) return;
    try {
      const res = await signMediaKey(getToken, inspectJob._id, key);
      if (res.url) {
        setActiveAudioStemUrl({ key, url: res.url, title });
      }
    } catch (e: any) {
      alert(`Could not sign audio stem URL: ${e.message}`);
    }
  };

  const handleRunNode2 = async () => {
    if (!inspectJob) return;
    setNode2Running(true);
    setNode2Error(null);
    try {
      await triggerSeparation(getToken, inspectJob._id);
      alert("Node 2 Audio Separation & Segmentation triggered successfully! Watching chunks stream in real-time.");
    } catch (e: any) {
      setNode2Error(e.message || "Failed to trigger Node 2 separation");
    } finally {
      setNode2Running(false);
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
    } catch (e: any) {
      alert(`Operation failed: ${e.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Header & Filter Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <span>Job Operations Center</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-brand-500/20 text-brand-300 border border-brand-500/30">
              Live Watch Engine
            </span>
          </h1>
          <p className="text-xs text-ink-400">Click any job to open the real-time Live Node Watch and inspect extracted media metadata</p>
        </div>

        <div className="flex items-center gap-1.5 bg-ink-900/60 p-1 rounded-xl border border-white/[0.06] overflow-x-auto">
          {["ALL", "DEAD_LETTER", "QUEUED", "PROCESSING", "FAILED", "COMPLETED"].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
                statusFilter === st
                  ? "bg-brand-500/20 text-brand-300 border border-brand-500/30"
                  : "text-ink-400 hover:text-white"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Jobs Table */}
      <div className="rounded-2xl border border-white/[0.08] bg-ink-900/40 overflow-hidden backdrop-blur-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/[0.08] bg-ink-950/60 text-[11px] uppercase tracking-wider text-ink-400 font-mono">
              <tr>
                <th className="py-3.5 px-4">Job ID / Legacy</th>
                <th className="py-3.5 px-4">Status & Stage</th>
                <th className="py-3.5 px-4">Duration & Res</th>
                <th className="py-3.5 px-4">VAD Chunks</th>
                <th className="py-3.5 px-4">Language / TTS</th>
                <th className="py-3.5 px-4">API Cost</th>
                <th className="py-3.5 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] text-ink-200">
              {jobs.map((job) => {
                const meta = job.mediaMetadata || {};
                return (
                  <tr key={job._id} className="hover:bg-white/[0.02] transition-colors font-mono">
                    <td className="py-3 px-4">
                      <button
                        onClick={() => handleInspect(job, "node1")}
                        className="text-left group flex flex-col hover:opacity-80 transition-opacity"
                      >
                        <div className="font-semibold text-brand-300 group-hover:underline truncate max-w-[140px] flex items-center gap-1.5">
                          <span>👁️</span>
                          <span>{job._id}</span>
                        </div>
                        <div className="text-[10px] text-ink-500 truncate max-w-[140px]">{job.legacyId}</div>
                      </button>
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          job.status === "DEAD_LETTER"
                            ? "bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse"
                            : (job.status || "").toLowerCase() === "completed"
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20"
                            : (job.status || "").toLowerCase() === "failed"
                            ? "bg-red-500/15 text-red-400"
                            : "bg-brand-500/20 text-brand-300 border border-brand-500/30 animate-pulse"
                        }`}
                      >
                        {job.status}
                      </span>
                      {job.failedStep && (
                        <div className="text-[10px] text-red-400/80 mt-1">Step: {job.failedStep}</div>
                      )}
                    </td>
                    <td className="py-3 px-4 text-ink-300">
                      <div className="font-semibold text-white">
                        {meta.durationSec ? `${meta.durationSec}s` : (job.total_duration_sec ? `${job.total_duration_sec}s` : "--")}
                      </div>
                      <div className="text-[10px] text-ink-500">
                        {meta.resolution || (meta.width && meta.height ? `${meta.width}x${meta.height}` : "Pending probe")}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-ink-300">
                      <button
                        onClick={() => handleInspect(job, "node2")}
                        className={`px-2 py-0.5 rounded text-[10px] font-bold hover:underline ${job.chunksCount ? "bg-purple-500/20 text-purple-300 border border-purple-500/30" : "text-ink-500"}`}
                      >
                        {job.chunksCount ? `${job.chunksCount} chunks ➔` : "Inspect Node 2"}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-ink-300">
                      <div>{job.sourceLang || "ckb"} ➔ {job.targetLang || "ar-IQ"}</div>
                      <div className="text-[10px] text-ink-500">{job.ttsProvider || "fish"}</div>
                    </td>
                    <td className="py-3 px-4 text-purple-300 font-semibold">
                      ${(job.total_cost_usd ?? job.api_cost ?? 0).toFixed(3)}
                    </td>
                    <td className="py-3 px-4 text-right space-x-1.5">
                      <button
                        onClick={() => handleInspect(job, "node1")}
                        title="Live Watch & Pipeline Inspector"
                        className="px-2.5 py-1 rounded bg-brand-500/20 hover:bg-brand-500/30 text-brand-300 border border-brand-500/30 text-[11px] font-bold"
                      >
                        👁️ Watch
                      </button>
                      <button
                        onClick={() => handleSourceDownload(job._id)}
                        title="Download Input Video/Audio"
                        className="px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-ink-300 text-[11px]"
                      >
                        📥 Raw
                      </button>
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setActionType("RETRY");
                        }}
                        className="px-2 py-1 rounded bg-brand-500/15 hover:bg-brand-500/25 text-brand-300 text-[11px]"
                      >
                        🔄 Retry
                      </button>
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setActionType("FAIL");
                        }}
                        className="px-2 py-1 rounded bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 text-[11px]"
                      >
                        ⚠️ Fail
                      </button>
                      <button
                        onClick={() => {
                          setSelectedJob(job);
                          setActionType("NUKE");
                        }}
                        className="px-2 py-1 rounded bg-red-500/15 hover:bg-red-500/25 text-red-400 text-[11px] font-bold"
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

        {/* Load More Pagination */}
        {status === "CanLoadMore" && (
          <div className="p-4 border-t border-white/[0.06] text-center">
            <button
              onClick={() => loadMore(50)}
              disabled={isLoading}
              className="px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-xs font-mono font-semibold text-ink-200 transition-colors"
            >
              {isLoading ? "Loading..." : "Load 50 More Jobs"}
            </button>
          </div>
        )}
      </div>

      {/* ───────────────────────────────────────────────────────────── */}
      {/* LIVE WATCH & PIPELINE INSPECTOR MODAL                        */}
      {/* ───────────────────────────────────────────────────────────── */}
      {inspectJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md p-4 overflow-y-auto">
          <div className="max-w-4xl w-full rounded-2xl border border-white/10 bg-[#0c0e14] p-6 space-y-6 shadow-2xl my-8">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="text-xl font-bold text-white tracking-tight">Live Pipeline Watch</span>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    {inspectJob.status}
                  </span>
                </div>
                <p className="text-xs text-ink-400 font-mono mt-1">
                  Job ID: <span className="text-white">{inspectJob._id}</span> · Legacy: <span className="text-ink-300">{inspectJob.legacyId}</span>
                </p>
              </div>

              <button
                onClick={() => setInspectJob(null)}
                className="w-8 h-8 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-ink-400 hover:text-white flex items-center justify-center text-sm font-bold transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Pipeline Stage Stepper */}
            <div className="grid grid-cols-2 sm:grid-cols-6 gap-2">
              <button
                type="button"
                onClick={() => setActiveNodeTab("node1")}
                className={`p-2.5 rounded-xl border text-center space-y-1 transition-all cursor-pointer ${
                  activeNodeTab === "node1"
                    ? "border-brand-500/80 bg-brand-500/25 ring-2 ring-brand-500/40 shadow-lg shadow-brand-500/20"
                    : "border-white/[0.08] bg-ink-900/40 hover:bg-white/[0.06]"
                }`}
              >
                <div className="text-[10px] font-mono font-bold text-emerald-400">NODE 1</div>
                <div className="text-xs font-bold text-white">Direct Upload</div>
                <div className="text-[9px] text-emerald-300/80 font-mono">✅ Ingested</div>
              </button>

              <button
                type="button"
                onClick={() => setActiveNodeTab("node2")}
                className={`p-2.5 rounded-xl border text-center space-y-1 transition-all cursor-pointer ${
                  activeNodeTab === "node2"
                    ? "border-purple-500/80 bg-purple-500/25 ring-2 ring-purple-500/40 shadow-lg shadow-purple-500/20"
                    : jobChunks.length > 0
                    ? "border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20"
                    : "border-white/[0.08] bg-ink-900/40 hover:bg-white/[0.06]"
                }`}
              >
                <div className="text-[10px] font-mono font-bold text-purple-400">NODE 2</div>
                <div className="text-xs font-bold text-white">Demucs & VAD</div>
                <div className="text-[9px] text-purple-300/80 font-mono">
                  {jobChunks.length > 0 ? `✅ ${jobChunks.length} Chunks` : "Separation"}
                </div>
              </button>

              <button
                type="button"
                onClick={() => setActiveNodeTab("node3")}
                className={`p-2.5 rounded-xl border text-center space-y-1 transition-all cursor-pointer ${
                  activeNodeTab === "node3"
                    ? "border-blue-500/80 bg-blue-500/25 ring-2 ring-blue-500/40"
                    : "border-white/[0.08] bg-ink-900/40 hover:bg-white/[0.06]"
                }`}
              >
                <div className="text-[10px] font-mono font-bold text-blue-400">NODE 3</div>
                <div className="text-xs font-bold text-ink-200">Kurdish ASR</div>
                <div className="text-[9px] text-ink-500 font-mono">Dual-Pass STT</div>
              </button>

              <button
                type="button"
                onClick={() => setActiveNodeTab("node4")}
                className={`p-2.5 rounded-xl border text-center space-y-1 transition-all cursor-pointer ${
                  activeNodeTab === "node4"
                    ? "border-amber-500/80 bg-amber-500/25 ring-2 ring-amber-500/40"
                    : "border-white/[0.08] bg-ink-900/40 hover:bg-white/[0.06]"
                }`}
              >
                <div className="text-[10px] font-mono font-bold text-amber-400">NODE 4</div>
                <div className="text-xs font-bold text-ink-200">Iraqi Arabic</div>
                <div className="text-[9px] text-ink-500 font-mono">Localization</div>
              </button>

              <button
                type="button"
                onClick={() => setActiveNodeTab("node5")}
                className={`p-2.5 rounded-xl border text-center space-y-1 transition-all cursor-pointer ${
                  activeNodeTab === "node5"
                    ? "border-cyan-500/80 bg-cyan-500/25 ring-2 ring-cyan-500/40"
                    : "border-white/[0.08] bg-ink-900/40 hover:bg-white/[0.06]"
                }`}
              >
                <div className="text-[10px] font-mono font-bold text-cyan-400">NODE 5</div>
                <div className="text-xs font-bold text-ink-200">TTS Synthesis</div>
                <div className="text-[9px] text-ink-500 font-mono">Voice Clone</div>
              </button>

              <button
                type="button"
                onClick={() => setActiveNodeTab("node6")}
                className={`p-2.5 rounded-xl border text-center space-y-1 transition-all cursor-pointer ${
                  activeNodeTab === "node6"
                    ? "border-pink-500/80 bg-pink-500/25 ring-2 ring-pink-500/40"
                    : "border-white/[0.08] bg-ink-900/40 hover:bg-white/[0.06]"
                }`}
              >
                <div className="text-[10px] font-mono font-bold text-pink-400">NODE 6</div>
                <div className="text-xs font-bold text-ink-200">Master Mux</div>
                <div className="text-[9px] text-ink-500 font-mono">Final Output</div>
              </button>
            </div>

            {/* TAB 1: NODE 1 INSPECTION */}
            {activeNodeTab === "node1" && (
              <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono flex items-center gap-2">
                  <span>📹 Node 1 Inspection: Source Video & Extracted FFprobe Metadata</span>
                </h3>

                {/* Video Player */}
                {inspectVideoUrl ? (
                  <div className="rounded-xl overflow-hidden border border-white/10 bg-black aspect-video max-h-[300px] w-full flex items-center justify-center relative">
                    <video
                      src={inspectVideoUrl}
                      controls
                      playsInline
                      className="w-full h-full object-contain"
                      preload="auto"
                    />
                  </div>
                ) : (
                  <div className="rounded-xl border border-white/[0.06] bg-black/40 p-6 text-center text-xs text-ink-400 font-mono">
                    Loading signed streaming URL from Cloudflare R2...
                  </div>
                )}

                {/* Extracted Metadata Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 font-mono text-xs">
                  <div className="p-3 rounded-lg border border-white/[0.06] bg-ink-900/50">
                    <span className="text-[10px] text-ink-500 uppercase">Duration</span>
                    <div className="text-sm font-bold text-white mt-0.5">
                      {inspectJob.mediaMetadata?.durationSec
                        ? `${inspectJob.mediaMetadata.durationSec}s`
                        : (inspectJob.total_duration_sec ? `${inspectJob.total_duration_sec}s` : "0.0s")}
                    </div>
                    <span className="text-[10px] text-ink-500">
                      {inspectJob.mediaMetadata?.durationMs ? `${inspectJob.mediaMetadata.durationMs} ms` : "--"}
                    </span>
                  </div>

                  <div className="p-3 rounded-lg border border-white/[0.06] bg-ink-900/50">
                    <span className="text-[10px] text-ink-500 uppercase">Resolution & FPS</span>
                    <div className="text-sm font-bold text-white mt-0.5">
                      {inspectJob.mediaMetadata?.resolution || "1920x1080"}
                    </div>
                    <span className="text-[10px] text-ink-500">
                      {inspectJob.mediaMetadata?.fps ? `${inspectJob.mediaMetadata.fps} FPS` : "30.0 FPS"}
                    </span>
                  </div>

                  <div className="p-3 rounded-lg border border-white/[0.06] bg-ink-900/50">
                    <span className="text-[10px] text-ink-500 uppercase">Codecs</span>
                    <div className="text-sm font-bold text-brand-300 mt-0.5 truncate">
                      {inspectJob.mediaMetadata?.videoCodec || "H.264"} / {inspectJob.mediaMetadata?.audioCodec || "AAC"}
                    </div>
                    <span className="text-[10px] text-ink-500">Video / Audio</span>
                  </div>

                  <div className="p-3 rounded-lg border border-white/[0.06] bg-ink-900/50">
                    <span className="text-[10px] text-ink-500 uppercase">Audio Sample Rate</span>
                    <div className="text-sm font-bold text-emerald-400 mt-0.5">
                      {inspectJob.mediaMetadata?.audioSampleRate
                        ? `${inspectJob.mediaMetadata.audioSampleRate} Hz`
                        : "48,000 Hz"}
                    </div>
                    <span className="text-[10px] text-ink-500">
                      {inspectJob.mediaMetadata?.audioChannels === 2 ? "Stereo (2 ch)" : "Mono (1 ch)"}
                    </span>
                  </div>

                  <div className="p-3 rounded-lg border border-white/[0.06] bg-ink-900/50 col-span-2 sm:col-span-4">
                    <span className="text-[10px] text-ink-500 uppercase">Cloudflare R2 Storage Key</span>
                    <div className="text-xs font-bold text-white mt-0.5 truncate select-all">
                      {inspectJob.sourceVideoR2Key || "dubbing/.../source.mp4"}
                    </div>
                    <div className="flex items-center gap-4 text-[10px] text-ink-400 mt-1">
                      <span>Size: {inspectJob.mediaMetadata?.fileSizeBytes ? `${(inspectJob.mediaMetadata.fileSizeBytes / (1024 * 1024)).toFixed(2)} MB` : "--"}</span>
                      <span>Bitrate: {inspectJob.mediaMetadata?.bitrateKbps ? `${inspectJob.mediaMetadata.bitrateKbps} kbps` : "--"}</span>
                      <span>Container: {inspectJob.mediaMetadata?.formatName || "mp4"}</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: NODE 2 DEMUCS & SILERO VAD INSPECTION */}
            {activeNodeTab === "node2" && (
              <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-purple-400 font-mono flex items-center gap-2">
                    <span>🎛️ Node 2 Inspection: Demucs Vocal Isolation & Silero VAD Chunks</span>
                  </h3>
                  
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleRunNode2}
                      disabled={node2Running}
                      className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-mono text-xs font-bold transition-colors flex items-center gap-1.5 shadow-lg shadow-purple-600/20"
                    >
                      <span>⚡</span>
                      <span>{node2Running ? "Separating Audio..." : "Run Node 2 Separation"}</span>
                    </button>
                    <span className="px-2.5 py-1 rounded-lg text-[10px] font-mono font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                      {jobChunks.length} Chunks Generated
                    </span>
                  </div>
                </div>

                {node2Error && (
                  <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs font-mono text-red-400">
                    ⚠️ Error: {node2Error}
                  </div>
                )}

                {/* Stems Overview with Direct Audio Playback */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 font-mono text-xs">
                  <div className="p-3.5 rounded-lg border border-white/[0.06] bg-ink-900/50 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-ink-400 uppercase font-bold">🎵 Background Instrumental / SFX Stem</span>
                      <span className="text-[10px] text-emerald-400 font-bold">44.1kHz Stereo</span>
                    </div>
                    <div className="text-xs font-semibold text-white truncate">
                      {inspectJob.bgAudioR2Key || `dubbing/.../stems/no_vocals.wav`}
                    </div>
                    <button
                      onClick={() => handlePlayStem(inspectJob.bgAudioR2Key || `dubbing/${inspectJob.workspaceId || "ws"}/${inspectJob._id}/stems/no_vocals.wav`, "Background Stem")}
                      className="px-2.5 py-1 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 text-[11px] font-bold flex items-center gap-1.5"
                    >
                      <span>▶️</span>
                      <span>Play Background Stem</span>
                    </button>
                  </div>

                  <div className="p-3.5 rounded-lg border border-white/[0.06] bg-ink-900/50 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-ink-400 uppercase font-bold">🗣️ Isolated High-Res Vocals Stem</span>
                      <span className="text-[10px] text-purple-400 font-bold">44.1kHz Master</span>
                    </div>
                    <div className="text-xs font-semibold text-white truncate">
                      {inspectJob.isolatedVocalsR2Key || `dubbing/.../stems/vocals.wav`}
                    </div>
                    <button
                      onClick={() => handlePlayStem(inspectJob.isolatedVocalsR2Key || `dubbing/${inspectJob.workspaceId || "ws"}/${inspectJob._id}/stems/vocals.wav`, "Vocals Stem")}
                      className="px-2.5 py-1 rounded bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/30 text-[11px] font-bold flex items-center gap-1.5"
                    >
                      <span>▶️</span>
                      <span>Play Vocals Stem</span>
                    </button>
                  </div>
                </div>

                {/* Active Stem Audio Player Bar */}
                {activeAudioStemUrl && (
                  <div className="p-3 rounded-xl border border-brand-500/30 bg-brand-500/10 space-y-1.5">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-white font-bold">Playing: {activeAudioStemUrl.title}</span>
                      <button
                        onClick={() => setActiveAudioStemUrl(null)}
                        className="text-ink-400 hover:text-white text-[10px]"
                      >
                        ✕ Close Player
                      </button>
                    </div>
                    <audio
                      src={activeAudioStemUrl.url}
                      controls
                      autoPlay
                      className="w-full h-8"
                    />
                  </div>
                )}

                {/* Silero VAD Chunks Table */}
                <div className="rounded-xl border border-white/[0.06] overflow-hidden bg-ink-900/30">
                  <div className="p-3 border-b border-white/[0.06] bg-ink-950/80 text-[11px] font-mono font-bold text-ink-300 flex items-center justify-between">
                    <span>Silero VAD Speech Boundaries & Sliced 44.1kHz Vocal Chunks</span>
                    <span className="text-[10px] text-ink-500">Status: PENDING_ASR</span>
                  </div>

                  {jobChunks.length > 0 ? (
                    <div className="max-h-[300px] overflow-y-auto divide-y divide-white/[0.04] text-xs font-mono">
                      {jobChunks.map((chunk: any) => (
                        <div key={chunk._id} className="p-3 flex items-center justify-between hover:bg-white/[0.02] transition-colors">
                          <div className="flex items-center gap-3">
                            <span className="px-2 py-0.5 rounded bg-brand-500/20 text-brand-300 font-bold text-[10px]">
                              #{chunk.chunkIndex + 1}
                            </span>
                            <div>
                              <div className="text-white font-semibold flex items-center gap-2">
                                <span>{chunk.startTime.toFixed(2)}s ➔ {chunk.endTime.toFixed(2)}s</span>
                                <span className="text-[10px] text-purple-300">({chunk.speechDuration ? chunk.speechDuration.toFixed(2) : (chunk.endTime - chunk.startTime).toFixed(2)}s)</span>
                              </div>
                              <div className="text-[10px] text-ink-500 truncate max-w-[280px]">
                                {chunk.kurdish_raw_audio_url || "R2 chunk key"}
                              </div>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            {chunk.kurdish_raw_audio_url && (
                              <button
                                onClick={() => handlePlayStem(chunk.kurdish_raw_audio_url, `Chunk #${chunk.chunkIndex + 1}`)}
                                className="px-2 py-1 rounded bg-white/[0.06] hover:bg-white/[0.12] text-[11px] text-ink-200 font-bold"
                              >
                                ▶️ Play
                              </button>
                            )}
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/20">
                              {chunk.status || "PENDING_ASR"}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-8 text-center text-xs text-ink-400 font-mono space-y-3">
                      <p className="text-white font-semibold">No VAD chunks generated yet for this job.</p>
                      <p className="text-[11px] text-ink-400">Click the button below to extract audio and run Demucs + Silero VAD segmentation:</p>
                      <button
                        onClick={handleRunNode2}
                        disabled={node2Running}
                        className="px-4 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs font-mono transition-colors shadow-lg shadow-purple-600/20"
                      >
                        ⚡ Run Node 2 Audio Separation Now
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 3: NODE 3 KURDISH ASR */}
            {activeNodeTab === "node3" && (
              <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-6 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-blue-400 flex items-center gap-2">
                    <span>🎙️ Node 3: Kurdish Sorani Speech-to-Text (ASR) Engine</span>
                  </h3>
                  <span className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    Dual-Pass Global Reference
                  </span>
                </div>
                <p className="text-ink-300 leading-relaxed">
                  Node 3 transcribes each segmented 44.1kHz vocal chunk into accurate Kurdish Sorani text using Unicode normalization and dual-pass context anchoring.
                </p>
                <div className="p-4 rounded-xl border border-white/[0.06] bg-ink-900/40 text-ink-400">
                  Ready to deploy Node 3 ASR pipeline.
                </div>
              </div>
            )}

            {/* TAB 4: NODE 4 IRAQI TRANSLATION */}
            {activeNodeTab === "node4" && (
              <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-6 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                    <span>💬 Node 4: Iraqi Arabic (العامية العراقية) Localization Engine</span>
                  </h3>
                  <span className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    Phonetic Syllable Matching
                  </span>
                </div>
                <p className="text-ink-300 leading-relaxed">
                  Node 4 converts Kurdish Sorani transcriptions into natural spoken Iraqi Arabic with strict syllable budgets and phonetic number expansion for lip-sync alignment.
                </p>
              </div>
            )}

            {/* TAB 5: NODE 5 TTS SYNTHESIS */}
            {activeNodeTab === "node5" && (
              <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-6 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-2">
                    <span>🔊 Node 5: TTS Voice Synthesis & Cadence Alignment</span>
                  </h3>
                  <span className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                    Fish Audio / Clone
                  </span>
                </div>
                <p className="text-ink-300 leading-relaxed">
                  Node 5 generates clone voice audio in Iraqi Arabic and warps playback to fit the exact millisecond duration of each chunk.
                </p>
              </div>
            )}

            {/* TAB 6: NODE 6 MASTER MUXING */}
            {activeNodeTab === "node6" && (
              <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-6 font-mono text-xs">
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-pink-400 flex items-center gap-2">
                    <span>🎬 Node 6: Master Muxing & Video Export</span>
                  </h3>
                  <span className="px-2.5 py-0.5 rounded text-[10px] font-bold bg-pink-500/20 text-pink-300 border border-pink-500/30">
                    Dynamic Audio Ducking
                  </span>
                </div>
                <p className="text-ink-300 leading-relaxed">
                  Node 6 mixes the new Iraqi vocal track over the isolated background instrumental track (<span className="text-emerald-300 font-bold">no_vocals.wav</span>) and muxes with the original video container.
                </p>
              </div>
            )}

            {/* Actions Footer */}
            <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
              <button
                onClick={() => handleSourceDownload(inspectJob._id)}
                className="px-4 py-2 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-xs font-mono font-semibold text-white transition-colors"
              >
                📥 Download Source File
              </button>
              <button
                onClick={() => setInspectJob(null)}
                className="px-4 py-2 rounded-lg bg-brand-500 hover:bg-brand-400 text-xs font-mono font-bold text-white transition-colors"
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
