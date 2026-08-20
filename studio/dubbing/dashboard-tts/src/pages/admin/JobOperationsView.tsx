import React, { useState } from "react";
import { usePaginatedQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useAuth } from "@clerk/clerk-react";
import { downloadJobSource, retryJob, failJob, nukeJob } from "../../api/adminApi";

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
  const [selectedJob, setSelectedJob] = useState<any | null>(null);
  const [actionType, setActionType] = useState<"RETRY" | "FAIL" | "NUKE" | null>(null);
  const [nukeConfirmText, setNukeConfirmText] = useState("");
  const [failReason, setFailReason] = useState("");
  const [overrideProvider, setOverrideProvider] = useState("runpod");
  const [actionLoading, setActionLoading] = useState(false);

  const handleInspect = async (job: any) => {
    setInspectJob(job);
    setInspectVideoUrl(null);
    try {
      const data = await downloadJobSource(getToken, job._id);
      if (data.download_url) {
        setInspectVideoUrl(data.download_url);
      }
    } catch (e) {
      console.warn("Could not fetch video streaming URL for inspection:", e);
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
                <th className="py-3.5 px-4">Language / TTS</th>
                <th className="py-3.5 px-4">API Cost</th>
                <th className="py-3.5 px-4">Created</th>
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
                        onClick={() => handleInspect(job)}
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
                      <div>{job.sourceLang || "ckb"} ➔ {job.targetLang || "ar-IQ"}</div>
                      <div className="text-[10px] text-ink-500">{job.ttsProvider || "fish"}</div>
                    </td>
                    <td className="py-3 px-4 text-purple-300 font-semibold">
                      ${(job.total_cost_usd ?? job.api_cost ?? 0).toFixed(3)}
                    </td>
                    <td className="py-3 px-4 text-ink-500 text-[11px]">
                      {new Date(job.createdAt || job._creationTime).toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right space-x-1.5">
                      <button
                        onClick={() => handleInspect(job)}
                        title="Live Watch & Node 1 Inspection"
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
      {/* LIVE WATCH & NODE 1 INSPECTION MODAL                         */}
      {/* ───────────────────────────────────────────────────────────── */}
      {inspectJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md p-4 overflow-y-auto">
          <div className="max-w-3xl w-full rounded-2xl border border-white/10 bg-[#0c0e14] p-6 space-y-6 shadow-2xl my-8">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="text-xl font-bold text-white tracking-tight">Live Pipeline Watch</span>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    NODE 1: UPLOAD_COMPLETE
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
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              <div className="p-2.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 text-center space-y-1">
                <div className="text-[10px] font-mono font-bold text-emerald-400">NODE 1</div>
                <div className="text-xs font-bold text-white">Direct Upload</div>
                <div className="text-[9px] text-emerald-300/80 font-mono">✅ Ingested</div>
              </div>

              <div className="p-2.5 rounded-xl border border-white/[0.06] bg-ink-900/40 text-center space-y-1 opacity-70">
                <div className="text-[10px] font-mono font-bold text-ink-400">NODE 2</div>
                <div className="text-xs font-bold text-ink-200">Demucs Vocal</div>
                <div className="text-[9px] text-ink-500 font-mono">Separation</div>
              </div>

              <div className="p-2.5 rounded-xl border border-white/[0.06] bg-ink-900/40 text-center space-y-1 opacity-70">
                <div className="text-[10px] font-mono font-bold text-ink-400">NODE 3</div>
                <div className="text-xs font-bold text-ink-200">Kurdish ASR</div>
                <div className="text-[9px] text-ink-500 font-mono">Transcription</div>
              </div>

              <div className="p-2.5 rounded-xl border border-white/[0.06] bg-ink-900/40 text-center space-y-1 opacity-70">
                <div className="text-[10px] font-mono font-bold text-ink-400">NODE 4</div>
                <div className="text-xs font-bold text-ink-200">Iraqi Arabic</div>
                <div className="text-[9px] text-ink-500 font-mono">Localization</div>
              </div>

              <div className="p-2.5 rounded-xl border border-white/[0.06] bg-ink-900/40 text-center space-y-1 opacity-70">
                <div className="text-[10px] font-mono font-bold text-ink-400">NODE 5</div>
                <div className="text-xs font-bold text-ink-200">TTS Synthesis</div>
                <div className="text-[9px] text-ink-500 font-mono">Voice Clone</div>
              </div>

              <div className="p-2.5 rounded-xl border border-white/[0.06] bg-ink-900/40 text-center space-y-1 opacity-70">
                <div className="text-[10px] font-mono font-bold text-ink-400">NODE 6</div>
                <div className="text-xs font-bold text-ink-200">Master Mux</div>
                <div className="text-[9px] text-ink-500 font-mono">Render Output</div>
              </div>
            </div>

            {/* Node 1 Inspection Card: Video Player + FFprobe Metadata Grid */}
            <div className="space-y-4 rounded-xl border border-white/[0.08] bg-ink-950/60 p-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-400 font-mono flex items-center gap-2">
                <span>📹 Node 1 Inspection: Source Video & Extracted FFprobe Metadata</span>
              </h3>

              {/* Video Player */}
              {inspectVideoUrl ? (
                <div className="rounded-xl overflow-hidden border border-white/10 bg-black aspect-video max-h-[280px] w-full flex items-center justify-center">
                  <video
                    src={inspectVideoUrl}
                    controls
                    className="w-full h-full object-contain"
                    preload="metadata"
                  />
                </div>
              ) : (
                <div className="rounded-xl border border-white/[0.06] bg-black/40 p-6 text-center text-xs text-ink-400 font-mono">
                  Loading source video stream from Cloudflare R2...
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
